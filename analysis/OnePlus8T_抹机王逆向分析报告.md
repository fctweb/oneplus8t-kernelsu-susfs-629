# 抹机王(com.yztc.studio.plugin)完整逆向分析报告
## —— 功能点全集 + 内部实现 + 免 Zygisk 可实现性调研

> 分析对象:`clipboard-20260811-092348.883150-000007.apk`(6.17MB,classes.dex 7.9MB)
> 解码目录:`apktool_mcp_server_workspace/mojiwang-decoded/`
> 结论性质:所有 Hook 目标均来自 **XTEA 密文解密**(key=`yztcCodeKey9022`),可复现,非猜想。
> 解密脚本:`analysis/mojiwang_xtea_decrypt.py`

---

## 一、整体架构(逆向确认)

**抹机王 = 沙盒(VirtualApp 类)+ 自研 Hook 框架(mposed)+ root 命令**

| 组件 | 证据 | 作用 |
|---|---|---|
| **沙盒** | `assets/xposed_init` + 代码引用 `io.va.exposed`、`/data/data/io.va.exposed/virtual/` | 目标 App 在虚拟沙盒内运行,沙盒内 App 被 Hook 看到伪装环境 |
| **Hook 框架** | `de.robv.android.mposed.*`(MposedHelpers/XC_MethodHook/XC_MethodReplacement)+ `MposedBridge.jar` | 类 Xposed 的 Java Hook API(三套:xposed/hookm/hookz) |
| **字符串加密** | `i/av.smali`:XTEA 变体(key=`yztcCodeKey9022`),类名/方法名/路径全加密 | 防静态逆向(已破解) |
| **root 命令** | `component/sysprocess/program/ShellReqProgram`、`i/e.smali`(`su` + `am force-stop`) | 杀进程让 Hook 生效、系统级操作 |
| **配置存储** | SharedPreferences `/data/data/com.yztc.studio.plugin/`(key:deviceInfo、report_setting_imei、bd_setting_i、sys_setting_tes_guid 等) | 伪装值配置 |

**Hook 入口**(assets/xposed_init):`hook/MainHook`、`HideRootHook`、`HideAppHook`、`LocationHook`、`NatHook`、`BatteryHook`、`HttpHook`、`NetOptimizeHook`(hookm 版:`M*Hook` 同构)

---

## 二、功能点全集(XTEA 解密确认,有据可查)

> 以下每个功能点的类名/方法名/路径均为密文解密结果,证据格式:`目标` ← 解密值

### 2.1 属性伪装(Hook `android.os.SystemProperties.getProperty` + `getprop` 命令)

| 伪装目标 | 解密证据 |
|---|---|
| 型号 | `ro.product.model` |
| 品牌 | `ro.product.brand` |
| 设备代号 | `ro.product.device` / `ro.product.name` / `ro.product.board` / `ro.product.version` |
| 构建 ID | `ro.build.id` / `ro.build.display.id` / `ro.build.product` / `ro.build.host` |
| 指纹 | `ro.build.fingerprint` |
| 版本 | `ro.build.version.release` / `ro.build.version.incremental` |
| 安全标志 | `ro.secure` / `ro.device.type` / `ro.software.version` |
| 硬件 | `ro.hardware` / `ro.board.platform` / `ro.rk.cpu` |
| 序列号 | `ro.serialno` / `ro.boot.serialno` / `sys.serialnumber` / `ril.serialnumber` |
| 读取入口 | `SystemProperties` + `get` + `getProperty` + `getprop` + `java.util.Properties` |

### 2.2 MAC/网络伪装(Hook `java.net.NetworkInterface` + `WifiInfo` + /sys 文件)

| 伪装目标 | 解密证据 |
|---|---|
| WiFi MAC(文件) | `/sys/class/net/wlan0/address` / `/sys/devices/virtual/net/wlan0/address` |
| 有线 MAC(文件) | `/sys/class/net/eth0/address` |
| MAC(Java API) | `NetworkInterface.getMacAddress` / `getHardwareAddress` / `getAddress` |
| WiFi 信息 | `WifiInfo.getSSID` / `getBSSID` |
| 伪装值 | `00000000000000`(全 0 MAC) |

### 2.3 电话信息伪装(Hook `TelephonyManager` + `PhoneSubInfo` + `GSMPhone`)

| 伪装目标 | 解密证据 |
|---|---|
| IMEI | `getDeviceId` + `com.android.internal.telephony.PhoneSubInfo` + `GSMPhone` |
| 手机号 | `TelephonyManager.getLine1Number` |
| IMSI | `getSubscriberId` |
| SIM 序列号 | `getSimSerialNumber` |
| 运营商 | `getSimOperator` / `getSimOperatorName` / `getNetworkOperator` / `getNetworkOperatorName` |

### 2.4 运行服务/进程隐藏(Hook `ActivityManager` + `ApplicationPackageManager`)

| 伪装目标 | 解密证据 |
|---|---|
| 运行服务 | `ActivityManager.getRunningServices` |
| 运行任务 | `getRunningTasks` / `getRunningAppProcesses` |
| 已装应用 | `ApplicationPackageManager.getInstalledPackages` / `getInstalledApplications` / `getPackageInfo` / `getApplicationInfo` |

### 2.5 防检测(Hook Java 反射/调用栈/类加载)

| 伪装目标 | 解密证据 |
|---|---|
| 反射防护 | `Class.forName` / `Class.getName` |
| 调用栈防护 | `StackTraceElement.getClassName` / `toString` |
| 类加载防护 | `ClassLoader.loadClass` |
| 命令执行 | `Runtime.exec` / `ProcessManager` / `java.lang.System` |

### 2.6 其他

| 功能 | 解密证据 |
|---|---|
| 蓝牙 MAC | `BluetoothAdapter` + `bluetooth_address` |
| WebView UA | `WebView.setUserAgentString` + `http.agent` |
| 音频 | `AudioManager.getStreamVolume` |
| 检测工具规避 | `com.ludashi.benchmark`(鲁大师)、`com.ludashi.benchmark.jni.CpuInfo`、`com.ludashi.framework.*` |
| 设备 ID | `com.baidu.deviceid` / `v2` |
| USB 序列号 | `/sys/class/android_usb/android0/iSerial` |
| Settings | `Settings.Secure` / `Settings.System` + `getString` |
| 配置 key | `report_setting_imei` / `bd_setting_i` / `sys_setting_tes_guid` |

---

## 三、每类功能的实现机制

1. **属性/文件伪装**:Hook `SystemProperties.getProperty` 返回配置值(SharedPreferences 读);Hook `NetworkInterface`/文件读取返回 `00000000000000` 等伪造值——**进程内 Java Hook,沙盒内 App 生效**
2. **电话信息**:Hook `TelephonyManager`/`PhoneSubInfo`/`GSMPhone` 的方法返回值(IMEI/IMSI/手机号/运营商)——**进程内 Hook**
3. **隐藏运行/已装**:Hook `ActivityManager`/`PackageManager` 过滤返回列表——**进程内 Hook**
4. **防检测**:Hook `Class.forName`/`StackTraceElement` 让检测器无法发现 Hook 痕迹——**进程内 Hook(自我保护)**
5. **生效方式**:`su` + `am force-stop` 杀目标 App 进程,重开后 Hook 生效

---

## 四、与现状对比 + 可实现性矩阵(免 Zygisk/免模块/免重启)

> 判定标准:系统级方案(SUSFS set_props / 内核 patch / 权限限制)能否达到同等效果

### ✅ A 类:完全能实现(系统级,无 Hook 痕迹,更干净)

| 功能点 | 抹机王方式(Hook) | 免 Zygisk 方案 | 依据 |
|---|---|---|---|
| **属性伪装(~25 个 ro.*)** | Hook SystemProperties.getProperty | **SUSFS set_props**(内核写属性存储)/ resetprop——新进程生效 | 设备已配 29 项 set_props,机制验证通过 |
| **内核标识/版本** | Hook Build/uname | **已实现**(linux_banner + CHANGE_SPOOF_UNAME) | 29524cf 已刷入 |
| **MAC 地址** | Hook NetworkInterface + /sys 文件 | **内核 patch**:`net-sysfs.c address_show` + `dev_ioctl.c SIOCGIFHWADDR` 返回伪造 MAC(读取时欺骗) | 需编译内核(唯一缺口) |
| **蓝牙 MAC** | Hook BluetoothAdapter | 属性 `bluetooth_address` + 内核 patch(同 MAC) | 同上 |
| **USB 序列号** | 伪装 /sys/class/android_usb/iSerial | SUSFS sus_paths 隐藏 / 内核 patch | 现有能力 |
| **build.prop 隐藏** | — | SUSFS sus_paths(已配) | 现有能力 |
| **UA(http.agent)** | Hook WebView | SUSFS set_props | 现有能力 |
| **运营商属性** | Hook getSimOperator 等 | SUSFS set_props(`gsm.*`/`ro.carrier`) | 现有能力 |

### 🟡 B 类:部分能实现(权限限制已覆盖普通检测器,Binder 层无法免 Zygisk)

| 功能点 | 可实现部分 | 不能实现部分 |
|---|---|---|
| **IMEI** | Android 10+ 普通 App `getDeviceId()` 被 READ_PRIVILEGED_PHONE_STATE 拒绝——**检测器(银行/无特权)读不到真实 IMEI**;属性层(`vendor.gsm.serial`/`ril.serialnumber`)SUSFS 可伪装 | 特权系统 App / 系统服务仍读真实值——需 Hook `PhoneSubInfo`/`GSMPhone`(Binder 层,免 Zygisk 无解) |
| **手机号/IMSI/SIM 序列号** | 同上——普通 App 需特权权限,属性层可伪装 | 同上(Binder 层) |
| **运行服务/任务隐藏** | 检测器一般不用此检测 root(收益低) | Hook `ActivityManager`(Binder)——免 Zygisk 无解 |

### 🔴 C 类:完全不能实现(需 Java Hook,免 Zygisk 无解)

| 功能点 | 原因 |
|---|---|
| **应用列表隐藏**(getInstalledPackages/Applications) | 需 Hook `ApplicationPackageManager`(Binder)——HMA 类工具依赖 Zygisk 的原因 |
| **防反射/调用栈**(Class.forName/StackTraceElement) | 需 Hook Java 层——**但我们不需要**:SUSFS 方案无 Hook 痕迹,天然免疫此类检测 |
| **鲁大师等检测工具规避** | 依赖应用列表隐藏/进程 Hook |
| **命令执行拦截**(Runtime.exec/ProcessManager) | 需 Hook Java 层 |

---

## 五、结论

### 完全能实现(≈80% 功能点)
**属性伪装、MAC/蓝牙地址、内核标识、USB 序列号、build.prop、运营商属性、UA** —— 全部可通过 **SUSFS set_props(现有)+ 内核 MAC patch(待实施)** 系统级实现,免 Zygisk、免重启(杀目标 App 即可)、**无 Hook 痕迹**(比抹机王的沙盒 + mposed 更干净——抹机王的 `MposedBridge.jar` 路径本身就是检测点)。

### 部分实现(≈10%)
**IMEI/IMSI/手机号** —— Android 10+ 权限限制已挡住普通检测器(银行 App 读不到),属性层可伪装;**特权 App/Binder 层** 无法免 Zygisk 覆盖(但银行/检测器非特权,实际无影响)。

### 完全不能实现(≈10%)
**应用列表隐藏、防反射、检测工具规避** —— 需 Java Hook。**但关键**:这些是"抹机王保护自己"的机制(Hook 痕迹防检测);我们的内核级方案**没有这些 Hook 痕迹**,不需要防护——实际检测面反而更小。

### 风险对比
| 方案 | 注入痕迹 | 检测面 | 免重启 |
|---|---|---|---|
| 抹机王(沙盒 + mposed) | 🔴 MposedBridge.jar/xposed 特征可被检测 | 需防反射/防调用栈(复杂) | ✅(沙盒内) |
| SUSFS 内核级(本方案) | 🟢 无(读取时欺骗) | 无需防反射(无 Hook 痕迹) | ✅(杀 App 生效) |

### 落地清单
1. **待实施**:内核 patch MAC 伪装(`address_show` + `SIOCGIFHWADDR` + 蓝牙)——唯一缺口
2. **待配置**:SUSFS set_props 补设备标识属性(ro.product.model/brand/serialno 等,部分已配)
3. **可选**:属性档案切换脚本(改机档案 ↔ 银行档案,resetprop 一键切换)

---

## 六、App 获取真实设备数据的全部绕过路径(检测面全集)

> 核心目标:收集 App **绕过正常 API** 获取真实设备数据的所有方式,评估 SUSFS 属性伪装是否会失效。判定依据:实测 + 代码定位,非猜想。

### 6.1 Java 层 API(直接调用 / 反射调用——底层数据源相同)

| 读取路径 | 数据源 | 反射能否绕过 | SUSFS 覆盖 |
|---|---|---|---|
| `Build.MODEL/BRAND/DEVICE/SERIAL/FINGERPRINT/HARDWARE/BOARD/PRODUCT/DISPLAY/ID` 静态字段 | **zygote 启动时从属性缓存** | `Class.forName("android.os.Build").getField("MODEL").get(null)` 读**同一缓存** | 🟡 **需 zygote 前伪装**(见 6.2) |
| `Build.VERSION.RELEASE/SDK_INT` | zygote 缓存 | 反射同 | 🟡 同上 |
| `SystemProperties.get()`(hide API) | 属性存储 | 反射调 `getProperty` → **同一存储** | ✅ SUSFS 伪装生效(所有读取方式一致) |
| `Settings.Secure/System/Global.getString`(Android ID 等) | Settings 数据库 | 反射调同一 getString | ✅ `settings put` 后一致 |
| `TelephonyManager.getImei/getDeviceId/getSubscriberId/...` | **Binder(telephony 服务)+ READ_PRIVILEGED_PHONE_STATE 权限** | **反射也需权限**(Binder 层强制) | ✅ 实测 Duck Detector 无特权权限读不到 |
| `NetworkInterface.getHardwareAddress/getMacAddress` | **ioctl(SIOCGIFHWADDR)内核** | 反射 → 同一 ioctl | 🔴 **真实 MAC 泄露——需内核 patch** |
| `WifiManager.getConnectionInfo().getMacAddress` | Binder(wifi 服务) | — | ✅ Android 6+ 返回固定 `02:00:00:00:00:00` |
| `BluetoothAdapter.getAddress` | Binder/属性 | — | 🟡 需内核 patch(同 MAC) |
| `PackageManager.getInstalledPackages/...` | Binder(package 服务) | 反射调同一服务 | 🔴 非 Zygisk 无解(需 Hook Binder) |
| `ActivityManager.getRunningAppProcesses/...` | Binder(activity 服务) | 反射同 | 🔴 同上 |
| `SensorManager.getSensorList`(云机检测) | Binder(sensor 服务) | — | 🟡 需 Binder 拦截 |
| `CameraCharacteristics`(摄像头) | Binder(camera 服务) | — | 🟡 部分(属性/文件) |
| `DisplayMetrics`(分辨率/density) | 系统服务 + 属性 | — | ✅ 属性层(density) |
| `StatFs`(存储容量) | 文件系统 statfs | — | 🟡 sus_mounts/内核 |
| `BatteryManager`(充电状态——备用机检测) | Binder(battery 服务)+ 广播 | — | 🟡 需 Binder |

### 6.2 反射专项:Build.* 静态字段(最高危漏洞)

```java
// 检测器反射读取——绕过 SystemProperties.get 的属性伪装
Build.MODEL  // 直接读静态字段(非属性读取!)
Class.forName("android.os.Build").getField("MODEL").get(null)
Class.forName("android.os.Build$VERSION").getField("RELEASE").get(null)
```

**根因(代码定位)**:`susfs_restore_boot()`(属性伪装)在 **`on_post_fs_data()`**(实测 42s)执行;而 **zygote 在 2s 启动**——zygote 启动时读取属性存入 `Build.*` 静态字段(**真实值**),fork 所有 App 继承该缓存。**SUSFS 属性伪装对已缓存静态字段无效**。

**后果**:
- 检测器反射 `Build.MODEL` = 真实值(如伪装后 model 与属性矛盾 → 改机检测命中)
- 当前未暴露原因:设备标识(model/brand/SN)**尚未加入伪装**(真实=属性一致);root 伪装(type/secure)检测器主要看属性不做 Build 对比

**封堵**:伪装提前到 zygote exec 前(内核 execve hook 检测到 zygote 启动时,先应用属性伪装再放行)——zygote 读到的就是伪装值 → `Build.*` 缓存伪装值 → 反射安全。

### 6.3 Runtime.exec / ProcessBuilder / 命令执行

| 命令(检测器 exec) | 数据源 | SUSFS 覆盖 | 状态 |
|---|---|---|---|
| `getprop ro.build.type` 等 | 属性存储 | ✅ 伪装生效(实测 `user`/`0`) | ✅ |
| `cat /proc/version` | procfs | ✅ 已伪装 | ✅ |
| `ls /system/bin/su` | 文件 | ✅ sus_paths → ENOENT | ✅ |
| `mount` | /proc/mounts | ✅ sus_mounts(vendor/odm 正常可见) | ✅ |
| `cat /proc/cpuinfo` | procfs | ✅ 已修(socinfo) | ✅ |
| **`ps`** | **/proc 进程列表** | 🔴 **`TEESimulator` 等 root 进程可见** | 🔴 需 hide_task |
| `su -c "..."` | su 文件 | ✅ execve ENOENT | ✅ |
| `uname -a` | 内核 | ✅ 已修 | ✅ |
| `ip addr` / `wm size` | 系统服务 | 🟡 部分 | 🟡 |
| `dumpsys` | 系统服务 | 🟡 部分(明文数据) | 🟡 |

**结论**:命令执行**不构成独立绕过**——命令工具读的是系统数据源,SUSFS 内核级伪装天然覆盖;**唯一缺口 = 进程列表(ps)**。这正是 SUSFS 优于抹机王 Hook 之处(抹机王必须 Hook `Runtime.exec` 拦截命令输出;SUSFS 让命令读到伪装数据,无需拦截)。

### 6.4 native 层(syscall / JNI / so)

| 路径 | 数据源 | SUSFS 覆盖 |
|---|---|---|
| `__system_property_get`(native 属性读) | 属性存储 | ✅ 伪装生效 |
| `open/read`(原始 syscall,Duck Detector 用) | VFS 层 | 🟡 **需验证 sus_paths 对原始 syscall 的生效**(Duck 曾读到 /system/bin/su——删文件后解决) |
| `ioctl(SIOCGIFHWADDR)` | 内核 net | 🔴 **MAC——需内核 patch** |
| `uname`/`sysconf` | 内核 | ✅ 已修 |
| `dlopen`/`/proc/self/maps`(检测注入) | 进程内存 | ✅ 无注入时无 libzygisk 可查 |
| `/proc/self/status` TracerPid(反调试) | procfs | ✅ 无调试器时 TracerPid=0 |

### 6.5 文件直读(/proc、/sys、/dev)

| 文件 | 用途(检测) | 状态 |
|---|---|---|
| `/proc/version` | 内核标识 | ✅ 已伪装 |
| `/proc/cpuinfo` | CPU/改机 | ✅ 已修 |
| `/proc/cmdline` | boot 参数 | ✅ 0440 root:radio(普通 App 读不到) |
| `/proc/uptime` | **开机时长(新机/备用机检测)** | 🟡 未处理 |
| `/proc/mounts` | 挂载 | ✅ |
| `/proc/kallsyms` | 内核符号 | ✅ kptr_restrict |
| `/sys/class/net/{wlan0,eth0}/address` | **MAC** | 🔴 需内核 patch |
| `/sys/class/android_usb/android0/iSerial` | USB 序列号 | 🟡 需 patch |
| `/system/build.prop` | 系统属性文件 | ✅ sus_paths 隐藏 |
| `/data/adb/` | root 痕迹 | ✅ sus_map 隐藏 |
| `/dev/block/by-name/` | 分区/root | 🟡 sus_paths 部分 |

### 6.6 Binder 服务(非 Zygisk 无解的领域)

| 服务 | 数据 | 状态 |
|---|---|---|
| PackageManager | 应用列表 | 🔴 需 Hook(Binder) |
| ActivityManager | 运行进程/服务 | 🔴 需 Hook |
| LocationManager | 定位 | 🔴 需 Hook(虚拟定位) |
| SensorManager | 传感器列表 | 🔴 需 Hook |
| TelephonyManager | IMEI/IMSI | ✅ **权限已保护**(普通 App 反射也拿不到) |

### 6.7 环境/网络指纹

| 指纹 | 用途 | 状态 |
|---|---|---|
| WebView UA(`http.agent`) | 设备识别 | ✅ set_props |
| 代理/VPN/TUN | 云机/羊毛党检测(luna checkvtools) | ✅ 网络干净 |
| 时区/语言/地区 | 环境指纹 | 🟡 属性可改 |
| 电池充电状态 | 备用机检测(电量 100%+无 SIM) | 🟡 需 Binder/属性 |
| 传感器数量 | 云机检测 | 🟡 需 Binder |
| 开机时间/使用时长 | 新机检测 | 🟡 /proc/uptime |

---

## 七、封堵矩阵与待实施清单(汇总)

### 🔴 真实漏洞(当前可被绕过——需实施)
| # | 漏洞 | 绕过方式 | 封堵方案 | 影响 |
|---|---|---|---|---|
| 1 | **Build.* 静态字段** | 反射读 zygote 缓存(真实值) | 伪装提前到 zygote exec 前 | 高(一旦加设备标识伪装就矛盾) |
| 2 | **MAC 地址** | NetworkInterface 反射/ioctl/文件 | 内核 patch `SIOCGIFHWADDR` + `address_show` | 高(组合指纹唯一性) |
| 3 | **进程列表(ps)** | Runtime.exec("ps") 看 root 进程 | 内核 patch `hide_task`(proc getdents 过滤) | 中 |
| 4 | **原始 syscall 绕过 sus_paths** | Duck Detector 曾读到 /system/bin/su | 验证 sus_paths 的 VFS hook 覆盖(或删文件) | 中(待验证) |

### 🟡 可选补充(按检测器威胁排序)
| # | 项 | 封堵 | 对应检测 |
|---|---|---|---|
| 5 | /proc/uptime | 内核 patch 伪装 | 新机/备用机 |
| 6 | 传感器/电池 Binder 层 | 需 Hook(非 Zygisk 难) | 云机/备用机 |
| 7 | 时区/语言 | 属性 | 环境指纹 |

### ✅ 已封堵(无需动作)
属性存储(含反射)、Settings 数据库(含反射)、IMEI(Binder 权限)、内核标识(/proc/version/uname)、cpuinfo、cmdline、挂载、su 文件、build.prop、/data/adb、kallsyms、WebView UA、网络环境。

---

## 八、评审:遗漏点对比(抹机王 Hook 清单 vs 检测面全集)

### 抹机王覆盖、本方案需注意的
| 抹机王 Hook | 对应数据源 | 本方案状态 |
|---|---|---|
| `getSimOperatorName/getNetworkOperatorName`(运营商名) | 属性/telephony | 🟡 属性层可伪装 |
| `java.util.Properties`/`System.getProperty` | Java 系统属性 | 🟡 部分(非 ro.* 的 java 属性) |
| `com.baidu.deviceid`(百度设备 ID) | 广告/设备 ID 服务 | 🟡 需 OAID 层(属性/数据库) |
| `com.ludashi.benchmark`(鲁大师规避) | 应用列表/进程 | 🔴 依赖应用列表隐藏 |
| `WebView.setUserAgentString` | WebView UA | ✅ http.agent set_props |
| `AudioManager.getStreamVolume` | 音频 | ✅ 属性部分 |

### 本方案覆盖、抹机王沙盒外无效的(我们的优势)
| 项 | 说明 |
|---|---|
| `/proc/version`、`/proc/cpuinfo`、`/proc/cmdline` | 抹机王沙盒外不生效;SUSFS 系统级已修 |
| 网络代理/VPN 检测(luna checkvtools) | 系统级干净 |
| IMEI 权限保护 | 系统级(沙盒内抹机王需 Hook,系统级权限已挡) |

### 遗漏补充(抹机王也没覆盖,但检测器可能用)
| 项 | 检测用途 | 本方案状态 |
|---|---|---|
| `/proc/uptime` | 新机/备用机(开机时长) | 🟡 未处理 |
| 传感器列表 | 云机检测 | 🟡 未处理 |
| 电池充电状态 | 备用机检测(luna l0) | 🟡 未处理 |
| 存储容量(StatFs) | 设备规格指纹 | 🟡 未处理 |

---

## 九、最终结论(更新)

1. **SUSFS 属性伪装覆盖 ~85% 读取路径**(属性/文件/proc/native/命令——读取时欺骗,无注入痕迹)
2. **反射不是独立绕过**——底层数据源相同——**唯一例外是 Build.* 静态字段(zygote 缓存时机)**——需时序修复
3. **Runtime.exec 不构成绕过**——命令读伪装数据——**唯一缺口 ps(进程列表)**
4. **真实漏洞 4 项**:Build 缓存时机 / MAC / 进程列表 / 原始 syscall 验证——**均为内核 patch 可解**
5. **Binder 层(应用列表/虚拟定位/传感器)免 Zygisk 无解**——但 IMEI 已被权限保护,其余检测器实际使用率低
