# Reframe Desktop (Tauri)

This is an **early** desktop wrapper for Reframe using **Tauri**.

## What it does (v1)

- Provides Start/Stop buttons for the local `infra/docker-compose.yml` stack.
- Opens the Reframe UI at `http://localhost:5173` (via Docker Compose `web` service).
- “Check updates” uses the Tauri updater (and falls back to opening GitHub Releases if misconfigured).
- Designed to be **offline-first** (no paid APIs required).

## Auto-updates

See `apps/desktop/UPDATER.md`.

## Prerequisites

- Docker Desktop (or Docker Engine) with Compose support.
- Rust toolchain (for building the desktop app).
- Tauri OS prerequisites (varies per OS; see Tauri docs).

### Notes for WSL users

This repo is often developed inside WSL2, but **building Tauri on Linux** typically requires system packages
(`webkit2gtk`, `librsvg2`, etc.) that you may not have (and may not be able to install without admin rights).

Recommended workflow:
- Develop the Reframe stack in WSL (Docker + API/worker/web).
- Build the Tauri desktop app on the **native host OS** (Windows) with the Tauri prerequisites installed.

## Development

From `apps/desktop`:

- Install deps: `npm install`
- Run: `npm run tauri dev`

## Notes

- This desktop wrapper currently relies on **local Docker** (simplest approach). Bundling API/worker as child processes is a follow-up.
