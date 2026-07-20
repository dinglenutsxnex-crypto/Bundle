"""
sync_bundles.py
===============
Fetches the latest Shadow Fight Arena config archive, decrypts it, reads
bundlesConfig to get all asset bundle paths, then downloads every .bin bundle
from the CDN and commits them directly to GitHub via the Git Data API.

No local git repo operations — files live only in memory (or /tmp briefly),
so runner disk space is never an issue.

Required env vars (injected by the workflow):
    GITHUB_TOKEN   – repo write token
    GITHUB_REPO    – owner/repo  (default: dinglenutsxnex-crypto/Bundle)
    GITHUB_BRANCH  – branch to commit to (default: main)

Optional:
    SFA_PLATFORM   – Android (default) | iOS | StandaloneWindows
    BATCH_SIZE     – files per commit  (default: 250)
    WORKERS        – parallel download+upload threads (default: 16)
    FORCE_SYNC     – "true" to re-upload even if version unchanged
"""

import base64
import json
import os
import random
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ────────────────────────────────────────────────────────────────────

BALANCE_URL = (
    "https://sfalb.nekki.com/balance"
    "?w=PROD-AS&fv=1.9.80.20.26181-prod&rand={rand}&p=Android&client_version=1.9.81"
)
AES_KEY = bytes.fromhex("08050674cc9ab867197f0cad55a770ca")
AES_IV  = bytes.fromhex("653e0715236e0f734f1ebf64228b322d")

CDN_MIRRORS  = ["https://sfacdn.nekki.com", "https://sc22o7jgey.a.trbcdn.net"]
GITHUB_API   = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "dinglenutsxnex-crypto/Bundle")
GITHUB_BRANCH= os.environ.get("GITHUB_BRANCH", "main")
PLATFORM     = os.environ.get("SFA_PLATFORM", "Android")
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE", "250"))
WORKERS      = int(os.environ.get("WORKERS", "16"))
FORCE_SYNC   = os.environ.get("FORCE_SYNC", "false").lower() == "true"
UA_GAME      = "UnityPlayer/2022.3"


# ── Pure-Python AES-128-CBC ───────────────────────────────────────────────────

def _build_aes_tables():
    S = [
        0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
        0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
        0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
        0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
        0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
        0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
        0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
        0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
        0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
        0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
        0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
        0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
        0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
        0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
        0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
        0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
    ]
    SI = [0] * 256
    for i, v in enumerate(S): SI[v] = i
    def gmul(a, b):
        p = 0
        for _ in range(8):
            if b & 1: p ^= a
            hi = a & 0x80; a = (a << 1) & 0xff
            if hi: a ^= 0x1b
            b >>= 1
        return p
    m9  = [gmul(i,  9) for i in range(256)]
    m11 = [gmul(i, 11) for i in range(256)]
    m13 = [gmul(i, 13) for i in range(256)]
    m14 = [gmul(i, 14) for i in range(256)]
    rcon = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]
    return S, SI, m9, m11, m13, m14, rcon

_S, _SI, _M9, _M11, _M13, _M14, _RCON = _build_aes_tables()

def _sub_word(w):
    return (_S[w>>24]<<24)|(_S[(w>>16)&0xff]<<16)|(_S[(w>>8)&0xff]<<8)|_S[w&0xff]
def _rot_word(w):
    return ((w<<8)|(w>>24))&0xffffffff
def _key_expand(key):
    w = [int.from_bytes(key[i:i+4], 'big') for i in range(0, 16, 4)]
    for i in range(4, 44):
        t = w[i-1]
        if i % 4 == 0: t = _sub_word(_rot_word(t)) ^ (_RCON[i//4-1] << 24)
        w.append(w[i-4] ^ t)
    return [[w[r*4], w[r*4+1], w[r*4+2], w[r*4+3]] for r in range(11)]
def _aes128_decrypt_block(blk, rk):
    s = [[blk[r+4*c] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4): s[r][c] ^= (rk[10][c] >> (24-r*8)) & 0xff
    for rnd in range(9, 0, -1):
        s[1][0],s[1][1],s[1][2],s[1][3] = s[1][3],s[1][0],s[1][1],s[1][2]
        s[2][0],s[2][1],s[2][2],s[2][3] = s[2][2],s[2][3],s[2][0],s[2][1]
        s[3][0],s[3][1],s[3][2],s[3][3] = s[3][1],s[3][2],s[3][3],s[3][0]
        for r in range(4):
            for c in range(4): s[r][c] = _SI[s[r][c]]
        for c in range(4):
            for r in range(4): s[r][c] ^= (rk[rnd][c] >> (24-r*8)) & 0xff
        for c in range(4):
            a,b,d,e = s[0][c],s[1][c],s[2][c],s[3][c]
            s[0][c] = _M14[a]^_M11[b]^_M13[d]^_M9[e]
            s[1][c] = _M9[a] ^_M14[b]^_M11[d]^_M13[e]
            s[2][c] = _M13[a]^_M9[b] ^_M14[d]^_M11[e]
            s[3][c] = _M11[a]^_M13[b]^_M9[d] ^_M14[e]
    s[1][0],s[1][1],s[1][2],s[1][3] = s[1][3],s[1][0],s[1][1],s[1][2]
    s[2][0],s[2][1],s[2][2],s[2][3] = s[2][2],s[2][3],s[2][0],s[2][1]
    s[3][0],s[3][1],s[3][2],s[3][3] = s[3][1],s[3][2],s[3][3],s[3][0]
    for r in range(4):
        for c in range(4): s[r][c] = _SI[s[r][c]]
    for c in range(4):
        for r in range(4): s[r][c] ^= (rk[0][c] >> (24-r*8)) & 0xff
    return bytes(s[r][c] for c in range(4) for r in range(4))

def aes128_cbc_decrypt(data, key, iv):
    rk = _key_expand(key); out = bytearray(); prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i+16]
        out += bytes(a^b for a,b in zip(_aes128_decrypt_block(blk, rk), prev))
        prev = blk
    pad = out[-1]
    return bytes(out[:-pad]) if 1 <= pad <= 16 else bytes(out)


# ── Minimal ZIP reader ────────────────────────────────────────────────────────

def _zip_entries(buf):
    eocd = -1
    for i in range(len(buf) - 22, max(-1, len(buf) - 22 - 65535), -1):
        if buf[i:i+4] == b'PK\x05\x06': eocd = i; break
    if eocd < 0: raise ValueError("No EOCD in ZIP")
    cd_off = struct.unpack_from('<I', buf, eocd+16)[0]
    num    = struct.unpack_from('<H', buf, eocd+10)[0]
    entries = []; pos = cd_off
    for _ in range(num):
        if buf[pos:pos+4] != b'PK\x01\x02': break
        comp   = struct.unpack_from('<H', buf, pos+10)[0]
        csz    = struct.unpack_from('<I', buf, pos+20)[0]
        fn_len = struct.unpack_from('<H', buf, pos+28)[0]
        ex_len = struct.unpack_from('<H', buf, pos+30)[0]
        cm_len = struct.unpack_from('<H', buf, pos+32)[0]
        lh_off = struct.unpack_from('<I', buf, pos+42)[0]
        name   = buf[pos+46:pos+46+fn_len].decode(errors='replace')
        entries.append((name, comp, csz, lh_off))
        pos += 46 + fn_len + ex_len + cm_len
    return entries

def _extract_entry(buf, entry):
    name, comp, csz, lh_off = entry
    fn_len = struct.unpack_from('<H', buf, lh_off+26)[0]
    ex_len = struct.unpack_from('<H', buf, lh_off+28)[0]
    raw = buf[lh_off+30+fn_len+ex_len : lh_off+30+fn_len+ex_len+csz]
    return raw if comp == 0 else zlib.decompress(raw, -15)


# ── Protobuf bundle-name parser ───────────────────────────────────────────────

def _read_varint(buf, pos):
    r = 0; s = 0
    while True:
        b = buf[pos]; pos += 1; r |= (b & 0x7f) << s
        if not (b & 0x80): break
        s += 7
    return r, pos

def _parse_proto(buf, start, end):
    fields = []; pos = start
    while pos < end:
        tag, pos = _read_varint(buf, pos)
        fn = tag >> 3; wt = tag & 7
        if wt == 0:
            v, pos = _read_varint(buf, pos); fields.append((fn, 0, v))
        elif wt == 2:
            l, pos = _read_varint(buf, pos); v = buf[pos:pos+l]
            fields.append((fn, 2, v)); pos += l
        elif wt == 5:
            fields.append((fn, 5, struct.unpack_from('<I', buf, pos)[0])); pos += 4
        elif wt == 1:
            fields.append((fn, 1, struct.unpack_from('<Q', buf, pos)[0])); pos += 8
        else:
            break
    return fields

def parse_bundle_config(cfg_bytes):
    archives = set()
    for _, wt, gdata in _parse_proto(cfg_bytes, 0, len(cfg_bytes)):
        if wt != 2: continue
        for gf in _parse_proto(gdata, 0, len(gdata)):
            if gf[0] != 2 or gf[1] != 2: continue
            for sf in _parse_proto(gf[2], 0, len(gf[2])):
                if sf[0] == 3 and sf[1] == 2:
                    name = sf[2].decode('utf-8', errors='replace').strip()
                    if name: archives.add(name)
    return archives


# ── GitHub API ────────────────────────────────────────────────────────────────

def _gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }

def _gh_get(path):
    req = urllib.request.Request(f"{GITHUB_API}{path}", headers=_gh_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def _gh_post(path, payload, method="POST"):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{GITHUB_API}{path}", data=data, method=method, headers=_gh_headers()
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

def gh_get_branch_sha():
    return _gh_get(f"/repos/{GITHUB_REPO}/git/ref/heads/{GITHUB_BRANCH}")["object"]["sha"]

def gh_get_commit_tree(commit_sha):
    return _gh_get(f"/repos/{GITHUB_REPO}/git/commits/{commit_sha}")["tree"]["sha"]

def gh_get_existing_files(version):
    """Return set of filenames already in bundles/{version}/ (empty if path doesn't exist)."""
    try:
        tree = _gh_get(f"/repos/{GITHUB_REPO}/contents/bundles/{version}")
        return {entry["name"] for entry in tree}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise

def gh_upload_blob(content_bytes):
    """Upload raw bytes as a git blob. Returns the blob SHA."""
    result = _gh_post(f"/repos/{GITHUB_REPO}/git/blobs", {
        "content": base64.b64encode(content_bytes).decode(),
        "encoding": "base64",
    })
    return result["sha"]

def gh_create_tree(base_tree_sha, entries):
    """
    entries: list of {"path": str, "mode": "100644", "type": "blob", "sha": str}
    Returns new tree SHA.
    """
    result = _gh_post(f"/repos/{GITHUB_REPO}/git/trees", {
        "base_tree": base_tree_sha,
        "tree": entries,
    })
    return result["sha"]

def gh_create_commit(tree_sha, parent_sha, message):
    result = _gh_post(f"/repos/{GITHUB_REPO}/git/commits", {
        "message": message,
        "tree": tree_sha,
        "parents": [parent_sha],
    })
    return result["sha"]

def gh_update_ref(commit_sha):
    _gh_post(
        f"/repos/{GITHUB_REPO}/git/refs/heads/{GITHUB_BRANCH}",
        {"sha": commit_sha},
        method="PATCH",
    )


# ── CDN download ──────────────────────────────────────────────────────────────

def _get_bytes(url, timeout=60, retries=3):
    last_err = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA_GAME})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"Download failed for {url}: {last_err}")

def download_and_upload_blob(args):
    """Worker: download one bundle from CDN, upload blob to GitHub. Returns (path, blob_sha)."""
    archive_name, cdn_base, repo_path = args
    url  = cdn_base + archive_name + ".bin"
    # Try mirrors in order
    data = None
    for mirror in CDN_MIRRORS:
        try:
            data = _get_bytes(url.replace(CDN_MIRRORS[0], mirror, 1))
            break
        except Exception:
            continue
    if data is None:
        raise RuntimeError(f"All mirrors failed for {archive_name}")

    blob_sha = gh_upload_blob(data)
    return repo_path, blob_sha


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not GITHUB_TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN env var is not set")

    # 1. Balance → version
    rand = random.randint(10000, 99999)
    print(f"[1] Fetching balance…")
    balance  = json.loads(_get_bytes(BALANCE_URL.format(rand=rand), timeout=15))
    version  = balance["version"]["cur"]
    zip_url  = balance["version"]["url"]
    mirrors  = balance.get("mirrors", [])
    if mirrors:
        CDN_MIRRORS[:] = mirrors + [m for m in CDN_MIRRORS if m not in mirrors]
    print(f"    Version : {version}")
    print(f"    ZIP URL : {zip_url}")

    # 2. Check if already synced
    print(f"[2] Checking existing state…")
    head_sha  = gh_get_branch_sha()
    tree_sha  = gh_get_commit_tree(head_sha)
    print(f"    HEAD    : {head_sha[:12]}")

    if not FORCE_SYNC:
        existing_files = gh_get_existing_files(version)
        if existing_files:
            print(f"    {len(existing_files)} files already in bundles/{version}/ — checking completeness…")
        # We'll skip individual files that already exist (handled per-file below)
    else:
        existing_files = set()
        print("    FORCE_SYNC=true — re-uploading everything")

    # 3. Download + decrypt config archive
    print(f"[3] Downloading config archive…")
    outer_zip = _get_bytes(zip_url, timeout=120)
    print(f"    {len(outer_zip):,} bytes")

    entries   = _zip_entries(outer_zip)
    enc_entry = next((e for e in entries if e[0].endswith('.enc')), None)
    if not enc_entry:
        sys.exit("ERROR: no .enc file in config archive")

    print(f"[4] Decrypting {enc_entry[0]}…")
    enc_data  = _extract_entry(outer_zip, enc_entry)
    inner_zip = aes128_cbc_decrypt(enc_data, AES_KEY, AES_IV)
    if inner_zip[:4] != b'PK\x03\x04':
        sys.exit("ERROR: decryption failed — wrong AES key?")
    print(f"    Decrypted to {len(inner_zip):,} bytes")
    del outer_zip, enc_data  # free memory

    # 4. Parse bundlesConfig
    print(f"[5] Parsing bundlesConfig…")
    inner_entries = _zip_entries(inner_zip)
    cfg_entry = next(
        (e for e in inner_entries
         if re.search(rf'bundlesConfig_\d+_{re.escape(PLATFORM)}\.bytes', e[0])), None
    )
    if not cfg_entry:
        available = [e[0] for e in inner_entries if 'bundlesConfig' in e[0]]
        sys.exit(f"ERROR: no bundlesConfig for '{PLATFORM}'. Available: {available}")

    m = re.search(r'bundlesConfig_(\d+)_', cfg_entry[0])
    bundle_set = m.group(1) if m else "6"
    cdn_base   = f"{CDN_MIRRORS[0]}/Bundles/ArenaBundles{bundle_set}/{PLATFORM}/archives/"
    print(f"    Config  : {cfg_entry[0]}  (set={bundle_set})")
    print(f"    CDN base: {cdn_base}")

    cfg_bytes = _extract_entry(inner_zip, cfg_entry)
    del inner_zip
    archives  = sorted(parse_bundle_config(cfg_bytes))
    print(f"    Archives: {len(archives)} unique names")

    # 5. Filter out already-present files
    to_upload = [
        a for a in archives
        if f"{a}.bin" not in existing_files
    ]
    skipped = len(archives) - len(to_upload)
    print(f"    Skipping: {skipped} already in repo  |  Uploading: {len(to_upload)}")

    if not to_upload:
        print("Nothing to do.")
        return

    # 6. Download + upload blobs in parallel, commit in batches
    print(f"[6] Uploading blobs ({WORKERS} workers, {BATCH_SIZE} per commit)…")
    current_head = head_sha
    current_tree = tree_sha

    work = [
        (name, cdn_base, f"bundles/{version}/{name}.bin")
        for name in to_upload
    ]

    total     = len(work)
    done      = 0
    failed    = 0
    batch_num = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        # Submit all jobs; collect results and flush to GitHub in BATCH_SIZE chunks
        pending_entries = []   # (repo_path, blob_sha) ready for current batch
        futures = {pool.submit(download_and_upload_blob, item): item[0] for item in work}

        for fut in as_completed(futures):
            name = futures[fut]
            try:
                repo_path, blob_sha = fut.result()
                pending_entries.append({
                    "path": repo_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha":  blob_sha,
                })
            except Exception as e:
                failed += 1
                print(f"  FAIL {name}: {e}", file=sys.stderr)

            done += 1

            # Flush a batch when it's full OR we've processed everything
            if len(pending_entries) >= BATCH_SIZE or (done == total and pending_entries):
                batch_num += 1
                count = len(pending_entries)
                msg   = (
                    f"sync: {version} [{PLATFORM}] "
                    f"batch {batch_num} ({count} files, {done}/{total} total)"
                )
                new_tree   = gh_create_tree(current_tree, pending_entries)
                new_commit = gh_create_commit(new_tree, current_head, msg)
                gh_update_ref(new_commit)
                current_head = new_commit
                current_tree = new_tree
                pending_entries = []
                pct = done / total * 100
                print(f"  ✓ batch {batch_num}: {count} files committed ({pct:.0f}%, failures={failed})")

    # 7. Update latest.txt
    print(f"[7] Updating bundles/latest.txt…")
    latest_blob = gh_upload_blob((version + "\n").encode())
    final_tree  = gh_create_tree(current_tree, [{
        "path": "bundles/latest.txt",
        "mode": "100644",
        "type": "blob",
        "sha":  latest_blob,
    }])
    final_commit = gh_create_commit(
        final_tree, current_head,
        f"sync: {version} [{PLATFORM}] — done ({total} total, {failed} failed)"
    )
    gh_update_ref(final_commit)

    print(f"\nDone. {total - failed}/{total} bundles committed in {batch_num} batches.")
    if failed:
        sys.exit(f"Exiting with error: {failed} bundles failed")


if __name__ == "__main__":
    main()
