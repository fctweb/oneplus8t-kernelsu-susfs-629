#!/usr/bin/env python3
"""
Inject a KSU whitelist check into fork.c's SUSFS hide-bit assignment.

Problem: SUSFS sets susfs_task_state's NON_ROOT_USER_APP_PROC bit on EVERY
fork'd child. KSU root shells (`ksud debug su`) and the manager app are
therefore hidden/killed by SUS_PATH / SUS_MAP hiding (e.g. /system/bin/su),
breaking the manager app's root shell / feature checks.

Fix: only set the hide bit when the parent is NOT KSU-authorized
(ksu domain or allowlisted). Whitelisted parents (root shell, manager
app) get unhidden children; all other apps stay hidden (bank/Hunter
detection preserved). This uses ksu_is_allow_uid_for_current(), which
for uid 0 checks is_ksu_domain() (so init->zygote is NOT whitelisted).

Usage: python3 inject-fork-susfs-whitelist.py <kernel-root>
"""

import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: inject-fork-susfs-whitelist.py <kernel-root>")
        sys.exit(1)

    kernel_dir = sys.argv[1]
    candidates = [
        os.path.join(kernel_dir, "kernel/fork.c"),
        os.path.join(kernel_dir, "fork.c"),
    ]
    filepath = None
    for p in candidates:
        if os.path.exists(p):
            filepath = p
            break
    if not filepath:
        print(f"ERROR: fork.c not found under {kernel_dir}")
        sys.exit(1)

    with open(filepath) as f:
        content = f.read()

    if "KSU_FORK_SUSFS_WHITELIST_INJECTED" in content:
        print("  Already injected, skipping")
        return

    # 1. Add extern declaration after the susfs_def.h include
    ext_decl = (
        "#include <linux/susfs_def.h>\n"
        "/* KSU_FORK_SUSFS_WHITELIST_INJECTED: whitelist check for fork\n"
        " * SUSFS hide-bit assignment. Only hide when parent is NOT\n"
        " * KSU-authorized (ksu domain or allowlisted). */\n"
        "extern bool __ksu_is_allow_uid_for_current(uid_t uid);\n"
    )
    if "#include <linux/susfs_def.h>" in content:
        content = content.replace(
            "#include <linux/susfs_def.h>",
            ext_decl,
            1,
        )
        print("  OK: added extern __ksu_is_allow_uid_for_current")
    else:
        print("  WARNING: susfs_def.h include not found, adding extern near top")
        # fallback: add after the last #include block (approx)
        marker = "#include <linux/uaccess.h>\n"
        if marker in content:
            content = content.replace(
                marker,
                marker + ext_decl,
                1,
            )

    # 2. Replace the unconditional bit set with a whitelist check
    old_assign = (
        "\t#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
        "\t\tp->susfs_task_state |= TASK_STRUCT_NON_ROOT_USER_APP_PROC;\n"
        "\t#endif"
    )
    old_assign_alt = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
        "\tp->susfs_task_state |= TASK_STRUCT_NON_ROOT_USER_APP_PROC;\n"
        "#endif"
    )
    new_assign = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
        "\t/* KSU_FORK_SUSFS_WHITELIST_INJECTED: only set the SUSFS hide\n"
        "\t * bit when the parent is NOT KSU-authorized (ksu domain or\n"
        "\t * allowlisted). KSU root shells (ksud debug su) and the manager\n"
        "\t * app are therefore not hidden/killed by SUS_PATH hiding; all\n"
        "\t * other apps stay hidden (bank/Hunter detection preserved).\n"
        "\t * ksu_is_allow_uid_for_current() returns true for uid 0 only in\n"
        "\t * the ksu domain, so init->zygote is NOT whitelisted. */\n"
        "\tpr_info(\"KSU_FORK: uid=%d is_ksu_domain=%d\\n\",\n"
        "\t\tcurrent_uid().val, __ksu_is_allow_uid_for_current(current_uid().val));\n"
        "\tif (!__ksu_is_allow_uid_for_current(current_uid().val))\n"
        "\t\tp->susfs_task_state |= TASK_STRUCT_NON_ROOT_USER_APP_PROC;\n"
        "#endif"
    )

    if old_assign in content:
        content = content.replace(old_assign, new_assign, 1)
        print("  OK: replaced hide-bit assignment with whitelist check")
    elif old_assign_alt in content:
        content = content.replace(old_assign_alt, new_assign, 1)
        print("  OK: replaced hide-bit assignment (alt indent)")
    else:
        print(f"  ERROR: hide-bit assignment anchor not found in {filepath}")
        print("  --- context ---")
        for i, line in enumerate(content.split('\n')):
            if 'susfs_task_state' in line and 'NON_ROOT' in line:
                print(f"  line {i+1}: {line}")
        sys.exit(1)

    with open(filepath, "w") as f:
        f.write(content)

    print(f"  OK: KSU_FORK_SUSFS_WHITELIST injected into {filepath}")


if __name__ == "__main__":
    main()
