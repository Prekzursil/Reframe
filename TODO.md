# TODO / Roadmap

---

## 1. Project & Infra

- [x] Create monorepo layout: `apps/`, `services/`, `packages/`, `infra/`.
- [x] Add `pyproject.toml` for `packages/media-core` (Poetry or plain pip).
- [x] Add `apps/api/` with FastAPI skeleton + `main.py`.
- [x] Add `apps/web/` with React + Vite + TypeScript.
- [x] Add `services/worker/` with Celery app.
- [x] Add `infra/docker-compose.yml` for API, worker, Redis, web.
- [x] Add Dockerfiles: `Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.web`.
- [x] Add root `.gitignore` for Python, Node, env, media, build artifacts.
- [x] Add `.env.example`:
  - [x] API: `DATABASE_URL`, `MEDIA_ROOT`, `BROKER_URL`, `RESULT_BACKEND`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `TRANSLATOR_*`.
  - [x] Web: `VITE_API_BASE_URL`.
- [x] Add basic `Makefile` or task runner (`justfile`) for common commands.
- [x] Add pre‑commit config (ruff/black/isort, eslint/prettier).
- [x] Add GitHub Actions CI for API/worker checks and web build.

---

## 2. Media Core – Transcription

- [x] Create `packages/media-core/transcribe/__init__.py`.
- [x] Implement `TranscriptionConfig` (model, language, device, backend).
- [x] Implement `Word` and `TranscriptionResult` models.
- [x] Backend: `openai_whisper` (simple baseline).
- [x] Backend: `faster_whisper` (GPU‑friendly).
- [x] Backend: `whisper_cpp` integration (via `pywhispercpp` or subprocess).
- [x] Optional: support `whisper-timestamped` or `whisperX` for more accurate word timings.
- [x] Normalize outputs to `List[Word]` regardless of backend.
- [x] Add CLI entrypoint (`python -m media_core.transcribe`) for quick testing.
- [x] Unit tests: transcription result normalization (words sorted, no overlaps, correct lengths).
- [x] Make transcribe CLI execute chosen backend (with safe fallback) instead of placeholder.
- [x] Flesh out whisper.cpp / whisper-timestamped execution paths with graceful fallback if deps missing.
- [x] Add optional dependency groups for transcription backends (openai, faster-whisper, whispercpp).

---

## 3. Media Core – Subtitle Building

- [x] Create `packages/media-core/subtitles/builder.py`.
- [x] Implement `SubtitleLine` model (with `words: list[Word]`).
- [x] Implement grouping logic:
  - [x] `max_chars_per_line`,
  - [x] `max_words_per_line`,
  - [x] `max_duration`,
  - [x] `max_gap`.
- [x] Export to SRT writer.
- [x] Export to VTT writer.
- [x] Export to ASS writer (basic).
- [x] Use `pysubs2` for ASS styling where helpful.
- [x] Unit tests: grouping for different languages & fast/slow speech.

---

## 4. Media Core – TikTok‑Style Renderer

- [x] Create `packages/media-core/subtitles/styled.py`.
- [x] Implement `SubtitleStyle` model (font, colors, stroke, shadow, outline, position).
- [x] Implement `StyledSubtitleRenderer` using MoviePy:
  - [x] Function to compute word sizes/positions given frame size.
  - [x] Base text layer (full line duration).
  - [x] Shadow/outline layers.
  - [x] Per‑word highlight `TextClip`s with word‑specific `start/end`.
- [x] Support variable video resolutions & aspect ratios (auto center).
- [x] Support vertical (9:16) & horizontal (16:9) layouts.
- [x] Add a simple “solid background + subtitles only” mode for preview.
- [x] Provide a few preset styles (e.g. “TikTok default”, “Yellow highlight”, “Clean white”).
- [x] Integration test: render a 5–10 second sample with 3 lines and verify no crashes.
- [x] Build actual MoviePy text/highlight rendering; remove plan-only scaffold.

---

## 5. Media Core – Translation

- [x] Create `packages/media-core/translate/__init__.py`.
- [x] Define `Translator` interface:
  - [x] `translate_batch(texts: list[str], src: str, tgt: str) -> list[str]`.
- [x] Implement simple cloud translation backend (if you already use one).
- [x] Implement local/offline backend (e.g., Argos Translate / HF model) where feasible.
- [x] Implement SRT translator:
  - [x] Parse SRT → list of `SubtitleLine`.
  - [x] Batch lines for translation.
  - [x] Rebuild SRT while preserving timings.
- [x] Implement bilingual SRT builder (original + translated lines).
- [x] Unit tests: translation preserves count/order, handles empty lines.
- [x] Add local/offline translator backend (e.g., Argos/HF) and wire into SRT translator.

---

## 6. Media Core – Video Editing

- [x] Create `packages/media-core/video_edit/ffmpeg.py`.
- [x] Function: `probe_media(path) -> dict` (duration, resolution, codecs).
- [x] Function: `extract_audio(video_path, audio_path)`.
- [x] Function: `cut_clip(video_path, start, end, output_path)`.
- [x] Function: `reframe(video_path, output_path, aspect_ratio, strategy="crop|blur_bg")`.
- [x] Function: `merge_video_audio(video_path, audio_path, output_path, offset, ducking, normalize)`.
- [x] Function: `burn_subtitles(video_path, srt_or_ass_path, output_path, extra_filters=None)`.
- [x] Tests: basic FFmpeg invocation works and outputs exist.
- [x] Return ffprobe metadata (duration/resolution/codec) from `probe_media`.
- [x] Add `blur_bg` strategy to `reframe` for blurred letterboxing.

---

## 7. Media Core – Shorts Segmentation

- [x] Create `packages/media-core/segment/shorts.py`.
- [x] Define `SegmentCandidate` model (start, end, score, reason, snippet).
- [x] Implement naive equal‑splits strategy (baseline, from `long_to_shorts_app`).
- [x] Implement sliding window candidate generator (configurable window size & stride).
- [x] Implement scoring using simple heuristics (density of keywords, sentence boundaries).
- [x] Implement LLM scoring backend:
  - [x] Interface: `score_segments(transcript, candidates, prompt, model)`.
  - [x] Provider: Groq or OpenAI (whichever you prefer).
- [x] Implement selector: pick top N segments under min/max duration & non‑overlap rules.
- [x] Unit tests: segments non‑overlapping, durations within bounds.

---

## 8. Worker Service (Celery)

- [x] Set up `services/worker/worker.py` with Celery app initialization.
- [x] Configure broker/result backend via env (Redis by default).
- [x] Task: `transcribe_video(video_asset_id, config) -> transcription_asset_id`.
- [x] Task: `generate_captions(video_asset_id, options) -> srt_asset_id`.
- [x] Task: `translate_subtitles(subtitle_asset_id, options) -> new_subtitle_asset_id`.
- [x] Task: `render_styled_subtitles(video_asset_id, subtitle_asset_id, style, options) -> video_asset_id`.
- [x] Task: `generate_shorts(video_asset_id, options) -> list[clip_asset_id]`.
- [x] Task: `merge_video_audio(video_asset_id, audio_asset_id, options) -> video_asset_id`.
- [x] Implement job status updates & progress reporting.
- [x] Create real `MediaAsset` rows (and stub files) for worker outputs and attach to jobs/clip payloads.

---

## 9. API – Core

- [x] Implement settings management using `pydantic-settings`.
- [x] Add DB models (SQLModel or SQLAlchemy) for:
  - [x] `Job`,
  - [x] `MediaAsset`,
  - [x] (Optional) `SubtitleStylePreset`.
- [x] Add migration tooling (Alembic) if using SQLAlchemy.
- [x] Endpoint: `POST /api/v1/captions/jobs`.
- [x] Endpoint: `POST /api/v1/subtitles/translate`.
- [x] Endpoint: `POST /api/v1/shorts/jobs`.
- [x] Endpoint: `POST /api/v1/utilities/merge-av`.
- [x] Endpoint: `GET /api/v1/jobs/{job_id}`.
- [x] Endpoint: `GET /api/v1/jobs` (listing/filtering).
- [x] Endpoint: `GET /api/v1/assets/{asset_id}` (download).
- [x] Endpoint: `GET /api/v1/presets/styles`.
- [x] Add OpenAPI docs with tags & examples.
- [x] Add asset download endpoint that streams the underlying file (not just metadata).

---

## 10. API – Job Lifecycle & Errors

- [x] Standardize job statuses & error codes.
- [x] Add structured error responses (code, message, details).
- [x] Add background cleanup for orphaned temp files.
- [x] Add endpoint to cancel a running job (best effort).
- [x] Add rate limiting for heavy endpoints (optional, later).
- [x] Return rate limit errors via `ApiError` payloads.
- [x] Add `/utilities/translate-subtitle` endpoint for subtitle tools.
- [x] Store uploads under `/media/tmp` to align with cleanup loop.
 - [x] Wire job creation to Celery tasks and persist status/progress updates.

---

## 11. Frontend – Shell & Shared

- [x] Scaffold layout:
  - [x] Sidebar or top nav with sections: Shorts, Captions, Subtitles, Utilities, Jobs.
  - [x] Shared header/footer.
- [x] Add base UI kit (buttons, inputs, selects, modals, toasts).
- [x] Add global loading spinner and error boundary.
- [x] Implement typed API client (axios/fetch with TS types).
- [x] Configure theme (dark/light) with CSS variables or Tailwind.
- [x] Add simple settings modal (default model, language, output paths, etc.).
- [x] Align shorts job payload with API and fix upload input collisions.
- [x] Point subtitle tools to real `/utilities/translate-subtitle` endpoint.
- [x] Replace shorts mock clip placeholders with backend-driven results.

---

## 12. Frontend – Captions & Translate

- [x] Page: **Captions & Translate**.
- [x] Section: Upload video / dropzone wired to backend.
- [x] Form controls:
  - [x] Source language (auto / manual).
  - [x] Whisper backend & model selection.
  - [x] Output formats (SRT/VTT/ASS).
  - [x] Target language(s) for translation (optional).
- [x] On submit:
  - [x] Create caption job via API.
  - [x] Show job in “Recent jobs” panel with status & progress.
- [x] When job completes:
  - [x] Show download buttons for each generated asset.
  - [x] Preview subtitles in a simple video player if possible.
- [x] Auto-poll caption/translate jobs and surface download/preview when `output_asset_id` becomes available.

---

## 13. Frontend – TikTok‑Style Subtitles

- [x] Page: **Subtitle Styling** (UI exists; flow still incomplete).
- [x] Upload video OR select an existing `MediaAsset` using real asset IDs (uploads now backend-wired).
- [x] Select subtitles (existing SRT) OR generate from captions pipeline when absent (caption job trigger present; still needs reliable output/polling).
- [x] Style editor:
  - [x] Font family (dropdown).
  - [x] Font size slider.
  - [x] Text color picker.
  - [x] Highlight color picker.
  - [x] Stroke width slider.
  - [x] Outline toggle + width slider + color picker.
  - [x] Shadow toggle + offset slider.
  - [x] Position & alignment controls.
  - [x] “Preview 5 seconds” button to trigger job and surface preview asset (depends on backend producing preview).
- [x] “Render full video” button -> create styled subtitle job and display/poll result asset (depends on backend producing asset).
- [x] Show progress/status for styling jobs (polling, errors).
- [x] Auto-generate captions when absent and chain into styling; fetch/present preview/render assets reliably.

---

## 14. Frontend – AI Shorts Maker

- [x] Page: **Shorts Maker** (core UI present; backend integration incomplete).
- [x] Input:
  - [x] Video upload or URL input (uploads now backend-wired).
  - [x] Number of clips desired.
  - [x] Min/max clip duration.
  - [x] Aspect ratio selection.
  - [x] “Use subtitles” toggle with style selector.
  - [x] “Prompt to guide selection” textarea.
- [x] Submit:
  - [x] Create shorts job.
- [x] Show a progress view with dynamic step feedback (progress bar).
- [x] Result view:
  - [x] Render real clip assets from backend (thumbnail/GIF, duration, score).
  - [x] Enable per-clip download buttons (video + subtitles) when backend provides URIs; disable when absent.
  - [x] Ability to delete/ignore clips.
  - [x] Handle empty/failed clip outputs gracefully.
- [x] Generate real GIF/thumbnail previews from clips via FFmpeg (replace placeholder thumbnail asset).

---

## 15. Frontend – Utilities (SRT & Merge)

- [x] Page: **Subtitle Tools**.
  - [x] SRT upload → translation options (backend upload wired).
  - [x] Bilingual SRT option.
  - [x] Result download confirmed with real asset (depends on backend job output wiring).
- [x] Page: **Video / Audio Merge**.
  - [x] Upload/choose video (backend upload wired).
  - [x] Upload/choose audio (backend upload wired).
  - [x] Controls: offset, ducking, normalize.
  - [x] Submit → job → result download (polling present; relies on real assets being produced).
- [x] Poll utilities jobs and fetch output assets for download/preview when ready.

---

## 16. Frontend – Jobs & History

- [x] Page: **Jobs**.
  - [x] Table listing with filters (status, type, date).
  - [x] Each row shows progress bar and link to result view.
- [x] Job detail:
  - [x] Show inputs, outputs, logs.
  - [x] Actions: download all as zip, copy transcript, etc.

---

## 17. Observability & Testing

- [x] Integrate structured logging on the backend (JSON logs).
- [x] Log FFmpeg commands and exit codes when processing fails.
- [x] Add health check endpoint (`/healthz`).
- [x] Unit tests for media-core modules:
  - [x] transcribe, subtitles, translate, video_edit, segment.
- [x] Integration tests:
  - [x] End‑to‑end “video → SRT” job.
  - [x] End‑to‑end “video → TikTok‑style rendered” sample.
  - [x] End‑to‑end “video → shorts with subtitles” with small test video.
- [x] Frontend tests:
  - [x] Component tests for forms and job list.
  - [x] Minimal e2e flow (upload → job complete → download).
- [x] Address `npm audit` moderate vulnerabilities in `apps/web` dependencies.
  - [x] Was: `esbuild <=0.24.2` via Vite; fixed by bumping Vite to v7 (esbuild upgraded).

---

## 18. Packaging & Distribution

- [x] Add `Dockerfile` for an “all‑in‑one” image (API + worker) for simple servers.
- [x] Align `.env.example` env var names with `REFRAME_*` settings (or support unprefixed `DATABASE_URL`/`MEDIA_ROOT` env vars).
- [x] Docker-compose: share/mount `MEDIA_ROOT` volume between API + worker so generated assets are downloadable.
- [x] Document `Dockerfile.allinone` usage + required env vars in README.
- [x] Add `./start.sh` quickstart for Docker Compose (creates `.env` with safe defaults).
- [x] Desktop wrapper (Tauri):
  - [x] Decide wrapper (Tauri recommended for performance).
  - [x] v1: manage the stack via local Docker Compose.
  - [x] Signed updater via GitHub Releases (`latest.json` + signatures).
  - [x] Automate publishing via GitHub Actions (Desktop Release workflow).
  - [x] Desktop UI: add a quick link to open `latest.json` (helps debug updater issues).
  - [x] Desktop UI: add “Copy debug info” (version, bundle type, updater URL, docker/compose status).
- [ ] Desktop: verify updater end-to-end (install old version → update → relaunch) (manual per OS).
  - [x] Script: validate published `latest.json` + release asset URLs.
  - [x] Docs: add end-to-end verification checklist.
  - [x] Desktop: display current app version in UI (helps verify old→new relaunch).
  - [x] Publish two signed desktop releases via tags (`desktop-v0.1.6`, then `desktop-v0.1.7`), so `latest.json` exists.
  - [ ] Windows: install `desktop-v0.1.6`, update to `desktop-v0.1.7`, confirm relaunch + version bump.
  - [ ] macOS: install `desktop-v0.1.6` (aarch64/x64), update to `desktop-v0.1.7`, confirm relaunch + version bump.
  - [ ] Linux: run `desktop-v0.1.6` (AppImage), update to `desktop-v0.1.7`, confirm relaunch + version bump.
- [x] Provide example configs for:
  - [x] Local dev (no GPU),
  - [x] Local GPU workstation,
  - [x] Small server deployment.

---

## 19. UX & Polish

- [x] Add onboarding “wizard” or quick start card on home page.
- [x] Provide a few sample videos for testing.
- [x] Add warnings for long jobs (e.g., “this may take ~N minutes on CPU”).
- [x] Expose only the most important knobs in v1; hide advanced settings in collapsible sections.
- [x] Add tooltips explaining Whisper backends, models, and trade‑offs.
- [x] Add “copy command” buttons that show the equivalent CLI for advanced users.

---

## 20. Future / Nice‑to‑Have

- [x] Speaker diarization integration (pyannote) for speaker‑labeled subtitles.
  - [x] Add media-core diarization config + speaker segment model (offline-default noop).
  - [x] Implement optional pyannote backend wiring in worker captions pipeline (extract audio → diarize → label lines).
  - [x] Docs: explain diarization dependencies (torch/pyannote) + offline-mode behavior.
  - [x] Add UI option to enable speaker labels (optional; advanced).
  - [ ] Validate with a real pyannote run and document expected memory/CPU impact.
    - [x] Add a small benchmark script (`scripts/benchmark_diarization.py`) to run diarization on a sample and print timing + peak RSS.
    - [x] Benchmark script: support `--format md` output for easy doc pasting.
    - [x] Benchmark script: fail fast with a clear error when `HF_TOKEN` is missing for pyannote.
    - [x] Benchmark script: add a Docker helper (`scripts/benchmark_diarization_docker.sh`) to avoid local Torch installs.
    - [ ] Prereq: accept Hugging Face model terms / request access for `pyannote/speaker-diarization-3.1` and set `HF_TOKEN` locally (never commit).
    - [x] Run SpeechBrain benchmark (token-free fallback) and paste results into docs.
    - [ ] Run pyannote benchmark (CPU + GPU if available) and paste results into docs.
- [x] Smart silence trimming (cut dead air before generating shorts).
  - [x] media-core: add ffmpeg `silencedetect` helper (`detect_silence`).
  - [x] Worker: optional `trim_silence` scoring for `tasks.generate_shorts`.
  - [x] Web: expose `trim_silence` toggle + thresholds in Shorts form.
  - [x] Add an integration test with a silent-padding fixture and assert fewer silent segments chosen.
- [x] Basic subtitle editor (inline text edit + shift timings).
  - [x] Web: add a raw subtitle editor (load from asset id → edit → shift timings → re-upload as new asset).
  - [x] Subtitle editor: add a cue table view (per-line edit) + validation (optional).
- [x] Support for timelines / EDL export.
  - [x] Web: export Shorts results as CSV + basic CMX3600-style EDL.
  - [x] Timeline export: support audio tracks + per-clip reel names (optional).
- [x] Optional cloud integrations (S3, remote GPU workers).
  - [x] Define a storage abstraction (`StorageBackend`) and keep local filesystem as default.
  - [x] Add S3-compatible backend (AWS S3 / Cloudflare R2) for assets + bundles (opt-in via env).
  - [x] Worker: support downloading remote input assets (pre-signed URL) into `MEDIA_ROOT/tmp` before processing.
  - [x] API: optional pre-signed download URLs for large assets (avoid proxying through API).
  - [x] Docs: deployment guide for remote storage + remote workers (free-tier friendly defaults).
- [x] Optional “export upload package” for YouTube/TikTok (title, description, tags).

---

## 21. Offline‑First + Real Worker Pipelines (Next)

### Worker: replace placeholders with real processing
- [x] Worker: make `packages/media-core` importable in all runtimes (local dev, Docker worker, all-in-one image).
- [x] Worker: implement `tasks.merge_video_audio` using `media_core.video_edit.ffmpeg.merge_video_audio` (no placeholders).
- [x] Worker: implement `tasks.generate_shorts` using `probe_media` + candidate generation + `cut_clip` (no LLM scoring required initially).
- [x] Worker: implement `tasks.generate_captions` using media-core transcription + subtitle builder; support SRT/VTT/ASS output.
- [x] Worker: implement `tasks.translate_subtitles` using media-core SRT translator (default local/Argos or no-op; optional Groq).
- [x] Worker: implement `tasks.render_styled_subtitles` using ffmpeg/libass subtitle burn-in; support `preview_seconds`.
- [x] Styled subtitles: implement word-by-word highlight (ASS karaoke) to use `highlight_color`.
- [x] Styled subtitles: accept `.vtt` inputs (convert to `.srt`/`.ass`) for render jobs.

### Offline + Groq free-tier (optional)
- [x] Add Groq chat client integration (OpenAI-compatible) for:
  - [x] shorts segment scoring (optional),
  - [x] CloudTranslator (optional),
  - [x] only when `GROQ_API_KEY` is set; otherwise fallback to heuristics/offline.
- [x] Add `REFRAME_OFFLINE_MODE=true` to hard-disable any network-backed providers (including OpenAI API transcription).

### Config + docs correctness
- [x] Fix `.env.example` so `VITE_API_BASE_URL` matches the API client expectation (`/api/v1`) OR make the web client auto-append.
- [x] Make `TranscriptionConfig` default backend offline/cost-safe (no OpenAI API calls by default).
- [x] Clean docs: remove stray `:contentReference[oaicite:*]` markers from `README.md` (and `RAW_PROMPT.md` if still needed).

### CI + fixtures
- [x] CI: install `ffmpeg` in GitHub Actions (Python job) so worker integration tests can exercise real processing paths.
- [x] Add a tiny generated sample video/audio fixture (generated at test time or via script; avoid large binaries).

---

## 22. Next Level (Beta polish + creator workflow)

### Local-first UX (no paid APIs)
- [x] Add a “System status / Dependencies” panel in the web UI (ffmpeg present, whisper backend availability, model cache locations).
- [x] Add scripts to download/manage local models in a predictable cache dir (whisper.cpp + faster-whisper) and document disk sizes.
  - [x] Add `scripts/prefetch_whisper_model.py` (faster-whisper model prefetch).
  - [x] Add whisper.cpp model download helper (ggml) and document placement.
  - [x] Document disk sizes + cache locations for Whisper models.
- [x] Add scripts to download/manage Argos Translate language packs and document supported language pairs.
  - [x] Add `scripts/install_argos_pack.py` (install packs by src/tgt).
  - [x] Document recommended language packs + supported pairs for common workflows.

### Creator workflow (quality + control)
- [x] Add transcript viewer with search + click-to-seek timestamps (no re-run required).
- [x] Add a shorts “segment editor” (adjust start/end, reorder, re-cut selected clips without re-scoring).
- [x] Add per-clip subtitle style overrides + a “batch apply style” action.
- [x] Shorts: generate real per-clip captions by slicing a timed captions asset (SRT/VTT) and shifting to clip time.
- [x] Shorts: optionally auto-render/burn-in subtitles per clip when `use_subtitles=true` (uses chosen preset; stores styled clip URIs in the manifest).

### Reliability & safety
- [x] Add upload limits (max bytes) + content-type validation for `/assets/upload`.
- [x] Add a “delete asset/job” flow + retention policy for `MEDIA_ROOT/tmp`.
- [x] Add job retries with backoff for transient ffmpeg failures (and surface retry attempts in the UI).

### Desktop readiness
- [x] Desktop: add an in-app “Diagnostics” screen (shows backend URLs, ffmpeg detected, worker connectivity, storage backend).

### Optional diarization improvements (free/offline)
- [x] Add an optional SpeechBrain diarization backend (no HF token) as a fallback when pyannote models are unavailable.

---

## 23. Hosted SaaS (Opus Clip‑style) — Productization Roadmap

Goal: offer Reframe as a paid hosted service (multi-tenant web app) while keeping the existing local-first + self-hosted mode.

- [x] Capture a first-pass hosted SaaS roadmap in `ARCHITECTURE.md` + `TODO.md`.

### Foundations (multi-tenancy + security)
- [ ] Add auth for the hosted API (start with a simple JWT/session approach; later consider OAuth/SSO).
- [ ] Add `User` / `Organization` models and enforce job/asset ownership in all API endpoints.
- [ ] Add per-tenant storage prefixes (S3/R2) so all assets live under `{org_id}/...` (supports isolation + lifecycle rules).
- [ ] Add API-side rate limits and abuse protections for expensive endpoints (uploads, rendering, transcription).

### Upload/download at scale
- [ ] Add direct-to-object-storage uploads via pre-signed URLs (avoid proxying large uploads through FastAPI).
- [ ] Add resumable uploads (TUS/S3 multipart) for large videos.
- [ ] Add CDN-backed delivery for public/preview assets (optional) with signed URLs for private outputs.

### Billing + usage metering
- [ ] Define the cost model: what you bill for (minutes processed, GPU-seconds, storage, egress) and what limits exist per plan.
- [ ] Add usage metering tables (per job) and a “usage” page in the UI.
- [ ] Integrate Stripe for subscriptions + seat/org billing + plan enforcement.
- [ ] Add per-plan concurrency limits (e.g., max running jobs) and queueing behavior.

### Worker scaling + reliability
- [ ] Split workers into CPU and GPU pools (routing by job type/backends) and add autoscaling deployment configs.
- [ ] Add job idempotency + dedupe for retry safety (especially for uploads + long-running jobs).
- [ ] Add retention policies for intermediate assets and plan-based retention windows.

### Opus Clip‑style UX
- [ ] Add a “project” abstraction (source video → derived clips, transcripts, styles, exports).
- [ ] Add shareable preview links for clips (signed, time-limited URLs).
- [ ] Add team collaboration features (org members, roles, shared projects) (later).

