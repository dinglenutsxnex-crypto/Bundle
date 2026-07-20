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
    ...                       ← 4000+ .bin files, each a decompressed UnityFS bundle
  assets/                     ← extracted animation files (from extract-animations.yml)
    some_animation_name.bin
    ...
```

Bundles served by the CDN arrive zstd-compressed. `sync_bundles.py` decompresses each one immediately after download and writes only the decompressed `UnityFS` bytes to disk — the compressed original is never persisted.

## How it works

1. **Balance check** — hits `https://sfalb.nekki.com/balance` to get the latest `version.cur` and the config ZIP URL.
2. **Decrypt config** — downloads `{version}_all.zip`, finds the `.enc` file inside, and AES-128-CBC decrypts it to get the inner config ZIP.
3. **Parse bundlesConfig** — reads `client/bundlesConfig_{N}_{Platform}.bytes` (protobuf) to extract all archive names. The `{N}` also determines the CDN subdirectory (`ArenaBundles{N}`).
4. **Download bundles** — fetches `https://sfacdn.nekki.com/Bundles/ArenaBundles{N}/Android/archives/{name}.bin` for each archive, 16 workers in parallel. Each response is zstd-decompressed before being written to disk.
5. **Commit** — stages `bundles/` and pushes a commit like `sync: 1.9.80.20.26181-prod [Android] — 4086 files`.

Already-present bundles are skipped, so incremental updates are fast.

`bundles/assets/` is reserved for `extract-animations.yml` output and is never touched by the sync workflow.

## Manual trigger

Go to **Actions → Sync SFA Bundles → Run workflow**. You can optionally set:
- **Platform**: `Android` (default), `iOS`, or `StandaloneWindows`
- **Force**: `true` to re-download even if the version hasn't changed

Go to **Actions → Extract Animations → Run workflow** to pull animation `TextAsset`s out of a synced version's raw bundles. Requires:
- **version**: the `bundles/{version}` folder to read from (e.g. `1.9.80.21.26220-prod`)

Output always lands in `bundles/assets/`, which is wiped and rebuilt on every run.

## Scripts

| File | Purpose |
|------|---------|
| `scripts/sync_bundles.py` | All sync logic — balance fetch, decrypt, parse, download, zstd-decompress. Stdlib only, except shelling out to the `zstd` CLI for decompression. |
| `scripts/extract_animations.py` | Reads raw bundles from `bundles/{version}/`, decompresses (zstd, if still compressed) and loads each with UnityPy, keeps `TextAsset`s matching the animation magic header. Writes to `bundles/assets/`. |
| `.github/workflows/sync-bundles.yml` | Runs the sync script daily and on manual trigger, then commits. |
| `.github/workflows/extract-animations.yml` | Runs the extraction script on manual trigger for a given version, then commits `bundles/assets/`. |

## CDN URL pattern

```
https://sfacdn.nekki.com/Bundles/ArenaBundles{N}/{Platform}/archives/{archive_name}.bin
```

Where `{N}` comes from the `bundlesConfig_{N}_{Platform}.bytes` filename in the config archive (currently `6`).
