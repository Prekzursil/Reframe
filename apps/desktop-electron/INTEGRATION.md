# apps/desktop-electron — Reframe "Media Studio" (Electron fat client)

This directory is the **fat-client** Reframe desktop app: a local-first,
fully-offline video studio (long video → vertical shorts, transcription,
translation/dub, OpusClip-style karaoke captions, virality scoring) that does
**all heavy media processing on-device**.

- **Stack:** Electron (React + TypeScript, electron-vite) + an embedded **Python
  3.12 compute sidecar** over newline-delimited stdio JSON-RPC. ffmpeg, Whisper
  (faster-whisper), a Qwen GGUF via llama.cpp, kokoro/edge TTS, and a Remotion
  caption renderer all run locally. No API service, no Docker, no runtime network.
- **Two-stage install:** the slim app ships the Electron shell + embeddable
  CPython + ffmpeg + the sidecar source; the heavy ML env + models download on
  first run into a configurable data folder (default next to the app, not
  AppData). See `WIRING-T5.md` + `sidecar/runtime_setup/bootstrap.py`.

## Relationship to `apps/desktop` (Tauri) — RFC, additive

This is an **architectural alternative** to the existing Tauri `apps/desktop`,
which `DESKTOP.md` describes as a *thin shell over the Dockerized API + worker
stack*. `apps/desktop-electron` is the opposite — a self-contained fat client
with no backend dependency, where the reframe/shorts pipeline works end-to-end on
the user's machine. It is added **additively**: the Tauri `apps/desktop` is left
untouched. Whether it supersedes the Tauri shell, the two coexist, or one is
retired is a review decision; this change deletes/modifies nothing existing.

## Layout

| Path | What |
|------|------|
| `app/` | Electron main + preload + React renderer + the Remotion render-cli |
| `sidecar/` | the Python compute sidecar (`media_studio` package) + first-run setup |
| `vendor/remotion-captions/` | caption template registry (12+ OpusClip styles) |
| `build/` | packaging scripts (embeddable-python staging, portable zip, WSL verthor bootstrap) |
| `electron-builder.yml` | two-target Windows packaging (NSIS + portable zip) |
| `CONTRACTS.md`, `WIRING-*.md` | the frozen build contract + per-unit wiring notes |

## Build (Windows)

```
build/python-embed-setup.ps1            # stage embeddable CPython + ffmpeg (network; gitignored)
cd app && npm install && npm run build  # electron-vite -> app/out + Remotion bundle
cd app && npx electron-builder --config ../electron-builder.yml --win
```

Tests: `cd app && npx vitest run` (renderer + main) and `cd sidecar && python -m pytest -q`.

## CI integration status (follow-up)

This app's suites (vitest + pytest) are **not yet wired into the monorepo
quality-zero pipeline**. Wiring them into coverage / Codacy / CodeQL to meet the
`quality-zero-platform` bar is tracked as follow-up to this landing PR; until
then, scope the new path out of the strict gates or mark it allowed-to-fail.
