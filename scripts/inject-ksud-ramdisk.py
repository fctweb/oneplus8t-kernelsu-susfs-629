#!/usr/bin/env python3
"""Inject ksud binary (+ optional ReZygisk early monitor) into boot.img ramdisk.
Usage: python3 inject-ksud-ramdisk.py <ksud_binary> <stock_boot.img> <output_ramdisk.lz4> [monitor_binary]
"""
import struct, os, subprocess, shutil, sys

def main():
    if len(sys.argv) < 4:
        print("Usage: inject-ksud-ramdisk.py <ksud_binary> <stock_boot.img> <output_ramdisk.lz4> [monitor_binary]")
        sys.exit(1)

    ksud_bin = sys.argv[1]
    boot_img = sys.argv[2]
    output = sys.argv[3]
    monitor_bin = sys.argv[4] if len(sys.argv) > 4 else None

    if not os.path.exists(ksud_bin):
        print(f"ERROR: ksud binary not found at {ksud_bin}")
        sys.exit(1)

    # Parse boot.img header
    with open(boot_img, 'rb') as f:
        hdr = f.read(4096)
    kernel_size = struct.unpack('<I', hdr[8:12])[0]
    ramdisk_size = struct.unpack('<I', hdr[16:20])[0]
    page_size = struct.unpack('<I', hdr[36:40])[0]
    kernel_end = page_size + kernel_size
    ramdisk_start = ((kernel_end + page_size - 1) // page_size) * page_size

    print(f"Kernel size: {kernel_size}")
    print(f"Ramdisk size: {ramdisk_size} at offset {ramdisk_start}")

    # Read ramdisk
    f = open(boot_img, 'rb')
    f.seek(ramdisk_start)
    rd = f.read(ramdisk_size)
    f.close()

    # Save compressed ramdisk
    ramdisk_lz4 = '/tmp/ramdisk-orig.lz4'
    with open(ramdisk_lz4, 'wb') as rf:
        rf.write(rd)

    # Decompress
    ramdisk_raw = '/tmp/ramdisk-orig.raw'
    subprocess.run(['lz4', '-d', ramdisk_lz4, ramdisk_raw], check=True)
    print(f"Decompressed: {os.path.getsize(ramdisk_raw)} bytes")

    # Extract cpio
    extract_dir = '/tmp/ramdisk-extract'
    if os.path.exists(extract_dir):
        subprocess.run(['rm', '-rf', extract_dir])
    os.makedirs(extract_dir)
    os.chdir(extract_dir)
    subprocess.run(['cpio', '-idm', '-F', ramdisk_raw], check=True)
    orig_count = len(os.listdir(extract_dir))
    print(f"Extracted {orig_count} entries")

    # Copy ksud to ramdisk root (NOT /sbin/ — conflicts with Android symlink)
    shutil.copy2(ksud_bin, 'ksud')
    os.chmod('ksud', 0o755)

    # B2: optional ReZygisk early monitor (libzygisk_ptrace.so). Started by the
    # kernel-injected `on init` rc section as `/rezygisk-monitor monitor`.
    if monitor_bin:
        if not os.path.exists(monitor_bin):
            print(f"ERROR: monitor binary not found at {monitor_bin}")
            sys.exit(1)
        shutil.copy2(monitor_bin, 'rezygisk-monitor')
        os.chmod('rezygisk-monitor', 0o755)
        print(f"Added rezygisk-monitor ({os.path.getsize('rezygisk-monitor')} bytes) at ramdisk root")
    print(f"Added ksud ({os.path.getsize('ksud')} bytes) at ramdisk root")

    # No su symlink needed — su is handled by overlay /odm/bin/su

    # Repack cpio
    ramdisk_new_cpio = '/tmp/ramdisk-new.cpio'
    subprocess.run(['sh', '-c', f'find . | cpio -o -H newc > {ramdisk_new_cpio}'], check=True)
    print(f"Repacked cpio: {os.path.getsize(ramdisk_new_cpio)} bytes")

    # Re-compress with lz4 LEGACY format (0x184C2102 magic) — the bootloader
    # and kernel's init/ramdisk decompressor expect the legacy framing, NOT
    # the standard lz4 frame (0x184D2204). Using `lz4 -f` (frame) here made
    # repacked boot images fail to boot (observed: fastboot boot black screen).
    subprocess.run(['lz4', '-f', '-l', ramdisk_new_cpio, output], check=True)
    new_size = os.path.getsize(output)
    with open(output, 'rb') as f:
        magic = f.read(4)
    print(f"Output ramdisk: {new_size} bytes ({new_size/1024/1024:.1f} MB), lz4 magic={magic.hex()} (expect 02214c18)")

if __name__ == '__main__':
    main()
