# P2 INTEGRATION REPORT — media-studio (2026-06-12)

Scope: CONTRACTS.md base + P2 addendum (A2-A8) vs the as-built `app/` + `sidecar/`.
Method: full read of the composition root + every A2 feature lane, plus a **live smoke run** of
`handlers.register_all()` against a temp data dir (real imports, real registry).

## 0. Smoke-run evidence (executed, not inferred)

`register_all(Services(data_dir=<tmp>))` completed with **42 methods** registered and **11 manifest
assets**; duplicate registration raises by design (`protocol.register`, protocol.py:87-91), so a clean
run proves no double-wiring:

- METHODS includes every A2 name: `media.playable`, `media.proxy.start`, `timeline.peaks`,
  `tts.voices`, `tts.sample.add`, `tts.dub.start`, `tracks.audio.list/mux/replace/strip`,
  `job.list`, `job.retry`, `assets.list`, `assets.ensure` (+ extra `assets.cancel`).
- ASSETS: `whisper-large-v3-turbo`, `qwen3-4b-gguf` (day-1), `kokoro-v1.0-onnx`,
  `kokoro-voices-v1.0`, `chatterbox-env` (T2), `translategemma-4b-gguf`, `translategemma-12b-gguf`
  (T3), `chrome-headless-shell-win64` (T4a), `llama-server-cuda`, `llama-server-cuda-cudart`,
  `llama-server-cpu` (T5).

## 1. A2 method-by-method cross-check (UI call site · sidecar registration · schema)

| A2 method | Sidecar registration | UI call site | Schema both sides | Verdict |
|---|---|---|---|---|
| `media.playable` | features/media_compat.py:462 (via handlers.py:806-810) | renderer/views/Workspace.tsx:145; also main-process mstream resolver app/main/main.ts:117 | `{playable, reason?, proxyPath?}` media_compat.py:330-348 = rpc.ts:106-110 | ✅ |
| `media.proxy.start` | media_compat.py:463 | Workspace.tsx:151 (+ onJobDone remount 154-158) | `{jobId}` → done `{path}` media_compat.py:351-371 = rpc.ts:298-299 | ✅ (see M-6: error payload ignored) |
| `timeline.peaks` | features/timeline.py:320 | renderer/features/Timeline.tsx:164 | `{sampleRate:int, peaks:[0..1]}` timeline.py:286-289 = rpc.ts:303-305 | ✅ (see M-5: blocks loop) |
| `tts.voices` | features/tts/__init__.py:101 | renderer/features/Dub.tsx:160 | `{voices:[{id,engine,lang,name}]}` voices.py:5 = rpc.ts:308-310 | ✅ |
| `tts.sample.add` | tts/__init__.py:102 | Dub.tsx:203 | `{sample: VoiceSample}` = rpc.ts:98-103; samples default to `%APPDATA%/media-studio/voices` (voices.py:47-49; handlers passes no override) | ✅ |
| `tts.dub.start` | tts/__init__.py:103 | Dub.tsx:232 | params `{videoId,trackId,engine,voice?,sampleId?,targetLang?}` tts/dub.py:309-336 = rpc.ts:313-321; done `{audioTrack, path}` dub.py:387 | ✅ |
| `tracks.audio.list` | features/tracks_audio.py:552 | Dub.tsx:165 | `{audioTracks:[AudioTrack]}` tracks_audio.py:398-405 = rpc.ts:79-86, 325-326 | ✅ |
| `tracks.audio.mux` | tracks_audio.py:553 | **NONE** (typed client only, rpc.ts:327-333) | `{videoId,path,lang,name,kind}` → `{audioTrack}` tracks_audio.py:407-420 | ⚠️ registered, UI-unreachable (mux happens only internally via `mux_for_dub`, dub.py:379) |
| `tracks.audio.replace` | tracks_audio.py:554 | **NONE** (rpc.ts:334-338 only) | tracks_audio.py:423-425 ✓ | ⚠️ UI-unreachable |
| `tracks.audio.strip` | tracks_audio.py:555 | **NONE** (rpc.ts:339-340 only) | tracks_audio.py:451-453 ✓ | ⚠️ UI-unreachable |
| `shortmaker.export` + `audioTrackId` | handler exists (handlers.py:616-626 → shortmaker.py:586-619) | ShortMaker.tsx:483 sends `captionStyle`/`reframeEngine` (487-488) but **never `audioTrackId`** | client types it (rpc.ts:288) — **sidecar ignores it**: shortmaker.py:595 copies only `("reframeEngine","captionStyle")`; no audio handling anywhere in run_export/_export_one | ❌ A2 line "carry the chosen audio track into clips" UNIMPLEMENTED end-to-end |
| `job.list` | protocol.py:251-256 (built-in) | **NONE** (rpc.ts:354 only; useJob tracks single jobs) | JobInfo jobs.py:157-174 = rpc.ts:139-146 ("queued" mapping ✓) | ⚠️ registered, no consumer |
| `job.retry` | protocol.py:259-298 | App.tsx:22 `registerJobRetry` + retry toast useJob.ts:115-160 | request recording on every job-returning dispatch (protocol.py:188-208; first-write-wins jobs.py:268-291) | ✅ |
| `assets.list` | assets/rpc.py:103 | renderer/features/Assets.tsx:76 | AssetInfo `{name,kind,sizeMB,installed,dest}` manager.py:391-397 = rpc.ts:89-95 | ✅ |
| `assets.ensure` | assets/rpc.py:104 | Assets.tsx:108 | `{names:[str]}` → `{jobId}`; resume (Range/.part, manager.py:78-92) + preflight_disk (manager.py:136, 432) per A2 | ✅ |
| `assets.cancel` | assets/rpc.py:105 | Assets.tsx:140 | thin alias of job.cancel | ⚠️ NOT in the frozen A2 list (additive deviation, documented CONTRACT-NOTE) |

A3 schemas (`AudioTrack`, `JobInfo`, `AssetInfo`, `VoiceSample`, job.done error payload
`{error:{message,type}}` jobs.py:442-445) match field-for-field on both sides.

## 2. Targeted verifications requested

### U5 queue vs direct-start callers — ✅ SAFE
- `JobRegistry.start()` with a free slot spawns **synchronously on the calling thread**
  (jobs.py:302-326 → `_pump` 328-358), so every existing `ctx.jobs.start(handler)` caller
  (handlers.py, media_compat, shortmaker, tts, assets) behaves exactly as P1 when idle.
- Queued-while-cancelled jobs finish CANCELLED without running (jobs.py:341-343, 459-470);
  the pool slot is returned in a `finally` (jobs.py:413-416) so a crashing job can't shrink the pool;
  `job.status` keeps the P1 `"pending"` value while JobInfo maps it to `"queued"` (jobs.py:51-62, 164).
- Residual concerns: (a) **nothing passes `gpu=True`** anywhere (verified by grep), so the
  "gpu serialized to 1" lane never engages — two heavy model jobs can run concurrently under
  `max_workers=2` (rpc.py:54 uses defaults); (b) with 2 slots, a transcribe + dub pair queues
  `media.proxy.start` → the player's proxy build waits behind long jobs (UX stall, not a strand).

### Remotion exe resolution chain — ✅ WIRED end-to-end (but see CRIT-1)
- Supervisor injection: `buildSidecarEnv()` sets `MEDIA_STUDIO_NODE_EXE = process.execPath`
  (app/main/sidecar.ts:118-120) and, when packaged resources exist, `MEDIA_STUDIO_RENDER_JS` +
  `MEDIA_STUDIO_REMOTION_BUNDLE` (sidecar.ts:123-136); the spawn uses it (sidecar.ts:189),
  pre-set user env always wins.
- Engine chains (env → settings → dev fallback) mirror llama-server's: caption_remotion.py:196-233
  (node exe), 236-262 (render.js), 265-292 (bundle), 295-322 (Chrome Headless Shell, optional,
  U4-asset-extracted). `ELECTRON_RUN_AS_NODE=1` set at spawn (caption_remotion.py:404-412).
  Both pipes drained per A6-2 (run_render, 442-517). Chrome zip pinned + registered (109-160).

### T4b claudeshorts fallback — ✅ REACHABLE
- `run_export` resolves the engine ONCE (shortmaker.py:508-515) via `resolve_engine_name`
  (reframe.py:362-384): script-presence + `wsl --status` probe (reframe.py:299-359); on failure
  returns claudeshorts + a typed `reframe.fallback` notice surfaced through `ctx.progress`
  (shortmaker.py:514-515). The UI picker (auto/verthor/claudeshorts, ShortMaker.tsx:143-146)
  flows through both controls and top-level export params (487-488) into settings (shortmaker.py:595).
- Degradation inside claudeshorts is also graceful: mediapipe → cv2 haar → center crop
  (reframe_claudeshorts.py module doc, lines 11-16).

### U4 manifest entries from T2/T3/T4a/T5 — ✅ ALL REGISTERED (proven by the smoke run)
- T2: kokoro.py:59-85 (model + voices), chatterbox.py:67-81 (pinned torch env) — imported via
  `_tts.register` (handlers.py:822, 848-857).
- T3: translation.py:533-565 — side-effect import handlers.py:874.
- T4a: caption_remotion.py:144-160 — side-effect import handlers.py:873.
- T5: tools_resolver.py:348-386 — side-effect import handlers.py:876.
- Ordering safe: `assets.list` reads `manifest.all_assets()` at call time (manager.py:402-404),
  not at registration time.

## 3. Findings (ranked)

### CRIT-1 — `captionStyle` is never consumed: the entire T4a remotion lane is dead code in the live pipeline
- The UI ships a premium style picker (`bold/bounce/clean/karaoke`, engine:"remotion" —
  ShortMaker.tsx:129-136) and sends `captionStyle` both in controls and as a top-level export param
  (ShortMaker.tsx:487).
- The sidecar export handler copies it into settings (shortmaker.py:595-598) — and **nothing reads
  it after that**. Repo-wide grep for `captionStyle` in sidecar: select.py:118 (TypedDict),
  shortmaker.py:595 (the copy). The caption stage `_lazy_caption` (shortmaker.py:184-198) always
  constructs the libass `caption.CaptionEngine` (caption.py:268-295 — **no `style` parameter, no
  engine dispatch**). `RemotionCaptionEngine` is instantiated by no production code; its only live
  reference is the manifest side-effect import (handlers.py:873).
- Effect: every premium style silently renders as classic libass; `'none'` ("No captions",
  ShortMaker.tsx:136) still burns captions (`_export_one` always calls `render_caption`,
  shortmaker.py:447-459). All T4a machinery (render-cli, vendored compositions, Chrome asset,
  the env chain in §2) is built, tested, wired… and unreachable.
- Fix shape: a caption-engine registry mirroring reframe's (`STYLES`→remotion, libass default,
  'none'→skip) consumed inside `_lazy_caption` from `settings["captionStyle"]`.

### HIGH-1 — A2 `shortmaker.export audioTrackId` unimplemented end-to-end
- A2 (CONTRACTS.md:137): "`shortmaker.export` gains OPTIONAL `audioTrackId` (carry the chosen
  audio track into clips)". Sidecar: `ShortMaker.export` ignores it (shortmaker.py:586-619; only
  `reframeEngine`/`captionStyle` whitelisted at 595); `run_export`/`_export_one`/`_lazy_cut` have
  no audio-track mapping (the cut always carries the source's default audio, shortmaker.py:152-170).
  UI: ShortMaker.tsx never offers/sends it (zero occurrences). Only the typed client mentions it
  (rpc.ts:288).
- Effect: after a dub (T2's whole point), exported shorts still carry the ORIGINAL audio; the
  dub→short pipeline is severed at its last hop.

### MED-1 — `tracks.audio.mux/replace/strip` have no UI call sites
- Registered (tracks_audio.py:553-555) and typed (rpc.ts:327-341), but Dub.tsx only calls
  `tracks.audio.list` (Dub.tsx:165). `mux` is reached internally by the dub job (`mux_for_dub`,
  dub.py:379); `replace`/`strip` are reachable by NO code path. The A2 audio-track management
  surface exists on the wire but a user cannot exercise it.

### MED-2 — `job.list` has no consumer
- Built-in registered (protocol.py:251-256), JobInfo metadata backfill works (jobs.py:268-291),
  client typed (rpc.ts:354) — but no renderer component calls it (useJob tracks only jobs it
  started). A jobs panel/queue indicator (the visible payoff of U5's JobInfo work) is absent.

### MED-3 — packaged-runtime dependency gaps (first-run env ≠ dev venv)
- `runtime_setup/requirements-sidecar.txt` omits **`edge-tts`** (only pyproject.toml:23 pins it,
  and pyproject deps are NOT installed by the A7 first-run bootstrap). In a packaged install the
  EdgeTTS engine import fails at dub time (edgetts.py:87-88 lazy import), while `tts.voices` still
  advertises the builtin edge voice subset (edgetts.py:40 — no import needed): users can select
  voices that cannot synthesize.
- **`mediapipe`** is pinned nowhere (not in requirements-sidecar.txt, not an env asset) → the
  claudeshorts engine always degrades to haar/center crop in packaged installs, and the
  `__main__._preimport_native_modules` entries for `mediapipe` (and `aiohttp`, also unpinned)
  (__main__.py:57-65) are no-ops there. Degradation is graceful but silent quality loss.

### MED-4 — long direct-return handlers block the single RPC dispatch thread
- `serve()` dispatches sequentially on the stdin thread (rpc.py:128+ / handle_line). First
  `timeline.peaks` on a long video decodes the FULL audio track synchronously (timeline.py:285),
  `tracks.strip` remuxes the whole file (handlers.py:396-415), `tracks.audio.mux/replace/strip`
  run full ffmpeg passes (tracks_audio.py:368-386). While any of these runs, EVERY rpc call from
  the UI stalls (job notifications still flow; new requests don't). Contract types these as
  direct-return, but the UX cost on multi-GB sources is real; consider job-backed variants or a
  dispatch worker.

### LOW-1 — `assets.cancel` is an extra method not in the frozen A2 registry
(assets/rpc.py:105, Assets.tsx:140). Additive + documented, but A2 says "register exactly these".

### LOW-2 — Workspace proxy completion ignores the job.done ERROR payload
Workspace.tsx:154-158 clears the note and remounts the Player on ANY matching `job.done`,
including `{error:{...}}` — a failed proxy build presents as a (still broken) player with no message.

### LOW-3 — gpu lane unused (see §2/U5): no caller tags `gpu=True`; heavy-model serialization rests
solely on ModelRunner's own lifecycle.

## 4. What is solidly DONE
- Composition root registers all 42 methods, idempotence enforced; `__main__` preimports updated
  per A6-1; failure surfacing via job.done error payload uniform (jobs.py:434-445).
- U5 pool: backward-compatible, FIFO, queued-cancel, slot-leak-proof; retry/record machinery
  correct including the first-write-wins guard for retry-of-retry.
- Remotion runtime chain (supervisor env → engine resolution → ELECTRON_RUN_AS_NODE) complete.
- T4b registry + automatic typed-notice fallback complete and consumed by run_export + UI picker.
- U4 manifest complete across T2/T3/T4a/T5 with pinned URLs/reqs, detect probes, resume+preflight.
- Dub pipeline honors the A4 batched recipe: translate-ALL → free MT (`_DubTranslator.free` stops
  the shared llama server, handlers.py:711-717) → synth-ALL; result muxed + persisted as AudioTrack.
- U1/U2/U3 surfaces mounted: Player + mstream proxy resolver (main.ts:104-117), dialog/drop path
  bridges (preload.ts:45-75), toast/useJob with retry wiring (App.tsx:22).
