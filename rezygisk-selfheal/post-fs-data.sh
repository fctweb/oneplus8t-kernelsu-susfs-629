#!/system/bin/sh
# ============================================================
# ReZygisk Self-Heal (验证版)
# 背景:KSUN 的 post-fs-data 阶段(~43s)晚于 zygote fork(~2s),
#       ReZygisk monitor 的 PTRACE_O_TRACEFORK 错过 zygote,
#       zygiskd 永不被 fork → state.json 不存在 → WebUI 报错。
# 方案:本脚本在 post-fs-data 阶段(monitor 启动后)检测到
#       ReZygisk 错过注入,则自动触发一次 zygote 重启完成注入。
# 幂等:每 boot 最多触发一次(标记文件),平时零影响。
# ============================================================

# 1. 仅当 ReZygisk 已安装时工作
if [ ! -f /data/adb/modules/rezygisk/module.prop ]; then
    exit 0
fi

# 2. 本次开机已修复过,跳过(防 zygote 重启风暴)
MARK=/data/adb/rezygisk/.zygote_restarted
if [ -f "$MARK" ]; then
    exit 0
fi

# 3. 等待 ReZygisk monitor 启动完成(post-fs-data.d 中启动)。
#    错过 zygote 时 zygiskd 不会被 fork,state.json 永不出现。
sleep 3

# 4. 已正常:state.json 存在 = monitor 抓到了 zygote,无需修复
if [ -f /data/adb/rezygisk/state.json ]; then
    exit 0
fi

# 5. 精确复核:zygote64 是否已注入 libzygisk(maps 里找得到)
ZPID=$(pidof zygote64 2>/dev/null)
if [ -n "$ZPID" ] && grep -q "libzygisk" "/proc/$ZPID/maps" 2>/dev/null; then
    exit 0
fi

# 6. 确认错过 → 触发一次 zygote 重启(Android 官方软重启机制,init 自动拉起)
touch "$MARK"
log -p i -t rezygisk-selfheal "ReZygisk missed zygote, restarting zygote to complete injection"
setprop ctl.restart zygote

exit 0
