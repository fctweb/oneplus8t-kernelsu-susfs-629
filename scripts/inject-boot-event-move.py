#!/usr/bin/env python3
"""Inject ALL SUSFS boot restore + module move code into boot_event.c.
Complete replacement for fix_boot_event_properties.patch's boot_event.c hunks.

Adds:
  1. #include <uapi/linux/fs.h>
  2. susfs_restore_boot() call inside on_post_fs_data()
  3. Complete code block: susfs_restore_boot(), susfs_is_boot_restored(),
     susfs_mark_inode_sus_map(), susfs_rename_one(), susfs_rename_actor(),
     susfs_apply_module_updates()

Usage: python3 inject-boot-event-move.py <kernel-root>
"""

import sys, os

SUSFS_CODE_BLOCK = r"""
#ifdef CONFIG_KSU_SUSFS
#include <uapi/linux/fs.h>
extern void susfs_apply_module_updates(void);
#endif

#ifdef CONFIG_KSU_SUSFS
static bool susfs_boot_restored __read_mostly = false;

static void susfs_restore_boot(void)
{
	int i;

	{
		static const char * const paths[] = {
			"/system/bin/su",
			"/odm/bin/su",
			"/data/adb/ksu/su",
			"/system/addon.d",
			"/system/build.prop",
			"/data/adb/modules",
			"/data/adb/ksu-pdeath",
			"/data/adb/ksu/.allowlist",
			"/data/adb/ksu/.feature_config",
			NULL,
		};
		for (i = 0; paths[i]; i++)
			susfs_add_sus_path_kernel(paths[i]);
	}
	{
		static const char * const maps[] = { "/data/adb/", NULL };
		for (i = 0; maps[i]; i++) susfs_mark_inode_sus_map(maps[i]);
	}
	{
		static const char * const mounts[] = { "/vendor", "/odm", NULL };
		for (i = 0; mounts[i]; i++) susfs_add_sus_mount_kernel(mounts[i]);
	}

	susfs_set_uname_kernel("4.19.304", "Default/4.19");

#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
	susfs_set_log(false);
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
	WRITE_ONCE(susfs_hide_sus_mnts_for_all_procs, true);
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING
	WRITE_ONCE(susfs_is_avc_log_spoofing_enabled, true);
#endif

	susfs_restore_properties();

	/* Move any modules left in staging (modules_update/) to active (modules/).
	 * Replaces handle_updated_modules() which never runs because
	 * init.rc exec injection is broken on this ROM (LineageOS 13). */
	susfs_apply_module_updates();

	susfs_boot_restored = true;
	pr_info("susfs: boot restore complete\n");
}

int susfs_is_boot_restored(void)
{
	return susfs_boot_restored ? 1 : 0;
}

static int susfs_mark_inode_sus_map(const char *path)
{
	struct path p;
	struct inode *inode;
	int err;

	err = kern_path(path, 0, &p);
	if (err) return err;
	inode = d_inode(p.dentry);
	spin_lock(&inode->i_lock);
	inode->i_state |= INODE_STATE_SUS_MAP;
	spin_unlock(&inode->i_lock);
	path_put(&p);
	return 0;
}

/* Move module from staging to active:
 *   rename(modules_update/<name>/, modules/<name>/)
 * If the target exists, use RENAME_EXCHANGE to atomically swap. */
static int susfs_rename_one(const char *name, int namlen)
{
	char old_path[256], new_path[256];
	struct path old_p = {}, new_p = {}, modules_dir = {};
	struct dentry *new_dentry;
	int err;

	scnprintf(old_path, sizeof(old_path), "/data/adb/modules_update/%s", name);
	scnprintf(new_path, sizeof(new_path), "/data/adb/modules/%s", name);

	err = kern_path(old_path, 0, &old_p);
	if (err)
		return 0; /* source disappeared, skip */

	if (kern_path("/data/adb/modules", 0, &modules_dir)) {
		path_put(&old_p);
		return 0;
	}

	new_dentry = lookup_one_len(name, modules_dir.dentry, namlen);
	if (IS_ERR(new_dentry)) {
		path_put(&modules_dir);
		path_put(&old_p);
		return 0;
	}

	err = kern_path(new_path, 0, &new_p);
	if (!err) {
		err = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
				 new_p.dentry->d_parent->d_inode, new_p.dentry,
				 NULL, RENAME_EXCHANGE);
		path_put(&new_p);
	} else {
		err = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
				 modules_dir.dentry->d_inode, new_dentry,
				 NULL, 0);
	}

	dput(new_dentry);
	path_put(&modules_dir);
	path_put(&old_p);
	return 0;
}

struct susfs_rename_ctx {
	struct dir_context ctx;
};

static int susfs_rename_actor(struct dir_context *ctx, const char *name,
			      int namlen, loff_t offset, u64 ino,
			      unsigned int d_type)
{
	if (name[0] == '.')
		return 0;
	susfs_rename_one(name, namlen);
	return 0;
}

void susfs_apply_module_updates(void)
{
	struct file *dir;
	struct susfs_rename_ctx rctx = {
		.ctx.actor = susfs_rename_actor,
	};

	dir = filp_open("/data/adb/modules_update/", O_RDONLY | O_DIRECTORY, 0);
	if (IS_ERR(dir)) {
		pr_debug("susfs: modules_update not found (no staging)\n");
		return;
	}

	pr_debug("susfs: applying module updates...\n");
	iterate_dir(dir, &rctx.ctx);
	filp_close(dir, NULL);
	pr_debug("susfs: module updates done\n");
}
#endif /* CONFIG_KSU_SUSFS */
"""

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

    # 2. Find on_post_fs_data() and inject susfs_restore_boot() call
    #    Pattern: after ksu_stop_input_hook_runtime(); and before }
    stop_hook = 'ksu_stop_input_hook_runtime();'
    pos = content.find(stop_hook)
    if pos > 0:
        insert_pos = pos + len(stop_hook)
        call_block = (
            '\n#ifdef CONFIG_KSU_SUSFS\n'
            '\tsusfs_restore_boot();\n'
            '#endif')
        content = content[:insert_pos] + call_block + content[insert_pos:]
        print("  Inserted susfs_restore_boot() call in on_post_fs_data()")
    else:
        print("  WARNING: ksu_stop_input_hook_runtime(); not found")

    # 3. Find the SUSFS include block #endif and insert all code after it
    #    The block looks like:
    #      #ifdef CONFIG_KSU_SUSFS
    #      #include <linux/susfs.h>
    #      extern void susfs_restore_properties(void);
    #      #endif
    #    We find this #endif and insert our code block after it.
    #    But we need the LAST #endif in the include area, not the end-of-file one.
    #    Strategy: find "#endif" after "susfs_restore_properties" and before "bool ksu_module_mounted"
    marker_end = content.find('bool ksu_module_mounted')
    susfs_restore_props = content.find('susfs_restore_properties(void);')

    if susfs_restore_props > 0 and marker_end > susfs_restore_props:
        # Find the #endif that closes this block
        block_end = content.find('#endif', susfs_restore_props, marker_end)
        if block_end > 0:
            # The #endif is at block_end, extend to include the newline
            eol = content.find('\n', block_end)
            if eol > block_end:
                insert_after = eol + 1
            else:
                insert_after = block_end + len('#endif')
            content = content[:insert_after] + '\n' + SUSFS_CODE_BLOCK + content[insert_after:]
            print("  Injected complete SUSFS code block after include #endif")
        else:
            print("  WARNING: #endif after susfs_restore_properties not found")
    else:
        print("  WARNING: SUSFS include block markers not found")

    with open(path, 'w') as f:
        f.write(content)

    print("  === Verification ===")
    for keyword in ['susfs_apply_module_updates', 'susfs_is_boot_restored',
                    'susfs_restore_boot', 'susfs_rename_one']:
        count = content.count(keyword)
        print(f"  {keyword}: {count}")

if __name__ == '__main__':
    main()
