# Desktop Wrapper (Tauri plan)

## Decision

Use **Tauri** as the desktop wrapper (recommended for performance and a smaller distribution size than Electron).

## What a “desktop wrapper” does for Reframe

Reframe’s core UI is a web app (`apps/web`), but “desktop wrapper” means:

- You can ship a single installer (`.msi` / `.dmg` / `.AppImage`) that feels like a native app.
- The desktop app can:
  - open the local UI,
  - manage local services (v1: Docker Compose),
  - store local settings,
  - provide a predictable “launcher” experience (no terminals),
  - and support auto-updates.

The desktop wrapper is **not** where the heavy media processing happens — that still runs in the Python API/worker stack.

## Tauri vs Electron (how to choose)

Both Tauri and Electron let you build a desktop app using a web UI. The key difference is what runtime they ship.

### Electron

- Bundles **Chromium + Node.js** into your app.
- Pros:
  - Very consistent UI/rendering across OSes (same Chromium everywhere).
  - Huge ecosystem and many battle-tested desktop patterns (tray, auto-update, deep OS integrations).
  - If you already need Node APIs or many Node native modules, it can be straightforward.
- Cons:
  - Large installers (tens to hundreds of MB).
  - Higher idle RAM/CPU overhead (Chromium is heavy).
  - Bigger security surface (Node + Chromium; you must harden carefully).

### Tauri

- Uses the OS’s **native WebView** (WebView2 on Windows, WebKit on macOS, WebKitGTK on Linux).
- The “backend” is a small **Rust** binary that exposes commands to your frontend.
- Pros:
  - Much smaller installers.
  - Lower idle resource usage.
  - Security model is simpler by default (no Node in the renderer).
- Cons:
  - WebView behavior can differ between platforms (and OS versions).
  - Linux builds need system libraries (the workflow is a little more “native-app-like” than Electron).
  - Some Electron tooling/examples don’t translate 1:1.

### What matters most for Reframe

For Reframe specifically, the wrapper mainly needs to:

- Start/stop a local stack (Docker Compose in v1),
- open a local web UI,
- provide diagnostics (“is Docker running?”, “is the API reachable?”),
- and offer a signed updater via GitHub Releases.

This is a great fit for Tauri because Reframe doesn’t need a full embedded Chromium runtime and benefits a lot from:

- smaller downloads,
- lower RAM usage (especially while the worker is chewing on video),
- and a tighter security posture for a local-first tool.

## Near-term approach

- Keep the desktop app as a thin shell around the existing **API + worker** services.
- Prefer **offline-first** behavior:
  - `REFRAME_OFFLINE_MODE=true` by default in desktop builds.
  - No paid/cloud providers unless explicitly configured.

## Current implementation (v1)

- A basic Tauri scaffold lives in `apps/desktop`.
- It currently relies on **local Docker Compose** (simplest):
  - start/stop `infra/docker-compose.yml`,
  - open the UI at `http://localhost:5173`.
- See `apps/desktop/README.md` for prerequisites (especially for WSL vs native Windows/macOS/Linux builds).

## Next steps (planned)

- Decide whether to keep the Docker approach long-term, or switch to running API/worker as bundled child processes.
- Automate the signed updater release workflow (GitHub Releases + signing secrets).

## When you might prefer Electron instead

If Reframe’s desktop app grows into something that requires:

- a consistent Chromium runtime for advanced web features across platforms,
- heavy use of Node.js APIs or Node-native modules,
- very complex windowing/tray/background behavior,

…then Electron becomes more attractive despite the resource and size costs.
