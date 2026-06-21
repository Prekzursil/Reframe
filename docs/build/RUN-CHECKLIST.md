# media-studio — RUN CHECKLIST (install · run · verify) — P2 edition (2026-06-12)

Exact, copy-pasteable steps to install dependencies, launch the app + sidecar, and verify the
GPU/model path. Windows / PowerShell. Paths absolute where it matters.

> **Status:** the composition root EXISTS (`media_studio/__main__.py` → `handlers.register_all()`
> → **42 methods** registered, verified live). The P1-era warning about `METHOD_NOT_FOUND` is
> obsolete. Current suite state: sidecar 1089/1091, UI 299/302 — the 5 failures and the remaining
> wiring gaps are in `docs/build/P2-COMPLETENESS-REPORT.md` (read it with this).

---

## 0. Prerequisites (one-time, host machine)

- **Windows 11**, PowerShell 7+. **Python 3.12** via `py -3.12` (`build\check-python.ps1` asserts).
- **Node.js 18+** + npm.
- **ffmpeg + ffprobe** on `PATH` (or `settings.ffmpegPath` / env `MEDIA_STUDIO_FFMPEG`/`_FFPROBE`).
  Resolution order: settings → env → bundled (`media_studio/resources/bin`) → PATH (`ffmpeg.py`).
- **NVIDIA GPU + CUDA runtime** for fast whisper + the llama.cpp CUDA server (CPU fallbacks exist).
- **WSL2 + verthor** ONLY if you want the verthor reframe lane — otherwise the claude-shorts
  engine is the automatic fallback (typed notice). Bootstrap: `build\wsl-verthor-bootstrap.ps1`.
- **llama-server**: `D:\tools\llama-cpp-cuda\llama-server.exe` works as the dev default; a fresh
  machine instead resolves through `tools_resolver` (settings.llamaServerPath → env
  `MEDIA_STUDIO_LLAMA_SERVER` → `%APPDATA%\media-studio\tools\` via `assets.ensure` → dev path).

## 1. Sidecar (Python compute process)

```powershell
cd C:\Users\Prekzursil\source\media-studio\sidecar

# Venv exists already (.venv, Python 3.12.10) with the heavy stack IN PLACE:
#   faster-whisper 1.2.1 / ctranslate2 4.8.0 / scenedetect 0.7 / opencv 4.13 /
#   onnxruntime 1.26.0 / av 17.1 / huggingface_hub / httpx
#   + the NVIDIA wheels ALREADY INSTALLED: nvidia-cublas-cu12, nvidia-cudnn-cu12,
#     nvidia-cuda-nvrtc-cu12  (GPU ctranslate2/onnxruntime paths — do not remove).
# Fresh machine: py -3.12 -m venv .venv ; .venv\Scripts\pip install -e .[dev]
#   then install the runtime pins: .venv\Scripts\pip install -r runtime_setup\requirements-sidecar.txt

# >>> NEW P2 deps NOT yet in the venv — install these (T2 TTS + T4b reframe): <<<
.venv\Scripts\pip install kokoro-onnx==0.4.9 edge-tts==7.0.0
#   (edge-tts pulls aiohttp; both are already in __main__'s native pre-import list)
.venv\Scripts\pip install mediapipe          # T4b claudeshorts face-detect backend
#   ⚠ pin it once chosen and ADD to runtime_setup\requirements-sidecar.txt (currently missing).
#   ⚠ pin conflict to reconcile: pyproject.toml says onnxruntime==1.20.1, the venv +
#     requirements-sidecar.txt say 1.26.0 — do NOT let `pip install -e .` downgrade it.

# Run the suite (offline; every heavy seam mocked):
.venv\Scripts\python -m pytest -q     # expect 2 known failures (see P2-COMPLETENESS-REPORT §7)
```

### Sanity-check the assembled sidecar by hand (no Electron)

```powershell
# IMPORTANT: launch `media_studio` (assembled), NOT `media_studio.rpc` (bare core).
'{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}' | .venv\Scripts\python -m media_studio
'{"jsonrpc":"2.0","id":2,"method":"library.list","params":{}}' | .venv\Scripts\python -m media_studio
# Both answer; assets/tts/timeline/media/tracks.audio/job.list are all registered (42 methods).
```

## 2. Render CLI (T4a Remotion captions) — NEW, REQUIRED for premium styles

The Python `RemotionCaptionEngine` spawns `render-cli/dist/render.js` under the Electron exe
(`ELECTRON_RUN_AS_NODE=1`); compositions are pre-bundled. **Neither exists until you build them:**

```powershell
cd C:\Users\Prekzursil\source\media-studio\app
npm install                      # app deps (electron, vite, react, vitest)
npm run render-cli:install       # render-cli's OWN node_modules (remotion 4.0.422 pinned)
npm run render-cli:bundle        # tsc -> render-cli/dist + @remotion/bundler -> render-cli/out/remotion-bundle
```

Dev resolution then works with zero env vars (engine falls back to the repo paths). Packaged
builds get `MEDIA_STUDIO_RENDER_JS` / `MEDIA_STUDIO_REMOTION_BUNDLE` injected by the supervisor.
**Chrome Headless Shell** downloads via the Assets panel (`assets.ensure(["chrome-headless-shell-win64"])`)
or Remotion self-resolves. NOTE: the export pipeline does not yet ROUTE styles to this engine
(punch-list #2) — build it now so the wiring lands on a working toolchain.

## 3. App (Electron + React)

```powershell
cd C:\Users\Prekzursil\source\media-studio\app
npm run dev
# Supervisor resolves python: MEDIA_STUDIO_PYTHON env -> sidecar\.venv (FOUND automatically) -> py -3.12.
# It launches `-m media_studio` (assembled) and injects MEDIA_STUDIO_NODE_EXE + PIP_EXTRA_INDEX_URL.
npm test          # vitest — expect 3 known failures (stale Workspace tab count + splitAt assertion)
```

⚠ `npm run build` / packaged runs: feature panels are NOT in the production bundle yet
(runtime-variable lazy import — punch-list #3); packaged-mode env injection + first-run bootstrap
are also unwired (punch-list #6). **Dev (`npm run dev`) is the supported path right now.**

## 4. Models & heavy assets — all manifest-driven via the Assets panel (U4)

Open **Workspace → Assets** (or call `assets.ensure`) — downloads have resume + disk preflight:

| Asset | What / where |
|---|---|
| `whisper-large-v3-turbo` | HF snapshot into HF_HOME — same cache faster-whisper reads. |
| `qwen3-4b-gguf` | Pinned Q4_K_M → `%APPDATA%\media-studio\models\qwen3-4b.gguf`; an existing copy (settings.ggufPath/modelsDir) is auto-detected, no re-download. |
| **MT GGUFs (T3) — via assets, not manual:** `translategemma-4b-gguf` (~2.5 GB, tier 1) · `translategemma-12b-gguf` (~7.4 GB, tier 2 SLOW) | pinned HF URLs → `%APPDATA%\media-studio\models\`. The tiered translator + model-identity-aware runner swap them on the one llama lane; tier 3 = hosted (needs `useCloud` + key). |
| `kokoro-v1.0-onnx` + `kokoro-voices-v1.0` | Kokoro TTS weights (onnx + voice embeddings). |
| `chatterbox-env` | **Isolated torch env — DEFERRED TO FIRST USE by design.** Do NOT pre-install; first Chatterbox dub (or explicit ensure) pip-installs `chatterbox-tts==0.1.2 + torch/torchaudio==2.6.0+cu124` into `%APPDATA%\media-studio\envs\chatterbox` (~4 GB; needs the PyTorch index — the supervisor injects `PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124`; `runtime_setup\bootstrap.py --chatterbox` is the equivalent CLI). Torch NEVER enters the main sidecar env. |
| `chrome-headless-shell-win64` | Remotion renderer browser (~160 MB). |
| `llama-server-cuda` + `-cudart` + `-cpu` | llama.cpp builds for machines without `D:\tools` (zips → `bootstrap.py --tools-only` extracts). |

Manual llama-server start is NO LONGER needed — `ModelRunner.start_server()` is wired
(selection, translation tiers, dub MT all start/stop/swap it; whisper evicted first via the lane).

## 5. End-to-end smokes (dev)

1. **Library:** drag-drop a video AND use the native picker (U2). Bad file → typed toast.
2. **Playback (U1):** mp4 plays directly; MKV/HEVC → "building playback proxy…" → plays after the
   proxy job (cached per video). Scrub works (Range protocol).
3. **Transcribe:** Start → progress → transcript persisted (first run downloads whisper).
4. **Timeline (T1):** waveform from `timeline.peaks` (cached), split/merge/retime/drag, undo, Save
   → `subtitles.edit` round-trips.
5. **Translate (T3):** subtitle track → target lang; tiers route local-4B / 12B-offload(SLOW) /
   hosted(ONLINE); model swap visible in logs.
6. **Dub (T2):** Kokoro voice → dub job (translate-all → free MT → synth-all → align ±15% → concat)
   → audition WAV plays in-panel (mstream `dub:` route) → muxed audio track listed. edge-tts =
   ONLINE label; Chatterbox = sample add (10–30 s wav) + first-use env install.
7. **ShortMaker:** select → candidates → export: engine A/B verthor vs claudeshorts (auto-fallback
   notice without WSL). KNOWN GAPS: Remotion styles still render via libass (punch-list #2);
   no audio-track carry (#4); no preview window (#9).
8. **Jobs:** cancel mid-job; failure → toast with reason + Retry; `job.list` via DevTools console
   (`await window.api.rpc('job.list')`) — no panel yet (#10).

## 6. Known seams still needing wiring (pointer)

The five P0/P1 punch-list items in `P2-COMPLETENESS-REPORT.md §8`: green-the-suites fixes,
shortmaker→Remotion routing, production panel bundling, `audioTrackId` carry, packaged-mode
supervisor block. Everything else on this checklist is live today.
