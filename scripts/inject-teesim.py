#!/usr/bin/env python3
"""
inject-teesim.py — TEESimulator 固化(方案 Y):开机自动启动 TEESimulator

背景(OnePlus8T / kebab, LineageOS 20 + KSU-Next + SUSFS):
  - TEESimulator 需要注入 keystore2 进程 + Java App 常驻,才能模拟
    硬件密钥认证(修复 Momo "TEE 损坏"、银行 App 检测)
  - 方案 Y = 内核注入开机启动 + /data 文件(OnePlus 8T system-as-root 切根后
    ramdisk 释放,文件必须放 /data/local/teesim,刷机后一键部署一次):
      1. teesim 文件(classes.dex / libTEESimulator.so / inject /
         keybox.xml / target.txt / resetprop / start.sh)放在
         /data/local/teesim/(刷机流程中的部署步骤)
      2. KERNEL_SU_RC 注入 `on post-fs-data` 段 start teesim service,
         service 以 u:r:su:s0 运行 /data/local/teesim/start.sh
      3. start.sh 等待 sys.boot_completed=1 后:
         - 复制 target.txt/keybox.xml → /data/adb/tricky_store(硬编码路径)
         - chcon /data/local/teesim/* 为 adb_data_file(keystore 域可读)
         - ksud sepolicy patch 2 条(keystore 读 adb_data_file/shell_data_file)
         - 守护循环:启动 TEESimulator App,死亡自动重启
  参考:inject-early-monitor.py(B2 ReZygisk 同款注入框架)

幂等:SCRIPT_MARK 检测,已注入则跳过。
"""

import sys
import os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_TEESIM_INJECTED */"

# 注入到 KERNEL_SU_RC 的 C 字符串行(追加在末尾,保持 on 段 + service 顶层结构)
#
# 关键设计(实测/源码确认):
#  - `on post-fs-data` 段 start teesim:此时 /system 已挂载(sh 可用)、
#    ksud 已运行(sepolicy patch 可用);start.sh 内部再等 boot_completed
#  - service(非 oneshot):start.sh 是守护循环(每 30s 检查 App 存活),
#    必须常驻;class core 早期启动不阻塞
#  - seclabel u:r:su:s0:KSUN su 域,能 exec sh/chcon/ksud/app_process
#    (与手动部署验证时的域一致)
#  - 不用 on init:B2 教训 on init exec 阻塞;且 on init 时 /system 未挂载,
#    /system/bin/sh 不可用
TEESIM_RC_LINES = (
    '    "on post-fs-data\\n"\n'
    '    "    setprop sys.teesim.started 1\\n"\n'
    '    "    start teesim\\n"\n'
    '    "\\n"\n'
    '    "service teesim /system/bin/sh /data/local/teesim/start.sh\\n"\n'
    '    "    class core\\n"\n'
    '    "    user root\\n"\n'
    '    "    seclabel u:r:su:s0\\n"\n'
    '    "    disabled\\n"\n'
    '    "\\n"\n'
)


def find_file(root, candidates):
    for c in candidates:
        p = os.path.join(root, c)
        if os.path.exists(p):
            return p
    return None


def inject_teesim_rc(kernel_root):
    path = find_file(kernel_root, [
        "drivers/kernelsu/runtime/ksud_integration.c",
        "KernelSU/kernel/runtime/ksud_integration.c",
    ])
    if not path:
        print("  WARNING: ksud_integration.c not found")
        return True
    with open(path) as f:
        content = f.read()

    if SCRIPT_MARK in content:
        print(f"  {path}: already injected")
        return True

    # 追加到 KERNEL_SU_RC 末尾:锚点是最后一个 on 段后的 "\n\n" 结尾
    # 找 "on property:sys.boot_completed=1\n" 段作为锚点,在其后插入
    anchor = '"on property:sys.boot_completed=1\\n"'
    if anchor not in content:
        print(f"  WARNING: anchor {anchor!r} not found in {path}")
        return True

    content = content.replace(
        anchor,
        anchor + "\n" + SCRIPT_MARK + "\n" + TEESIM_RC_LINES,
        1,
    )
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: injected on-post-fs-data teesim service")
    return True


def inject_selinux_rule(kernel_root):
    """su 域需要 exec ramdisk 里的 /teesim/start.sh(rootfs/unlabeled)。

    service teesim seclabel u:r:su:s0:init 以 su 域 exec /system/bin/sh,
    sh 再读/执行 /teesim/start.sh(ramdisk 根文件,rootfs/unlabeled 标签)。
    KSUN 的 rules.c 已有 init→ksu 域全权,但 su 域对 rootfs 文件的
    execute_no_trans/read/open 需显式补充(手动验证:adb root 的 su 域
    能执行系统内文件,但 ramdisk rootfs 文件是新场景,补规则保险)。
    """
    path = find_file(kernel_root, [
        "drivers/kernelsu/selinux/rules.c",
        "KernelSU/kernel/selinux/rules.c",
    ])
    if not path:
        print("  WARNING: selinux/rules.c not found (skip sepolicy rule)")
        return True
    with open(path) as f:
        content = f.read()

    if SCRIPT_MARK in content:
        print(f"  {path}: sepolicy already injected")
        return True

    anchor = 'ksu_allow(db, "init", KERNEL_SU_DOMAIN, ALL, ALL);'
    if anchor not in content:
        print(f"  WARNING: init->ksu anchor not found in {path}")
        return True

    rule = (
        "\n"
        "\t// Y: TEESimulator started by `on post-fs-data` start teesim.\n"
        "\t// service seclabel u:r:su:s0 exec /system/bin/sh + /data/local/teesim/start.sh\n"
        "\t// (data files). su domain needs adb_data_file access.\n"
        "\t// IMPORTANT: keystore rules are baked in at build time because\n"
        "\t// runtime `ksud sepolicy patch` was observed to crash/reboot the\n"
        "\t// device (file-class rules too, on this kernel) — build-time rules\n"
        "\t// are safe and effective from first boot.\n"
        "\tksu_allow(db, \"su\", \"rootfs\", \"file\", \"execute_no_trans\");\n"
        "\tksu_allow(db, \"su\", \"rootfs\", \"file\", \"execute\");\n"
        "\tksu_allow(db, \"su\", \"rootfs\", \"file\", \"read\");\n"
        "\tksu_allow(db, \"su\", \"rootfs\", \"file\", \"open\");\n"
        "\tksu_allow(db, \"su\", \"unlabeled\", \"file\", \"execute_no_trans\");\n"
        "\tksu_allow(db, \"su\", \"unlabeled\", \"file\", \"execute\");\n"
        "\tksu_allow(db, \"su\", \"unlabeled\", \"file\", \"read\");\n"
        "\tksu_allow(db, \"su\", \"unlabeled\", \"file\", \"open\");\n"
        "\tksu_allow(db, \"su\", \"adb_data_file\", \"dir\", \"search\");\n"
        "\tksu_allow(db, \"su\", \"adb_data_file\", \"file\", \"read\");\n"
        "\tksu_allow(db, \"su\", \"adb_data_file\", \"file\", \"open\");\n"
        "\t// keystore2 must dlopen libTEESimulator.so from /data/local/teesim\n"
        "\t// (chcon'd adb_data_file). Build-time rule — no runtime patch.\n"
        "\tksu_allow(db, \"keystore\", \"adb_data_file\", \"file\", \"read\");\n"
        "\tksu_allow(db, \"keystore\", \"adb_data_file\", \"file\", \"open\");\n"
        "\tksu_allow(db, \"keystore\", \"adb_data_file\", \"file\", \"execute\");\n"
        "\tksu_allow(db, \"keystore\", \"adb_data_file\", \"file\", \"execute_no_trans\");\n"
        "\tksu_allow(db, \"keystore\", \"shell_data_file\", \"file\", \"read\");\n"
        "\tksu_allow(db, \"keystore\", \"shell_data_file\", \"file\", \"open\");\n"
        "\tksu_allow(db, \"keystore\", \"shell_data_file\", \"file\", \"execute\");\n"
        "\tksu_allow(db, \"keystore\", \"shell_data_file\", \"file\", \"execute_no_trans\");\n"
        "\t" + SCRIPT_MARK + "\n"
    )
    content = content.replace(anchor, anchor + rule, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: injected su exec rootfs/unlabeled rules")
    return True


def main():
    ok = True
    ok &= inject_teesim_rc(KERNEL_ROOT)
    ok &= inject_selinux_rule(KERNEL_ROOT)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
