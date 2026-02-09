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

### 1.1 Hosted SaaS mode (Opus Clip‑style) — roadmap

You can also operate Reframe as a **hosted** service (multi‑tenant, paid plans) without rewriting the media pipeline.
Conceptually, the same building blocks apply, but the “local filesystem + local Docker” assumptions are replaced by
cloud primitives:

- **Web app delivery**
  - Serve `apps/web` as a static build from a CDN (Cloudflare Pages, Vercel, S3+CloudFront, etc.).
  - All API calls go to a hosted API base URL (not `localhost`).

- **Multi‑tenant API**
  - Add authentication (session cookies or JWT) and a `user_id`/`org_id` concept.
  - Every job and asset is owned by a user/org; enforce authorization at the API boundary.
  - Prefer direct-to-object-storage uploads (pre-signed PUT) to avoid proxying large files through the API.

- **Workers & scaling**
  - Keep Celery (or move to a managed queue) with autoscaled worker pools:
    - CPU pool (cheap) for light work.
    - GPU pool (expensive) for fast transcription and heavy rendering.
  - Enforce per-user concurrency limits and quotas to control cost.

- **Object storage**
  - Store assets/bundles in S3-compatible storage (AWS S3 / Cloudflare R2).
  - Use per-tenant prefixes (e.g. `s3://bucket/{org_id}/...`) to simplify isolation and lifecycle policies.
  - Prefer generating **signed download URLs** for large assets (already supported) instead of streaming via the API.

- **Billing + metering**
  - Integrate payments (typically Stripe) and a plan model (free trial, monthly tiers, usage-based add-ons).
  - Meter usage in units that map to cost drivers:
    - minutes transcribed,
    - minutes rendered,
    - GPU-seconds,
    - storage GB-month,
    - egress/download bandwidth (if relevant).

- **Privacy & retention**
  - Clear policy for where uploads are stored, for how long, and how deletions are handled.
  - Automated retention rules for temp/intermediate outputs (especially for free plans).

This repo already has several “hosted-ready” building blocks (remote storage backend, remote-worker asset download,
download URL endpoint), so the next step is primarily **auth + multi-tenancy + metering**.

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
