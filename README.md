# Reframe — Media Studio

**A local-first desktop video editor that turns long videos into shorts.** Manage your
videos and do AI things to them — make vertical 9:16 shorts (the star), transcribe,
generate/edit/translate subtitles, dub, caption, stabilize shaky footage, mix/duck audio,
trim dead air, detect speakers, and convert formats. Runs **offline** with local models
(faster-whisper + Qwen3-4B via llama.cpp); an optional cloud key buys higher quality when
you want it. **No accounts, no telemetry, no cloud dependency.**

> Reframe ships in two forms from one engine: this **local desktop app** (the focus), and a
> future **hosted platform** (an OpusClip-style paid service) that reuses the same Python
> engine behind a SaaS layer. The platform prototype is preserved on the `prototype/hosted-platform`
> branch + the `snapshot-saas-2026-06-16` tag.

## What it does

| Area | Features |
|------|----------|
| **Short-maker** (the star) | LLM moment-selection → boundary-snap → cut → vertical reframe → captions → export; subtle zoom/punch-in; brand-logo overlay; virality scoring + a feedback flywheel |
| **Reframe** | 9:16 auto-reframe via **verthor** (WSL2/MediaPipe) with an automatic in-sidecar **claudeshorts** (OpenCV/MediaPipe) fallback |
| **Stabilize** *(differentiator)* | camera-shake removal via ffmpeg **vidstab** 2-pass — something OpusClip & peers don't do |
| **Audio** | A/V mix + sidechain **auto-duck** + EBU R128 loudnorm; **silence-trim** dead-air removal |
| **Captions / Subtitles** | generate / edit / translate; **bilingual stacked** subtitles; libass + Remotion karaoke styles; emphasis + Netflix CPS/CPL timing |
| **Speakers** | token-free **diarization** (speaker labels) |
| **Dub / TTS** | multi-engine TTS (Kokoro / Chatterbox / edge-tts) + translation-driven dub |
| **Timeline / Export** | per-video workspace; **EDL/CSV NLE export** (Premiere/DaVinci); **package-for-upload** ZIP |
| **Pipelines** | saved multi-step **recipes** run in one shot; **system health** diagnostics |

## Architecture

- **App:** Electron + React/TypeScript renderer ⇄ a **Python compute sidecar** over **stdio JSON-RPC**.
- **Engine:** `sidecar/media_studio/features/*` are transport-agnostic implementations; `engine.py`
  is the one stable facade; `handlers.py` is the JSON-RPC dispatch. This same engine powers both the
  desktop app and the future hosted platform.
- **Heavy work:** verthor (9:16 reframe, WSL2), ffmpeg/libass (cut/caption/convert/stabilize/mix),
  PySceneDetect (scene cuts). Models are downloaded on demand to the app data dir (never committed).
- **Contract:** [`CONTRACTS.md`](CONTRACTS.md) is the frozen interface.

## Quality

A single lean, deterministic **`quality`** gate (one CI check) enforces: Ruff (lint+format),
Oxlint + Biome (JS/TS), tsc + basedpyright (types), **100% sidecar line+branch coverage** + a
ratcheted renderer floor, Opengrep (SAST), gitleaks (secrets), and osv-scanner (deps). See
[`QUALITY-CHARTER.md`](QUALITY-CHARTER.md).

## Develop

```bash
# sidecar (Python 3.12)
cd sidecar && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]" && .venv/Scripts/python -m pytest

# app (Node 20)
cd app && npm install && npm run dev
```
