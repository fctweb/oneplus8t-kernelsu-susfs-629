#!/usr/bin/env python3
"""Inject susfs_task_state clearing into anon_ksu_ioctl in supercall.c.
Called from CI after inject-ksu-prctl.py.

The upstream KernelSU-Next@legacy branch uses 4-space indentation.
The pattern to match is:
    return ksu_supercall_handle_ioctl(cmd, (void __user *)arg);

Usage: python3 inject-susfs-taskstate.py <kernel-root>
"""

import sys, os

def main():
    if len(sys.argv) < 2:
        print("Usage: inject-susfs-taskstate.py <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    path = os.path.join(root, "drivers/kernelsu/supercall/supercall.c")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found")
        sys.exit(1)

    with open(path) as f:
        content = f.read()

    if 'susfs_task_state = 0' in content:
        print("  already has susfs_task_state clear, skipping")
        return

    # Upstream uses 4-space indentation (NOT tabs)
    old = '    return ksu_supercall_handle_ioctl(cmd, (void __user *)arg);'
    new = (
        '    /* SUSFS: exempt root processes from path hiding so root shells\n'
        '     * and ksud commands (all uid 0) can see hidden paths. Gated on\n'
        '     * uid 0 ONLY: is_manager() is unusable here because this kernel\n'
        '     * build reports the MANAGER flag for every uid (auto-crown),\n'
        '     * and arbitrary apps can obtain the ksu fd via the public\n'
        '     * prctl/reboot magic (no uid check). Gating on uid 0 means a\n'
        '     * non-root app cannot clear its own hide bit and detect hidden\n'
        '     * root paths (e.g. /system/bin/su) -> bank/Hunter/Momo. The\n'
        '     * manager app never needs the clear: all its /data/adb and\n'
        '     * /system/bin/su access goes through the root shell (uid 0). */\n'
        '#ifdef CONFIG_KSU_SUSFS\n'
        '    if (current_uid().val == 0)\n'
        '        current->susfs_task_state = 0;\n'
        '#endif\n'
        '    return ksu_supercall_handle_ioctl(cmd, (void __user *)arg);'
    )

    if old not in content:
        print(f"  WARNING: pattern not found in {path}")
        print(f"  Looked for: {repr(old)}")
        sys.exit(0)

    # Ensure current_uid() is declared.
    if '#include <linux/cred.h>' not in content:
        content = content.replace(
            '#include <linux/anon_inodes.h>',
            '#include <linux/anon_inodes.h>\n#include <linux/cred.h>',
            1,
        )

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: uid-0-gated susfs_task_state clear injected")

if __name__ == '__main__':
    main()
