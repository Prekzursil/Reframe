# Reframe – Project Goals

## 1. Vision

Create a single, local‑first GUI app that lets creators

- turn long videos into engaging shorts,
- generate and translate captions,
- apply TikTok‑style word‑highlight subtitles,
- and perform common subtitleaudio utilities,

without juggling a dozen separate scripts and repos.

---

## 2. Primary Use Cases

1. Long video → a batch of shorts
   - Podcasters, educators, streamers repurposing 1–3 hour content.
   - Want 5–20 shorts with good hooks, correct subtitles, and platform‑ready formats.

2. Full‑length captioning & translation
   - Make long‑form videos accessible and multilingual.
   - Export SRTVTT for YouTube or burn‑in subtitles directly.

3. Stylized subtitles for social
   - Generate DescriptCapCut‑style word‑by‑word highlighted captions in a few clicks.

4. SRT translation & cleanup
   - Take existing subtitle files, translate them, keep timing, maybe generate bilingual versions.

5. Audio replacement  merging
   - Replace camera audio with a mastered track.
   - Merge translateddubbed audio back into the original.

---

## 3. Non‑Goals (for now)

- Full, production‑grade video editor (timeline, transitions, color grading).
- Fully automated multi‑platform uploader (YouTubeTikTok API integration).
- Real‑time streaming  live captioning (this is strictly offlinebatch for now).
- Deepfake voice cloning – translationdubbing will initially rely on basic TTS or external tools.

---

## 4. Phase Plan

### Phase 0 – Consolidate & Scaffold

Goal Turn the existing experiments into a unified skeleton.

- Decide & lock in tech stack (FastAPI + Celery + React + media-core).
- Scaffold monorepo (`appsapi`, `appsweb`, `packagesmedia-core`, `servicesworker`, `infra`).
- Port the simplest feature end‑to‑end
  - video upload → transcribe → SRT download.

Success criteria

- You can run `docker-compose up` and get
  - API docs at `docs`,
  - A simple web form to upload a video and get SRT.

---

### Phase 1 – Captions & SRT Translation

Goal Reliable transcription + subtitle translation, no shorts yet.

- Implement
  - multi‑backend transcription (whisper, faster‑whisper, whisper.cpp),
  - `SubtitleBuilder` with grouping rules,
  - SRTVTTASS export,
  - SRT translator (single → target language).

- Frontend
  - “Captions & Translate” page with
    - upload video,
    - choose language & model,
    - progress view,
    - downloadable files list.

Success criteria

- You can feed in a 30–60 minute video and get usable subtitles + a translated SRT, via the GUI.

---

### Phase 2 – TikTok‑Style Subtitles

Goal Nail the “wow” factor word‑by‑word highlighting.

- Implement MoviePy‑based renderer with
  - per‑word highlight overlays,
  - configurable stroke, outline, shadow, colors.
- Add subtitle style presets and a visual preview in the UI.
- Allow exporting
  - just styled video,
  - and SRTASS alongside it.

Success criteria

- Given a transcript + video, you can generate a vertical video with TikTok‑style captions and tweak style in the GUI.

---

### Phase 3 – AI Shorts Maker

Goal High‑quality shorts from long videos.

- Implement segmentation & ranking
  - sliding windows over transcript,
  - LLM scoring, with prompt customization.
- Expose parameters
  - number of clips,
  - minmax duration,
  - aspect ratio,
  - whether to add subtitles & style.
- Integrate job queue & progress UI.

Success criteria

- Short creators can feed a 1+ hour video and get a batch of shorts with captions in one run.

---

### Phase 4 – Utilities & Polish

Goal Round out the app and make it pleasant to live in.

- Audiovideo merge tool.
- SRT editor basics (fix text inline, re‑time lines).
- Preset management (subtitle styles, language presets).
- Desktop packaging (TauriElectron).
- Basic logging, error handling, and crash reporting.

Success criteria

- You can use Reframe as your default “AI subtitle + shorts” toolbox without touching scripts.

---

## 5. Success Metrics

Qualitative

- You stop switching between your old tools for 80–90% of subtitle + shorts work.
- Generating subtitles or shorts is fast enough to be used in real workflows (minutes, not hours, on typical hardware).

Quantitative (once you’re dogfooding)

- Time from “drop in a long video” to “have a batch of shorts + captions” reduced by at least 3× vs your current workflow.
- You can run multiple jobs per day without major babysitting.

---

## 6. Guiding Principles

- Local‑first by default; no mandatory cloud dependency.
- Pluggable for models & APIs (STT, LLM, translation).
- One mental model upload → pick tool → run job → see outputs.
- Plain data structures internally (words, lines, clips) so scripts & notebooks can reuse the core easily.
