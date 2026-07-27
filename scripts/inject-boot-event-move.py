#!/usr/bin/env python3
"""Inject ALL SUSFS boot restore + module move code into boot_event.c.
Replaces the old fix_boot_event_properties.patch approach.

Adds into on_post_fs_data():
  - susfs_restore_boot() call

Appends at file end:
  - susfs_restore_boot() full impl with paths/mounts/maps/props
  - susfs_is_boot_restored()
  - susfs_collect_actor(), susfs_move_one(), susfs_apply_module_updates()

Usage: python3 inject-boot-event-move.py <kernel-root>
"""

import sys, os

SUSFS_BLOCK = r"""

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

/* ── collector: collect module IDs from modules_update/ ────────── */
struct susfs_collect_ctx {
	struct dir_context ctx;
	char names[16][256];
	int count;
};

static int susfs_collect_actor(struct dir_context *ctx, const char *name,
			       int namlen, loff_t offset, u64 ino,
			       unsigned int d_type)
{
	struct susfs_collect_ctx *c =
		container_of(ctx, struct susfs_collect_ctx, ctx);

	if (name[0] == '.')
		return 0;
	/* Skip non-directories (files). F2FS may report DT_UNKNOWN,
	 * but rename_one will still skip them later via kern_path. */
	if (d_type != DT_DIR && d_type != DT_UNKNOWN)
		return 0;
	if (c->count >= 16)
		return 0; /* safety limit */
	memcpy(c->names[c->count], name, namlen);
	c->names[c->count][namlen] = '\0';
	c->count++;
	return 0;
}

/* ── Move module from staging to active ──────────────────────── */
static void susfs_move_one(const char *name)
{
	char old_path[256], new_path[256];
	struct path old_p = {}, new_p = {}, modules_dir = {};
	struct dentry *new_dentry;
	int err, namlen = strlen(name);

	scnprintf(old_path, sizeof(old_path), "/data/adb/modules_update/%s", name);
	scnprintf(new_path, sizeof(new_path), "/data/adb/modules/%s", name);

	err = kern_path(old_path, 0, &old_p);
	if (err) return; /* source disappeared */

	/* Ensure /data/adb/modules/ exists (create if first module install) */
	if (kern_path("/data/adb/modules", 0, &modules_dir)) {
		struct path adb_dir;
		if (!kern_path("/data/adb", 0, &adb_dir)) {
			new_dentry = lookup_one_len("modules", adb_dir.dentry, 7);
			if (!IS_ERR(new_dentry)) {
				vfs_mkdir(adb_dir.dentry->d_inode, new_dentry, 0755);
				dput(new_dentry);
			}
			path_put(&adb_dir);
		}
		/* Retry after creating it */
		if (kern_path("/data/adb/modules", 0, &modules_dir)) {
			path_put(&old_p);
			return;
		}
	}

	new_dentry = lookup_one_len(name, modules_dir.dentry, namlen);
	if (IS_ERR(new_dentry)) {
		path_put(&modules_dir);
		path_put(&old_p);
		return;
	}

	err = kern_path(new_path, 0, &new_p);
	if (!err) {
		/* Target exists → RENAME_EXCHANGE to swap atomically */
		vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
			   new_p.dentry->d_parent->d_inode, new_p.dentry,
			   NULL, RENAME_EXCHANGE);
		path_put(&new_p);
	} else {
		/* Target doesn't exist → simple rename */
		vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
			   modules_dir.dentry->d_inode, new_dentry,
			   NULL, 0);
	}

	dput(new_dentry);
	path_put(&modules_dir);
	path_put(&old_p);
}

void susfs_apply_module_updates(void)
{
	struct file *dir;
	struct susfs_collect_ctx cctx = {
		.ctx.actor = susfs_collect_actor,
		.count = 0,
	};
	int i;

	dir = filp_open("/data/adb/modules_update/", O_RDONLY | O_DIRECTORY, 0);
	if (IS_ERR(dir)) {
		pr_debug("susfs: modules_update not found (no staging)\n");
		return;
	}
	pr_debug("susfs: collecting module IDs from staging...\n");
	iterate_dir(dir, &cctx.ctx);
	filp_close(dir, NULL); /* close BEFORE moving to avoid stale dentries */

	if (cctx.count == 0)
		return;

	pr_debug("susfs: moving %d module(s) to active...\n", cctx.count);
	for (i = 0; i < cctx.count; i++)
		susfs_move_one(cctx.names[i]);
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

    lines = content.split('\n')

    # 1. Add SUSFS includes after #include <linux/printk.h>
    include_marker = '#include <linux/printk.h>'
    susfs_includes = (
        '#ifdef CONFIG_KSU_SUSFS\n'
        '#include <linux/susfs.h>\n'
        '#include <uapi/linux/fs.h>\n'
        'extern void susfs_restore_properties(void);\n'
        'static void susfs_restore_boot(void);\n'
        'static int susfs_mark_inode_sus_map(const char *path);\n'
        'extern void susfs_apply_module_updates(void);\n'
        '#endif')
    for i, line in enumerate(lines):
        if line.strip() == include_marker:
            # Insert after this line
            insert = i + 1
            for extra_line in reversed(susfs_includes.split('\n')):
                lines.insert(insert, extra_line)
            print(f"  Added SUSFS includes after {include_marker}")
            break
    else:
        print(f"  WARNING: {include_marker} not found")

    # 2. Add susfs_restore_boot() call after the stop_input_hook() CALL
    #    inside on_post_fs_data() (not the extern declaration at file level).
    for i, line in enumerate(lines):
        # Match the call (indented with tab) not the extern declaration
        if line.strip().startswith('stop_input_hook();') and not line.strip().startswith('extern'):
            insert = i + 1
            call_block = [
                '#ifdef CONFIG_KSU_SUSFS',
                '\tsusfs_restore_boot();',
                '#endif']
            for extra_line in reversed(call_block):
                lines.insert(insert, extra_line)
            print("  Added susfs_restore_boot() call after stop_input_hook()")
            break
    else:
        print("  WARNING: stop_input_hook(); not found")

    # 3. Append SUSFS code block at end of file
    lines.append('')
    for line in SUSFS_BLOCK.split('\n'):
        lines.append(line)
    print("  Appended SUSFS functions block at end of file")

    content = '\n'.join(lines)

    with open(path, 'w') as f:
        f.write(content)

    print("  === Verification ===")
    for kw in ['susfs_apply_module_updates', 'susfs_is_boot_restored',
               'susfs_restore_boot', 'susfs_move_one', 'susfs_collect_actor']:
        print(f"  {kw}: {content.count(kw)}")

if __name__ == '__main__':
    main()
