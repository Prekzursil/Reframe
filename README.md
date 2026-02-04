# Reframe – AI Media Toolkit

> Local‑first GUI app for AI shorts, captions, translation, and TikTok‑style subtitles.

Reframe is a monolithic but modular toolkit that unifies all the experiments you’ve collected:

- `ai-short-maker` (shorts + subtitles)
- `long_to_shorts_app` (FastAPI + Celery + GROQ)
- `video-subtitles-generator` (Descript‑style word highlighting)
- `subsai`, `Whisper-WebUI`, `pyvideotrans`, etc.

The goal is **one** desktop‑friendly GUI that:

- turns long videos into shorts using AI,
- generates & translates captions,
- merges video + audio,
- translates SRTs,
- and burns *either* plain or TikTok‑style word‑highlight subtitles.

It’s inspired by tools like Clipify (AI shorts from long videos), Subs AI (multi‑backend Whisper UI), and pyVideoTrans (translation + dubbing pipeline).

---

## Feature Overview

**Core v1 feature set**

- **AI Shorts Maker**
  - Input: local file or URL (YouTube / generic, via `yt-dlp`).
  - Modes:
    - *Auto interesting segments*: LLM ranks transcript chunks and picks top N moments.
    - *Prompt‑guided*: “Find all moments where I talk about pricing” etc.
  - Control: min/max clip length, number of clips, aspect ratio (9:16, 1:1, 16:9).
  - Output: rendered shorts (with or without burnt subtitles) + .srt/.ass + JSON metadata.

- **Caption & Translation**
  - Long‑form captioning with **word‑level timestamps** (via whisper‑timestamped / faster‑whisper / whisper.cpp).
  - Export: `.srt`, `.vtt`, `.ass`, TXT.
  - Translate to target language(s) using pluggable translation backends.
  - Optional title/description translation for YouTube/TikTok upload workflows.

- **TikTok‑style Subtitles**
  - Plain captions (classic SRT).
  - **Word‑by‑word highlight** style similar to Descript / CapCut:
    - Bold white text with stroke & outline.
    - Per‑word highlight color that appears exactly while the word is spoken.
  - Styling presets: font, color, highlight color, outline, shadow, positioning.

- **SRT / Subtitle Translator**
  - Import `.srt` / `.ass`.
  - Translate while preserving timing & formatting.
  - Generate bilingual (stacked / side‑by‑side) variants.

- **Video / Audio Merger**
  - Replace or mix audio track in a video with an external audio file.
  - Options: offset, duck original audio, normalize loudness.

- **“Utilities”**
  - Batch subtitling.
  - Silence trimming & pacing.
  - Speaker diarization for multi‑speaker content (leveraging patterns from Whisper-WebUI & pyannote).

---

## High‑Level Architecture

Reframe is designed as a **local‑first monorepo**:

- `apps/api` – Python FastAPI service exposing a JSON API.
- `apps/web` – React + TypeScript frontend (can run as:
  - local web UI, and
  - desktop app via Tauri/Electron wrapper).
- `services/worker` – Celery worker(s) for heavy media jobs.
- `packages/media-core` – Python library with all media logic:
  - `transcribe/` – Whisper, faster‑whisper, whisper.cpp, etc.
  - `segment/` – long‑to‑short segmentation + LLM scoring.
  - `subtitles/` – SRT/ASS generation, TikTok‑style highlight via MoviePy.
  - `translate/` – transcript & subtitle translation.
  - `video_edit/` – clipping, scaling, merge, burn‑in via FFmpeg/MoviePy.
  - `models/` – pydantic models for jobs, media assets, subtitle styles.

Existing tools like Clipify, pyVideoTrans, and Subs AI are monolithic or semi‑modular; Reframe explicitly separates **media core** from **API/UI**, so you can reuse the core from CLI tools or notebooks.

See `ARCHITECTURE.md` for details.

---

## Tech Stack (Proposed)

**Backend / Media engine**

- Python 3.11+
- FastAPI (+ Uvicorn) for HTTP API.
- Celery + Redis (or RabbitMQ) for background jobs.
- FFmpeg for all audio/video I/O.
- Whisper variants (openai/whisper, faster‑whisper, whisper.cpp, whisper‑timestamped).
- MoviePy + pysubs2 for subtitle rendering & styling.
- Pydantic / SQLModel + SQLite (dev) → Postgres (optional, for server mode).

**Frontend**

- React + Vite + TypeScript.
- Shadcn/Radix‑style component library (you already have this in `ai-short-maker`).
- Tailwind or CSS‑in‑JS (up to you).
- Optional: Tauri wrapper for native desktop app.

---

## How This Builds on Your Existing Prototypes

From the projects in `AI Media Toolkit/`:

- **`ai-short-maker`**
  - Great React UI patterns: sidebar layout, job queue, subtitle generator/translator forms.
  - Job model with status & log fields.
  - LLM‑based transcript analysis using GROQ.
  - ➜ Reuse the **UX patterns** and the idea of a `ProcessingJob` model, but reimplement core logic in `media-core`.

- **`long_to_shorts_app` (v1 + v2)**
  - FastAPI + Celery pattern for async video jobs.
  - Whole‑video transcription, equal sized clips, SRT+ASS generation with pysubs2.
  - Docker‑first deployment idea.
  - ➜ Use this as the backbone for the new **FastAPI + Celery** layout and SRT/ASS generation.

- **`video-subtitles-generator`**
  - MoviePy pipeline for **per‑word highlighted subtitles**.
  - Layered text (base text, outline, shadow, per‑word highlight).
  - ➜ Adopt this strategy inside `media-core/subtitles/highlighted.py` and expose style presets via the GUI.

- **`subsai`, `Whisper-WebUI`**
  - Demonstrate how to support multiple Whisper backends, VAD, and diarization in one UI.
  - ➜ Borrow config ideas (backend selection, model cache directory, device selection).

- **`pyvideotrans`**
  - Mature translation + dubbing pipeline, including SRT translation and audio re‑synthesis.
  - ➜ Use as reference for future “full translation + dubbing” mode.

The point of Reframe is to **merge** these ideas into one consistent, testable architecture instead of having many one‑off experiments.

---

## Development Status

Right now this repo is in the **planning / scaffolding** stage:

- This README + `ARCHITECTURE.md` + `GOAL.md` describe the target system.
- `TODO.md` contains a detailed checklist you can turn into issues.
- Initial work is:
  - scaffolding the monorepo,
  - wiring minimal FastAPI + worker + single “transcribe video → SRT” endpoint,
  - creating a simple “upload video → show subtitles” UI.

---

## Getting Started (planned flow)

Once the initial scaffolding is done, the flow will look like:

```bash
# 1. Configure env (edit as needed)
cp .env.example .env

# 2. Start services
docker compose -f infra/docker-compose.yml up --build

# 3. API will run on http://localhost:8000
# 4. Web UI will run on http://localhost:5173
```

---

## Packaging & Deployment

### Shared media volume (docker compose)

The API and worker mount the same `MEDIA_ROOT` volume so assets generated by the worker are immediately downloadable via the API. See `infra/docker-compose.yml`.

### Remote storage (S3 / Cloudflare R2)

If the API and worker do **not** share a filesystem, configure the API to store assets in S3-compatible storage:

- `REFRAME_STORAGE_BACKEND=s3` (or `r2`)
- `REFRAME_S3_BUCKET=<bucket>`
- `REFRAME_S3_PREFIX=<optional/prefix>`
- `REFRAME_S3_REGION=<region>` (optional for R2)
- `REFRAME_S3_ENDPOINT_URL=<https://<account>.r2.cloudflarestorage.com>` (R2)
- `REFRAME_S3_PUBLIC_BASE_URL=<https://public.example.com>` (optional, recommended)
- `REFRAME_S3_PRESIGN_EXPIRES_SECONDS=604800`

**Notes**

- If `REFRAME_S3_PUBLIC_BASE_URL` is set, asset URIs are public URLs (best for the web UI).
- If you need pre-signed downloads, use `GET /api/v1/assets/{asset_id}/download-url?presign=true`.
- `REFRAME_OFFLINE_MODE=true` disables all remote storage and network providers.

### Remote workers (no shared volume)

When the worker runs on a different host, it will download remote `http(s)` asset URIs into `MEDIA_ROOT/tmp` before processing. Ensure:

- `REFRAME_OFFLINE_MODE` is **not** set (or false) for the worker.
- `MEDIA_ROOT/tmp` has enough disk space for temporary inputs/outputs.

### All‑in‑one Docker image (API + worker)

For simpler single‑host deployments, build/run the all‑in‑one image:

```bash
docker build -f Dockerfile.allinone -t reframe-allinone .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=sqlite:////data/reframe.db \
  -e MEDIA_ROOT=/data/media \
  -e BROKER_URL=redis://host.docker.internal:6379/0 \
  -e RESULT_BACKEND=redis://host.docker.internal:6379/0 \
  -e REFRAME_OFFLINE_MODE=true \
  -v reframe-media:/data/media \
  reframe-allinone
```

This runs **both** the API and Celery worker in one container via `scripts/entrypoint-allinone.sh`.

**Required env vars (minimum)**

- `DATABASE_URL` (or `REFRAME_DATABASE__URL`)
- `MEDIA_ROOT` (or `REFRAME_MEDIA_ROOT`)
- `BROKER_URL`
- `RESULT_BACKEND`

**Optional env vars**

- `REFRAME_OFFLINE_MODE=true` to prevent using any cloud providers.
- `OPENAI_API_KEY`, `GROQ_API_KEY` for optional providers (not used when offline mode is enabled).
