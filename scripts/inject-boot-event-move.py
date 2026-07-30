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

/* Delayed work — runs 35s after boot when fscrypt DE key is loaded.
 * Ensures modules/ exists, then moves any pending modules.
 * Uses rename workaround for f2fs stale inline dentry: mkdir a temp
 * name then mv to "modules" — rename uses a different code path
 * in f2fs that bypasses the stale dentry check.
 * Uses override_creds(ksu_cred) — kworker SELinux context lacks
 * permission to write to adb_data_file (verified: returns EACCES). */
static void susfs_cleanup_dwork_fn(struct work_struct *work)
{
	const struct cred *old;

	printk(KERN_INFO "susfs: delayed cleanup\n");

	call_usermodehelper("/system/bin/sh",
		(char *[]){"sh", "-c",
			   "mkdir /data/adb/.susfs_tmp 2>/dev/null; "
			   "mv /data/adb/.susfs_tmp /data/adb/modules 2>/dev/null; "
			   "mkdir -p /data/adb/modules_update 2>/dev/null || true",
			   NULL},
		NULL, UMH_WAIT_PROC);

	if (ksu_cred) {
		old = override_creds(ksu_cred);
		susfs_apply_module_updates();
		revert_creds(old);
	}
}

DECLARE_DELAYED_WORK(susfs_cleanup_dwork, susfs_cleanup_dwork_fn);

/* Called from anon_ksu_release() when current->fs is NULL.
 * Reschedules cleanup so it runs in kworker context.
 * The cleanup function uses override_creds(ksu_cred) for VFS access. */
void susfs_schedule_module_move(void)
{
	mod_delayed_work(system_wq, &susfs_cleanup_dwork, 1);
}

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
	 * Must run as init (no override_creds) — the ksu domain
	 * (u:r:ksu:s0) triggers SUSFS path hiding that makes
	 * kern_path("/data/adb/modules") return -ENOENT. */
	susfs_apply_module_updates();

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
	char old_path[256], new_path[256], upd_path[256];
	struct path old_p = {}, new_p = {}, modules_dir = {};
	struct dentry *new_dentry, *upd_dentry;
	struct inode *dir_inode;
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

	/* Do NOT skip if module.prop already exists — ksud Rust code
	 * pre-creates modules/<id>/module.prop and modules/<id>/update
	 * BEFORE the kernel move (module.rs lines 646-652). Skipping
	 * would leave the full module files stranded in modules_update/. */

	err = kern_path("/data/adb/modules", 0, &modules_dir);
	if (err) {
		printk(KERN_INFO "susfs: move_one '%s' modules/ err=%d, deferring\n", name, err);
		path_put(&old_p);
		return;
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
		/* Check if target has actual module files (not just ksud
		 * pre-created module.prop/update). If so, skip exchange —
		 * module is already active. The source after a previous
		 * exchange has only module.prop + update (stale remnant). */
		struct path _check;
		scnprintf(upd_path, sizeof(upd_path), "%s/bin", old_path);
		if (kern_path(upd_path, 0, &_check) != 0) {
			scnprintf(upd_path, sizeof(upd_path), "%s/lib", old_path);
			if (kern_path(upd_path, 0, &_check) != 0) {
				printk(KERN_INFO "susfs: move_one '%s' source stale, skipping\n", name);
				dput(new_dentry);
				path_put(&modules_dir);
				path_put(&new_p);
				path_put(&old_p);
				return;
			}
		}
		path_put(&_check);
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

	/* After successful rename, remove the ksud "update" marker file.
	 * ksud creates this file in the staging directory before closing
	 * the KSU fd. If the move happens asynchronously (deferred
	 * workqueue), ksud may have already exited and left the marker.
	 * The marker disables the App's module toggle (Module.kt:1209). */
	if (err == 0) {
		scnprintf(upd_path, sizeof(upd_path), "%s/update", new_path);
		if (kern_path(upd_path, 0, &new_p) == 0) {
			upd_dentry = new_p.dentry;
			dir_inode = d_inode(upd_dentry->d_parent);
			inode_lock_nested(dir_inode, I_MUTEX_PARENT);
			vfs_unlink(dir_inode, upd_dentry, NULL);
			inode_unlock(dir_inode);
			printk(KERN_INFO "susfs: move_one '%s' removed update marker\n", name);
			path_put(&new_p);
		}
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
