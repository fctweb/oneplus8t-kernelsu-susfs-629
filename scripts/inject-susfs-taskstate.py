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
        '    /* SUSFS: exempt KSU-authorized processes from path hiding.\n'
        '     * Clear the hide bit ONLY for the manager app or uid 0 (root\n'
        '     * shells / ksud commands), so that arbitrary apps which obtain\n'
        '     * the ksu fd via the public prctl/reboot magic (no uid check in\n'
        '     * the kprobe handler) cannot clear their own hide bit and then\n'
        '     * detect hidden root paths (e.g. /system/bin/su) -> bank/\n'
        '     * Hunter/Momo detection. */\n'
        '#ifdef CONFIG_KSU_SUSFS\n'
        '    if (is_manager() || current_uid().val == 0)\n'
        '        current->susfs_task_state = 0;\n'
        '#endif\n'
        '    return ksu_supercall_handle_ioctl(cmd, (void __user *)arg);'
    )

    if old not in content:
        print(f"  WARNING: pattern not found in {path}")
        print(f"  Looked for: {repr(old)}")
        sys.exit(0)

    # Ensure the identifiers used by the gated clear are declared.
    if '#include <linux/cred.h>' not in content:  # current_uid()
        content = content.replace(
            '#include <linux/anon_inodes.h>',
            '#include <linux/anon_inodes.h>\n#include <linux/cred.h>',
            1,
        )
    if '#include "manager/manager_identity.h"' not in content:  # is_manager()
        # Anchor after an existing KSU include if present, else after cred.h
        if '#include "arch.h"' in content:
            content = content.replace(
                '#include "arch.h"',
                '#include "arch.h"\n#include "manager/manager_identity.h"',
                1,
            )
        else:
            content = content.replace(
                '#include <linux/cred.h>',
                '#include <linux/cred.h>\n#include "manager/manager_identity.h"',
                1,
            )

    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  {path}: gated susfs_task_state clear injected")

if __name__ == '__main__':
    main()
