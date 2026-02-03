# Desktop Wrapper (Tauri plan)

## Decision

Use **Tauri** as the desktop wrapper (recommended for performance and a smaller distribution size than Electron).

## Near-term approach

- Keep the desktop app as a thin shell around the existing **API + worker** services.
- Prefer **offline-first** behavior:
  - `REFRAME_OFFLINE_MODE=true` by default in desktop builds.
  - No paid/cloud providers unless explicitly configured.

## Next steps (planned)

- Decide whether the desktop app should:
  - run API/worker as child processes (bundled Python runtime), or
  - rely on local Docker (simpler, but requires Docker installed).
- Add a basic Tauri scaffold once the service lifecycle approach is chosen.

