#!/system/bin/sh
# =============================================================================
# TEESimulator 固化启动脚本(方案 Y)——ramdisk /teesim/start.sh
# 由内核注入的 `on post-fs-data` 段 service teesim 启动(u:r:su:s0 域)
# 流程:等 boot 完成 → 复制配置 → chcon 标签 → sepolicy patch → 守护循环
# =============================================================================

# 1. 等待系统完全启动(避免过早注入 keystore2;同时等 /data 就绪)
while [ "$(getprop sys.boot_completed)" != "1" ]; do
    sleep 2
done

# 2. 配置目录(TEESimulator 硬编码 /data/adb/tricky_store,每次开机幂等复制)
mkdir -p /data/adb/tricky_store
cp -f /teesim/target.txt /data/adb/tricky_store/target.txt 2>/dev/null
cp -f /teesim/keybox.xml /data/adb/tricky_store/keybox.xml 2>/dev/null
chmod 644 /data/adb/tricky_store/target.txt /data/adb/tricky_store/keybox.xml 2>/dev/null

# 3. ramdisk 文件标签 → adb_data_file(keystore 域可读注入的 so;每次开机 chcon)
chcon -R u:object_r:adb_data_file:s0 /teesim/ 2>/dev/null

# 4. sepolicy 规则(内存级,每次开机重新 patch;file 类规则实测安全)
/data/adb/ksud sepolicy patch "allow keystore adb_data_file file *" 2>/dev/null
/data/adb/ksud sepolicy patch "allow keystore shell_data_file file *" 2>/dev/null

# 5. 守护循环:App 不在则启动;每 30s 检查(keystore2 重启 → App 自杀 → 自动拉起)
while true; do
    if ! pgrep -f "org.matrix.TEESimulator.App" >/dev/null 2>&1; then
        cd /teesim && PATH=/teesim:$PATH nohup /system/bin/app_process \
            -Djava.class.path=/teesim/classes.dex /teesim \
            --nice-name=TEESimulator org.matrix.TEESimulator.App \
            >/teesim/app.log 2>&1 &
    fi
    sleep 30
done
