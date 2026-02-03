Here’s a first-pass project plan plus the four markdown docs you asked for (README, ARCHITECTURE, goal, TODO). You can copy‑paste each block into its own file.

I’m calling the project **Reframe** (working title: *AI Media Toolkit*), but you can rename it easily.

---

````markdown
<!-- README.md -->

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

- **“Utilities” (future)**
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
````

In development, you’ll:

* Run FastAPI directly with `uvicorn apps.api.main:app --reload`.
* Start the worker with `celery -A services.worker worker -l info`.
* Run the React dev server with `npm run dev` in `apps/web`.

Exact commands are listed in `todo.md` once the layout is finalized.

---

## Roadmap

See [`todo.md`](./todo.md) for the detailed roadmap, grouped by:

* Project & Infra
* Media Core
* AI Shorts Maker
* Captioning & Translation
* Subtitle Styling
* SRT & Utilities
* Frontend UX
* Packaging & Distribution
* Observability & Testing

---

## License / Credits

Licensing TBD (MIT or Apache‑2 would keep things flexible), but the project is heavily **inspired by and will likely reuse ideas from**:

* Clipify ([GitHub][1])
* Subs AI ([GitHub][2])
* pyVideoTrans ([GitHub][3])
* The original `video-subtitles-generator` (Descript‑style subtitles)
* Your own `ai-short-maker` and `long_to_shorts_app` experiments.

Make sure to respect the original licenses of the code you copy or vendor in.

````

---

```markdown
<!-- ARCHITECTURE.md -->

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
````

---

## 3. Core Concepts & Data Models

### 3.1 Job

Represents a long‑running processing task.

Fields (conceptual):

* `id: UUID`
* `type: Literal["shorts", "caption", "srt_translate", "merge_av"]`
* `status: Pending | Running | Completed | Failed | Cancelled`
* `input_media_ids: List[UUID]`
* `output_media_ids: List[UUID]`
* `params: dict` (serialized settings)
* `progress: float` (0–1)
* `logs: List[JobLogEntry]`
* `created_at`, `updated_at`

Jobs are created via API endpoints and executed by Celery workers.

### 3.2 MediaAsset

Represents a video/audio file or generated artifact.

* `id: UUID`
* `type: video | audio | srt | ass | vtt | json`
* `path: str` (relative to media root)
* `meta: dict` (codec info, length, language, etc.)
* `created_at`

### 3.3 Transcript & Subtitles

Standard internal representation:

```python
class Word(BaseModel):
    text: str
    start: float
    end: float
    confidence: float | None = None

class SubtitleLine(BaseModel):
    text: str
    start: float
    end: float
    words: list[Word]
```

* Output from **transcription** is `list[Word]`.
* `SubtitleBuilder` groups words into `SubtitleLine`s with configurable:

  * max chars per line,
  * max words per line,
  * max line duration,
  * max gap between words.

This follows the strategy used in tools like video‑subtitles‑generator (grouping word‑level timestamps into line‑level subtitles before rendering). ([GitHub][4])

### 3.4 SubtitleStyle

Defines styling for plain and TikTok‑style subtitles:

```python
class SubtitleStyle(BaseModel):
    font_family: str
    font_size: int
    text_color: str          # hex
    highlight_color: str     # hex
    stroke_color: str
    stroke_width: int
    outline_color: str
    outline_width: int
    shadow_color: str
    shadow_offset: int
    position: Literal["bottom", "top", "center"]
    alignment: Literal["center", "left", "right"]
```

---

## 4. Pipelines

### 4.1 Shorts Maker Pipeline

**Use case:** Turn a long video into N sharable shorts with subtitles.

**Steps:**

1. **Ingest**

   * Frontend uploads a file or submits a URL.
   * API downloads remote URLs via `yt-dlp` and stores as `MediaAsset`.

2. **Transcribe**

   * Worker chooses STT backend (`whisper`, `faster-whisper`, `whisper.cpp`) based on config.
   * Produces `List[Word]` plus detected language.
   * Strategy similar to Subs AI / Whisper-WebUI multi‑backend support. ([GitHub][2])

3. **Segment & Rank**

   * Build candidate segments by sliding over the timeline with windows (e.g. 15–90 seconds).
   * For each candidate:

     * Collect words & approximate emotion/structure features.
     * Send context + snippet to an LLM (Groq/OpenAI/etc.) with a scoring prompt:

       * *“Rate how strong this is as a standalone short (1–10) and justify briefly.”*
   * Select top N candidates subject to min/max clip length & minimum score.
   * This mirrors the approach described in “How I Built an AI‑Powered YouTube Shorts Generator”. ([Vitalii Honchar][5])

4. **Clip Extraction**

   * Use FFmpeg to cut the video into selected segments.
   * Optionally reframe to 9:16 / 1:1 with crop/blur background.

5. **Subtitles (optional)**

   * Build `SubtitleLine`s from word timestamps per clip.
   * Choose style:

     * Plain SRT (no burn‑in).
     * Burnt‑in plain text.
     * Burnt‑in TikTok‑style word highlight (MoviePy).

6. **Export**

   * For each clip:

     * Save video file.
     * Save SRT/ASS.
     * Save JSON with metadata (title, language, transcript, chosen score).
   * Update `Job` with progress & asset references.

---

### 4.2 Caption & Translation Pipeline

**Use case:** Full‑length captions & translation for a long video/podcast.

1. **Transcribe**

   * As in Shorts pipeline but usually with a larger model or more accurate settings.
   * Optionally apply VAD or BGM separation for clearer speech (pattern from Whisper-WebUI). ([GitHub][4])

2. **Subtitle Grouping**

   * `SubtitleBuilder` groups words into lines with user‑configurable rules.
   * Export `.srt`, `.vtt`, `.ass`.

3. **Translate (optional)**

   * Subtitle translation:

     * Parse SRT lines.
     * Call translation backend per line or batched.
     * Keep original timings.
   * Transcript translation:

     * For long content, chunk by paragraphs to keep context.
   * Backends can include:

     * Cloud APIs (DeepL, Google Translate, etc.).
     * Local models (e.g., Argos Translate, NLLB/M2M100 via HuggingFace). ([pyVideoTrans][6])

4. **Burn‑In (optional)**

   * Use MoviePy or FFmpeg `subtitles` filter to burn SRT/ASS onto video.

---

### 4.3 TikTok‑Style Highlight Subtitles

**Objective:** Word‑by‑word highlighting synced to speech.

Implementation pattern (inspired by `video-subtitles-generator`):

1. Start from `SubtitleLine` with `words` and `start/end`.
2. For each line:

   * Calculate the width of each word via a temporary `TextClip`.
   * Position the line at bottom center by summing word widths.
3. Build layers:

   * **Shadow/outline layer** – duplicate text at multiple offsets for deep outline.
   * **Base text layer** – white (or configurable) text visible for the whole line duration.
   * **Highlight layer** – per‑word `TextClip`s:

     * `set_start(word.start)`
     * `set_duration(word.end - word.start)`
     * `color = highlight_color`.
4. Composite all clips onto the video or a colored background.
5. Export high‑quality H.264/H.265 with audio.

This architecture gives you the Descript/CapCut‑style karaoke effect with fine control over stroke, shadow, and color.

---

### 4.4 SRT / Subtitle Translator

* API endpoint accepts:

  * SRT/ASS file,
  * source & target language,
  * options (bilingual output, extra formatting).
* Worker:

  1. Parses file into `SubtitleLine`s.
  2. Groups text into batches for efficient translation.
  3. Calls translation backend.
  4. Reconstructs SRT/ASS, preserving timings and formatting tags where possible.
* Advanced options:

  * Keep original + translated stacked or side‑by‑side.
  * Apply length constraints to avoid overflow.

---

### 4.5 Video / Audio Merger

Simple but very useful utility:

* Inputs:

  * Video file.
  * External audio file.
  * Options: start offset, duck original audio, normalize loudness.
* Implementation:

  * Use FFmpeg `-i video -i audio -filter_complex` to:

    * Align audio,
    * Mix (`amix`) with ducking,
    * Normalize (`loudnorm`),
    * Replace audio track if desired.
* Output:

  * New video with updated audio track.
  * Optional SRT/ASS burn‑in in same pass.

---

## 5. API Surface (Draft)

Examples of key endpoints:

* `POST /api/v1/shorts/jobs`

  * Body: `ShortsJobCreate`
  * Response: `Job`

* `POST /api/v1/captions/jobs`

  * Body: `CaptionJobCreate`

* `POST /api/v1/subtitles/translate`

  * Upload SRT/ASS, choose target language(s).

* `POST /api/v1/utilities/merge-av`

  * Video + audio upload + options.

* `GET /api/v1/jobs/{job_id}`

  * Returns `Job` with progress & result assets.

* `GET /api/v1/assets/{asset_id}`

  * Streams file (video/audio/srt/etc.).

* `GET /api/v1/presets/subtitle-styles`

  * List built‑in & user‑defined styles.

---

## 6. Extensibility

Reframe should be easy to extend:

* **New tools** are just new Celery tasks + API endpoints using `media-core`.
* **New STT backends** implement a `Transcriber` interface:

  * `transcribe(path, model, language) -> list[Word]`
* **New translation backends** implement a `Translator` interface:

  * `translate(texts: list[str], src: str, tgt: str) -> list[str]`
* **New subtitle styles** are configs; UI simply exposes them via sliders/pickers.

This mirrors how Subs AI and pyVideoTrans plug in multiple backends under a single interface. ([GitHub][2])

---

## 7. Deployment Modes

1. **Local Desktop (default)**

   * Everything runs on the user’s machine.
   * GPU acceleration when available.
   * No auth, simple file‑based storage.

2. **Local Web Server**

   * Run in Docker on a machine with GPU.
   * Access via browser over LAN.
   * Optional basic auth.

3. **Hosted / Multi‑User (future)**

   * Swap SQLite with Postgres.
   * Add user accounts, quotas, rate limits.
   * Optionally integrate S3‑style object storage.

---

## 8. Open Questions / Notes

* Which LLM provider to default to (Groq vs OpenAI vs local)?
* GPU vs CPU support matrix (faster‑whisper, whisper.cpp, etc.).
* Amount of configurability exposed in v1 vs hidden behind “Advanced” toggles.
* How to package MoviePy + FFmpeg reliably for Windows/macOS/Linux.

These are tracked as items in `todo.md`.

````

---

```markdown
<!-- goal.md -->

# Reframe – Project Goals

## 1. Vision

Create a **single, local‑first GUI app** that lets creators:

- turn long videos into engaging shorts,
- generate and translate captions,
- apply TikTok‑style word‑highlight subtitles,
- and perform common subtitle/audio utilities,

without juggling a dozen separate scripts and repos.

---

## 2. Primary Use Cases

1. **Long video → a batch of shorts**
   - Podcasters, educators, streamers repurposing 1–3 hour content.
   - Want: 5–20 shorts with good hooks, correct subtitles, and platform‑ready formats.

2. **Full‑length captioning & translation**
   - Make long‑form videos accessible and multilingual.
   - Export SRT/VTT for YouTube or burn‑in subtitles directly.

3. **Stylized subtitles for social**
   - Generate *Descript/CapCut‑style* word‑by‑word highlighted captions in a few clicks.

4. **SRT translation & cleanup**
   - Take existing subtitle files, translate them, keep timing, maybe generate bilingual versions.

5. **Audio replacement / merging**
   - Replace camera audio with a mastered track.
   - Merge translated/dubbed audio back into the original.

---

## 3. Non‑Goals (for now)

- Full, production‑grade video editor (timeline, transitions, color grading).
- Fully automated multi‑platform uploader (YouTube/TikTok API integration).
- Real‑time streaming / live captioning (this is strictly offline/batch for now).
- Deepfake voice cloning – translation/dubbing will initially rely on basic TTS or external tools.

---

## 4. Phase Plan

### Phase 0 – Consolidate & Scaffold

**Goal:** Turn the existing experiments into a unified skeleton.

- Decide & lock in tech stack (FastAPI + Celery + React + media-core).
- Scaffold monorepo (`apps/api`, `apps/web`, `packages/media-core`, `services/worker`, `infra`).
- Port the *simplest* feature end‑to‑end:
  - video upload → transcribe → SRT download.

Success criteria:

- You can run `docker-compose up` and get:
  - API docs at `/docs`,
  - A simple web form to upload a video and get SRT.

---

### Phase 1 – Captions & SRT Translation

**Goal:** Reliable transcription + subtitle translation, no shorts yet.

- Implement:
  - multi‑backend transcription (whisper, faster‑whisper, whisper.cpp),
  - `SubtitleBuilder` with grouping rules,
  - SRT/VTT/ASS export,
  - SRT translator (single → target language).

- Frontend:
  - “Captions & Translate” page with:
    - upload video,
    - choose language & model,
    - progress view,
    - downloadable files list.

Success criteria:

- You can feed in a 30–60 minute video and get usable subtitles + a translated SRT, via the GUI.

---

### Phase 2 – TikTok‑Style Subtitles

**Goal:** Nail the “wow” factor: word‑by‑word highlighting.

- Implement MoviePy‑based renderer with:
  - per‑word highlight overlays,
  - configurable stroke, outline, shadow, colors.
- Add subtitle style presets and a visual preview in the UI.
- Allow exporting:
  - just styled video,
  - and SRT/ASS alongside it.

Success criteria:

- Given a transcript + video, you can generate a vertical video with TikTok‑style captions and tweak style in the GUI.

---

### Phase 3 – AI Shorts Maker

**Goal:** High‑quality shorts from long videos.

- Implement segmentation & ranking:
  - sliding windows over transcript,
  - LLM scoring, with prompt customization.
- Expose parameters:
  - number of clips,
  - min/max duration,
  - aspect ratio,
  - whether to add subtitles & style.
- Integrate job queue & progress UI.

Success criteria:

- Short creators can feed a 1+ hour video and get a batch of shorts with captions in one run.

---

### Phase 4 – Utilities & Polish

**Goal:** Round out the app and make it pleasant to live in.

- Audio/video merge tool.
- SRT editor basics (fix text inline, re‑time lines).
- Preset management (subtitle styles, language presets).
- Desktop packaging (Tauri/Electron).
- Basic logging, error handling, and crash reporting.

Success criteria:

- You can use Reframe as your default “AI subtitle + shorts” toolbox without touching scripts.

---

## 5. Success Metrics

Qualitative:

- You stop switching between your old tools for 80–90% of subtitle + shorts work.
- Generating subtitles or shorts is fast enough to be used in real workflows (minutes, not hours, on typical hardware).

Quantitative (once you’re dogfooding):

- Time from “drop in a long video” to “have a batch of shorts + captions” reduced by at least **3×** vs your current workflow.
- You can run multiple jobs per day without major babysitting.

---

## 6. Guiding Principles

- **Local‑first** by default; no mandatory cloud dependency.
- **Pluggable** for models & APIs (STT, LLM, translation).
- **One mental model**: upload → pick tool → run job → see outputs.
- **Plain data structures** internally (words, lines, clips) so scripts & notebooks can reuse the core easily.
````

---

```markdown
<!-- todo.md -->

# TODO / Roadmap

Below is a structured checklist you can turn into GitHub issues.

---

## 1. Project & Infra

- [ ] Create monorepo layout: `apps/`, `services/`, `packages/`, `infra/`.
- [ ] Add `pyproject.toml` for `packages/media-core` (Poetry or plain pip).
- [ ] Add `apps/api/` with FastAPI skeleton + `main.py`.
- [ ] Add `apps/web/` with React + Vite + TypeScript.
- [ ] Add `services/worker/` with Celery app.
- [ ] Add `infra/docker-compose.yml` for API, worker, Redis, web.
- [ ] Add Dockerfiles: `Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.web`.
- [ ] Add root `.gitignore` for Python, Node, env, media, build artifacts.
- [ ] Add `.env.example`:
  - [ ] API: `DATABASE_URL`, `MEDIA_ROOT`, `BROKER_URL`, `RESULT_BACKEND`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `TRANSLATOR_*`.
  - [ ] Web: `VITE_API_BASE_URL`.
- [ ] Add basic `Makefile` or task runner (`justfile`) for common commands.
- [ ] Add pre‑commit config (ruff/black/isort, eslint/prettier).

---

## 2. Media Core – Transcription

- [ ] Create `packages/media-core/transcribe/__init__.py`.
- [ ] Implement `TranscriptionConfig` (model, language, device, backend).
- [ ] Implement `Word` and `TranscriptionResult` models.
- [ ] Backend: `openai_whisper` (simple baseline).
- [ ] Backend: `faster_whisper` (GPU‑friendly).
- [ ] Backend: `whisper_cpp` integration (via `pywhispercpp` or subprocess).
- [ ] Optional: support `whisper-timestamped` or `whisperX` for more accurate word timings.
- [ ] Normalize outputs to `List[Word]` regardless of backend.
- [ ] Add CLI entrypoint (`python -m media_core.transcribe`) for quick testing.
- [ ] Unit tests: transcription result normalization (words sorted, no overlaps, correct lengths).

---

## 3. Media Core – Subtitle Building

- [ ] Create `packages/media-core/subtitles/builder.py`.
- [ ] Implement `SubtitleLine` model (with `words: list[Word]`).
- [ ] Implement grouping logic:
  - [ ] `max_chars_per_line`,
  - [ ] `max_words_per_line`,
  - [ ] `max_duration`,
  - [ ] `max_gap`.
- [ ] Export to SRT writer.
- [ ] Export to VTT writer.
- [ ] Export to ASS writer (basic).
- [ ] Use `pysubs2` for ASS styling where helpful.
- [ ] Unit tests: grouping for different languages & fast/slow speech.

---

## 4. Media Core – TikTok‑Style Renderer

- [ ] Create `packages/media-core/subtitles/styled.py`.
- [ ] Implement `SubtitleStyle` model (font, colors, stroke, shadow, outline, position).
- [ ] Implement `StyledSubtitleRenderer` using MoviePy:
  - [ ] Function to compute word sizes/positions given frame size.
  - [ ] Base text layer (full line duration).
  - [ ] Shadow/outline layers.
  - [ ] Per‑word highlight `TextClip`s with word‑specific `start/end`.
- [ ] Support variable video resolutions & aspect ratios (auto center).
- [ ] Support vertical (9:16) & horizontal (16:9) layouts.
- [ ] Add a simple “solid background + subtitles only” mode for preview.
- [ ] Provide a few preset styles (e.g. “TikTok default”, “Yellow highlight”, “Clean white”).
- [ ] Integration test: render a 5–10 second sample with 3 lines and verify no crashes.

---

## 5. Media Core – Translation

- [ ] Create `packages/media-core/translate/__init__.py`.
- [ ] Define `Translator` interface:
  - [ ] `translate_batch(texts: list[str], src: str, tgt: str) -> list[str]`.
- [ ] Implement simple cloud translation backend (if you already use one).
- [ ] Implement local/offline backend (e.g., Argos Translate / HF model) where feasible.
- [ ] Implement SRT translator:
  - [ ] Parse SRT → list of `SubtitleLine`.
  - [ ] Batch lines for translation.
  - [ ] Rebuild SRT while preserving timings.
- [ ] Implement bilingual SRT builder (original + translated lines).
- [ ] Unit tests: translation preserves count/order, handles empty lines.

---

## 6. Media Core – Video Editing

- [ ] Create `packages/media-core/video_edit/ffmpeg.py`.
- [ ] Function: `probe_media(path) -> dict` (duration, resolution, codecs).
- [ ] Function: `extract_audio(video_path, audio_path)`.
- [ ] Function: `cut_clip(video_path, start, end, output_path)`.
- [ ] Function: `reframe(video_path, output_path, aspect_ratio, strategy="crop|blur_bg")`.
- [ ] Function: `merge_video_audio(video_path, audio_path, output_path, offset, ducking, normalize)`.
- [ ] Function: `burn_subtitles(video_path, srt_or_ass_path, output_path, extra_filters=None)`.
- [ ] Tests: basic FFmpeg invocation works and outputs exist.

---

## 7. Media Core – Shorts Segmentation

- [ ] Create `packages/media-core/segment/shorts.py`.
- [ ] Define `SegmentCandidate` model (start, end, score, reason, snippet).
- [ ] Implement naive equal‑splits strategy (baseline, from `long_to_shorts_app`).
- [ ] Implement sliding window candidate generator (configurable window size & stride).
- [ ] Implement scoring using simple heuristics (density of keywords, sentence boundaries).
- [ ] Implement LLM scoring backend:
  - [ ] Interface: `score_segments(transcript, candidates, prompt, model)`.
  - [ ] Provider: Groq or OpenAI (whichever you prefer).
- [ ] Implement selector: pick top N segments under min/max duration & non‑overlap rules.
- [ ] Unit tests: segments non‑overlapping, durations within bounds.

---

## 8. Worker Service (Celery)

- [ ] Set up `services/worker/worker.py` with Celery app initialization.
- [ ] Configure broker/result backend via env (Redis by default).
- [ ] Task: `transcribe_video(video_asset_id, config) -> transcription_asset_id`.
- [ ] Task: `generate_captions(video_asset_id, options) -> srt_asset_id`.
- [ ] Task: `translate_subtitles(subtitle_asset_id, options) -> new_subtitle_asset_id`.
- [ ] Task: `render_styled_subtitles(video_asset_id, subtitle_asset_id, style, options) -> video_asset_id`.
- [ ] Task: `generate_shorts(video_asset_id, options) -> list[clip_asset_id]`.
- [ ] Task: `merge_video_audio(video_asset_id, audio_asset_id, options) -> video_asset_id`.
- [ ] Implement job status updates & progress reporting.

---

## 9. API – Core

- [ ] Implement settings management using `pydantic-settings`.
- [ ] Add DB models (SQLModel or SQLAlchemy) for:
  - [ ] `Job`,
  - [ ] `MediaAsset`,
  - [ ] (Optional) `SubtitleStylePreset`.
- [ ] Add migration tooling (Alembic) if using SQLAlchemy.
- [ ] Endpoint: `POST /api/v1/captions/jobs`.
- [ ] Endpoint: `POST /api/v1/subtitles/translate`.
- [ ] Endpoint: `POST /api/v1/shorts/jobs`.
- [ ] Endpoint: `POST /api/v1/utilities/merge-av`.
- [ ] Endpoint: `GET /api/v1/jobs/{job_id}`.
- [ ] Endpoint: `GET /api/v1/jobs` (listing/filtering).
- [ ] Endpoint: `GET /api/v1/assets/{asset_id}` (download).
- [ ] Endpoint: `GET /api/v1/presets/styles`.
- [ ] Add OpenAPI docs with tags & examples.

---

## 10. API – Job Lifecycle & Errors

- [ ] Standardize job statuses & error codes.
- [ ] Add structured error responses (code, message, details).
- [ ] Add background cleanup for orphaned temp files.
- [ ] Add endpoint to cancel a running job (best effort).
- [ ] Add rate limiting for heavy endpoints (optional, later).

---

## 11. Frontend – Shell & Shared

- [ ] Scaffold layout:
  - [ ] Sidebar or top nav with sections: Shorts, Captions, Subtitles, Utilities, Jobs.
  - [ ] Shared header/footer.
- [ ] Add base UI kit (buttons, inputs, selects, modals, toasts).
- [ ] Add global loading spinner and error boundary.
- [ ] Implement typed API client (axios/fetch with TS types).
- [ ] Configure theme (dark/light) with CSS variables or Tailwind.
- [ ] Add simple settings modal (default model, language, output paths, etc.).

---

## 12. Frontend – Captions & Translate

- [ ] Page: **Captions & Translate**.
- [ ] Section: Upload video / dropzone.
- [ ] Form controls:
  - [ ] Source language (auto / manual).
  - [ ] Whisper backend & model selection.
  - [ ] Output formats (SRT/VTT/ASS).
  - [ ] Target language(s) for translation (optional).
- [ ] On submit:
  - [ ] Create caption job via API.
  - [ ] Show job in “Recent jobs” panel with status & progress.
- [ ] When job completes:
  - [ ] Show download buttons for each generated asset.
  - [ ] Preview subtitles in a simple video player if possible.

---

## 13. Frontend – TikTok‑Style Subtitles

- [ ] Page: **Subtitle Styling**.
- [ ] UI:
  - [ ] Upload video OR select an existing `MediaAsset`.
  - [ ] Select subtitles (existing SRT) OR generate from scratch (reusing captions pipeline).
  - [ ] Style editor:
    - [ ] Font family (dropdown).
    - [ ] Font size slider.
    - [ ] Text color picker.
    - [ ] Highlight color picker.
    - [ ] Stroke width slider.
    - [ ] Outline toggle + width slider + color picker.
    - [ ] Shadow toggle + offset slider.
    - [ ] Position & alignment controls.
  - [ ] “Preview 5 seconds” button to render a short preview.
- [ ] “Render full video” button -> creates a styled subtitle job.

---

## 14. Frontend – AI Shorts Maker

- [ ] Page: **Shorts Maker**.
- [ ] Input:
  - [ ] Video upload or URL input.
  - [ ] Number of clips desired.
  - [ ] Min/max clip duration.
  - [ ] Aspect ratio selection.
  - [ ] “Use subtitles” toggle with style selector.
  - [ ] “Prompt to guide selection” textarea.
- [ ] Submit:
  - [ ] Create shorts job.
  - [ ] Show a progress view with steps (transcribe → segment → render).
- [ ] Result view:
  - [ ] Grid of generated clips with:
    - [ ] Thumbnail / GIF.
    - [ ] Duration.
    - [ ] Score.
    - [ ] Download buttons (video + subtitles).
  - [ ] Ability to delete/ignore clips.

---

## 15. Frontend – Utilities (SRT & Merge)

- [ ] Page: **Subtitle Tools**.
  - [ ] SRT upload → translation options → result download.
  - [ ] Bilingual SRT option.
- [ ] Page: **Video / Audio Merge**.
  - [ ] Upload/choose video.
  - [ ] Upload/choose audio.
  - [ ] Controls: offset, ducking, normalize.
  - [ ] Submit → job → result download.

---

## 16. Frontend – Jobs & History

- [ ] Page: **Jobs**.
  - [ ] Table listing with filters (status, type, date).
  - [ ] Each row shows progress bar and link to result view.
- [ ] Job detail:
  - [ ] Show inputs, outputs, logs.
  - [ ] Actions: download all as zip, copy transcript, etc.

---

## 17. Observability & Testing

- [ ] Integrate structured logging on the backend (JSON logs).
- [ ] Log FFmpeg commands and exit codes when processing fails.
- [ ] Add health check endpoint (`/healthz`).
- [ ] Unit tests for media-core modules:
  - [ ] transcribe, subtitles, translate, video_edit, segment.
- [ ] Integration tests:
  - [ ] End‑to‑end “video → SRT” job.
  - [ ] End‑to‑end “video → TikTok‑style rendered” sample.
  - [ ] End‑to‑end “video → shorts with subtitles” with small test video.
- [ ] Frontend tests:
  - [ ] Component tests for forms and job list.
  - [ ] Minimal e2e flow (upload → job complete → download).

---

## 18. Packaging & Distribution

- [ ] Add `Dockerfile` for an “all‑in‑one” image (API + worker) for simple servers.
- [ ] Tauri/Electron:
  - [ ] Decide wrapper (Tauri recommended for performance).
  - [ ] Wire Tauri to run API/worker as child processes or rely on local Docker.
  - [ ] Integrate update mechanism (optional later).
- [ ] Provide example configs for:
  - [ ] Local dev (no GPU),
  - [ ] Local GPU workstation,
  - [ ] Small server deployment.

---

## 19. UX & Polish

- [ ] Add onboarding “wizard” or quick start card on home page.
- [ ] Provide a few sample videos for testing.
- [ ] Add warnings for long jobs (e.g., “this may take ~N minutes on CPU”).
- [ ] Expose only the most important knobs in v1; hide advanced settings in collapsible sections.
- [ ] Add tooltips explaining Whisper backends, models, and trade‑offs.
- [ ] Add “copy command” buttons that show the equivalent CLI for advanced users.

---

## 20. Future / Nice‑to‑Have

- [ ] Speaker diarization integration (pyannote) for speaker‑labeled subtitles.
- [ ] Smart silence trimming (cut dead air before generating shorts).
- [ ] Basic subtitle editor (inline text edit + shift timings).
- [ ] Support for timelines / EDL export.
- [ ] Optional cloud integrations (S3, remote GPU workers).
- [ ] Optional “export upload package” for YouTube/TikTok (title, description, tags).

```

---

If you’d like, next step I can help you:

* adapt the `ai-short-maker` React UI to this new API shape, or
* sketch actual Pydantic models & FastAPI route signatures so you can start coding immediately.

[1]: https://github.com/Automately-Solutions/Clipify?utm_source=chatgpt.com "Clipify: Transform Long Videos into Engaging Short Clips"
[2]: https://github.com/absadiki/subsai?utm_source=chatgpt.com "absadiki/subsai: 🎞️ Subtitles generation tool (Web-UI + ..."
[3]: https://github.com/jianchang512/pyvideotrans?utm_source=chatgpt.com "jianchang512/pyvideotrans: Translate the video from one ..."
[4]: https://github.com/sindresorhus/awesome-whisper?utm_source=chatgpt.com "Awesome list for Whisper — an open-source AI-powered ..."
[5]: https://vitaliihonchar.com/insights/youtube-shorts-creator?utm_source=chatgpt.com "How I Built an AI-Powered YouTube Shorts Generator"
[6]: https://pyvideotrans.com/?utm_source=chatgpt.com "pyVideoTrans-Open Source Video Translation Tool ..."
