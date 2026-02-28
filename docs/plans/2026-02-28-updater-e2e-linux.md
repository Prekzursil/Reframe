# Desktop updater E2E (linux)

- timestamp_utc: `2026-02-28T02:50:07.934909+00:00`
- success: `True`
- old_tag: `desktop-v0.1.6`
- new_tag: `desktop-v0.1.7`
- expected_old_version: `0.1.6`
- expected_new_version: `0.1.7`
- observed_old_version: `0.1.6`
- observed_new_version: `0.1.7`

## Commands

```text
/usr/bin/python3 /tmp/reframe-worktrees/best-of-best/scripts/verify_desktop_updater_release.py
bash /tmp/reframe-worktrees/best-of-best/scripts/desktop_updater_e2e_linux.sh --old-tag desktop-v0.1.6 --new-tag desktop-v0.1.7 --work-dir /tmp/reframe-worktrees/best-of-best/.tmp/desktop-updater-e2e/linux
```

## Raw Helper Output

```json
{
  "expected_new_version": "0.1.7",
  "expected_old_version": "0.1.6",
  "install_path": "/home/prekzursil/.local/share/reframe-updater-e2e/Reframe.AppImage",
  "new_asset": "Reframe_0.1.7_amd64.AppImage",
  "new_tag": "desktop-v0.1.7",
  "observed_new_version": "0.1.7",
  "observed_old_version": "0.1.6",
  "old_asset": "Reframe_0.1.6_amd64.AppImage",
  "old_tag": "desktop-v0.1.6",
  "platform": "linux",
  "success": true,
  "work_dir": "/tmp/reframe-worktrees/best-of-best/.tmp/desktop-updater-e2e/linux"
}
```
