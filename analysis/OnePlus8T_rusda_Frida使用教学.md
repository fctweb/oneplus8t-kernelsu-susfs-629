# rusda 17.15.0(Frida 反检测魔改版)使用教学手册

> 适用设备:OnePlus 8T(KB2000,Android 13,arm64) · 电脑:macOS · 目标:逆向分析 App(如今日头条)**且不影响银行等 App 使用**
> 更新日期:2026-08-13

---

## 〇、先搞懂三个关键原则(避免翻车)

1. **rusda 是"按需启停"的分析工具,不是常驻服务**
   - 分析时启动 → 分析完 `kill` → 用银行时设备里**没有任何注入框架痕迹** → 银行永远不受影响
2. **注入是"按目标进程"的**
   - 你只 attach 今日头条 → 只有头条进程被注入 → 银行进程零痕迹
3. **环境级扫描靠"改名 + 换端口"防**
   - rusda 已改掉 `frida-server` 进程名/线程名/内存字符串(XOR 加密)
   - **端口必须手动换**(默认 27042 是结构性硬伤,扫端口的 App 一抓一个准)

---

## 一、前置准备(一次性)

### 1.1 电脑端确认

```bash
# adb 可用(本机路径)
export PATH="$HOME/Library/Android/sdk/platform-tools:$PATH"
adb devices          # 应显示 13cda54f device

# Python 3 可用(本机自带 3.9.6)
python3 --version

# xz 解压工具(macOS 自带)
which xz
```

### 1.2 设备端确认

```bash
adb shell getprop ro.product.cpu.abi   # 应输出 arm64-v8a(确认是 arm64)
adb shell getprop sys.boot_completed   # 应输出 1(系统已开机)
```

---

## 二、下载 rusda 17.15.0(电脑端,一次性)

### 2.1 下载地址

GitHub Releases:
```
https://github.com/taisuii/rusda/releases/tag/17.15.0
```

需要下载的文件(OnePlus 8T 是 arm64):
| 文件 | 用途 |
|---|---|
| **`rusda-server-17.15.0-android-arm64.xz`** | 设备端守护进程(核心,必下) |
| `rusda-gadget-17.15.0-android-arm64.so.xz` | 嵌入式注入库(可选,重打包 App 用) |
| `rusda-inject-17.15.0-android-arm64.xz` | 无 server 的注入器(可选,L2 高级) |

命令行下载(推荐):
```bash
cd ~/Downloads && mkdir -p rusda && cd rusda
curl -L -o rusda-server.xz \
  "https://github.com/taisuii/rusda/releases/download/17.15.0/rusda-server-17.15.0-android-arm64.xz"
```

### 2.2 解压

```bash
xz -d rusda-server.xz
ls -la rusda-server          # 约 40MB 的 ELF 可执行文件
file rusda-server            # 应显示 ELF 64-bit LSB executable, ARM aarch64
```

> ⚠️ 若 `xz -d` 后文件名没有后缀,直接用;产物是 ELF 二进制,无需扩展名。

---

## 三、部署到设备(每次重刷机后需重做)

### 3.1 push + 改名(改名进一步降低检测概率)

```bash
# 推送到 /data/local/tmp(标准临时目录)
adb push rusda-server /data/local/tmp/

# 改名成不显眼的名字(例:像系统工具)
adb shell "mv /data/local/tmp/rusda-server /data/local/tmp/audioserver"
adb shell "chmod 755 /data/local/tmp/audioserver"
```

> 改名理由:即使 rusda 已改名,再套一层"系统服务名"更稳(ps 里 `audioserver` 毫不违和)。

### 3.2 启动(关键:换端口 + 用 setsid!)

```bash
# 用随机高端口(避开 27042/27043 默认端口)
# 注意:本机 SUSFS 已隐藏 su——用 adb root 提权(不要用 su -c)
adb root                       # 重启 adbd 为 root(uid=0, context=u:r:su:s0)
adb shell "setsid /data/local/tmp/audioserver -l 127.0.0.1:47777 >/data/local/tmp/rusda.log 2>&1 &"
```

| 参数 | 说明 |
|---|---|
| `-l 127.0.0.1:47777` | 只监听本机 + 非默认端口(防端口扫描) |
| `adb root` 先提权 | 本机 SUSFS 隐藏了 su——必须用 adb root(不是 su -c) |
| **`setsid`(必用!)** | **脱离 adb shell 会话——否则 server 随 adb shell 退出被杀**(`nohup` 不够——实测 `nohup ... &` 下 frida 连 server 报 `connection closed`;`setsid` 后稳定) |
| `&` | 后台运行 |

验证启动成功(进程名会与系统 audioserver 混淆,别只看 ps):
```bash
adb shell "cat /data/local/tmp/rusda.log 2>/dev/null"   # 空=正常
adb forward tcp:47777 tcp:47777                         # 端口转发(必须)
frida-ps -H 127.0.0.1:47777                             # 能列出进程=server 存活(最可靠)
```

> ⚠️ **端口号记下来**(PC 端连接要用)。每次启动换不同端口更安全(可写进启动脚本随机)。
> ⚠️ **Enforcing 下 attach 会失败**(`agent connection closed unexpectedly`——SELinux MLS 拒绝 memfd 注入,见附录 B)——分析前先 `adb shell setenforce 0`,见附录 B.2 完整流程。

---

## 四、电脑端安装 frida-tools(一次性)

rusda 兼容官方客户端,直接装官方 frida-tools 即可。

### 4.1 安装(推荐 venv,避免污染系统 Python)

```bash
cd ~/rusda
python3 -m venv frida-env
source frida-env/bin/activate
pip install frida-tools
# 检查版本(frida 应为 17.x,与 rusda 17.15.0 匹配)
frida --version
```

> 若不想用 venv:`pip3 install --user frida-tools`(macOS 系统 Python 3.9.6 若报 PEP 668,用 venv)。

### 4.2 连接验证

```bash
# ⚠️ 先做端口转发(必须):
adb forward tcp:47777 tcp:47777
# 再连接——注意用 -H(不能带 -U,-U 与 -H 互斥!)
frida-ps -H 127.0.0.1:47777
```

看到进程列表 = rusda-server 与 frida-tools 连接成功。

> ⚠️ **`-H 127.0.0.1:47777` 必须带**——因为 rusda-server 监听的是 47777,不是默认 27042。每次连接都要带端口。

---

## 五、实战:逆向分析今日头条

### 5.1 获取包名

```bash
# 设备上打开今日头条,然后:
adb shell "dumpsys activity activities | grep topResumedActivity"
# 或直接查:
adb shell "pm list packages | grep -i toutiao"   # com.ss.android.article.news
```

今日头条包名:`com.ss.android.article.news`

### 5.2 两种启动方式

**方式 A:attach(App 已运行)**
```bash
frida -H 127.0.0.1:47777 com.ss.android.article.news
```

**方式 B:spawn(冷启动,可 hook 启动早期代码)**
```bash
frida -H 127.0.0.1:47777 -f com.ss.android.article.news --no-pause
```

进入交互式控制台后:
```javascript
// 测试 hook Java 方法(例:打印 toast)
Java.perform(function () {
  console.log("[*] Java bridge OK");
  // 你的 hook 逻辑写这里
});
```

### 5.3 常用分析命令

| 命令 | 作用 |
|---|---|
| `frida-ps -H 127.0.0.1:47777` | 列出进程 |
| `frida-trace -H 127.0.0.1:47777 -i open com.ss.android.article.news` | 追踪 native open 调用 |
| `frida -H 127.0.0.1:47777 -l script.js com.ss.android.article.news` | 加载 JS 脚本 |
| `frida -H 127.0.0.1:47777 -f 包名 --no-pause` | spawn 冷启动 |

### 5.4 示例脚本(查头条的 Frida 检测)

保存 `check_frida.js`:
```javascript
Java.perform(function () {
  // 1. 检查目标进程是否有 Frida 检测线程(正常应无)
  console.log("[*] 当前进程: " + Process.id);
  // 2. hook 常见检测点:读 /proc/self/task 枚举线程名
  var File = Java.use("java.io.File");
  // 3. 列出加载的 so
  Process.enumerateModules().forEach(function (m) {
    if (m.name.toLowerCase().indexOf("sec") >= 0) {
      console.log("[so] " + m.name + " @ " + m.base);
    }
  });
  console.log("[*] hook 注入成功,头条进程已可操作");
});
```

运行:
```bash
frida -H 127.0.0.1:47777 -l check_frida.js com.ss.android.article.news
```

> 字节系 App 内置 sec-sdk——它会动态扫 rw-p 段内存找 `frida-eternal-agent` 等字符串——**这正是 rusda XOR 运行时解码的应对场景**(明文只在栈上一闪即逝)。

---

## 六、用完清理(关键!保护银行 App)

### 6.1 标准清理流程

```bash
# 1. 退出 frida 客户端(Ctrl+C)

# 2. 杀掉 rusda-server——⚠️ 用精确 pid,勿 killall(会误杀系统原生 audioserver!)
#    系统自带 audioserver(pid ~1222)是 Android 音频服务,不能杀
#    我们的 rusda 是 root 用户启动的(ps 第二列是 root)
adb shell "kill <rusda的pid>"      # pid 从 ps -A 里找 root 用户的 audioserver

# 3. 删除设备端文件(彻底无痕)
adb shell "rm -f /data/local/tmp/audioserver"
#    ⚠️ 删文件时用全路径 /data/local/tmp/audioserver——不会碰到系统的 /system/bin/audioserver

# 4. 确认无残留
adb shell "ps -A | grep -iE 'audioserver|frida|rusda'"   # 应无输出
adb shell "ls /data/local/tmp/"                          # 应无 audioserver

# 5. 最稳妥:重启一次(清 TracerPid 等瞬时残留)
adb reboot
```

### 6.2 "用银行前必须"检查清单

用农业银行/兴业银行/支付宝/微信前,确认:
```bash
adb shell "ps -A | grep -iE 'frida|rusda|audioserver'"
# 无输出 = 环境干净,可放心用银行
```

---

## 七、与银行 App 共存的完整规范

| 场景 | 操作 |
|---|---|
| **逆向分析头条** | 启动 rusda-server(换端口)→ 分析 → 完成 |
| **用完** | killall + 删文件 + 重启(必做) |
| **用银行 App** | 确保 rusda-server 未运行(检查清单) |
| **银行 App 使用中** | 绝不启动 rusda-server |
| **设备重启后** | rusda-server 不会自启(手动启动)→ 天然干净 |

**为什么这样保证银行不受影响:**
1. 银行进程从未被 attach → 进程内零 Frida 痕迹
2. 用银行时 rusda-server 未运行 → 环境级扫描(端口/进程名/内存)全部干净
3. 设备重启后无自启 → 长期干净

---

## 八、常见问题排错

| 现象 | 原因 | 解决 |
|---|---|---|
| `frida-ps -U -H ...` 连接失败 | 端口写错 / server 没起 | 确认 `-l` 端口与 `-H` 端口一致 |
| attach 后 App 秒退 | 该 App 检测到注入 | 换端口再试;若仍死 = 需要更深对抗(L2 级,超出 rusda) |
| `Failed to attach: process not found` | 包名错 / App 没运行 | 用 `frida-ps -U -H ...` 确认进程名 |
| frida 版本不匹配 | PC 端 frida 与 server 版本差太多 | `pip install -U frida-tools`(17.x 即可) |
| 银行 App 报风险 | rusda-server 还在跑 | killall + 重启,按 6.1 清理 |

---

## 九、进阶(可选)

### 9.1 一键启动脚本(每次随机端口)

设备端 `start.sh`:
```bash
#!/system/bin/sh
PORT=$((30000 + RANDOM % 20000))   # 随机 30000-49999
echo "listening on $PORT"
/data/local/tmp/audioserver -l 127.0.0.1:$PORT &
echo $PORT > /data/local/tmp/audioserver.port
```
电脑端读端口:`adb shell cat /data/local/tmp/audioserver.port`

### 9.2 spawn 早期 hook(分析头条启动流程)

```bash
frida -H 127.0.0.1:47777 -f com.ss.android.article.news \
  -l /path/to/script.js --no-pause
```
脚本里 `Java.perform` 前加 `Java.performNow` 可更早注入。

### 9.3 如果 rusda 也被头条检测(升级路径)

按作者决策树:**Florida → rusda → 都死 = Level 2/3 自研**。
- Level 2(自研 stealth-injector):跳过 server,用 `rusda-inject` 直注入(项目已提供 inject 产物)
- Level 3(环境伪装):您已用 SUSFS 内核方案完成(比 Magisk 层更底层)

---

## 十、资源速查

| 资源 | 地址 |
|---|---|
| rusda 仓库 | https://github.com/taisuii/rusda |
| rusda Release | https://github.com/taisuii/rusda/releases |
| 原理教程(微信公众号) | R逆向(frida 魔改系列) |
| Frida 官方文档 | https://frida.re/docs/ |
| frida-tools | `pip install frida-tools` |

**一句话总结**:下载 rusda-server arm64 → push 改名 → `-l 随机端口` 启动 → PC 端 `frida-ps -U -H 端口` → 分析头条 → **用完 kill + 删 + 重启** → 银行永远干净。

---

## 附录 A:实操验证记录(2026-08-13,OnePlus 8T 实测)

### A.1 验证结果(全通过)

| 步骤 | 结果 |
|---|---|
| 下载 rusda-server-17.15.0-arm64(51MB ELF,`file` 确认 aarch64) | ✅ |
| venv 装 frida-tools(frida 17.17.0,与 server 17.15.0 同主线兼容) | ✅ |
| push `/data/local/tmp/audioserver` + chmod 755 | ✅ |
| `adb root` 提权 + `-l 127.0.0.1:47777` 启动 | ✅(pid 25565 root 用户,ss 确认监听) |
| `adb forward tcp:47777 tcp:47777` + `frida-ps -H 127.0.0.1:47777` | ✅(列出全设备进程,含 TEESimulator/Hunter/银行) |
| `frida -H ... -n Files -e "Java.perform(...)"` attach 注入 | ✅(Frida 控制台正常进入) |
| 清理:kill + 删文件 + 端口释放 | ✅ |
| 银行 App 未受影响(com.android.bankabc 正常运行) | ✅ |

### A.2 踩坑记录(重要)

1. **su 被 SUSFS 隐藏** → 启动**必须用 `adb root`**(执行后 `id` 显示 uid=0, context=u:r:su:s0),`su -c` 会报 `inaccessible or not found`
2. **frida 连接参数**:`frida-ps -H 127.0.0.1:47777`——**不能带 `-U`**(`-U` 与 `-H` 互斥,会报 `Only one of -D, -U, -R, and -H may be specified`);必须先 `adb forward`
3. **系统原生 `audioserver` 进程混淆**:设备本来就有 `audioserver`(pid ~1222,`android.hardware.audio.service` 1047)——**清理时勿 `killall audioserver`**(会杀系统音频服务),**必须用精确 pid**(ps 里 root 用户、从 /data/local/tmp 启动的那个);删文件用全路径 `/data/local/tmp/audioserver`
4. rusda-server 监听验证:`adb shell ss -tln | grep 47777`(47777=0xBB51)
5. 头条未安装时可用任意无害 App(如 Files)验证 attach 功能——**不要用银行 App 测试注入**

---

## 附录 B:setenforce 0 分析规范 + SELinux MLS 限制(2026-08-13 实测发现)

### B.1 限制:Enforcing 下 attach 失败(MLS 约束)

**实测现象**:rusda attach 任何 App(Clock/抖音/Settings)在 SELinux **Enforcing** 下都报
`Failed to attach: agent connection closed unexpectedly`;`setenforce 0` 后立即成功。

**根因**(logcat avc denied 实锤):
```
avc: denied { read write } for path=/memfd:jit-cache (deleted) dev="tmpfs"
  scontext=u:r:untrusted_app:s0:c138,... tcontext=u:object_r:unlabeled:s0 tclass=file
```
- frida/rusda 注入 agent 用 `memfd_create`(rusda 已改名 `memfd:jit-cache`)
- memfd 标签 = `unlabeled`;untrusted_app 域读写它受 **SELinux MLS 约束(mlsconstrain)** 拒绝
- **ksud sepolicy patch 的 allow 规则无法覆盖 mlsconstrain**(试过 `allow untrusted_app unlabeled file *` 仍拒绝——read 放行但 write 仍拒)
- `setenforce 0`(permissive)绕过所有 avc 决策 → 注入成功

### B.2 分析规范(临时方案,已实测)

```
分析抖音等 App:
  adb shell setenforce 0          # 1. 临时 permissive(注入通道打开)
  adb shell "setsid /data/local/tmp/audioserver -l 127.0.0.1:47777 >/data/local/tmp/rusda.log 2>&1 &"   # 2. 启动 rusda(必用 setsid——nohup 会被 adb shell 退出杀掉)
  adb forward tcp:47777 tcp:47777 # 3. 端口转发
  frida -H 127.0.0.1:47777 -p <pid> -l script.js    # 4. 分析
  # 分析完(4 步,缺一不可):
  adb shell "kill \$(ps -A | grep 'tmp/audioserver' | awk '{print \$2}') 2>/dev/null"   # a. 杀 rusda 进程(按路径匹配,不误杀系统 audioserver)
  adb forward --remove tcp:47777 # b. 移除端口转发(必须——残留转发=连接口仍开着)
  adb shell setenforce 1          # c. 立即恢复 enforcing(关键!)
  # d. 文件处置(二选一):
  #    彻底干净:  adb shell "rm -f /data/local/tmp/audioserver"(下次需重新 push 53MB)
  #    保留复用:  adb shell "ls /data/local/tmp/audioserver"(下次直接 setsid 启动,免重新部署)
```

⚠️ **setenforce 0 期间的信号**:全局 permissive 是系统级异常(正常设备 enforcing)——**分析期间不要开银行 App**;分析完立即恢复 enforcing 即无残留。

### B.3 内核级根治方案(已实验,暂停)

| 方案 | 做法 | 状态 |
|---|---|---|
| **A. avc hook** | 内核 kprobe `avc_has_perm`,对 tsid=unlabeled 放行(memfd 注入通道) | ❌ **已实验失败并回滚**:构建出 1b0cffc 刷入后,打开 KernelSU-Next App 触发系统崩溃(重启),已回滚到 7bf9edb 稳定版。原因分析:kprobe 高频触发 + early-props 注入叠加,风险大于收益——**暂停,不继续** |
| **B. 改 mlsconstrain** | 编译期去掉 untrusted_app 写 unlabeled 的 MLS 约束 | 🟡 中——改 policy 二进制结构,有哈希/结构比对风险(未实验) |
| **C. frida-gadget 重打包** | 绕 memfd 注入(agent 随 App 启动) | 🟢 低——但抖音有加固/签名校验,重打包难 |

**当前结论**:**用 B.2 的 setenforce 0 临时方案**(实测稳定可靠);内核 avc hook 方向已实验证明会崩系统,不再尝试。分析完立即恢复 enforcing 无任何残留与检测信号。
