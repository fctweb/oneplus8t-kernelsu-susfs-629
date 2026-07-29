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

/* Try to remove stale f2fs inline-dentry for 'modules' ONLY when the
 * path truly does not resolve.  If /data/adb/modules/ already exists
 * (e.g. just created by susfs_move_one), the entry is valid — do not
 * delete it or we will orphan the directory. */
static void susfs_cleanup_stale_modules(void)
{
	void *(*fe_fn)(struct inode *, const struct qstr *, struct page **);
	void *(*de_fn)(void *, struct page *, struct inode *, struct inode *);
	int (*sync_fn)(void *, struct writeback_control *, int, int);
	struct path _cp, _mp;
	struct qstr qn = QSTR_INIT("modules", 7);
	struct page *pg = NULL;
	void *de;
	struct writeback_control wbc;

	/* If modules/ resolves, entry is valid — skip */
	if (kern_path("/data/adb/modules", 0, &_mp) == 0) {
		path_put(&_mp);
		return;
	}

	fe_fn = (void *)kallsyms_lookup_name("f2fs_find_entry");
	de_fn = (void *)kallsyms_lookup_name("f2fs_delete_entry");
	sync_fn = (void *)kallsyms_lookup_name("f2fs_sync_node_pages");
	if (!fe_fn || !de_fn || !sync_fn) {
		printk(KERN_INFO "susfs: cleanup unavailable\n");
		return;
	}
	if (kern_path("/data/adb", 0, &_cp))
		return;

	de = fe_fn(d_inode(_cp.dentry), &qn, &pg);
	if (de && pg && !IS_ERR(pg)) {
		unsigned long ino = *(const __le32 *)((const u8 *)de + 4);
		printk(KERN_INFO "susfs: found stale entry ino=%lu\n",
		       le32_to_cpu(ino));
		de_fn(de, pg, d_inode(_cp.dentry), NULL);
		printk(KERN_INFO "susfs: cleaned stale entry\n");
		shrink_dcache_parent(d_inode(_cp.dentry)->i_sb->s_root);
		memset(&wbc, 0, sizeof(wbc));
		wbc.sync_mode = WB_SYNC_ALL;
		wbc.nr_to_write = LONG_MAX;
		sync_fn(d_inode(_cp.dentry)->i_sb->s_fs_info, &wbc, 0, 0);
		printk(KERN_INFO "susfs: flushed node pages\n");
	} else if (pg && !IS_ERR(pg)) {
		put_page(pg);
	}
	path_put(&_cp);
}

/* Delayed work — runs 35s after boot when fscrypt DE key is loaded.
 * Deletes stale entry, then moves any pending modules from staging
 * to active. susfs_move_one will create /data/adb/modules/ if needed. */
static void susfs_cleanup_dwork_fn(struct work_struct *work)
{
	const struct cred *old;

	printk(KERN_INFO "susfs: delayed cleanup\n");
	susfs_cleanup_stale_modules();

	if (ksu_cred) {
		old = override_creds(ksu_cred);
		susfs_apply_module_updates();
		revert_creds(old);
	}
}

static DECLARE_DELAYED_WORK(susfs_cleanup_dwork, susfs_cleanup_dwork_fn);

static void susfs_restore_boot(void)
{
	int i;

	/* Schedule stale-entry cleanup at 35s (when fscrypt key loaded).
	 * Must be done async — f2fs_find_entry needs the key to resolve
	 * encrypted filenames in inline dentries. */
	schedule_delayed_work(&susfs_cleanup_dwork,
			      msecs_to_jiffies(35000));

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

	/* Move any modules left in staging to active.
	 * Override creds to KSU domain (permissive) so VFS operations
	 * succeed from PID 1 context (init SELinux context may lack
	 * access to adb_data_file on some kernels). */
	if (ksu_cred) {
		const struct cred *old = override_creds(ksu_cred);
		susfs_apply_module_updates();
		revert_creds(old);
	}

	susfs_boot_restored = true;
	printk(KERN_INFO "susfs: boot restore complete\n");
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
#define SUSFS_MAX_STAGING 16
#define SUSFS_NAME_MAX 128

struct susfs_collect_ctx {
	struct dir_context ctx;
	char (*names)[SUSFS_NAME_MAX];
	int capacity;
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
	if (d_type != DT_DIR && d_type != DT_UNKNOWN)
		return 0;
	if (c->count >= c->capacity)
		return 0;
	printk(KERN_INFO "susfs: collect found '%s' (d_type=%u)\n", name, d_type);
	memcpy(c->names[c->count], name, min((size_t)namlen, sizeof(c->names[0]) - 1));
	c->names[c->count][min((size_t)namlen, sizeof(c->names[0]) - 1)] = '\0';
	c->count++;
	return 0;
}

/* ── Move module from staging to active ──────────────────────── */
static void susfs_move_one(const char *name)
{
	char old_path[256], new_path[256], prop_path[256];
	struct path old_p = {}, new_p = {}, modules_dir = {};
	struct dentry *new_dentry, *target_parent;
	int err, namlen = strlen(name);

	printk(KERN_INFO "susfs: move_one '%s' begin\n", name);

	scnprintf(old_path, sizeof(old_path), "/data/adb/modules_update/%s", name);
	scnprintf(new_path, sizeof(new_path), "/data/adb/modules/%s", name);

	err = kern_path(old_path, 0, &old_p);
	if (err) {
		printk(KERN_INFO "susfs: move_one '%s' source not found err=%d\n", name, err);
		return;
	}
	printk(KERN_INFO "susfs: move_one '%s' source found\n", name);

	/* Check if module already active — skip if module.prop exists */
	scnprintf(prop_path, sizeof(prop_path), "/data/adb/modules/%s/module.prop", name);
	if (kern_path(prop_path, 0, &new_p) == 0) {
		printk(KERN_INFO "susfs: move_one '%s' already active, skipping\n", name);
		path_put(&new_p);
		path_put(&old_p);
		return;
	}

	/* Ensure /data/adb/modules/ exists (create if needed) */
	err = kern_path("/data/adb/modules", 0, &modules_dir);
	if (err) {
		printk(KERN_INFO "susfs: move_one '%s' creating modules/ dir\n", name);
		err = kern_path("/data/adb", 0, &new_p);
		if (err) {
			printk(KERN_INFO "susfs: move_one '%s' /data/adb/ err=%d\n", name, err);
			path_put(&old_p);
			return;
		}
		target_parent = lookup_one_len("modules", new_p.dentry, 7);
		if (IS_ERR(target_parent)) {
			printk(KERN_INFO "susfs: move_one '%s' lookup modules err=%ld\n", name, PTR_ERR(target_parent));
			path_put(&new_p);
			path_put(&old_p);
			return;
		}
		if (!d_really_is_positive(target_parent)) {
			err = vfs_mkdir(d_inode(new_p.dentry), target_parent, 0755);
			printk(KERN_INFO "susfs: move_one '%s' vfs_mkdir modules err=%d\n", name, err);
		}
		dput(target_parent);
		path_put(&new_p);
		/* Retry kern_path after mkdir */
		err = kern_path("/data/adb/modules", 0, &modules_dir);
		if (err) {
			printk(KERN_INFO "susfs: move_one '%s' modules/ still err=%d\n", name, err);
			path_put(&old_p);
			return;
		}
	}

	new_dentry = lookup_one_len(name, modules_dir.dentry, namlen);
	if (IS_ERR(new_dentry)) {
		printk(KERN_INFO "susfs: move_one '%s' lookup target dentry failed\n", name);
		path_put(&modules_dir);
		path_put(&old_p);
		return;
	}
	printk(KERN_INFO "susfs: move_one '%s' found target dentry\n", name);

	err = kern_path(new_path, 0, &new_p);
	if (!err) {
		printk(KERN_INFO "susfs: move_one '%s' target exists, RENAME_EXCHANGE\n", name);
		err = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
			   new_p.dentry->d_parent->d_inode, new_p.dentry,
			   NULL, RENAME_EXCHANGE);
		printk(KERN_INFO "susfs: move_one '%s' exchange done err=%d\n", name, err);
		path_put(&new_p);
	} else {
		printk(KERN_INFO "susfs: move_one '%s' target not exists err=%d, simple rename\n", name, err);
		err = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
			   modules_dir.dentry->d_inode, new_dentry,
			   NULL, 0);
		printk(KERN_INFO "susfs: move_one '%s' rename done err=%d\n", name, err);
	}

	dput(new_dentry);
	path_put(&modules_dir);
	path_put(&old_p);
	printk(KERN_INFO "susfs: move_one '%s' finish\n", name);
}

void susfs_apply_module_updates(void)
{
	struct file *dir;
	char (*names)[SUSFS_NAME_MAX];
	struct susfs_collect_ctx cctx = {
		.ctx.actor = susfs_collect_actor,
		.names = NULL,
		.capacity = SUSFS_MAX_STAGING,
		.count = 0,
	};
	int i;

	dir = filp_open("/data/adb/modules_update/", O_RDONLY | O_DIRECTORY, 0);
	if (IS_ERR(dir)) {
		printk(KERN_INFO "susfs: stage0 no staging dir\n");
		return;
	}
	printk(KERN_INFO "susfs: stage1 collecting module IDs\n");

	names = kmalloc(SUSFS_MAX_STAGING * SUSFS_NAME_MAX, GFP_ATOMIC);
	if (!names) {
		printk(KERN_INFO "susfs: stage1 kmalloc OOM\n");
		filp_close(dir, NULL);
		return;
	}
	cctx.names = names;
	printk(KERN_INFO "susfs: stage2 iterate_dir\n");

	iterate_dir(dir, &cctx.ctx);
	filp_close(dir, NULL);

	if (cctx.count == 0) {
		printk(KERN_INFO "susfs: stage2 nothing to move\n");
		kfree(names);
		return;
	}

	printk(KERN_INFO "susfs: stage3 moving %d module(s)\n", cctx.count);
	for (i = 0; i < cctx.count; i++)
		susfs_move_one(cctx.names[i]);
	kfree(names);
	printk(KERN_INFO "susfs: stage4 done\n");
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
        '#include <linux/slab.h>\n'
        '#include <linux/workqueue.h>\n'
        '#include <linux/cred.h>\n'
        '#include <linux/namei.h>\n'
        '#include \"ksu.h\"\n'
        'extern unsigned long kallsyms_lookup_name(const char *name);\n'
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
               'susfs_restore_boot', 'susfs_move_one', 'susfs_collect_actor',
               'susfs_ensure_modules']:
        print(f"  {kw}: {content.count(kw)}")

if __name__ == '__main__':
    main()
