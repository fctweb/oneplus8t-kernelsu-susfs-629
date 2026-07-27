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

/* Bypass broken f2fs_lookup by allocating dentry directly and calling
 * vfs_mkdir.  On f2fs, a stale inline-dentry entry (orphaned inode)
 * causes f2fs_lookup → f2fs_iget to return -ENOENT, blocking mkdir.
 * d_alloc_name + vfs_mkdir avoids calling f2fs_lookup entirely.
 * If f2fs_mkdir's internal add_link detects the stale entry we also
 * try f2fs_find_entry + f2fs_delete_entry to clean it up first. */
static void susfs_ensure_dir(const char *parent_path, const char *name)
{
	struct path parent_p;
	struct dentry *d;
	struct inode *p_inode;
	int err;

	if (kern_path(parent_path, 0, &parent_p)) {
		pr_info("susfs: ensure_dir kern_path fail %s\n", parent_path);
		return;
	}
	p_inode = d_inode(parent_p.dentry);
	if (!p_inode) {
		pr_info("susfs: ensure_dir no inode %s\n", parent_path);
		path_put(&parent_p);
		return;
	}

	d = d_alloc_name(parent_p.dentry, name);
	if (!d) {
		pr_info("susfs: ensure_dir d_alloc fail %s/%s\n",
			parent_path, name);
		path_put(&parent_p);
		return;
	}

	inode_lock_nested(p_inode, I_MUTEX_PARENT);
	err = vfs_mkdir(p_inode, d, 0755);
	inode_unlock(p_inode);
	pr_info("susfs: ensure_dir vfs_mkdir '%s/%s' err=%d\n",
		parent_path, name, err);

	if (err == -EEXIST) {
		/* Stale entry exists — try to remove it via f2fs internals */
		void *(*fe_fn)(struct inode *, const struct qstr *,
			       struct page **);
		void (*de_fn)(void *, struct page *, struct inode *,
			      struct inode *);
		struct inode *(*iget_fn)(struct super_block *, unsigned long);
		struct qstr qn = QSTR_INIT(name, strlen(name));
		struct page *pg = NULL;
		void *de;

		fe_fn = (void *)kallsyms_lookup_name("f2fs_find_entry");
		de_fn = (void *)kallsyms_lookup_name("f2fs_delete_entry");
		iget_fn = (void *)kallsyms_lookup_name("f2fs_iget");

		if (fe_fn && de_fn && iget_fn) {
			de = fe_fn(p_inode, &qn, &pg);
			pr_info("susfs: ensure_dir stale de=%p pg=%p\n", de, pg);

			if (de && pg && !IS_ERR(pg)) {
				unsigned long ino = *(const __le32 *)
					((const u8 *)de + 4);
				struct inode *test = iget_fn(
					p_inode->i_sb, le32_to_cpu(ino));
				pr_info("susfs: ensure_dir stale ino=%lu "
					"test=%p\n", le32_to_cpu(ino), test);
				if (IS_ERR(test)) {
					pr_info("susfs: removing stale entry "
						"'%s' (ino=%lu err=%ld)\n",
						name, le32_to_cpu(ino),
						PTR_ERR(test));
					de_fn(de, pg, p_inode, NULL);
					/* Retry mkdir after cleanup */
					dput(d);
					d = d_alloc_name(parent_p.dentry,
							 name);
					if (d) {
						inode_lock_nested(p_inode,
							I_MUTEX_PARENT);
						err = vfs_mkdir(p_inode, d,
								 0755);
						inode_unlock(p_inode);
						pr_info("susfs: ensure_dir "
							"retry err=%d\n", err);
					}
				} else {
					iput(test);
					put_page(pg);
				}
			} else if (pg && !IS_ERR(pg)) {
				put_page(pg);
			}
		}
	}
	dput(d);
	path_put(&parent_p);
}

static void susfs_restore_boot(void)
{
	int i;

	/* Ensure /data/adb/modules/ and /data/adb/modules_update/ exist.
	 * We use d_alloc_name + vfs_mkdir to bypass a broken f2fs_lookup
	 * caused by stale inline-dentry entries (orphaned inodes). */
	susfs_ensure_dir("/data/adb", "modules");
	susfs_ensure_dir("/data/adb", "modules_update");

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
	pr_info("susfs: collect found '%s' (d_type=%u)\n", name, d_type);
	memcpy(c->names[c->count], name, min((size_t)namlen, sizeof(c->names[0]) - 1));
	c->names[c->count][min((size_t)namlen, sizeof(c->names[0]) - 1)] = '\0';
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

	pr_info("susfs: move_one '%s' begin\n", name);

	scnprintf(old_path, sizeof(old_path), "/data/adb/modules_update/%s", name);
	scnprintf(new_path, sizeof(new_path), "/data/adb/modules/%s", name);

	err = kern_path(old_path, 0, &old_p);
	if (err) {
		pr_info("susfs: move_one '%s' source not found err=%d\n", name, err);
		return;
	}
	pr_info("susfs: move_one '%s' source found\n", name);

	/* Skip if /data/adb/modules/ doesn't exist — will be created on next
	 * module install by install_module_to_system().  vfs_mkdir from PID 1
	 * context is unreliable due to dentry cache and locking semantics. */
	if (kern_path("/data/adb/modules", 0, &modules_dir)) {
		pr_info("susfs: move_one '%s' modules/ missing, deferring\n", name);
		path_put(&old_p);
		return;
	}

	new_dentry = lookup_one_len(name, modules_dir.dentry, namlen);
	if (IS_ERR(new_dentry)) {
		pr_info("susfs: move_one '%s' lookup target dentry failed\n", name);
		path_put(&modules_dir);
		path_put(&old_p);
		return;
	}
	pr_info("susfs: move_one '%s' found target dentry\n", name);

	err = kern_path(new_path, 0, &new_p);
	if (!err) {
		pr_info("susfs: move_one '%s' target exists, RENAME_EXCHANGE\n", name);
		err = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
			   new_p.dentry->d_parent->d_inode, new_p.dentry,
			   NULL, RENAME_EXCHANGE);
		pr_info("susfs: move_one '%s' exchange done err=%d\n", name, err);
		path_put(&new_p);
	} else {
		pr_info("susfs: move_one '%s' target not exists, simple rename\n", name);
		err = vfs_rename(old_p.dentry->d_parent->d_inode, old_p.dentry,
			   modules_dir.dentry->d_inode, new_dentry,
			   NULL, 0);
		pr_info("susfs: move_one '%s' rename done err=%d\n", name, err);
	}

	dput(new_dentry);
	path_put(&modules_dir);
	path_put(&old_p);
	pr_info("susfs: move_one '%s' finish\n", name);
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
		pr_info("susfs: stage0 no staging dir\n");
		return;
	}
	pr_info("susfs: stage1 collecting module IDs\n");

	names = kmalloc(SUSFS_MAX_STAGING * SUSFS_NAME_MAX, GFP_ATOMIC);
	if (!names) {
		pr_info("susfs: stage1 kmalloc OOM\n");
		filp_close(dir, NULL);
		return;
	}
	cctx.names = names;
	pr_info("susfs: stage2 iterate_dir\n");

	iterate_dir(dir, &cctx.ctx);
	filp_close(dir, NULL);

	if (cctx.count == 0) {
		pr_info("susfs: stage2 nothing to move\n");
		kfree(names);
		return;
	}

	pr_info("susfs: stage3 moving %d module(s)\n", cctx.count);
	for (i = 0; i < cctx.count; i++)
		susfs_move_one(cctx.names[i]);
	kfree(names);
	pr_info("susfs: stage4 done\n");
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
               'susfs_ensure_dir', 'susfs_fixup_stale_f2fs_entry']:
        print(f"  {kw}: {content.count(kw)}")

if __name__ == '__main__':
    main()
