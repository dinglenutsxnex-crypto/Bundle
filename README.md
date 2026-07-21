# Bundle

Auto-synced Shadow Fight Arena asset bundles.

The GitHub Actions workflow runs daily, checks the game's balance server for the latest version, downloads all asset bundles from the CDN, and commits them here.

## Layout

```
bundles/
  latest.txt                  ← current synced version string
  1.9.80.20.26181-prod/       ← one folder per game version, raw synced bundles
    000d4845d55a955c4f996094bae3364b.bin
    001b2a93d0efc969bb5637f424b384a8.bin
    ...                       ← 4000+ .bin files, each zstd-compressed as served by the CDN
  assets/                     ← extracted animation files (from extract-animations.yml)
    some_animation_name.bin
    ...
```

Bundles served by the CDN arrive zstd-compressed. `sync_bundles.py` stores them exactly as downloaded — compressed — since decompressing every bundle at sync time roughly quadruples on-disk size and several bundles exceed GitHub's 100MB file limit once decompressed. `extract_animations.py` decompresses each bundle in memory, per-file, right before handing it to UnityPy; nothing decompressed ever touches disk in the sync step.

## How it works

1. **Balance check** — hits `https://sfalb.nekki.com/balance` to get the latest `version.cur` and the config ZIP URL.
2. **Decrypt config** — downloads `{version}_all.zip`, finds the `.enc` file inside, and AES-128-CBC decrypts it to get the inner config ZIP.
3. **Parse bundlesConfig** — reads `client/bundlesConfig_{N}_{Platform}.bytes` (protobuf) to extract all archive names. The `{N}` also determines the CDN subdirectory (`ArenaBundles{N}`).
4. **Download bundles** — fetches `https://sfacdn.nekki.com/Bundles/ArenaBundles{N}/Android/archives/{name}.bin` for each archive, 16 workers in parallel, and writes each response to disk as-is (still zstd-compressed).
5. **Commit** — stages `bundles/` and pushes a commit like `sync: 1.9.80.20.26181-prod [Android] — 4086 files`.

Already-present bundles are skipped, so incremental updates are fast.

`bundles/assets/` is reserved for `extract-animations.yml` output and is never touched by the sync workflow.

## Manual trigger

Go to **Actions → Sync SFA Bundles → Run workflow**. You can optionally set:
- **Platform**: `Android` (default), `iOS`, or `StandaloneWindows`
- **Force**: `true` to re-download even if the version hasn't changed

Go to **Actions → Extract Animations → Run workflow** to pull animation `TextAsset`s out of a synced version's raw bundles. Requires:
- **version**: the `bundles/{version}` folder to read from (e.g. `1.9.80.21.26220-prod`)

The work is split across 4 parallel shards (matching the sync workflow's shard count), each decompressing and scanning its slice of bundles independently, then merged into a single `bundles/assets/` commit. If two shards happen to produce an animation with the same derived filename, the merge step disambiguates by appending a short content hash rather than overwriting one with the other.

Output always lands in `bundles/assets/`, which is wiped and rebuilt on every run.

## Scripts

| File | Purpose |
|------|---------|
| `scripts/sync_bundles.py` | All sync logic — balance fetch, decrypt, parse, download. Zero external deps (stdlib only). Bundles are written to disk exactly as the CDN serves them (zstd-compressed). |
| `scripts/extract_animations.py` | Reads raw bundles from `bundles/{version}/`, zstd-decompresses each in memory and loads it with UnityPy, keeps `TextAsset`s matching the animation magic header. Supports `SHARD_INDEX`/`SHARD_TOTAL` env vars for splitting the bundle list across parallel runs. Writes to `OUTPUT_DIR` (default `bundles/assets`). |
| `.github/workflows/sync-bundles.yml` | Runs the sync script daily and on manual trigger, splits the download into 4 shards, merges, then commits. |
| `.github/workflows/extract-animations.yml` | Runs the extraction script across 4 parallel shards for a given version, uploads each shard's output as an artifact, then a merge job flattens all four (resolving any filename collisions) and commits `bundles/assets`. |

## CDN URL pattern

```
https://sfacdn.nekki.com/Bundles/ArenaBundles{N}/{Platform}/archives/{archive_name}.bin
```

Where `{N}` comes from the `bundlesConfig_{N}_{Platform}.bytes` filename in the config archive (currently `6`).
