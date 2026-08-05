#!/usr/bin/env python3
"""Remove the synchronous module-move hook from anon_ksu_release().

The kernel-side `susfs_apply_module_updates()` in anon_ksu_release fires on
EVERY ksu fd close. During a module install the ksud process opens/closes the
fd multiple times, so the move runs 1..N times while installer.sh is still
writing staging. The second run hits RENAME_EXCHANGE against a half-written
staging dir and swaps the (complete) active module out, losing webroot/bin
etc. → module shows "Error getting state", Unknown, WebUI flash.

Fix: don't move from anon_ksu_release at all. Staging → active is done by
userspace ksud immediately after install (handle_updated_modules), where the
fscrypt key is loaded and std::fs::rename is atomic. The boot-time move in
boot_event.c susfs_restore_boot() stays (harmless when staging is empty).

Keeps the ksud_boot.h declaration so boot_event.c still compiles.

Usage: python3 inject-susfs-module-move.py <kernel-root>
"""

import sys, os, re

def main():
    if len(sys.argv) < 2:
        print("Usage: inject-susfs-module-move.py <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    sc_path = os.path.join(root, "drivers/kernelsu/supercall/supercall.c")
    kh_path = os.path.join(root, "drivers/kernelsu/runtime/ksud_boot.h")

    # 0. Keep the declarations in ksud_boot.h so boot_event.c still compiles.
    if os.path.exists(kh_path):
        with open(kh_path) as f:
            kh_content = f.read()
        if 'susfs_apply_module_updates' not in kh_content:
            kh_content += '\nvoid susfs_apply_module_updates(void);\n'
        if 'susfs_schedule_module_move' not in kh_content:
            kh_content += 'void susfs_schedule_module_move(void);\n'
        with open(kh_path, 'w') as f:
            f.write(kh_content)
        print(f"  Added declarations to {kh_path}")
    else:
        print(f"  WARNING: {kh_path} not found")

    if not os.path.exists(sc_path):
        print(f"ERROR: {sc_path} not found")
        sys.exit(1)

    with open(sc_path) as f:
        content = f.read()

    # 1. If the injected block is present, strip it so anon_ksu_release is clean.
    #    Matches the injected variant (both the plain synchronous one and the
    #    ksu_cred/current->fs dual-path one).
    stripped = False
    # variant A: single susfs_apply_module_updates() call
    pat_a = re.compile(
        r'(\tpr_(?:info|debug)\("ksu fd released\\n"\);\n)'
        r'#ifdef CONFIG_KSU_SUSFS.*?#endif\n'
        r'\treturn 0;\n\}',
        re.DOTALL,
    )
    if pat_a.search(content):
        content = pat_a.sub(
            r'\1\treturn 0;\n}', content,
        )
        stripped = True

    # variant B: dual-path ksu_cred block
    pat_b = re.compile(
        r'(\tpr_(?:info|debug)\("ksu fd released\\n"\);\n)'
        r'#ifdef CONFIG_KSU_SUSFS.*?}\n#endif\n'
        r'\treturn 0;\n\}',
        re.DOTALL,
    )
    if pat_b.search(content):
        content = pat_b.sub(
            r'\1\treturn 0;\n}', content,
        )
        stripped = True

    # 2. Sanity: ensure no susfs_apply_module_updates call remains in anon_ksu_release
    release_section = content.split('static long anon_ksu_ioctl', 1)[0]
    if 'susfs_apply_module_updates' in release_section:
        print(f"  WARNING: susfs_apply_module_updates still present in anon_ksu_release")
    else:
        print(f"  anon_ksu_release: clean (no fd-close module move)")

    with open(sc_path, 'w') as f:
        f.write(content)

    print(f"  {sc_path}: removed module-move from anon_ksu_release (staging→active now done by userspace ksud)")

if __name__ == '__main__':
    main()
