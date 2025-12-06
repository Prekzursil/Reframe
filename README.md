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

It’s inspired by tools like Clipify (AI shorts from long videos), Subs AI (multi‑backend Whisper UI), and pyVideoTrans (translation + dubbing pipeline). :contentReference[oaicite:0]{index=0}  

---

## Feature Overview

**Core v1 feature set**

- **AI Shorts Maker**
  - Input: local file or URL (YouTube / generic, via `yt-dlp`).
  - Modes:
    - *Auto interesting segments*: LLM ranks transcript chunks and picks top N moments. :contentReference[oaicite:1]{index=1}  
    - *Prompt‑guided*: “Find all moments where I talk about pricing” etc.
  - Control: min/max clip length, number of clips, aspect ratio (9:16, 1:1, 16:9).
  - Output: rendered shorts (with or without burnt subtitles) + .srt/.ass + JSON metadata.

- **Caption & Translation**
  - Long‑form captioning with **word‑level timestamps** (via whisper‑timestamped / faster‑whisper / whisper.cpp). :contentReference[oaicite:2]{index=2}  
  - Export: `.srt`, `.vtt`, `.ass`, TXT.
  - Translate to target language(s) using pluggable translation backends.
  - Optional title/description translation for YouTube/TikTok upload workflows.

- **TikTok‑style Subtitles**
  - Plain captions (classic SRT).
  - **Word‑by‑word highlight** style similar to Descript / CapCut:
    - Bold white text with stroke & outline.
    - Per‑word highlight color that appears exactly while the word is spoken. :contentReference[oaicite:3]{index=3}  
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
  - Speaker diarization for multi‑speaker content (leveraging patterns from Whisper-WebUI & pyannote). :contentReference[oaicite:4]{index=4}  

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

Existing tools like Clipify, pyVideoTrans, and Subs AI are monolithic or semi‑modular; Reframe explicitly separates **media core** from **API/UI**, so you can reuse the core from CLI tools or notebooks. :contentReference[oaicite:5]{index=5}  

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
  - Demonstrate how to support multiple Whisper backends, VAD, and diarization in one UI. :contentReference[oaicite:6]{index=6}  
  - ➜ Borrow config ideas (backend selection, model cache directory, device selection).

- **`pyvideotrans`**
  - Mature translation + dubbing pipeline, including SRT translation and audio re‑synthesis. :contentReference[oaicite:7]{index=7}  
  - ➜ Use as reference for future “full translation + dubbing” mode.

The point of Reframe is to **merge** these ideas into one consistent, testable architecture instead of having many one‑off experiments.

---

## Development Status

Right now this repo is in the **planning / scaffolding** stage:

- This README + `ARCHITECTURE.md` + `goal.md` describe the target system.
- `todo.md` contains a detailed checklist you can turn into issues.
- Initial work is:
  - scaffolding the monorepo,
  - wiring minimal FastAPI + worker + single “transcribe video → SRT” endpoint,
  - creating a simple “upload video → show subtitles” UI.

---

## Getting Started (planned flow)

Once the initial scaffolding is done, the flow will look like:

```bash
# 1. Start services
docker-compose up --build

# 2. API will run on http://localhost:8000
# 3. Web UI will run on http://localhost:5173 (or similar)
