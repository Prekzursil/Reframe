# Media Studio — Design (v0.1, 2026-06-11)

> **SCOPE CORRECTION (2026-06-11):** This is a **local personal video-manager app**, not a hosted platform.
> The v0.2 "Structural commitments (R1–R8)" below — security invariants (signed weight manifests, OS
> keystore, egress-consent), the SaaS seam, the enforced VRAM-lane scheduler, the 3-tier security posture —
> were design-gate over-reach and are **DESCOPED**. The build follows the lean `PLAN-P1.md`. Keep only
> ordinary correctness (argv-list subprocess, escape ASS cue text, confine file ops). The cloud platform is
> a separate later project.

Working name: **media-studio**. A local, portable (Windows/Mac/Linux) AI media studio. The flagship
SaaS/Opus-clip-grade platform comes later; **this doc is the local app**. Decisions below are locked
from the design grill; sections marked ⏳ await in-flight research.

## 1. Vision & scope (all-in-one)
A desktop app that, fully offline-capable, can:
- **Prompt-driven short-maker** (the star): long video + prompt → AI-picked vertical clips with captions.
- Transcribe (incl. long video), translate, and a full **subtitle suite** (generate/edit/sync/translate/AI-fix/TTS).
- **Subtitle/track management**: rename + relabel (language) tracks, add/remove tracks, burn-in (hardcode) or
  soft multi-track, and **remove** a soft subtitle from a clip (not possible if hardcoded).
- **TTS voiceover/dub**: generate spoken tracks from subtitles in many languages + **animated captions**.
- **Full ffmpeg wrapper** (HandBrake-like): container/codec conversion, aspect ratios, mp3/audio extract, batch.
- **Project-based** with an Aegisub/Subtitle-Edit-style **timeline subtitle editor**.

## 2. Architecture
- **Shell/UI:** Electron (React + a timeline editor). Chosen for the richest editor-UI ecosystem; Node is
  present (also hosts Remotion caption rendering).
- **Compute:** a **Python sidecar** process (FastAPI/JSON-RPC over localhost or stdio) owning all heavy
  work: ffmpeg orchestration, faster-whisper, verthor reframe, mediapipe, translation, TTS, model calls.
- **IPC:** Electron ⇄ sidecar via local HTTP/WebSocket (progress streaming) + a job queue; long jobs run
  in the sidecar with canc... + progress events to the UI.
- **Bundling:** Electron app + a packaged Python runtime (PyInstaller/embeddable) + ffmpeg binary. Ship
  per-OS portable builds. Optional model assets downloaded on first run (keep base installer lean).

## 3. Pluggable AI backend  ⏳ (research wf_24246194-541)
A provider abstraction so EVERY model task supports, interchangeably and per-task:
1. **Local** (Ollama / llama.cpp / OpenAI-compatible local server) — offline, free, shipped.
2. **Free/cheap hosted** (e.g. Groq / Google AI Studio / OpenRouter free tiers) — better quality, ~free.
3. **Cloud flagship** (Claude / GPT) — best quality; default for the future platform.
Tasks routed through it: prompt→segment-selection, subtitle AI-fix/sync, translation. (Transcription =
whisper, separate.) The LLM research will fill: best open model per task, the **flagship-ceiling** (where
cloud materially wins), free-hosting matrix, and the **ship-local default set** (whisper size + LLM that
fits 6GB VRAM). User leans: keep all 3 open with sensible defaults.

## 4. Short-maker pipeline (flagship)
Driven by **prompt + structured controls** (clip count, min/max length, aspect, caption style, language).
1. **Transcribe** (faster-whisper, word-level timestamps; whisperX-style alignment). ⏳ variant from research.
2. **Select** — LLM finds **hooks + complete thoughts**, **scene-aware**, boundaries snapped to sentence ends
   + audio silences + scene cuts (PySceneDetect). Ranks candidates against the prompt + structured controls.
3. **Propose → preview/approve** — N ranked candidate clips shown with preview; user approves / nudges
   boundaries / regenerates before export (no blind auto-export).
4. **Reframe** — **smart default = verthor** (1080×1920, subject-tracked); switchable to claude-shorts.
5. **Caption** — smart default animated style; switchable (see §6).
6. **Export** — per-platform encodes (libx264 default), batch.

## 5. Subtitle suite + timeline editor
- **Generate** subs from audio (whisper) in source language; **translate** to N languages (⏳ model).
- **Timeline editor**: edit text, split/merge/retime cues, drag-sync, waveform reference.
- **AI-fix/sync**: LLM corrects ASR errors + fixes segmentation/timing; forced-alignment for hard sync.
- **Track mgmt**: rename, set language label, add/remove tracks; **burn-in** (libass) or **soft multi-track**
  (mux); **strip** a soft sub from a clip (mux without that stream). Hardcoded subs cannot be removed (noted).
- **Formats**: SRT, ASS/SSA, VTT.

## 6. Reframe + caption engines (both, user-selectable)
- **Reframe:** **verthor** (engine-2, verified — YOLOv11+ByteTrack, GPU, no node) AND **claude-shorts**
  (engine-1 — Remotion crop + built-in karaoke captions, needs node). Already built/recipe'd under
  `D:\tools\reframe`.
- **Captions:** **both** — (a) **libass/ASS via ffmpeg** = fast, lightweight, batch, burn or soft (MVP
  default); (b) **Remotion (React)** = premium animated/kinetic templates (Node already in Electron).

## 7. TTS voiceover/dub  ✅ (research → docs/research/TTS-ENGINES.md)
Generate spoken dub tracks from subtitle text, multilingual, selectable voices, time-aligned to cue timings.
- **Ship-local:** **Kokoro-82M** (Apache-2.0, 8 langs, fast, CPU-OK) = default; **Chatterbox Multilingual 0.5B**
  (MIT, 23 langs, zero-shot voice clone) = premium tier (6GB borderline → FP16/ONNX, bench first). License BLOCKS
  XTTS-v2 (CPML) + F5-TTS weights (CC-BY-NC) for a closed app; **OpenVoice V2** (MIT) = light clone via tone-transfer.
- **Hosted fallback** (same pluggable backend): `edge-tts` (free, no key, 100+ langs, --rate; ToS caveat → personal);
  paid Google Cloud TTS / Deepgram for SaaS.
- **Dub alignment:** per-cue target duration → **two-pass speaking-rate re-synth** (preferred, pitch-safe) →
  ffmpeg `atempo`/`rubberband` time-stretch fallback clamped ±15% → pad trailing silence to the cue. Azure
  duration-conditioned TTS if added. Mirror ThioJoe/Auto-Synced-Translated-Dubs.

## 8. Conversion (ffmpeg wrapper)
One UI over ffmpeg: containers (mp4/mkv/mov/webm), codecs (h264/h265/av1/vp9), aspect/scale presets, audio
extract (mp3/aac/wav/flac), frame-rate, bitrate/CRF, **batch** queue, and the subtitle mux/burn ops from §5.

## 9. Project model
A **project** = source media + derived transcript/subs (all languages) + edits + generated clips + settings,
saved to a project folder (JSON manifest + assets). Enables iterative sub editing and re-export.

## 10. Dependencies (initial)
Electron + React; Python sidecar (FastAPI, faster-whisper, ffmpeg-python/subprocess, mediapipe, verthor,
scenedetect, libass via ffmpeg, a translation model ⏳, a TTS engine ⏳, an LLM client lib); Remotion (Node);
ffmpeg static binary. GPU optional (CUDA) with CPU fallback.

## 11. Phased delivery (within "all-in-one")
- **P1 (vertical slice):** import → transcribe → short-maker (prompt+controls → select → preview → verthor
  reframe → ASS captions → export). Pluggable backend with ONE working provider.
- **P2:** full subtitle suite + timeline editor + translation + track mgmt + conversion wrapper.
- **P3:** Remotion premium captions, claude-shorts engine, TTS voiceover/dub, batch everything.
- **P4 (later, out of scope):** the cloud SaaS platform (Opus-grade).

## 12. Open questions (for the design gate / user)
- Final AI-backend default per task + ship-local model set (⏳ research).
- TTS engine choice + license for shipping (⏳ research).
- Translation: dedicated MT model vs the LLM (⏳ research).
- Electron+Python packaging strategy + model-asset download-on-first-run vs bundled (installer size).
- Project file format + media-asset handling (copy vs reference).

## 13. Risks
- Bundle size (Python + ML + ffmpeg + Node + optional models) → mitigate with download-on-first-run.
- Cross-platform GPU variance (CUDA only on NVIDIA) → robust CPU fallback + clear perf messaging.
- Remotion render cost (headless Chrome) → keep ASS as the fast path; Remotion opt-in.
- Scope (all-in-one) → enforce the P1 vertical slice first to reach usable value.

---

## v0.2 — Design Review Gate #1 resolutions (2026-06-11)
Gate #1 = ITERATE (see `DESIGN-GATE-1.md`). Resolutions below.

### User decisions
- **Long-video prompt→short:** P1 scoped to SHORT/MEDIUM input (local Qwen3-4B + map-reduce); long video =
  labelled "escalation" (hosted), NOT a P1 promise. De-risk with a local-4B selection-quality spike on real
  long/medium video BEFORE the P1 build locks.
- **Local LLM default:** Qwen3-4B (GPU-resident) default; Qwen3-8B opt-in "accuracy mode" (offload).
- **Languages: ALL.** Tiered translation route via the Provider per-task fallback chain: **TranslateGemma-4B**
  (high/mid-resource default) → **Aya-Expanse-8B** (local, low-resource) → **hosted Gemini-Flash/flagship**
  (hardest/RTL/idiom/creative). Same tiering for subtitle-fix on non-major languages.
- **Project files:** reference originals by path (small/instant) + a **Consolidate** command that copies
  assets into the project for portability/archive.

### Structural commitments (R1–R8)
- **IPC = stdio JSON-RPC** (Electron-main ⇄ Python sidecar), NOT a localhost HTTP port. Job = id + persisted
  status + progress-event schema + real cancellation. Sidecar supervised (spawn/health/restart); derived
  assets written atomically (temp+rename).
- **VRAM-aware scheduler with exclusive GPU lanes** — whisper / LLM / verthor never co-resident-OOM; enforced
  (ASR pass → free VRAM → LLM pass), not by convention.
- **Security invariants (must-fix):** (a) model-weight download integrity = SHA-256/signed manifest in the
  signed installer + verify-before-load + safetensors-over-pickle; (b) subprocess argv-list only (no
  shell=True), path canonicalize+confine, validate numeric args, subtitle cue text treated as data
  (escape libass); (c) API keys in the OS secret store, excluded from the shareable project folder;
  (d) egress consent boundary = local-by-default + per-provider first-use consent + persistent
  trains_on_data warning.
- **UI = outcome-based.** Primary control = 3-tier posture **Private-Offline / Free-Better / Best-Cloud**;
  per-task model grid → Advanced. Engines hidden: reframe = smart default + override; captions = style picker
  + "premium animated" toggle (ASS vs Remotion under the hood). Ranked-candidate review = rank + rationale +
  approve/nudge/regenerate/discard (non-destructive). + an Information-Architecture pass (project-centric
  workspace; short-maker = front door; a "quick tools" lane for one-off conversions).
- **Engine interfaces:** one `ReframeEngine` + one `CaptionEngine`. **P1 = verthor + libass ONLY.**
  claude-shorts + Remotion premium captions = ONE shared Node/Remotion subsystem in **P3**.
- **Support matrix:** Tier-1 = RTX 4050 / Windows / CUDA (validated). Mac-Metal / AMD / CPU-only = supported
  but best-effort (honest perf; CPU short-maker = correct-but-slow). First-run model-download subsystem =
  resumable + checksummed (ties to security-a) + mirror fallback + disk preflight + offline-bundle option +
  onboarding (can start on a hosted provider while local models download).
- **Honest SaaS seam:** Provider abstraction + pipeline stages + map-reduce + capability model PORT to the
  later platform; shell + IPC + single-tenant orchestration + local asset store are REPLACED. Add a thin
  asset-store interface (local-fs now); do NOT pre-build multi-tenancy. ffmpeg wrapper = "the media ops the
  suite needs, presets-first," not a HandBrake clone. Chatterbox + 8B-resident = toggle-only, pending on-4050 bench.

### P1 — the vertical slice (acceptance-test gated)
**Build:** import a video → transcribe (whisper large-v3-turbo + word timing) → short-maker (prompt +
structured controls → hook/complete-thought/scene-aware selection via local Qwen3-4B + map-reduce → ranked
candidates → preview/approve/nudge → **verthor** 9:16 reframe → **libass** captions → export) — over the
stdio-JSON-RPC sidecar + VRAM scheduler + Provider abstraction (≥1 local + ≥1 hosted) + the security
invariants + the first-run download subsystem + reference-based projects.
**Acceptance test ("lovable"):** from a ~10-min talk on the Tier-1 machine, ≥3 of 5 proposed clips are
share-worthy without manual re-editing; transcribe→export-3-clips within an agreed time budget on the RTX 4050.
**P1 NON-GOALS (explicit):** timeline subtitle editor, TTS/dub, Remotion premium captions, claude-shorts
engine, full transcode/HandBrake wrapper, multi-tenancy. (All → P2/P3.)
**De-risking spikes before the build locks:** (1) local-4B short-selection quality on real video;
(2) sidecar VRAM-orchestration (whisper→free→LLM sequential) on the 4050.
