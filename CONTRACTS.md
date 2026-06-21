# media-studio — FROZEN BUILD CONTRACT (read first, do not change)

This is the single source of truth every build agent shares. It defines the directory layout, the IPC
protocol, the data schemas, and the engine interfaces. **Build to this contract exactly.** If something is
underspecified, choose the simplest thing consistent with it and note the assumption in a `# CONTRACT-NOTE:`
comment — do not invent new public method names or schemas.

## 0. What we're building
A **local personal video-manager desktop app** (NOT a hosted platform — no auth, no signed-weight manifests,
no keystore, no egress-consent framework, no multi-tenancy). Electron UI + Python compute sidecar. Features:
manage a library of videos; transcribe; subtitles (generate/edit/translate, SRT/ASS/VTT); subtitle-track
management (rename/relabel/add/remove/burn-in/soft-mux/strip); ffmpeg conversion; and the star — a
prompt-driven **short-maker** (select → boundary-snap → cut → reframe → captions → export). Lean plan:
`docs/PLAN-P1.md`.

## 1. Directory layout (write ONLY in your assigned dir)
```
app/                         # Electron + React + TypeScript (UI)
  package.json  tsconfig.json  electron.vite.config.ts
  main/        main.ts        # app entry, BrowserWindow, sidecar supervisor
               sidecar.ts     # spawn/health/restart the python sidecar; stdio JSON-RPC transport
               ipc.ts         # forward renderer requests <-> sidecar; relay progress notifications
               preload.ts     # contextBridge: window.api.rpc(method, params), window.api.onProgress(cb)
  renderer/    index.html
               src/main.tsx  src/App.tsx
               src/lib/rpc.ts            # typed client over window.api
               src/views/Library.tsx     src/views/Workspace.tsx
               src/features/Transcribe.tsx  Subtitles.tsx  Tracks.tsx  Convert.tsx  ShortMaker.tsx
               src/components/*           # shared UI bits
sidecar/                     # Python 3.12 compute process
  pyproject.toml
  media_studio/
    __init__.py
    rpc.py        # stdio JSON-RPC server: read newline-delimited JSON from stdin, dispatch, write to stdout
    protocol.py   # METHODS registry (name -> handler) + request/response/notification framing
    jobs.py       # Job, JobStatus, progress emit, cooperative cancellation, JobRegistry
    library.py    # Library (add/list/remove) + Project manifest (open/save/consolidate, ref-by-path)
    ffmpeg.py     # resolve bundled ffmpeg/ffprobe; build argv lists; run with progress parsing
    models/
      provider.py # Provider interface (complete/chat) + LocalServerProvider (llama.cpp) + CloudProvider (optional)
      runner.py   # load-use-free model lifecycle: whisper in-proc; llama.cpp server start/stop; one heavy model at a time
    features/
      transcribe.py  subtitles.py  tracks.py  convert.py
      select.py      boundary.py   reframe.py  caption.py  shortmaker.py
    util.py
  tests/          # pytest; mirror module names: test_jobs.py, test_library.py, test_subtitles.py, ...
docs/  spike/      # EXISTING — reference only, do not modify. spike/select.py = the proven selection recipe.
CONTRACTS.md  README.md  .gitignore
```

## 2. IPC protocol — stdio JSON-RPC 2.0, newline-delimited
The sidecar reads one JSON object per line from **stdin** and writes one JSON object per line to **stdout**
(logs go to **stderr** only — never stdout). Requests: `{"jsonrpc":"2.0","id":<int>,"method":<str>,"params":{}}`.
Responses: `{"jsonrpc":"2.0","id":<int>,"result":{}}` or `{"jsonrpc":"2.0","id":<int>,"error":{"code","message"}}`.
Progress = **notification** (no id): `{"jsonrpc":"2.0","method":"job.progress","params":{"jobId","pct","message"}}`.
Job completion for long jobs = a final notification `{"method":"job.done","params":{"jobId","result"}}` OR the
response resolves when done — long jobs return `{"jobId"}` immediately and stream progress, then `job.done`.

### Method registry (the public surface — do not rename)
- `ping()` -> `{"pong":true,"version":str}`
- `library.list()` -> `{"videos":[{id,path,title,addedAt,durationSec,hasTranscript,thumbnailPath}]}`
- `library.add({path})` -> `{video}` ; `library.remove({id})` -> `{ok:true}`
- `library.thumbnail({id})` -> `{thumbnailPath}` (WU-2: idempotent source-video poster under `data_dir/thumbnails/<id>.jpg`)
- `project.open({id})` -> `{project}` ; `project.save({project})` -> `{ok}` ; `project.consolidate({id})` -> `{ok,folder}`
- `transcribe.start({videoId, language?})` -> `{jobId}` ; streams progress ; `job.done.result` = `{transcript}`
- `subtitles.generate({videoId})` -> `{track}` ; `subtitles.edit({trackId, cues})` -> `{track}`
- `subtitles.translate({trackId, targetLang})` -> `{jobId}` -> `{track}` ; `subtitles.export({trackId, format})` -> `{path}` (format: srt|ass|vtt)
- `tracks.list({videoId})` -> `{tracks}` ; `tracks.rename({trackId,name})` ; `tracks.relabel({trackId,lang})`
- `tracks.add({videoId, trackId})` ; `tracks.remove({videoId, trackId})` ; `tracks.burn({videoId, trackId})` -> `{jobId}` -> `{path}` ; `tracks.strip({videoId, trackId})` -> `{path}`
- `convert.start({videoId|path, options})` -> `{jobId}` -> `{path}` ; options = `{container,vcodec,acodec,scale,fps,crf,audioOnly,audioFormat}`
- `convert.batch({items})` -> `{jobId}` -> `{paths}`
- `shortmaker.select({videoId, prompt, controls})` -> `{jobId}` -> `{candidates}` ; controls = `{count,minSec,maxSec,aspect,language,captionStyle}`
- `shortmaker.export({videoId, candidateIds})` -> `{jobId}` -> `{clips:[{path}]}`
- `job.cancel({jobId})` -> `{ok}` ; `job.status({jobId})` -> `{status,pct}`
- `settings.get()` / `settings.set({...})` -> includes `{useCloud:bool, cloudApiKey?, modelsDir, ffmpegPath}` (editing-refinement adds the `captionSpeakerLabels` setting key; the refine tunables are per-call RPC params, not settings — see §A5)

## 3. Data schemas (Python TypedDict / TS interface — keep field names identical both sides)
- **Word** `{text:str, start:float, end:float}` ; **Segment** `{start:float, end:float, text:str, words:[Word]}`
- **Transcript** `{language:str, segments:[Segment], durationSec:float}`
- **Cue** `{index:int, start:float, end:float, text:str}` ; **SubtitleTrack** `{id, lang, name, format, kind:"soft"|"hard", cues:[Cue]}`
- **Candidate** `{rank:int, start:float, end:float, durationSec:float, hook:str, why:str, score:int, sourceStart:float}`
  (`sourceStart` = the clip's start in the ORIGINAL video; captions must subtract it to re-base to the clip's local t=0)
- **Video** `{id, path, title, addedAt, durationSec, hasTranscript, thumbnailPath}` (thumbnailPath is additive, default `""`)
- **Project** `{id, video, transcript?, tracks:[SubtitleTrack], clips:[{candidate, path}], settings}`

## 4. Engine interfaces (exactly ONE impl each in this build)
- `ReframeEngine.reframe(in_path, out_path, aspect="9:16") -> out_path` — sole impl = **verthor** adapter.
  Verthor runs under **WSL2**; invoke its script **FROM A FILE** (`wsl bash <script> <args>`), NEVER pipe a
  script via `tr|bash` (mediapipe consumes stdin and corrupts the script — proven gotcha). Output 1080x1920 h264.
- `CaptionEngine.render(clip_path, cues, out_path, burn=True, width=1080, height=1920) -> out_path` — sole impl
  = **libass via ffmpeg**. Generate ASS sized for width x height; **cue times re-based to the clip (subtract
  sourceStart)**; **escape cue text** (no raw `{`/`}` ASS override injection). burn=True hardcodes; burn=False soft-mux.

## 5. Selection recipe (the short-maker's heart — already proven, port from spike/select.py)
Provider chat call, **reasoning ON** (NO `/no_think`), `temperature 0.4`, two-pass system prompt: (1) state the
talk's thesis + list 6-8 most quotable lines (weight `(Applause)`), find the COMPLETE thought around each;
(2) select N clips, **each 20-60s** (hard), opens on a hook, the single most-quotable line MUST be included.
Strip `<think>...</think>` before JSON parse. Output = `[Candidate]`. `boundary.py` then snaps start/end to
sentence-end (word timing) + audio silence + scene cut (PySceneDetect), staying in 20-60s, never mid-word.

## 6. HARD RULES for every agent (non-negotiable)
- **File scope:** write ONLY under the directory you are assigned. Read CONTRACTS.md + your deps. Do not edit
  `docs/`, `spike/`, or another agent's dir.
- **NO git, NO installs, NO servers, NO GUI, NO network.** Do NOT run `npm install`/`pip install`/`npm run`/
  `electron`/`vite`/`uvicorn`/any long or network command — they hang the workflow. Author code + tests only.
- **Allowed checks (fast, offline):** `python -m py_compile <file>` for Python, `node --check <file>` for plain
  JS. Do not attempt to run pytest/jest (deps aren't installed — the human runs them after).
- **TDD-author:** write the pytest/jest tests alongside each module (they'll be run after install). Pure-logic
  modules (jobs, library, subtitles parse/IO, boundary, caption-ASS-gen, convert-argv, select-prompt-build)
  must have thorough unit tests with NO heavy-ML imports (mock the provider/whisper/verthor at the seam).
- **Subprocess safety as correctness (not security theater):** ffmpeg/wsl calls use **argv lists** (never
  `shell=True`), so paths with spaces work. Escape ASS cue text so captions render.
- **Keep it lean:** no auth, no weight-signing, no keystore, no consent framework, no SaaS abstractions.
- Match the method names + schemas in §2/§3 EXACTLY (both Python and TS sides).

## 7. Stack choices (use these; create the config in the foundation phase)
Electron + electron-vite + React 18 + TypeScript (strict). Python 3.12, pytest, stdlib JSON-RPC (no FastAPI).
ffmpeg/ffprobe = bundled binary resolved by absolute path. faster-whisper (large-v3-turbo). LLM = a managed
llama.cpp **server** (OpenAI-compatible /v1) the sidecar starts/stops; default model Qwen3-4B GGUF.
PySceneDetect for scene cuts. No torch unless verthor's own venv needs it (verthor is its own WSL env).

---

# P2 ADDENDUM (2026-06-12) — frozen for the P2 build. Read WITH the base contract above.
Scope: PLAN-P2.md v2.1 (gate-passed). Where this addendum extends §2/§3/§4/§6/§7, it WINS.

## A2. Method registry additions (names are FROZEN — register exactly these)
- `media.playable({videoId})` -> `{playable:bool, reason?, proxyPath?}`  (codec-driven: remux-safe vs proxy)
- `media.proxy.start({videoId})` -> `{jobId}` -> `{path}`  (h264 720p proxy, cached per video)
- `timeline.peaks({videoId})` -> `{sampleRate:int, peaks:[float 0..1]}`  (cached; invalidated by source mtime/path)
- `tts.voices()` -> `{voices:[{id,engine,lang,name}]}`
- `tts.sample.add({path})` -> `{sample: VoiceSample}` ; samples live in %APPDATA%/media-studio/voices/
- `tts.dub.start({videoId, trackId, engine, voice?, sampleId?, targetLang?})` -> `{jobId}` -> `{audioTrack, path}`
- `tracks.audio.list({videoId})` -> `{audioTracks:[AudioTrack]}`
- `tracks.audio.mux({videoId, path, lang, name, kind})` -> `{audioTrack}`
- `tracks.audio.replace({videoId, audioTrackId, path})` -> `{audioTrack}`
- `tracks.audio.strip({videoId, audioTrackId})` -> `{path}`
- `shortmaker.export` gains OPTIONAL `audioTrackId` (carry the chosen audio track into clips)
- `job.list()` -> `{jobs:[JobInfo]}` ; `job.retry({jobId})` -> `{jobId}` (re-runs from stored request params)
- `assets.list()` -> `{assets:[AssetInfo]}` ; `assets.ensure({names:[str]})` -> `{jobId}` (download/install w/ resume+preflight)

## A3a. Editing-refinement schema additions (2026-06 — additive only; frozen fields unchanged)
These extend base §3. They are **additive**: every previously-frozen field of `Cue`
keeps its name and meaning — only an OPTIONAL field is added.
- `Cue` gains OPTIONAL `speaker?: string` — the diarized speaker label carried onto a
  cue (set on subtitle generate when the transcript was diarized and the
  `captionSpeakerLabels` setting is on). Frozen `index/start/end/text` are unchanged.
  Mirrors `DiarizedSegment = Segment & { speaker?: string }`.
- `RefinePlan` (NEW, internal + wire payload for `refine.preview`/`refine.apply`):
  `{ keeps: [[start:float, end:float], ...],
     stats: { fillersRemoved:int, fillerSeconds:float, silenceRemovedSec:float, keptSec:float } }`.
  `keeps` is the unified keep-list (filler keep-spans ∩ silence keep-spans); `stats`
  is the typed savings block surfaced in the Refine panel.

## A3. Schema additions (field names FROZEN, both Python and TS)
- `AudioTrack {id, lang, name, kind:"original"|"dub", voice?, path}` ; `Project.audioTracks:[AudioTrack]`
- `JobInfo {jobId, feature, label, videoId?, status:"queued"|"running"|"done"|"error"|"cancelled", pct}`
- `AssetInfo {name, kind:"model"|"env"|"tool", sizeMB, installed:bool, dest}`
- `VoiceSample {id, name, path, durationSec}`
- job.done error payload (existing): `{error:{message,type}}` — ALL failures must surface this way.

## A4. Engine interfaces (REPLACES base §4's "exactly one impl"; still exactly THREE interfaces)
- `ReframeEngine.reframe(in,out,aspect)` impls: **verthor** (default, WSL) + **claudeshorts** (MediaPipe/OpenCV crop
  via compute-rect + ffmpeg crop, in-sidecar; ALSO the automatic fallback when WSL/verthor absent — typed notice).
- `CaptionEngine.render(clip,cues,out,style,...)` impls: **libass** (default, fast styles) + **remotion** (premium
  animated: Python engine spawns the render CLI subprocess — the ELECTRON EXE with `ELECTRON_RUN_AS_NODE=1` resolved
  via settings/env injected by the supervisor (chain like llama-server's) — argv + JSON job file; compositions are
  PRE-BUNDLED at app-build time; Chrome Headless Shell registers in assets).
- `TtsEngine.synth(cues, voice, lang, out_wav)` (NEW): **kokoro** (default local — the `kokoro-onnx` build,
  onnxruntime, NEVER the torch pip package) + **edgetts** (hosted, label ONLINE) + **chatterbox** (voice-clone,
  runs in its OWN downloaded env as a subprocess — torch stays OUT of the main sidecar env).
- Dub alignment recipe (FROZEN): per-cue target duration -> rate re-synth -> ffmpeg atempo clamp ±15% -> pad; dub
  pipeline is BATCHED: translate ALL cues -> free MT -> synth ALL cues (never interleave model swaps).

## A5. Editing-refinement settings key + refine RPC params + workspace tab (2026-06)
The editing-refinement bundle adds exactly ONE persisted **settings key** — read via
`settings.get()` / `settings.set({...})` (base §2) — plus a set of per-call **RPC
params** on `refine.preview` / `refine.apply`. They are NOT the same surface: only
`captionSpeakerLabels` lives in the settings store; the refine tunables are passed
per call (from the Refine panel's local state) and are NOT read from any `refine.*`
settings key. All are OPTIONAL; absent → the cited engine default, so behaviour is
unchanged when unset. Existing `removeFillers` / `silenceTrim` / `diarizeBackend`
keep their shortmaker meaning unchanged.

**Settings key** (persisted, read via `settings.get()`):

| Key | Type | Meaning | Default precedent |
|---|---|---|---|
| `captionSpeakerLabels` | bool | when on, subtitle generate prefixes each cue's text with the diarized speaker label (read at `handlers.py` subtitle-generate via `settings.get("captionSpeakerLabels")`; off → cues untouched) | new (mirrors the `captionPolish` flag) |

**`refine.preview` / `refine.apply` call params** (per-call, NOT settings keys —
sent in the RPC `params` payload, read by `refine.py`'s `_plan`; camelCase wire
names, default-applied when the param is absent):

| Param | Type | Meaning | Default applied |
|---|---|---|---|
| `noiseDb` | float | silence-detection threshold (dB) — `refine.py:295`, sent by `Refine.tsx` | `silencetrim.DEFAULT_NOISE_DB` |
| `minSilenceSec` | float | minimum silent-span duration to cut — `refine.py:296`, sent by `Refine.tsx` | `silencetrim.DEFAULT_MIN_SILENCE_SEC` |
| `mergeGapMs` | int | filler-cut merge window (ms) — `refine.py:306`, sent by `Refine.tsx` | `fillers.DEFAULT_MERGE_GAP_MS` |
| `padSec` | float | padding kept around kept spans — `refine.py:307`. Default-only: read from `params` but NOT yet wired through the Refine panel, so in practice it takes the default unless a caller supplies it. | `silencetrim.DEFAULT_PAD_SEC` |
| `fillerSets` | dict | per-language filler-set override (incl. `ro`). **Threaded into `plan_refine(filler_sets=...)`** (`refine.py:308`) — it changes the cut math (which words are removed), not just config. Not currently wired through the Refine panel; supplied directly in `params` when overriding. Absent → `fillers.DEFAULT_SETS`. | `fillers.DEFAULT_SETS` |

**Workspace tab order (`WORKSPACE_TABS`, `app/renderer/src/views/Workspace.tsx`):**
the **Refine** tab (`{ id: 'refine', label: 'Refine' }`) sits in the
system-advanced group **directly after `diarize`** —
`… subtitles, diarize, refine, tracks, convert …`.

## A6. Phase-0 hard lessons (NON-NEGOTIABLE for every agent)
1. **Pre-import natives**: any NEW native module used inside a job (onnxruntime, mediapipe, soundfile, scenedetect,
   cv2) MUST be added to `__main__._preimport_native_modules` — a C-extension first-imported on a job thread
   DEADLOCKS the sidecar (proven). Note your additions in your summary; the wiring agent consolidates.
2. **Drain every subprocess pipe**: never Popen with a PIPE you don't read (proven 29-min freeze). Reuse
   `ffmpeg.run()` or replicate its stderr-drain-thread pattern.
3. **Failures must surface**: long jobs fail via the job.done error payload; never swallow.
4. **argv lists only**; paths with spaces; WSL scripts FROM FILE; escape ASS cue text.
5. No torch in the main sidecar env. Pinned versions for everything entering assets_manifest.

## A7. Runtime/dep additions
- Heavy wheels live in `%APPDATA%/media-studio/envs/` via first-run setup: embeddable CPython has NO ensurepip/venv —
  bootstrap get-pip.py, install `pip --target`, activate via `python312._pth`/PYTHONPATH. Pinned requirements files.
- Vendor source for T4: `D:/tools/reframe/claude-shorts` (MIT; remotion/src/components/*Captions.tsx, scripts/
  compute_reframe.py, ENGINE1_BUILD_RECIPE.md Route A). Copy what you need into the repo (vendor/), keep LICENSE.

## A8. File ownership for the P2 build (write ONLY in your lane; SHARED files belong to the WIRING agent)
- U1: app/main/mediaProtocol.ts · renderer/components/Player.tsx · sidecar features/media_compat.py (+rpc+tests)
- U2: app/main/dialogIpc.ts · renderer/views/Library.tsx (owner) (+preload snippet for wiring)
- U3: renderer/components/toast/* · renderer/components/useJob.ts (owner)
- U4: sidecar media_studio/assets/* (manager/manifest/rpc+tests) · renderer/features/Assets.tsx
- U5: sidecar jobs.py + protocol.py (owner; ALL existing tests must stay green) (+tests)
- T1: sidecar features/timeline.py(+rpc+tests) · renderer/features/Timeline.tsx + lib timelineOps.ts(+tests)
- T2: sidecar features/tts/* + features/tracks_audio.py(+rpc+tests) · renderer/features/Dub.tsx
- T3: docs/research/MT-MODELS-2026.md · sidecar models/translation.py(+tests) · models/runner.py (owner)
- T4a: vendor/remotion-captions/* · app/render-cli/* (own package.json) · sidecar features/caption_remotion.py(+tests)
- T4b: sidecar features/reframe_claudeshorts.py(+tests) + features/reframe.py (owner: registry+fallback) ·
       renderer/features/ShortMaker.tsx (owner: style picker + engine A/B)
- T5: electron-builder.yml · build/* · sidecar runtime_setup/* + media_studio/tools_resolver.py(+tests)
- WIRING (last, serialized): handlers.py · __main__.py · Workspace.tsx · App.tsx · preload.ts · main.ts ·
  lib/rpc.ts · app/package.json · CONTRACTS conformance.
