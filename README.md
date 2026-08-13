# Reframe — Media Studio

> **Status:** ACTIVE
> Documentation map: [`docs/INDEX.md`](docs/INDEX.md) — a doc not reachable from there
> does not exist. Release history: [`CHANGELOG.md`](CHANGELOG.md). Gate composition:
> [`QUALITY-CHARTER.md`](QUALITY-CHARTER.md).

**A local-first desktop video studio that turns long videos into shorts.** Manage your
library, then do AI things to your footage: make vertical 9:16 shorts (the star),
prompt-driven edits, batch repurposing, transcribe, generate / edit / translate subtitles,
dub, caption, stabilize shaky footage, mix / duck audio, trim dead air, detect speakers,
score moments, and convert formats. Runs **offline** with local models
(faster-whisper + Qwen3-4B via llama.cpp); optional cloud API keys buy higher quality and
multimodal models when you want them. **No accounts, no telemetry, no cloud dependency.**

> **Plug and play.** Download one file from
> [**Releases**](https://github.com/Prekzursil/Reframe/releases), run it, and the app does
> its own first-run setup. Python, ffmpeg, and the render engine are **bundled** — there are
> **no prerequisites to install** by hand.

---

## Download & install (plug-and-play)

Grab the latest from the [**Releases page**](https://github.com/Prekzursil/Reframe/releases)
and pick one:

| Asset | What it is |
|-------|------------|
| `media-studio-<version>-win-x64.exe` | **NSIS installer** — double-click, choose an install dir, then choose what to set up (see below). Gets a Start-menu / desktop shortcut ("Reframe - Media Studio"). Auto-updates in place from here on. |
| `media-studio-<version>-win-x64.zip` | **Portable** — unzip anywhere and run `Reframe - Media Studio.exe`. No install, no admin. |

<!-- Deliberately version-agnostic. `electron-builder.yml` derives the artifact name from
     `app/package.json`, so a hardcoded number here goes stale on every bump — it had been
     sitting at 1.4.1 while package.json read 1.4.2. It would also have been wrong in the
     other direction: the newest PUBLISHED release is v1.4.0 (v1.4.1 is still a Draft and
     there is no v1.4.2 tag), so naming any specific version pointed at an asset a reader
     could not download. Take whatever the Releases page actually offers. -->


**The installer asks once, then first run does the rest automatically.** After the
directory page the installer shows a **component page**:

| Choice | What gets set up now |
|--------|----------------------|
| **Minimum** | The app plus subject tracking, so reframing works right away. |
| **Default** (recommended) | Adds offline transcription — captions, subtitles and search work out of the box. |
| **Full** | Everything up front, including the local AI Director model. |
| **Custom** | Tick the feature packs you want (*Transcription & subtitles*, *AI Director*). |

Whatever you pick is what the app provisions on its first launch — **unattended**, with no
second prompt. Anything you skip still downloads the first time you use it, and you can
change the selection later in **Settings**. Upgrading never re-asks and never re-downloads:
an existing install keeps the profile, models and settings it already has.

The download itself is **slim** (the app + a bundled CPython + ffmpeg + the render engine) —
**no models are bundled in the installer**. On first launch the app downloads the heavier
pieces (ML wheels and the local models your choice implies) into your user data dir
(`%APPDATA%\media-studio`) — resumable and checksummed. Budget a **few GB** of one-time
download depending on which models you enable. **After that it works fully offline.**

You **do not** need Python, Node, ffmpeg, CUDA, or any toolchain installed — everything the
app needs to run is in the package or fetched on first run.

---

## The app: a Hub + 5 AI feature bundles, in a tabbed UI

Reframe is one **AI Provider Hub** (the shared substrate) with **five feature bundles** built
on top, surfaced through a clean top-level **tabbed** interface.

**The Hub** owns everything AI: a curated, capability-aware **model catalog**, **provider /
API-key management**, **multi-key auto-rotation** (jobs don't stall on a free-tier `429`),
live **usage bars**, and one **AI-Job envelope** that gates every cloud call behind explicit
**consent** and a **budget / spend cap**. Local models are always the fallback. The five
bundles — **prompt-driven editing (Director)**, **repurpose**, **intelligence**,
**editing-refine**, and **UX quality-of-life** — all plug into this one substrate, so there
is exactly one place to manage keys, cost, and privacy.

### The rail

The app organises everything into **four destinations plus Settings** (an ARIA tablist; the
active destination is derived from the route, so the rail can never desync). The list below is
derived from the `tabs` array in `app/renderer/src/App.tsx`, which that file declares to be the
SSOT for the rail.

**This section previously described EIGHT tabs** — Library / Make Shorts / Edit / Caption / Export /
Deliver / Director / Settings — and was invalidated by the L5 navigation rebuild (`69665321`).
**Nothing was removed from the product:** four of those eight had two answers in two places
("where do I make a short?", "where do I finish?"), so each old destination became a **mode** of the
destination that owns its job, reached by a small sub-navigation inside it. The mapping is given
below so a reader arriving from the old docs can find what they knew.

| Destination | What it's for | Modes (former top-level tabs) |
|-----|---------------|---------------|
| **Library** | Your video library home. Add videos; opening one routes into **Refine**. | — |
| **Produce** | Both AI paths in one place, because they are the same job — AI proposes, you review. | **Make Shorts** (candidate-driven: AI moment-pick **and** manual-interval shorts → boundary-snap → cut → vertical 9:16 reframe → caption editor → export, plus the produced-Shorts gallery and batch / template repurposing, carrying the interrupted-batch resume badge) · **Director** (prompt-driven: describe an edit, review the storyboard / diff and its cost, then apply real ffmpeg op-engines) |
| **Refine** | The editor for one video. | **Editor** (trim / cut / join, reframe, audio mix / duck / loudnorm, stabilize, transcribe — a preview with a docked timeline and a selection-driven inspector) · **Caption design** (the draggable / resizable caption box over a real frame, cue editing, burn-in vs soft-mux) |
| **Deliver** | Getting files out. | **Finish** (the guarded per-video commit — pick a platform preset, review what will be written, then commit, with determinate progress and a cancel) · **Publish** (cross-video / batch, platform presets, and the pro EDL/CSV hand-off) |
| **Settings** | A sub-tabbed area. `SETTINGS_SECTIONS` in `views/Settings.tsx` is the SSOT for which sub-sections exist — deliberately not re-listed here, because the duplicated list is exactly what rotted last time. | — |

> **Reading `Refine` accurately:** "Editor" does not open on the Workspace directly. `views/Edit.tsx`
> opens on its Task Hub and mounts the Workspace — preview, docked timeline, selection-driven
> inspector — only after a card is picked, or immediately when a remembered hub choice resumes there.
> So the L5 "timeline with zero navigation actions" invariant holds **from the Workspace mount**, not
> from a first open of this destination. That gap is real and tracked as a follow-up.

**Providers & Keys + spend cap.** Keys live **only on your machine** — never transmitted
anywhere but the owning provider, never logged. A persisted, month-keyed **cumulative spend
cap** tracks cloud-AI cost across runs and **hard-blocks** further cloud egress once you hit
your limit, so many small approved runs can't quietly add up.

---

## Features

| Area | Features |
|------|----------|
| **Short-maker** (the star) | LLM moment-selection → boundary-snap → cut → vertical reframe → captions → export; subtle zoom/punch-in; brand-logo overlay; virality scoring + a feedback flywheel |
| **Reframe** | 9:16 auto-reframe that runs **natively — no WSL required**. The in-sidecar **claudeshorts** engine is the default (`auto`), finding faces with a single native **YuNet** detector (`cv2.FaceDetectorYN`, a sha256-pinned ONNX CNN — as of v1.2.0, replacing the old MediaPipe/haar path); **verthor** (WSL2/MediaPipe) is an optional explicit opt-in for higher quality, and **EdgeTAM** is an opt-in torch tracker (`reframeTracker="edgetam"`). **No silent fallback:** an explicit `verthor` (or `edgetam`) request fails loudly when its stack is absent — never silently swapped, never a silent center-crop. The default path **follows a single speaker**; a **HYBRID multi-speaker** engine (per-segment cut / 50-50 split / 3-up composite, shipped in v1.1.0) is an explicit opt-in — see [ROADMAP](docs/ROADMAP.md). |
| **Caption editor** | A draggable / resizable caption box previewed on a real video frame (stored normalised → ASS alignment + margins), a previewable style-template swatch picker (karaoke + premium looks), and per-output subtitle delivery (burn-in / soft track / separate file / none) — defaults persisted in Settings and seeded into every new short. |
| **Director** | prompt-driven edits → storyboard/diff + cost preview → real ffmpeg op-engines |
| **Stabilize** *(differentiator)* | camera-shake removal via ffmpeg **vidstab** 2-pass — something OpusClip & peers don't do |
| **Audio** | A/V mix + sidechain **auto-duck** + EBU R128 loudnorm; **silence-trim** dead-air removal |
| **Captions / Subtitles** | generate / edit / translate; **bilingual stacked** subtitles; libass + Remotion karaoke styles; emphasis + Netflix CPS/CPL timing |
| **Speakers** | token-free **diarization** (speaker labels) |
| **Dub / TTS** | multi-engine TTS (Kokoro / Chatterbox / edge-tts) + translation-driven dub |
| **Timeline / Export** | per-video workspace; **EDL/CSV NLE export** (Premiere/DaVinci); **package-for-upload** ZIP |
| **Intelligence** | **clip recommendations** (rank moments to turn into shorts); **best-frame thumbnails** (auto-pick the strongest frame); **semantic search** over your library (local-first embeddings, cloud only with per-data-type consent) |
| **Pipelines** | saved multi-step **recipes** run in one shot; **system health** diagnostics |

---

## System requirements (honest)

- **OS:** Windows **x64** (Windows 10/11). This release ships Windows installers only.
- **CPU / RAM:** any modern 64-bit machine runs the app and the CPU pipeline; transcription
  and the local LLM are noticeably faster with more cores / RAM.
- **GPU (optional, recommended):** an **NVIDIA GPU + CUDA** accelerates transcription, the
  vision stack, and **Chatterbox** voice-clone TTS. Without a GPU everything still works on
  **CPU** (slower) — there is always a CPU fallback.
- **9:16 reframe:** the default in-process **claudeshorts** reframer runs **natively — no
  setup required** — and detects faces with a single native **YuNet** ONNX model
  (`cv2.FaceDetectorYN`, as of v1.2.0); the high-quality **verthor** path (WSL2 / MediaPipe)
  is an explicit opt-in. The default path **follows a single speaker** — even in a wide or
  two-shot the crop locks onto the dominant/active speaker and tracks them smoothly, never an
  empty studio or the gap between two people. Automatic **multi-speaker switching** (cutting
  between people as they talk) shipped in **v1.1.0** as an explicit opt-in HYBRID engine; see
  the [ROADMAP](docs/ROADMAP.md).
- **Disk / network:** ~**a few GB** of one-time first-run download for ML wheels + the models
  you enable (into `%APPDATA%\media-studio`). **Offline after** the first-run setup.
- **No toolchain needed:** Python, ffmpeg, and the render engine are bundled.

---

## Architecture

- **App:** Electron + React/TypeScript renderer ⇄ a **Python compute sidecar** over **stdio JSON-RPC**.
- **Engine:** `sidecar/media_studio/features/*` are transport-agnostic implementations; `engine.py`
  is the one stable facade; `handlers.py` is the JSON-RPC dispatch. This same engine powers both the
  desktop app and the future hosted platform.
- **Heavy work:** verthor (9:16 reframe, WSL2), ffmpeg/libass (cut/caption/convert/stabilize/mix),
  PySceneDetect (scene cuts). Models are downloaded on demand to the app data dir (never committed).
- **Contract:** [`docs/rpc-contract-v2.md`](docs/rpc-contract-v2.md) is the live interface.
  [`CONTRACTS.md`](CONTRACTS.md) is the original frozen v1 contract and is **superseded**
  — it says so on its own line 3, and this line used to call it "the frozen interface",
  which pointed every new reader at a retired authority.

> Reframe ships from one engine in two forms: this **local desktop app** (the focus), and a
> future **hosted platform** (an OpusClip-style paid service) that reuses the same Python
> engine behind a SaaS layer. The platform prototype is preserved on the
> `prototype/hosted-platform` branch + the `snapshot-saas-2026-06-16` tag.

## Quality

A single lean, deterministic **`quality`** gate (one CI check) enforces: Ruff (lint+format),
Oxlint + Biome (JS/TS), tsc + basedpyright (types), **strict 100% line+branch coverage
everywhere** (sidecar **and** renderer), Opengrep (SAST), gitleaks (secrets), and osv-scanner
(deps). See [`QUALITY-CHARTER.md`](QUALITY-CHARTER.md). A separate **opt-in** E2E suite
(real-pipeline + AI + GUI) runs nightly / on demand and does not gate PRs.

## Develop

```bash
# sidecar (Python 3.12)
cd sidecar && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]" && .venv/Scripts/python -m pytest

# app (Node 20)
cd app && npm install && npm run dev
```

Building the Windows installers (NSIS `.exe` + portable `.zip`) is a multi-step,
network-fetching build documented at the top of [`electron-builder.yml`](electron-builder.yml).
Built artifacts land in `installers/` (gitignored — binaries are never committed; they ship
via GitHub Releases).

See [`CHANGELOG.md`](CHANGELOG.md) for release history.
