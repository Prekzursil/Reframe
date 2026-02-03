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
