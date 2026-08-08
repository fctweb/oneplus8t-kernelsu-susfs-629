#!/system/bin/sh
# =============================================================================
# TEESimulator 固化启动脚本(方案 Y)——/data/local/teesim/start.sh
# 由内核注入的 `on post-fs-data` 段 service teesim 启动(u:r:su:s0 域)
# 流程:等 boot 完成 → 复制配置 → chcon 标签 → 守护循环
# =============================================================================

# 0. 单例锁:防止多个守护循环同时运行(否则各自拉起 App 造成内存堆积,
#    曾实测 ~100 个 TEESimulator 实例把内存耗尽、lmkd 误杀前台 App)。
#    ★ 用 mkdir 原子锁(可靠);不用 flock(toybox flock 是外部命令,
#    锁随 flock 进程退出即释放,无法跨周期持有)。
LOCKDIR=/data/local/teesim/daemon.lockdir
mkdir "$LOCKDIR" 2>/dev/null || exit 0
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

# 1. 等待系统完全启动(避免过早注入 keystore2;同时等 /data 就绪)
while [ "$(getprop sys.boot_completed)" != "1" ]; do
    sleep 2
done

# 2. 配置目录(TEESimulator 硬编码 /data/adb/tricky_store,每次开机幂等复制)
mkdir -p /data/adb/tricky_store
cp -f /data/local/teesim/target.txt /data/adb/tricky_store/target.txt 2>/dev/null
cp -f /data/local/teesim/keybox.xml /data/adb/tricky_store/keybox.xml 2>/dev/null
chmod 644 /data/adb/tricky_store/target.txt /data/adb/tricky_store/keybox.xml 2>/dev/null

# 3. 文件标签 → system_file(keystore 域对 system_file 默认有 stat/read/getattr
#    规则,免运行时 sepolicy patch 也免编译期规则;adb_data_file 会因缺 getattr
#    导致 keystore dlopen 时 stat 失败 Permission denied)
#    额外好处:普通 App 域无法读取 system_file 标签的 /data 文件,更隐蔽
chcon -R u:object_r:system_file:s0 /data/local/teesim/ 2>/dev/null

# 4. 守护循环:App(comm=TEESimulator)不在则启动;每 30s 检查
#    ★ 检测用 ps | grep -c(可靠,无 awk 兼容问题);不能用 pgrep -f/-x
#      (toybox 行为异常,匹配到 sh 包装导致无限拉起)也不能用 awk if()
#      (toybox awk 语法报错 → 永远返回失败 → 同样无限拉起)
while true; do
    if [ "$(ps -A | grep -c ' TEESimulator')" = "0" ]; then
        cd /data/local/teesim && PATH=/data/local/teesim:$PATH nohup /system/bin/app_process \
            -Djava.class.path=/data/local/teesim/classes.dex /data/local/teesim \
            --nice-name=TEESimulator org.matrix.TEESimulator.App \
            >/data/local/teesim/app.log 2>&1 &
    fi
    sleep 30
done
