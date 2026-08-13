# OnePlus 8T TEESimulator 固化方案(方案 Y)完整指南

> **状态:2026-08-08 实测验证通过**(Momo TEE 消失 / 兴业银行+农业银行正常 / Hunter 正常 / 系统稳定)
> 适用:OnePlus 8T(kebab)+ LineageOS 20(Android 13)+ KernelSU-Next + SUSFS 移植内核

---

## 1. 背景与目标

- **问题**:解锁 bootloader + 移植内核后,TEE(TrustZone)相关 keymaster 服务失效,`keystore2` 日志报
  `Error::Km(ErrorCode(-10003))` / `"No such security level"` → Momo 检测出 **"TEE 损坏"**,部分 App 会因此判定环境异常。
- **目标**:让 Momo / 兴业银行 / 农业银行 / Hunter 全部检测正常,且**刷机后无需手动操作即自动生效**。
- **方案**:TEESimulator(JingMatrix, GPL-3.0)——注入 keystore2 进程,劫持 Binder 事务,软件模拟硬件密钥对 +
  伪造 key attestation 证书链(自带 keybox.xml AOSP 测试密钥)。

## 2. 方案架构(3 层)

```
┌─ ① 内核注入段(KERNEL_SU_RC,编译进 Image)
│    on post-fs-data → start teesim
│    service teesim /system/bin/sh /data/local/teesim/start.sh
│        class core / user root / seclabel u:r:su:s0 / disabled
│
├─ ② 编译期 sepolicy 规则(rules.c,编译进内核 sepolicy 表)
│    keystore → adb_data_file / shell_data_file : file read/open/execute/execute_no_trans
│    su → rootfs / unlabeled / adb_data_file(exec + 读)
│    (★ 不用运行时 ksud sepolicy patch——实测会导致设备崩溃重启)
│
└─ ③ /data/local/teesim/start.sh(刷机后部署一次,开机全自动)
    等 sys.boot_completed=1
    → 复制 target.txt / keybox.xml → /data/adb/tricky_store(TEESimulator 硬编码路径)
    → chcon -R /data/local/teesim 为 adb_data_file(keystore 域可读)
    → 守护循环(30s):App 不在则 app_process 启动 TEESimulator,死亡自动拉起
```

## 3. 关键演进与教训(为什么最终是这样)

| 版本 | 方案 | 结果 |
|---|---|---|
| fd97d58 | 文件打包进 **ramdisk**(/teesim) | ❌ **system-as-root 切根后 ramdisk 释放**,`/teesim` 不存在,注入段 exec 失败 |
| 0342987 | 路径改 `/data/local/teesim`(文件在 data) | ⚠️ 注入段生效,但 **start.sh 里运行时 `ksud sepolicy patch` 导致设备崩溃重启**(多次复现;chcon + app_process 单独执行均安全) |
| **ea74543** ✅ | **keystore 规则编译进内核 rules.c** + start.sh 移除 patch | ✅ 刷入后自动启动、keystore2 注入成功、零 avc 拒绝、系统稳定 |

**教训**:
1. **OnePlus 8T 是 system-as-root**:boot.img ramdisk 只在 initramfs 阶段存在,切根(system 分区 dm-2)后内容全部释放——**ramdisk 固化不可行**。
2. **运行时 sepolicy patch 在此内核不可靠**:即使 file 类规则也会触发崩溃重启(根因未明,与 KSUN/SUSFS 的 selinux_hide 交互相关)——**规则必须编译期内核固化**。
3. **USB 调试自动关闭**:早期 Momo 实验在 `susfs_config.json` 的 `set_props` 残留了 `"persist.sys.usb.config": "mtp"` → 每次重启 USB 调试被关(曾误判为"设备崩溃")。**已从配置移除**(勿再加回)。

## 4. 文件清单

### 4.1 构建侧(仓库 `qcxl/oneplus8t-kernelsu-susfs-629`,main 分支)

| 文件 | 作用 |
|---|---|
| `scripts/inject-teesim.py` | 内核注入:①KERNEL_SU_RC 加 `on post-fs-data` start teesim + service 定义;②rules.c 注入 su/keystore 域规则(幂等,SCRIPT_MARK) |
| `prebuilt/teesim/` | 部署源文件(7 个,见 4.2) |
| `install-teesim.sh` | 一键部署脚本(PC 端执行) |
| `.github/workflows/build-ksu-debug.yml` | CI:编译前调用 inject-teesim.py |

### 4.2 部署侧(`/data/local/teesim/`,7 个文件)

```
classes.dex          TEESimulator App(Java 主程序)
libTEESimulator.so   注入 keystore2 的 Binder 拦截 so
inject               ptrace 注入器(libinject.so)
keybox.xml           证书伪造密钥盒(AOSP 测试密钥)
target.txt           拦截目标包名配置
start.sh             固化启动脚本(守护循环)
resetprop            包装脚本 → /data/adb/ksud resetprop(App 设置 ro.* 属性用)
```

## 5. 刷机部署步骤(完整流程)

### 5.1 前置(与现有刷机指南一致)

1. 刷入 LineageOS 20 系统(卡刷) + 稳定移植内核(`a7de100` 或更新的方案 Y 内核)
2. 安装 KernelSU-Next App + 部署 ksud(`/data/adb/ksud`)
3. 配置 SUSFS(`susfs_config.json`):sus_paths 隐藏 `/sys/module/kernelsu`、`/system/bin/su` 等;set_props 含 ro.debuggable=0 等——**勿含 persist.sys.usb.config**
4. 创建 `/system/bin/su` 为普通文件并重启(SUSFS 隐藏生效)

### 5.2 部署 TEESimulator(一次性)

```bash
# 仓库根目录执行(需 adb root)
bash install-teesim.sh
# 或手动:
adb root
adb shell "mkdir -p /data/local/teesim"
adb push prebuilt/teesim/classes.dex prebuilt/teesim/libTEESimulator.so \
    prebuilt/teesim/inject prebuilt/teesim/keybox.xml prebuilt/teesim/target.txt \
    prebuilt/teesim/start.sh prebuilt/teesim/resetprop /data/local/teesim/
adb shell "chmod 755 /data/local/teesim/inject /data/local/teesim/start.sh /data/local/teesim/resetprop; chcon -R u:object_r:adb_data_file:s0 /data/local/teesim/"
```

### 5.3 重启,自动生效

```bash
adb reboot
# 开机完成后(约 2-3 分钟)验证:
adb shell "ps -A | grep TEESimulator"        # 应有 TEESimulator 进程
adb shell "grep -c libTEESimulator /proc/\$(pidof keystore2)/maps"   # 应 ≥ 3
```

**之后每次开机全自动**:内核注入的 service 启动 start.sh → 复制配置 → chcon → 守护循环拉起 App,无需任何手动操作。

## 6. 验证清单

| 项 | 预期 |
|---|---|
| 系统稳定性 | uptime 持续增长,无崩溃/重启循环 |
| Momo | "TEE 损坏" 消失,其余项正常 |
| 兴业银行 / 农业银行 | 正常使用,无 root 弹窗 / 非安全设备提示 |
| Hunter | 无 `/system/bin/su` 等风险项 |
| keystore2 注入 | `/proc/<keystore2>/maps` 含 libTEESimulator.so(3 段) |
| dmesg avc | 无 `keystore` 读 `libTEESimulator.so` 拒绝 |

## 7. 注意事项

1. **sepolicy patch 禁令**:开机流程中**不要**执行 `ksud sepolicy patch`(尤其 keystore 相关)——本内核实测会崩溃重启。规则已编译期内核固化,无需补。
2. **USB 调试**:`susfs_config.json` 的 `set_props` **不得**含 `persist.sys.usb.config`(否则每次重启关闭 USB 调试)。
3. **TEESimulator 多进程(已修复,ff7ab4b)**:守护循环早期 bug 曾导致 ~100 个实例堆积 → 内存枯竭 → lmkd 误杀前台 App(Hunter 崩溃)。修复:
   - **单例锁**:`mkdir` 原子锁(不用 flock——toybox flock 是外部命令,锁随进程退出释放)
   - **可靠检测**:`ps -A | grep -c " TEESimulator"`(不用 pgrep -f/-x——匹配 sh 包装;不用 awk if()——toybox awk 语法报错)
   - **文件标签**:`chcon system_file`(不用 adb_data_file——keystore 域缺 getattr 规则,dlopen stat 被拒;system_file 有默认 stat/read,且普通 App 域读不到,更隐蔽)
   - start.sh 在 `/data/local/teesim/`,修改后**下次开机生效,无需重建内核**
4. **OTA 系统更新**:会覆盖 boot(system-as-root 的 ramdisk/内核)→ 需重刷移植内核;`/data` 保留时 teesim 文件仍在,**无需重新部署**;若 `-w` 清 data 则需重新执行 5.2。
5. **上游更新**:TEESimulator 新版本需重新构建内核(文件在 prebuilt/teesim/ 里替换后 push 触发 CI)。
6. **keybox.xml 已升级为 Google 根共享 keybox**(2026-08-08,提交 2a3a718):证书链根为 Google attestation 根(serialNumber `f92009e853b6b045`,指纹 `CE:DB:1C:B6:...`),Native Test 判定 `untrusted=false / Device locked=true / Verified boot state=Verified`,"AOSP Attestation Key" 告警消除。原 AOSP 测试 keybox 备份:**`prebuilt/teesim/keybox.xml.aosp.bak`**(提交 a41e369;设备侧同存于 `/data/adb/tricky_store/keybox.xml.aosp.bak`;DeviceID=dev1,md5 `f0594bc3...`)。**风险**:共享 keybox 可能被 Google 检测复用而失效——若失效,还原 AOSP 备份(本地生成、永不失效,仅测试工具会报 "AOSP Attestation Key")。替换方式:改 `/data/adb/tricky_store/keybox.xml` + `prebuilt/teesim/keybox.xml`,重启或重启 TEESimulator App 生效。

## 8. 如何重新构建(改了 teesim 文件或注入脚本后)

```bash
cd build-kernelsu-susfs
# 修改 prebuilt/teesim/* 或 scripts/inject-teesim.py 后:
git add -A && git commit -m "update teesim"
git push origin main        # push 自动触发 CI(push 事件,标题=commit 描述)
# 等 CI 完成(run 状态 success),下载 artifact kebab-kernel-ksu-debug.zip
# 解压得 ksu-debug-boot.img → fastboot flash boot_a/b → 重启
```

## 9. 相关提交(内核仓库 main)

```
ea74543 fix(teesim): bake keystore adb_data_file rules into kernel(最终版 ✅)
0342987 fix(teesim): system-as-root → /data/local/teesim(路径修正)
fd97d58 feat(teesim): plan Y — embed TEESimulator in ramdisk(废弃:切根释放)
```

## 10. 备选方案与对比(2026-08 调研结论)

### 10.1 OhMyKeymint(更隐蔽的 keystore 替代实现)——暂不需要

| 维度 | TEESimulator(本方案) | OhMyKeymint |
|---|---|---|
| 实现方式 | 劫持型:注入 keystore2 拦截 Binder 事务 | 重实现型:完整重写 keymint HAL(AOSP AIDL 接口),替代而非劫持 |
| 隐蔽性 | 中(拦截层与 AOSP 可能有细微差异) | 更高(行为完全对齐 AOSP,检测器更难发现不一致) |
| 部署结构 | Java App + 注入 so(已非模块化固化,本方案) | 模块 + 两个后台 daemon(keymint/injector),配置在 `/data/misc/keystore/omk/` |
| 配置 | target.txt + keybox.xml | config.toml + injector.toml + keybox.xml(EC+RSA 双链,格式严格) |
| 成熟度 | 本方案全链路实测通过 | 较新(215 stars / 150 commits);AGPL-3.0 + 附加条款(禁止商业用途) |

**结论**:当前所有检测(Momo/兴业/农业/Hunter)已通过,TEESimulator 足够;OMK 的"更高隐蔽性"属过度设计,且模块 + daemon 结构非模块化改造成本高。**留作未来检测升级时的备选**。

### 10.2 Tricky Addon(target.txt 图形化配置)——不适用

- **硬依赖**:需先装 Tricky Store 模块 + KSU WebUI——违反"不能装模块"(银行检测 `/data/adb/modules`)约束。
- 本方案 target.txt 已固化且极少变更,手动维护成本低。
- 唯一借鉴:其 target.txt 语法(`!`/`?` 模式、verifiedBootHash、安全补丁级别)可作为未来扩展参考。

### 10.3 keystore 概念速览(为什么需要 TEESimulator)

- **keystore/keystore2** = Android 密钥保险库服务:生成/存储/管理密钥,私钥不离开安全环境。
- **安全级别**:SOFTWARE / TRUSTED_ENVIRONMENT(TEE)/ STRONGBOX。
- **key attestation(密钥认证)**:证明"密钥由受信任硬件生成"的证书链——银行 App / Momo 检测 TEE 的核心。
- 解锁 + 移植内核 → keymaster HAL 无法访问 TEE → keystore2 报 `ErrorCode(-10003)` → Momo "TEE 损坏"。
- **TEESimulator 的作用**:让 keystore 层"以为"有 TEE——拦截密钥生成/认证请求,软件生成密钥 + 用 keybox.xml 伪造硬件认证证书链,App 验证通过。

---

## 11. 附录:luna / 春秋 Native Check 检测修复(2026-08-08 实测闭环)

### 11.1 现象

- **luna(icu.nullptr.nativetest)**:高危风险 "1. Root 环境 2. 发现 KernelSU 4. 该设备不建议使用:支付/社交/购物/游戏"。
- **春秋 Native Check(com.chunqiunativecheck)**:检测到 "设备取得 ROOT 权限 / result=hit: app zygote SELinux oracle found KSU context"。
- **Momo / 农业银行 / 兴业银行**:均正常(不受影响)。

### 11.2 根因(selinux oracle 三类接口)

KernelSU 的 `selinux_hide`(feature 4)已启用时,仅 **setprocattr(`/proc/self/attr/*`)写** 返回 `-EINVAL`;但:

1. `my_write_context`(`/sys/fs/selinux/context` 写,旧 setcon 路径):返回**假成功**(write size)→ 检测器判定 "ksu 域存在且 setcon 成功" → `ksuDomain=yes`。
2. `my_write_access`(`/sys/fs/selinux/access` 写,libselinux `selinux_check_access` 路径):返回**全允许 av 决策**(`0 0xffffffff 0 0xffffffff 0 0`)→ 检测器判定 "ksu 域可查询且权限允许" → `ksu_domain=1`。
3. `my_setprocattr`:仅拦 `name=="current"`,`setexeccon`(attr/exec)等探测可绕过。

luna 的 `SelinuxContextOracleService` 与 Native Check 的 `detectSelinuxAccessOracleAnomaly` 正是用 2/3 探测 ksu 域。

### 11.3 修复(内核提交 597688c)

`kernel-patches/unified-selinux_hide.c`:

- `my_write_context`:含 ksu 的写 → **`-EINVAL`**(镜像"无 ksu 域的干净内核")
- `my_write_access`:含 ksu 的查询 → **`-EINVAL`**(同上;全允许/假成功都泄露域存在)
- `my_setprocattr`:覆盖全部 attr name(`current/exec/prev/fscreate/keycreate/sockcreate`)

### 11.4 验证(实测通过)

```
luna   Bugly: SELinux oracle result=0 ksu_domain=0 ksu_file=0 magisk_file=0
luna   Luna : SELinux context oracle snapshot: ksuDomain=no, ksuFile=no, magiskFile=no
luna   UI   : Root 和 KernelSU 告警消失
Native Check: Root 和 KernelSU 告警消失
```

### 11.5 luna 剩余显示项(非 root 检测,无需处理)

- **Security update: 2024-01-05**:确认是 **OnePlus 8T + Android 13 的设备指纹展示**(三个工具显示一致;当前系统属性已伪装 2024-02-05、vendor 真实 2023-08-05,均非 2024-01-05;TEESimulator 证书已是 202402 但显示不变 → 证明不从证书读)→ **非检测项**。
- **模块扫描 / 备用机 / 云机 / 新机 / 不建议使用支付社交购物游戏**:设备指纹与综合建议类,与 root 隐藏无关,不影响银行 App。

### 11.6 已回滚的尝试(TEESimulator,确认无效)

- `743d0c2`(imported attest key 也重新生成证书)+ `security_patch.txt` 配置:针对 "Security update 2024-01-05" 的尝试——确认该值为设备指纹后**已回滚**(fork `qcxl/TEESimulator` reset 到上游 `150a476`,prebuilt/teesim/classes.dex 恢复上游 2332052B,提交 cda4010)。
  - ⚠️ 补充:TEESimulator 证书里的 patchlevel 与 SUSFS `set_props` 的 `ro.build.version.security_patch` 是两层;后者(属性伪装)也会被 Hunter 6.6.5 的 Build Identity 一致性检测命中(STRONG HIT)——处理方式见刷机指南 §12.1/§12.11(移除伪装,回真实值)。
- 教训:**先确认检测值的数据源(属性/证书/指纹库)再动手**,避免为无效目标构建。
