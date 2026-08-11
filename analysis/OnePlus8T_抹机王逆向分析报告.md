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
