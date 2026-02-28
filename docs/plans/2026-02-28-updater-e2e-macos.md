# Desktop updater E2E (macos)

- timestamp_utc: `2026-02-28T04:52:17.705057+00:00`
- success: `True`
- old_tag: `desktop-v0.1.6`
- new_tag: `desktop-v0.1.7`
- expected_old_version: `0.1.6`
- expected_new_version: `0.1.7`
- observed_old_version: `0.1.6`
- observed_new_version: `0.1.7`

## Commands

```text
/Library/Frameworks/Python.framework/Versions/3.11/bin/python /Users/runner/work/Reframe/Reframe/scripts/verify_desktop_updater_release.py
bash /Users/runner/work/Reframe/Reframe/scripts/desktop_updater_e2e_macos.sh --old-tag desktop-v0.1.6 --new-tag desktop-v0.1.7 --work-dir /Users/runner/work/Reframe/Reframe/.tmp/desktop-updater-e2e/macos
```

## Raw Helper Output

```json
{
  "expected_new_version": "0.1.7",
  "expected_old_version": "0.1.6",
  "new_asset": "Reframe_aarch64.app.tar.gz",
  "new_tag": "desktop-v0.1.7",
  "observed_new_version": "0.1.7",
  "observed_old_version": "0.1.6",
  "old_asset": "Reframe_aarch64.app.tar.gz",
  "old_tag": "desktop-v0.1.6",
  "platform": "macos",
  "success": true,
  "work_dir": "/Users/runner/work/Reframe/Reframe/.tmp/desktop-updater-e2e/macos"
}
```
