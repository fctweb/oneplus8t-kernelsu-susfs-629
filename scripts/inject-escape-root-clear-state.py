#!/usr/bin/env python3
"""
Inject SUSFS hide-bit clearing into escape_with_root_profile().

KSU's `escape_with_root_profile()` grants root (uid 0 + ksu domain) but
leaves current->susfs_task_state's NON_ROOT_USER_APP_PROC bit set (it was
set at fork()). As a result, the root shell spawned by `ksud debug su`
is still subject to SUSFS SUS_PATH / SUS_MAP hiding and gets SIGKILLed
when it touches hidden paths (e.g. /system/bin/su) — which breaks the
manager app's root shell / feature checks (settings page loses items).

Fix: after a successful escape_with_root_profile(), clear the SUSFS
hide bit so the KSU root shell is not hidden.

Usage: python3 inject-escape-root-clear-state.py <kernel-root>
"""

import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: inject-escape-root-clear-state.py <kernel-root>")
        sys.exit(1)

    kernel_dir = sys.argv[1]
    candidates = [
        os.path.join(kernel_dir, "drivers/kernelsu/policy/app_profile.c"),
        os.path.join(kernel_dir, "KernelSU/kernel/policy/app_profile.c"),
        os.path.join(kernel_dir, "kernel/policy/app_profile.c"),
    ]
    filepath = None
    for p in candidates:
        if os.path.exists(p):
            filepath = p
            break
    if not filepath:
        print(f"ERROR: app_profile.c not found under {kernel_dir}")
        sys.exit(1)

    with open(filepath) as f:
        content = f.read()

    if "KSU_ROOT_SHELL_CLEAR_STATE_INJECTED" in content:
        print("  Already injected, skipping")
        return

    # Anchor: the tail of escape_with_root_profile() right before return 0.
    # rifsxd KernelSU-Next legacy uses 4-space indent + `profile.namespaces`
    # (dot, not arrow) and has NO ksu_put_root_profile() call.
    anchors = [
        "    setup_mount_ns(profile.namespaces);\n\treturn 0;",
        "    setup_mount_ns(profile.namespaces);\n    return 0;",
        "\tsetup_mount_ns(profile->namespaces);\n\tksu_put_root_profile(profile);\n\treturn 0;",
        "\tsetup_mount_ns(profile->namespaces);\n\tksu_put_root_profile(profile);\n\treturn 0;",
    ]

    # The clear must go BEFORE `return 0;` on the success path. So we split the
    # anchor: keep the setup_mount_ns line, then inject, then the rest.
    block = (
        "\n\t/* KSU_ROOT_SHELL_CLEAR_STATE_INJECTED: clear the SUSFS path-\n"
        "\t * hiding bit so this KSU root shell is not hidden/killed by\n"
        "\t * SUS_PATH / SUS_MAP hiding (e.g. /system/bin/su). Without\n"
        "\t * this, `ksud debug su` spawns a root shell that gets SIGKILLed\n"
        "\t * when it touches hidden paths, breaking the manager app's root\n"
        "\t * shell / feature checks. */\n"
        "\t#ifdef CONFIG_KSU_SUSFS\n"
        "\tcurrent->susfs_task_state = 0;\n"
        "\t#endif\n"
    )

    injected = False
    for anchor in anchors:
        if anchor in content:
            # Split anchor into (setup_mount_ns line) + (return 0;)
            lines = anchor.split("\n")
            head = lines[0]  # setup_mount_ns(...);
            tail = "\n".join(lines[1:])  # return 0;
            content = content.replace(
                head + "\n" + tail,
                head + block + tail,
                1,
            )
            injected = True
            break

    if not injected:
        # Fallback: anchor only on setup_mount_ns line, inject after it
        import re
        m = re.search(r'^(\s*)setup_mount_ns\(profile(?:->|\.)namespaces\);', content, re.MULTILINE)
        if m:
            indent = m.group(1)
            block_indented = (
                "\n" + indent + "/* KSU_ROOT_SHELL_CLEAR_STATE_INJECTED: clear the SUSFS\n"
                + indent + " * path-hiding bit so this KSU root shell is not hidden. */\n"
                + indent + "#ifdef CONFIG_KSU_SUSFS\n"
                + indent + "current->susfs_task_state = 0;\n"
                + indent + "#endif"
            )
            content = content[:m.end()] + block_indented + content[m.end():]
            injected = True

    if not injected:
        print(f"  ERROR: anchor not found in {filepath}")
        sys.exit(1)

    with open(filepath, "w") as f:
        f.write(content)

    print(f"  OK: injected KSU_ROOT_SHELL_CLEAR_STATE into {filepath}")


if __name__ == "__main__":
    main()
