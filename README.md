# Bundle

Auto-synced Shadow Fight Arena asset bundles.

The GitHub Actions workflow runs daily, checks the game's balance server for the latest version, downloads all asset bundles from the CDN, and commits them here.

## Layout

```
bundles/
  latest.txt                  ← current synced version string
  1.9.80.20.26181-prod/       ← one folder per game version
    000d4845d55a955c4f996094bae3364b.bin
    001b2a93d0efc969bb5637f424b384a8.bin
    ...                       ← 4000+ .bin files
```

## How it works

1. **Balance check** — hits `https://sfalb.nekki.com/balance` to get the latest `version.cur` and the config ZIP URL.
2. **Decrypt config** — downloads `{version}_all.zip`, finds the `.enc` file inside, and AES-128-CBC decrypts it to get the inner config ZIP.
3. **Parse bundlesConfig** — reads `client/bundlesConfig_{N}_{Platform}.bytes` (protobuf) to extract all archive names. The `{N}` also determines the CDN subdirectory (`ArenaBundles{N}`).
4. **Download bundles** — fetches `https://sfacdn.nekki.com/Bundles/ArenaBundles{N}/Android/archives/{name}.bin` for each archive, 16 workers in parallel.
5. **Commit** — stages `bundles/` and pushes a commit like `sync: 1.9.80.20.26181-prod [Android] — 4086 files`.

Already-present bundles are skipped, so incremental updates are fast.

## Manual trigger

Go to **Actions → Sync SFA Bundles → Run workflow**. You can optionally set:
- **Platform**: `Android` (default), `iOS`, or `StandaloneWindows`
- **Force**: `true` to re-download even if the version hasn't changed

## Scripts

| File | Purpose |
|------|---------|
| `scripts/sync_bundles.py` | All logic — balance fetch, decrypt, parse, download. Zero external deps (stdlib only). |
| `.github/workflows/sync-bundles.yml` | Runs the script daily and on manual trigger, then commits. |

## CDN URL pattern

```
https://sfacdn.nekki.com/Bundles/ArenaBundles{N}/{Platform}/archives/{archive_name}.bin
```

Where `{N}` comes from the `bundlesConfig_{N}_{Platform}.bytes` filename in the config archive (currently `6`).
