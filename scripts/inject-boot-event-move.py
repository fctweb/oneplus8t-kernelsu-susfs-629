#!/usr/bin/env python3
"""Inject susfs_apply_module_updates() + rename helpers into boot_event.c

Called from CI after fix_boot_event_properties.patch is applied (or as
replacement).  Adds:

  1. #include <uapi/linux/fs.h> (after #include <linux/printk.h>)
  2. extern declaration of susfs_apply_module_updates (after #endif)
  3. Call to susfs_apply_module_updates() inside susfs_restore_boot()
  4. New functions susfs_rename_one, susfs_rename_actor,
     susfs_apply_module_updates (replaces or appends)

Usage: python3 inject-boot-event-move.py <kernel-root>
"""

import sys, os

def main():
    if len(sys.argv) < 2:
        print("Usage: inject-boot-event-move.py <kernel-root>")
        sys.exit(1)

    root = sys.argv[1]
    path = os.path.join(root, "drivers/kernelsu/runtime/boot_event.c")

    if not os.path.exists(path):
        print(f"ERROR: {path} not found")
        sys.exit(1)

    with open(path) as f:
        content = f.read()

    if 'susfs_apply_module_updates' in content:
        print("  already injected, skipping")
        return

    # 1. Add #include <uapi/linux/fs.h> after #include <linux/printk.h>
    content = content.replace(
        '#include <linux/printk.h>',
        '#include <linux/printk.h>\n#include <uapi/linux/fs.h>', 1)

    # 2. Find susfs_restore_boot() and add the call before susfs_boot_restored
    restore_func_end = content.find('susfs_boot_restored = true;')
    if restore_func_end > 0:
        indent = '\t'  # tab indent
        to_insert = (indent + '/* Move any modules left in staging to active.\n'
                     + indent + ' * Replaces handle_updated_modules() which never runs\n'
                     + indent + ' * because init.rc exec injection is broken on this ROM. */\n'
                     + indent + 'susfs_apply_module_updates();\n')
        content = content[:restore_func_end] + to_insert + content[restore_func_end:]
        print("  Inserted susfs_apply_module_updates() call in susfs_restore_boot()")
    else:
        print("  WARNING: susfs_boot_restored = true; not found, skipping call injection")

    # 3. Find #endif /* CONFIG_KSU_SUSFS */ at the end and append new functions
    endif_pos = content.rfind('#endif /* CONFIG_KSU_SUSFS */')
    if endif_pos < 0:
        endif_pos = content.rfind('#endif  /* CONFIG_KSU_SUSFS */')

    new_funcs = '''
/* Move module from staging to active:
 *   rename(modules_update/<name>/, modules/<name>/)
 * If the target exists, use RENAME_EXCHANGE to atomically swap. */
static int susfs_rename_one(const char *name, int namlen)
{
\tchar old_path[256], new_path[256];
\tstruct path old_p = {}, new_p = {}, modules_dir = {};
\tstruct dentry *new_dentry;
\tint err;

\tscnprintf(old_path, sizeof(old_path), "/data/adb/modules_update/%s", name);
\tscnprintf(new_path, sizeof(new_path), "/data/adb/modules/%s", name);

\terr = kern_path(old_path, 0, &old_p);
\tif (err)
\t\treturn 0; /* source disappeared, skip */

\tif (kern_path("/data/adb/modules", 0, &modules_dir)) {
\t\tpath_put(&old_p);
\t\treturn 0;
\t}

\tnew_dentry = lookup_one_len(name, modules_dir.dentry, namlen);
\tif (IS_ERR(new_dentry)) {
\t\tpath_put(&modules_dir);
\t\tpath_put(&old_p);
\t\treturn 0;
\t}

\t/* Check if target exists */
\terr = kern_path(new_path, 0, &new_p);
\tif (!err) {
\t\terr = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
\t\t\t\t new_p.dentry->d_parent->d_inode, new_p.dentry,
\t\t\t\t NULL, RENAME_EXCHANGE);
\t\tpath_put(&new_p);
\t} else {
\t\terr = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
\t\t\t\t modules_dir.dentry->d_inode, new_dentry,
\t\t\t\t NULL, 0);
\t}

\tdput(new_dentry);
\tpath_put(&modules_dir);
\tpath_put(&old_p);
\treturn 0;
}

struct susfs_rename_ctx {
\tstruct dir_context ctx;
};

static int susfs_rename_actor(struct dir_context *ctx, const char *name,
\t\t\t      int namlen, loff_t offset, u64 ino,
\t\t\t      unsigned int d_type)
{
\tif (name[0] == '.')
\t\treturn 0;
\tsusfs_rename_one(name, namlen);
\treturn 0;
}

void susfs_apply_module_updates(void)
{
\tstruct file *dir;
\tstruct susfs_rename_ctx rctx = {
\t\t.ctx.actor = susfs_rename_actor,
\t};

\tdir = filp_open("/data/adb/modules_update/", O_RDONLY | O_DIRECTORY, 0);
\tif (IS_ERR(dir)) {
\t\tpr_debug("susfs: modules_update not found (no staging)\\n");
\t\treturn;
\t}

\tpr_debug("susfs: applying module updates...\\n");
\titerate_dir(dir, &rctx.ctx);
\tfilp_close(dir, NULL);
\tpr_debug("susfs: module updates done\\n");
}
'''

    if endif_pos > 0:
        content = content[:endif_pos] + new_funcs + content[endif_pos:]
        print("  Appended new functions before #endif /* CONFIG_KSU_SUSFS */")
    else:
        print("  WARNING: #endif /* CONFIG_KSU_SUSFS */ not found, appending at end")
        # Find #endif at the end for the include guard
        last_endif = content.rfind('#endif')
        if last_endif > 0:
            content = content[:last_endif] + new_funcs + content[last_endif:]

    with open(path, 'w') as f:
        f.write(content)

    print("  Injection complete")
    lines = sum(1 for l in content.split('\\n') if 'susfs_apply_module_updates' in l)
    print(f"  susfs_apply_module_updates references: {lines}")

if __name__ == '__main__':
    main()
