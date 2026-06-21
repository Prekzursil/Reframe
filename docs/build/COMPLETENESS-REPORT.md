# media-studio — COMPLETENESS REPORT (post-build punch list)

Read-only sweep of `app/` + `sidecar/` against `CONTRACTS.md`. Every finding is
file:line. Sorted into the seven requested sections, then a prioritized fix list.

**Rough completeness: ~80%.** Almost every module is fully written, well-typed,
and thoroughly unit-tested. The build is held back by **one structural gap** (no
process actually wires the feature handlers into the RPC registry), so the
sidecar boots but answers only `ping`/`job.*`. Fix that one file and the app goes
from "looks done, does nothing" to "runnable".

---

## 1. CONTRACTS.md §2 methods NOT registered in the sidecar (THE headline gap)

The §2 method registry has ~30 public methods. The framework to register them
exists (`protocol.method` decorator + `protocol.register`), and **every feature
module ships a working handler + a `register(...)` function**. But **nothing ever
calls those `register()` functions.** There is no assembled entry point.

Evidence:
- `sidecar/media_studio/protocol.py:186-216` — only `ping`, `job.cancel`,
  `job.status` are registered at import (the three `@method` decorators here).
- `sidecar/media_studio/rpc.py:143-157` — `main()` builds the server and serves,
  but imports **no** feature module. Its own docstring admits it: *"the assembled
  sidecar entry point is expected to import the feature packages before calling
  `main`"* (`rpc.py:146-149`). That assembled entry point **does not exist**.
- `sidecar/media_studio/__init__.py` — empty (1 line). Does not import features.
- `sidecar/media_studio/features/__init__.py` — empty (1 line). Does not import
  the feature modules.
- `pyproject.toml:31` — entry point is `media_studio.rpc:main`, i.e. the bare
  core server with no handlers wired.
- `app/main/sidecar.ts:55` — the Electron side launches exactly
  `py -3.12 -m media_studio.rpc`, which runs `rpc.main()` → only ping/job.* live.

**Net effect:** at runtime every one of the following returns JSON-RPC
`METHOD_NOT_FOUND` (-32601):

`library.list`, `library.add`, `library.remove`, `project.open`, `project.save`,
`project.consolidate`, `transcribe.start`, `subtitles.generate`, `subtitles.edit`,
`subtitles.translate`, `subtitles.export`, `tracks.list`, `tracks.rename`,
`tracks.relabel`, `tracks.add`, `tracks.remove`, `tracks.burn`, `tracks.strip`,
`convert.start`, `convert.batch`, `shortmaker.select`, `shortmaker.export`,
`settings.get`, `settings.set`.

The handlers themselves are present and correct — they just need wiring:
- `transcribe.register(resolve_video, ...)` → `transcribe.py:309`
- `ShortMaker(...).register(protocol.register)` → `shortmaker.py:629`
- `convert.start_handler` / `convert.batch_handler` → `convert.py:240,277` (these
  return a *job body*, not a §2 RPC handler — the wiring layer must adapt them:
  read params, `ctx.jobs.start(handler)`, return `{jobId}`).
- subtitles / tracks / library / project / settings — these modules expose pure
  functions and classes but **no `register()` helper and no RPC handler at all**;
  the (missing) assembly module must author thin handlers over them:
  - `subtitles.py` — has `generate/edit/translate/export` logic but no handler that
    maps `subtitles.generate({videoId})` → load transcript → `{track}`. Note the
    method↔function gap: `subtitles.generate(transcript)` takes a *transcript*,
    but the RPC takes `{videoId}` — the wiring layer must resolve videoId→transcript.
  - `tracks.py` — `list/rename/relabel/add/remove/burn/strip` operate on a
    *Project dict*; the RPC takes `{videoId|trackId}` — wiring must load the
    Project, apply, and persist.
  - `library.py` — `Library` / `Project` classes, no handlers.
  - **`settings.get` / `settings.set` have NO implementation anywhere.** No module
    persists or returns the §2 settings object (`{useCloud, cloudApiKey?,
    modelsDir, ffmpegPath}`). `App.tsx:59,76` calls them; they will fail.

**This is the single must-fix-first item.** It is the difference between a green
pytest suite (which it largely already is) and a runnable app (which it is not).

---

## 2. §3 schema field mismatches — Python side vs `app/renderer/src/lib/rpc.ts`

Good news: the **core §3 data schemas match exactly.** `Word`, `Segment`,
`Transcript`, `Cue`, `SubtitleTrack`, `Candidate`, `Video`, `Project` field names
and casing are identical between the Python TypedDict-style dicts and the three TS
copies (`lib/rpc.ts:19-85`, `components/api.ts:12-74`, `features/_api.ts:47-99`).
`sourceStart`, `durationSec`, `hasTranscript`, `addedAt` all line up. No field
name/case mismatch in the data schemas.

The mismatches are in **method result/param envelopes**, not the data records:

1. **`ConvertOptions` field TYPES diverge from the Python side.**
   - TS (`lib/rpc.ts:104-113`, `_api.ts:84-93`): `scale`, `fps`, `crf` are all
     `string`. The Convert UI sends `crf: '23'` (a string) — `Convert.tsx:43`.
   - Python `ffmpeg.build_convert_argv` (`ffmpeg.py:117-164`) does
     `str(crf)`/`str(fps)`/`str(scale)`, so it tolerates either — **no runtime
     break**, but the contract said "keep field names identical both sides" and
     the *types* silently differ (number vs string). The select test even passes
     `duration_sec` as an int. Cosmetic / low risk, but note it.

2. **`tracks.add` / `tracks.remove` result shape is invented.**
   - §2 (`CONTRACTS.md:68`) gives NO documented result for `tracks.add` /
     `tracks.remove` (only `tracks.burn`→`{jobId}`→`{path}` and
     `tracks.strip`→`{path}` are typed).
   - TS client declares `tracks.add(...) : Promise<{ ok: boolean }>` and
     `tracks.remove(...) : Promise<{ ok: boolean }>` (`lib/rpc.ts:207-210`).
   - There is no handler, but when one is written it must agree with the TS
     `{ ok: boolean }` assumption (or the TS must change). Flag so they're authored
     consistently.

3. **`transcribe.start` / `subtitles.translate` / `tracks.burn` / `convert.start`
   long-job resolution is assumed but unbridged.** The UI (`Transcribe.tsx:62-77`,
   `Subtitles.tsx:138-148`, `Tracks.tsx:149-158`, `Convert.tsx:95-106`) treats
   `rpc(...)` as resolving with the **terminal** result (`{transcript}` /
   `{track}` / `{path}`). But the sidecar resolves the `id` response **immediately**
   with `{jobId}` (`rpc.py:122-123`) and delivers the terminal payload only via a
   separate `job.done` notification. `app/main/sidecar.ts:177-200` / `ipc.ts:73`
   relay `job.done` to a **separate channel** (`onJobDone`), and `preload.ts:56`
   exposes `onJobDone`. **But the non-ShortMaker panels never call `onJobDone`** —
   `Transcribe/Subtitles/Tracks/Convert` only read `res.transcript`/`res.track`/
   `res.path` off the immediate resolution, which will be `undefined` (the immediate
   resolution is `{jobId}` only). So these panels will show progress but **never
   render the final result.** Only `ShortMaker.tsx:368,414` correctly awaits
   `waitForJobDone(...)`. This is a real wiring bug (see §4).

---

## 3. Tests: missing / weak / heavy-ML-at-collection

**Python: strong.** Every sidecar module has a mirrored test, and **none import
faster-whisper / torch / scenedetect / mediapipe at collection time** — all heavy
deps are mocked at an injected seam:
- `test_transcribe.py:1-20` mocks the whisper loader seam (no `faster_whisper`).
- `test_provider.py:1-28` injects the HTTP transport (no socket).
- `test_runner.py:1-23` injects popen / whisper_load / free_hook (no process/GPU).
- `test_reframe.py`, `test_caption.py`, `test_tracks.py`, `test_convert.py` inject
  the ffmpeg/subprocess runner; `test_boundary.py`, `test_select.py`,
  `test_subtitles.py`, `test_shortmaker.py` are pure-logic with fakes.
- `conftest.py:1-5` is explicitly heavy-ML-free.

Full Python test inventory (all present): `test_jobs`, `test_library`, `test_rpc`
(covers protocol.py + rpc.py), `test_ffmpeg`, `test_convert`, `test_caption`,
`test_reframe`, `test_select`, `test_boundary`, `test_subtitles`, `test_tracks`,
`test_transcribe`, `test_shortmaker`, `test_provider`, `test_runner`.

Gaps / weaknesses:
- **No test exercises the assembled sidecar with all handlers registered** —
  because that assembly module doesn't exist (§1). So the suite is green while the
  app is non-functional; the tests can't catch the §1 gap. Add an integration test
  that registers all handlers and asserts every §2 method resolves (it will fail
  today, correctly).
- **No `dependencies` pin for `mediapipe`/`torch`** in `pyproject.toml:16-20`
  (only `faster-whisper`, `scenedetect`, `httpx`) — fine because verthor is its own
  WSL venv, but means `convert`/`reframe`/`boundary` real detectors are unimplemented
  seams (see §5). Not a test break.

**TypeScript: adequate but config-fragile.**
- TS tests self-declare environment via `// @vitest-environment jsdom` pragmas
  (`Library.test.tsx:1`, `api.test.ts:1`, etc.) and `jsdom` is in devDeps
  (`package.json:30`). They mock the bridge (`Library.test.tsx:8-12`), so no real
  Electron / window.api is needed.
- **RISK: `package.json:16` runs `"test": "vitest run"` but there is NO vitest /
  vite test config file** (confirmed: no `vitest.config.*`, and the only config is
  `electron.vite.config.ts`, which exports a *multi-target electron-vite* config
  vitest cannot consume as a test config). Vitest will run with defaults; the
  per-file jsdom pragmas should carry the DOM tests, but there is no `test:
  { environment, globals, setupFiles }` block and no React Testing Library — tests
  hand-roll `createRoot`/`act` (`Library.test.tsx:3-4`). Likely runs, but is
  brittle and undocumented. Recommend adding an explicit `vitest.config.ts` with
  `environment: 'jsdom'` and `globals: true`.
- No test for `App.tsx`, `main.tsx`, `main/main.ts`, `main/ipc.ts`,
  `main/sidecar.ts` (the Electron main-process supervisor + IPC bridge are
  untested — the riskiest glue in the app is uncovered). `sidecar.ts` JSON-RPC
  framing/restart logic especially deserves a unit test.

---

## 4. UI features not wired to a real rpc call (placeholder/stub handlers)

Most panels ARE wired to real rpc. The exceptions:

1. **Long-job terminal results never arrive in 4 of 5 panels (the `onJobDone`
   gap).** `Transcribe.tsx:62-77`, `Subtitles.tsx:138-148`, `Tracks.tsx:149-158`,
   `Convert.tsx:95-106` read the terminal payload off the *immediate* rpc
   resolution, which is `{jobId}` only — so transcript/track/path stay `undefined`
   and the panel sits at "running" with progress but no result. The bridge *does*
   expose `onJobDone` (`preload.ts:56`, `ipc.ts:73`, `sidecar.ts` `done` event),
   and `ShortMaker.tsx` uses it correctly via `waitForJobDone` — the other four
   panels just never subscribe. Real functional bug, not a placeholder, but it
   means those features won't complete in the UI. (Alternatively the main-process
   rpc layer could be changed to resolve the `id` only when `job.done` arrives, as
   the panels' CONTRACT-NOTEs assume — but `sidecar.ts:260` resolves on the `id`
   response, which is the immediate `{jobId}`.)

2. **ShortMaker preview is a placeholder.** `ShortMaker.tsx:670-672` — the
   `<div className="sm-preview">` is explicitly a stub: *"real `<video>` wiring is
   owned by the workspace/player unit"*. No actual clip preview/playback exists
   anywhere. Nudge/approve/discard/regenerate/export ARE wired (`ShortMaker.tsx:358,
   407,432`).

3. **`shortmaker.export` sends only `candidateIds`, but the sidecar can't resolve
   them.** `ShortMaker.tsx:407-410` sends `{videoId, candidateIds}`. The sidecar's
   `_resolve_candidates` (`shortmaker.py:602-626`) prefers an inline `candidates`
   list and otherwise asks the context loader for an id→Candidate map — which
   nothing populates. With ids-only and no map, export resolves to `[]` and exports
   nothing. The UI even has the candidate objects in hand (`approvedCandidates`,
   `ShortMaker.tsx:201`) but doesn't forward them. Wiring mismatch.

4. **Quality (Local/Cloud) toggle depends on `settings.get`/`settings.set`** which
   have no sidecar implementation (§1). `App.tsx:59,76` — toggle works in-memory,
   persistence silently no-ops/fails (caught and swallowed at `App.tsx:65,77`).

Everything else is genuinely wired: `Library` (`library.list/add/remove`,
`Library.tsx:44,65,91`), `Workspace` (`project.open`, `Workspace.tsx:107`),
`Tracks` list/rename/relabel/add/remove/strip (`Tracks.tsx:42,98,103,110,116,126`),
`Convert` start/batch (`Convert.tsx:95,122`), `Subtitles` generate/edit/export
(`Subtitles.tsx:85,105,162`).

---

## 5. Stubs / TODO / NotImplementedError / pass-only bodies

- **`boundary.detect_silences` — `raise NotImplementedError`**
  (`boundary.py:430-439`). Intentional seam (`# pragma: no cover - seam`), but it
  means production silence-snapping is unimplemented; `shortmaker._lazy_snap`
  passes `settings.get("silences")` (`shortmaker.py:145-150`), which nothing fills,
  so snapping relies on sentence-ends only. Functional shortfall, not a crash.
- **`boundary.detect_scene_cuts` — `raise NotImplementedError`**
  (`boundary.py:442-451`). Same: PySceneDetect is declared in `pyproject.toml:18`
  but never actually invoked anywhere. The §5 "scene cut (PySceneDetect)" boundary
  source is **not wired**.
- **No real silence/scene detector module exists** to fill those seams — the
  orchestrator comment says production wires them (`shortmaker.py:141-144`) but no
  code does.
- **`shortmaker._lazy_cut` / `_lazy_export` error paths are `# pragma: no cover -
  prod seam`** (`shortmaker.py:169,206`) — fine, real ffmpeg paths.
- `transcribe.WhisperModel.transcribe` / `WhisperLoader.load` are `...` Protocol
  bodies (`transcribe.py:64,74`) — correct (Protocols).
- No `TODO`/`FIXME`/`XXX` comments and no accidental `pass`-only function bodies
  found in the production tree. The only `NotImplementedError`s are the two
  boundary seams above plus the abstract `Provider.chat` (`provider.py:167`, correct
  for an ABC).
- `ShortMaker.tsx:670` preview placeholder (also listed in §4).

---

## 6. §4 engine gotchas — VERIFICATION

All three §4 correctness rules are **correctly honored** in the engine code:

(a) **verthor invoked FROM A FILE, not stdin-piped.** ✅ CORRECT.
`reframe.build_reframe_argv` (`reframe.py:153-181`) builds
`["wsl", "bash", <script>, <in>, <out>, <aspect>, <w>, <h>]` — the script is the
3rd argv element (bash's positional file arg). No `-c`, no `tr`, no `|`, nothing to
stdin. `ReframeEngine.reframe` (`reframe.py:204-234`) passes the argv LIST to the
runner with no `shell=True`. Tests lock this in (`test_reframe.py:130-155,209-227`).

(b) **ASS cue text escaped (no raw `{`/`}` override injection).** ✅ CORRECT, in
all three ASS generators:
- `caption.escape_ass_text` (`caption.py:56-76`) — backslash-doubled FIRST, then
  `{`→`\{`, `}`→`\}`, newlines→`\N`. Tested against `{\fake}` and `{\an8}`
  payloads (`test_caption.py:74-89,213-220`).
- `tracks.ass_escape` (`tracks.py:191-207`) — same escaping, used by
  `build_ass_document` (`tracks.py:266`).
- `subtitles.escape_ass_text` (`subtitles.py:437-448`) — slightly different
  (`{`→`(`, `}`→`)`) but still neutralizes override blocks; used by `to_ass`
  (`subtitles.py:468`).
  **Minor note:** three independent ASS generators/escapers now exist
  (`caption.py`, `tracks.py`, `subtitles.py`) with subtly different escaping and
  style headers — duplication risk, but each is safe. Not a violation.

(c) **Caption cue times re-based by `sourceStart`.** ✅ CORRECT.
- `caption.build_ass` subtracts `source_start` per cue via `rebase_cue_time`
  (`caption.py:98-105,167-169`), clamps to ≥0, and skips cues entirely before the
  clip (`caption.py:170-171`). The ⭐ t≠0 test passes (`test_caption.py:175-189`).
- `shortmaker._export_one` threads the candidate's `sourceStart` into the caption
  stage (`shortmaker.py:435,451`), and `_cues_for_clip` keeps cues in original-video
  time so the caption stage does the subtraction (`shortmaker.py:274-308`).
- `tracks.build_ass_document` also re-bases by `source_start` (`tracks.py:261-262`).

**No §4 gotcha is violated.** This is the strongest part of the build.

---

## 7. PRIORITIZED FIX LIST

### A. To get a GREEN pytest suite (sidecar)
The Python suite is **already essentially green** — every module imports cleanly
(heavy deps behind seams), tests mock at the seam, no collection-time heavy import.
Order if anything needs touching:

1. **Confirm `faster-whisper`/`scenedetect`/`httpx` are NOT needed at import.**
   They aren't (verified: lazy imports inside `FasterWhisperLoader.load`
   `transcribe.py:95`, provider uses stdlib urllib, boundary detectors are seams).
   So `pytest` runs with **only pytest installed** — no model downloads. ✅
2. **(Optional) add the missing integration test** that registers every handler and
   asserts all §2 methods resolve. It will FAIL today (proving §1), which is the
   point — it's the regression guard for the real gap.
3. Nothing else blocks pytest. If a CI runner does `pip install -e .[dev]`, note
   that `faster-whisper`/`scenedetect` pull large wheels (torch etc.) at *install*
   time even though tests don't import them — consider a `pytest`-only install
   path (`pip install pytest`) for the fast lane.

### B. To get a RUNNABLE app (in priority order)
1. **[BLOCKER] Write the sidecar assembly / entry point** that imports every
   feature module, wires `register(...)` for each §2 method, and runs the loop.
   This is the `media_studio.rpc:main` reality gap (§1). Concretely:
   - Build a module (e.g. `media_studio/__main__.py` or `media_studio/app.py`) that:
     constructs `Library` + settings store + `ModelRunner`; registers
     `library.*`, `project.*`, `settings.*`, `subtitles.*`, `tracks.*`,
     `convert.*`, `transcribe.start`, `shortmaker.*` onto `protocol.METHODS`;
     then calls `rpc.main()`.
   - Point `app/main/sidecar.ts:55` (and `pyproject.toml:31`) at that module
     (e.g. `-m media_studio` or `-m media_studio.app`).
2. **[BLOCKER] Implement `settings.get` / `settings.set`** — no persistence layer
   exists for the §2 settings object. Needed by `App.tsx` and by every feature that
   reads `ffmpegPath`/`modelsDir`/`useCloud`.
3. **[HIGH] Fix the long-job terminal-result wiring in the 4 panels** (§4.1):
   make `Transcribe/Subtitles/Tracks/Convert` subscribe to `onJobDone` (like
   `ShortMaker`), OR change the main-process rpc layer to resolve the request only
   when `job.done` arrives. Without this, those features show progress but never
   display output.
4. **[HIGH] Fix `shortmaker.export` candidate forwarding** (§4.3): have
   `ShortMaker.tsx` send the approved `candidates` objects (it has them via
   `approvedCandidates`), not just `candidateIds`, OR populate the context loader's
   id→Candidate map in the sidecar. Otherwise export produces zero clips.
5. **[MEDIUM] Wire the boundary detectors** (§5): implement `detect_silences`
   (ffmpeg `silencedetect`) and `detect_scene_cuts` (PySceneDetect) and feed them
   into `shortmaker._lazy_snap`. Until then boundary-snap uses sentence-ends only —
   degraded but functional.
6. **[MEDIUM] Add a `vitest.config.ts`** (`environment: 'jsdom'`, `globals: true`)
   so `npm test` is deterministic instead of relying on per-file pragmas with no
   base config (§3).
7. **[LOW] Reconcile `ConvertOptions` numeric-vs-string types** and the
   `tracks.add/remove → {ok}` result shape between TS and the (to-be-written)
   handlers (§2.1, §2.2).
8. **[LOW] Add tests for the Electron main process** (`sidecar.ts` framing/restart,
   `ipc.ts` relay) — the untested glue (§3).

---

### One-paragraph bottom line
The hard parts are done and done well: the JSON-RPC core, the job system, the
ffmpeg/argv builders, the selection recipe, boundary-snapping, and all three §4
engine-correctness rules (verthor-from-file, ASS escaping, sourceStart re-basing)
are correct and thoroughly tested with zero heavy-ML imports at collection. What's
missing is the **assembly seam**: no process registers the feature handlers, so the
sidecar answers only `ping`/`job.*`; `settings.*` is unimplemented; and four of
five UI panels never read their long-job results. Fix the entry-point wiring +
settings + the `onJobDone` plumbing and this goes from ~80% to runnable.
