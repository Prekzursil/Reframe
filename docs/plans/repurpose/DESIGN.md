# Repurpose Bundle — Design Doc

**Status:** v1 — DESIGN (awaiting Design Review Gate)
**Date:** 2026-06-18
**Owner:** Reframe Media Studio
**Branch:** `feat/repurpose-design` (docs only — no feature code)
**Scope:** three repurposing capabilities that turn long/many source videos into platform-ready output at scale:
1. **Batch queue** — process many source videos through a pipeline with progress + resume.
2. **Reusable edit templates** — save an edit-recipe (a workflow) once, apply it to new sources.
3. **Multi-platform export presets** — TikTok / Reels / Shorts aspect ratios + caption styles + duration targets, applied per-platform in one pass.

> **RAILS honored.** Every claim below cites real code (`file:line`). Where a capability does **not** exist today it is named explicitly as a **GAP** with the smallest reuse-based fill. The bundle is **docs only** here; the eventual BUILD rides the shipped Hub substrate (AI-Job envelope, rotation pool, `handlers.register_all`) and clears the standing gates (sidecar `pytest --cov-branch --cov-fail-under=100`; renderer vitest `thresholds:100`; ruff / oxlint / biome / basedpyright / tsc; never `--no-verify`; never `git add -A`).

---

## 1. Problem & motivation

A creator who wants to "repurpose" content is rarely working with one clip. They have **a folder of 30 podcast episodes** and want vertical shorts from each; they have **a house style** (transcribe → polish captions → make 5 shorts → package) they re-run for every upload; and they ship the **same clip to three platforms** (TikTok 9:16 / Reels 9:16 / YouTube Shorts 9:16) with platform-specific caption styles and duration windows.

The codebase already has every *primitive* this needs:

- **A pipeline runner over many steps** — `features/recipes.py` (`recipes.run`, lines 256-300) runs a saved `[{method, params}]` recipe as ONE job, awaiting any `{jobId}` sub-job and relaying scaled progress (`_await_subjob`, lines 323-359), with `$N.key` references threading one step's output into the next (`resolve_refs`, lines 133-153).
- **A many-item batch** — `features/convert.py` `convert_batch` (`handlers.py:1007`) → `batch_handler` (`convert.py:281`) → `convert_batch` (`convert.py:195-238`) iterates a list of items, spreads progress evenly, honors per-item cancellation, returns `{paths}`.
- **Platform presets** — `app/renderer/src/features/shortMakerPresets.ts` `PLATFORM_PRESETS` (tiktok/reels/shorts, all 9:16, distinct `count`/`maxSec`) + `applyPreset` already exist for the single-video Short Maker.
- **The render engines** — `features/reframe.py` (`ReframeEngine`, 1080×1920 9:16, WSL/verthor with claudeshorts fallback, `get_engine`/`resolve_engine_name`) and `features/shortmaker.py` (`ShortMaker.export`, `run_export`, `Stages`).
- **A bounded job pool** — `jobs.py` `JobRegistry` (2 workers; gpu-tagged serialized to 1; FIFO queue; `job.list`/`job.retry`).

**What is missing is composition and durability:** there is no way to (a) point a pipeline at *many sources* and watch one aggregate job; (b) save the recipe AND its per-platform export fan-out as a reusable named "template"; (c) **resume** a batch after the app restarts (the job registry is in-memory only — `jobs.py:204` `self._jobs: dict` — so a crash or quit loses all queue + progress state). The Repurpose bundle composes the primitives and adds the one missing durability layer.

---

## 2. Goals

- **G1 — Batch over many sources:** one queue that runs a chosen pipeline (a recipe template) against N library videos, with aggregate + per-source progress and per-source pass/fail isolation (one bad source must not sink the batch).
- **G2 — Resume:** a batch survives a sidecar/app restart — completed sources stay completed, in-flight/queued sources re-enqueue, nothing re-does finished work.
- **G3 — Reusable edit templates:** save a workflow (recipe steps + default controls + export targets) under a name; apply it to any new source(s) without re-typing. Generalize `recipes.*` rather than fork it.
- **G4 — Multi-platform export presets:** extend the existing 9:16 platform presets into first-class, server-persisted presets carrying aspect + caption style + duration target (min/max sec) + clip count, and fan ONE source out to multiple platform presets in one batch run.
- **G5 — Reuse the job model + render engines:** every long-running step runs on the existing `JobRegistry`; every render goes through `ShortMaker.export` / `ReframeEngine` — NO new media logic, NO second job bus.
- **G6 — Reuse the Hub envelope for AI parts:** any step that calls a provider (`shortmaker.select`, `phase8.select`, `subtitles.translate`) keeps riding `run_ai_job` (consent + budget pre-flight + cache + degrade), unchanged. The batch layer adds NO new provider call site.
- **G7 — Quality bar:** 100% line+branch sidecar coverage; renderer UI to 100%; reversible/safe by default; no secrets logged.

## 3. Non-goals

- **Scheduling / unattended cron / watch-folder ingestion.** A batch is user-initiated. (A watch-folder is a clean later add on top of `batch.enqueue`.)
- **Distributed / multi-machine execution.** Single host, the existing 2-worker pool.
- **New AI capabilities or new providers.** The bundle orchestrates existing methods; the Hub already owns model routing.
- **A second persistence engine (DB/vector store).** Resume uses the same atomic JSON-document pattern `settings_store` / `RecipeStore` already use (`recipes.py:177-181`).
- **Re-implementing reframe/caption rendering.** The engines exist; we call them.

---

## 4. Capability inventory — what exists vs. what is NEW (cited)

| Need | Exists today | Cite | Verdict |
|------|--------------|------|---------|
| Run a multi-step pipeline as one job | `recipes.run` + `_run_steps` + `_await_subjob` | `recipes.py:256,279,323` | **REUSE** (template = recipe) |
| Iterate many items, spread progress, per-item cancel | `convert_batch` | `convert.py:195` | **REUSE pattern** (generalize from convert-only to any pipeline) |
| Sub-job awaiting + progress relay | `Recipes._await_subjob` | `recipes.py:323` | **REUSE** |
| Step-to-step data references | `resolve_refs` (`$N.key`) | `recipes.py:133` | **REUSE** |
| Save/list/delete named pipelines | `RecipeStore` (atomic JSON) | `recipes.py:159` | **REUSE / extend** |
| Platform presets (aspect/maxSec/count) | `PLATFORM_PRESETS`, `applyPreset` | `shortMakerPresets.ts` | **REUSE renderer; PROMOTE to sidecar-persisted** |
| Build export params from controls | `buildExportParams` | `shortMakerPresets.ts` | **REUSE** |
| Vertical render 1080×1920 + engine fallback | `ReframeEngine`, `get_engine` | `reframe.py:44,207` | **REUSE** |
| Short export pipeline (reframe+caption+mux) | `ShortMaker.export`, `run_export` | `shortmaker.py:1206,1048` | **REUSE** |
| Bounded job pool, queue, retry, cancel | `JobRegistry` | `jobs.py:179` | **REUSE** |
| Caption styles (karaoke/hormozi/tiktok/clean) | `REMOTION_CAPTION_TEMPLATES`, `CAPTION_STYLE_OPTIONS` | `captionTemplates.ts:56`, `shortMakerLogic.ts:198` | **REUSE** |
| Settings persistence (free-form keys) | `SettingsStore`, `DEFAULT_SETTINGS` | `settings_store.py:41` | **REUSE** |
| The single RPC registration site | `register_all` | `handlers.py:1982` | **EXTEND** (new modules' own `register()`) |
| **Batch queue over many sources** | — | — | **NEW: `features/batch.py`** |
| **Resume across restart (durable job state)** | — (`jobs.py:204` in-memory only) | — | **NEW: `BatchStore` + run-resume; GAP §10.1** |
| **Per-platform export fan-out as one run** | — (single-video only in UI) | — | **NEW: preset fan-out in batch step expansion** |
| **Server-persisted platform presets** | — (renderer-const only) | `shortMakerPresets.ts` | **NEW: `features/export_presets.py`** |

---

## 5. Architecture

Three small **new** sidecar feature modules, each following the established "owns its own `register()`, injectable seams, pure logic + JSON persistence" pattern (`recipes.register`, `shorts.register`). NO new provider call sites; NO second job bus.

```
features/
  batch.py            NEW  batch.* — queue many sources through a template; durable; resumable
  export_presets.py   NEW  exportPresets.* — server-persisted platform presets (aspect/style/dur/count)
  templates.py        NEW  templates.* — a thin superset of recipes (steps + default controls + export targets)
                          (alternatively: extend recipes.py in place — see §5.4 decision)
models/
  (none new)               batch steps reuse run_ai_job via the existing AI handlers; no new model code
```

### 5.1 Templates = recipes + export intent (`features/templates.py` or extended `recipes.py`)

A **template** is the durable, reusable "edit recipe" of G3. It is a recipe (`{id, name, steps:[{method, params, label}]}`, `recipes.py:80-114`) PLUS two additive fields:

- `defaultControls` — a `ShortMakerControls`-shaped object (`shortMakerLogic.ts:48-66`: `count/minSec/maxSec/aspect/language/captionStyle/reframeEngine/...`) used as the step params' base, so the user saves "my house style" once.
- `exportTargets` — a list of platform-preset ids (`["tiktok","reels","shorts"]`) the export step fans out to (§5.3).

The runner is **unchanged from `recipes._run_steps`** (`recipes.py:279`): each step's `method` is resolved on the live `protocol.METHODS` registry, invoked, and `{jobId}` results are awaited via `_await_subjob`. `$N.key` references still thread output forward. The only new logic is **step expansion**: before running, a single `shortmaker.export` step whose params name multiple `exportTargets` is expanded into one export call per platform preset (§5.3), so a template targeting 3 platforms produces 3 export sub-steps with merged params.

**Reuse-vs-new:** the recipe storage (`RecipeStore`, atomic temp+rename, `recipes.py:159-208`), normalization (`normalize_recipe`, `recipes.py:80`), reference resolution, and the whole sub-job runner are REUSED verbatim. New = the two extra normalized fields + the expansion function (pure, fully testable).

### 5.2 Batch queue (`features/batch.py`)

A **batch** = `{id, name, templateId, sourceVideoIds:[...], status, items:[BatchItem]}` where a `BatchItem` = `{videoId, status: "queued"|"running"|"done"|"error"|"cancelled", jobId?, error?, results?}`. It runs each source through the named template **as a nested recipe run**, so one batch = one parent job that drives N per-source recipe runs.

- **Execution shape** mirrors `convert_batch` (`convert.py:195-238`): iterate `sourceVideoIds`, spread the parent job's `[0,100]` progress across items, honor cancellation between items (`job_ctx.raise_if_cancelled`, `recipes.py:285`). Per-source isolation: a source whose template run errors is recorded `error` on its `BatchItem` and the batch **continues** (NOT the convert behavior, which aborts — this is the one deliberate divergence, §10.3).
- **Per-source run** = invoke the template runner for that `videoId` (binding the template's steps to this source, e.g. `transcribe.start {videoId}` → … → `shortmaker.export`). Because the template runner returns `{jobId}`, the batch awaits it with the SAME `_await_subjob` relay (`recipes.py:323`) — no new waiting code.
- **The job pool does the throttling.** Each per-source recipe run already starts sub-jobs on `ctx.jobs` (the 2-worker pool, `jobs.py:199`); the batch does not need its own concurrency control. GPU-heavy steps (Phase-8 signals) already serialize via the `gpu=True` tag (`jobs.py:345`).

### 5.3 Multi-platform export presets (`features/export_presets.py`)

Promote the renderer-only `PLATFORM_PRESETS` (`shortMakerPresets.ts`) to a **server-persisted, editable** catalog so a template can reference preset ids and a batch can fan out to them.

- A `ExportPreset` = `{id, label, aspect, minSec, maxSec, count, captionStyle, reframeEngine}` — exactly the controls fields `shortmaker.export` already consumes via `buildExportParams` (`shortMakerPresets.ts`) → `ShortMaker.export` (`shortmaker.py:1206`, which reads `reframeEngine`/`captionStyle` from params, line 1215).
- **Seeded** with the three existing presets (tiktok/reels/shorts, all 9:16) so behavior matches the current UI on day one. The §5 hard window clamp (20-60 s, enforced in BOTH `sanitizeControls` and the sidecar `select._resolve_window` → `MAX_CLIP_SEC=60`, documented at `shortMakerPresets.ts`) is REUSED — presets cannot promise a window the pipeline silently corrects.
- **Fan-out** (the NEW expansion in §5.1): a batch/template export step listing `exportTargets:["tiktok","shorts"]` produces, per source, one `shortmaker.export` call per preset, each merging the preset fields onto the template's `defaultControls`. Output lands in the existing per-video export dir (`exports/shorts-<videoId>`, `handlers.py:1351`) with the preset id in the clip metadata so the Shorts gallery (`shorts.list`) can group by platform.
- **YouTube landscape note:** the brief lists "YT" — `reframe.output_dimensions` (`reframe.py:96`) already handles non-9:16 ratios (landscape fixes width to 1920). A `youtube` preset at `16:9` is therefore expressible with the existing engine; seeded but flagged in §10.4 (the reframe SCRIPT is tuned for vertical subject-tracking — a 16:9 pass-through is a thinner path).

### 5.4 Decision: extend `recipes.py` vs. new `templates.py`

**Recommendation (for the gate):** add `templates.py` as a thin module that REUSES `RecipeStore`/`normalize_recipe`/`Recipes._run_steps` by import, rather than mutating `recipes.py`. Rationale: keeps the proven `recipes.*` surface and its 100%-covered tests untouched (the standing coverage gate, CLAUDE.md), and keeps each file < 800 lines (coding-style rule). The alternative — adding `defaultControls`/`exportTargets` to `normalize_recipe` — is fewer files but mutates a frozen, fully-tested wire shape. **GATE QUESTION (F-template-shape):** confirm new-module vs. in-place extension.

---

## 6. RPC surface (new `*.*` handlers in `register_all`)

All registered through the existing single composition root (`handlers.py:1982` `register_all`), each via the module's own `register(...)` helper bound to the Services' `data_dir`/`settings`/`jobs` (mirrors `_recipes.register`, `handlers.py:2205`). Long-running → `{jobId}`; CRUD → direct-return.

### `exportPresets.*` (direct-return CRUD)
| Method | Params | Result | Notes |
|--------|--------|--------|-------|
| `exportPresets.list` | — | `{presets:[ExportPreset]}` | seeded with tiktok/reels/shorts |
| `exportPresets.save` | `{preset}` | `{preset}` | upsert by id; window-clamped on save |
| `exportPresets.delete` | `{id}` | `{ok}` | built-in seeds restorable via `reset` |
| `exportPresets.reset` | — | `{presets}` | restore the seeded defaults |

### `templates.*` (CRUD direct; one long job)
| Method | Params | Result | Notes |
|--------|--------|--------|-------|
| `templates.list` | — | `{templates:[Template]}` | reuses `RecipeStore` over `templates.json` |
| `templates.save` | `{template}` | `{template}` | normalize = recipe-normalize + `defaultControls`/`exportTargets` |
| `templates.delete` | `{id}` | `{ok}` | |
| `templates.apply` | `{templateId, videoId}` | `{jobId}` | run the template against ONE source (the single-source path; sugar over `batch.start` with one item) |

### `batch.*` (CRUD + the queue)
| Method | Params | Result | Notes |
|--------|--------|--------|-------|
| `batch.create` | `{name, templateId, sourceVideoIds}` | `{batch}` | persists a `BatchState` (queued items) — durable |
| `batch.start` | `{id}` | `{jobId}` | the long parent job; per-source isolation; resumable |
| `batch.status` | `{id}` | `{batch}` | aggregate + per-item status (read from store + live job) |
| `batch.list` | — | `{batches:[BatchSummary]}` | including finished ones |
| `batch.cancel` | `{id}` | `{ok}` | cancels the parent job (→ cooperative item cancel, `jobs.py:447`) |
| `batch.resume` | `{id}` | `{jobId}` | re-enqueue not-yet-done items (§10.1) |
| `batch.delete` | `{id}` | `{ok}` | drops a finished/cancelled batch record |

**No new provider RPC.** Every AI-bearing step a template runs (`shortmaker.select`, `phase8.select`, `subtitles.translate`) is an EXISTING method that already enters `run_ai_job` (`handlers.py:849,1292`). The batch/template layer never builds a provider, never reads a key — it only invokes already-wired handlers through `protocol.METHODS` (the `recipes` mechanism, `recipes.py:313-317`). This keeps the "ONE RPC site" and "AI rides the envelope" invariants intact.

---

## 7. Renderer surface

A new **Repurpose** view (tab in `TabBar.tsx` / `App.tsx`), composed of three panels, all driven through the canonical client (`lib/rpc.ts`). New typed client groups mirror the recipe group already there (`rpc.ts:757-763`):

- `client.exportPresets.{list,save,delete,reset}`
- `client.templates.{list,save,delete,apply}`
- `client.batch.{create,start,status,list,cancel,resume,delete}`
- New TS interfaces in `rpc.ts` (§3 schema block): `ExportPreset`, `Template`, `BatchItem`, `BatchState`, `BatchSummary` — field names identical to the sidecar (the house rule, `rpc.ts:17`).

Panels (under `renderer/src/features/` and `renderer/src/views/`):
1. **TemplateEditor** — pick steps (from a method allowlist), set `defaultControls` (REUSE `shortMakerLogic` `DEFAULT_CONTROLS`/`sanitizeControls` + `shortMakerPresets` `buildExportParams`), choose `exportTargets`. Save via `templates.save`.
2. **ExportPresetsPanel** — table of presets, edit aspect/style/min-max-sec/count; REUSE `PLATFORM_PRESETS` as the seed view + `CAPTION_STYLE_OPTIONS` (`shortMakerLogic.ts:198`) for the style picker.
3. **BatchQueue** — multi-select library videos (REUSE the native multi-picker `window.api.openVideos`, `rpc.ts:438`), pick a template, `batch.create` → `batch.start`. Live aggregate + per-source rows driven by `onProgress`/`onJobDone` (`rpc.ts:473,478`) and `batch.status` polling; a **Resume** button calls `batch.resume` for any batch left incomplete (visible on relaunch). REUSE the existing `JobQueue.tsx` / `ProgressBar.tsx` components for row rendering.

Progress relay: the parent batch job's `job.progress` carries `"source k/N · <title> · step j/M · <label>"` (extends the recipe runner's existing `"step k/N · <label>"` message, `recipes.py:293`).

---

## 8. Data / storage + settings keys

All persistence is the **atomic temp+rename JSON document** pattern already used by `settings_store` and `RecipeStore` (`recipes.py:177-181`) — under the per-user data dir (`Services.data_dir`, `handlers.py:143`), never a project folder.

| File (under `data_dir`) | Owner | Shape |
|--------------------------|-------|-------|
| `templates.json` | `templates.py` (reuses `RecipeStore`) | `[Template]` |
| `export-presets.json` | `export_presets.py` | `[ExportPreset]` (seeded) |
| `batches/<batchId>.json` | `batch.py` (`BatchStore`) | `BatchState` — per-batch file so a large run's checkpoint write is O(1) and a corrupt batch can't poison others |

**Settings keys (additive to `DEFAULT_SETTINGS`, `settings_store.py:41`):**
- `repurposeDefaultTemplate: string` — last-used template id (UX convenience).
- `repurposeExportTargets: string[]` — default platform fan-out (seed `["tiktok"]`).
- `batchContinueOnError: boolean` (default `true`) — the per-source isolation toggle (§10.3).

Reuse the existing `defaultTargetJobSize` (`settings_store.py:69`, consumed by `_default_target_job_size`, `handlers.py:1743`) as the per-source short-count default when a preset omits `count`.

`BatchState` (the resume contract):
```jsonc
{
  "id": "batch-ab12",
  "name": "Podcast season 3 → shorts",
  "templateId": "tmpl-housestyle",
  "status": "running",          // queued|running|done|error|cancelled|partial
  "createdAt": 1781757400.0,
  "items": [
    { "videoId": "vid-1", "status": "done",   "results": {...} },
    { "videoId": "vid-2", "status": "error",  "error": "transcribe failed: ..." },
    { "videoId": "vid-3", "status": "queued" }
  ]
}
```

---

## 9. Reversibility / safety + AI consent/budget

- **Reversible by construction.** Templates and presets are JSON CRUD; deleting a batch never touches produced media (it lives under `exports/shorts-<videoId>`, owned by the existing shorts library, `handlers.py:2133`). `exportPresets.reset` restores seeds. No in-place edits to source media — every render writes a NEW derivative (the `ShortMaker.export` contract).
- **Cancellation is cooperative + already proven.** `batch.cancel` sets the parent job's flag (`jobs.py:447`); the batch loop's `raise_if_cancelled` (`recipes.py:285`) stops between sources and cancels the in-flight sub-job (`_await_subjob`, `recipes.py:345-347`). No new cancellation machinery.
- **AI consent + budget ride the Hub envelope, unchanged.** The batch never calls a provider directly. When a template step is `shortmaker.select`/`phase8.select`/`subtitles.translate`, those handlers already build the envelope via `_run_ai_job` (`handlers.py:1617`) and enforce the budget-ack gate `_enforce_cloud_budget_ack` (`handlers.py:1672`): if `confirmCloudBudget` is on and the run would egress, the step requires the `ai.planJob` `cacheKey` as `confirmBudget`.
  - **Batch consequence (GAP §10.2):** a fully-unattended N-source batch can't interactively pre-flight each source's AI step. The envelope's `cacheKey` is per-request, so a batch-wide blanket ack would not match. **Design decision for the gate:** the batch surfaces a single **pre-run consent summary** (one `ai.planJob` per distinct step shape via the existing pure planner, ZERO provider calls — `handlers.py:1693`) and requires the user to acknowledge cloud egress for the whole batch ONCE; if `confirmCloudBudget` is on, the batch either (a) runs only sources whose AI steps are cache hits / local-only, or (b) is refused with the same typed message until the user disables the per-call gate or chooses an all-local routing preset. Frame/text consent (`providers.setConsent`, `handlers.py:414`) is unchanged and still enforced per-entry at pool construction (`handlers.py:597`). **GATE QUESTION (F-batch-consent):** confirm (a) skip-non-acked vs. (b) refuse-batch as the default.
- **No secrets in batch state.** `BatchState`/results store method results, never keys; the redaction invariants (`providers.list`, `handlers.py:330`) are untouched because the batch never reads raw provider config.

---

## 10. Explicit capability gaps

### 10.1 — Durable/resumable jobs do NOT exist today (the headline gap)
`JobRegistry` is purely in-memory: `self._jobs: dict` (`jobs.py:204`), threads are daemon (`jobs.py:372`), no state is written to disk. A restart loses every queue position, progress %, and result. **Resume (G2) therefore cannot be built on the job registry — it must be built at the BATCH layer.** Fill: `BatchStore` checkpoints `BatchState` after each item transition (queued→running→done/error). `batch.resume` reads the file, treats `done` items as complete, and re-enqueues `queued`/`running`/(optionally `error`) items as a fresh parent job. **Resume is at SOURCE granularity, not mid-source step granularity** — a source that crashed at step 3 of 5 re-runs from step 1 (its earlier outputs are idempotent overwrites; transcribe persists onto the project and flips `hasTranscript`, `handlers.py:1068-1072`, so a re-run is cheap-ish but not free). True mid-pipeline resume would require per-step checkpointing in the recipe runner — **out of scope; named here.**

### 10.2 — Unattended budget pre-flight is awkward under `confirmCloudBudget`
The per-request `cacheKey` ack model (`handlers.py:1672-1691`) is built for interactive single runs. A batch needs a batch-level consent story (§9). No code change to the envelope is proposed; the gap is a UX/policy decision (the F-batch-consent gate question).

### 10.3 — `convert_batch` aborts on first error; batch needs per-source isolation
`convert_batch` (`convert.py:195-238`) and the recipe runner (`_run_one_step` re-raises, `recipes.py:314-321`) FAIL the whole run on a single error. The batch deliberately diverges: it catches a per-source run failure, records it on the `BatchItem`, and continues (gated by `batchContinueOnError`, default on). This is NEW per-source try/except wrapping the existing runner — not a change to the runner itself.

### 10.4 — Reframe engine is vertical-subject-tracking; landscape (YT 16:9) is a thin path
`reframe.output_dimensions` supports arbitrary ratios (`reframe.py:96-115`), but the WSL/verthor script and the claudeshorts fallback are tuned for 9:16 subject-following (`reframe.py:6-9`). A `youtube` 16:9 preset is expressible but is effectively a duration/caption variant of the source aspect, not a true reframe. Seeded but documented as such; full landscape repurposing (e.g. 1:1 square, 4:5) needs engine validation per ratio — named, not solved here.

### 10.5 — Caption-style ↔ preset coupling is by-id only
Presets reference a `captionStyle` id; the renderer/sidecar style sets must stay in sync (already enforced by `captionTemplates.conformance.test.ts`, `captionTemplates.ts:8`). A preset persisting an id that a later build removes would fall back to the default style (same tolerance `readBrandSettings` already applies, `shortMakerPresets.ts`). No new risk, but the preset store must validate ids against `CAPTION_STYLE_OPTIONS` on save (mirrors `setFunctionModel`'s function-id guard, `handlers.py:514`).

### 10.6 — `templates.run` step allowlist
A template runs arbitrary `protocol.METHODS` by name (the recipe model). For a saved/shared template this is a (local-only) capability surface. Fill: a normalize-time allowlist of repurpose-relevant methods (`transcribe.*`, `subtitles.*`, `shortmaker.*`, `phase8.select`, `nle.export`, `package.export`, convert/audio steps) — reject unknown/dangerous method names at `templates.save`, same fail-loud posture as `normalize_recipe` (`recipes.py:98`).

---

## 11. Build sequencing (for the PLAN, not built here)

1. `export_presets.py` + `exportPresets.*` + seeds + renderer ExportPresetsPanel (smallest, unblocks fan-out).
2. `templates.py` (reuses `RecipeStore`/runner) + `templates.*` + TemplateEditor + step expansion (§5.1) + allowlist (§10.6).
3. `batch.py` + `BatchStore` + `batch.*` + per-source isolation (§10.3) + BatchQueue panel.
4. Resume (§10.1) — `batch.resume` + checkpoint-on-transition + the relaunch "incomplete batch" surface.
5. Batch consent summary (§9 / §10.2) once the gate picks (a) or (b).

Each work unit: TDD first; sidecar `pytest --cov-branch --cov-fail-under=100`; renderer vitest 100%; ruff/oxlint/biome/basedpyright/tsc green; commit scoped (never `git add -A`), never `--no-verify`.

## 12. Open gate questions

- **F-template-shape (§5.4):** new `templates.py` (recommended) vs. extend `recipes.normalize_recipe` in place.
- **F-batch-consent (§9/§10.2):** default to (a) run-only-non-egressing under `confirmCloudBudget`, or (b) refuse-batch-until-acked.
- **F-resume-granularity (§10.1):** confirm source-level resume is acceptable for v1 (mid-pipeline checkpointing deferred).
- **F-error-policy (§10.3):** confirm `batchContinueOnError` default `true`.
- **F-youtube (§10.4):** include a seeded 16:9 `youtube` preset in v1, or vertical-only until landscape reframe is validated.
