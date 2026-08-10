# OnePlus 8T — luna(icu.nullptr.nativetest)逆向分析报告

> 版本:2026-08-08
> 目标:逆向 luna 检测机制,定位 "黑灰产设备 8/8 / 模块扫描 / 备用机·云机·新机" 等显示的判定依据与底层调用,为隐藏方案提供依据。
> 结论摘要:见 §10。核心逆向成果(字符串解密算法、检测函数映射、判定链)见 §5-§8。

---

## 目录

1. [概述与目标](#1-概述与目标)
2. [环境与工具](#2-环境与工具)
3. [luna 总体架构](#3-luna-总体架构)
4. [关键资源与检测项映射](#4-关键资源与检测项映射)
5. [字符串加密算法(核心逆向成果)](#5-字符串加密算法核心逆向成果)
6. [检测函数详细分析(native JNI)](#6-检测函数详细分析native-jni)
7. [检测函数详细分析(Java 层)](#7-检测函数详细分析java-层)
8. [判定链:"黑灰产设备" 标题的触发机制](#8-判定链黑灰产设备-标题的触发机制)
9. [动态排查记录(排除清单)](#9-动态排查记录排除清单)
10. [结论:各显示项的根因](#10-结论各显示项的根因)
11. [与 root 隐藏相关的检测(selinux oracle)](#11-与-root-隐藏相关的检测selinux-oracle)
12. [网络环境检查](#12-网络环境检查)
13. [遗留问题与后续分析方向](#13-遗留问题与后续分析方向)
14. [附录 A:IDA MCP 调用方法](#14-附录-aida-mcp-调用方法)
15. [附录 B:字符串解密脚本](#15-附录-b字符串解密脚本)

---

## 1. 概述与目标

### 1.1 背景

设备:OnePlus 8T(KB2000),LineageOS 20(Android 13),KernelSU-Next + SUSFS + TEESimulator(方案 Y 固化)。

luna(包名 `icu.nullptr.nativetest`,APK 文件名 `luna1435.apk`,约 4.9MB)顶部显示:

```
黑灰产设备 8/8 ********
*模块扫描 *备用机 *云机 *新机
*OnePlus | Android 13 Security update: 2024-01-05
⚠️ 该设备不建议使用:支付,社交,购物,游戏类应用避免账号被封禁
```

其中 "Security update: 2024-01-05" 已确认是设备指纹展示(见 §11.3)。本报告聚焦 "黑灰产设备 8/8" 与 "模块扫描" 的判定依据。

### 1.2 目标

1. 确定 "黑灰产设备" 标题的触发条件(哪个检测、返回什么值)
2. 确定 "模块扫描"(step8)的检测点与命中源
3. 破解 libBugly.so 的字符串加密,还原各检测的底层方法
4. 评估可解决性(不影响银行 App / KernelSU-Next App / Momo / Native Check)

---

## 2. 环境与工具

| 工具 | 用途 | 备注 |
|---|---|---|
| `unzip` | 解包 APK | `luna1435.apk` → `classes.dex`(1.5MB)+ `lib/arm64-v8a/libBugly.so` |
| `jadx 1.5.1` | Java 反编译 | 对 luna 的 dex 反编译慢/卡,主要用作辅助 |
| `apktool-mcp`(localhost:8652) | smali 解码 | 工作区限制:`/Users/weifeng/Downloads/OnePlus8T/apktool_mcp_server_workspace/` 内操作;`decode_apk` 得完整 smali |
| `ida-pro-mcp`(localhost:**8745**,非 13337) | 反汇编/反编译 | zeromcp 封装,`idb_open` 得 session;`decompile`(Hex-Rays)、`get_bytes` 等 |
| NDK llvm 工具链 | 本地 objdump/nm/readelf | `$ANDROID_HOME/ndk/26.3.11579264/toolchains/llvm/prebuilt/darwin-x86_64/bin` |
| adb / strace(设备自带) | 动态验证 | 设备 `/system/bin/strace` 存在 |

> 注意:ida-pro-mcp 实际端口是 **8745**(进程 `idalib-mcp --host 127.0.0.1 --port 8745`),不是用户记录的 13337。

### 2.1 关键文件

- `/tmp/luna/apk/classes.dex` — Java 层
- `/tmp/luna/apk/lib/arm64-v8a/libBugly.so` — native 层(全部检测核心,369672 字节)
- `apktool_mcp_server_workspace/luna-decoded/smali/luna/safe/luna/MainActivity.smali` — 12589 行主逻辑

### 2.2 函数地址总表(libBugly.so,imagebase 0x0)

| JNI 导出 | 地址 | 大小 | 检测内容(见 §6) |
|---|---|---|---|
| `Java_luna_safe_luna_MainActivity_checknum` | `0x211f4` | — | 读 `persist.sys.vold_app_data_isolation_enabled` |
| `Java_luna_safe_luna_MainActivity_checkappnum` | `0x21658` | — | 读 `persist.zygote.app_data_isolation` |
| `Java_luna_safe_luna_MainActivity_checksuskernel` | `0x21850` | — | KernelSU 检测(selinux oracle) |
| `Java_luna_safe_luna_MainActivity_checkvtools` | `0x1e43c` | — | socket bind 检测(云机/VM),返回 0-3 |
| `Java_luna_safe_luna_MainActivity_checkxiaomi` | `0x21318` | — | 小米机型检测 |
| `Java_luna_safe_luna_MainActivity_findapply` | `0x1ad24` | 0xd98 | 无障碍服务检测('auto'/'scene') |
| `Java_luna_safe_luna_MainActivity_findlsp` | `0x22168` | — | CGROUP/LSPosed + DRM ID/Android ID 采集 |
| `Java_luna_safe_luna_MainActivity_fhma` | `0x21bb4` | 0x5b4 | `stat /data/property/persistent_properties` + `ro.dalvik.vm.native.bridge` |
| `Java_luna_safe_luna_MainActivity_kernels` | `0x19af0` | 0x1234 | getDeviceIdentifiers(MediaDrm)+ 属性序列化 |
| `Java_luna_safe_luna_MainActivity_roots` | — | — | su 指令检测(**崩溃点**,见 §6.10) |

---

## 3. luna 总体架构

### 3.1 8 步检测流程

luna 主界面 "黑灰产设备 x/8" 中 **8 = 固定检测步数**,x = 当前执行到的 step(进度,非命中数)。smali 证据:

```smali
# MainActivity.smali ~1066
const-string v0, "%d/%d\n\n%s"      # String.format
const/16 v2, 0x8                    # 分母固定 8
```

8 个 step 与日志对应(`logcat -s Luna:*`):

```
Detection step 3 cost XXms: 系统        (Magisk/mountinfo/attr_prev/bin 目录)
Detection step 4 cost XXms: 证书        (KeyStore attestation)
Detection step 5 cost XXms: Root环境     (selinux oracle: ksuDomain=no)
Detection step 6 cost XXms: 信息泄露     (checkvtools: bind 检测)
Detection step 7 cost XXms: 环境指纹
Detection step 8 cost XXms: 模块扫描     (checkappnum/checknum/fhma/findlsp/findapply)
Risk detected at step 8: 模块扫描        ← 当前设备唯一命中日志
```

### 3.2 关键执行器方法(MainActivity.smali)

| 方法 | 行号 | 作用 |
|---|---|---|
| `J0(IL鬚鬚鷙貜籲;)Z` | 3451 | step 执行器:执行 Callable(`run()` 在 try 块),异常走 `catchall_0`(记录日志 + setLocale 恢复 + return) |
| `V0(Ljava/lang/String;Ljava/util/concurrent/Callable;)` | — | 子检测执行器(返回 Object) |
| `N0(Ljava/lang/String;Ljava/lang/String;)V` | 3819 | UI 更新(检测名 + 说明) |
| `x0(I)Ljava/lang/String;` | ~12050 | step 编号 → 检测名(switch,见 §4.2) |
| `s0()Z` | 11469 | **step6.checkvtools 包装:返回 3 → 显示"黑灰产设备"**(见 §8) |
| `k0()Z` | 6945 | 备用机/云机/新机检测(SDK_INT>29 分支) |
| `q0()Z` | 10511 | 非主用户检测(主用户 userId==0 → 返回 false 通过) |
| `l0()Z` | 7196 | 工作室检测(BATTERY_CHANGED:电量 100%+充电+无 SIM) |
| `m0()Z` | 7942 | uname 关键词扫描 + 用户名 emoji/中文正则 |

### 3.3 风险判定("Risk detected at step")

```smali
# ~5050-5210
new-instance v8, L籲爩龘鬚簾齇糴;          # 5 个混淆 Callable(step 子检测)
J0(step, Callable) → v8                    # v8 被多次覆盖
...
if-eqz v8, :cond_4
const-string v10, "Risk detected at step " # v8 != 0 → 报风险
```

5 个 J0 Callable 混淆类:`籲爩龘鬚簾齇糴` / `鬚爩齇貜籲蠶籲鱅` / `鱅矡竈貜竈蠶鱅竈矡`(roots,崩溃点) / `鬚鷙鼕` / `籲鷙簾`。

### 3.4 step8 的 5 个子检测(smali 7420-7942)

```
step8.checkappnum → V0 → Boolean
step8.checknum    → V0 → Boolean
step8.fhma        → V0 → Boolean
step8.findlsp     → V0 → Boolean
step8.findapply   → V0 → Boolean
```

任一返回 true 即可能触发 "模块扫描" 标记。

---

## 4. 关键资源与检测项映射

### 4.1 检测项字符串资源(值取自 `res/values-zh/strings.xml`)

| 资源名 | id | 值 |
|---|---|---|
| `checkpoint_kernel` | 0x7f0d0030 | 模块扫描 |
| `checkpoint_root` | 0x7f0d0034 | Root环境 |
| `checkpoint_studio_fingerprint` | 0x7f0d0035 | 环境指纹 |
| `checkpoint_evil_app` | 0x7f0d002d | 信息泄露 |
| `checkpoint_complete` | 0x7f0d002b | 检测完成 |
| `emulator_detected` | 0x7f0d0042 | 备用机/云机/新机 |
| `risk_device` | 0x7f0d0063 | 黑灰产设备 |
| `high_risk_os` | 0x7f0d004a | 高危风险 |
| `userid_abnormal` | 0x7f0d0087 | UserID abnormal - Hook |
| `version_low` | 0x7f0d0088 | 备用机 * 测试机 |
| `errtips` | 0x7f0d0045 | ⚠️ 该设备不建议使用:... |
| `risk_detected_magisk/apatch/shamiko/dex2oat/overlay` | — | Magisk / APatch / Shamiko / 存在Root框架 / 系统目录被overlay挂载 |

### 4.2 x0(I) 的 switch(step → 检测名)

`MainActivity.smali` 12050-12250,`packed-switch`(case 0-7):

| case | 资源 | 显示 |
|---|---|---|
| 0 | checkpoint_kernel | 模块扫描 |
| 1 | checkpoint_studio_fingerprint | 环境指纹 |
| 2 | checkpoint_evil_app | 信息泄露 |
| 3 | checkpoint_root | Root环境 |
| 4-7 | (证书/系统/BootLoader/CPU架构) | — |

---

## 5. 字符串加密算法(核心逆向成果)

### 5.1 算法

libBugly.so 的所有检测字符串以 **XOR 加密** 存储在 `.data` 段(虚拟地址 0x56e20 起,文件偏移 0x54e20,大小 0x4d03)。

**加密方式**:
```
密文[i] = 明文[i] XOR key        (每个字符串独立 key)
字符串结尾:明文 0x00 → 密文 key
加密串后面紧跟一个真 0x00(分隔)
```

**解密**:
```
key = 密文中"后跟 0x00 的那个字节"(即加密的字符串终止符)
明文 = 密文[:该位置] 逐字节 XOR key
```

验证实例:

| 地址 | 密文尾部 key | 明文 |
|---|---|---|
| 0x57640 | 0xe6 | `android/content/Context` |
| 0x57660 | 0xd4 | `getSystemService` |
| 0x57cc0 | 0x7f | `/data/property/persistent_properties` |
| 0x57c20 | — | `persist.zygote.app_data_isolation` |
| 0x57b00 | — | `persist.sys.vold_app_data_isolation_enabled` |
| 0x5b670 | — | `*** checkvtools bind...............: %s:%u` |

### 5.2 全量已解密字符串(按函数)

**fhma(0x57c00-0x57da0)**:
```
0x57c00: ***Found kernel_find_bl: %s
0x57c10: find_bl: %s
0x57c20: persist.zygote.app_data_isolation
0x57c50: *** persist.zygote.app_data_isolation ......
0x57c80: /proc/fs/ext4
0x57c90: *** /proc/fs/ext4 permissions are not 555
0x57cc0: /data/property/persistent_properties
```

**findapply(0x57640-0x577d0)**:
```
0x57640: android/content/Context
0x57660: getSystemService
0x57680: (Ljava/lang/String;)Ljava/lang/Object;
0x576b0: ACCESSIBILITY_SERVICE
0x576f0: getEnabledAccessibilityServiceList
0x57720: (I)Ljava/util/List;
0x57740: ()[Ljava/lang/Object;
0x57760: ()Ljava/lang/String;
0x577d0: ***Found service with 'auto' or 'scene': %s
```

**kernels(0x57500-0x57640)**:
```
0x57530: ()[Ljava/lang/String;
0x57580: (Ljava/lang/String;)Ljava/lang/String;
0x57620: %s,0,0,0,1,0|%ld
0x57510: getDeviceIdentifiers
0x57380: android/provider/Settings$Secure
0x573c0: (Landroid/content/ContentResolver;Ljava/lang/String;)Ljava/lang/String;
0x57280: getPropertyByteArray
0x572a0: (Ljava/lang/String;)[B
0x572f0: deviceUniqueId
0x57300: %02x
0x57220: *** Failed to create Widevine UUID
0x57250: *** Failed to create MediaDrm instance
0x57330: *** luna.verid = %s
```

**checkvtools(0x5b670 附近)**:
```
0x5b670: *** checkvtools bind...............: %s:%u
0x5b6a0: *** checkvtools bind............: %s:%u errno=%d %s
```

**系统/Magisk 检测(0x57040-0x57150)**:
```
0x57040: Checking directory: %s
0x57070: %s/sutest
0x57080: Found magisk at: %s
0x570a0: android/media/MediaDrm
0x57120: *** MediaDrm constructor not found
```

### 5.3 重要发现:属性名截断陷阱

`persist.zygote.app_data_isolation`(33 字符)与 `persist.sys.vold_app_data_isolation_enabled`(45 字符)都 **超过 Android 属性名 31 字符上限**。libc `__system_property_get` 会截断查询(日志:`The property name length for "..." is >= 31; truncated to "..."`)→ **永远查不到该属性**。

- checknum:读到截断名(不存在)→ 返回 "unknown"
- checkappnum:状态机分析(v7<=0 走 v1=1823259233 分支 → 最终 **v0=0 通过**;v7>0 走 v1=342211282 分支 → **v0=1 命中**)

> 即:checknum/checkappnum 的判定是 **"属性存在 → 命中"**,而截断查询使属性"永远不存在" → **永远通过**。它们不是命中源。

---

## 6. 检测函数详细分析(native JNI)

### 6.1 checknum(0x211f4)

```c
v7 = __system_property_get("persist.sys.vold_app_data_isolation_enabled", v4);
__android_log_print(3, "Luna", "***Found vold_app_data_isolation_enabled: %s", v6);
if (v7 <= 0) 返回 "unknown"(属性不存在)
else         返回属性值(NewStringUTF)
```

- 纯读取,不判定风险。日志曾出现 `***Found vold_app_data_isolation_enabled: 1`(设值后)。

### 6.2 checkappnum(0x21658)

```c
v7 = __system_property_get("persist.zygote.app_data_isolation", v5);
// 状态机(v1 魔数分发):
//   v7<=0 → v1=1823259233 → 最终 v0=0(通过)
//   v7>0  → v1=342211282  → log(57C50); v0=1(命中)
// 日志: "*** persist.zygote.app_data_isolation ......"
```

- **"属性存在 → 命中"**,但 33 字符属性名被 libc 截断,查询永远失败 → 永远通过。**非命中源**。

### 6.3 fhma(0x21bb4,0x5b4)

```c
stat("/data/property/persistent_properties", &v15);
v20 = stat(...) != 0;                 // stat 失败标志
// 日志(57CF0/57D40/57D70/57DA0——含路径+长整数)
// 判定: v8(=stat 的 st_size 等字段) < 2048 → v1=1 命中
//       v8 >= 2048 → v1=0 通过
```

- **命中条件:persistent_properties 大小 < 2048(或 stat 失败)**。
- 设备实测:文件 2378-2503 字节 ≥ 2048 → **通过**。移走文件(stat 失败,v8=0)→ 命中(曾被我误判为命中源,实为自己实验造成)。
- 另读 `ro.dalvik.vm.native.bridge`(模拟器检测,真机为空)。

### 6.4 findapply(0x1ad24,0xd98)

```c
FindClass("android/content/Context")
  → getSystemService(ACCESSIBILITY_SERVICE)
  → getEnabledAccessibilityServiceList()
  → 遍历服务名,匹配含 'auto' 或 'scene'
日志: "***Found service with 'auto' or 'scene': %s"
```

- **检测无障碍服务**。设备 `settings get secure enabled_accessibility_services` = null(无)→ **通过**。

### 6.5 findlsp(0x22168)

- 大型函数(反编译大量变量)。字符串主要是 **DRM ID / Android ID 采集**(MediaDrm + Settings$Secure)。
- CGROUP 异常检测在 **Java 层**(MainActivity.smali 7713:`*** 检测到框架隐藏自身痕迹- LSPosed 或 Hook导致CGROUP异常`),仅在 findlsp Callable 返回 true 时打印。
- 设备 cgroup 实测(`/proc/908/cgroup`):`schedtune:/top-app`、`cpuset:/foreground` 等全部正常 → **通过**。

### 6.6 kernels(0x19af0,0x1234)

- 用 `snprintf("%s,0,0,0,1,0|%ld")` 序列化检测结果;`getDeviceIdentifiers` 调 `getMediaDrmId`(DRM ID);读 `Settings$Secure.ANDROID_ID`。
- 属于"设备标识采集",与风险判定关联弱。

### 6.7 checkvtools(0x1e43c)—— "黑灰产设备" 核心

- **魔数状态机(控制流平坦化)**,含 `socket` / `bind` / `getsockname` / `sockaddr` 结构。
- 日志:`*** checkvtools bind...............: %s:%u` / `... errno=%d %s`。
- 绑定目标地址 0x570ac0/0x570ae8/0x570af8(加密串,尚未完全还原;0x570ac0 明文前缀含 "com."——域名/IP 探测)。
- **返回 0-3 等级**,由 s0() 判定(v0==3 → "黑灰产设备",v0==2 → "高危风险")。

### 6.8 checkxiaomi(0x21318)

- 小米机型检测(设备非小米,不触发)。

### 6.9 checksuskernel(0x21850)

- KernelSU 检测(与 selinux oracle 联动,见 §11——已通过)。

### 6.10 roots(崩溃点)

```
MainActivity.roots(Native Method)
  → NoSuchMethodError: no non-static method
     "Lluna/safe/luna/MainActivity;.encryptData(Ljava/lang/String;)Ljava/lang/String;"
  → 崩溃于 J0(step 执行器)内,Thread-2
```

- **luna 闭源 bug**:native `roots` 调用 Java 方法 `encryptData`,但 APK 的 MainActivity 中不存在该方法(APK 与 so 版本不匹配 / R8 优化删除)。**每次检测必崩**,是 luna 自身的致命缺陷。

---

## 7. 检测函数详细分析(Java 层)

### 7.1 m0()(7942)—— uname 关键词 + 用户名正则

```java
String release = Os.uname().release.toLowerCase();
String[] kws = {"ksu","toybox","wild","shirkneko","twrp","lineage",
                "cyanogenmod","cyanogen","xda","-aky","kernelsu"};
if (release.contains(任意kw)) → 命中
// 用户名检测(正则):
//   ".*[emoji范围].*"  ".*[\u4e00-\u9fa5].*"
```

- 设备 uname release 被 SUSFS 伪装为 `4.19.304-perf`(不含关键词)→ **通过**。

### 7.2 k0()(6945)—— 备用机/云机/新机

```java
Log.w("Luna", "🚨🚨🚨 开始检查CPU架构...");
if (!q0()) goto cond_0;            // q0 非主用户检测
T0();
if (SDK_INT > 29) {                // Android 11+
    getString(risk_device);        // "黑灰产设备"
    getString(version_low);        // "备用机 * 测试机"
    N0(检测名, 说明);
    return true;                   // 命中!
}
```

- **Android 11+ 且 q0() 返回 true → 必显示"黑灰产设备 + 备用机测试机"并返回 true**。
- 但 q0()(10511):`userId==0(主用户)→ return false` → 用户(主用户)走 cond_0,不显示。**k0() 不是标题来源**。

### 7.3 q0()(10511)—— 非主用户检测

```java
int uid = Process.myUid();
int userId = UserHandle.getUserId(uid);
if (userId != 0) {                 // 非主用户(工作资料/多用户)
    Log.e("Luna", "*** 检测到非主用户运行: uid=..., userId=...");
    N0(...); return true;          // 命中
}
return false;                      // 主用户 → 通过
```

### 7.4 l0()(7196)—— 工作室检测

```java
IntentFilter("android.intent.action.BATTERY_CHANGED");
registerReceiver(...);
status = intent.getIntExtra("status", -1);   // 2=CHARGING, 5=FULL
// + 电量 100% + getSimState()(无 SIM)
// → "备用机/云机/新机"(emulator_detected)
```

- 设备实测:level=100、status=5、USB powered=true(adb 连接充电)、无 SIM → **命中"备用机/云机/新机"**。

### 7.5 SelinuxContextOracle(Java + native)

- 独立服务(`SelinuxContextOracleService`),探测 `u:r:ksu:s0` 等域存在性(见 §11)。

---

## 8. 判定链:"黑灰产设备" 标题的触发机制

### 8.1 s0()(11469)—— 最终标题判定

```java
// s0() = step6.checkvtools 包装
Object r = V0("step6.checkvtools", Callable爩龘齇貜鷙龘);  // native checkvtools 返回 Integer
int v0 = (Integer) r;
if (v0 != 3) {                       // v0 == 3 → 黑灰产设备
    getString(risk_device);          // "黑灰产设备"
    getString(userid_abnormal);      // "UserID abnormal - Hook"
    N0(...);
    return true;                     // 命中
}
if (v0 != 2) {                       // v0 == 2 → 高危风险
    getString(high_risk_os);         // "高危风险"
    ...
}
```

**"黑灰产设备" 标题 = step6.checkvtools 返回 3**。显示说明 "UserID abnormal - Hook"。

### 8.2 checkvtools 返回 3 的含义

- checkvtools 是 **socket bind 检测**:尝试绑定特定地址/端口,根据 bind 结果/errno 判定"云机 / 虚拟机 / 异常网络环境"。
- 用户设备网络为**家用 WiFi NAT**(见 §12),无代理/VPN——bind 行为可能被 luna 误判,或受 luna 崩溃污染。

### 8.3 完整判定链总结

```
UI 顶部 "黑灰产设备 8/8"
  ├─ "黑灰产设备" = s0()(step6.checkvtools) 返回 3
  │     └─ checkvtools = socket bind 网络探测(云机/VM)
  ├─ "8/8" = 进度(8 步全部执行)
  └─ 列表命中项:
        *模块扫描   = step8(roots 崩溃污染 or 复合判定)
        *备用机/云机/新机 = l0() 工作室检测(满电+充电+无SIM,实测命中)
        *Security update 2024-01-05 = 设备指纹展示(非检测)
```

---

## 9. 动态排查记录(排除清单)

以下实验全部在设备上执行(每次 `pm clear luna.safe.luna` 后重测,观察 `logcat -s Luna:*` 的 "Risk detected at step 8"):

| # | 实验 | 结果 | 结论 |
|---|---|---|---|
| 1 | 移走 `/data/local/tmp/ksud/c1/c2/md.png/s3.png` | 仍命中 | 非 /data/local/tmp |
| 2 | 移走 `/data/local/tmp/su/super*.bin/susfs_config.json/截图` | 仍命中 | 同上 |
| 3 | 移走 `/data/local/teesim`(停守护循环) | 仍命中 | 非 teesim 部署 |
| 4 | 移走 `/data/adb/tricky_store` | 仍命中 | 非 TEESimulator 配置 |
| 5 | 移走 `/data/adb/ksu` + `/data/adb/ksud` | 仍命中 | 非 SUSFS 配置/ksud 文件 |
| 6 | 移走全部 `.bak` 到 `/data/hidden_backup` | 仍命中 | 非残留文件 |
| 7 | 移走 `/data/property/persistent_properties` | 仍命中(后恢复 2503B) | fhma 非命中源(大小≥2048 通过) |
| 8 | `rm /dev/ksu_init_diag.log /dev/susfs_ksu_applied` | 仍命中 | 非 /dev 节点 |
| 9 | 无障碍服务 | null(无) | findapply 通过 |
| 10 | `uname -r` = 4.19.304-perf(伪装,无关键词) | m0() 通过 | 非 uname |
| 11 | `/proc/modules` / `/proc/mounts` 无 susfs/ksu | 无异常 | 非内核模块/挂载 |
| 12 | hidepid=2(app 看不到其他进程) | 进程检测无效 | 非 ksud 进程 |
| 13 | cgroup(zygote/luna 子进程)全部正常 | findlsp 通过 | 非 CGROUP 异常 |
| 14 | 设 `persist.zygote.app_data_isolation=0` | 仍命中 | checkappnum 截断查询永远失败 |
| 15 | 设 `persist.zygote.app_data_isolati`(31字符截断名) | 仍命中(且 luna 崩溃干扰) | 同上 |
| 16 | 网络检查:无代理/无 VPN/无 REDIRECT | 干净 | 非透明代理 |
| 17 | strace 附加(luna 反调试,检测行为改变) | 不完整 | 无法用 strace 抓全 |

**关键观察**:
- luna 每次检测**必崩**(roots → encryptData NoSuchMethodError),崩溃在 Thread-2,与检测竞争。
- 所有已知检测点(文件/进程/属性/无障碍/cgroup/uname)单项全部通过,但 step8 仍报 "模块扫描"。

---

## 10. 结论:各显示项的根因

| 显示项 | 根因 | 可解决性 |
|---|---|---|
| **黑灰产设备(标题)** | s0()/step6.checkvtools 返回 3(socket bind 云机/VM 探测) | 部分:网络环境 NAT 误判可换网验证;崩溃污染不可控 |
| **8/8** | 8 步全部执行完(进度,非命中数) | —(无需解决) |
| **模块扫描** | step8 复合判定;roots 崩溃(encryptData NoSuchMethodError)污染检测结果 | ❌ luna 闭源 bug |
| **备用机/云机/新机** | l0() 工作室检测:电量 100% + USB 充电 + 无 SIM(实测全中) | ✅ 拔 USB/插 SIM/用电池可消除 |
| **Security update 2024-01-05** | 设备指纹展示(见 §11.3) | —(非检测) |
| **不建议使用:支付/社交/购物/游戏** | 综合风险评分(errtips 文案) | —(综合判定) |

**对实际使用的影响**:银行 App(农业/兴业)、KernelSU-Next App、Momo、春秋 Native Check **全部正常**——luna 的显示不影响真实使用,属于其检测误报 + 自身崩溃的综合结果。

---

## 11. 与 root 隐藏相关的检测(selinux oracle)

### 11.1 检测机制

luna 的 `SelinuxContextOracleService` 探测 SELinux 域存在性,判定 KernelSU:

- `ksu_domain`:尝试 setcon / access 查询 `u:r:ksu:s0`
- `ksu_file` / `magisk_file`:文件上下文

### 11.2 已修复(内核 597688c)

`kernel-patches/unified-selinux_hide.c`:
- `my_write_context`(/sys/fs/selinux/context 写):含 ksu → `-EINVAL`
- `my_write_access`(/sys/fs/selinux/access 写):含 ksu → `-EINVAL`(原返回全允许 0xffffffff 泄露域存在)
- `my_setprocattr`:覆盖全部 attr name(current/exec/prev/fscreate/keycreate/sockcreate)

实测:`SELinux oracle result=0 ksu_domain=0 ksu_file=0 magisk_file=0`、`ksuDomain=no` → luna "Root 环境 / 发现 KernelSU" 消失。

### 11.3 Security update 2024-01-05

三个工具(luna/Momo/Native Check)显示一致 = **OnePlus 8T + Android 13 设备指纹展示**,不从系统属性(getprop 伪装 2024-02-05)、不从 attestation 证书(TEESimulator 证书已 202402)读取 → **非检测项**。相关 TEESimulator 修改已回滚。

---

## 12. 网络环境检查

设备当前网络(adb 实测):

| 项 | 值 |
|---|---|
| 网络 | 仅 WiFi(ASUS_5G,192.168.1.11/24,路由器 192.168.1.2) |
| 全局代理 | `settings get global http_proxy` = null |
| VPN/TUN | 无(仅 wlan0) |
| iptables | 无 REDIRECT/DNAT/TPROXY |
| 监听端口 | 无本地代理 |
| 代理属性 | 仅厂商 `vendor.per_proxy`(非透明代理) |

**结论:无任何代理配置**,checkvtools 的 bind 判定不是代理导致。

---

## 13. 遗留问题与后续分析方向

1. **checkvtools 返回 3 的确切条件**:0x570ac0/0x570ae8/0x570af8 的 bind 目标(域名/IP)尚未完全解密(高字节加密串)。后续可用"运行时内存 dump"或继续 IDA 状态机分析。
2. **luna roots 崩溃(encryptData NoSuchMethodError)**:闭源 bug。可尝试其他 luna 版本对比,或反馈作者。
3. **"模块扫描" 的确切命中子检测**:5 个 J0 Callable(籲爩龘鬚簾齇糴 等)与 5 个 V0 子检测的对应关系未完全映射;roots 崩溃污染的具体路径未 100% 确认。
4. **网络验证实验**:切换蜂窝数据(4G/5G)重测 luna,若 "黑灰产设备" 消失 → 确认网络判定;不变 → 崩溃污染。
5. **云机判定特征**:checkvtools 的 socket 检测逻辑(状态机)可继续用 IDA 单步还原,识别它具体 bind 哪些地址/端口。

---

## 14. 附录 A:IDA MCP 调用方法

服务:`idalib-mcp --host 127.0.0.1 --port 8745`(zeromcp/1.3.0,工具 65 个)。

```bash
# 1. initialize(拿 Mcp-Session-Id 响应头)
curl -s -D - -X POST -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1.0"}}}' \
  http://127.0.0.1:8745/mcp

# 2. idb_open(拿 session_id)
curl -s -X POST -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <sid>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"idb_open","arguments":{"input_path":"/tmp/luna/apk/lib/arm64-v8a/libBugly.so"}}}' \
  http://127.0.0.1:8745/mcp

# 3. 之后每次调用都带 database=<session_id>
#    decompile: {"name":"decompile","arguments":{"database":"<db>","addr":"0x1e43c"}}
#    get_bytes: {"name":"get_bytes","arguments":{"database":"<db>","regions":[{"addr":"0x57640","size":32}]}}
#    lookup_funcs: {"name":"lookup_funcs","arguments":{"database":"<db>","queries":["Java_luna_safe_luna_MainActivity_fhma"]}}
```

常用工具:`server_health` / `idb_open` / `idb_list` / `lookup_funcs` / `decompile`(Hex-Rays) / `disasm` / `get_bytes` / `get_string` / `callees` / `xrefs_to` / `find_bytes` / `imports_query`。

> 注意:session 会失效("Worker for session ... not reachable")——失效后重新 idb_open。

---

## 15. 附录 B:字符串解密脚本

```python
# 解密 libBugly.so .data 段 XOR 字符串
# 算法:key = 密文中"后跟 0x00 的字节"(加密的字符串终止符)
with open('/tmp/luna/apk/lib/arm64-v8a/libBugly.so','rb') as f:
    data = f.read()

FILE_OFF = 0x54e20      # .data 段文件偏移
VIRT_BASE = 0x56e20     # .data 段虚拟地址

def read_virt(addr, size):
    off = FILE_OFF + (addr - VIRT_BASE)
    return data[off:off+size]

def decrypt(addr, maxlen=120):
    bs = read_virt(addr, maxlen)
    for i in range(1, len(bs)-1):
        if bs[i+1] == 0x00:            # 找到加密终止符(key)
            key = bs[i]
            return ''.join(chr(b^key) if 32<=(b^key)<127 else '.'
                           for b in bs[:i])
    return None

# 用法示例
print(decrypt(0x57640))   # android/content/Context
print(decrypt(0x57cc0))   # /data/property/persistent_properties
print(decrypt(0x5b670))   # *** checkvtools bind...............: %s:%u
```

---

## 附:关键时间线与仓库状态

- 内核 main = `cda4010`(含 selinux_hide 修复 `597688c`)
- 设备:597688c 内核 + TEESimulator 上游版(150a476)
- luna APK:`luna1435.apk`(用户提供)
- 反编译产物:`apktool_mcp_server_workspace/luna-decoded/`(smali)、`/tmp/luna/`(dex/so)
