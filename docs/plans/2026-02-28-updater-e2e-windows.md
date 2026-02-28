# Desktop updater E2E (windows)

- timestamp_utc: `2026-02-28T04:52:54.896301+00:00`
- success: `True`
- old_tag: `desktop-v0.1.6`
- new_tag: `desktop-v0.1.7`
- expected_old_version: `0.1.6`
- expected_new_version: `0.1.7`
- observed_old_version: `0.1.6`
- observed_new_version: `0.1.7`

## Commands

```text
'C:\hostedtoolcache\windows\Python\3.11.9\x64\python.exe' 'D:\a\Reframe\Reframe\scripts\verify_desktop_updater_release.py'
pwsh -NoProfile -ExecutionPolicy Bypass -File 'D:\a\Reframe\Reframe\scripts\desktop_updater_e2e_windows.ps1' -OldTag desktop-v0.1.6 -NewTag desktop-v0.1.7 -WorkDir 'D:\a\Reframe\Reframe\.tmp\desktop-updater-e2e\windows'
```

## Raw Helper Output

```json
{
  "expected_new_version": "0.1.7",
  "expected_old_version": "0.1.6",
  "new_asset": "Reframe_0.1.7_x64_en-US.msi",
  "new_tag": "desktop-v0.1.7",
  "observed_new_version": "0.1.7",
  "observed_old_version": "0.1.6",
  "old_asset": "Reframe_0.1.6_x64_en-US.msi",
  "old_tag": "desktop-v0.1.6",
  "platform": "windows",
  "success": true,
  "uninstalled_previous_version": null,
  "work_dir": "D:\\a\\Reframe\\Reframe\\.tmp\\desktop-updater-e2e\\windows"
}
```
