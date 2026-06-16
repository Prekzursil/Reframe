# Media Studio — Local App Plan (lean, 2026-06-11)

> **SCOPE CORRECTION (supersedes the platform-scoped v2.1).** This is a **local personal video-manager
> desktop app** the user runs on their own machine — NOT a hosted/SaaS platform. The earlier plan let the
> design-review gate drag in enterprise hardening (signed weight manifests, OS keystore, egress-consent
> boundary, SaaS seam, enforced VRAM-lane subsystem, 3-tier security posture). **All of that is cut.** The
> Opus-grade cloud platform is a separate, later project — do NOT pre-build for it. Basic hygiene stays as
> ordinary correctness (argv-list subprocess so paths-with-spaces work; escape ASS cue text so captions
> render; keep file ops inside the library/project) — not a security program.

**What it is:** a local desktop app to **manage your videos** and do AI things to them — make vertical
shorts (the star), transcribe, generate/edit/translate subtitles, manage subtitle tracks, and convert
formats. Offline-capable with local models; an optional cloud key for higher quality when you want it.

**Stack (kept from the design):** Electron (React + library/editor UI) + a Python sidecar over **stdio
JSON-RPC**; local models = faster-whisper + Qwen3-4B via a managed llama.cpp server (the proven spike
path); verthor for reframe; ffmpeg/libass for cut/caption/convert. GPU optional, CPU fallback.

**Method:** TDD (test-first), pragmatic coverage (meaningful tests per WU, not a 100%-ceremony). Each WU
ends green before the next that depends on it. No `--no-verify`; no force-push.

**Proven already:** the selection recipe — Qwen3-4B + reasoning-on, two-pass, 20–60 s duration-enforced —
caught every iconic moment of a 10-min talk (spike v2, ledger #55). That's the heart of the short-maker.

---

## Phase A — App skeleton

### LA0 — Electron + Python sidecar skeleton
- Monorepo: `app/` (Electron/React) + `sidecar/` (Python); **stdio JSON-RPC** handshake (`ping`/`version`);
  **bundled ffmpeg** resolved by absolute path (not system PATH); dev-run + per-OS build scripts.
- **Done when:** `ping` round-trips both ways; a launchable window on Windows (Tier-1); ffmpeg invoked from
  the bundled path (test).

### LA1 — Job + progress framework
- A simple job model: start → stream progress events → complete/fail; real cancellation; derived files
  written atomically (temp+rename) so a cancel/crash never leaves a half-written asset.
- **Done when:** start→progress→done; cancel mid-job leaves a clean state.

### LA2 — Local model runner (+ optional cloud)
- Run faster-whisper (in-process) and Qwen3-4B (managed **llama.cpp server**, lifecycle owned by the
  sidecar); **load-use-free** pragmatically — only one heavy model resident at a time on 6 GB (free before
  loading the next), CPU fallback if VRAM is short. First-run model download = a simple resumable progress
  (whisper + Qwen3-4B + verthor weights). An **optional** cloud provider (one API key in app settings,
  local-by-default) for higher-quality selection/translation when the user opts in.
- **Done when:** whisper then Qwen3-4B then verthor run sequentially on the 4050 without OOM; local
  selection returns spike-quality output; cloud path only fires when a key is set.

### LA3 — Library / project model
- A **library** of videos (add/list/remove); a **project** = a video (referenced by path) + its derived
  transcript/subtitles/clips + settings, as a versioned JSON manifest; an optional **Consolidate** that
  copies assets in so a project folder is portable. Missing-source detection.
- **Done when:** add a video → open/save round-trips; Consolidate makes the folder relocatable; a moved
  source is reported, not silently broken.

---

## Phase B — Video-manager features

### LB1 — Transcribe
- faster-whisper **large-v3-turbo**, word-level timestamps, language auto-detect; progress + cancel; CPU
  fallback. Output = segment+word JSON (the format the spike proved).
- **Done when:** a fixture clip → expected word-timed transcript; cancel works.

### LB2 — Subtitle suite (generate / edit / translate)
- Generate subs from the transcript (source language); edit cues (text, timing, split/merge/retime);
  **translate** to any language via the provider (LLM); import/export **SRT / ASS / VTT**.
- **Done when:** transcript → SRT/ASS/VTT round-trips; an edited cue persists; a translated track is
  produced in a target language.

### LB3 — Subtitle / track management
- Per video: **rename** a track, set its **language label**, **add / remove** tracks, **burn-in** (libass)
  or **soft-mux** (keep selectable), and **strip** a soft sub from a clip (mux without that stream).
  Hardcoded subs can't be removed (surfaced in UI). Cue text escaped so it can't break the ASS render.
- **Done when:** add/rename/relabel/remove a soft track; burn-in produces hardcoded captions; strip removes
  a soft stream; escaping test passes.

### LB4 — Convert (ffmpeg wrapper)
- One UI over ffmpeg: containers (mp4/mkv/mov/webm), codecs (h264/h265/av1/vp9), aspect/scale presets,
  audio extract (mp3/aac/wav/flac), frame-rate, bitrate/CRF, **batch** queue. argv-list calls (paths with
  spaces work).
- **Done when:** convert a file across container+codec; extract audio; a 2-item batch completes; cancel
  works.

### LB5 — Short-maker (the star)
- Prompt + structured controls (clip count, min/max length, aspect, caption style, language) → the full
  pipeline: **select** (the proven reasoning-on two-pass duration-enforced recipe; map-reduce for medium
  input) → **boundary-snap** (sentence ends from word timing + audio silence + scene cuts via
  PySceneDetect, stay in 20–60 s) → **cut** (ffmpeg, frame-accurate; the clip record keeps its
  `source_start`) → **reframe** (verthor 9:16 1080×1920, the verified from-file recipe) → **captions**
  (libass, re-based to the clip's local t=0, sized for 1080×1920) → **export** (libx264, batch the
  approved clips). Degenerate inputs handled inline: no-speech → "no clips"; zero/too-few candidates →
  reason shown; no valid boundary → drop with reason; verthor finds no subject → center-crop fallback.
- **Done when:** a 10-min talk → ranked candidates incl. the thesis line at 20–60 s (regression test pins
  the spike win); approved candidates export as 9:16 mp4s with synced captions (use a clip starting at
  source t≠0 so a broken caption offset can't pass); controls respected (ask 3 → 3; min-len clamps).

---

## Phase C — UI

### LC1 — App shell (the video manager)
- A **library/manager** home (your videos) → open one into a **workspace** with tabs: **Transcribe ·
  Subtitles · Tracks · Convert · Short-maker**. A simple **Local / Cloud** quality toggle (local by
  default; Cloud only if a key is set). Progress surfaced from LA1 events; smart engine defaults hidden
  behind a style/override, not raw engine names.
- **Done when:** library lists videos; opening one shows the tabs; each tab invokes its sidecar feature;
  Local/Cloud toggle changes routing.

### LC2 — Short-maker review loop
- Ranked candidates with rank + rationale + score → preview → **approve / nudge-boundaries / regenerate /
  discard**, all **non-destructive** (originals recoverable; nudge re-snaps, doesn't re-select; nothing
  auto-exports).
- **Done when:** approve/nudge/discard are non-destructive; nudge stays in 20–60 s; export only on explicit
  approve.

---

## Phase D — Integration

### LD1 — Wire end-to-end + "lovable" check
- Connect the library → workspace → features → short-maker pipeline over the Phase-A runtime.
- **Done when (pragmatic, not a ceremony):** from a ~10-min talk on the 4050, **≥3 of 5 proposed clips are
  share-worthy without manual re-editing**, and transcribe→export-3-clips runs in a reasonable time
  (recorded). Subtitles/tracks/convert each work on a real file end to end.

---

## Order & parallelism
- **Spine:** LA0 → LA1 → LA2 → LB1 → LB5 → LC2 → LD1 (the short-maker path).
- **Parallel once LA1+LA3 land:** LB2 (subtitles), LB3 (tracks), LB4 (convert) are independent features;
  LC1 (shell) can come up alongside the LB features.
- **Lowest residual risk:** LB5's selection (already spiked). **Watch:** LA2 sequential model loading on
  6 GB (validate early); LB5 caption-timing re-base (the t≠0 fixture catches it).

## Later (explicitly NOT now)
TTS voiceover/dub · Remotion premium/kinetic captions · claude-shorts engine · waveform timeline editor ·
the hosted SaaS platform. (Engine interfaces stay single: verthor for reframe, libass for captions.)

## Carry to kickoff
- A "reasonable time" target number for LD1 (set with the per-clip re-encode cost included).
- Electron+Python packaging choice (PyInstaller vs embeddable) — decided empirically in LA0; Mac/Linux
  builds present but Tier-1 = Windows.
