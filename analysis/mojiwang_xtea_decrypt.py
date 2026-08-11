import re
M = 0xFFFFFFFF

def bytes_to_ints(data):
    n = (len(data) + 3) // 4
    arr = [0] * n
    for i, b in enumerate(data):
        arr[i >> 2] |= (b & 0xFF) << ((i & 3) << 3)
    return arr

def decrypt(data_int, key, rounds):
    n = len(data_int)
    if n < 2: return data_int
    delta = 0x9E3779B9
    v3 = (rounds * delta) & M
    v2 = data_int[0]
    for _ in range(rounds):
        v5 = (v3 >> 2) & 3
        for i in range(n - 1, 0, -1):
            v = data_int[i - 1]; w = data_int[i]
            v8 = ((v >> 5) ^ ((v2 << 2) & M)) & M
            v9 = ((v2 >> 3) ^ ((v << 4) & M)) & M
            v8 = (v8 + v9) & M
            vv = (v2 ^ v3) & M
            keyidx = (i & 3) ^ v5
            vv = (vv + (v ^ key[keyidx])) & M
            vv = (vv ^ v8) & M
            data_int[i] = (w - vv) & M
            v2 = data_int[i]
        v = data_int[n - 1]; w = data_int[0]
        v8 = ((v >> 5) ^ ((v2 << 2) & M)) & M
        v9 = ((v2 >> 3) ^ ((v << 4) & M)) & M
        v8 = (v8 + v9) & M
        vv = (v2 ^ v3) & M
        keyidx = v5
        vv = (vv + (v ^ key[keyidx])) & M
        vv = (vv ^ v8) & M
        data_int[0] = (w - vv) & M
        v2 = data_int[0]
        v3 = (v3 - delta) & M
    return data_int

key_str = "yztcCodeKey9022"
keyb = key_str.encode('utf-8')
key = [int.from_bytes(keyb[i*4:(i+1)*4], 'little') for i in range(4)]

def dec(hexstr):
    data = bytes.fromhex(hexstr)
    di = bytes_to_ints(data)
    n = len(di)
    rounds = (0x34 // n) + 6
    out = decrypt(di, key, rounds)
    raw = b''.join(v.to_bytes(4, 'little') for v in out)
    return raw.rstrip(b'\x00').decode('utf-8', errors='replace')

# 所有密文(去重)
cipher = set()
for line in open('/tmp/cipertexts.txt'):
    c = line.strip()
    if c: cipher.add(c)

for c in sorted(cipher):
    try:
        txt = dec(c)
        # 过滤可读
        if txt and sum(1 for ch in txt if 32 <= ord(ch) < 127 or 0x4e00 <= ord(ch) <= 0x9fff) >= max(3, len(txt)//2):
            print(f"{c[:16]}... = {txt!r}")
        else:
            print(f"{c[:16]}... = (不可读) {txt!r}")
    except Exception as e:
        print(f"{c[:16]}... = ERROR {e}")
