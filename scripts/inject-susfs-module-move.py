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

    # 2. Add includes + workqueue declarations after sulog/event.h
    old_include = '#include "sulog/event.h"'
    work_decl = '\n#include <linux/workqueue.h>\n#include "runtime/ksud_boot.h"\n'
    work_decl += '\n#ifdef CONFIG_KSU_SUSFS\n'
    work_decl += '/* Deferred staging→active move — runs in workqueue thread */\n'
    work_decl += 'static void susfs_move_workfn(struct work_struct *work)\n{\n'
    work_decl += '\tsusfs_apply_module_updates();\n}\n'
    work_decl += 'static DECLARE_WORK(susfs_move_work, susfs_move_workfn);\n'
    work_decl += '#endif\n'
    new_include = old_include + work_decl
    content = content.replace(old_include, new_include, 1)

    # 3. Replace anon_ksu_release() — use schedule_work instead of direct call.
    #    VFS ops can sleep, but anon_ksu_release() is called from __close_fd()
    #    which holds file_lock spinlock, making sleeping illegal.
    old_release = '''static int anon_ksu_release(struct inode *inode, struct file *filp)
{
\tpr_info("ksu fd released\\n");
\treturn 0;
}'''

    new_release = '''static int anon_ksu_release(struct inode *inode, struct file *filp)
{
\tpr_info("ksu fd released\\n");
#ifdef CONFIG_KSU_SUSFS
\tschedule_work(&susfs_move_work);
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
