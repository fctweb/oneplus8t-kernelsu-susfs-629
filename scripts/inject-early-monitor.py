#!/usr/bin/env python3
"""
inject-early-monitor.py — ReZygisk 根治(B2):monitor 提前到 `on init` 启动

背景(OnePlus8T / kebab, LineageOS 20 + KSU-Next + SUSFS):
  - zygote 在 ~4.8s fork(/data 同时就绪)
  - KSUN 的 post-fs-data 注入段未执行;SUSFS umh 兜底 ~39.9s 才启动 ksud
    → ReZygisk monitor(依赖 /data 模块)永远错过 zygote fork
  - ReZygisk 官方机制:ptrace SEIZE init + PTRACE_O_TRACEFORK,必须在
    zygote fork 前 seize init,错过即失效(无兜底)

本脚本(配合 fork 版 ReZygisk):
  1. 在 KERNEL_SU_RC 注入 `on init` 段,init 解析完 rc(≈3s)即 exec
     /rezygisk-monitor(打包进 boot.img ramdisk 的 ReZygisk ptrace monitor)
  2. fork 版 monitor 先 seize init(不依赖 /data),再等 /data 就绪后
     初始化 socket/zygiskd → zygote fork 时一切就绪,正常注入
  3. monitor 以 init 域运行(exec root --,继承 init 域):
     - init 域可 ptrace init(同域,Android 默认允许)
     - ramdisk 文件 /rezygisk-monitor 类型 unlabeled/rootfs——需要
       init 域对其 file execute 权限(见下方 selinux 规则注入)

幂等:SCRIPT_MARK 检测,已注入则跳过。
"""

import sys
import os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_EARLY_MONITOR_INJECTED */"

# 注入到 KERNEL_SU_RC 的 C 字符串行(放在 "on post-fs-data" 段之前)
# on init 段:setprop marker 已验证机制(execdone=1);exec 用
# /system/bin/rezygisk-monitor(monitor 放 /system 而非 ramdisk——本设备
# system-as-root,ramdisk 在 switch_root 后消失)。
EARLY_RC_LINES = (
    '    "on init\\n"\n'
    '    "    setprop sys.rezygisk.early 1\\n"\n'
    '    "    exec root -- /system/bin/rezygisk-monitor monitor\\n"\n'
)


def find_file(root, candidates):
    for c in candidates:
        p = os.path.join(root, c)
        if os.path.exists(p):
            return p
    return None


def inject_early_monitor(kernel_root):
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

    # 在 "on post-fs-data" 段前插入 on init 段
    anchor = '"on post-fs-data\\n"'
    if anchor not in content:
        print(f"  WARNING: anchor {anchor!r} not found in {path}")
        return True

    content = content.replace(
        anchor,
        SCRIPT_MARK + "\n" + EARLY_RC_LINES + anchor,
        1,
    )
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: injected on-init early monitor exec")
    return True


def inject_selinux_rule(kernel_root):
    """init 域需要 exec ramdisk 里的 /rezygisk-monitor(unlabeled/rootfs)。

    KSUN 的 rules.c 已有 `ksu_allow(db, "init", KERNEL_SU_DOMAIN, ALL, ALL)`
    (init→ksu 域全权),但 exec 动作本身是 init 域对文件的操作,补:
      allow init rootfs:file { execute read open }
      allow init unlabeled:file { execute read open }
    rootfs/unlabeled 对应 ramdisk 根文件。monitor 继承 init 域(exec root --),
    因此无需额外域转换;init 域 ptrace init(同域)Android 默认允许。
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
        "\t// B2: early ReZygisk monitor started by `on init` exec root --.\n"
        "\t// exec root -- has no seclabel => monitor keeps the init domain,\n"
        "\t// which requires execute_no_trans (not just execute). Monitor\n"
        "\t// lives in /system/bin (system_file).\n"
        "\tksu_allow(db, \"init\", \"system_file\", \"file\", \"execute_no_trans\");\n"
        "\tksu_allow(db, \"init\", \"system_file\", \"file\", \"execute\");\n"
        "\tksu_allow(db, \"init\", \"system_file\", \"file\", \"read\");\n"
        "\tksu_allow(db, \"init\", \"system_file\", \"file\", \"open\");\n"
        "\tksu_allow(db, \"init\", \"rootfs\", \"file\", \"execute_no_trans\");\n"
        "\tksu_allow(db, \"init\", \"unlabeled\", \"file\", \"execute_no_trans\");\n"
        "\t" + SCRIPT_MARK + "\n"
    )
    content = content.replace(anchor, anchor + rule, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: injected init exec rootfs/unlabeled rules")
    return True


def main():
    ok = True
    ok &= inject_early_monitor(KERNEL_ROOT)
    ok &= inject_selinux_rule(KERNEL_ROOT)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
