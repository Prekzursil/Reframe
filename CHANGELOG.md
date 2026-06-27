# Changelog

All notable changes to Reframe — Media Studio are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] — 2026-06-28

**Reframe v1.0.0 — the first stable release.** A plug-and-play, local-first Windows desktop
video studio that turns long videos into shorts: download one file, run it, and the app does
its own first-run setup (Python, ffmpeg, and the render engine are bundled). Both gates are at
**strict 100% line + branch coverage** (sidecar **and** renderer) and `main` CI is green.

### Added — Five-section information architecture (V1 IA)

- **A clean five-section top-level IA** replaces the old tab set. The app is now organised into
  **Library · Make Shorts · Edit · Director · Settings** (an ARIA tablist whose active section
  is *derived from the route*, so the strip can never desync):
  - **Library** — the video library home; opening a video routes into **Edit** for it.
  - **Make Shorts** — the novice front door / short-maker: **AI moment-pick *and* manual-interval**
    shorts, the single produced-Shorts gallery, and batch / template repurposing (it carries the
    interrupted-batch resume badge).
  - **Edit** — the per-video manual surface (trim / cut / join, reframe, caption editor, audio,
    stabilize, transcribe, export) hosted in the per-video Workspace.
  - **Director** — the prompt-driven AI video-editing panel (storyboard / diff + cost preview →
    real ffmpeg op-engines).
  - **Settings** — Models & System / Providers & Keys / Storage / System Health.

### Added — Caption position & style editor + output options

- **Caption position editor** — a draggable / resizable caption box with a live preview on a
  real video frame, so the caption lands exactly where you place it on the export. The box is
  stored normalised (resolution-independent) and converted to ASS alignment + margins by the
  sidecar; quick Top / Center / Bottom band buttons re-seat it.
- **Subtitle style templates** — a previewable swatch picker (karaoke + the OpusClip-style
  premium looks), each rendered with its real palette / font / box / outline, previewed both
  as swatches and live on the video before processing.
- **Output options in the Output Tray** — subtitle delivery is now a real choice (burn-in /
  soft track / separate file / none) honoured by the export pipeline (burn is no longer
  hard-coded), alongside save cut / save short / save SRT for every combination.
- **Preferences** — a Settings → Caption defaults area persists the default caption style,
  position, subtitle delivery, and language; Make Shorts seeds new clips from it.

### Changed — Framing: native, no-WSL by default + no silent fallback

- **9:16 reframe now runs natively with no WSL required.** The `auto` selector resolves to the
  in-sidecar **claudeshorts** (OpenCV / MediaPipe) engine, so the short-maker needs no WSL by
  default; **verthor** (WSL2 / MediaPipe) is now an *explicit opt-in* for higher quality.
- **No silent fallback.** An explicit `verthor` request fails **loudly** when WSL is absent
  (raising rather than being silently swapped); the `auto` path that does substitute surfaces a
  typed notice in job progress. First-run setup is loud about what it is doing — no quiet
  degradation. The packaging root-cause + a `dataRoot` fallback and a startup self-test landed
  alongside.
- **Single-speaker framing (V1).** Even in a wide / two-shot the crop locks onto the dominant /
  active speaker and tracks them smoothly — never an empty studio or the gap between two people.
  Automatic multi-speaker *switching* remains a V2 roadmap item.

### Security

- **`cloudApiKey` is redacted over the RPC / IPC bridge** — the only RPC-facing settings
  accessor now redacts provider keys so a key can never leak unredacted to the renderer.
- Stopped a silent-caption-erasure path so caption edits are never quietly dropped.

### Coverage / CI

- Strict **100% line + branch coverage** enforced on both the Python sidecar and the
  TypeScript renderer under the single deterministic `quality` CI gate; `main` is green and has
  **0 open issues**.

## [0.1.0] — 2026-06-25

First public release: a plug-and-play, local-first Windows desktop video studio that turns
long videos into shorts. Download the NSIS installer or portable zip from the
[Releases page](https://github.com/Prekzursil/Reframe/releases) — Python, ffmpeg, and the
render engine are bundled, and first run sets up the rest automatically (offline thereafter).

### Highlights

- **AI Provider Hub** — one shared AI substrate for the whole app: a curated, capability-aware
  model catalog; provider / API-key management; **multi-key auto-rotation** so jobs don't
  stall on a free-tier `429`; live per-key usage bars; and a single **AI-Job envelope** that
  gates every cloud call behind explicit consent and a budget. Local models are always the
  always-available fallback; keys stay on your machine and are never logged.
- **Five feature bundles** built on the Hub:
  - **Prompt-driven editing (Director)** — describe an edit, review the storyboard / diff and
    its cost, then apply real ffmpeg op-engines (reframe, zoom/pan, retime, overlay,
    lower-third, remove fillers, translate captions, export).
  - **Repurpose** — batch many sources through one aggregate job, save reusable templates +
    per-platform export presets (TikTok / Reels / Shorts), and resume after an app restart.
  - **Intelligence** — clip recommendations, best-frame thumbnails, and local-first semantic
    search over your library (cloud only with per-data-type consent).
  - **Editing-refine** — caption-cue remapping after silence-trim and related editing
    refinements.
  - **UX quality-of-life** — readiness rollups, onboarding, job-queue and consent affordances.
- **UI redesign + tabbed navigation** — top-level ARIA tablist:
  **Library · Create · Director · Repurpose · Settings**, with the per-video Workspace nested
  under Library (#231).
- **Providers & Keys panel** — add / redact API keys, capability + cost badges, per-key live
  usage bars, and per-data-type consent toggles, all in one place (#231).
- **Monthly cumulative spend cap** — a persisted, month-keyed (UTC) cumulative cost ledger in
  integer cents under the data root; soft/hard caps wired into every cloud-AI egress path so
  many small approved runs can't quietly add up. The hard cap refuses egress past the limit
  (#232).
- **8 audit bug fixes** shipped with the redesign and follow-ups, including: caption-cue
  remap after silence-trim, enforced offline on cloud-AI egress, sidecar exit/error listener
  race guard, race-safe job-store writes, embedder raw-key fix (was redacted → cloud 401),
  reframe auto-engine WSL-absent fallback to claudeshorts, transcribe device/model auto-detect
  + CPU fallback, and Director text-consent gating of the edit plan (no transcript leak).
- **Test harness** — strict 100% line+branch coverage everywhere (sidecar and renderer) under
  one deterministic `quality` CI gate, plus a permanent **opt-in** E2E suite
  (real-pipeline + AI + GUI) that runs nightly / on demand without gating PRs.

### Packaging

- Two Windows x64 artifacts: an **NSIS installer** (`.exe`) and a **portable zip**.
- Slim download (Electron app + bundled CPython 3.12 / 3.14 + ffmpeg + the Remotion render
  engine); heavy ML wheels and chosen models install on first run into `%APPDATA%\media-studio`
  (resumable + checksummed). No external prerequisites.

### Known caveats (honest)

- **First run downloads a few GB** of ML wheels + the models you enable; budget time and disk.
  The app is fully offline only **after** that first-run setup.
- **GPU is optional** — an NVIDIA GPU + CUDA accelerates transcription, the vision stack, and
  Chatterbox voice-clone TTS; without one, everything still runs on CPU (slower).
- **9:16 reframe** uses WSL2 / MediaPipe (verthor) for best quality and auto-falls back to the
  in-process claudeshorts reframer when WSL2 is absent.
- Windows x64 only in this release.
