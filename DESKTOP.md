# Desktop Wrapper (Tauri plan)

## Decision

Use **Tauri** as the desktop wrapper (recommended for performance and a smaller distribution size than Electron).

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

## Next steps (planned)

- Decide whether to keep the Docker approach long-term, or switch to running API/worker as bundled child processes.
- Integrate an update mechanism (optional later).
