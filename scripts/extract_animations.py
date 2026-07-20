"""
extract_animations.py
======================
Reads every *.bin bundle from INPUT_DIR, zstd-decompresses it (the CDN
serves bundles zstd-wrapped — that's the reason a prior version of this
script always saw 0 objects: UnityPy was being handed compressed bytes,
not a real UnityFS bundle), loads the decompressed bytes with UnityPy,
and keeps every TextAsset whose raw data starts with the animation magic
header. Nothing is written back into INPUT_DIR — decompression happens
in memory only, so the original .bin files on disk are untouched.

Output always goes to `bundles/assets` (OUTPUT_DIR) — a subfolder of
`bundles/`, kept separate from the raw `bundles/{version}/*.bin` files
that sync_bundles.py writes, so extraction output and raw synced bundles
never collide on disk or in git history. bundles/assets is deleted and
rebuilt from scratch at the start of every run — no stale files left
over from a previous run.

Magic header (6 bytes):
    EE C0 D2 C2 22 A0

Env vars:
    INPUT_DIR   – folder containing the raw *.bin bundles to scan (required)
    OUTPUT_DIR  – where extracted animations are written (default: bundles/assets)
"""

import os
import shutil
import sys
import traceback
from collections import Counter
from pathlib import Path

import UnityPy

try:
    import zstandard
except ImportError:
    sys.exit(
        "ERROR: zstandard package is required (pip install zstandard).\n"
        "Bundles from the CDN are zstd-compressed; UnityPy cannot read\n"
        "them without decompression first."
    )

print(f"UnityPy version: {getattr(UnityPy, '__version__', 'unknown')}")

ANIM_MAGIC = bytes.fromhex("eec0d2c222a0")
ZSTD_MAGIC = bytes.fromhex("28b52ffd")

INPUT_DIR = os.environ.get("INPUT_DIR")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "bundles/assets"))

if not INPUT_DIR:
    sys.exit("ERROR: INPUT_DIR env var is required")

input_dir = Path(INPUT_DIR)
if not input_dir.is_dir():
    sys.exit(f"ERROR: INPUT_DIR does not exist or is not a directory: {input_dir}")

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_bundle(bin_path: Path):
    raw_bytes = bin_path.read_bytes()
    if raw_bytes[:4] == ZSTD_MAGIC:
        dctx = zstandard.ZstdDecompressor()
        raw_bytes = dctx.decompress(raw_bytes, max_output_size=500 * 1024 * 1024)
    return UnityPy.load(raw_bytes)

bin_files = sorted(input_dir.glob("*.bin"))
print(f"Scanning {len(bin_files)} bundle(s) in {input_dir}")

total_text_assets = 0
kept = 0
skipped_non_anim = 0
failed_bundles = 0
failed_reads = 0
type_counts = Counter()
first_failure_shown = False

for bin_path in bin_files:
    try:
        env = load_bundle(bin_path)
    except Exception:
        failed_bundles += 1
        print(f"  FAIL to load {bin_path.name}:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        continue

    for obj in env.objects:
        type_counts[obj.type.name] += 1

        if obj.type.name != "TextAsset":
            continue
        total_text_assets += 1

        try:
            data = obj.read()
            raw = data.script if hasattr(data, "script") else data.m_Script
            if isinstance(raw, str):
                raw = raw.encode("utf-8", errors="surrogateescape")
        except Exception:
            failed_reads += 1
            print(f"  FAIL to read TextAsset in {bin_path.name}:", file=sys.stderr)
            if not first_failure_shown:
                traceback.print_exc(file=sys.stderr)
                first_failure_shown = True
            else:
                print(f"    {sys.exc_info()[1]}", file=sys.stderr)
            continue

        if not raw.startswith(ANIM_MAGIC):
            skipped_non_anim += 1
            continue

        name = getattr(data, "m_Name", None) or f"unnamed_{obj.path_id}"
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        dest = OUTPUT_DIR / f"{safe_name}.bin"

        if dest.exists():
            dest = OUTPUT_DIR / f"{safe_name}_{obj.path_id}.bin"

        dest.write_bytes(raw)
        kept += 1

print(f"\nDone.")
print(f"  Bundles scanned       : {len(bin_files)}")
print(f"  Bundles failed to load: {failed_bundles}")
print(f"  TextAssets seen       : {total_text_assets}")
print(f"  TextAssets unreadable : {failed_reads}")
print(f"  Kept as animations    : {kept}")
print(f"  Skipped (non-anim)    : {skipped_non_anim}")
print(f"  Output dir            : {OUTPUT_DIR}")

print(f"\nObject types seen across all bundles (top 20):")
if type_counts:
    for type_name, count in type_counts.most_common(20):
        print(f"  {count:>8}  {type_name}")
else:
    print("  none — every bundle loaded with an empty object graph.")
    print("  Confirmed cause historically: CDN bundles are zstd-compressed")
    print("  and were being handed to UnityPy without decompression. This")
    print("  script now decompresses automatically, so if you still see")
    print("  this, check that INPUT_DIR actually contains .bin files and")
    print("  that zstandard installed correctly.")
