# 错误经验库

> `2.3.0` | 项目：SUSFS v1.5.5 → v2.2.0 port (KSUN-legacy)
> 每次修复后在此新增条目。通用经验加 `[cross-project]` 标签。

## E001：SYS_SECCOMP 阻止 KSU fd 安装导致设置页开关项缺失

**现象**：管理器 App 设置页的 KernelFeaturesCard 中，传统 SU 命令支持、内核处理卸载模块、SU 日志、ADB Root、Hide SELinux modification、AVC 日志伪装 共 6 个开关项不显示。logcat 出现 `F/DEBUG: signal 31 (SIGSYS) Cause: seccomp prevented call to disallowed arm64 system call 142`。

**根因**：管理器 App 嵌入的 `libksud.so` 在 `init_driver_fd()` 中先尝试 `scan_driver_fd()`（扫描 `/proc/self/fd` 寻找 `[ksu_driver]` 匿名 inode），失败后回退到 `syscall(SYS_reboot, KSU_INSTALL_MAGIC1, KSU_INSTALL_MAGIC2, 0, &fd)`。Android 的 seccomp 白名单不允许 `__NR_reboot=142`，导致 SIGSYS 杀进程。所有 KSU supercall 无法执行，`ksud feature check <feature>` 返回空字符串，UI 判断为 `unsupported` 隐藏开关。

**修复**：在 `supercall.c` 中添加 `secure_computing` kprobe。当捕获到 `__NR_reboot` 且参数为 KSU 魔数时，跳过 seccomp 检查（return 1）。另添加始终注册的 `__arm64_sys_reboot` kprobe（不依赖 `KSU_KPROBES_HOOK`），在绕过 seccomp 后安装 KSU driver fd 并返回 fd 号。

**教训**：
- 不能假设 Android 进程可以调用 `reboot` 等被 seccomp 限制的 syscall
- kprobe 在 `secure_computing` 上可以绕过 seccomp，且只影响极窄的条件（`__NR_reboot + 0xDEADBEEF + 0xCAFEBABE`）
- `PT_REGS_SYSCALL_PARM4` 在 arm64 arch.h 中有定义，不能用 `PT_REGS_PARM4`（未定义）

**锚点**：`drivers/kernelsu/supercall/supercall.c` — `seccomp_bypass_pre()` + `ksu_reboot_kprobe_pre()`

**标签**：cross-project

---

## E002：`__ksu_is_allow_uid_for_current(0)` 返回 `is_ksu_domain()` 导致 adb root 下 grant_root 被拒

**现象**：冷启动后 `ksud debug su` 返回 `Error: Operation not permitted (os error 1)`。strace 显示 `ioctl(5, KSU_IOCTL_GRANT_ROOT) = -1 EPERM`。`adb root` 后 UID=0 但 `allowed_for_su()` 返回 false。

**根因**：`kernel/policy/allowlist.c:358-362` 中 `__ksu_is_allow_uid_for_current(0)` 的实现为：
```c
if (unlikely(uid == 0)) {
    return is_ksu_domain();  // 要求进程必须是 u:r:ksu:s0 域
}
```
`adb root` 后进程的 SELinux context 通过 `escape_to_root_for_adb_root()` 设置为 `u:r:su:s0`，而非 `u:r:ksu:s0`。`is_ksu_domain()` 检查 `cached_su_sid` 与当前 SID 是否匹配，由于 context 为 `su` 域而非 `ksu` 域，返回 false → `allowed_for_su()` 返回 false → EPERM。

**修复**：UID 0 时直接 `return true`。UID 0 已经是 root，不存在权限提升风险。`ksud debug su` 从 UID 0 调用 grant_root 应允许。

**教训**：
- `uid == 0` 的快捷路径应直接放行，不应附加 SELinux context 检查
- 不要假设 `adb root` 后进程的 SELinux context 一定是 `ksu` 域
- 根因分析必须读源码，不能仅靠日志推测

**锚点**：`drivers/kernelsu/policy/allowlist.c` — `__ksu_is_allow_uid_for_current()`

**标签**：cross-project

---

## E003：post-fs-data exec 包含 SELinux context 导致 ksud 守护进程无法启动

**现象**：`/system/bin/su` 不存在；`ksud` 系统守护进程不在进程列表；`rootAvailable()` → `Shell.isAppGrantedRoot()` 因 `su -c id` 找不到可执行文件永远返回 false。底部导航栏只有首页和设置两个 Tab（超级用户和模块被 `rootRequired=true` 过滤）。

**根因**：`KERNEL_SU_RC` 中 `on post-fs-data` 的 exec 命令包含 `exec u:r:ksu:s0 root -- ksud post-fs-data`。但 ksu SELinux 域由 `apply_kernelsu_rules()` 在延迟 workqueue（~33s）中创建，而 `post-fs-data` 事件在 ~10-15s 触发。此时 `u:r:ksu:s0` 域不存在，init 无法执行该 exec，ksud 守护进程从未启动。`su` 软链接依赖 `ksud install` 命令安装，ksud 未启动故 `su` 不存在。

**修复**：将 `KERNEL_SU_RC` 中 post-fs-data 的 exec 改为 `exec root -- ksud post-fs-data`（无 SELinux context）。init 进程的 `u:r:init:s0` 域已有 KSU 添加的 `allow init adb_data_file:file *` 规则，有足够权限。

**教训**：
- init.rc 的 `exec` 命令中的 SELinux context 在触发时必须已存在，否则 exec 静默失败
- 延迟创建的 SELinux 域不能用于 early boot 的 init.rc 触发器
- `rootAvailable()` 失败不一定是因为 grant_root 被拒，也可能是 `su` 二进制不存在

**锚点**：`drivers/kernelsu/runtime/ksud_integration.c` — `KERNEL_SU_RC` 字符串中的 post-fs-data exec

**标签**：cross-project

---

## E004：`track_throne()` 在内置路径从未被调用导致管理器 UID 未设置

**现象**：冷启动后 `allowed_for_su()` 中 `is_manager()` 返回 false（`ksu_manager_appid = KSU_INVALID_APPID`）。只有在 `on_boot_completed` 触发后才被设置。管理器 App 启动时管理器 UID 未被识别，`fullFeatured` 为 false。

**根因**：`kernel/core/init.c` 的内置（built-in）路径只调用了 `ksu_throne_tracker_init()`（清空哈希列表），从未调用 `track_throne()` 来扫描 `/data/system/packages.list` 发现管理器 App 的 UID。`track_throne()` 仅在 late-load 路径（`#ifdef MODULE`）中被调用。内置路径中管理器 UID 只有在 `on_boot_completed()` 触发时才通过 `boot_event.c` 的 `track_throne(true)` 设置，此时 App 已经启动完毕并显示了 "grant root failed" 错误。

**修复**：在延迟 workqueue 回调中添加 `track_throne(false)`，并添加最多 5 次重试（每次间隔 2 秒）以应对 `packages.list` 被 Package Manager 锁定的情况。同时添加 `#include "manager/manager_identity.h"` 和 `#include <linux/delay.h>`。

**教训**：
- 内置路径和 LKM 路径的初始化流程不同，`track_throne()` 在 LKM 路径中被调用不意味着在内置路径中也被调用
- 需要验证每个代码路径的执行分支，不能基于一个分支的假设推断另一个
- 系统服务的文件锁（如 `packages.list`）会导致 `track_throne()` 返回而不做任何事，需要重试机制

**锚点**：`drivers/kernelsu/core/init.c` — `ksu_delayed_selinux_init()`（workqueue 回调）

**标签**：cross-project

---

### E005：SUSFS open_redirect 重定向 procfs 路径导致银行 App "网络不给力"

**现象**：农业银行 App（`com.android.bankabc`）能进入主界面（native 页面正常），但点击任何功能页（走 UC WebView/H5 容器）都显示"网络不给力，请稍后再试"。网络连通性正常（ping/DNS/HTTPS 全部通过），App 的 TCP 连接均为 ESTABLISHED。

**根因**：commit `91ced34` 在 `susfs_restore_boot()` 添加 open_redirect，把 `/proc/net/unix`、`/proc/self/mounts`、`/proc/version`、`/proc/self/attr/current` 重定向到 `/dev/null`（uid_scheme=2，对所有非 KSU 域进程生效）。银行 App 是 untrusted_app_30（非 KSU 域），UC WebView/H5 初始化读 `/proc/net/unix` 检查 socket、读 `/proc/self/mounts` 判断网络环境，拿到空数据 → 判定"网络异常" → 显示"网络不给力"。主界面 native 不走 H5 网络层所以正常。

**修复**：回滚到 #670（commit `6391554`），`susfs_restore_boot()` 的 sus_path 为干净最小集，不含 open_redirect 调用；VFS 钩子在无 `INODE_STATE_OPEN_REDIRECT` 标记时休眠，对普通 App 无副作用。已加防回归注释。

> ⚠️ 补充（E006）：移除 open_redirect 后问题依旧。进一步验证（原厂内核 + KSU 内核均复现）确认**真正根因是 SELinux execmod denial**（见 E006）。open_redirect 是次要因素，但修复它仍是正确的。

**教训**：不要对 `/proc/net/unix`、`/proc/self/mounts` 等"App 正常运行也读取"的系统状态文件用 open_redirect 重定向到 /dev/null；open_redirect 只适合隐藏检测特征文件（su 二进制、ksu 目录）。若 App "能进主界面但功能页报错"，优先怀疑 H5/WebView 依赖的系统文件被重定向，而非 SELinux 规则缺失。`dmesg | grep open_redirect` 可核对实际注册规则（设备内核可能与工作区代码不一致）。

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪"。**标签**：cross-project

---

### E006：SELinux execmod denial 导致银行 App SecNeo 加固壳失败显示"网络不给力"

**现象**：农业银行 App（`com.android.bankabc`）能进入主界面，但点击功能页报"网络不给力"。**在原厂内核（无 KSU）、KSU 内核（完整属性伪装）、关闭 USB 调试、禁用 ReZygisk 的全部组合下均复现**。抓包显示 App 建立 TLS 连接收到服务器证书后**主动 RST 断开**。dmesg 持续出现：
```
avc: denied { execmod } for comm="android.bankabc"
  path="/apex/com.android.runtime/lib64/bionic/libc.so"
  tcontext=u:object_r:system_lib_file:s0 tclass=file
avc: denied { execmod } for comm="android.bankabc"
  path="/apex/com.android.runtime/bin/linker64"
  tcontext=u:object_r:system_linker_exec:s0 tclass=file
```

**根因**：银行 App 使用 SecNeo（梆梆）加固壳（`com/secneo/apkwrapper`），加固壳需要在内存中修改 libc.so/linker64 代码段（内存加固/反调试补丁），需要 SELinux `execmod` 权限。Android 默认策略禁止 untrusted_app 对 system_lib_file/system_linker_exec 执行 execmod → 加固壳初始化失败 → App 业务功能无法执行 → 显示伪造的"网络不给力"。**此问题与内核/KSU/伪装无关**（原厂内核同样复现），是 Android SELinux 策略本身对 untrusted_app 的限制。

**修复**：在 `inject-selinux-domain-init.py` 的 `fix_rules()` 中为 untrusted_app/untrusted_app_30 添加 execmod + proc_net + userdebug_or_eng_prop + proc_version + proc_pid_max + odsign_prop 共 32 条规则（与回滚前 1891b8f 一致）。这些规则经 `apply_kernelsu_rules()` 在 SELinux 策略加载时注入。

**教训**：
- **"网络不给力"类错误优先查 dmesg 的 avc denial**，而非假设网络故障或 root 检测——抓包确认 App 主动 RST 断开是"应用层拒绝"，avc execmod denial 是直接原因
- 加固类银行 App（SecNeo/梆梆）需要 execmod 修改 libc/linker64，这是**功能硬需求**，不是 root 检测点
- 排查顺序：① 原厂内核对照（排除内核因素）② 抓包看是否主动断开 ③ dmesg 查 avc denial ④ 查 execmod/属性类 denial
- 回滚前的 execmod 规则当时"看似无效"可能是其他问题掩盖，需用 dmesg 验证规则是否真正进策略

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E007：SUSFS 符号隐藏不完整泄漏 kallsyms + 银行 App "网络不给力"根因是设备时间错误

**现象**：① `/proc/kallsyms` 中泄漏 `do_susfs_ioctl`、`__ksymtab_susfs_*`、`__kstrtab_susfs_*` 等 15 个 SUSFS 符号（kptr_restrict=2 时地址为 0 但符号名可见）。② 农业银行 App 二级页面报"网络不给力"。

**根因**：① `50_add_susfs_in_kernel-4.19.patch` 的符号隐藏规则 `strncmp(iter->name, "susfs_", 6)` 只匹配"以 susfs_ 开头"的符号，漏掉了 `__ksymtab_susfs_*`/`__kstrtab_susfs_*`（导出符号表，前缀为 __ksymtab_/__kstrtab_）和 `do_susfs_ioctl`。② 银行 App "网络不给力"真正根因是**设备系统时间错误（RTC 慢约10小时）**：App 请求 `mgw.htm` 用设备时间生成签名，服务器校验 `Result-Status: 7003 验签-时效性失败`，App 显示"网络不给力"。此问题与内核/KSU/伪装无关（原厂内核同样复现），修正时间后立即恢复正常。

**修复**：① 隐藏规则改为 `strstr(iter->name, "susfs")` + `strstr(iter->name, "kernelsu")`，覆盖全部含 susfs/kernelsu 子串的符号（含 __ksymtab/__kstrtab/do_susfs_ioctl）。② 时间问题：用户空间修正 RTC（`hwclock -w`）+ 配置 NTP（`settings put global ntp_server ntp.aliyun.com`），**非内核问题，无需固化到内核**。

**教训**：
- 字符串前缀匹配（strncmp）会漏掉带公共前缀的导出符号（`__ksymtab_susfs_*`），应使用 `strstr`（子串匹配）做符号隐藏
- 排查"网络不给力"类问题，若所有本地伪装均无效且原厂内核同样复现，优先怀疑**系统时间/服务器签名时效性**，而非环境检测——通过 mitmproxy 解密看响应头 `Result-Status` 可快速定位
- 银行 App 的 `mgw.htm` 网关返回 `Result-Status: 7003 验签-时效性失败` 是时间不同步的明确信号
- 设备 RTC 时间错误 + `CONFIG_RTC_HCTOSYS=y`（开机 RTC→系统）会导致开机后时间错误，需确保 NTP 配置正确

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E008：SUSFS 属性伪装残留字节导致 Hunter 检测 "Find Prop Modify Mark"

**现象**：Hunter 环境检测工具报告 2 项 `Find Prop Modify Mark (Abnormal prop remains for: ro.build.type)`。

**根因**：`kernel-patches/properties.c` 的 `property_set()` 写属性时**只写新值 + NUL 终止符，未清空整个 value[PROP_VALUE_MAX] 区**。当新值比旧值短时（如 `ro.build.type` 从 `userdebug` 改为 `user`，或 `ro.lineage.*` 清空为空字符串），value 区在 NUL 之后**残留旧值字节**（实测 `user\x00ebug\x00`，残留 `debug`）。bionic 的 `__system_property_update()` 会先 memset 整个 value 区再写入，因此 SUSFS 的残留被 Hunter 识别为 "Abnormal prop remains"（属性残留）。

**修复**：`property_set()` 写入前先**清零整个 value[PROP_VALUE_MAX] 区**（循环 `kernel_write(fp, &zero, 1, &pos)` 92 次），再写新值 + NUL。这样任何属性（改短/清空）都不会残留旧字节。

**教训**：
- 内核直接改属性共享内存时，必须模拟 bionic 的完整写入协议（先 memset value 区再写），不能只写新值
- 残留字节检测是安全工具（Hunter）识别属性伪装的常见手段——值变短时必须清除 NUL 后的旧数据
- 验证方法：`dd if=/dev/__properties__/u:object_r:build_prop:s0 bs=1 count=4096` 检查 value 区 NUL 后是否全零
- 注意：手动 resetprop 可临时清除残留，但重启后 SUSFS boot restore 会重新写入（带残留），必须修复内核源码

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E009：SUSFS 属性变体不一致 + uname 伪装值异常导致 Hunter 检测 "设备机型&ROM可能被修改"

**现象**：Hunter 检测报告 `设备机型&ROM可能被修改`。DeviceBaseInfo 显示 uname 为 `Linux localhost 4.19.304 Default/4.19 aarch64 Toybox`（version 字段 `Default/4.19` 明显是伪造值）。检查属性区发现大量属性变体不一致：`ro.build.type=user` 但 `ro.system.build.type=userdebug`、`ro.product.build.type=userdebug`、`ro.odm.build.type=userdebug` 等；`ro.product.model=KB2000` 但 `ro.product.system.model=KB2005` 等。

**根因**：① SUSFS `susfs_restore_properties()` 只伪装了 `ro.build.type`/`ro.build.flavor` 等基础属性，遗漏了 `ro.product.build.*`、`ro.system.build.*`、`ro.vendor.build.*`、`ro.odm.build.type` 等分区属性变体——它们保留了真实的 `userdebug`/`KB2005`，与伪装值矛盾，Hunter 检测到属性不一致。② boot restore 的 `susfs_set_uname_kernel("4.19.304", "Default/4.19")` 把 uname version 伪装成 `Default/4.19`，这不是真实内核 version 格式（应为 `#1 SMP PREEMPT ...`），Hunter 一眼识别为伪造。

**修复**：① 在 `susfs_restore_properties()` 补充伪装 `ro.product.build.type=user`、`ro.product.build.tags=release-keys`、`ro.product.build.fingerprint`（与 ro.build.* 一致）。② uname version 改为合理的原厂格式 `#1 SMP PREEMPT Fri Feb 9 00:58:10 UTC 2024`（与原厂 LineageOS 内核 /proc/version 的 version 段一致）。

**教训**：
- Android 分区属性（`ro.system.*`、`ro.vendor.*`、`ro.product.*`、`ro.odm.*`）是属性伪装的常见遗漏点——伪装 `ro.build.*` 时必须同步所有分区变体，否则属性间矛盾会被检测
- uname 伪装的 version 字段不能用 `Default/4.19` 这种占位符，必须是真实内核 version 格式（`#1 SMP PREEMPT <date>`），否则一目了然
- 验证属性一致性：`getprop | grep -E "build.type|\.model\]"` 检查所有变体
- `ro.product.build.*`/`ro.product.system.model` 在 build_prop context 可被 SUSFS 定位；`ro.system.build.type` 等动态属性需用户空间 resetprop（ksud susfs_config.json）

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E010：SUSFS `susfs_spoof_uname` 的 `spin_is_locked` 检查导致 uname 伪装失效

**现象**：boot restore 的 `susfs_set_uname_kernel("4.19.304", "#1 SMP PREEMPT...")` 成功写入（dmesg 确认），ksud `set-uname` 也返回 0，但 `uname -v` 仍显示真实内核版本（`#2 SMP PREEMPT Sat Aug 1...`），uname 伪装完全不生效。

**根因**：`susfs_spoof_uname()` 的实现：
```c
if (unlikely(my_uname.release[0] == '\0' || spin_is_locked(&susfs_uname_spin_lock)))
    return;
```
`newuname` 系统调用在**进程上下文**执行，此时 `susfs_uname_spin_lock` 通常**未被持有**。`spin_is_locked()` 在未持有的锁上检查**不可靠**，在 SMP + 优化编译下可能**误报为 locked**，导致 `susfs_spoof_uname` 提前 return，uname 伪装静默失效。这是 SUSFS 上游的已知缺陷。

**修复**：移除 `spin_is_locked()` 检查，只保留 `my_uname.release[0] == '\0'`（未设置时跳过）保护。uname 伪装本身不依赖该锁（`susfs_set_uname`/`susfs_set_uname_kernel` 在写时加锁，`susfs_spoof_uname` 只读 my_uname，进程上下文读无需锁保护）。

**教训**：
- `spin_is_locked()` 只能用于锁**必然被持有**的上下文（如中断处理、锁持有者内），不能在普通进程上下文用它对未持有的锁做状态判断——会误报导致功能失效
- 只读共享变量的函数（如 uname 伪装读取 my_uname）在进程上下文无需自旋锁保护，只需检查数据是否已初始化（空值守卫）
- 验证 uname 伪装是否生效：boot restore 设置后立即 `uname -v`，若显示真实值则 hook 未生效

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E011：50_add 补丁 kallsyms.c hunk 行数声明错误导致 sys.c/fork.c 的 SUSFS hook 静默缺失

**现象**：修复 E010 后（#706）uname 伪装仍不生效。`uname -v` 始终显示真实内核版本，即使 boot restore 已正确设置 my_uname（dmesg 确认）、ksud set-uname 返回 0。设备内核 `/proc/kallsyms` 中 `__arm64_sys_newuname` 和 `susfs_spoof_uname` 符号都存在，但 hook 未执行。

**根因**：`50_add_susfs_in_kernel-4.19.patch` 中 kallsyms.c 段的 hunk 头声明为 `@@ -657,8 +657,18 @@`（新行数 18），但实际 hunk 内容为 **8 行上下文 + 11 行新增 = 19 行**。行数声明少 1，导致 GNU patch 在应用完 kallsyms.c 后报 `patch: **** malformed patch at line 1318`，**在 `kernel/sys.c` 和 `kernel/fork.c` 被处理前中止**。CI workflow 用 `patch ... || echo "WARNING: 50_add patch failed"` **静默忽略了失败**，构建"成功"但 sys.c（newuname hook）和 fork.c（susfs_task_state）的 SUSFS 代码完全缺失——这就是 uname 伪装不生效的真正根因。

**修复**：将 kallsyms.c 段 hunk 头 `+657,18` 修正为 `+657,19`，使行数声明与实际 hunk 内容一致。修复后完整应用补丁：`sys.c`（susfs_spoof_uname ×2）、`fork.c`（susfs_task_state ×1）均成功打入。

**教训**：
- **GNU patch 在 hunk 行数声明错误时会静默中止并返回非零，但不会指出具体错误原因**——必须检查 `patch` 的退出码和完整 stderr，不能只看"patching file"输出
- CI 中 `patch ... || echo "WARNING"` 的模式会**吞掉关键补丁失败**，导致"构建成功但功能缺失"的假象。应改为：关键补丁失败必须让 CI 报错（fail-fast），或在构建后验证关键符号存在
- 验证 SUSFS hook 是否真正编译进内核：在干净 kernel 源码上运行 `patch -p1 --dry-run` 完整应用，确认 sys.c/fork.c 无 FAILED
- 遗留：`task_mmu.c`（1/3 hunk）和 `proc_namespace.c`（1/4 hunk）因本地内核额外包含 `#include <linux/ctype.h>` 等差异而失败，影响 `SUS_KSTAT` 功能，不影响 uname 伪装，另行处理

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E012：SUSFS 清空 ro.lineage 属性产生 default_prop 孤儿 entry，触发 Hunter "Found hole in prop area"

**现象**：Hunter 报 `Find Prop Modify Mark (Found hole in prop area:u:object_r:default_prop:s0)` ×2（清除 build_prop 区域的 KB2005 残留后从 3 个减为 2 个）。Momo 的 TEE 损坏、SELinux 宽容、非原厂系统均已在 TEESimulator + Enforcing + uname 伪装修复后消失，仅剩此 prop hole。

**根因**：`susfs_restore_properties()` 里用**空字符串**清空 `ro.lineage.*`（×8）和 `ro.modversion`：
```c
{ "ro.lineage.version", "" }, ... { "ro.modversion", "" },
```
SUSFS 的 `property_set()` 直接对 `/dev/__properties__/u:object_r:default_prop:s0` 做 `kernel_write`：只把 serial 清零、value 清零，但 **prop_info entry 和 trie 中的 name 前缀没有移除**。结果在 default_prop 区域留下**孤儿 entry**（serial=0、value 全零、只有 `lineage`/`lineagelegal` 名字残留）。Hunter 用标准 prop_area 布局遍历 trie，发现这些"有名字无数据"的 entry，判定为 hole。

**修复**：从 `susfs_restore_properties()` 的 set_props 数组**移除全部 ro.lineage.* / ro.modversion 清空条目**，让 LineageOS 系统自行管理这些属性（保持有效值）。理由：
- 设空字符串和删除**都会**产生 hole：删除会清零 name 首字节破坏 trie；设空会留下 serial=0 的孤儿 entry（本 bug）
- 保持有效值的 ro.lineage 属性比制造 hole 更好——属性区域布局保持原样
- `ro.lineage.*` 的存在是 LineageOS 指纹，但原系统本身就有，伪装目标是消除"矛盾/修改痕迹"而非消除指纹本身

**教训**：
- SUSFS 内核 `property_set` 直接改属性区域（绕过 bionic 原子更新），**任何"清空"操作都会留下结构残留**（孤儿 entry），比"不处理"更糟
- Hunter 的 "Found hole in prop area" 检测**属性区域布局完整性**（trie + prop_info 结构），不是属性值。值错误报 "Abnormal prop" / "Prop Modify Mark"，结构错误报 "hole"
- 之前 73c1ed7 已移除过 lineage 清空（"avoid Abnormal prop remains"），后来 d5d7719 又因"删除会破坏 trie"加回空字符串方案——**两者都错，正确是不处理**
- 遗留：本次修改需重启验证（#708）；设备上已有的孤儿 entry 需在干净构建后确认是否被 bionic 正常管理清理

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E013：分区属性变体伪装持久化失败 — resetprop 触发路径失效（init.rc 注入被忽略 + kernel 域无 SELinux 权限）

**现象**：重启后 `ro.system.build.type`、`ro.vendor.build.type`、`ro.odm.build.type`、`ro.product.*.model` 等**分区属性变体**显示真实值（`userdebug`/`KB2005`），而内核 `susfs_restore_properties()` 设置的 `ro.build.type`、`ro.product.build.type` 等 9 个属性始终生效（`user`/`release-keys`）。

**根因**（三层）：
1. **触发路径 A 失效**：KERNEL_SU_RC 注入的 `on post-fs-data → exec root -- ksud post-fs-data` 被本 ROM（LineageOS 20 / Android 13）init 解析器忽略。`SUSFS_BOOT_RESTORE_COMPLETE.md` dmesg 实证：read_proxy 追加 375 字节成功，但 4 个注入段（post-fs-data / nonencrypted / vold.decrypt / boot_completed）全部被跳过，无 `starting service exec ksud` 日志。
2. **触发路径 B 无权限**：实际触发的 35s delayed work `call_usermodehelper("/data/adb/ksud", ["ksud","post-fs-data"])`（`inject-boot-event-move.py`）从 kworker 触发，ksud 以 **`u:r:kernel:s0`** 运行。resetprop 对 `ro.*` 走 **mmap 直写**（`prop-rs-android/sys_prop.rs`：`force_skip = skip_svc || name.starts_with("ro.")`），需要 `O_RDWR` 打开 `/dev/__properties__/u:object_r:<ctx>:s0`（`sys_prop.rs:231`）——kernel 域被 SELinux 拒（`inject-boot-event-move.py` 注释实证："kworker SELinux context lacks permission to write to adb_data_file (verified: returns EACCES)"）。
3. **错误被静默吞掉**：`susfs_config.rs:159-163` 用 `let _ = susfsd::set_prop(...)` 忽略所有失败，无任何日志，表现为"看起来没生效但不知哪里失败"。

**辅助根因**：`restore_if_needed()`（`cli.rs:621`）在 `ensure_binaries()`（`init_event.rs:56`）之前执行，首次刷机时 `/data/adb/ksu/bin/resetprop` 符号链接尚未创建 → `Command::new` 失败（ENOENT）。

**修复（方案 A：迁移到内核 property_set）**：
- `prop_contexts[]` 补全 3 个 context：`build_vendor_prop`（ro.vendor.build.*、ro.product.vendor.*、ro.vendor_dlkm.*）、`build_odm_prop`（ro.product.odm.*）、`vendor_default_prop`（ro.odm.build.*）。已在设备确认 `/dev/__properties__/u:object_r:<ctx>:s0` 文件存在。
- `susfs_restore_properties()` set_props[] 补全 11 个分区属性变体（ro.system.build.type、ro.system_ext.build.type、ro.vendor.build.type、ro.vendor_dlkm.build.type、ro.odm.build.type + 6 个 ro.product.*.model = KB2000）。
- 内核在 zygote exec 时（init 域）执行，权限可靠（与现有 9 个属性相同）；`try_context()` 对不存在的 context 文件安全跳过（`filp_open` 失败返回 NULL），不影响其他 ROM。
- `ro.odm_dlkm.build.type` 设备上不存在，`property_set` 返回 -ENOENT 静默跳过，无害。
- ksud config 保留 set_props（双轨冗余）：resetprop 若成功同值覆盖无害，若失败内核兜底。

**教训**：
- **KernelSU-Next 的 init.rc 注入在本 ROM 不可靠**——不能依赖 `ksud post-fs-data`/`services` 事件做开机关键操作
- **`call_usermodehelper` 从 kworker 触发时以 kernel 域运行**，无 SELinux 权限访问 Android 属性区域，所有用户态 resetprop 都会失败
- **错误用 `let _ =` 吞掉是最坏的**——无法诊断。任何"静默失败"的配置应用都应加日志
- 内核 `property_set`（zygote exec，init 域）是设置 ro.* 分区属性的**唯一可靠路径**
- 分区属性实际 context 与 AOSP 规则可能不同（如 ro.odm.build.type 在 vendor_default_prop 而非 build_odm_prop）——**必须按设备实际确认**

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E014：伪装 ro.product.*.model 分区变体导致兴业银行检测"非安全设备(110)"并强退

> ⚠️ **已修正（E016）**：本条目为**误判**。兴业弹窗真正根因是 `ro.lineage.*` 指纹（E015），**不是 model 伪装**。model 伪装（KB2000）已加回。误判源于用 `HomeActivity` 测试（跳过安全检测）而非真实入口 `FirstPageActivity`。保留此条目作为误判教训。

**现象**：#709 把分区属性变体全部伪装成 `user`/`KB2000` 后，兴业银行（`com.cib.cibmb`，newland 加固）打开主页弹窗"检测到您的设备非安全设备(110)"并自动关闭。无 FATAL EXCEPTION、无 native tombstone（主动退出）。农行（`com.android.bankabc`）正常。

**根因**：`#709`（E013 方案 A）把 `ro.product.*.model` 分区变体（ro.product.system.model、ro.product.vendor.model、ro.product.odm.model、ro.product.bootimage.model 等）从真实值 `KB2005` 伪装成 `KB2000`。兴业银行检测这些变体被修改后判定设备不安全并强退。

**A/B 测试实证**（严格测试：强杀所有后台进程再只开兴业银行）：
| 状态 | 兴业银行 |
|------|---------|
| build.type 变体=user + model 变体=KB2005（真实）| ✅ 无弹窗 |
| build.type 变体=user + model 变体=KB2000（伪装）| ❌ 弹窗(110) 后强退 |
| 全部真实（userdebug + KB2005）| ✅ 无弹窗 |

**修复**：内核 `susfs_restore_properties()` 移除 6 个 `ro.product.*.model` 伪装（保留 5 个 build.type 变体伪装：ro.system.build.type、ro.system_ext.build.type、ro.vendor.build.type、ro.vendor_dlkm.build.type、ro.odm.build.type）。`ro.product.model` 本身是真实 KB2000，与 KB2005 变体并存，Hunter 接受（无"机型修改"提示）。同步移除 ksud `default_config()` 的 6 个 model 伪装（避免双轨 resetprop 成功时再触发）。

**教训**：
- **银行 App 会检测 `ro.product.*.model` 分区变体是否被修改**，比 Hunter 更严格——不能伪装 model 变体
- **测试银行 App 必须强杀所有后台进程（包括银行自身）再打开**，否则残留进程干扰检测结果
- 区分"build.type 变体伪装"（安全）和"model 变体伪装"（银行检测）——前者消除 userdebug 矛盾，后者触发银行安全检测
- 农行（bankabc）不检测 model 变体，兴业（cibmb）检测——同一伪装对不同银行影响不同，需分别验证

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E015：兴业银行弹窗根因 = ro.lineage.* 指纹暴露 + susfs_trigger_post_fs_data 缺 override_creds 致 35s ksud 以 kernel 域运行

**现象**：干净 LineageOS + #702/#707 内核上兴业银行（`com.cib.cibmb`）正常；#708（E012）后弹窗"非安全设备(110)"并强退。农行不受影响。

**二分法定位**（逐个刷入测试）：
| 构建 | 改动 | 兴业银行 |
|------|------|---------|
| #702 (E006) | 基础 | ✅ 正常 |
| #705 (E009) | 分区属性变体 | ✅ 正常 |
| #707 (E011) | 50_add 补丁 | ✅ 正常 |
| #708 (E012) | **移除 ro.lineage 清空** | ❌ 弹窗 |
| #708 + 手动 resetprop 清空 ro.lineage | | ✅ 恢复 |

**根因**：兴业银行检测 `ro.lineage.*`/`ro.modversion` 属性**存在且有值**（LineageOS 定制 ROM 指纹）。#707 的内核 `susfs_restore_properties()` 清空这些属性（空字符串）→ 兴业检测不到指纹 → 正常。**E012 移除清空** → 指纹恢复有值 → 兴业弹窗。

**关键反转**：E012 原以为"清空产生 orphan hole（Hunter 检测）"必须移除，但二分法证明：
- **内核 property_set 清空**（kernel_write 直接写，不更新全局 serial/futex）→ 产生 orphan → Hunter hole
- **resetprop 清空**（走 bionic 协议，正确更新全局 serial/futex）→ **结构完整，Hunter 无 hole**，且兴业正常

**第二个缺陷**：`susfs_trigger_post_fs_data()`（`inject-boot-event-move.py`）用 `call_usermodehelper` 触发 `ksud post-fs-data` 时**没有 override_creds(ksu_cred)**。kworker 上下文是 `u:r:kernel:s0`，无 SELinux 权限读 `/data/adb/*` 和打开 `/dev/__properties__/*` → 35s 的 ksud post-fs-data 无法应用 config set_props、无法执行模块 post-fs-data.sh。已验证 `runcon u:r:kernel:s0 ls /data/adb/modules` → Permission denied；而 `runcon u:r:ksu:s0` 正常。

**修复**：
1. `inject-boot-event-move.py`：`susfs_trigger_post_fs_data()` 用 `override_creds(ksu_cred)` 包裹 `call_usermodehelper`，让 35s 的 ksud post-fs-data 以 ksu 域（permissive，rules.c:95,106）运行
2. config `set_props` 加 9 个 ro.lineage.*/ro.modversion = ""（ksud 用 resetprop 清空，结构完整）

**教训**：
- **E012 的修复方向错了**——它用"移除清空"消除 Hunter hole，副作用是暴露 ro.lineage 指纹触发兴业弹窗。正确做法是**改用 resetprop 清空**（结构完整）而非内核 property_set
- **内核 property_set（kernel_write 直写）与 resetprop（bionic 协议）清空属性的结果不同**——前者产生 orphan（Hunter 检测），后者结构完整
- **`call_usermodehelper` 从 kworker 触发时以 kernel 域运行**，无 SELinux 权限访问 /data/adb 和属性区域——必须 override_creds(ksu_cred) 才能让子进程做用户态操作
- **二分法排查非常有效**：从 #702 到 #709 逐个刷入，快速定位 E012 为触发点

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

### E016：E014 误判修正 — ro.product.*.model 伪装可安全加回（兴业弹窗真正根因是 ro.lineage 指纹）

**背景**：E014 曾把兴业银行弹窗归因于 `ro.product.*.model` 变体伪装成 KB2000，移除了 6 个 model 伪装。后用**正确测试方式**（`FirstPageActivity` 真实入口冷启动，而非 `HomeActivity`）验证，发现 model 伪装**不是**兴业弹窗根因。

**实证**（干净 LineageOS 上 A/B 测试，均用 FirstPageActivity）：
| model 变体 | ro.lineage | 兴业银行 | Hunter |
|-----------|-----------|---------|--------|
| KB2005（真实）| 有值 | ❌ 弹窗 | — |
| KB2005（真实）| 已清空 | ✅ 正常 | ✅ 无 hole |
| **KB2000（伪装）**| **已清空** | ✅ **正常** | ✅ **无 hole** |

**结论**：兴业银行检测的是 **`ro.lineage.*`/`ro.modversion` 属性有值**（LineageOS 指纹，见 E015），**不是 model 变体**。E014 移除了 6 个 model 伪装是**误判**。

**修复**：将 6 个 `ro.product.*.model` 伪装（KB2000）**加回**内核 `susfs_restore_properties()`（与 `ro.product.model=KB2000` 真实值一致，Hunter 无"机型修改"矛盾）。总 set_props 恢复到 23 个。

**教训**：
- **测试银行 App 必须用真实入口 Activity（MANIFEST 的 LAUNCHER，如 `FirstPageActivity`），不能用 `am start -n ...HomeActivity`**——后者跳过安全检测，导致误判
- E014 的错误教训：用错误测试方式（HomeActivity）得出错误结论（model 伪装导致弹窗），实际是 ro.lineage 指纹 + 测试方式问题
- **A/B 测试要用用户实际的操作路径**（桌面图标 → LAUNCHER Activity），而非开发者跳转

**检查清单锚点**：TEST_PROCEDURE.md 第 2 节"全链路追踪" + 第 3 节"边界条件和副作用验证"。**标签**：cross-project

---

## 当前状态（build #335 验证结果）

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `ksud debug su` 从 adb root | ✅ | `context=u:r:ksu:s0` — Fix 4（uid=0→true）有效 |
| `seccomp_bypass` kprobe 注册 | ❌ | `secure_computing` 符号不存在，返回 -2（ENOENT） |
| `ksud 守护进程` 从 post-fs-data 启动 | ❌ | 查询不到 ksud 系统进程 — Fix 1 未生效或 exec 失败 |
| `track_throne()` 在 workqueue | ❌ | `failed to set manager UID` — 5 次重试全部失败 |
| `system/bin/su` 存在 | ❌ | /system 分区只读，软链接无法创建 |
| 底部导航栏 4 个 Tab | ❌ | `fullFeatured`=false，只显示 Home + Settings |
| 设置页 7 个 feature 开关 | ❌ | 嵌入式 libksud.so 无 KSU fd |

### 未解决问题

1. **`secure_computing` kprobe 失效**：该符号在内核中不可用于 kprobe。需要换为 `__seccomp_filter` 或使用 syscall table hook 方案。
2. **`track_throne()` 失败**：`/data/system/packages.list` 在 workqueue 执行时（33-43s）仍被锁定。需要延长重试窗口到 120s，或使用 `on_boot_completed` 替代。
3. **`su` 不存在**：`/system` 只读分区。需要启用 `KSU_SUSFS_HAS_MAGIC_MOUNT=y` 通过 overlay 挂载 su 软链接。
4. **依赖关系**：上述 3 个问题相互独立，但都导致 App 功能受限。

## 验证检查项

### F01：构建产物验证（刷机前）
- [ ] 构建时间与最新 commit 一致
- [ ] `strings Image | grep uid_zero_fix` — Fix 4 文字常量已嵌入
- [ ] `strings Image | grep NOCTX_FIX` — Fix 1 文字常量已嵌入
- [ ] `strings Image | grep seccomp_bypass` — Fix 2 kprobe 符号已嵌入
- [ ] `nm vmlinux | grep seccomp_bypass_pre` — Fix 2 函数已链接
- [ ] `nm vmlinux | grep ksu_reboot_kprobe_pre` — Fix 2 函数已链接
- [ ] `adb shell zcat /proc/config.gz | grep CONFIG_KSU` — KSU 配置项确认

### F02：启动时序
- [ ] `adb logcat -b events -d -v time | grep boot_progress` — 记录各阶段时间戳
- [ ] `adb logcat -b events -d -v time | grep post_fs_data` — post-fs-data 时间
- [ ] `adb shell dmesg | grep "ksu_debug: delayed init"` — workqueue 执行时间（~33s）
- [ ] `adb shell dmesg | grep "manager UID set"` — track_throne 成功时间
- [ ] `adb logcat -b events -d -v time | grep proc_start | grep rifxsd` — App 启动时间

### F03：Fix 验证
- [ ] F1: `adb shell ps -ef | grep /data/adb/ksu/bin/ksud | grep -v grep` — ksud 守护进程运行中
- [ ] F1: `adb shell ls -la /system/bin/su` — su 软链接存在
- [ ] F2: `adb shell dmesg | grep "seccomp_bypass kprobe registered"` — seccomp_bypass kprobe 注册
- [ ] F2: `adb shell dmesg | grep "ksu_reboot kprobe registered"` — ksu_reboot kprobe 注册
- [ ] F2: `adb logcat -d -v time | grep SYS_SECCOMP | tail -5` — 无新增 SECCOMP crash
- [ ] F2: 设置页 UI dump 确认 7 个 feature 开关全部显示
- [ ] F3: `adb shell cat /sys/module/kernelsu/parameters/ksu_debug_manager_appid` — 管理器 UID 已设置
- [ ] F4: `adb shell dmesg | grep diag:.*allowed_for_su.*is_allow=1` — allowed_for_su 返回 true
- [ ] F4: `adb shell 'echo id | /data/adb/ksu/bin/ksud debug su'` — context=u:r:ksu:s0

### F04：App 功能验证
- [ ] 底部导航栏显示 4 个 Tab（首页、超级用户、模块、设置）
- [ ] 首页无 "授予 root 权限失败" WarningCard
- [ ] 设置页 KernelFeaturesCard 显示全部 7 个开关项
- [ ] 模块页可列出 bindhosts
- [ ] `ksud module list` 正常返回 JSON

### F05：SELinux 审计
- [ ] `adb shell cat /sys/fs/selinux/avc/cache_stats | head -5` — 无新增 avc denial
- [ ] `adb shell cat /data/misc/audit/audit.log 2>/dev/null | grep denied | grep -v libksud | tail -10` — 无 KSU 相关 denial

### F06：稳定性
- [ ] 连续 3 次冷启动每次验证通过
- [ ] 连续 3 次热启动（kill→open）每次验证通过
- [ ] 待机唤醒后验证通过
