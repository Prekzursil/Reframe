# Reframe Desktop (Tauri)

This is an **early** desktop wrapper for Reframe using **Tauri**.

## What it does (v1)

- Provides Start/Stop buttons for the local `infra/docker-compose.yml` stack.
- Opens the Reframe UI at `http://localhost:5173` (via Docker Compose `web` service).
- Designed to be **offline-first** (no paid APIs required).

## Prerequisites

- Docker Desktop (or Docker Engine) with Compose support.
- Rust toolchain (for building the desktop app).
- Tauri OS prerequisites (varies per OS; see Tauri docs).

## Development

From `apps/desktop`:

- Install deps: `npm install`
- Run: `npm run tauri dev`

## Notes

- This desktop wrapper currently relies on **local Docker** (simplest approach). Bundling API/worker as child processes is a follow-up.
