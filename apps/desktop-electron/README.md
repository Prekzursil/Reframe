# media-studio

A **local, personal video-manager desktop app** — manage your videos and do AI things to them: make vertical
shorts (the star), transcribe, generate/edit/translate subtitles, manage subtitle tracks, and convert formats.
Runs offline with local models (faster-whisper + Qwen3-4B via llama.cpp); an optional cloud key for higher
quality when you want it. **Not** a hosted platform — no accounts, no telemetry, no cloud dependency.

- **Architecture:** Electron + React/TypeScript UI ⇄ Python compute sidecar over **stdio JSON-RPC**.
- **Engines:** verthor (9:16 reframe, WSL2), ffmpeg/libass (cut/caption/convert), PySceneDetect (scene cuts).
- **Contract:** see [`CONTRACTS.md`](CONTRACTS.md) (the build's frozen interface).
- **Plan:** see [`docs/PLAN-P1.md`](docs/PLAN-P1.md). **Design:** [`docs/DESIGN.md`](docs/DESIGN.md).

## Dev (after the build lands)
```
# sidecar
cd sidecar && python -m venv .venv && .venv\Scripts\pip install -e . && .venv\Scripts\pytest
# app
cd app && npm install && npm run dev
```

Status: initial build in progress (scaffold + features authored, then install/run/GPU-verify).
