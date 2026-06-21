# Editing-Refinement Bundle — PLAN

**Status:** PLAN (docs only; no feature code). Follows the gate-approved DESIGN at
`docs/plans/editing-refine/DESIGN.md`.
**Branch:** `feat/editing-refine-design` (off `origin/main`).
**Repo:** `Prekzursil/Reframe` (local `C:/Users/Prekzursil/Documents/github/Reframe`).
**Date:** 2026-06-18.

> RAILS — every WU below cites real code (verified against source in this clone,
> not just the DESIGN). All sidecar paths are under `sidecar/media_studio/`;
> renderer paths under `app/renderer/src/`. NO new cut/detection/cluster math —
> all reused from shipped, tested modules. AI is DEFERRED; when/if built it rides
> the shipped Hub envelope only (`models/ai_job.py` `plan_ai_job`/`run_ai_job`,
> `models/provider.py` rotation pool, the ONE RPC site `handlers.register_all`,
> `handlers.py:1982`).

---

## 0. Ground-truth anchors (re-verified against source, file:line)

| Anchor | Where | Confirmed |
|---|---|---|
| Filler cut-list + stats | `features/fillers.py:201` `build_cutlist_with_stats`; `:284` `build_cutlist`; `:351` `build_segment_cut_argv`; `:305` `remap_time`; `:324` `remap_cues` | yes |
| Filler defaults / sets / guards | `fillers.py:44` `DEFAULT_MERGE_GAP_MS`; `:60` `DEFAULT_SETS` (en+ro); `:94` `_lang_sets`; `:53` `_SENTENCE_END`; `:170` sentence-end guard | yes |
| Silence detection + keeps | `features/silencetrim.py:159` `detect_silence_spans`; `:107` `keep_spans`; `:150` `removed_seconds`; `:199` `trim_clip`; `:254` `class SilenceTrim`; `:257` `__init__` (seams); `:336` `register` | yes |
| Diarize core | `features/diarize.py:179` `diarize_transcript`; `:92` `greedy_cluster`; `:134` `assign_speakers_to_segments`; `:174` `roster`; `:129` `speaker_label`; `:51` `DEFAULT_THRESHOLD=0.5`; `:374` `register`; `:347` `register_diarize_assets` | yes |
| **GAP: speaker dropped** | `subtitles.py:102` `make_cue` (only `index/start/end/text`); `:107` `reindex` (re-builds with only those 4 keys); `:125` `cues_from_transcript` (never reads `seg["speaker"]`); `:152` `_split_segment` | yes |
| ONE RPC site | `handlers.py:1982` `register_all`; silencetrim reg `:2176`; diarize reg `:2219` | yes |
| Reuse seams in register_all | `handlers.py:197` `_resolve_video_path`; `:152` `_ffmpeg_run`; `:153` `_ffprobe_duration`; `:146` `exports_dir`; diarize `load_project=_load_project_data`/`save_project=_save_project_data` (`:2221-2222`) | yes |
| AI envelope (deferred only) | `models/ai_job.py` `plan_ai_job`/`run_ai_job`; `handlers.py:1601` `plan_ai_job_envelope`; `:1617` `_run_ai_job` | yes |
| Renderer bridge | `features/_api.ts:57` `getApi`; `:151` `waitForJobDone`; `:167` `pickField`; `:35` `MediaStudioApi`; `:68` `Segment`. `Diarize.tsx:14` imports; `:19` `DiarizedSegment`; `:46-49` `DiarizeProps`/`api?` prop; `:52` component | yes |
| Gate config | sidecar `pyproject.toml:49` `[tool.pytest.ini_options]` (`testpaths=["tests"]`); renderer `app/vitest.config.ts:44-48` `thresholds:100`; `app/package.json:19` `test`, `:18` `typecheck`; `app/.oxlintrc.json` present | yes |

---

## 1. Per-WU gate commands (run from the named dir; never `--no-verify`, never `git add -A`)

**Sidecar gate (run in `sidecar/`):**
```
ruff check media_studio tests
ruff format --check media_studio tests
basedpyright media_studio
pytest --cov=media_studio --cov-branch --cov-fail-under=100 -q
```
(For a focused WU loop, narrow with `pytest tests/test_refine.py --cov=media_studio.features.refine --cov-branch --cov-fail-under=100`, but the FINAL per-WU gate is the full-suite 100% line above — coverage is global, partial runs do not satisfy it.)

**Renderer gate (run in `app/`):**
```
npx oxlint
npx @biomejs/biome check renderer/src
npm run typecheck         # tsc --noEmit
npm run test:coverage     # vitest run --coverage  (thresholds 100/100/100/100)
```

**Staging discipline (all WUs):** `git add <explicit paths>` only; before each commit
`git diff --cached --name-only` and confirm scope. Conventional commits
(`feat:`/`test:`/`docs:`). Parallel agents share one index → scoped adds mandatory.

---

## 2. Work-Unit decomposition

Two test-first layers per code WU: write failing tests → watch fail → implement →
gate green. Fakes injected at the ffmpeg `run` seam, the silence `detect_run`
seam, the `duration` probe, the diarize backend factory, and the renderer `api`
bridge — NO real ffmpeg / model / network in any test.

---

### WU-0 — Branch + scaffold (no behavior)
- **Goal:** confirm working branch `feat/editing-refine-design`; create empty
  `docs/plans/editing-refine/PLAN.md` (this file) and the test-file placeholders'
  directory expectations. No source changes.
- **Files:** `docs/plans/editing-refine/PLAN.md` (this commit).
- **Test strategy:** none (docs). Existing suites must still pass.
- **Acceptance (falsifiable):** `git branch --show-current` == `feat/editing-refine-design`;
  full sidecar + renderer gates pass UNCHANGED from baseline (no regression introduced).
- **Deps:** none.

---

### WU-1 — `refine.plan_refine` (pure span/stat unifier)  ⟂ parallelizable
- **Goal:** NEW `features/refine.py` with a PURE
  `plan_refine(words, lang, total_sec, silences, *, remove_fillers, remove_silence, merge_gap_ms, pad_sec, filler_sets=None) -> RefinePlan`.
  It composes the EXISTING math only: filler keep-spans via
  `fillers.build_cutlist`/`build_cutlist_with_stats` (`fillers.py:284`/`:201`),
  silence keep-spans via `silencetrim.keep_spans` (`silencetrim.py:107`), unions
  them into ONE keep-list, and emits a typed
  `RefinePlan = {keeps:[[s,e]...], stats:{fillersRemoved:int, fillerSeconds:float, silenceRemovedSec:float, keptSec:float}}`.
  No subprocess, no model, no I/O. Stats mirror the shipped per-clip stats
  (`shortmaker.py` `{fillersRemoved, fillerSeconds}`) + silence `removed_seconds`
  (`silencetrim.py:150`).
  - **`filler_sets` threading (resolves the §4 `refine.fillerSets` setting — it must
    actually change the cut math, not be read-and-dropped):** the optional
    `filler_sets: Mapping[str, Mapping[str, frozenset]] | None` is passed straight to
    the engine's `fillers=` kwarg —`build_cutlist`/`build_cutlist_with_stats` already
    accept `fillers=` (default `DEFAULT_SETS`, `fillers.py:284`/`:201`, resolved per
    `_lang_sets`, `fillers.py:94`). `plan_refine` calls
    `build_cutlist_with_stats(words, lang, fillers=(filler_sets or fillers.DEFAULT_SETS), merge_gap_ms=...)`.
    `None` ⇒ shipped `DEFAULT_SETS` (back-compat, incl. the bundled `ro` set); a
    caller-supplied per-language override (e.g. an extended `ro`) genuinely changes
    which words are cut. This is the value path WU-5 reads `refine.fillerSets` into.
- **Files:** NEW `sidecar/media_studio/features/refine.py` (pure fns + `RefinePlan`
  typing + `__all__`); NEW `sidecar/tests/test_refine.py`.
- **Test strategy (100% line+branch):** hand-built `words` lists (filler + non-filler,
  sentence-boundary cases hitting `fillers.py:170` guard), hand-built fake
  `silences` spans. Branch matrix: `remove_fillers` ∈ {T,F} × `remove_silence` ∈ {T,F}
  (4 combos incl. both-off → keeps == whole `[[0,total_sec]]`), empty words, empty
  silences, overlapping filler∩silence spans (union must not double-count
  `keptSec`/seconds), `lang` falling back to `en` (`fillers.py:94`), zero-length
  total_sec edge. `filler_sets` branch: `None` (⇒ `DEFAULT_SETS`) vs a custom set —
  a custom `ro` override that marks an EXTRA word as filler must change the cut-list
  (proves the kwarg is threaded, not dropped). NO ffmpeg/model — `plan_refine` is pure.
- **Acceptance (falsifiable):**
  1. `plan_refine(..., remove_fillers=False, remove_silence=False)` returns
     `keeps == [[0.0, total_sec]]` and all `stats.*Removed*`/seconds == 0.
  2. Given one filler word [2.0,2.4] and one silence span [5.0,7.0] over total=10,
     `keeps` excludes BOTH ranges and `stats.fillerSeconds≈0.4`,
     `stats.silenceRemovedSec≈2.0`, `stats.keptSec≈7.6` (no double-count on
     disjoint spans).
  3. Overlapping filler-inside-silence collapses to ONE removed region; summed
     removed ≤ total and `keptSec == total - removed`.
  4. **filler-set override:** for `lang='ro'`, the SAME `words` with
     `filler_sets=None` keeps a word W, but with a `filler_sets` that adds W to the
     `ro` `standalone`/`always` set, `keeps` EXCLUDES W and `stats.fillersRemoved`
     increases by 1 — proving `refine.fillerSets` reaches the cut math.
  5. `pytest --cov=media_studio --cov-branch --cov-fail-under=100` green; ruff +
     basedpyright clean.
- **Deps:** none (pure reuse of already-shipped modules). **Parallel with WU-3, WU-4.**

---

### WU-2 — `RefineService` (preview + apply) over injected seams
- **Goal:** in `features/refine.py` add a `RefineService` whose `__init__` takes the
  SAME injectable seams pattern as `SilenceTrim.__init__` (`silencetrim.py:257`) —
  `resolver`, `out_dir`, `settings_provider`, `run`, `duration`, `detect_run` —
  PLUS the two project-store seams that the diarize feature already exposes and that
  WU-5 will pass through `refine.register`: `load_project`/`save_project` (the same
  callables `diarize.register` declares — `diarize.py:374` `load_project`/
  `save_project`, wired in `register_all` to `_load_project_data`/`_save_project_data`
  per the §0 anchor table). `preview`/`apply` read the transcript words via
  `load_project` (no direct I/O in the service body — the seam is faked in tests).
  - `preview(params, ctx) -> {plan}`: resolve clip (`resolver`), run
    `silencetrim.detect_silence_spans` via the injected `detect_run` (`silencetrim.py:159`),
    fetch transcript words via the `load_project` seam, call `plan_refine` (WU-1) —
    **threading `filler_sets=params.get("fillerSets")` straight into `plan_refine`'s
    `filler_sets=` param** (the `refine.fillerSets` value path; `None` ⇒ `DEFAULT_SETS`).
    **NO encode, NO file write** (Descript "see before you cut").
  - `apply(params, ctx) -> {path, removedSec, stats, cues?}` as a JOB: take a plan
    (or recompute via `plan_refine`, **passing the same `filler_sets`**), build argv
    with `fillers.build_segment_cut_argv` (`fillers.py:351`), run through the injected
    `run` seam (= `ffmpeg.run`) inside `ctx.jobs.start` (mirror diarize/silencetrim
    job pattern), write a NEW file `out_dir/{stem}.refined.mp4` (original untouched),
    and re-time caption cues via `fillers.remap_cues` (`fillers.py:324`).
- **Files:** EDIT `sidecar/media_studio/features/refine.py`; EDIT
  `sidecar/tests/test_refine.py`.
- **Test strategy (100%):** fake `resolver` (returns a path / returns None →
  not-found branch), fake `detect_run` returning canned silencedetect text, fake
  `run` (records argv, no subprocess), fake `duration`, fake `load_project`/
  `save_project` (returns transcript with words). Branches: clip-not-found;
  nothing-to-cut → pass-through path == original (matches `silencetrim.py:240-242`
  semantics); fillers-only; silence-only; both; cues present vs absent (remap vs
  skip); `fillerSets` present vs absent in `params` (override forwarded to
  `plan_refine` vs `DEFAULT_SETS`); job cancellation path (`ctx.jobs` fake
  raising/cancelled). Assert `build_segment_cut_argv` received the WU-1 keep-list and
  the OUTPUT path is the `.refined.mp4` sibling, never the input.
- **Acceptance (falsifiable):**
  1. `preview` calls `detect_run` exactly once and `run` ZERO times (no encode);
     returns `{plan}` whose stats equal `plan_refine` on the same inputs.
  2. `apply` with `keeps==[[0,total]]` (nothing to cut) returns the original path
     and `removedSec==0`, performing no re-encode (pass-through).
  3. `apply` with real cuts writes `*.refined.mp4` ≠ input path; returned `cues`
     equal `fillers.remap_cues(input_cues, keeps)`; `stats` equal the plan stats.
  4. `preview`/`apply` with `params["fillerSets"]` set forward that mapping to
     `plan_refine(..., filler_sets=<mapping>)` (asserted via the recorded
     `plan_refine` call or a stat delta vs the same params with no `fillerSets`);
     absent ⇒ `plan_refine` receives `None`/`DEFAULT_SETS`.
  5. Full sidecar gate green.
- **Deps:** WU-1.

---

### WU-3 — Subtitles speaker-carry (GAP #2 closed)  ⟂ parallelizable
- **Goal:** EDIT `subtitles.py` so the diarized `speaker` survives to cues/SRT/ASS/VTT.
  - `make_cue` (`subtitles.py:102`) gains an optional `speaker` param; sets it on
    the cue dict only when present (additive — frozen `index/start/end/text` keep
    their CONTRACTS.md §3 order/names).
  - `reindex` (`subtitles.py:107`) preserves an optional `speaker` key when the
    input cue has one (currently it strips everything but the 4 fields).
  - `cues_from_transcript` (`subtitles.py:125`) reads `seg.get("speaker")` and
    threads it through both the single-cue path and the `_split_segment`
    (`subtitles.py:152`) split path.
  - NEW pure helper `format_speaker_prefix(cues, *, on) -> cues` that prefixes
    `text` with `"<speaker>: "` when `on` and the cue has a speaker (immutable;
    new dicts). Setting `captionSpeakerLabels` (read in WU-5) drives `on`.
- **Files:** EDIT `sidecar/media_studio/features/subtitles.py`; EDIT
  `sidecar/tests/test_subtitles.py` (+ `test_subtitles_bilingual.py` if a split
  case needs a speaker fixture).
- **Test strategy (100%):** transcript segments WITH and WITHOUT `speaker`; a
  long segment forcing `_split_segment` (each split cue inherits the segment
  speaker); blank-segment drop still works; `reindex` round-trip keeps `speaker`
  when present and omits the key when absent (no `speaker:None` leakage);
  `format_speaker_prefix` with `on=True`/`on=False` × speaker-present/absent
  (4 branches). Assert SRT/ASS/VTT renderers still emit byte-identical output for
  the NO-speaker, prefix-off case (back-compat).
- **Acceptance (falsifiable):**
  1. `cues_from_transcript` on a diarized transcript yields cues each carrying the
     correct `speaker`; on a non-diarized transcript yields cues with NO `speaker`
     key (not `None`).
  2. `reindex` preserves `speaker` when present and produces no `speaker` key when
     absent.
  3. `format_speaker_prefix(on=False, ...)` is identity on text; `on=True` prefixes
     exactly `"SPEAKER_00: "` once and only on speaker-bearing cues.
  4. Existing subtitles tests unchanged-pass; full sidecar gate green at 100%.
- **Deps:** none. **Parallel with WU-1, WU-4.**

---

### WU-4 — `diarize.rename_speakers` (pure) + `diarize.rename` RPC (GAP #3)  ⟂ parallelizable
- **Goal:** in `diarize.py` add PURE
  `rename_speakers(transcript, mapping) -> transcript` (immutable, like
  `assign_speakers_to_segments`, `diarize.py:134`): rewrites each segment's
  `speaker` and the top-level `speakers` roster (`diarize.py:198`) via `mapping`
  (`{SPEAKER_NN: friendly}`); unmapped labels pass through unchanged; input never
  mutated. Add a direct-return RPC handler on the `Diarize` service that loads the
  project transcript (`load_project` seam), applies `rename_speakers`, persists via
  `save_project`, and returns `{transcript}`.
- **Files:** EDIT `sidecar/media_studio/features/diarize.py` (add fn + handler;
  register `diarize.rename` inside its existing `register`, `diarize.py:374`);
  EDIT `sidecar/tests/test_diarize.py`.
- **Test strategy (100%):** pure: empty mapping (identity), partial mapping
  (unmapped passes through), mapping a label not in transcript (no-op), roster +
  per-segment both rewritten, original dict unmutated (assert by identity/deep
  compare). RPC: fake `load_project`/`save_project`; assert persisted transcript
  == renamed and `{transcript}` returned; missing-project / no-transcript branch.
- **Acceptance (falsifiable):**
  1. `rename_speakers(t, {"SPEAKER_00":"Alex"})` returns a NEW dict where every
     `SPEAKER_00` (segments + roster) is `"Alex"`; `t` is byte-identical to before.
  2. `diarize.rename` handler calls `save_project` exactly once with the renamed
     transcript and returns `{transcript: <renamed>}`.
  3. `diarize.start` behavior unchanged (its tests still pass).
  4. Full sidecar gate green at 100%.
- **Deps:** none. **Parallel with WU-1, WU-3.**

---

### WU-5 — RPC registration + `subtitles.generate` speaker gate (the ONE site)
- **Goal:** wire all new RPCs at the single registrar `handlers.register_all`
  (`handlers.py:1982`), mirroring the silencetrim block (`:2176`) and diarize block
  (`:2219`):
  - `refine.register(resolver=svc._resolve_video_path, out_dir=svc.exports_dir/"refined",
    settings_provider=svc.settings.get, run=svc._ffmpeg_run, duration=svc._ffprobe_duration,
    load_project=_load_project_data, save_project=_save_project_data, register_fn=reg)`
    → registers `refine.preview` (direct) + `refine.apply` (job). Module owns its
    own `register()` (mirror `silencetrim.register`, `silencetrim.py:336`).
  - `diarize.rename` already registered in WU-4's `diarize.register` — confirm it
    appears via `register_fn=reg` at the existing diarize block.
  - EDIT `subtitles_generate` (`handlers.py:722`): after building cues, if
    `settings.get("captionSpeakerLabels")` (new key, mirrors the `captionPolish`
    gate at `handlers.py:738`), apply `subtitles.format_speaker_prefix(cues, on=True)`.
    `{track}` return shape UNCHANGED.
  - Read new settings keys with defaults: `refine.noiseDb`/`refine.minSilenceSec`/
    `refine.padSec` (reuse silencetrim defaults `silencetrim.py:57-60`),
    `refine.mergeGapMs` (`fillers.DEFAULT_MERGE_GAP_MS`, `fillers.py:44`),
    `refine.fillerSets` (per-language filler-set override of `fillers.DEFAULT_SETS`,
    `fillers.py:60`). **`refine.fillerSets` is not merely read — it is threaded into
    the cut math:** `subtitles_generate`/the refine path put it into the service call
    as `params["fillerSets"]`, which `RefineService` forwards to
    `plan_refine(..., filler_sets=...)` (WU-1/WU-2). When absent it falls back to
    `DEFAULT_SETS` (no behavior change). A WU-5 test asserts that a `refine.fillerSets`
    value reaches `plan_refine` (not dropped) — i.e. the setting and the DESIGN §4
    entry agree (this closes the prior plan↔DESIGN contradiction).
- **Files:** EDIT `sidecar/media_studio/handlers.py`; EDIT the relevant
  `sidecar/tests/test_handlers*.py` (match existing handler-test module).
- **Test strategy (100%):** fake `reg` registrar asserts the three new names
  (`refine.preview`, `refine.apply`, `diarize.rename`) registered exactly once;
  duplicate-registration loudness preserved (`protocol.register` default). For
  `subtitles_generate`: settings `captionSpeakerLabels` True (prefix applied) vs
  False/absent (no prefix) — both branches; diarized vs non-diarized transcript.
  Settings-default branches for each new `refine.*` key (present vs missing),
  including `refine.fillerSets` present → forwarded as `filler_sets` to `plan_refine`
  (asserted on a recorded service/`plan_refine` call) vs missing → `DEFAULT_SETS`.
- **Acceptance (falsifiable):**
  1. After `register_all`, the registrar received `refine.preview`, `refine.apply`,
     `diarize.rename` (and all pre-existing names still present — no displacement).
  2. `subtitles.generate` with `captionSpeakerLabels=True` on a diarized transcript
     returns cues whose text is speaker-prefixed; with the flag off/absent returns
     UNPREFIXED text identical to today (`{track}` shape unchanged).
  3. `refine.apply` is registered as a job, `refine.preview` as direct.
  4. A `refine.fillerSets` setting value reaches `plan_refine` as `filler_sets`
     (asserted, not dropped); absent ⇒ `DEFAULT_SETS`.
  5. Full sidecar gate green at 100%.
- **Deps:** WU-2 (service), WU-3 (format_speaker_prefix), WU-4 (rename handler).

---

### WU-6 — `Refine.tsx` renderer panel
- **Goal:** NEW `app/renderer/src/features/Refine.tsx` "Tighten the edit": calls
  `refine.preview` via the frozen bridge, renders the keep/cut list + saved-seconds
  + per-category stats, exposes **Remove fillers** / **Remove silence** toggles +
  tunables (noiseDb, minSilenceSec, mergeGapMs), then **Apply** → `refine.apply`
  job with progress. Both source and result surfaced. Same structure as
  `Diarize.tsx`: `getApi()`/`bridge.rpc`/`waitForJobDone`/`onProgress`
  (`Diarize.tsx:14,53,64,83-101`), injectable `api?` prop for tests
  (`Diarize.tsx:46-49`).
- **Files:** NEW `app/renderer/src/features/Refine.tsx`; NEW
  `app/renderer/src/features/Refine.test.tsx`.
- **Test strategy (100% lines/branches/functions/statements):** inject a fake
  `api` bridge (the `api?` prop, mirrors `Diarize.test.tsx`). Cover: initial
  render; preview success → list + saved-seconds rendered; preview error →
  error message; toggle states (fillers on/off × silence on/off) re-issue preview
  with correct params; Apply → job started, progress events update UI, done →
  result surfaced; Apply error branch; cancel path (`job.cancel`). `pickField`
  null-result branch. Every conditional render branch exercised.
- **Acceptance (falsifiable):**
  1. Mounting with a fake `api` and a stubbed `refine.preview` renders the proposed
     saved-seconds and per-category counts from the stub.
  2. Toggling "Remove silence" off re-calls `refine.preview` with
     `removeSilence:false` (asserted on the fake bridge).
  3. Clicking Apply dispatches `refine.apply`, processes a progress event, and on
     done shows the result path; an error result shows the error branch.
  4. `npm run test:coverage` meets 100/100/100/100; oxlint + biome + tsc clean.
- **Deps:** WU-5 (RPCs live). UI can be authored in parallel against the contract,
  but its acceptance test asserts against the real RPC names from WU-5.

---

### WU-6b — Mount `Refine.tsx` into the workspace (panel reachability)
- **Goal:** make the panel from WU-6 ACTUALLY OPENABLE — without this the feature
  ships dead-coded behind a green coverage gate (the DESIGN's headline "one Refine
  renderer panel the user can open" is not delivered until the workspace mounts it).
  Mirror EXACTLY how `Diarize` is wired in `app/renderer/src/views/Workspace.tsx`:
  - add a STATIC lazy import next to the existing ones
    (`const Refine = lazy(() => import('../features/Refine'));`, alongside
    `Workspace.tsx:32` `const Diarize = lazy(...)`);
  - add a `WORKSPACE_TABS` entry `{ id: 'refine', label: 'Refine' }`
    (`Workspace.tsx:35-47` — the data-driven tab list; **panel registration is this
    const array + the `renderPanel()` switch, NOT a CSS file** — `workspace.css`/
    `shorts.css` carry no per-panel id, so NO `.css` edit is required);
  - add a `case 'refine': return <Refine videoId={video.id} />;` to `renderPanel()`
    (`Workspace.tsx:122-147` switch; matches the `case 'diarize'` shape at `:126-127`).
  - Pick the tab position deliberately (e.g. directly after `'diarize'` in the
    system-advanced group) and keep WU-8's docs in sync with the chosen order.
- **Files:** EDIT `app/renderer/src/views/Workspace.tsx`; EDIT
  `app/renderer/src/views/Workspace.test.tsx`.
- **Test strategy (100% — Workspace.test.tsx already enforces vitest 100/100/100/100):**
  the test file already (a) asserts the contract tab list in order
  (`Workspace.test.tsx:122-126`) and (b) drives every `renderPanel()` case from a
  per-id marker table (`Workspace.test.tsx:227-232`, each panel `vi.mock`-stubbed via
  `stubPanel`, e.g. `:64` `vi.mock('../features/Diarize', ...)`). So this WU MUST:
  add `vi.mock('../features/Refine', () => stubPanel('Refine'))`; add `'Refine'` to
  the expected ordered-tabs assertion at the chosen position; add
  `['refine', 'Refine']` to the per-case render table so the new switch branch is
  covered. Without these three edits the new `case`/import/tab are uncovered lines →
  the 100% gate FAILS (this is the lever that prevents shipping the panel dead-coded).
- **Acceptance (falsifiable):**
  1. `WORKSPACE_TABS` contains `{ id: 'refine', label: 'Refine' }` and the
     ordered-tabs test asserts `'Refine'` at the chosen position.
  2. Selecting the Refine tab in `Workspace` mounts the panel: the per-case render
     test for `['refine','Refine']` finds the stubbed Refine marker after
     `onSelect('refine')`, exercising the new `renderPanel()` branch.
  3. `renderPanel()`'s new `case 'refine'` and the lazy import are covered (no new
     uncovered lines); `npm run test:coverage` meets 100/100/100/100; oxlint +
     biome + tsc clean.
- **Deps:** WU-6 (the panel component exists). **Parallel with WU-7** (disjoint
  files: WU-6b edits `Workspace.tsx`/`Workspace.test.tsx`; WU-7 edits `Diarize.tsx`/
  `Diarize.test.tsx`).

---

### WU-7 — `Diarize.tsx` speaker-rename block
- **Goal:** EDIT `app/renderer/src/features/Diarize.tsx`: add a per-speaker rename
  row (a text input per `SPEAKER_NN` from the roster) → `diarize.rename` →
  refresh roster/labels. Existing run/cancel/progress (`Diarize.tsx:62-114`)
  untouched. Reuse `extractSpeakers` (`Diarize.tsx:32`).
- **Files:** EDIT `app/renderer/src/features/Diarize.tsx`; EDIT
  `app/renderer/src/features/Diarize.test.tsx`.
- **Test strategy (100%):** fake `api`; cover: rename inputs rendered per speaker;
  editing + submit calls `diarize.rename` with the `{SPEAKER_NN: name}` mapping;
  success refreshes displayed labels; error branch; empty-roster branch (no inputs).
  Existing Diarize tests still pass.
- **Acceptance (falsifiable):**
  1. With a roster of two speakers, two rename inputs render.
  2. Renaming `SPEAKER_00`→"Alex" and submitting calls `diarize.rename` with
     `{ "SPEAKER_00": "Alex" }` and the panel then shows "Alex".
  3. Pre-existing Diarize run/cancel tests pass unchanged.
  4. `npm run test:coverage` 100/100/100/100; oxlint + biome + tsc clean.
- **Deps:** WU-4 (RPC), WU-5 (registered).

---

### WU-8 — Settings + docs reconciliation (close-out)
- **Goal:** document the new settings keys (`captionSpeakerLabels`, `refine.noiseDb`,
  `refine.minSilenceSec`, `refine.padSec`, `refine.mergeGapMs`, `refine.fillerSets`)
  in the settings/contracts doc(s) the repo already maintains; document
  `refine.fillerSets` as the per-language filler-set override that is THREADED into
  `plan_refine`'s `filler_sets=` param (matching DESIGN §4 — call out that it changes
  the cut math, not just config); record the chosen Refine workspace tab position
  (the `WORKSPACE_TABS` order from WU-6b) wherever the tab contract is documented;
  add the additive optional `Cue.speaker?` + `RefinePlan` to CONTRACTS.md §3
  (additive only — frozen fields unchanged). No code behavior.
- **Files:** EDIT the existing settings doc + CONTRACTS.md (whichever the repo uses;
  located at BUILD time — DESIGN cites CONTRACTS.md §2/§3).
- **Test strategy:** none (docs); both gate suites must remain green at 100%.
- **Acceptance (falsifiable):** every new settings key + new optional data field is
  documented; `refine.fillerSets`'s doc entry states it flows to `plan_refine`
  (`filler_sets`); the Refine tab position is recorded; `git grep` finds each key
  name in both code and docs; full sidecar + renderer gates green (no regression).
- **Deps:** WU-5, WU-6, WU-6b, WU-7 (final names + tab order settled).

---

## 3. Dependency graph

```
                WU-0 (branch + this PLAN doc)
                  |
   +--------------+--------------+
   |              |              |
 WU-1          WU-3           WU-4          (all pure / leaf — PARALLEL)
 plan_refine   subtitles      diarize.rename
   |           speaker-carry  rename_speakers
   |              |              |
 WU-2            |              |
 RefineService   |              |
   |             |              |
   +------+------+------+-------+
          |
        WU-5  (register_all: refine.* + diarize.rename + subtitles gate)  [ONE RPC site]
          |
   +------+------+
   |             |
 WU-6          WU-7            (renderer — PARALLEL with each other)
 Refine.tsx    Diarize rename block
   |             |
 WU-6b          |             (mount Refine into Workspace — depends on WU-6)
 Workspace wire |
   |             |
   +------+------+
          |
        WU-8  (settings + contracts docs close-out)
```

## 4. Parallelism notes
- **Wave A (parallel, leaf):** WU-1, WU-3, WU-4 — disjoint files
  (`refine.py`, `subtitles.py`, `diarize.py` + their own test files), no shared
  edits. Run as 3 parallel agents in **isolated worktrees** (parallel agents on a
  shared index contaminate commits — use `Agent(isolation:worktree)` or scoped
  `git add` + `git diff --cached --name-only` before every commit).
- **WU-2** depends only on WU-1 → starts as soon as WU-1 lands.
- **Wave B (serializing point):** WU-5 edits the single `handlers.py` registrar +
  `subtitles_generate` and depends on WU-2/WU-3/WU-4. It is the ONE shared file —
  give it a single owner; do not parallel-edit `handlers.py`.
- **Wave C (parallel):** WU-6 and WU-7 are disjoint renderer files
  (`Refine.tsx` new; `Diarize.tsx` edit) — parallel after WU-5. **WU-6b**
  (mount `Refine.tsx` into `Workspace.tsx`/`Workspace.test.tsx`) runs after WU-6 and
  is disjoint from WU-7, so WU-6b ∥ WU-7. WU-6b is what makes the panel reachable —
  without it the Refine panel ships dead-coded behind the 100% gate.
- **WU-8** last (needs final names; also records the chosen Refine tab position).
- **AI (deferred):** the optional "smart refine"/caption-cleanup touchpoint is NOT
  a WU here. When built it adds exactly one path through `plan_ai_job`/`run_ai_job`
  (`models/ai_job.py`) gated by `handlers.plan_ai_job_envelope` (`handlers.py:1601`)
  with provider selection from `models/provider.py` — no new consent/budget code.

## 5. Reuse-vs-new (one glance)
- **REUSE unchanged:** `fillers.py` (cutlist/argv/remap), `silencetrim.py`
  (detect/keep/removed), `diarize.py` engine + backends, `ffmpeg.run`,
  `jobs.JobContext`, project store seams (`_load_project_data`/`_save_project_data`/
  `_resolve_video_path`/`_ffmpeg_run`/`_ffprobe_duration`), AI envelope +
  rotation pool (deferred AI only).
- **NEW:** `features/refine.py` (`plan_refine` with `filler_sets` threading +
  `RefineService.preview/apply` + `register`); `diarize.rename_speakers` +
  `diarize.rename` RPC; subtitles speaker-carry edits + `format_speaker_prefix`;
  `Refine.tsx` + its `Workspace.tsx` mount wiring (lazy import + `WORKSPACE_TABS`
  entry + `renderPanel()` `case`, WU-6b); `Diarize.tsx` rename block; settings
  `captionSpeakerLabels` + `refine.*` (incl. `refine.fillerSets` threaded to the cut
  math); optional `Cue.speaker?` + `RefinePlan` contract additions.
- **GAPS closed:** standalone previewable filler/silence RPC (WU-1/2/5) reachable in
  the UI (WU-6 + WU-6b mount); speaker→caption plumbing (WU-3); speaker rename (WU-4). **GAPS deferred
  (documented, unchanged):** word-level/waveform editor; per-speaker caption
  styling; overlapping-speaker diarization; auto filler-language expansion;
  semantic (vs amplitude) silence; smart-AI refine.
