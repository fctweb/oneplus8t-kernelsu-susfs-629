# OnePlus 8T (kebab) 全新刷机完整指南(手把手版)

> **目标**:从零彻底清除设备所有分区数据,全新安装 LineageOS 20 系统 + 移植内核(KernelSU-Next + SUSFS)+ KernelSU-Next 管理器,并通过银行 App / Momo / Hunter 环境检测。
> **适用设备**:OnePlus 8T (KB2000 / kebab)
> **系统**:LineageOS 20 (Android 13) nightlies
> **版本**:2026-08 编写,基于 lineage-20.0-20240209-nightly-kebab-signed + 稳定移植内核(CI run 31108984710)

---

## 刷机总流程(严格按此顺序,勿跳步)

```
① 准备与备份  →  ② 解锁 Bootloader  →  ③ 清除数据  →  ④ 刷系统(物理分区→动态分区)
→  ⑤ 刷移植内核  →  ⑥ 首次开机+基础设置  →  ⑦ 装 App+部署 ksud
→  ⑧ 创建 su+重启(SUSFS 隐藏)  →  ⑨ 写 SUSFS 配置  →  ⑩ 最终验证
```

> ⚠️ **顺序不可错乱**:先刷完系统与内核、能开机,再做 App/ksud/SUSFS 配置;反过来做会导致 root 管理失效或隐藏不生效。

---

## 目录大纲

1. [前置概念(必读)](#1-前置概念必读)
2. [资源清单与下载地址](#2-资源清单与下载地址)
3. [刷机前准备与备份](#3-刷机前准备与备份)
4. [解锁 Bootloader](#4-解锁-bootloader)
5. [进入 Fastboot / Fastbootd 模式](#5-进入-fastboot--fastbootd-模式)
6. [清除所有分区数据](#6-清除所有分区数据)
7. [刷入 LineageOS 20 系统](#7-刷入-lineageos-20-系统)
8. [刷入移植内核](#8-刷入移植内核)
9. [首次开机与基础设置](#9-首次开机与基础设置)
10. [WiFi 感叹号修复](#10-wifi-感叹号修复)
11. [安装 KernelSU-Next App 与 ksud](#11-安装-kernelsu-next-app-与-ksud)
12. [SUSFS 隐藏配置(银行 App 检测)](#12-susfs-隐藏配置银行-app-检测)
13. [最终验证清单](#13-最终验证清单)
14. [注意事项与救砖](#14-注意事项与救砖)

---

## 1. 前置概念(必读)

### 1.1 A/B 双槽位分区(Slot A / Slot B)
OnePlus 8T 使用 **A/B 无缝分区**架构:
- **物理分区**(boot、dtbo、recovery、vbmeta 等)有 **slot_a / slot_b 两套**,可自由刷写与切换
- **动态分区**(system/vendor/odm/product/system_ext)是**单 group 共享**设计(super 7GB 内一个 `qti_dynamic_partitions` 组):**同一时间只有一个槽位有动态分区条目**(system_a 或 system_b),另一槽由 update_engine 安装时才创建——**这不是故障**
- 当前启动的槽位通过 `fastboot getvar current-slot` 查询
- 切换槽位前,若目标槽动态分区不存在,需先用 recovery 卡刷把系统装进该槽(见 7.2 节)
- **本指南要求两个槽位的物理分区都刷**(boot/dtbo/recovery 双份),避免"槽位混用"导致 bootloop

### 1.2 动态分区(Super 分区)
system / vendor / odm / product / system_ext **不是独立物理分区**,而是包在 **super 分区**里的**动态子分区**:
- 刷动态子分区镜像必须进入 **fastbootd 模式**(用户空间 fastboot)
- bootloader 模式下只能刷 boot / dtbo / vbmeta / recovery 等物理分区

> ⚠️ **区分两种 fastboot**:
> - **bootloader fastboot**:开机按音量下+电源,或 `adb reboot bootloader`(显示 "Fastboot Mode")
> - **fastbootd**:bootloader 下执行 `fastboot reboot fastboot`(显示 "FastbootD")

### 1.3 Payload 与镜像提取
LineageOS 官方安装包是 OTA 格式(`payload.bin`),需用 **payload_dumper** 工具提取出各分区镜像。本指南直接使用已提取的镜像:`payload_dumper/output/`。

### 1.4 vbmeta 与 AVB 验证(关键!)
- Android Verified Boot(AVB)会校验 boot 分区签名
- **移植内核是自编译的,签名与官方不同**,必须**禁用 AVB 验证**,否则刷入后 bootloop
- 刷 vbmeta 时必须加 `--disable-verity --disable-verification`

### 1.5 KernelSU-Next 与 SUSFS
- **移植内核** = LineageOS 20 内核 + KernelSU-Next + SUSFS 编译而成,`/proc/version` 已伪造为官方样式
- **ksud** = KernelSU-Next 的后台守护进程,负责模块管理、SUSFS 配置应用
- **KernelSU-Next App** = 管理器,通过内核 ksu fd 通信,配置 root 授权

---

## 2. 资源清单与下载地址

### 2.1 电脑端工具
| 工具 | 说明 | 获取方式 |
|---|---|---|
| **adb / fastboot** | 刷机核心工具 | macOS:本机 `~/Library/Android/sdk/platform-tools/`(已配置) |
| **payload_dumper** | 提取系统镜像 | 本地 `payload_dumper/`(已配置) |
| **USB 驱动** | Windows 需装;macOS/Linux 免驱 | — |

### 2.2 系统与内核(核心刷机包)
| 资源 | 来源 / 下载地址 | 说明 |
|---|---|---|
| **LineageOS 20 官方包** | 本地:`lineage-20.0-20240209-nightly-kebab-signed/`(含 payload.bin) | 用于提取镜像 + recovery 卡刷 |
| **提取的系统镜像** | 本地:`payload_dumper/output/` | boot / dtbo / odm / product / recovery / system / system_ext / vbmeta / vbmeta_system / vendor |
| **移植内核 boot.img** | GitHub Actions:`qcxl/oneplus8t-kernelsu-susfs-629` → **Build rsuntk KSU + SUSFS Kernel (debug)** → 产物 `kebab-kernel-ksu-debug.zip` → 解压得 `ksu-debug-boot.img` | ⚠️ **用已验证构建(当前:`7bf9edbc` = CI run 31662375179,含 Hunter 6.6.5 selinux_hide 黑名单扩展)**,勿用重启循环版(25753ede / db2be765 / a6472d7)与设备伪装版(early props/prjName/cpuinfo 伪装,已回滚);详见 §2.4 |
| **ksud** | GitHub Actions:`qcxl/KernelSU-Next` → **Build Manager CI** → 产物 `ksud-aarch64-linux-android/.../ksud` | KSUN 后台守护进程(需手动部署) |
| **KernelSU-Next App** | GitHub Actions:`qcxl/KernelSU-Next` → **Build Manager CI** → 产物 **`manager`**(apk) | root 管理器 App。⚠️ **用最新构建(v3.2.0-207+)**,旧版有"授予 root 权限失败"(12.7)与"Profile 模板拉取不到数据"(12.9)问题 |

### 2.3 关键文件路径速查(本机)
```
# 系统镜像(已提取)
/Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/*.img

# 移植内核(从 CI 下载解压后)
/Users/weifeng/Downloads/OnePlus8T/ksu-debug-boot.img   # 当前已验证版 7bf9edbc(run 31662375179)

# LineageOS 卡刷包
/Users/weifeng/Downloads/OnePlus8T/lineage-20.0-20240209-nightly-kebab-signed.zip
```

### 2.4 当前内核版本与提交对应关系(2026-08-13 核实)

> 内核仓库:`qcxl/oneplus8t-kernelsu-susfs-629`(main 分支)。本机/设备当前实际使用状态如下。

| 点 | Commit | CI run | 说明 |
|---|---|---|---|
| **当前设备内核(已刷)** | `7bf9edbc` | 31662375179 | = 3b7aa86(无设备伪装)+ **selinux_hide 黑名单扩展**(Hunter 6.6.5 的 su/adbroot/zygisk/magisk 域探测返回 -EINVAL,消除 independent SELinux Policy Risks/APatch——见 §12.11) |
| **main 当前 HEAD** | `bf891e78` | — | 文档提交(不影响内核代码;内核代码最新 = 7bf9edbc) |
| **设备伪装回滚点** | `3b7aa86` | — | early props / cpuinfo 伪装 / oplus prjName 等设备伪装代码全部移除(force push 到此) |
| **#763(旧记忆中的回滚点)** | `29524cf7` | 31390657468 | linux_banner `@`→`.` 修复(Duck Detector maintainer 检测);是 3b7aa86 的祖先(+10 提交) |
| **早期稳定版** | `a7de100b` | 31180401513 | 更早的稳定构建(重启循环三提交之前的基准) |
| **重启循环版(勿用)** | `25753ede` / `db2be765` / `a6472d7` | — | ReZygisk 隐身相关,刷入即重启循环——已回滚 |

**设备当前状态**:内核 7bf9edbc = 反检测完整(#763 的 linux_banner/-perf/prctl/version 伪装全在)+ 无设备伪装(属性真实 OnePlus 8T)+ Hunter 6.6.5 修复(selinux_hide 黑名单、lineage 置空、cil 隐藏——见 §12.11)。银行 App/KSUN/Momo 均正常。

---

## 3. 刷机前准备与备份

### 3.1 数据备份(必做!全盘会清空)
> ⚠️ 刷机将清除**所有数据**(应用、聊天记录、银行 App 数据均不可恢复)。务必先备份。

**第 1 步**:联系人/相册/应用数据手动备份(云同步或导出到电脑)。
**第 2 步**:可选,用 adb 拉取部分数据:
```bash
adb backup -apk -shared -system -f backup.ab   # 传统备份(部分 Android 13 已移除)
```

### 3.2 环境检查
**第 1 步**:确认电脑端工具可用:
```bash
adb --version && fastboot --version   # 均输出版本号即正常
```
**第 2 步**:确认手机连接:
```bash
adb devices        # 应显示 设备号  device(不是 offline/unauthorized)
adb get-state      # 应输出 device
```
> 若显示 unauthorized:手机弹窗点"允许 USB 调试";若 offline:换线/换口/`adb kill-server && adb start-server`。

**第 3 步**:确认电量 ≥ 50%(建议插线刷机):
```bash
adb shell dumpsys battery | grep level
```

### 3.3 手机端设置
**第 1 步**:设置 → 关于手机 → 连续点按"版本号"7 次,开启开发者选项。
**第 2 步**:开发者选项 → 开启 **USB 调试**。
**第 3 步**:开发者选项 → **允许 OEM 解锁**(若已解锁可忽略)。

---

## 4. 解锁 Bootloader

> 如果设备已解锁(本机此前已解锁,`fastboot oem device-info` 显示 unlocked),可跳过本节。

**第 1 步**:开启 OEM 解锁:设置 → 开发者选项 → OEM 解锁 → 开启(若无此选项说明已解锁)。

**第 2 步**:进入 bootloader 并解锁:
```bash
adb reboot bootloader
fastboot oem unlock        # 屏幕确认后执行(会清空数据!)
# 或(部分版本)
fastboot flashing unlock
```

**第 3 步**:解锁完成后设备会重置,重新走 3.3 步骤开启 USB 调试。

> ⚠️ **解锁会清除所有数据并恢复出厂**,此步骤本身就是"全清"的一部分。

---

## 5. 进入 Fastboot / Fastbootd 模式

**方式一:从系统进入 bootloader(刷物理分区用)**:
```bash
adb reboot bootloader      # 屏幕显示 "Fastboot Mode"
```

**方式二:bootloader 下进入 fastbootd(刷动态分区用)**:
```bash
fastboot reboot fastboot   # 屏幕显示 "FastbootD"
```

**查看当前槽位**:
```bash
fastboot getvar current-slot   # 预期: a 或 b
fastboot getvar all | grep -i slot   # 完整槽位信息
```

---

## 6. 清除所有分区数据

**第 1 步**:擦除用户数据(在 bootloader 模式):
```bash
fastboot -w
# 输出:Erasing 'userdata' OKAY / 重新格式化 userdata(约 8-15 秒)
# 说明:A/B 设备无独立 cache 分区,提示 "wipe task partition not found: cache" 属正常
```
> ⚠️ 若报 `not allowed in snapshotted state`:见 7.3 节的快照处理。

**第 2 步**:物理分区先 erase(确保彻底,双槽位都擦):
```bash
fastboot erase boot_a
fastboot erase boot_b
fastboot erase dtbo_a
fastboot erase dtbo_b
fastboot erase misc
# 每个都输出 Erasing ... OKAY 即正常
```

**第 3 步**:动态分区无需单独 erase——刷入完整镜像即完全覆盖(见第 7 节)。

---

## 7. 刷入 LineageOS 20 系统

### 7.1 刷物理分区(bootloader 模式)

**第 1 步**:确认在 bootloader 模式:
```bash
fastboot devices   # 显示设备即正常
```

**第 2 步**:刷 boot(移植内核,双槽位显式刷——`--slot all` 实测不可靠):
```bash
fastboot --slot a flash boot /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/boot.img
fastboot --slot b flash boot /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/boot.img
# 每个输出 Sending 'boot_a/b' OKAY + Writing 'boot_a/b' OKAY
```

**第 3 步**:刷 dtbo(同样双槽位):
```bash
fastboot --slot a flash dtbo /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/dtbo.img
fastboot --slot b flash dtbo /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/dtbo.img
```

**第 4 步**:刷 vbmeta(⚠️ 必须禁验证,否则移植内核 bootloop):
```bash
fastboot flash vbmeta /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/vbmeta.img --disable-verity --disable-verification
fastboot flash vbmeta_system /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/vbmeta_system.img --disable-verity --disable-verification
```

**第 5 步**(可选):刷 recovery(方便以后卡刷):
```bash
fastboot --slot a flash recovery /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/recovery.img
fastboot --slot b flash recovery /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output/recovery.img
```

### 7.2 刷动态分区(fastbootd 模式)

**第 1 步**:进入 fastbootd:
```bash
fastboot reboot fastboot
fastboot getvar current-slot   # 确认
```

**第 2 步**:刷 5 个动态分区镜像(⚠️ fastbootd 下**不能用 `--slot`**,默认刷当前 active 槽):
```bash
cd /Users/weifeng/Downloads/OnePlus8T/payload_dumper/output
fastboot flash system system.img
fastboot flash vendor vendor.img
fastboot flash odm odm.img
fastboot flash product product.img
fastboot flash system_ext system_ext.img
# 每个输出 Sending sparse ... OKAY + Writing 'system_b' OKAY(槽位后缀按当前 active)
```
> ⚠️ 若报 "No such file or directory":目标槽动态分区条目不存在(单 group 共享设计),见下方"双槽位完整指南"。

### 7.3 双槽位完整指南(手把手,2026-08 实测)

> **为什么只有一个槽有系统**:OnePlus 8T 的 super(7GB)内只有一个动态分区组,同一时间只有"当前 active 槽"有动态分区条目。另一槽由 update_engine 安装时才创建。**这不是故障**——boot_a/boot_b 物理分区始终双份。

**第 1 步:确认当前 active 槽(决定要补哪个槽)**
```bash
fastboot getvar current-slot              # bootloader 里查
adb shell getprop ro.boot.slot_suffix     # 系统里查(输出 _a 或 _b)
```
**规则**:`adb sideload` 永远写"当前 active 的相反槽",装完自动切 active 到新槽。
- active=a → sideload 写 **b 槽**,完成后 active 变 b
- active=b → sideload 写 **a 槽**,完成后 active 变 a

**第 2 步:进 recovery 并卡刷**
```bash
adb reboot bootloader
fastboot reboot recovery
# 手机操作:Apply update → Apply from ADB(屏幕显示 "Waiting for ADB Sideload...")
adb sideload /Users/weifeng/Downloads/OnePlus8T/lineage-20.0-20240209-nightly-kebab-signed.zip
# 等 "Total xfer: 1.00x" 出现,随后设备自动安装(约 5-10 分钟)
# 装完提示选 No(不装其他包)→ 返回主菜单 → Reboot to bootloader
fastboot getvar current-slot   # 应已切到新槽
```

**第 3 步:卡刷后必做(否则重启循环/无法 root)**
卡刷会把 boot 写回**官方内核**,必须重刷双槽位**稳定内核**(见第 8 章),并补 su + 重启(见 11.4 节)。

**第 4 步:双槽位完整后的效果**
- 两槽都有系统 + 移植内核,`fastboot set_active a/b` + 重启可自由切换
- `/data` 为两槽共享:ksud、SUSFS 配置、App 数据跨槽保留

**常见问题**:
- **sideload 报 `kInstallDeviceOpenError`(错误码 7)**:上次卡刷的 Virtual A/B **快照未 merge**。解决:先 `fastboot reboot` 让系统正常启动(快照自动 merge),再重新执行第 2 步。
- **`fastboot -w` 报 `not allowed in snapshotted state`**:同上,快照未合并。先启动系统完成 merge,或 `fastboot snapshot-update cancel` 后再 -w。

### 7.4 再次清除用户数据(刷系统后必做)
```bash
fastboot -w
# 输出 Erasing 'userdata' OKAY + 重新格式化
```
> ⚠️ 若报 `not allowed in snapshotted state`:先 `fastboot reboot` 进系统完成快照 merge,或 `fastboot snapshot-update cancel`,再回 bootloader 执行 -w。

---

## 8. 刷入移植内核

> ⚠️ **内核版本选择(实测重要)**:必须用**稳定内核**(CI run **31108984710** 的产物)。最新 CI 内核(如 a6472d7)与卡刷/全新系统不兼容会**无限重启循环**。

**第 1 步**:回到 bootloader:
```bash
fastboot reboot bootloader
```

**第 2 步**:双槽位刷移植内核(必须显式双槽位,`--slot all` 不可靠):
```bash
fastboot --slot a flash boot /path/to/ksu-debug-boot.img
fastboot --slot b flash boot /path/to/ksu-debug-boot.img
# 每个输出 Writing 'boot_a/b' OKAY
```

**第 3 步**:校验并重启:
```bash
fastboot getvar current-slot   # 确认 active
fastboot reboot                # 首次开机(3-5 分钟属正常)
```

> ⚠️ **实测教训**:若 boot 只有单槽位(如仅 boot_b),开机可能**卡系统转圈无法进系统**——重刷双槽位后恢复正常。
> ⚠️ 若走 recovery 卡刷路线(7.3 节):卡刷会覆盖 boot 为官方内核,**刷完必须重新执行本节**。
> ⚠️ 若想先验证官方系统,可先执行第 9 节再回来刷内核。

---

## 9. 首次开机与基础设置

**第 1 步**:等待首次开机(3-5 分钟,出现 LineageOS 向导属正常,勿以为变砖)。

**第 2 步**:完成向导:选择语言 → 连接 WiFi → 跳过/登录(可先跳过) → 设置锁屏(可选)。

**第 3 步**:开启开发者选项 + USB 调试:
- 设置 → 关于手机 → 连续点按版本号 7 次
- 开发者选项 → 开启 **USB 调试**

**第 4 步**:确认 adb 连接:
```bash
adb devices          # 应显示 device(手机弹窗点允许)
adb root             # 首次可能重启 adbd;重复执行直到成功
adb shell id         # 应输出 uid=0(root)
```

---

## 10. WiFi 感叹号修复

> 新装 LineageOS 后 WiFi 可能显示"!",因系统默认走 Google 连通性检测(国内无法访问)。

**第 1 步**:用 adb 设置国内可访问的检测地址:
```bash
adb shell settings put global captive_portal_https_url http://connectivitycheck.gstatic.com/generate_204
adb shell settings put global captive_portal_http_url http://connectivitycheck.gstatic.com/generate_204
adb shell settings put global captive_portal_mode 1
```

**第 2 步**:断开重连 WiFi 或重启,感叹号应消失。

> 若仍感叹号,改用国内检测地址:
> ```bash
> adb shell settings put global captive_portal_https_url http://connect.rom.miui.com/generate_204
> ```

---

## 11. 安装 KernelSU-Next App 与 ksud

### 11.1 安装 App
**第 1 步**:从自己的仓库 CI 下载 manager apk(GitHub Actions:`qcxl/KernelSU-Next` → Build Manager CI → 产物 `manager`)。
**第 2 步**:安装:
```bash
adb install manager*.apk
# 输出 Success 即安装成功
```

### 11.2 首次运行(自动部署 ksud)
**第 1 步**:打开 KernelSU-Next App → 提示"内核已支持"进入主界面。
**第 2 步**:App 首次运行会执行 `ksud install`(部署 busybox / ksud 软链接 / 更新 /data/adb/ksud)。
**第 3 步**:授予 App root 管理权限(若询问)。

> ⚠️ 若首页报"授予 root 权限失败"——KSUN App 内嵌 libksud 访问 SUSFS 标记文件被 SELinux 拒绝(旧版 App/ksud 才有的问题,见 **12.7 节**)。升级 App 到 v3.2.0-206+ 即可。

> ⚠️ **实测(2026-08)**:全新刷机后 `/data/adb/ksud` 可能不存在(ramdisk 注入段执行 `exec /data/adb/ksud post-fs-data` 时文件缺失 → 静默失败;SUSFS 由内核直接应用仍生效,但 su 不可用)。**必须手动部署一次**(或装 App 让 App 部署)。

### 11.3 手动部署 ksud(全新刷机后基本必做)
**第 1 步**:下载 ksud(见 2.2 节,`ksud-aarch64-linux-android` 产物)。
**第 2 步**:推送到设备并部署:
```bash
adb root
adb push ksud /data/local/tmp/
adb shell "cp /data/local/tmp/ksud /data/adb/ksud && chmod 755 /data/adb/ksud"
```

### 11.4 创建 su 并重启(SUSFS 隐藏必需)
**第 1 步**:验证 root 管理:
```bash
adb shell /data/adb/ksud debug version   # 输出 Kernel Version: ...
```

**第 2 步**:创建 su 为**普通文件**(ksud 副本,非符号链接):
```bash
adb shell "mount -o rw,remount / && cp /data/adb/ksud /system/bin/su && chmod 755 /system/bin/su"
```
> ⚠️ 若 cp 报 "No such file or directory":su **已存在且被 SUSFS 隐藏**(内核 boot restore 开机时已标记),**无需重建**,直接跳到第 3 步重启。可用 `dmesg | grep "added sus_path '/system/bin/su'"` 确认。

**第 3 步**:重启(让 SUSFS 重新应用 sus_paths,su 才被加入隐藏列表):
```bash
adb reboot
```

**第 4 步**:重启后验证:
```bash
adb shell "ls /system/bin/su"   # 非 root 应 No such file(隐藏生效)
```

> ⚠️ **注意**:`adb shell su -c ...` 会报 not found——因 adb shell 进程带 app 标记,SUSFS 对它隐藏了 su;`adb root` 后已是 uid=0,直接执行命令即可。授权 App 的 su 走内核 sucompat 重定向,不受影响。**切勿把 su 做成符号链接**(会被 Hunter readlink 检测)。

> ⚠️ **若 su 真丢失(重刷 system 后)**:`cp` 报 "No such file" 有两种情况——(a) su 已存在被 SUSFS 隐藏(**root 视角 `ls /system/bin/su` 能看到**);(b) su 真的不存在 + **SUSFS 内核 boot restore 无条件拦截该路径的 open/rename**(root 视角也是 No such file)——此时**无法通过 cp 重建**(内核拦截),且**切勿用 `adb remount` 尝试**(见 §11.5——会留 overlayfs 痕迹被检测)。App 授权走内核 sucompat 钩子,**不受 su 文件缺失影响**。

### 11.5 ⚠️ 禁止 `adb remount`(overlayfs 残留被检测——完整前因后果)

> **背景(2026-08-13 实测)**:为重建 su 执行 `adb remount`,导致 Hunter 6.6.5+ 报 **「Partition Stat Spoof Detected(sandbox dir)——STAT/MOUNT INCONSISTENCY(2 hit)」** 严重风险。

**前因**:
1. 动态分区下 `mount -o rw,remount /` 不生效(见下);改用 `adb remount` 成功让 /system 可写
2. `adb remount` 实际是给 **/vendor、/odm 挂 overlayfs**(upperdir=`/mnt/scratch/overlay/vendor/upper`、`/mnt/scratch/overlay/odm/upper`)
3. **关键坑:overlayfs 持久化**——Android 检测 `/mnt/scratch` 有数据 → **每次开机 init 自动重挂 overlay**(不是临时挂载,重启不消失!)

**后果(检测原理)**:
- stat `/vendor` 返回底层 dm 设备号 `252:4`(st_dev 走底层),而 `/proc/self/mountinfo` 顶层是 overlay 虚拟设备 `0:23`
- **dev mismatch**:`stat=252:4 vs mountinfo=0:23` → 检测器判定挂载被篡改 → **STAT/MOUNT INCONSISTENCY**
- 影响 /vendor、/odm 两项(2 hit)

**解决方案(清 scratch + 重启)**:
```bash
adb shell "rm -rf /mnt/scratch/overlay/*"   # 清空 overlay 数据(init 检测空 → 不再重挂)
adb reboot
# 验证(必须全过):
adb shell "grep -acE 'overlay.*(vendor|odm)' /proc/self/mountinfo"   # 应 0(无 overlay)
adb shell "grep -aE ' /vendor | /odm ' /proc/self/mountinfo | awk '{print \$3, \$5}'"  # 应 252:4 /vendor、252:0 /odm
adb shell "stat -c '%n %d' /vendor /odm"    # dev 应与 mountinfo 一致(64516=252:4、64512=252:0)
```

**注意事项(防复发)**:
1. **永远不要用 `adb remount`**——它是 /vendor /odm overlayfs 的源头,且持久化(重启不清),被 Hunter 的 stat/mountinfo 一致性检测发现
2. **动态分区 remount 真相**:`mount -o rw,remount /` 对动态分区(/) 不生效(Read-only)——如需写 /system 需先解决 SUSFS 拦截(见 11.4 警示),**不是 remount 能绕过的**
3. 若已执行过 `adb remount`(即使没写文件):**开机后立即查 `grep -c overlay /proc/self/mountinfo`**——非 0 就按上面方案清理
4. 检测后:**重新打开 Hunter 刷新**——「Partition Stat Spoof」应消失(其余检测项不受影响)

---

## 12. SUSFS 隐藏配置(银行 App 检测)

> 移植内核含 SUSFS,需配置隐藏项让银行 App(农业/兴业/支付宝/微信)检测不到 root。

### 12.1 配置 susfs_config.json
**第 1 步**:写入配置(路径:`/data/adb/ksu/susfs_config.json`),参考:

```json
{
  "uname_release": "4.19.304",
  "uname_version": "#2 SMP PREEMPT Fri Feb 9 00:58:10 UTC 2024",
  "sus_paths": [
    "/system/bin/su",
    "/odm/bin/su",
    "/data/adb/ksu/su",
    "/system/addon.d",
    "/system/build.prop",
    "/sys/module/kernelsu",
    "/dev/ksu_init_diag.log",
    "/dev/susfs_ksu_applied"
  ],
  "sus_path_loops": [],
  "sus_maps": ["/data/adb/"],
  "sus_mounts": ["/vendor", "/odm"],
  "enable_log": false,
  "enable_avc_log_spoofing": true,
  "hide_sus_mnts": true,
  "set_props": {
    "ro.build.type": "user",
    "ro.system_ext.build.type": "user",
    "ro.odm.build.type": "user",
    "ro.boot.flash.locked": "1",
    "ro.boot.warranty_bit": "0",
    "ro.build.flavor": "OnePlus8T-user",
    "ro.build.host": "rd-build-193",
    "ro.product.build.type": "user",
    "ro.vendor.build.type": "user",
    "ro.boot.verifiedbootstate": "green",
    "ro.debuggable": "0",
    "ro.system.build.type": "user",
    "ro.build.user": "jenkins",
    "ro.vendor_dlkm.build.type": "user",
    "ro.build.display.id": "RKQ1.211119.001",
    "ro.lineage.version": "",
    "ro.lineage.build.version": "",
    "ro.lineage.build.version.plat.rev": "",
    "ro.lineage.build.version.plat.sdk": "",
    "ro.lineage.device": "",
    "ro.lineage.display.version": "",
    "ro.lineage.releasetype": "",
    "ro.lineagelegal.url": "",
    "ro.modversion": ""
  },
  "delete_props": []
}
```

> 说明:文件不存在则创建;已存在则覆盖。可用本地编辑后 push。
>
> **⚠️ 禁止向 `set_props` 添加 `ro.build.version.security_patch` / `ro.vendor.build.security_patch`**:
> - 原因:Hunter 6.6.5(magiskkiller 内核)**检测 Build Identity 一致性**——对比 `Build.VERSION.SECURITY_PATCH`(zygote 启动缓存,真实值)与 `getprop ro.build.version.security_patch`(SUSFS 伪装值)——两者不一致直接报 **BUILD IDENTITY STRONG HIT** 与 **ROM PARTITION STRONG HIT** 两个高危项。
> - 2026-08-13 实测:移除这两条后 `getprop` 回真实值 2024-01-05,与 Build 缓存一致,STRONG HIT 全部消除(Build Identity Source Mismatch 降级为 Build Identity Consistency Check,全部字段一致)。
> - 同理,任何"伪装值 ≠ zygote 启动时读到的真实值"的 set_props 都存在被此类一致性检测命中的风险;若需伪装某属性,必须保证伪装值在 zygote 启动前生效(内核 early-props 方案)或与真实值一致。

### 12.2 应用配置
```bash
adb root
adb push susfs_config.json /data/local/tmp/
adb shell "cp /data/local/tmp/susfs_config.json /data/adb/ksu/susfs_config.json && chmod 644 /data/adb/ksu/susfs_config.json"
adb reboot          # 重启后自动应用
```

### 12.3 验证隐藏
```bash
# App 视角(非 root 的 adb shell):应 ENOENT
adb shell "ls /sys/module/kernelsu 2>&1"   # 应 No such file
adb shell "ls /system/bin/su 2>&1"         # 应 No such file
adb shell "cat /proc/version"              # 官方样式,无 -g<hash>-dirty
# root 视角(adb root 也带 app 标记,访问隐藏路径同样 ENOENT,属正常)
adb root && adb shell "ls /sys/module/kernelsu"   # 可能同样 No such file(正常)
```

### 12.4 `/system/bin/su` 的完整修复(Hunter 检测 + SUSFS 隐藏)

**现象**:Hunter 环境检测出现 3 项 `/system/bin/su` 风险:
1. `Check Find Root File(... /system/bin/su)`(server_iso / main_process 两个进程)
2. `Find Root File In Sniff(access find root file /system/bin/su)`

**问题一:符号链接被 readlink 检测(已修复)**

**根因**:`/system/bin/su` 若为**符号链接**(如 `su -> /data/adb/ksud`),Hunter 用 `readlink` 即可识别出 root 文件。

**修复**:把 su 做成**普通文件**(ksud 的副本,非符号链接),`readlink` 返回失败,Hunter 的 readlink 检测不再命中。

**问题二:SUSFS 的 sus_paths 隐藏不生效(首次刷机关键!)**

**根因**:SUSFS 添加 sus_path 时,若**文件当时不存在则添加失败**(`susfs_update_sus_path_inode()` 的 `kern_path` 失败即跳过)。首次刷机后 `/system/bin/su` 是**手动 cp 创建的**(开机时不存在)→ 开机应用 SUSFS 配置时该 sus_path **未被添加** → 后续 cp 出的 su 一直没被隐藏 → Hunter 的 access/stat 检测到。

**修复(必须重启)**:cp 出 su 后**重启设备**,SUSFS 重新应用配置时 su 已存在 → 添加成功 → 隐藏生效。

首次刷机/重刷 system 后的完整操作顺序(缺一不可):

```bash
# ① 手动部署 ksud(第 11.3 节,若尚未部署)
adb root
# ② 创建 su 为普通文件(ksud 副本,非符号链接)
adb shell "mount -o rw,remount / && cp /data/adb/ksud /system/bin/su && chmod 755 /system/bin/su"
#    ⚠️ 若 cp 报 "No such file or directory":通常是 su **已存在且被 SUSFS 隐藏**(内核 boot restore
#    在开机时已把 /system/bin/su 加入 sus_paths 并标记 inode,带 app 标记的进程访问它返回 ENOENT,
#    即使 adb root 也一样)。此时无需重建,直接跳到 ③ 重启;用 `dmesg | grep "added sus_path '/system/bin/su'"`
#    可确认(能查到=已隐藏)。若确认文件真的不存在,才需要创建(可临时把 susfs_config.json 中该路径移除并重启,cp 后再恢复)。
# ③ 必须重启,让 SUSFS 重新应用 sus_paths(su 已存在才能被加入隐藏列表)
adb reboot
# ④ 重启后验证(以下在非 root 的 adb shell 下执行):
adb shell "ls /system/bin/su"        # 应:No such file(隐藏生效)
adb shell "readlink /system/bin/su; echo rc=\$?"  # 应 rc=1(不可见)
```

**隐藏生效后的副作用(属正常,勿改)**:
- `adb shell su -c ...` 会报 not found——因为 adb shell 进程带 app 标记,SUSFS 对它隐藏了 su;**但 `adb root` 后 shell 已是 uid=0,直接执行命令即可,无需 su**。
- 真正 root 进程(ksud/init)仍可见 su;授权 App 执行 su 走内核 sucompat 重定向,**不受隐藏影响**。

**注意**:卡刷 LineageOS 或重刷 system 后 `/system/bin/su` 会被清掉,需重新执行上述 ①②③;**切勿把 su 做成符号链接**(会被 Hunter readlink 检测)。

### 12.5 TEESimulator 固化(方案 Y)——Momo "TEE 损坏" 修复,开机全自动

**背景**:解锁 + 移植内核后 keymaster/TEE 失效,keystore2 报 `ErrorCode(-10003)`,Momo 显示 **"TEE 损坏"**。
**方案**:TEESimulator 注入 keystore2,软件模拟硬件密钥 + 伪造 attestation 证书链。已固化进内核(方案 Y),
刷机后部署一次文件,之后**每次开机全自动生效**(无需手动操作)。

**完整指南见独立文档**:`OnePlus8T_TEESimulator_方案Y_完整指南.md`

**快速部署(3 步)**:

```bash
# 1. 前提:已刷方案 Y 内核(含 TEESimulator 注入段,见 8 章;最新构建见 GitHub Actions)
# 2. 部署文件(一次性,需 adb root):
bash install-teesim.sh     # 仓库 build-kernelsu-susfs 根目录
# 3. 重启,开机后验证:
adb reboot
adb shell "ps -A | grep TEESimulator"                      # 应见进程
adb shell "grep -c libTEESimulator /proc/\$(pidof keystore2)/maps"  # 应 ≥ 3
```

**验证**:Momo "TEE 损坏" 消失;兴业银行 / 农业银行正常;Hunter 正常。

**关键注意**:
- **禁止运行时 `ksud sepolicy patch`**(keystore 规则已编译期内核固化;运行时 patch 实测会导致设备崩溃重启)
- `susfs_config.json` 的 `set_props` **不得**含 `persist.sys.usb.config`(否则每次重启关闭 USB 调试)
- 完整 -w 刷机后需重新执行第 2 步部署;仅 OTA/重刷 boot 则 `/data` 保留,无需重新部署

### 12.6 selinux_hide 修复(luna / 春秋 Native Check 的 Root+KernelSU 检测)

**背景**:luna(icu.nullptr.nativetest)报 "1. Root 环境 2. 发现 KernelSU";春秋 Native Check 报 "app zygote SELinux oracle found KSU context"。

**根因**:`selinux_hide`(feature 4)启用了,但 3 个 oracle 接口中只有 `setprocattr` 返回 `-EINVAL`;
`/sys/fs/selinux/context` 写返回**假成功**、`/sys/fs/selinux/access` 写返回**全允许 av 决策**——luna 的
`SelinuxContextOracleService` 与 Native Check 的 `detectSelinuxAccessOracleAnomaly` 正是靠这两个接口
探测 "ksu 域是否存在",收到假成功/全允许即判定 `ksuDomain=yes`。

**修复**:内核提交 `597688c`(`kernel-patches/unified-selinux_hide.c`)——context/access 对含 ksu 的
写/查询统一返回 **`-EINVAL`**(镜像"无 ksu 域的干净内核");`setprocattr` 覆盖全部 attr name
(`current/exec/prev/fscreate/keycreate/sockcreate`)。

**验证(实测通过)**:
```
luna   : SELinux oracle result=0 ksu_domain=0 ksu_file=0 magisk_file=0
luna   : ksuDomain=no → UI 上 Root 和 KernelSU 告警消失
Native Check: Root 和 KernelSU 告警消失
```

**luna 剩余显示项(非 root 检测,无需处理)**:
- `Security update: 2024-01-05` = OnePlus 8T + Android 13 的**设备指纹展示**(三个工具显示一致;不从系统属性/attestation 证书读,当前属性已伪装 2024-02-05)——不是检测项。
- `模块扫描 / 备用机 / 云机 / 新机 / 不建议使用支付社交购物游戏` = 设备指纹与综合建议类,不影响银行 App。

**经验**:检测值先确认数据源(属性 / 证书 / 指纹库)再动手;针对 "Security update" 的 TEESimulator
`security_patch.txt` 配置与 imported-attest 修改已确认无效并回滚(详见方案 Y 指南 §11)。

---

### 12.7 已知问题:KSUN App 提示"授予 root 权限失败"(v3.2.0-205 及更早)

**症状**:打开 KernelSU-Next App → 首页报"授予 root 权限失败! 点击重启管理器进程",杀进程重启无效。

**根因**:KSUN App 内嵌 `libksud` 以 `untrusted_app` 域执行 `restore_if_needed()`(SUSFS 配置恢复),
访问 `/dev/susfs_ksu_applied` 标记文件被 SELinux 拒绝(`avc: denied { getattr/write }`)
→ `Path::exists()` 误判"配置未应用" → 每次启动重复执行 SUSFS apply(App 无 root 权限)
→ `ioctl permission denied` → App 报错。

**修复**:
- **根治**:升级 KSUN App 到 **v3.2.0-206-gabc9ea6f+**(已内置:标记检查容错 + 创建标记后自动
  `chcon u:object_r:shell_data_file:s0`)。注意旧版升级会报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`
  (签名不同)→ **先卸载再安装**(App 数据无关键内容;root 授权列表在内核/ksud 侧,重装后重新授权)。
- **应急(重启失效)**:`adb root && adb shell chcon u:object_r:shell_data_file:s0 /dev/susfs_ksu_applied`。

**预防**:ksud 与 App 用同版本(旧版 App 会用内嵌旧 libksud **覆盖** `/data/adb/ksud` 回旧版,
导致下次重启标记不再自动 chcon,问题复发)。

**验证**:App 首页显示"工作中";`logcat | grep susfs_ksu_applied` 无 `avc: denied`。

---

### 12.8 小骨检测"CPU 伪装检测"(cpuinfo 与 Build.HARDWARE 不匹配)

**症状**:小骨(com.envdetector)报危险项"CPU伪装检测":`cpuinfo Hardware(Qualcomm Technologies,Inc SM8250)显示骁龙处理器,但 Build.HARDWARE=qcom 不匹配任何已知骁龙处理型号,疑改机`。

**根因**:检测器判定规则 = cpuinfo Hardware 含 "Qualcomm"(声称骁龙)且 Build.HARDWARE 不含任何已知骁龙型号(sm/sdm/msm 前缀,knownSnapdragonHardware 列表)→ 不一致。`qcom` 是合法高通平台代号(官方 OnePlus 8T 也如此),但检测器不认识 → 误报/通病。

**修复(内核 7d59126,已刷入)**:改 `drivers/soc/qcom/socinfo.c` 的 `msm_read_hardware_id` 初始前缀为 `"qcom "` → `/proc/cpuinfo` Hardware 输出 `qcom SM8250`(无 "Qualcomm"、含 "qcom")。这样:① 不触发"声称骁龙但 Build 不匹配"分支;② cpuinfo 含 Build.HARDWARE 的 "qcom"(双向 contains 通过);③ 保留 SoC 型号 SM8250。

**注意**:`patch -p1 --forward --fuzz=3 < ../kernel-patches/fix_cpuinfo_hardware_qcom.patch` 已在 CI 构建流程(build-ksu-debug.yml)中应用,重新构建内核即包含此修复。

**验证**:`adb shell grep Hardware /proc/cpuinfo` 显示 `qcom SM8250`;小骨 CPU 伪装检测消失。

---

### 12.9 KSUN App Profile 模板页拉取不到数据(模板目录权限)

**症状**:KSUN App 打开 App Profile 模板页面拉取不到数据;logcat 报 `ksud::cli: Error: /data/adb/ksu/profile/templates/ is not a regular directory`。

**根因**:`/data/adb/ksu/profile/templates/` 由 ksud(root)创建为 **0700 root + adb_data_file**;而 KSUN App 内嵌 libksud 以 **untrusted_app 域**运行,读写该目录被 SELinux/文件权限拒绝 → `ensure_dir_exists` 的 `create_dir_all` EACCES → 报"is not a regular directory"。与 12.7 是同一类问题(App 内嵌 libksud 访问 root 私有文件)。

**修复(ksud a2911540,已部署 v3.2.0-207)**:开机 post-fs-data(root 上下文)预创建 `profile/`、`templates/`、`selinux/` 并设为 **0777 + shell_data_file**(`ensure_profile_dirs_accessible()`,幂等)。刷机/清 data 后开机自动生效,**零手动操作**。

**应急(旧版 ksud)**:
```bash
adb root && adb shell "chmod 0777 /data/adb/ksu/profile/templates && chcon u:object_r:shell_data_file:s0 /data/adb/ksu/profile/templates"
```
(重启失效,需每次执行;升级到 v3.2.0-207+ 根治)

**验证**:`adb shell ls -laZ /data/adb/ksu/profile/templates/` 显示 `drwxrwxrwx ... shell_data_file`;App Profile 模板页正常显示模板。

---

### 12.10 Duck Detector "Native Root"(prctl 探测)与 /proc/version 内核标识伪装

**症状**:Duck Detector 检测到:
- `Native Root: Danger — KernelSU detected via prctl: prctl(0xDEADBEEF, 2) returned KernelSU version 1`
- `Kernel Check: Kernel identity contains maintainer-style @ mentions`(先后命中 `@lineageos`、`@google`)
- 小骨检测:"内核可疑后缀 `[-perf]`"

**根因**:
1. **prctl(0xDEADBEEF, 2) 泄露**:KSUN 内核 `ksu_handle_prctl`(由 `scripts/inject-ksu-prctl.py` 注入)的 get_info 分支**无条件返回 KERNEL_SU_VERSION**。检测器调用 `prctl(0xDEADBEEF, 2, 0, 0, 0)`(arg3=NULL,version 指针无效),内核 copy_to_user 失败但**返回值 1 仍泄露**——Duck Detector 看到返回值 ≥ 1 即判定 "KernelSU version 1"。
2. **/proc/version 三方特征**:`buildbot@lineageos`(CI 的 KBUILD_BUILD_USER/HOST)+ `4.19.304-perf`(`kona-perf_defconfig`/`ksu.config.original` 的 CONFIG_LOCALVERSION + make 命令行 LOCALVERSION)+ `@` 分隔符(linux_banner 中 `LINUX_COMPILE_BY "@" LINUX_COMPILE_HOST`)——检测器视为自定义内核/第三方 ROM 特征。**注意 `@google.com` 也会被 @-mentions 命中,必须去掉 @ 而非只换域名**。

**修复(内核构建,提交 bd0b67f → b6cb051 → 29524cf)**:
1. **prctl 反检测**(`scripts/inject-ksu-prctl.py`):get_info 分支加 manager uid 检查——**只有已注册 manager(KSUN App)返回 version,其他进程返回 `-EINVAL`**(镜像原版内核);同时移除原无条件 `ksu_set_manager_appid()` 自动注册(任何 App 探测一下就把自己注册成 manager 的安全隐患)。KSUN App 的 libksud 走 IOCTL `KSU_IOCTL_GET_INFO` 获取信息,不依赖 prctl get_info,故无副作用。
2. **CI workflow**(`build-ksu-debug.yml`):
   - `KBUILD_BUILD_USER=buildbot` → `android-build`;`KBUILD_BUILD_HOST=lineageos` → `google.com`
   - make 命令行 `LOCALVERSION=-perf` → `LOCALVERSION=`(空)(注:仅改 ksu.config.original 的 CONFIG_LOCALVERSION 不够,setlocalversion 会把 CONFIG_LOCALVERSION 与命令行 LOCALVERSION 拼接)
   - 新增 patch 步骤:sed 改 `init/version.c` 的 `LINUX_COMPILE_BY "@"` → `LINUX_COMPILE_BY "."`(linux_banner 与 linux_proc_banner **两处**都改,消除 @ 提及)
3. **`kernel-patches/ksu.config.original`**:`CONFIG_LOCALVERSION="-perf"` → `""`;`CONFIG_LOCALVERSION_AUTO=y` → `n`

**刷入后 /proc/version**(预期形态):
```
Linux version 4.19.304 (android-build.google.com) (Android (8490178, based on r450784d) clang version 14.0.6 (...), LLD 14.0.6) #2 SMP PREEMPT Fri Feb 9 00:58:10 UTC 2024
```

**验证**:
```bash
adb shell cat /proc/version   # 无 -perf、无 @、无 buildbot@lineageos
# Duck Detector:Kernel Check 从 Top findings 消失;Native Root 的
# nativeFiles/nativePolicy/nativeSymbols/nativeLibrary 全部 Clean
# KSUN App:"工作中" + 超级用户授权正常(manager 权限不受影响)
```

**注意**:清 data 重刷后首次开机,KSUN App 通过 IOCTL auto-crown 注册 manager;在注册前若 App 依赖 prctl get_info 会失败——但实测 auto-crown 已覆盖该路径,无影响。

---

### 12.11 Hunter 6.6.5 高风险检测应对(2026-08-13 实测)

Hunter 升级到 6.6.5 后集成 `magiskkiller`(canyie)SELinux policy 检测 + Build 一致性检测,主页顶部出现「黑灰产设备,当前程序已经被Hook&修改!」红色判定。逐项展开详情后确认根因如下:

**8 项检测详情与根因(展开详情实测):**

| # | 检测项 | 判定 | 根因 | 是否已解决 |
|---|---|---|---|---|
| 1 | ROM Partition Source Mismatch | 🔴 STRONG HIT | security_patch prop=2024-02-05 vs Java=2024-01-05 | ✅ 已解决(移除伪装) |
| 2 | SELinux Root Policy Marker | 信息 | `ROOT_POLICY_TOKEN:adbroot@system_ext_sepolicy.cil` + `product_sepolicy.cil`(LineageOS 官方 policy 自带) | ➖ 未处理(信息级) |
| 3 | APatch SELinux Policy Suspected | 🟡 SUSPECTED | `contextEvidence=1, accessEvidence=1(access:7,11,12,131)`, `APATCH_MISSING_MAGISK_COMPAT_CONTEXT` | ➖ 残留(KSU policy 特征) |
| 4 | independent SELinux Policy Risks | 🔴 | `riskCodes=[AOSP_SU_TRANSITION, ADB_ROOT_CONTEXT, ZYGISK_NEXT_POLICY]` | ➖ 残留(KSU 加载的 policy 含 su 域/Zygisk 规则) |
| 5 | 当前设备机型&ROM可能被修改 | 🔴 | 「OnePlus环境信息查询失败!当前系统非ROM原生系统!」——LineageOS 非 OnePlus 原生,缺 OnePlus 专属组件;服务列表 246 个含 `adbroot_service` | ⚠️ 根本(需 OnePlus 原生 ROM) |
| 6 | Automation/Input Injection Weak Signal | 🟡 WEAK(score=38) | `Developer options enabled` + `ADB debugging enabled` + 非 AOSP 设备用 AOSP Latin IME | 🟡 可改善(关开发者选项) |
| 7 | Kernel Runtime Consistency Incomplete | 信息 | 详情全一致(pid/uid/seccomp/uname)——判定完整性不足 | ➖ 信息级 |
| 8 | Build Identity Source Mismatch | 🔴 STRONG HIT | 同 #1:security_patch Java=2024-01-05 vs prop=2024-02-05 | ✅ 已解决(移除伪装) |

**解决方案(已实施并验证):**

1. **移除 `ro.build.version.security_patch` / `ro.vendor.build.security_patch` 伪装(见 12.1 警告)**
   - 改后 `getprop ro.build.version.security_patch = 2024-01-05`(真实值,与 Build 缓存一致)
   - 实测:#8「Build Identity Source Mismatch」消失,降级为「Build Identity Consistency Check」且全部字段一致(fingerprint/build id/display_id/incremental/build_type/tags/sdk/release/brand/manufacturer/model);#1「ROM Partition Source Mismatch」同步消除
2. **其余项为 SELinux policy 痕迹 + 非原生 ROM 差异**,属性伪装无法消除:
   - su 域 transition / adbroot context / Zygisk Next 规则 = KSU-Next + SUSFS + ReZygisk 加载到内核 policy 的特征(6.6.5 新增 magiskkiller 检测面)
   - 「非 ROM 原生系统」= LineageOS 与 OnePlus 原生组件差异(属性层面无解)
   - 若要进一步压制,方向:改 `/system_ext/etc/selinux/system_ext_sepolicy.cil` 与 `/product/etc/selinux/product_sepolicy.cil` 文件内容(去 adbroot token,文件无 verity 强校验)+ 关闭开发者选项/ADB(弱信号)——需评估对 SELinux/调试的影响

3. **追加处理(同日实测,均验证通过)**:
   - **Custom ROM Identity Contradiction(STRONG HIT)**:`CUSTOM_ROM_MARKER_CONTRADICTS_OEM_IDENTITY`——brand/manufacturer=oneplus(OEM 身份)但 `ro.modversion`/`ro.lineage.*`(LineageOS 标记)存在 → 矛盾。**方案**:`susfs_config.json` 的 `set_props` 必须用 **dict 格式**(`{"ro.lineage.version": "", ...}`——注意旧 list 格式只有属性名、置空不生效),把 9 条 lineage/modversion 属性置空字符串:`ro.modversion`、`ro.lineage.version`、`ro.lineage.build.version`、`ro.lineage.build.version.plat.rev`、`ro.lineage.build.version.plat.sdk`、`ro.lineagelegal.url`、`ro.lineage.releasetype`、`ro.lineage.device`、`ro.lineage.display.version`。⚠️ **禁止用 `delete_props` 删除**(会清零属性名首字节、破坏属性区 trie,留"洞"反而被 Hunter 检测;ksud 源码注释明确此点)。改后 `getprop ro.lineage.*` 全空,Custom ROM 项消失。
   - **SELinux Root Policy Marker**:`ROOT_POLICY_TOKEN:adbroot@system_ext_sepolicy.cil / product_sepolicy.cil`——LineageOS 官方 policy 文件(0444 可读)里定义了 `adbroot` 域(`typeattributeset domain (... adbroot ...)` 等)——OEM 原生 policy 无此域 → 判为非 OEM 标记。**方案**:`sus_paths` 添加 `/system_ext/etc/selinux/system_ext_sepolicy.cil` + `/product/etc/selinux/product_sepolicy.cil` → App 读不到显示 `<missing>`(同 plat_sepolicy.cil 的 SELinux 限制待遇——"diagnostic only" 非风险),Marker 项消失。
   - 处理后顶部判定从「黑灰产设备」**降级为「高风险设备,可能存在攻击行为!」**——剩余项为 APatch Suspected(内核运行时 policy 的 KSU 特征,文件层无法消除)、机型&ROM 修改(LineageOS 非原生)、Automation 弱信号(USB 调试/开发者模式)。

4. **独立 SELinux Policy Risks / APatch Suspected(内核级根治,提交 `7bf9edb`)**
   - **根因**:`riskCodes=[AOSP_SU_TRANSITION, ADB_ROOT_CONTEXT, ZYGISK_NEXT_POLICY]`——magiskkiller 通过 context-oracle(写 `/sys/fs/selinux/context` 探测 `u:r:su:s0` / `u:r:adbroot:s0` / `u:r:zygisk:s0` 等)推断域是否存在。原 `selinux_hide.c` 的过滤函数 `buf_mentions_ksu()` 只匹配 `:ksu:`/`:ksu_`/`u:r:ksu:s0`——su/adbroot/zygisk 不匹配 → 走真实 policy 判定(KSU 加载的 su 规则 + LineageOS 原生 adbroot 域)→ 命中。
   - **方案**(改 `kernel-patches/unified-selinux_hide.c` 的 `buf_mentions_ksu`):扩展黑名单匹配 `:su:`、`adbroot`、`magisk`、`zygisk`、`xposed`、`lsposed`、`kernelsu`——`my_write_context`/`my_write_access` 对命中返回 **-EINVAL**(模拟"域不存在",与真实无 root 内核一致;不能返回假成功——会暴露"域存在且可查")。CI 的 "Apply unified selinux_hide.c" 步骤自动用该文件覆盖 `drivers/kernelsu/feature/selinux_hide.c`,无需改上游 KSU 源。
   - **验证**(刷入后):Hunter 的 `independent SELinux Policy Risks` + `APatch SELinux Policy Suspected` **合并降级为 `SELinux Policy Check Inconclusive`**——`oracleTrust=INCONCLUSIVE`、`product=UNKNOWN`、`contextEvidence=0`、`accessEvidence=0`、`riskCodes=[]`;**顶部「黑灰产设备/高风险设备」大判定标题完全消失**。
     - **Inconclusive 说明(2026-08-13 决策:保持现状)**:`oracleReasons=[ACCESS_UNAVAILABLE:41]` 源于 `my_write_access` 对 root 域探测返回 -EINVAL(magiskkiller 判定"oracle 探测不可用")。这是可接受的最优状态:riskCodes 空、顶部判定消失、银行 App/KSUN 正常。备选(改返回 denied 决策模拟真实 LineageOS、可能变 TRUSTED)需重建内核+全面回归,收益不确定且有重新暴露风险——**已决定不实验,保持 Inconclusive**。
   - **剩余项**(仅 2 项非高危):「当前设备机型&ROM可能被修改」(LineageOS 非 OnePlus 原生——需原生 ROM)、「Automation/Input Injection Weak Signal」(开发者模式+USB 调试开启——弱信号)。均无资金安全类强信号,银行 App/KSUN 功能不受影响。

**结论**:核心高危项(#1/#8 STRONG HIT + Custom ROM + SELinux Root Policy Marker + independent SELinux Policy Risks/APatch)已全部消除;顶部聚合判定消失,仅剩 2 项非高危(机型差异/调试弱信号),银行 App/KSUN 功能不受影响。

## 13. 最终验证清单

```bash
# 1. 系统版本
adb shell getprop ro.build.version.release        # 13 (Android 13)

# 2. 内核(移植内核 + 官方样式版本)
adb shell cat /proc/version   # Linux version 4.19.304 (android-build.google.com) ... 无 -perf、无 @、无 -g<hash>-dirty

# 3. root 管理(需 adb root 才能访问 /data/adb)
adb root
adb shell "/data/adb/ksud debug version"   # Kernel Version: ...

# 4. 稳定性(无重启循环)
adb shell cat /proc/uptime     # 持续增长
adb shell getprop sys.boot_completed   # 1
```

**人工验证(手机上)**:
- **银行 App**:农业银行无 root 弹窗;兴业银行无 110;支付宝/微信正常
- **环境检测**:Momo 无 root/Zygisk 注入告警、无 "TEE 损坏";Hunter 无 /system/bin/su、/sys/module/kernelsu 检测项
- **Duck Detector**:Kernel Check 无 @ mentions、无 -perf;Native Root 的 nativeFiles/nativePolicy/nativeSymbols/nativeLibrary 全 Clean(prctl 反检测,见 12.10)
- **luna / 春秋 Native Check**:无 "Root 环境"、无 "发现 KernelSU"、无 "SELinux oracle found KSU context"(selinux_hide 修复,见 12.6);"Security update: 2024-01-05" 为设备指纹展示,非风险项
- **root 功能**:用 root 管理器授权的 App(如终端模拟器)执行 su 应能提权

**可选:固定 120Hz(KSUN App 闪屏规避)**:
```bash
adb shell settings put system peak_refresh_rate 120
adb shell settings put system min_refresh_rate 120
```

---

## 14. 注意事项与救砖

### 14.1 注意事项
| 注意项 | 说明 |
|---|---|
| **数据全清** | 解锁 + `-w` + 刷镜像 = 所有分区数据清空,务必先备份 |
| **电量** | 刷机全程保持 ≥ 50%,建议插线 |
| **原装线/接口** | 用原装 USB-C 数据线,避免传输中断 |
| **勿中断刷写** | fastboot 刷写中不要拔线/强制关机 |
| **双槽位** | 物理分区(boot/dtbo/recovery)双份都刷;动态分区为单 group 共享,切槽前需先把系统装进目标槽(7.3 节) |
| **vbmeta 必须禁验证** | 移植内核自编译签名,不禁用 AVB 必 bootloop |
| **内核用稳定版** | 最新 CI 内核可能重启循环,用验证过的稳定内核(8 章) |
| **卡刷后重刷内核** | recovery 卡刷会把 boot 写回官方,必须重新刷移植内核 |
| **首次开机慢** | 3-5 分钟属正常,勿以为变砖 |
| **WiFi 感叹号** | 见第 10 节,首次安装必做 |
| **银行检测** | 保持无 Zygisk 注入 + SUSFS 隐藏配置(第 12 节) |

### 14.2 救砖(常见问题)

**Q1: 刷完 bootloop(无限重启)**
```bash
# 进 bootloader 重刷 vbmeta(禁用验证) + 移植内核(用验证过的稳定版本!)
adb reboot bootloader
fastboot flash vbmeta vbmeta.img --disable-verity --disable-verification
fastboot flash vbmeta_system vbmeta_system.img --disable-verity --disable-verification
fastboot --slot a flash boot ksu-debug-boot.img
fastboot --slot b flash boot ksu-debug-boot.img
fastboot -w && fastboot reboot
# 若 -w 报 snapshotted state:先 fastboot reboot 进系统完成快照 merge(或 snapshot-update cancel)再 -w
```

> 💡 **bootloop 常见根因**:①boot 只有单槽位(必须双槽位刷)②用了最新未验证内核(换稳定版)③vbmeta 未禁验证 ④卡刷后未重刷移植内核。

**Q2: 卡在 fastboot 无法进系统**
```bash
# 重新完整走第 7-8 节流程,确认双槽位 + vbmeta
```

**Q3: 完全黑屏/无法进入任何模式(救砖/EDL)**
```bash
# 1. 长按电源+音量上 强制重启
# 2. 若无效,进入 EDL 模式:关机状态长按音量上+下(或 fastboot oem edl)
# 3. EDL 需 MSM 工具(OnePlus 官方救砖包),此处不展开
```

**Q4: adb 连不上**
```bash
# 换线/换口,开发者选项确认 USB 调试开启
adb kill-server && adb start-server && adb devices
```

### 14.3 附录:payload 提取命令(如需重新提取)
```bash
cd /Users/weifeng/Downloads/OnePlus8T/payload_dumper
python3 payload_dumper.py \
  --partitions boot,dtbo,odm,product,recovery,system,system_ext,vbmeta,vbmeta_system,vendor \
  ../lineage-20.0-20240209-nightly-kebab-signed/payload.bin \
  -o output/
```

---

*文档结束。刷机有风险,操作前请通读全文;有任何一步不确定,先停下来确认。严格按照总流程的顺序执行,勿跳步。*
