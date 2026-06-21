# media-studio — INTEGRATION REPORT (app ↔ sidecar contract drift)

Scope: cross-check **every** RPC method the Electron renderer/main calls against
the sidecar's actual `protocol.METHODS` registry and the §3 data schemas. The #1
integration risk is **app↔sidecar contract drift** — a renamed method or a
camelCase/snake_case field mismatch silently breaks the wire at runtime even
though both sides compile and unit-test green.

Both sides were read in full:
- Python registry + dispatch: `sidecar/media_studio/protocol.py`,
  `sidecar/media_studio/rpc.py`, all `sidecar/media_studio/features/*.py`,
  `library.py`, `ffmpeg.py`, `models/*.py`.
- TS call surfaces: `app/renderer/src/lib/rpc.ts` (canonical client),
  `app/renderer/src/components/api.ts`, `app/renderer/src/features/_api.ts`, and
  every `rpc('...')` call site in `features/*.tsx`, `views/*.tsx`, `App.tsx`.
- Transport: `app/main/preload.ts`, `app/main/ipc.ts`, `app/main/sidecar.ts`,
  `app/main/main.ts`.

---

## HEADLINE FINDING (CRITICAL) — the contract methods are named correctly on both sides, but ~21 of them are NEVER registered at runtime

**Good news on naming:** every method string the UI sends matches a CONTRACTS.md
§2 name **exactly** — there are **no method-name typos** and **no schema
field-name (camelCase vs snake_case) mismatches** anywhere in the produced data
schemas. The TS interfaces and the Python result dicts agree field-for-field on
`Video`, `Transcript`, `Segment`, `Word`, `Cue`, `SubtitleTrack`, `Candidate`,
`Project`, `ConvertOptions`, and the `job.progress`/`job.done` payloads.

**Bad news on wiring:** there is **no composition root** that registers the
feature handlers. At runtime `protocol.METHODS` contains only the three
`@method`-decorated built-ins:

- `ping` — `protocol.py:186`
- `job.cancel` — `protocol.py:192`
- `job.status` — `protocol.py:205`

`rpc.py:main()` (`rpc.py:143-157`) builds the server and serves stdin, but imports
**no** feature module. Its own docstring admits the gap (`rpc.py:146-149`):
"the assembled sidecar entry point is expected to import the feature packages
before calling `main`". That entry point does not exist:
- `sidecar/media_studio/__init__.py` — empty (1 line).
- `sidecar/media_studio/features/__init__.py` — empty (no feature imports).
- `pyproject.toml:28-31` — the `media-studio-sidecar` script + the Electron
  launch (`app/main/sidecar.ts:55` → `py -3.12 -m media_studio.rpc`) both run the
  bare `rpc.main`, which wires nothing.
- `transcribe.register(...)` (`features/transcribe.py:309`) and
  `ShortMaker.register(...)` (`features/shortmaker.py:629`) exist **but nothing
  calls them**.
- `subtitles.py`, `tracks.py`, `library.py`, `convert.py`, and `settings`
  have **no `register()` and no `(params, ctx)` handler at all** — only pure
  functions/classes.

**Net effect:** every UI action except ping/job.cancel/job.status returns
JSON-RPC `METHOD_NOT_FOUND (-32601)`. The app shell loads, the sidecar boots, but
nothing computes. This is the single highest-severity integration risk and the
prerequisite for everything else in this report.

> A separate read-only sweep already documents this same gap with a fix sketch:
> `docs/build/COMPLETENESS-REPORT.md` §1. This report adds the exhaustive
> per-method method-name + schema-field cross-check the task requested.

---

## FULL CROSS-CHECK MATRIX

Legend — **Registered?** = does the method reach `protocol.METHODS` at runtime.
**Drift** = method-name / param-key / result-field / shape divergence.

| Method (§2) | Registered? (sidecar file:line) | UI call site (file:line) + params sent | UI expected result | Method-name drift | Schema/param drift |
|---|---|---|---|---|---|
| `ping` | YES `protocol.py:186` | `rpc.ts:169` `client.ping()` | `{pong,version}` | none | none |
| `library.list` | **NO** (`Library` is pure: `library.py:113+`) | `Library.tsx:44` `rpc('library.list')`; `rpc.ts:172` | `{videos:Video[]}` | none | none (Video fields match) — blocked by no-register |
| `library.add` | **NO** (`Library.add(path,title)` `library.py:118`) | `Library.tsx:65` `rpc('library.add',{path})`; `rpc.ts:173` | `{video:Video}` | none | param `path` ok; `add()` returns a bare `Video`, contract wants `{video}` wrapper — handler must wrap |
| `library.remove` | **NO** (`remove(video_id)→bool` `library.py:160`) | `Library.tsx:91` `rpc('library.remove',{id})`; `rpc.ts:174` | `{ok:boolean}` | none | param `id` ok; returns bare `bool`, contract wants `{ok}` |
| `project.open` | **NO** (`Project.open(manifest_path)` `library.py:217`) | `Workspace.tsx:107` `rpc('project.open',{id})`; `rpc.ts:178` | `{project:Project}` | none | **param mismatch**: fn takes a *manifest_path*, RPC sends `{id}`; no id→manifest resolver exists |
| `project.save` | **NO** (`Project.save(manifest_path)`) | `rpc.ts:179` (no view calls it) | `{ok}` | none | param/shape gap (takes a path, returns a Path) |
| `project.consolidate` | **NO** (`consolidate(folder)→str`) | `rpc.ts:180` | `{ok,folder}` | none | returns bare `str`, contract wants `{ok,folder}` |
| `transcribe.start` | **NO at runtime** — registrar exists `transcribe.py:309-328` but uncalled | `Transcribe.tsx:62` `rpc('transcribe.start',{videoId[,language]})`; `rpc.ts:185` | `{jobId, transcript?}`; done→`{transcript}` | none | params ok, result ok **if wired** (`transcribe.py:301-304`) |
| `subtitles.generate` | **NO** (`generate(transcript,...)` `subtitles.py:175`) | `Subtitles.tsx:85` `rpc('subtitles.generate',{videoId})`; `rpc.ts:190` | `{track}` | none | **param mismatch**: fn takes a *transcript*, RPC sends `{videoId}`; needs videoId→transcript resolver + `{track}` wrapper |
| `subtitles.edit` | **NO** (`edit(track,cues)` `subtitles.py:195`) | `Subtitles.tsx:105` `rpc('subtitles.edit',{trackId,cues})`; `rpc.ts:192` | `{track}` | none | **param mismatch**: fn takes a *track object*, RPC sends `{trackId}`; no trackId→track store exists |
| `subtitles.translate` | **NO** (`translate(track,target_lang,...)` `subtitles.py:238`) | `Subtitles.tsx:138` `rpc('subtitles.translate',{trackId,targetLang})`; `rpc.ts:194` | `{jobId, track?}` | none | **param mismatch** (`trackId` vs `track`); contract is a long job (`{jobId}`) but fn is synchronous — wiring must wrap in a Job |
| `subtitles.export` | **NO** (`export(track,fmt,out_path)` `subtitles.py:557`) | `Subtitles.tsx:162` `rpc('subtitles.export',{trackId,format})`; `rpc.ts:196` | `{path}` | none | **param mismatch**: fn takes `(track,fmt,out_path)`, RPC sends `{trackId,format}`; returns bare `str`, contract wants `{path}` |
| `tracks.list` | **NO** (`list_tracks(project)` `tracks.py:100`) | `Tracks.tsx:42` `rpc('tracks.list',{videoId})`; `rpc.ts:201` | `{tracks:[]}` | none | **param mismatch** (`videoId` vs `project`); needs `{tracks}` wrapper |
| `tracks.rename` | **NO** (`rename_track(project,track_id,name)` `tracks.py:139`) | `Tracks.tsx:98` (`rename`) `rpc('tracks.rename',{trackId,name})`; `rpc.ts:203` | `{track}` (rpc.ts) | none | params `trackId,name` ok; fn also needs a *project* it isn't given from params |
| `tracks.relabel` | **NO** (`relabel_track(project,track_id,lang)` `tracks.py:148`) | `Tracks.tsx:103` `rpc('tracks.relabel',{trackId,lang})`; `rpc.ts:205` | `{track}` | none | same missing-`project` gap |
| `tracks.add` | **NO** (`add_track(project,track)` `tracks.py:105`) | `Tracks.tsx:110` `rpc('tracks.add',{videoId,trackId})`; `rpc.ts:207` | `{ok}` | none | **param mismatch** (`videoId,trackId` vs `project,track`) |
| `tracks.remove` | **NO** (`remove_track(project,track_id)` `tracks.py:120`) | `Tracks.tsx:116` `rpc('tracks.remove',{videoId,trackId})`; `rpc.ts:209` | `{ok}` | none | param-shape gap (no `project`) |
| `tracks.burn` | **NO** (`burn_track(in_path,track,...)` `tracks.py:417`) | `Tracks.tsx:149` `rpc('tracks.burn',{videoId,trackId})`; `rpc.ts:211` | `{jobId, path?}` | none | **param mismatch** (no `in_path`/`track` from `{videoId,trackId}`); long-job not wired |
| `tracks.strip` | **NO** (`strip_track(in_path,...)` `tracks.py:484`) | `Tracks.tsx:126` `rpc('tracks.strip',{videoId,trackId})`; `rpc.ts:213` | `{path}` | none | **param mismatch**; returns bare `str` |
| `convert.start` | **NO** — `start_handler` is a FACTORY, not a `(params,ctx)` handler (`convert.py:240`) | `Convert.tsx:95` `rpc('convert.start',{...videoId/path, options})`; `rpc.ts:218` | `{jobId, path?}` | none | **handler-shape mismatch**: `start_handler(params,*,settings,resolver,run,probe)` returns `Callable[[JobContext],{path}]`, never `{jobId}`; wiring must `ctx.jobs.start(...)` and return `{jobId}` |
| `convert.batch` | **NO** — `batch_handler` same factory shape (`convert.py:277`) | `Convert.tsx:122` `rpc('convert.batch',{items})`; `rpc.ts:223` | `{jobId, paths?}` | none | same handler-shape mismatch |
| `shortmaker.select` | **NO at runtime** — `ShortMaker.register` `shortmaker.py:629-636` uncalled | `ShortMaker.tsx:358` `rpc('shortmaker.select',{videoId,prompt,controls})`; `rpc.ts:232` | `{jobId, candidates?}` | none | params ok, result ok **if wired** |
| `shortmaker.export` | **NO at runtime** — same registrar uncalled | `ShortMaker.tsx:407` `rpc('shortmaker.export',{videoId,candidateIds})`; `rpc.ts:237` | `{jobId, clips?:[{path}]}` | none | params ok but **value contract unsatisfiable**: UI sends `candidateIds` as `"${rank}@${sourceStart}"` strings; `_resolve_candidates` (`shortmaker.py:602-626`) needs an inline `candidates` array (never sent) or a populated id→Candidate map (nothing populates it) → empty export. See HIGH-3. |
| `job.cancel` | YES `protocol.py:192` | `Transcribe.tsx:87`, `Subtitles.tsx:178`, `Convert.tsx:143`, `ShortMaker.tsx:432` `rpc('job.cancel',{jobId})`; `rpc.ts:242` | `{ok}` | none | none |
| `job.status` | YES `protocol.py:205` | `rpc.ts:243` (via `useJob`/poll) | `{status,pct}` | none | none — returns `Job.snapshot()` `{status,pct}` |
| `settings.get` | **NO** | `App.tsx:59` `rpc('settings.get')`; `rpc.ts:248` | `{useCloud?,...}` | none | not registered |
| `settings.set` | **NO** | `App.tsx:76` `rpc('settings.set',{useCloud})`; `rpc.ts:249` | `Record<string,unknown>` | none | not registered |
| `job.progress` (notif) | YES emitted `rpc.py:68` / `protocol.make_progress` | all panels `onProgress` (e.g. `Transcribe.tsx:44`) | `{jobId,pct,message}` | none | none (field names match) |
| `job.done` (notif) | YES emitted `rpc.py:71` / `protocol.make_done` | `ShortMaker.tsx` `onJobDone`; preload relays it (`preload.ts:56`, `ipc.ts:73`) | `{jobId,result}` | none | none |

### Counts
- **Method-name mismatches: 0.** Every UI method string equals a §2 name.
- **Schema field-name (camel/snake) mismatches: 0.** All produced dicts use the
  §3 camelCase keys (`durationSec`, `sourceStart`, `addedAt`, `hasTranscript`,
  `jobId`, …); none leak snake_case across the wire. (Internal note: the LLM JSON
  uses `duration_sec`, but `select.to_candidates` converts to `durationSec`
  before it crosses the wire — not a contract violation.)
- **Methods unregistered at runtime: 21** (library×3, project×3, settings×2,
  subtitles×4, tracks×7, convert×2) **plus 3 registered-but-never-invoked**
  (transcribe.start, shortmaker.select, shortmaker.export).
- **Param-shape / handler-shape mismatches that any wiring layer must bridge: ~14**
  (the `videoId`/`trackId`/`id` wire params vs the pure-function signatures that
  expect `transcript`/`track`/`project`/`manifest_path`/`in_path`, plus the two
  convert factory handlers).

---

## RPCs the UI calls that the sidecar does NOT implement (as a runtime handler)

All 21 unregistered methods above qualify — the UI calls them, the sidecar has no
live handler. The most important to call out, because they have **no handler
code at all** (not just "unwired"), are:

- `subtitles.*` — `subtitles.py` exposes pure `generate/edit/translate/export`
  functions whose signatures don't match the wire params; **no `(params,ctx)`
  handler and no `register()`** exists.
- `tracks.*` — `tracks.py` exposes pure manifest/argv functions operating on a
  Project dict; **no handler, no `register()`**.
- `library.*` / `project.*` — `library.py` has the `Library` and `Project`
  classes but **no RPC handler layer**; methods like `project.open` take a
  *manifest path*, not the `{id}` the UI sends.
- `settings.get` / `settings.set` — **no settings store or handler exists
  anywhere** in the sidecar. `App.tsx:59,76` calls them on startup (to read/persist
  `useCloud`), so the very first thing the UI does fails.

Convert is "implemented" but as factory builders, not handlers (HIGH-1 below).

---

## Sidecar methods that NO UI surface calls

None that are orphaned in a problematic way. Coverage is essentially symmetric:
- `ping` — defined sidecar-side and exposed in `client.ping` (`rpc.ts:169`) but no
  view invokes it. Harmless (liveness probe for the supervisor / future health UI).
- `job.status` — registered + typed in `client.job.status` (`rpc.ts:243`); used via
  the `useJob` polling helper rather than a direct view call. Not orphaned.
- `project.save` / `project.consolidate` — typed in `client.project` (`rpc.ts:179-180`)
  but no current view triggers them; they're contract methods awaiting a "Save
  project" / "Consolidate" UI affordance. Expected, low risk.

There are **no sidecar-only methods missing from the TS client** — `rpc.ts`'s
`client` mirrors all ~30 §2 methods. Conversely there are **no UI-invented methods**
absent from the contract.

---

## OTHER INTEGRATION RISKS (ranked)

**CRITICAL-1 — No composition root (the headline).** Write the missing assembly
module (e.g. `sidecar/media_studio/app.py` or a real `__main__.py`) that: imports
every feature module; constructs `Library`, `ModelRunner`, `get_provider(settings)`,
`ReframeEngine`, a settings store, and the `videoId→path` / `trackId→track` /
`id→project` resolvers; authors thin `(params,ctx)` handlers over the pure
functions; calls `transcribe.register(...)`, `ShortMaker(...).register(protocol.register)`,
and `protocol.register(...)` for the rest; then runs `rpc.main`. Point
`pyproject.toml:31` + `app/main/sidecar.ts:55` at that module instead of
`media_studio.rpc`. This unblocks all 21+3 methods at once.

**HIGH-1 — convert handlers are factories, not RPC handlers.**
`convert.start_handler` / `batch_handler` (`convert.py:240,277`) return a
`Callable[[JobContext], …]` and take keyword-only deps — they do NOT match the
`Handler = (params, ctx) -> result` signature (`protocol.py:18-19`). Registering
them directly would dispatch wrong. The wiring layer must wrap:
`def h(params, ctx): return {"jobId": ctx.jobs.start(start_handler(params, settings=…, resolver=…)).id}`.

**HIGH-2 — long-job vs sync-function mismatch for subtitles/tracks.** The contract
makes `subtitles.translate`, `tracks.burn`, `convert.*`, `shortmaker.*` long jobs
(`{jobId}` + `job.done`), but `subtitles.translate` and `tracks.burn` are written
as synchronous functions. The renderer's `_api.ts` (`extractJobId`,
`features/_api.ts:120-126`) and the panels assume `rpc(...)` resolves with the
**terminal** result for these. The wiring layer must decide per method whether to
run sync (resolve immediately) or via `ctx.jobs.start` (return `{jobId}` + emit
`job.done`) — and it must match what each panel expects, or progress/cancel breaks.

**HIGH-3 — `shortmaker.export` candidate identity is unsatisfiable as wired.**
The UI builds `candidateIds` as `"${rank}@${sourceStart}"` strings
(`ShortMaker.tsx`), but never forwards the original `candidates` array.
`_resolve_candidates` (`shortmaker.py:602-626`) only resolves via an inline list
(not sent) or a `context["candidates"]` id→Candidate map (nothing populates it),
so export resolves to **zero clips**. Fix: either have the UI forward the selected
`Candidate` objects, or have the sidecar persist the `select` result keyed by the
same `"rank@sourceStart"` id the UI generates.

**MEDIUM-1 — sidecar process uses `py`, not your venv, by default.**
`app/main/sidecar.ts:53` defaults `MEDIA_STUDIO_PYTHON` to `py` and runs
`-3.12 -m media_studio.rpc`. The bare `py -3.12` won't see the `sidecar/.venv`
packages (faster-whisper, scenedetect). Set `MEDIA_STUDIO_PYTHON` to the venv's
`python.exe` before `npm run dev` (see RUN-CHECKLIST §2), or the real handlers —
once wired — fail to import their deps.

**MEDIUM-2 — stale `sidecar/.venv` is Python 3.14, not 3.12.** `pyvenv.cfg` +
`cpython-314` pyc caches indicate the existing venv was built with 3.14, violating
the contract's 3.12 pin and risking wheel-resolution failures for
faster-whisper/ctranslate2. Recreate with `py -3.12` (RUN-CHECKLIST §1).

**LOW-1 — TS `Window.api` augmentation is split across three modules.**
`components/api.ts:91-95` declares `interface Window { api }`, while `lib/rpc.ts`
and `features/_api.ts` deliberately avoid a second `declare global` (to dodge
TS2717 collisions) and read the bridge structurally. This is intentional and
documented, but it means the bridge's typed shape is asserted in three places;
keep them in sync if the bridge surface ever changes. Not a runtime risk.

**LOW-2 — `subtitles.export` format string.** Both sides agree on `srt|ass|vtt`
(`rpc.ts:45`, `tracks.py:53`), and `tracks` formats match — no drift, noted for
completeness.

---

## BOTTOM LINE

The contract was followed **precisely on names and field schemas** — there is no
classic "TS says `durationSec`, Python says `duration_sec`" drift to chase, and no
typo'd method. The integration risk is entirely structural: a missing composition
root leaves 21 contract methods unregistered (+3 registered-but-uninvoked), and
the handlers that do exist need a thin adapter layer to bridge the wire params
(`videoId`/`trackId`/`id`) to the pure functions' arguments
(`transcript`/`track`/`project`/`path`) and to wrap the convert/long-job factories
into `{jobId}` responses. Write that one assembly module and resolve HIGH-1..3 and
the app goes from "compiles and tests green, does nothing" to runnable.
