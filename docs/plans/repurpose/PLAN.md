# Repurpose Bundle — Implementation PLAN

**Status:** v1 — PLAN (derived from `docs/plans/repurpose/DESIGN.md`, design-gate passed after revision)
**Date:** 2026-06-18
**Branch:** `feat/repurpose-design` (this bundle works on its OWN branch off `origin/main`; clone fresh to a unique temp path per agent)
**Scope:** DESIGN + PLAN docs only. No feature code is written under this PLAN — it is the build map for a later execution phase.

> **RAILS honored.** Every WU below is grounded in code verified against a fresh clone of `feat/repurpose-design` (see §0 verification ledger; all `file:line` citations re-checked). Capability gaps are named, never hidden. The BUILD reuses the shipped Hub substrate (AI-Job envelope `_run_ai_job`/`ai.planJob`, rotation pool, the single RPC site `register_all`). Standing BUILD gates per WU: sidecar `pytest --cov-branch --cov-fail-under=100`; renderer `vitest run --coverage` (thresholds 100 lines/branches/functions/statements, `app/vitest.config.ts:44-49`); `ruff` / `oxlint` / `biome` / `basedpyright` / `tsc --noEmit`. Never `--no-verify`; never `git add -A` (scoped adds only).

---

## 0. Code-grounding verification ledger (re-checked on fresh clone, commit `a912221`)

| Claim used by the PLAN | Cite | Verified |
|------------------------|------|----------|
| `recipes.run` parent-job runner | `sidecar/media_studio/features/recipes.py:256` | ✓ |
| `Recipes._run_steps` step loop + cancel | `recipes.py:279` (`raise_if_cancelled` `recipes.py:285`) | ✓ |
| `Recipes._await_subjob` sub-job progress relay | `recipes.py:323` | ✓ |
| `resolve_refs` (`$N.key` threading) | `recipes.py:133` | ✓ |
| `RecipeStore` atomic JSON (`_write` temp+rename) | `recipes.py:159` (write `recipes.py:177`) | ✓ |
| `normalize_recipe` fail-loud validation | `recipes.py:80` | ✓ |
| `_recipes.register` module-owned register | `recipes.py:365`; called at `handlers.py:2205` | ✓ |
| `convert_batch` many-item even progress + cancel-between-items | `convert.py:194` (body 195-238) | ✓ |
| `JobRegistry` in-memory only (`self._jobs: dict`) | `jobs.py:179`, `jobs.py:204`; daemon pool 2/1 `jobs.py:198-209` | ✓ (the headline gap §10.1) |
| `register_all` single RPC composition root | `handlers.py:1982` | ✓ |
| `_run_ai_job` envelope builder | `handlers.py:1617` | ✓ |
| `_enforce_cloud_budget_ack` budget gate | `handlers.py:1672` | ✓ |
| `ai.planJob` pure planner (zero provider calls) | `handlers.py:1693` (registered `handlers.py:2039`) | ✓ |
| renderer `client.recipes.*` typed group | `app/renderer/src/lib/rpc.ts:757` | ✓ |
| `onProgress` / `onJobDone` / `openVideos` bridge | `rpc.ts:473,478,438` | ✓ |
| `TabBar` `role="tablist"`/`role="tab"`/`aria-selected` | `app/renderer/src/components/TabBar.tsx:17,24,25` | ✓ |
| renderer 100% coverage gate | `app/vitest.config.ts:44-49` | ✓ |
| test fakes pattern (`methods_provider=lambda`, `_FakeJobCtx`, `RpcContext(emit_notification=...)`) | `sidecar/tests/test_recipes.py:124,190,322` | ✓ |

**Capability gaps carried from DESIGN (verified, not solvable by reuse alone):**
- **G-DUR (headline):** no durable/resumable job state exists (`jobs.py:204`). Resume is built at the BATCH layer at SOURCE granularity (WU8), not mid-pipeline.
- **G-ISO:** `convert_batch` (`convert.py:194`) and `_run_one_step` (`recipes.py:302`, re-raises) abort on first error → batch needs NEW per-source try/except wrapping (WU7).
- **G-ACK:** per-request `cacheKey` ack (`handlers.py:1672`) does not fit unattended N-source batches → batch-level consent surface (WU9).
- **G-A11Y:** reused `JobQueue.tsx` carries NO `aria-live` region (only `role="alert"` on its error block) → live per-source announcer is net-new UX (WU11).
- **G-YT:** reframe is vertical-subject-tracking (`reframe.py:6-9`); 16:9 is a thin path via `output_dimensions` (`reframe.py:96`) — gated (F-youtube).

---

## 1. Work-unit overview

Twelve WUs. Each NEW component = its own WU with a 100% line+branch test plan and fakes at the ffmpeg/model/OCR seams (no real binaries, no real providers in tests). Sequenced per DESIGN §11: presets → templates → batch → resume → batch-consent, with renderer WUs trailing their sidecar counterparts.

| WU | Title | Layer | Type | Depends on |
|----|-------|-------|------|-----------|
| WU1 | `export_presets.py` — store + seeds + window clamp + caption-id validation | sidecar | NEW | — |
| WU2 | `exportPresets.*` RPC + `register_all` wiring | sidecar | NEW (extend register site) | WU1 |
| WU3 | `templates.py` — store + normalize (recipe + defaultControls + exportTargets) + method allowlist | sidecar | NEW (reuses `RecipeStore`/`normalize_recipe`) | WU1 |
| WU4 | Template step-expansion (preset fan-out) — pure function | sidecar | NEW | WU1, WU3 |
| WU5 | `templates.*` RPC (`list/save/delete/apply`) + `register_all` wiring | sidecar | NEW (reuses `_run_steps`/`_await_subjob`) | WU3, WU4 |
| WU6 | `batch.py` — `BatchStore` (per-batch JSON) + `BatchState`/`BatchItem` model + checkpoint-on-transition | sidecar | NEW | WU3 |
| WU7 | Batch runner — per-source isolation over the template runner (G-ISO) | sidecar | NEW | WU4, WU5, WU6 |
| WU8 | Resume (G-DUR) — `batch.resume` re-enqueue + source-granularity restart | sidecar | NEW | WU6, WU7 |
| WU9 | Batch consent (G-ACK) — pre-run summary from `ai.planJob` + visible-skip terminal state | sidecar | NEW | WU6, WU7 |
| WU10 | `batch.*` RPC (`create/start/status/list/cancel/resume/delete`) + `register_all` wiring | sidecar | NEW | WU7, WU8, WU9 |
| WU11 | Renderer client groups + TS interfaces (`rpc.ts`) + ExportPresetsPanel + TemplateEditor + BatchQueue + a11y live-status (G-A11Y) + Repurpose tab + resume-surface (badge/toast) | renderer | NEW | WU2, WU5, WU10 |
| WU12 | Cross-cutting verification pass — full gate run + scoped commit + PR readiness | both | gate | WU1-WU11 |

---

## 2. Work units (goal · files · test strategy · falsifiable acceptance · gate command)

### WU1 — `export_presets.py` (store + seeds + clamps)
- **Goal.** Server-persisted, editable platform-preset catalog promoting renderer-only `PLATFORM_PRESETS` (DESIGN §5.3). `ExportPreset = {id, label, aspect, minSec, maxSec, count, captionStyle, reframeEngine}`. Atomic-JSON store mirroring `RecipeStore` (`recipes.py:177` temp+rename). Seeded with tiktok/reels/shorts (all 9:16) so day-one behavior matches the current UI. Window clamp 20-60s enforced on save (DESIGN §5.3, §10.5). `captionStyle` id validated against the allowed set on save (G-10.5; mirrors `setFunctionModel` id-guard `handlers.py:514`). `reset` restores seeds.
- **Files.** NEW `sidecar/media_studio/features/export_presets.py`; NEW `sidecar/tests/test_export_presets.py`.
- **Test strategy.** Pure store unit tests over `tmp_path` JSON (no I/O seam to fake — store is filesystem-only, same as `test_recipes.py` `RecipeStore` tests). Cases: seed-on-empty; upsert-by-id; delete; reset-restores-seeds; window clamp below-min / above-max / in-range; invalid `captionStyle` id rejected (fail-loud `RpcError`); valid id accepted; corrupt-JSON-file recovery path; atomic-write temp+rename (assert no partial file on simulated write failure via a patched `os.replace`).
- **Falsifiable acceptance.**
  1. Empty store → `list()` returns exactly the 3 seeds with the 9:16 aspect each.
  2. `save({id:"x", maxSec:600, ...})` persists with `maxSec` clamped to 60; `minSec:5` clamped to 20.
  3. `save` with `captionStyle:"__nope__"` raises `RpcError` (`code` per the module's invalid-input convention) and writes nothing.
  4. `delete("tiktok")` then `reset()` → `list()` again contains tiktok.
  5. A simulated `os.replace` failure leaves the prior file intact (no truncation).
- **Gate.** `cd sidecar && pytest tests/test_export_presets.py --cov=media_studio/features/export_presets --cov-branch --cov-fail-under=100 && ruff check media_studio/features/export_presets.py && basedpyright media_studio/features/export_presets.py`

### WU2 — `exportPresets.*` RPC + register wiring
- **Goal.** Direct-return CRUD methods (DESIGN §6): `exportPresets.list/save/delete/reset`. Each via the module's own `register(...)` bound to `Services.data_dir` (mirrors `_recipes.register` call `handlers.py:2205`), added at the single composition root `register_all` (`handlers.py:1982`). File `export-presets.json` under `Services.data_dir` (`handlers.py:143`).
- **Files.** EDIT `sidecar/media_studio/features/export_presets.py` (add `register`); EDIT `sidecar/media_studio/handlers.py` (one `_export_presets.register(...)` block inside `register_all`, no other site); EDIT `sidecar/tests/test_export_presets.py` (RPC-level cases) + EDIT `sidecar/tests/test_handlers.py` or a new `test_handlers_export_presets.py` for the registration-site smoke.
- **Test strategy.** Call handlers through `RpcContext(emit_notification=lambda *_: None, jobs=None)` (the `test_recipes.py:124` idiom). Assert each method present in the assembled `protocol.METHODS` after `register_all`. CRUD round-trip via a `tmp_path` data dir.
- **Falsifiable acceptance.**
  1. After `register_all`, `protocol.METHODS` contains exactly `exportPresets.list/save/delete/reset` (and no other new key).
  2. `exportPresets.save` returns `{preset}` with clamped fields; a subsequent `exportPresets.list` reflects it.
  3. `exportPresets.delete` of a seed then `exportPresets.reset` restores it.
- **Gate.** `cd sidecar && pytest tests/test_export_presets.py tests/test_handlers*.py -k "export_preset or register_all" --cov=media_studio --cov-branch --cov-fail-under=100`

### WU3 — `templates.py` (store + normalize + allowlist)
- **Goal.** `templates.py` REUSES `RecipeStore`/`normalize_recipe`/`Recipes._run_steps` by import (DESIGN §5.4 recommendation, gate F-template-shape). A `Template` = recipe shape (`recipes.py:80-114`) PLUS additive `defaultControls` and `exportTargets:[presetId]`. Normalize = recipe-normalize + validate the two extra fields + a **method allowlist** (G-10.6): reject step `method`s outside `{transcribe.*, subtitles.*, shortmaker.*, phase8.select, nle.export, package.export, convert.*, audio.*}` with the same fail-loud posture as `normalize_recipe` (`recipes.py:98`).
- **Files.** NEW `sidecar/media_studio/features/templates.py`; NEW `sidecar/tests/test_templates.py`.
- **Test strategy.** Unit over `tmp_path` JSON (`templates.json`). Fake nothing (storage-only). Cases: normalize accepts a valid template; preserves `defaultControls`/`exportTargets`; rejects unknown method (`shell.exec`-style) at save; rejects malformed `exportTargets` (non-list / non-string ids); reuses `RecipeStore` round-trip (save/list/delete/get); empty/corrupt file.
- **Falsifiable acceptance.**
  1. `normalize` of `{steps:[{method:"shell.exec"}]}` raises `RpcError` (allowlist), writes nothing.
  2. `normalize` of a valid template retains `defaultControls` and `exportTargets` verbatim and assigns an id if absent (recipe-normalize behavior).
  3. The underlying `recipes.normalize_recipe` is the ONLY recipe-validation path called (verified by import, not re-implementation) — no fork of the wire shape.
- **Gate.** `cd sidecar && pytest tests/test_templates.py --cov=media_studio/features/templates --cov-branch --cov-fail-under=100 && ruff check media_studio/features/templates.py && basedpyright media_studio/features/templates.py`

### WU4 — Template step-expansion (preset fan-out)
- **Goal.** Pure function (DESIGN §5.1, §5.3): before a run, a `shortmaker.export` step whose params name multiple `exportTargets` is expanded into one export call per resolved `ExportPreset`, each merging preset fields onto the template's `defaultControls`. No I/O, no provider — fully testable. Output dir convention preserved (`exports/shorts-<videoId>`, `handlers.py:1351`); preset id attached to clip metadata so the Shorts gallery can group.
- **Files.** EDIT `sidecar/media_studio/features/templates.py` (add `expand_export_steps(steps, controls, presets)` pure fn); EDIT `sidecar/tests/test_templates.py`.
- **Test strategy.** Pure-function tests with in-memory preset dicts (no store, no ffmpeg). Cases: single target → one step (identity); 3 targets → 3 steps with merged params; preset field overrides `defaultControls`; unknown target id in `exportTargets` → fail-loud; empty `exportTargets` → no export step / passthrough per the documented rule; window clamp from preset honored in merged params.
- **Falsifiable acceptance.**
  1. `expand_export_steps` with `exportTargets:["tiktok","shorts"]` yields exactly 2 export steps; each merged params has that preset's `aspect`/`maxSec`/`captionStyle`.
  2. A target id not in the presets dict raises `RpcError`, yields no partial expansion.
  3. Non-export steps pass through unchanged and in order (idempotent on already-flat step lists).
- **Gate.** `cd sidecar && pytest tests/test_templates.py -k expand --cov=media_studio/features/templates --cov-branch --cov-fail-under=100`

### WU5 — `templates.*` RPC
- **Goal.** `templates.list/save/delete` (direct CRUD) + `templates.apply {templateId, videoId}` → `{jobId}` (DESIGN §6). `apply` runs the template against ONE source by binding steps to `videoId`, expanding export fan-out (WU4), then driving the EXISTING `Recipes._run_steps`/`_await_subjob` (`recipes.py:279,323`) — NO new runner, NO new sub-job waiting. `apply` is the single-source sugar over WU7's batch path (one item).
- **Files.** EDIT `sidecar/media_studio/features/templates.py` (add `register` + the `Templates` service); EDIT `sidecar/media_studio/handlers.py` (one `_templates.register(...)` block in `register_all`); EDIT `sidecar/tests/test_templates.py` + registration-site smoke.
- **Test strategy.** Fakes at the runner seam exactly like `test_recipes.py`: `methods_provider=lambda: {fake methods}` returning `{jobId}` for export, plain dicts for sync steps; `_FakeJobCtx` (`test_recipes.py:322`) and `RpcContext(emit_notification=..., jobs=<fake registry>)`. Assert `apply` returns `{jobId}` and the parent job body invokes the expanded step list in order. No real model, no real ffmpeg.
- **Falsifiable acceptance.**
  1. `templates.apply` returns `{jobId}`; the started job's body calls each expanded step's method via the live methods registry, in order.
  2. A template with 3 export targets produces 3 export invocations for the one source.
  3. Cancellation between steps propagates via `raise_if_cancelled` (`recipes.py:285`) — no new cancel code (assert the existing path is reused).
  4. After `register_all`, `protocol.METHODS` gains exactly `templates.list/save/delete/apply`.
- **Gate.** `cd sidecar && pytest tests/test_templates.py tests/test_handlers*.py -k "template or register_all" --cov=media_studio --cov-branch --cov-fail-under=100`

### WU6 — `batch.py` store + model + checkpointing
- **Goal.** `BatchStore` writes one file per batch (`batches/<batchId>.json`, DESIGN §8) using the atomic temp+rename pattern, so a large run's checkpoint is O(1) and a corrupt batch can't poison others. `BatchState = {id, name, templateId, status, createdAt, items:[BatchItem]}`; `BatchItem = {videoId, status: queued|running|done|error|cancelled|skipped, jobId?, error?, skipReason?, results?}`. Checkpoint after EVERY item transition (queued→running→done/error/skipped) — this is the durability substrate for resume (G-DUR), since `JobRegistry` itself is in-memory (`jobs.py:204`).
- **Files.** NEW `sidecar/media_studio/features/batch.py` (store + model + create/load/checkpoint, NOT the runner yet); NEW `sidecar/tests/test_batch.py`.
- **Test strategy.** Pure store tests over `tmp_path`. Cases: create persists all M items as `queued`; per-item transition rewrites the file atomically; load reconstructs full state incl. `skipped`+`skipReason`; per-batch isolation (write to A doesn't touch B); corrupt one batch file → others still loadable; `list` summaries omit heavy `results`.
- **Falsifiable acceptance.**
  1. `create(name, templateId, [v1,v2,v3])` writes a file with 3 `queued` items and `status:"queued"`.
  2. A transition `v2 → error` immediately rewrites the file (assert on-disk content reflects it before any later item runs).
  3. Two batches coexist; deleting/corrupting one leaves the other's `load` intact.
  4. `BatchState` round-trips `skipped`+`skipReason` losslessly.
- **Gate.** `cd sidecar && pytest tests/test_batch.py --cov=media_studio/features/batch --cov-branch --cov-fail-under=100`

### WU7 — Batch runner with per-source isolation (G-ISO)
- **Goal.** The parent batch job: iterate `sourceVideoIds`, spread `[0,100]` progress across items (mirroring `convert_batch` `convert.py:195-238`), and run each source through the template runner (WU5 path) — but with **NEW per-source try/except** so one bad source records `error` on its `BatchItem` and the batch CONTINUES (the deliberate divergence from `convert_batch`/`_run_one_step` which abort, G-ISO). Gated by `batchContinueOnError` (default `true`, DESIGN §8/§10.3). Awaits each per-source sub-job with the EXISTING `_await_subjob` relay (`recipes.py:323`). Progress message extends the recipe runner's `"step k/N"` (`recipes.py:293`) to `"source k/N · <title> · step j/M · <label>"`.
- **Files.** EDIT `sidecar/media_studio/features/batch.py` (add the runner over WU6 store + WU5 template path); EDIT `sidecar/tests/test_batch.py`.
- **Test strategy.** Fake the template-run seam (a callable returning `{jobId}` or raising) + `_FakeJobCtx` + fake `JobRegistry`. NO real ffmpeg/model. Cases: 3 sources all succeed → all `done`, checkpoint after each; source 2 raises → `error` recorded, sources 1 and 3 still `done` (isolation); `batchContinueOnError=false` → batch stops at first error with remaining `queued`; cancellation between sources via `raise_if_cancelled`; progress message format asserts the `source k/N` prefix.
- **Falsifiable acceptance.**
  1. With source 2's run raising, final state = `[done, error, done]` and `status:"partial"` (not aborted).
  2. With `batchContinueOnError=false`, final state after a source-2 error = `[done, error, queued]` and `status:"error"`.
  3. Each item flip is checkpointed to disk (assert intermediate on-disk state).
  4. Cancellation mid-batch leaves the in-flight item `cancelled` and later items `queued` (no new cancel machinery — reuses `_await_subjob` `recipes.py:345-347`).
- **Gate.** `cd sidecar && pytest tests/test_batch.py -k "isolation or runner or progress or cancel" --cov=media_studio/features/batch --cov-branch --cov-fail-under=100`

### WU8 — Resume (G-DUR, source granularity)
- **Goal.** `batch.resume {id}` → `{jobId}`: read the checkpointed `BatchState`, treat `done` items as complete, re-enqueue `queued`/`running`/(optionally `error`) items as a FRESH parent job (DESIGN §10.1). Resume is **source granularity** (F-resume-granularity): a source that crashed at step 3/5 re-runs from step 1 (earlier outputs are idempotent overwrites — transcribe flips `hasTranscript` `handlers.py:1068-1072`). Mid-pipeline checkpointing is explicitly OUT OF SCOPE and named here.
- **Files.** EDIT `sidecar/media_studio/features/batch.py` (add `resume`); EDIT `sidecar/tests/test_batch.py`.
- **Test strategy.** Construct a partially-complete `BatchState` on disk, call resume with the fake runner. Cases: `done` items not re-run; `queued`/`running` re-enqueued; `error` items re-enqueued only when policy says so; a fully-`done` batch resume is a no-op (returns terminal status, no new job); resume after a successful re-run flips remaining items to `done`.
- **Falsifiable acceptance.**
  1. Resuming `[done, error, queued]` re-runs only items 2 and 3 (item 1's runner is NOT invoked — assert call count).
  2. Resuming an all-`done` batch starts no job and reports `done`.
  3. A re-enqueued source runs from its FIRST step (assert the runner gets the full step list, not a suffix — source-granularity contract).
- **Gate.** `cd sidecar && pytest tests/test_batch.py -k resume --cov=media_studio/features/batch --cov-branch --cov-fail-under=100`

### WU9 — Batch consent surface (G-ACK) + visible skip
- **Goal.** Pre-run consent computed BEFORE `batch.start` from pure `ai.planJob` plans only (zero provider calls, `handlers.py:1693`): one plan per distinct step *shape* (sources sharing template+size collapse). Surface returns per-step-shape route/`willEgress`, the N-run/K-skip split with per-source `willEgress`/`cacheHit`, aggregated `costEst`, and `budget` headroom. Default policy F-batch-consent (a) skip-non-acked under `confirmCloudBudget` WITH the visible-skip contract: a non-acked egressing source gets terminal `status:"skipped"` + `skipReason` on its `BatchItem` (never silent absence, DESIGN §9.1). Acknowledgement passes each plan's `cacheKey` as `confirmBudget` to the underlying handler, satisfying `_enforce_cloud_budget_ack` (`handlers.py:1672`) WITHOUT changing the envelope. (b) refuse-batch is the alternative the gate may pick; both ship the same surfacing.
- **Files.** EDIT `sidecar/media_studio/features/batch.py` (add `plan_consent(...)` pure aggregator + skip-decision in the runner); EDIT `sidecar/tests/test_batch.py`.
- **Test strategy.** Fake `ai.planJob` returning canned plans (`{route, costEst, cacheHit, willEgress, budget, cacheKey}`) — NO real planner, NO provider. Cases: plan dedup by step-shape (2 distinct shapes from 30 sources → 2 planner calls, assert call count); local-only/cache-hit sources always run; egressing-unacked source → `skipped`+`skipReason="would egress — not acknowledged"`; no-headroom → `skipReason="no budget headroom"`; ack present → `confirmBudget=cacheKey` threaded; `confirmCloudBudget` OFF → all run, card informational only.
- **Falsifiable acceptance.**
  1. 30 sources, one template shape → exactly 1 `ai.planJob` invocation (dedup by shape, not by source).
  2. Under `confirmCloudBudget` on + no ack, an egressing source ends `skipped` with the reason token; a cache-hit source ends `done`.
  3. With ack, the underlying AI handler receives `confirmBudget` equal to the plan's `cacheKey` (assert the threaded value).
  4. The consent aggregate sums `costEst` only over egressing sources and reports the `budget` headroom.
- **Gate.** `cd sidecar && pytest tests/test_batch.py -k "consent or skip or plan" --cov=media_studio/features/batch --cov-branch --cov-fail-under=100`

### WU10 — `batch.*` RPC + register wiring
- **Goal.** `batch.create/start/status/list/cancel/resume/delete` (DESIGN §6) via the module's own `register(...)` at `register_all` (`handlers.py:1982`). `start`/`resume` → `{jobId}`; `status` merges store + live job; `cancel` sets the parent job flag (`jobs.py:447` cooperative). `start` runs the WU9 consent decision then the WU7 runner.
- **Files.** EDIT `sidecar/media_studio/features/batch.py` (add `register` + `Batch` service); EDIT `sidecar/media_studio/handlers.py` (one `_batch.register(...)` block in `register_all`); EDIT `sidecar/tests/test_batch.py` + registration-site smoke.
- **Test strategy.** Through `RpcContext` with a fake registry. Cases: each method present after `register_all`; `create` then `status` round-trip; `start` returns `{jobId}`; `cancel` flips the parent job; `status` reflects live job progress merged with stored items incl. `skipped`; `delete` of a finished batch.
- **Falsifiable acceptance.**
  1. After `register_all`, `protocol.METHODS` gains exactly the 7 `batch.*` keys and no others.
  2. `batch.status` of a partially-run batch returns `done`+`error`+`skipped` items with their reasons.
  3. `batch.cancel` results in cooperative cancellation (existing `jobs.py:447` path; no new machinery).
- **Gate.** `cd sidecar && pytest tests/test_batch.py tests/test_handlers*.py -k "batch or register_all" --cov=media_studio --cov-branch --cov-fail-under=100 && ruff check media_studio/features/batch.py && basedpyright media_studio/features/batch.py`

### WU11 — Renderer (client groups, panels, a11y, tab, resume-surface)
- **Goal.** New typed client groups + TS interfaces in `app/renderer/src/lib/rpc.ts` mirroring the `client.recipes.*` group (`rpc.ts:757`): `client.exportPresets.{list,save,delete,reset}`, `client.templates.{list,save,delete,apply}`, `client.batch.{create,start,status,list,cancel,resume,delete}`; interfaces `ExportPreset`, `Template`, `BatchItem`, `BatchState`, `BatchSummary` with field names IDENTICAL to the sidecar (house rule `rpc.ts:17`). New **Repurpose** tab (rides `TabBar.tsx:17,24,25` a11y for free). Three panels (DESIGN §7): **BatchQueue** (default landing — multi-select via `openVideos` `rpc.ts:438`, template pick, consent summary card §9.1, live rows via `onProgress`/`onJobDone` `rpc.ts:473,478`); **TemplateEditor** (curated-preset-first, never raw method ids, F-template-catalog); **ExportPresetsPanel** (table + constrained `captionStyle` select + inline window clamp). **a11y live-status (G-A11Y, net-new):** a `role="status" aria-live="polite"` aggregate region (idiom from `ShortMaker.tsx:773`) announcing on source-transition + terminal-state only (F-a11y-announce-granularity); per-source terminal errors `aria-live="assertive"`/`role="alert"` (`SidecarBanner.tsx:72`); text status tokens not color-only (`PresetPicker.tsx:6,11`); per-row `<ProgressBar>` keeps `role="progressbar"`/`aria-valuenow`. **Resume-surface (F-resume-surface):** tab badge `(N)` from a launch `batch.list` + one-time dismissible `ToastHost` toast (`ToastHost.tsx:68`, already polite).
- **Files.** EDIT `app/renderer/src/lib/rpc.ts` (interfaces + 3 client groups); NEW `app/renderer/src/views/Repurpose.tsx`; NEW `app/renderer/src/features/{BatchQueue,TemplateEditor,ExportPresetsPanel}.tsx` (+ a `BatchConsentCard` + a live-status announcer component); EDIT `app/renderer/src/App.tsx` + `components/TabBar.tsx` (tab + badge); NEW co-located `*.test.tsx` for each + `rpc.ts` group tests.
- **Test strategy.** vitest + Testing Library with the rpc bridge mocked (the existing renderer test idiom). Fake `onProgress`/`onJobDone` event streams. Assert a11y: `role="status"`/`aria-live` present and updated on source-transition only (not per pct tick); assertive error announcement on item error; status tokens are text (queried by text, not color); tab badge renders `(N)` when `batch.list` returns incomplete batches; toast appears once and deep-links. Assert TemplateEditor never renders a raw `protocol.METHODS` id (only curated labels). Window-clamp shown inline in ExportPresetsPanel; `captionStyle` select offers only valid ids.
- **Falsifiable acceptance.**
  1. `client.batch`/`client.templates`/`client.exportPresets` groups call the correct RPC method names with the correct param shapes (assert the mocked `rpc()` args).
  2. A simulated 30-source progress stream announces on each `source k/N` transition and on each terminal flip — NOT on every percent tick (assert announcement count ≈ source count, not pct count).
  3. An item-error event triggers an `aria-live="assertive"`/`role="alert"` announcement carrying the reason.
  4. With one incomplete batch in `batch.list`, the Repurpose tab shows a text `(1)` badge and a one-time resume toast.
  5. TemplateEditor exposes zero raw method ids (no `shortmaker.select`/`phase8.select` text in the DOM); only curated labels.
  6. ExportPresetsPanel `captionStyle` control is a closed select of valid ids; an out-of-range duration is clamped/blocked in-UI.
- **Gate.** `cd app && npx vitest run --coverage && npx tsc --noEmit && npx oxlint app/renderer/src && npx biome check app/renderer/src` (coverage must satisfy `vitest.config.ts:44-49` thresholds:100).

### WU12 — Cross-cutting verification + PR readiness (gate WU)
- **Goal.** A whole-bundle gate pass: run BOTH full suites at 100% line+branch, all linters/typecheckers green, confirm the only `register_all` edits are the three new `register()` blocks (invariant: ONE RPC site), confirm NO new provider call site exists anywhere in `batch.py`/`templates.py`/`export_presets.py` (grep for direct provider/key access — must be zero; AI rides the envelope only via `protocol.METHODS`). Scoped commit; PR draft.
- **Files.** No new source; CI/verification only. Possible EDIT to `sidecar/pyproject.toml` test markers if needed.
- **Test strategy.** Full `pytest --cov-branch --cov-fail-under=100` over `sidecar`; full `vitest run --coverage` over `app`. Static check: `grep` the three new sidecar modules for `Provider`/`api_key`/`_run_ai_job(` direct calls → assert absent (they must only invoke methods by name).
- **Falsifiable acceptance.**
  1. `cd sidecar && pytest --cov-branch --cov-fail-under=100` exits 0 (no module below 100% line+branch).
  2. `cd app && npx vitest run --coverage` exits 0 (thresholds:100 met).
  3. `git diff origin/main -- sidecar/media_studio/handlers.py` shows ONLY additions inside `register_all` (no second registration site; no provider wiring).
  4. The three new feature modules contain no direct provider construction or key read.
- **Gate.** `cd sidecar && pytest --cov-branch --cov-fail-under=100 && ruff check media_studio && basedpyright media_studio` ; `cd app && npx vitest run --coverage && npx tsc --noEmit && npx oxlint . && npx biome check .`

---

## 3. Dependency graph

```
WU1 (export_presets store)
 ├─> WU2 (exportPresets RPC) ───────────────┐
 ├─> WU3 (templates store+normalize+allowlist)
 │     ├─> WU4 (step-expansion fan-out) ─────┐
 │     └─> WU6 (batch store + checkpoint)     │
 │           ├─> WU7 (batch runner / isolation) <── WU4, WU5
 │           │     ├─> WU8 (resume)            │
 │           │     └─> WU9 (consent/skip)      │
 │           └─────────> WU10 (batch RPC) <── WU7,WU8,WU9
 └────────────────────> WU5 (templates RPC) <── WU3,WU4
                                                │
WU2 + WU5 + WU10 ──> WU11 (renderer: clients, panels, a11y, tab, resume-surface)
ALL ──────────────> WU12 (cross-cutting gate + PR)
```

Linear critical path (longest): **WU1 → WU3 → WU4 → WU5 → WU7 → WU8/WU9 → WU10 → WU11 → WU12.**

---

## 4. Parallelism notes

- **WU2 ‖ WU3** — once WU1 lands, the `exportPresets` RPC (WU2) and the templates store (WU3) are independent files (`export_presets.py` RPC layer vs. new `templates.py`); parallelizable. They touch `register_all` in disjoint blocks but **the `handlers.py` edit is a one-owner shared file** — sequence the two `register_all` additions or use scoped staged adds + `git diff --cached --name-only` before each commit (per the parallel-worktree-contamination rule). Prefer separate worktrees if run by parallel agents.
- **WU4 ‖ WU6** — step-expansion (pure, in `templates.py`) and the batch store (`batch.py`) are different files with no runtime dependency until WU7; parallelizable after WU3.
- **WU8 ‖ WU9** — resume and consent both extend `batch.py` after WU7; they touch the SAME file, so run sequentially OR in isolated worktrees with a merge step, NOT a shared index. Their tests are disjoint.
- **WU11 is the renderer convergence point** — it cannot start until WU2/WU5/WU10 expose the RPC surface (the renderer asserts real method names/param shapes). Within WU11, the three panels are independent files and parallelizable, but `rpc.ts`, `App.tsx`, and `TabBar.tsx` are one-owner shared files (sequence those edits).
- **WU12 is a barrier** — runs only after every WU is green; do not start until WU1-WU11 each pass their own gate.
- **Shared-file discipline (rails):** `handlers.py`, `rpc.ts`, `App.tsx`, `TabBar.tsx`, `pyproject.toml` are one-owner shared files. Any parallel agents must use scoped `git add <path>` (never `-A`) and verify `git diff --cached --name-only` before each commit, or operate in isolated worktrees.

---

## 5. Open gate questions (carried from DESIGN §12 — resolve before/at BUILD kickoff)

These do not block this PLAN doc; they steer specific WUs:
- **F-template-shape** → WU3 (new `templates.py`, recommended).
- **F-batch-consent** → WU9 (default (a) skip-non-acked with visible skip, recommended; (b) refuse-batch alt — both ship the surfacing).
- **F-resume-granularity** → WU8 (source-level for v1, recommended).
- **F-error-policy** → WU7 (`batchContinueOnError` default `true`).
- **F-youtube** → preset seed (G-YT): include 16:9 `youtube` preset in v1 or vertical-only.
- **F-a11y-announce-granularity** → WU11 (source-transition + terminal only, recommended).
- **F-resume-surface** → WU11 (tab badge + launch toast, recommended).
- **F-template-catalog** → WU11 (curated starter set + label copy; no raw method ids).
