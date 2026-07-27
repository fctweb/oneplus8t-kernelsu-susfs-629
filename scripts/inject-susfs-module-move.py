#!/usr/bin/env python3
"""Inject susfs_apply_module_updates() into supercall.c + ksud_boot.h

Called from CI after inject-susfs-taskstate.py.

Adds:
  1. Declaration of susfs_apply_module_updates() in ksud_boot.h
  2. #include "runtime/ksud_boot.h" after sulog/event.h in supercall.c
  3. susfs_apply_module_updates() call inside anon_ksu_release()

Usage: python3 inject-susfs-module-move.py <kernel-root>
"""

import sys, os

def main():
    if len(sys.argv) < 2:
        print("Usage: inject-susfs-module-move.py <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    sc_path = os.path.join(root, "drivers/kernelsu/supercall/supercall.c")
    kh_path = os.path.join(root, "drivers/kernelsu/runtime/ksud_boot.h")

    # 0. Add declaration to ksud_boot.h first so supercall.c can find it
    if os.path.exists(kh_path):
        with open(kh_path) as f:
            kh_content = f.read()
        if 'susfs_apply_module_updates' not in kh_content:
            kh_content += '\nvoid susfs_apply_module_updates(void);\n'
            with open(kh_path, 'w') as f:
                f.write(kh_content)
            print(f"  Added declaration to {kh_path}")
        else:
            print(f"  ksud_boot.h already has declaration")
    else:
        print(f"  WARNING: {kh_path} not found")

    # 1. Modify supercall.c
    if not os.path.exists(sc_path):
        print(f"ERROR: {sc_path} not found")
        sys.exit(1)

    with open(sc_path) as f:
        content = f.read()

    if 'susfs_apply_module_updates' in content:
        print("  supercall.c already injected, skipping")
        return

    # 2. Add #include "runtime/ksud_boot.h" after sulog/event.h
    old_include = '#include "sulog/event.h"'
    new_include = old_include + '\n#include "runtime/ksud_boot.h"'
    content = content.replace(old_include, new_include, 1)

    # 3. Add susfs_apply_module_updates() call inside anon_ksu_release()
    old_release = '''static int anon_ksu_release(struct inode *inode, struct file *filp)
{
\tpr_info("ksu fd released\\n");
\treturn 0;
}'''

    new_release = '''static int anon_ksu_release(struct inode *inode, struct file *filp)
{
\tpr_info("ksu fd released\\n");
#ifdef CONFIG_KSU_SUSFS
\t/* Module install just completed (libksud.so closing its KSU fd).
\t * Move any staging modules to active immediately. */
\tsusfs_apply_module_updates();
#endif
\treturn 0;
}'''

    content = content.replace(old_release, new_release, 1)

    with open(sc_path, 'w') as f:
        f.write(content)

    # Verification
    lines_added = sum(1 for l in content.split('\n') if 'susfs_apply_module_updates' in l)
    include_added = 'ksud_boot.h' in content
    print(f"  Injected: susfs_apply_module_updates (count={lines_added}), include={include_added}")

if __name__ == '__main__':
    main()
