# Clean-box first-run smoke (packaged Windows app)

The CI e2e suite proves the app works end-to-end **on the dev build** (`golden-journey`
passes on Windows + Linux; `preview.spec` everywhere) and proves the **packaged `.exe`**
launches (`packaged.spec`: `isPackaged`, asar path, the FirstRunSetup gate renders, the
seeded env is wired). What CI **cannot** cover is the **cold packaged first-run**: on a
fresh machine the shipped `.exe` pip-installs the heavy Python sidecar runtime into
`%APPDATA%\media-studio\envs\sidecar` — a multi-minute, network-bound step that exceeds
any CI window. This is the one decisive check to run by hand on a clean box.

## What you need

- A clean Windows 10/11 box **or** a fresh Windows user profile / VM snapshot with **no**
  prior `%APPDATA%\media-studio\` (delete it first if present).
- Network access (first run downloads the sidecar wheels + the sha256-pinned models).
- The v1.4.1 installer: `media-studio-1.4.1-win-x64.exe` (NSIS) — from the GitHub Release,
  or build locally: `cd app && npx electron-builder --config ../electron-builder.yml --win --publish never`.

## The smoke (≈5–10 min incl. first-run provisioning)

1. **Install + launch.** Run the NSIS installer, launch Reframe.
   - ✅ EXPECT: the window opens and shows the **FirstRunSetup** screen (a "setting up"
     UI with a progress phase) — **NOT a blank/white screen**. If it is blank for more
     than a few seconds, that is a real bug — capture `%APPDATA%\media-studio\logs\` and stop.
2. **Let provisioning finish.** The setup screen advances through the phases while it
   installs the sidecar runtime + downloads the models (YuNet etc.). This is the
   multi-minute step.
   - ✅ EXPECT: it reaches the shell (the `Reframe` brand + the `Library` panel) with no
     "sidecar is not running" banner.
3. **Real transcribe → reframe → export (offline after provisioning).**
   - Add a short 16:9 sample video (drop it on the Library).
   - Open it → **Make Shorts** → add a manual range (e.g. `0:00`–`0:05`) → **Make shorts
     from ranges**.
   - ✅ EXPECT: a produced **vertical 9:16** short appears in the gallery and the file
     exists on disk (`%APPDATA%\media-studio\exports\...`), plays, and is genuinely
     portrait (height > width).
4. **No white screen on relaunch.** Close and reopen the app.
   - ✅ EXPECT: it goes **straight to the shell** (no FirstRunSetup — provisioning is a
     first-run-only step; a returning user is never re-prompted), no blank screen.

## Auto-update smoke (1.4.0 → 1.4.1) — optional but recommended

If you have a machine already running the published **1.4.0**:

1. Launch 1.4.0, let it check the update feed (or trigger the in-app update check).
   - ✅ EXPECT: it detects **1.4.1**, downloads, and prompts to restart.
2. Restart into 1.4.1.
   - ✅ EXPECT: the app relaunches on 1.4.1 with the existing data root intact (no
     re-provisioning), and Make Shorts still works.

## What 1.4.1 fixes (why the update matters)

- **Vision-jobs cloud-egress fix** — the off-thread `get_raw()` returned redacted key
  markers, so tier≥2 cloud vision in `thumbnail.select` / `phase8.select` jobs
  crashed/degraded. Keys are now captured synchronously in the handler.
- **Renderer resilience (WU2)** — an `ErrorBoundary` wraps `<App/>` and every eager-rpc
  site guards the synchronous bridge throw, so a sidecar hiccup shows an inline error
  instead of a white screen; `main.ts` adds render-process-gone / uncaught handlers.
- **Reframe model provisioning** — the e2e + first-run provisioning path for the
  claudeshorts YuNet model is hardened (loud failure if a download is silently skipped).

## If something fails

Capture and send: `%APPDATA%\media-studio\logs\`, the exact step that failed, and whether
the screen was blank vs. showed the setup UI. A blank screen at step 1, or a failure to
reach the shell at step 2, is the class of bug this smoke exists to catch.
