#!/bin/bash
# =============================================================================
# install-teesim.sh — 一键部署 TEESimulator 到 /data/local/teesim(方案 Y)
# 用途:刷机/重刷系统后部署一次,之后每次开机由内核注入的 service 自动启动
# 用法:adb root 后,在 PC 上执行:
#   bash install-teesim.sh [设备序列号]
# 前置:设备已刷移植内核(含 TEESimulator 注入段)、已部署 ksud(/data/adb/ksud)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/prebuilt/teesim"
ADB="${ADB:-adb}"
SERIAL="${1:-}"

# 选择 adb(支持传入序列号)
if [ -n "$SERIAL" ]; then
    ADB="adb -s $SERIAL"
fi

echo "[1/4] 检查源文件..."
for f in classes.dex libTEESimulator.so inject keybox.xml target.txt start.sh resetprop; do
    [ -f "$SRC/$f" ] || { echo "错误:缺少 $SRC/$f"; exit 1; }
done
echo "  全部 7 个文件就绪"

echo "[2/4] 推送文件到 /data/local/teesim..."
$ADB root >/dev/null 2>&1 || true
sleep 2
$ADB shell "mkdir -p /data/local/teesim" 
$ADB push "$SRC/classes.dex" "$SRC/libTEESimulator.so" "$SRC/inject" \
    "$SRC/keybox.xml" "$SRC/target.txt" "$SRC/start.sh" "$SRC/resetprop" \
    /data/local/teesim/

echo "[3/4] 设置权限与 SELinux 标签..."
$ADB shell "chmod 755 /data/local/teesim/inject /data/local/teesim/start.sh /data/local/teesim/resetprop; chmod 644 /data/local/teesim/classes.dex /data/local/teesim/libTEESimulator.so /data/local/teesim/keybox.xml /data/local/teesim/target.txt; chcon -R u:object_r:adb_data_file:s0 /data/local/teesim/ 2>/dev/null; ls -la /data/local/teesim/"

echo "[4/4] 配置目录(可选,start.sh 每次开机也会自动复制)..."
$ADB shell "mkdir -p /data/adb/tricky_store; cp -f /data/local/teesim/target.txt /data/local/teesim/keybox.xml /data/adb/tricky_store/ 2>/dev/null; chmod 644 /data/adb/tricky_store/* 2>/dev/null; ls /data/adb/tricky_store/"

echo ""
echo "✅ 部署完成!重启后内核注入的 service 将自动启动 TEESimulator。"
echo "验证:adb shell 'ps -A | grep TEESimulator'(开机完成后应看到进程)"
