# Desktop Auto-Updates (Tauri Updater + GitHub Releases)

This desktop app uses the **Tauri Updater plugin** to support **signed** in-app updates.

The app is configured to check:

- `https://github.com/Prekzursil/Reframe/releases/latest/download/latest.json`

## Automated publishing (GitHub Actions)

This repo includes a GitHub Actions workflow that builds + publishes desktop releases (including `latest.json`) when you push a tag like:

- `desktop-v0.1.0`

Required repository secrets:

- `TAURI_SIGNING_PRIVATE_KEY` — contents of `apps/desktop/src-tauri/keys/tauri.key` (keep secret)
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` — optional (only if your key is password-protected)

Release flow:

1) Bump the version in:
   - `apps/desktop/package.json`
   - `apps/desktop/src-tauri/tauri.conf.json`
2) Push a tag:
   - `git tag desktop-v0.1.1`
   - `git push origin desktop-v0.1.1`
3) Wait for **Desktop Release** workflow to finish. A GitHub Release is created with:
   - updater bundles + `.sig`
   - `latest.json` asset used by the desktop app
4) Optional: validate the published updater JSON:
   - `python3 scripts/verify_desktop_updater_release.py`

## Signing keys

Keys are generated with the Tauri CLI signer:

- Private key (keep secret): `apps/desktop/src-tauri/keys/tauri.key` (**gitignored**)
- Public key: committed and embedded into `apps/desktop/src-tauri/tauri.conf.json`

If you need to rotate keys, generate a new keypair and replace the `plugins.updater.pubkey` value.

## Build updater artifacts

Tauri is configured with `bundle.createUpdaterArtifacts=true`, so release builds will produce updater bundles and `.sig` files.

When building, provide the signing key via env var:

```bash
cd apps/desktop
TAURI_SIGNING_PRIVATE_KEY_PATH=src-tauri/keys/tauri.key npx tauri build
```

Optional (recommended): set a password on the private key and provide it using `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.

## Publish an update (GitHub Releases)

Preferred: use the automated GitHub Actions workflow described above.

Manual (if needed):

1) Create a GitHub release for the new desktop version (tag should match `apps/desktop/src-tauri/tauri.conf.json` `version`).

2) Upload the updater bundles + signatures produced by Tauri:

- Linux: AppImage / `.tar.gz` updater bundle + `.sig`
- macOS: `.app.tar.gz` + `.sig`
- Windows: `.msi` / `.zip` updater bundle + `.sig`

Exact filenames differ by platform and bundler; use the files generated in `apps/desktop/src-tauri/target/release/bundle/`.

3) Create and upload `latest.json` as a release asset with this shape:

```json
{
  "version": "0.1.0",
  "notes": "Release notes here",
  "pub_date": "2026-02-03T00:00:00Z",
  "platforms": {
    "linux-x86_64": { "url": "https://...", "signature": "..." },
    "windows-x86_64": { "url": "https://...", "signature": "..." },
    "darwin-x86_64": { "url": "https://...", "signature": "..." }
  }
}
```

Notes:
- `signature` must be the **contents** of the generated `.sig` file (not a path/URL).
- `url` should point to the updater bundle asset in the GitHub release.

## Testing updates locally

The simplest test loop is:

1) Build and publish a `0.x.y` release and `latest.json`.
2) Run an older installed desktop build.
3) Click “Check updates” in the desktop UI to download/install and restart.

## Known-good E2E test releases (already published)

These tags are published and signed, and `latest.json` is already live:

- **Old**: `desktop-v0.1.6`
- **New (latest)**: `desktop-v0.1.7`

You can download the **old** installer for each OS using `gh`:

- Windows (MSI)
  - `gh release download desktop-v0.1.6 -p 'Reframe_0.1.6_x64_en-US.msi'`
- macOS (DMG)
  - Apple Silicon: `gh release download desktop-v0.1.6 -p 'Reframe_0.1.6_aarch64.dmg'`
  - Intel: `gh release download desktop-v0.1.6 -p 'Reframe_0.1.6_x64.dmg'`
- Linux (AppImage)
  - `gh release download desktop-v0.1.6 -p 'Reframe_0.1.6_amd64.AppImage'`

### End-to-end verification checklist

1) Publish two releases:
   - Old: `desktop-v0.x.y` (install this first)
   - New: `desktop-v0.x.(y+1)` (this should be the update you receive)
2) Confirm the updater JSON is reachable and valid:
   - `python3 scripts/verify_desktop_updater_release.py`
3) Launch the **old** desktop build and confirm the app version:
   - Expected: the UI shows `Desktop version: 0.x.y`
4) Click **Check updates**:
   - Expected: a prompt like `Update available: 0.x.y → 0.x.(y+1)`
5) Accept the update and watch the log panel:
   - Expected: `Downloading update…` → progress logs → `Download finished.` → `Update installed; restarting…`
6) After restart:
   - Click **Check updates** again
   - Expected: `No updates available.`

### Installing an older build (manual)

For the “old” release in the checklist above, install it from GitHub Releases:

- You can click **Open Releases** in the desktop UI to jump to the Releases page.

- Linux
  - Download the `.AppImage` (or the installer bundle you ship) from the old release assets.
  - `chmod +x ./Reframe*.AppImage && ./Reframe*.AppImage`
- Windows
  - Download and install the old `.msi` from the old release assets.
  - If you already have a newer install, uninstall it first so you can validate the updater path.
- macOS
  - Download and install the old build from the old release assets (often `.dmg` or `.app.tar.gz`).
  - If Gatekeeper blocks the app, you may need to allow it in System Settings → Privacy & Security.

Common failure modes:
- “Signature verification failed” typically means `latest.json` points at the wrong asset or signature contents are incorrect.
- “Update check failed” can be missing/invalid `latest.json` at the configured endpoint.
