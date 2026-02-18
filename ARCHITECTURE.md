# Reframe Architecture

## 1. High‑Level Overview

Reframe is a **local‑first media processing stack**:

- **Frontend** (`apps/web`)
  - React SPA/MPA with routes for:
    - Shorts Maker
    - Caption & Translate
    - Subtitle Tools (SRT translator, style presets)
    - Utilities (video/audio merge)
    - Jobs / History
  - Can run:
    - in browser for local web UI, and
    - inside a Tauri/Electron shell for a desktop app.

- **API Service** (`apps/api`)
  - Python FastAPI app exposing a stable REST/JSON API.
  - Handles:
    - job creation & status polling,
    - file upload/download,
    - preset management (subtitle templates, model choices),
    - health checks.

- **Worker(s)** (`services/worker`)
  - Celery worker processes that run CPU/GPU‑heavy tasks:
    - transcribing audio/video,
    - cutting clips,
    - rendering subtitled videos,
    - translating transcripts/SRT,
    - merging audio+video.

- **Media Core Library** (`packages/media-core`)
  - Pure‑Python library with no FastAPI/React coupling.
  - Provides functions & classes for each step in the pipeline:
    - `Transcriber`
    - `Segmenter`
    - `SubtitleBuilder` (plain + TikTok highlight)
    - `Translator`
    - `VideoEditor`
  - Can be used standalone from CLI or notebooks.

- **Storage**
  - Local filesystem for:
    - uploaded media (`/data/media`),
    - intermediate audio (`/data/audio`),
    - transcripts & subtitles (`/data/subtitles`),
    - rendered outputs (`/data/outputs`).
  - SQLite DB (dev) for metadata & jobs; Postgres optional later.

---

## 2. Directory Layout (Proposed)

```text
.
├─ apps/
│  ├─ api/
│  │  ├─ main.py            # FastAPI entrypoint
│  │  ├─ routes/            # /shorts, /captions, /subtitles, /jobs
│  │  ├─ schemas/           # Pydantic request/response models
│  │  └─ deps/              # DI, settings, DB session, etc.
│  └─ web/
│     ├─ src/
│     │  ├─ pages/          # React routes (Shorts, Captions, etc.)
│     │  ├─ components/     # Forms, previews, job list, etc.
│     │  └─ api/            # Typed API client
│     └─ ...
├─ services/
│  └─ worker/
│     ├─ worker.py          # Celery app
│     └─ tasks/             # Celery tasks using media-core
├─ packages/
│  └─ media-core/
│     ├─ transcribe/
│     ├─ segment/
│     ├─ subtitles/
│     ├─ translate/
│     ├─ video_edit/
│     ├─ models/            # Pydantic models (Job, MediaAsset, SubtitleStyle, etc.)
│     └─ config.py
├─ infra/
│  ├─ docker-compose.yml
│  ├─ Dockerfile.api
│  ├─ Dockerfile.worker
│  └─ nginx.conf (optional)
└─ docs/
   ├─ ARCHITECTURE.md
   ├─ README.md
   ├─ goal.md
   └─ todo.md
```

---

## 3. Monorepo Slice Ownership

When working on tasks in this monorepo, **clearly identify which slice(s) are affected**:

### Slice Definitions

- **`apps/api`** – Backend API slice
  - Changes to REST endpoints, database models, request/response schemas
  - Dependencies: `packages/media-core`
  - Testing: Integration tests in `apps/api/tests`

- **`apps/web`** – Frontend slice
  - React components, pages, UI logic, API client
  - Testing: Component tests, E2E tests
  - Build output: Static assets for production

- **`services/worker`** – Background worker slice
  - Celery task definitions, job processing logic
  - Dependencies: `packages/media-core`
  - Testing: Worker-specific tests

- **`packages/media-core`** – Core library slice
  - Media processing algorithms, transcription, translation, video editing
  - No web or API dependencies (standalone)
  - Testing: Unit tests for all modules

- **`infra/`** – Infrastructure slice
  - Docker configuration, deployment scripts
  - Affects all services when changed

- **`docs/`** – Documentation slice
  - Markdown files, architecture diagrams
  - No runtime impact; docs-only changes are low-risk

### Slice Ownership Guidelines

1. **Single-slice changes** are preferred and easier to review
2. **Multi-slice changes** require explicit coordination and integration plan
3. Always specify affected slices in issue descriptions and PRs
4. Run `make verify` from **repository root** before submitting changes
5. Keep changes **minimal and scoped** to the task at hand
