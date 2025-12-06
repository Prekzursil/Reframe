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

---

## 10. API – Job Lifecycle & Errors

- [x] Standardize job statuses & error codes.
- [x] Add structured error responses (code, message, details).
- [x] Add background cleanup for orphaned temp files.
- [x] Add endpoint to cancel a running job (best effort).
- [x] Add rate limiting for heavy endpoints (optional, later).

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

---

## 12. Frontend – Captions & Translate

- [x] Page: **Captions & Translate**.
- [x] Section: Upload video / dropzone.
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

---

## 13. Frontend – TikTok‑Style Subtitles

- [x] Page: **Subtitle Styling**.
- [x] UI:
  - [x] Upload video OR select an existing `MediaAsset`.
  - [x] Select subtitles (existing SRT) OR generate from scratch (reusing captions pipeline).
  - [x] Style editor:
    - [x] Font family (dropdown).
    - [x] Font size slider.
    - [x] Text color picker.
    - [x] Highlight color picker.
    - [x] Stroke width slider.
    - [x] Outline toggle + width slider + color picker.
    - [x] Shadow toggle + offset slider.
    - [x] Position & alignment controls.
  - [x] “Preview 5 seconds” button to render a short preview.
- [x] “Render full video” button -> creates a styled subtitle job.

---

## 14. Frontend – AI Shorts Maker

- [x] Page: **Shorts Maker**.
- [x] Input:
  - [x] Video upload or URL input.
  - [x] Number of clips desired.
  - [x] Min/max clip duration.
  - [x] Aspect ratio selection.
  - [x] “Use subtitles” toggle with style selector.
  - [x] “Prompt to guide selection” textarea.
- [x] Submit:
  - [x] Create shorts job.
  - [x] Show a progress view with steps (transcribe → segment → render).
- [x] Result view:
  - [x] Grid of generated clips with:
    - [x] Thumbnail / GIF.
    - [x] Duration.
    - [x] Score.
    - [x] Download buttons (video + subtitles).
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


