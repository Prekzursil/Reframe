# Reframe "Director" v1 — Implementation Plan (Prompt-Driven AI Video Editing)

**Status:** DRAFT for the Plan Review Gate (3 adversarial reviewers: Feasibility · Completeness · Scope/Alignment).
**Branch:** `feat/director-v1` (off `origin/main`).
**Date:** 2026-06-18.
**Scope authority (LOCKED — do not re-decide):** [`DESIGN.md`](./DESIGN.md) (design-gate-approved after revisions) + [`FEATURE.md`](./FEATURE.md). Substrate authority: [`../ai-program/PLAN.md`](../ai-program/PLAN.md) (the shipped Provider Hub / AI-Job).

> **RAILS for this doc.** Every capability claim cites real code as `file:line` on this branch. Where a capability does **not** exist it is labelled **GAP/NEW** explicitly — no fabrication. Director must **not** invent a parallel AI path: every LLM/vision call rides the **same** AI-Job envelope (`models/ai_job.py`: `plan_ai_job` `:204`, `run_ai_job` `:264`), the **same** rotation pool (`models/provider.py`: `RotatingProvider` `:534`, `build_pool_provider` `:684`), the **same** per-data-type consent + budget + cache, and registers on the **one** RPC site (`handlers.register_all`, `handlers.py:1982`).
>
> **Coverage-gate correction (load-bearing, verified).** `.coverage-thresholds.json` does **NOT** exist in this repo. The single source of truth is `.github/workflows/quality.yml` **gate:3**: sidecar `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` (`quality.yml:92`) **+** renderer `cd app && npx vitest run --coverage` at 100% (`quality.yml:95`; `app/vitest.config.ts:44-46` thresholds `lines/branches/functions/statements = 100`, vitest **NOT** jest). Heavy/native seams excluded with inline `# pragma: no cover` on the real-impl seam (proven: `smolvlm2.py` `_default_backend_factory`, `provider.py` `_urllib_post_json`); untestable renderer runtime lines use inline `/* v8 ignore … -- <reason> */`. Plus gate:1/5 lint+secrets (ruff/oxlint/biome via pre-commit, gitleaks), gate:2 types (tsc + basedpyright). **Never `--no-verify`; never `git add -A`; stage explicit paths.** TDD mandatory (RED→GREEN→refactor).

---

## 1. Context & locked critical path

Director is an **orchestrator** over engines that already ship, wired onto the **already-shipped** AI substrate. The substrate is **not** part of this plan's build — it is reused as-is:

- **AI-Job envelope** (`models/ai_job.py:204/264`) — pure plan + run-on-`ctx.jobs`, cache-first, budget-aware.
- **Rotation pool** (`models/provider.py:534/684`) — per-function routing via `_provider_for_function` (`handlers.py:575`), failover/429-cooldown/local-backstop.
- **`_run_ai_job`** (`handlers.py:1617`) — the one wrapper: builds the PURE envelope (`plan_ai_job_envelope` `:1601`), enforces ack (`_enforce_cloud_budget_ack` `:1672`), runs on `ctx.jobs`. `phase8_select` uses it at `:1292`.
- **`ai.planJob`** (`handlers.py:1693`, ZERO provider calls) — the cost/route/egress preview.
- **Per-data-type consent** — frame gate FIRST via `_resolve_vlm_reranker` (`handlers.py:670`) + `_frame_consented_vision_settings` (`handlers.py:597`).
- **`editPlan` is ALREADY a routing function** (`presets.py:59`); `vision` already names OCR (`presets.py:62/69`). Director **adds no routing slot**.

**What Director actually builds (the GAPs, DESIGN §8):** the apply/undo engine over a project COPY; an OCR list-extractor; panorama-stitch + constant-speed scroll-regen; the EditPlan DSL + validate-and-reject; an objective eval engine; the `director.*` RPC handlers; the `DirectorPanel.tsx` renderer surface; an eval harness.

**Locked build order (DESIGN §8 — `applyEngine` FIRST, "unretrofittable"):**

```
WU-dsl ──► WU-apply ──► WU-undo ──► WU-plan-rpc ──► WU-evaluate ──► WU-panel
   │           │                        ▲                              ▲
   │           └──► WU-ocr ─────────────┤                              │
   │           └──► WU-stitch ─► WU-regen┤                              │
   │                                     └──► WU-eval-harness ──────────┘
   └──► (WU-ocr / WU-stitch can start once WU-dsl op types are frozen)
```

Standing gate (EVERY WU): the two gate:3 commands above + gitleaks clean + TDD. Each WU lands its heavy seam behind the `# pragma: no cover` / `/* v8 ignore */` real-impl pattern with injected fakes, so planner/validator/eval/apply stay **pure, fully-tested functions**.

---

## 2. Work Unit dependency graph & parallelism

| WU | Title | Layer | Depends on | Parallel with |
|---|---|---|---|---|
| WU-dsl | EditPlan DSL + validate-and-reject | sidecar (pure) | — | — (foundation) |
| WU-apply | applyEngine over a project COPY (+ inverse) | sidecar | WU-dsl | WU-ocr, WU-stitch |
| WU-ocr | `ocrExtractList` engine (RapidOCR + vision gate) | sidecar | WU-dsl | WU-apply, WU-stitch |
| WU-stitch | `stitchPanorama` frame-stitch engine | sidecar | WU-dsl | WU-apply, WU-ocr |
| WU-regen | `regenScroll` constant-speed renderer | sidecar | WU-stitch | WU-apply, WU-ocr |
| WU-undo | `director.undo` (apply stored inverse) | sidecar | WU-apply | WU-ocr, WU-stitch, WU-regen |
| WU-plan-rpc | `director.plan` + `director.previewCost` + `director.apply` RPC | sidecar | WU-apply, WU-dsl (engines slot in as they land) | WU-eval-harness |
| WU-evaluate | `director.evaluate` objective metrics | sidecar | WU-plan-rpc | WU-eval-harness |
| WU-eval-harness | offline golden-plan eval harness | sidecar (test infra) | WU-plan-rpc | WU-evaluate, WU-panel |
| WU-panel | `DirectorPanel.tsx` storyboard/diff/banner/a11y | renderer | WU-plan-rpc, WU-evaluate (RPC shapes) | WU-eval-harness |

**Parallelism summary**
- **Wave 1 (foundation, serial):** WU-dsl.
- **Wave 2 (fan-out, 3 parallel):** **WU-apply ∥ WU-ocr ∥ WU-stitch** — all depend only on WU-dsl, touch disjoint new files, no shared mutable file. WU-regen serializes right after WU-stitch (consumes its panorama artifact).
- **Wave 3:** WU-undo (after WU-apply) ∥ WU-plan-rpc (after WU-apply; engines wire in as available).
- **Wave 4 (2 parallel):** **WU-evaluate ∥ WU-eval-harness** (both after WU-plan-rpc).
- **Wave 5:** WU-panel (after the RPC shapes from WU-plan-rpc + WU-evaluate are frozen; can begin against the frozen TS types while eval-harness finishes).

**Worktree note (parallel agents):** Wave-2/Wave-4 parallel WUs touch **disjoint new files** (each engine is its own module). The one shared sidecar file is `handlers.py` (touched by WU-undo, WU-plan-rpc, WU-evaluate) — those are **sequenced, not parallel**, so the single composition root `register_all` (`handlers.py:1982`) is edited by one owner at a time. If dispatched to isolated worktrees, mandate scoped `git add <path>` + `git diff --cached --name-only` before every commit (never `git add -A`).

---

## 3. Work Units (MVP)

### WU-dsl — EditPlan DSL + validate-and-reject (FOUNDATION)

- **id:** WU-dsl
- **goal:** the typed, ordered, REVERSIBLE EditPlan document (DESIGN §2.1) + a **pure** validate-and-reject pass, so the planner is a pure `prompt+understanding → EditPlan` function testable to 100% without rendering (`FEATURE.md:40`). Resolves the **exact EditPlan JSON schema** deferred to PLAN (DESIGN §9).
- **files/seams touched:**
  - **new** `sidecar/media_studio/models/edit_plan.py` — `@dataclass(frozen=True)` `EditPlan {planId, videoId, goal, sourceHash, ops, inverse}` and `EditOp {id, kind, span, params, reversible, rationale, status, statusReason}` (DESIGN §2.1). `kind` = `Literal["trim","cut","removeSilence","removeFillers","reorder","retime","reframe","zoomPan","caption","translateCaption","overlayText","lowerThird","export","stitchPanorama","regenScroll","ocrExtractList"]` (DESIGN §2.2 toolbox; `applyEngine` is the runner, not an op). `to_json`/`from_json` (canonical, deterministic key order) + JSON-schema dict for the renderer's TS mirror.
  - **new** `sidecar/media_studio/features/edit_validate.py` — `validate_and_reject(plan, *, understanding) -> EditPlan`: pure; for each op checks `span` vs real clip duration, track existence, per-kind preconditions; drops impossible ops by setting `status="dropped"` + typed `statusReason ∈ {span-exceeds-clip, unknown-track, precondition-unmet, ...}` (DESIGN §2.1) — **never silently discarded** (kept in the returned plan for the storyboard).
  - **new** `sidecar/media_studio/features/edit_plan_prompt.py` — the planner system prompt builder following the `select.py` pattern: two-pass shape (`select.py:707` `select_unified`), `<think>` strip (`select.py:70/358`), JSON parse → typed `EditPlan`. **Structurally fences** all media-derived text (transcript/OCR) as untrusted DATA, never instructions (DESIGN §5 mitigation #1). Pure: input = (goal, understanding); output = messages + a parse function. No provider here (the call is WU-plan-rpc via `_run_ai_job`).
- **public surface added:** `EditPlan`, `EditOp`, `EditPlanError`; `validate_and_reject`; `build_edit_plan_messages` + `parse_edit_plan`. No RPC yet.
- **test strategy (sidecar gate):** pure unit tests, no network/render. (a) round-trip `to_json`/`from_json` byte-stable; (b) `validate_and_reject` drops each rejection class with the correct `statusReason`, keeps valid ops, preserves order; (c) injected on-screen "delete all clips" op with an out-of-range span → dropped (the structural injection defense, DESIGN §5 #2); (d) `parse_edit_plan` strips `<think>` and rejects malformed JSON with `EditPlanError`; (e) prompt builder emits transcript/OCR inside a fenced DATA block, asserted by string structure. 100% line+branch via the pure functions only.
- **acceptance (falsifiable):** (a) `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0 with `edit_plan.py`/`edit_validate.py`/`edit_plan_prompt.py` at 100%; (b) a fixture plan with N ops where M are out-of-range returns a plan with exactly M ops `status="dropped"` and N−M `status="planned"`, order unchanged; (c) `to_json(from_json(x)) == x` for a fixtures corpus; (d) no `Provider`/transport import in any of the three modules (assert via import-scan — planner purity); (e) gitleaks clean.
- **dependencies:** none (foundation).
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit (ruff/basedpyright).
- **parallel?** No — every other WU consumes these types.

---

### WU-apply — `applyEngine` over a project COPY + inverse (DESIGN §5, GAP-1, build FIRST)

- **id:** WU-apply
- **goal:** the reversibility layer the in-place handlers lack. Today every handler mutates `project.data` in place and `project.save()`s with **no undo** (`subtitles_edit` walks `project.data["tracks"]` `handlers.py:234`, then `project.save()` `:743`). `applyEngine` walks `EditPlan.ops` over a **project COPY**, dispatches each op to its existing engine (DESIGN §2.2 toolbox), and **records the `inverse` op as it applies** so the whole plan has a one-shot undo. Stop-on-first-failure auto-rollback (DESIGN §5).
- **files/seams touched:**
  - **new** `sidecar/media_studio/features/apply_engine.py` — `apply_plan(plan, *, project_copy, engines) -> ApplyResult` where `engines` is an **injected dispatch table** `{kind: callable}` (the seam: real impls are the shipped engines; tests inject fakes). Applies ops in order; on first throw → stop, mark that op `status="failed"` + `statusReason=<msg>`, leave unreached ops `status="planned"`, then **walk recorded inverse to roll back the COPY** (DESIGN §5). Source manifest never touched (rollback = discard/invert the COPY). Pure dispatch + ordering logic; the heavy engine calls live behind the injected table.
  - **new** `sidecar/media_studio/features/project_copy.py` — `copy_project(project) -> ProjectCopy`: deep-copies `project.data` to an isolated manifest path (the COPY the engine writes to). The real filesystem write is the only `# pragma: no cover` seam; the copy/merge logic is pure.
  - **op→engine adapters (thin, new):** each `kind` adapter calls the shipped engine and returns its `inverse`. Reuse: `trim/cut/removeSilence` → `features/silencetrim.py`; `removeFillers` → `features/fillers.py`; `reorder` → immutable manifest track replace (the `subtitles_edit` replace pattern `handlers.py:234`); `retime/reframe/zoomPan` → `features/reframe.py`/`zoom.py`/`stabilize.py`; `caption` → `subtitles.generate` (`handlers.py:722`) + `tracks.burn` (`handlers.py:952`); `translateCaption` → `subtitles.translate` (`handlers.py:776`); `overlayText/lowerThird` → `features/caption_remotion.py`; `export` → `features/nle_export.py` `export`/`build_edl`/`clips_to_events` (`:283/:204/:151`). `stitchPanorama/regenScroll/ocrExtractList` adapters call the WU-stitch/WU-regen/WU-ocr engines (wired as those land).
- **public surface added:** `apply_plan`, `ApplyResult {ops_status, inverse_plan, project_copy_path}`, `ApplyError`; `copy_project`; the op-adapter registry. No RPC yet (WU-plan-rpc wires `director.apply`).
- **test strategy (sidecar gate):** inject a **fake engines table** (each fake returns a known inverse + can be told to raise). Tests: (a) N-op plan applies in order, COPY mutated, source untouched (assert source `project.data` unchanged by identity+value); (b) inverse plan recorded equals the per-op inverses in reverse order; (c) op #k raises → ops 1..k−1 rolled back via inverse, op #k `failed` + reason, ops k+1..N `planned`, COPY equivalent to pre-apply; (d) reversible=False op gated (not auto-applied without the second-confirm flag); (e) `copy_project` round-trips a fixture manifest. Filesystem write behind `# pragma: no cover`; all branch logic 100%.
- **acceptance (falsifiable):** (a) applying a plan never mutates the source manifest (byte-compare before/after); (b) for a forced mid-plan failure the COPY ends byte-equal to the pre-apply COPY (auto-rollback proven); (c) the returned `inverse_plan` re-applied to the post-apply COPY restores the pre-apply COPY (round-trip undo); (d) `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0; (e) gitleaks clean.
- **dependencies:** WU-dsl.
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit.
- **parallel?** **Yes** — Wave 2, parallel with WU-ocr + WU-stitch (disjoint new files).

---

### WU-ocr — `ocrExtractList` engine (RapidOCR over the existing vision consent gate, GAP-2)

- **id:** WU-ocr
- **goal:** read on-screen list/Q&A text → `{text:[...], poster}` (DESIGN §2.2/§3 step #1). SmolVLM2 today only **reorders** candidates (`smolvlm2.py`), it does not extract text. Build the OCR engine over the **registered-but-unbuilt** RapidOCR asset and route it through the **existing** frame-consent vision gate — NO new AI path.
- **files/seams touched:**
  - **new** `sidecar/media_studio/features/ocr_list.py` — `extract_list(frames, *, backend) -> {text, poster}` with `backend` an injected callable (the real-impl seam, mirrors `smolvlm2.py:_default_backend_factory`). `_default_backend_factory` loads RapidOCR from the pinned asset; behind `# pragma: no cover`. Frame sampling + text dedup/ordering is pure.
  - **vision routing (reuse, no new path):** the engine's provider/consent path resolves through `_provider_for_function("vision")` (`handlers.py:575`) + `_resolve_vlm_reranker`'s frame-gate-first pattern (`handlers.py:670`, filtering via `_frame_consented_vision_settings` `:597`) so a 429 failover can NEVER reach a non-consented provider. `ocrExtractList` (frames) is gated **independently** of `editPlan` (text) (DESIGN §6).
  - **asset note (DESIGN §9 F7 — do not propagate confusion):** `assets/manifest.py:266` URL is `ch_PP-OCRv4_det_infer.onnx` while the label at `:290` says "PP-OCRv5". The engine **must not hardcode a version**; it loads whatever the manifest slot resolves. PLAN flags this; the OCR engine is version-agnostic.
- **public surface added:** `extract_list`, `OcrResult {text, poster}`, `OcrError`. The `ocrExtractList` op-adapter (used by WU-apply). No new RPC method (it runs as an op inside `director.apply`).
- **test strategy (sidecar gate):** inject a **fake OCR backend** returning canned boxes/text + a fake frame source. Tests: (a) frames → ordered deduped list + poster path; (b) empty/blank frames → empty list, no raise; (c) frame egress NOT consented → engine refuses the cloud path and falls to local-only (assert the non-consented provider is never reached, mirroring the gate test in the Hub WU-vision); (d) backend raise → typed `OcrError`. RapidOCR load + real frame decode behind `# pragma: no cover`; all logic 100%.
- **acceptance (falsifiable):** (a) a fixture frame set yields the expected ordered list (golden); (b) with frame consent OFF, the transport spy for any cloud vision provider is **never** called (consent honored); (c) `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0 with `ocr_list.py` 100% (heavy seam pragma'd); (d) gitleaks clean (no key in any OCR log line).
- **dependencies:** WU-dsl (op type) — does **not** need WU-apply to build (adapter wires in when both land).
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit.
- **parallel?** **Yes** — Wave 2, parallel with WU-apply + WU-stitch.

---

### WU-stitch — `stitchPanorama` frame-stitch engine (GAP-3a)

- **id:** WU-stitch
- **goal:** stitch a span of scrolling frames into one tall panorama image (DESIGN §3 step #2). No frame-stitch code exists today (`stitch` greps hit only transcript re-stitching in `parakeet_asr.py`/`ctc_align.py`, unrelated — DESIGN §2.2).
- **files/seams touched:**
  - **new** `sidecar/media_studio/features/panorama_stitch.py` — `stitch_panorama(frames, *, aligner) -> PanoramaArtifact {image_path, height, frame_offsets}` with `aligner` an injected callable (real impl = OpenCV/feature-match or vertical-overlap correlation, behind `# pragma: no cover`). The frame-offset accumulation + artifact assembly is pure logic; the pixel-write is the seam.
- **public surface added:** `stitch_panorama`, `PanoramaArtifact`, `StitchError`. The `stitchPanorama` op-adapter. Artifact is read-only (reversible="artifact only", DESIGN §2.2).
- **test strategy (sidecar gate):** inject a **fake aligner** returning canned per-frame offsets + a fake image writer. Tests: (a) ordered frames → expected cumulative offsets + total height; (b) single frame → degenerate panorama (no raise); (c) aligner failure → `StitchError`. Real align/encode behind `# pragma: no cover`; offset math 100% (deterministic).
- **acceptance (falsifiable):** (a) a fixture offset sequence yields the expected `frame_offsets`/`height` (golden); (b) `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0 with `panorama_stitch.py` 100%; (c) the artifact is never written to the source manifest (read-only); (d) gitleaks clean.
- **dependencies:** WU-dsl.
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit.
- **parallel?** **Yes** — Wave 2, parallel with WU-apply + WU-ocr.

---

### WU-regen — `regenScroll` constant-speed scroll renderer (GAP-3b)

- **id:** WU-regen
- **goal:** re-render a **constant-speed** (`easing:"linear"`) glide over the stitched panorama, replacing the erratic original span (DESIGN §3 step #3). Explicitly **NOT** a speed-ramp (DESIGN §2.2/§3) — a fresh linear pan, durable inverse = restore the original span.
- **files/seams touched:**
  - **new** `sidecar/media_studio/features/scroll_regen.py` — `regen_scroll(panorama, *, durationMs, easing, renderer) -> ClipArtifact` with `renderer` an injected callable (real impl = render-cli pan over the panorama, behind `# pragma: no cover`). Frame-time/position curve computation (linear) is pure; the encode is the seam.
- **public surface added:** `regen_scroll`, `ClipArtifact`, `RegenError`. The `regenScroll` op-adapter (inverse = restore original span, recorded by WU-apply).
- **test strategy (sidecar gate):** inject a **fake renderer**. Tests: (a) linear easing → uniform per-frame position deltas (constant-speed assertion — the product claim); (b) duration/panorama-height → expected frame count; (c) non-linear easing rejected in v1 (linear-only, DESIGN §3); (d) renderer failure → `RegenError`. Encode behind `# pragma: no cover`; curve math 100%.
- **acceptance (falsifiable):** (a) the position curve has constant first-difference (zero acceleration) for `easing:"linear"` — falsifiable proof it is not a speed-ramp; (b) `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0 with `scroll_regen.py` 100%; (c) the op's recorded inverse restores the original span; (d) gitleaks clean.
- **dependencies:** WU-stitch (consumes its `PanoramaArtifact`).
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit.
- **parallel?** Partially — serializes after WU-stitch, but parallel with WU-apply/WU-ocr's tails.

---

### WU-undo — `director.undo` (apply the stored inverse plan)

- **id:** WU-undo
- **goal:** one-shot undo by applying the `inverse_plan` recorded at apply-time (DESIGN §5, §7.1).
- **files/seams touched:**
  - `sidecar/media_studio/handlers.py` — new `director_undo` method; registered **only** in `register_all` (`handlers.py:1982`) via `reg("director.undo", ...)` (alongside `reg("ai.planJob", ...)` `:2039`). Reuses WU-apply's `apply_plan` to run the stored inverse on the COPY.
- **public surface added:** RPC `director.undo {planId}` → `{jobId}` (runs on `ctx.jobs`).
- **test strategy (sidecar gate):** drive `director_undo` with a fake `JobRegistry` + a stored inverse plan; assert the inverse is applied and a terminal `job.done` emitted; assert duplicate registration of `director.undo` raises at `register_all` startup (the single-site invariant). 100% via the pure handler + injected jobs.
- **acceptance (falsifiable):** (a) undo after an apply restores the pre-apply COPY (round-trip with WU-apply); (b) `director.undo` is registered exclusively through `register_all` (assert no other `protocol.register`/`reg(` call names it); (c) gate:3 exits 0; (d) gitleaks clean.
- **dependencies:** WU-apply.
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit.
- **parallel?** **Yes** — Wave 3, parallel with the WU-ocr/WU-stitch/WU-regen tails; sequenced vs WU-plan-rpc on `handlers.py`.

---

### WU-plan-rpc — `director.plan` + `director.previewCost` + `director.apply` (the RPC spine)

- **id:** WU-plan-rpc
- **goal:** wire Director onto the substrate: `director.plan` (understand → editPlan LLM via `_run_ai_job` → validate-and-reject → `{planId, editPlan, preview}`), `director.previewCost` (thin wrapper over `ai.planJob`), `director.apply` (job: copy → walk ops → record inverse). Resolves the deferred question **"is `previewCost` distinct or folded into `ai.planJob`"** (DESIGN §7.1/§9).
- **files/seams touched:**
  - `sidecar/media_studio/handlers.py` — new `director_plan`, `director_apply`, and `director_preview_cost` methods. **`director_plan`** calls `self._run_ai_job(ctx, messages=build_edit_plan_messages(...), provider=self._provider_for_function("editPlan"), feature="director", ack=...)` (`handlers.py:1617`) — exactly the `phase8_select` pattern (`:1292`); the `work` closure parses + runs `validate_and_reject` (WU-dsl), returning the typed EditPlan (mirrors `phase8_select`'s work returning `{candidates}`). **`director_preview_cost`** delegates to `self.ai_plan_job(...)` (`handlers.py:1693`) per-function (text editPlan + frame vision) — **DECISION: keep it a distinct method that is a pure pass-through** to `ai.planJob` so the renderer has a stable `director.*` surface, but it performs ZERO extra calls. **`director_apply`** builds the envelope, enforces `_enforce_cloud_budget_ack` (`:1672`, echo `cacheKey` as `confirmBudget`), then runs `apply_plan` (WU-apply) on `ctx.jobs`. All three registered **only** in `register_all` (`:1982`).
- **public surface added:** RPC `director.plan {videoId, goal}` → `{planId, editPlan, preview}`; `director.previewCost {planId}` → `{perFunction:[{function, route, costEst, willEgress, cacheHit, cacheKey}]}`; `director.apply {planId, confirmBudget?}` → `{jobId}`.
- **test strategy (sidecar gate):** fake `RpcContext`/`JobRegistry` + fake provider (returns a canned editPlan JSON) + fake cache/budget. Tests: (a) `director.plan` returns a validated EditPlan, the planner provider came from `_provider_for_function("editPlan")` (assert), the work ran `validate_and_reject` (dropped ops present); (b) `director.previewCost` performs ZERO provider calls (transport spy untouched), returns per-function route/cost/egress/cacheKey; (c) `director.apply` enforces the ack when `confirmCloudBudget` on + will-egress (rejects missing `confirmBudget`, accepts the echoed `cacheKey`); (d) apply runs `apply_plan` on `ctx.jobs` and emits terminal `job.done` with per-op statuses; (e) all three registered exclusively via `register_all` (duplicate-name raises). 100% via injected fakes (no real model/network).
- **acceptance (falsifiable):** (a) `director.plan` issues exactly one editPlan LLM call through `_run_ai_job` and zero through any other path (transport spy: one call, on the editPlan-routed provider); (b) `director.previewCost` transport spy = zero calls; (c) `director.apply` without the echoed `cacheKey` when egress+confirm-on is rejected with the budget-ack error, with it proceeds; (d) media-derived text appears only inside the fenced DATA block of the planner messages (assert structure — injection mitigation #1); (e) gate:3 exits 0; (f) gitleaks clean (key header-only, never logged — log-spy assert).
- **dependencies:** WU-apply, WU-dsl. (WU-ocr/WU-stitch/WU-regen adapters wire into apply as they land; `director.plan` works before them — it only emits ops.)
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit (basedpyright on sidecar).
- **parallel?** Sequenced vs WU-undo on `handlers.py`; parallel with WU-eval-harness setup.

---

### WU-evaluate — `director.evaluate` objective before/after metrics (GAP, DESIGN §4)

- **id:** WU-evaluate
- **goal:** objective goal-vs-result metrics (preferred over a sycophancy-prone LLM judge — DESIGN §4, AGENTS.md §7). Compute before/after on the **understanding signals already available**.
- **files/seams touched:**
  - **new** `sidecar/media_studio/features/director_eval.py` — `evaluate(before, after, *, goal) -> {score, deltas, beforeAfter}`. Deltas (DESIGN §4 table): **motion-jerk** reduction via `features/motion.py` (jerk variance before vs after `regenScroll`); **cut-rhythm regularity** via `features/scene_transnet.py` cut intervals; **silence ratio** via `features/silencetrim.py` dead-air ratio; **OCR-text coverage** (#answers with on-screen text). Pure aggregation over signal dicts the engines already produce (signals are injected — the heavy signal compute is the shipped `phase8.signals` job, not re-implemented here).
  - `sidecar/media_studio/handlers.py` — `director_evaluate` method, registered **only** in `register_all` (`:1982`). Reads `motion`/`scene_transnet`/`silencetrim` signals (via the existing `phase8.signals` job `handlers.py:1196`) for before+after.
  - **optional** qualitative `editPlan` judge note — routed through `_run_ai_job` (no parallel path), **never overrides** the objective deltas (DESIGN §4).
- **public surface added:** RPC `director.evaluate {planId}` → `{score, deltas:{jerk, silenceRatio, cutRhythm, ocrCoverage}, beforeAfter}`. `evaluate` pure function.
- **test strategy (sidecar gate):** inject before/after signal fixtures. Tests: (a) jerk reduction computed (smoother scroll fixture → positive jerk delta); (b) silence-ratio + cut-rhythm deltas; (c) OCR coverage; (d) optional judge note present but score derived from objective deltas only (judge stub returns garbage → score unchanged — falsifiable "never overrides"); (e) `director.evaluate` registered only via `register_all`. 100% via the pure function + injected signals.
- **acceptance (falsifiable):** (a) for a fixture where after-scroll jerk variance < before, `deltas.jerk` is the signed reduction; (b) a malicious/garbage optional judge note does NOT change `score` (objective-only proof); (c) gate:3 exits 0; (d) gitleaks clean.
- **dependencies:** WU-plan-rpc.
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit.
- **parallel?** **Yes** — Wave 4, parallel with WU-eval-harness.

---

### WU-eval-harness — offline golden-plan eval harness (test infra)

- **id:** WU-eval-harness
- **goal:** an offline harness that runs canonical prompts (the Battle-Cats-list example #1, the 50-Q&A example #2 — `FEATURE.md:14-15`) through `director.plan` → `validate_and_reject` → `apply_plan` (fakes at every seam) and asserts the **golden EditPlan + golden eval deltas**, so the planner/validator/eval can't regress silently. This is the falsifiable "does the canonical example still decompose correctly" guard (DESIGN §3).
- **files/seams touched:**
  - **new** `sidecar/media_studio/tests/director/test_golden_plans.py` (+ `fixtures/`) — golden understanding inputs (transcript + phase8 signals + OCR) for the two canonical examples; asserts the produced EditPlan op sequence (e.g. example #1 = `ocrExtractList → stitchPanorama → regenScroll → overlayText → export`, DESIGN §3) and the eval deltas, all with injected fake providers/engines (deterministic, no network/render).
  - **new** `sidecar/media_studio/tests/director/_fakes.py` — shared fake provider (canned editPlan JSON per fixture), fake engines table, fake OCR/stitch/regen backends.
- **public surface added:** none (test-only). Strengthens the gate:3 sidecar suite.
- **test strategy (sidecar gate):** the harness IS tests. The two golden examples must produce their golden plans + deltas; a deliberately-injected "delete all clips" op in the example #2 transcript fixture must be **dropped** by validate-and-reject (end-to-end injection-defense assertion, DESIGN §5). Contributes to the 100% sidecar coverage (no new prod lines, exercises existing ones).
- **acceptance (falsifiable):** (a) example #1 produces exactly the 5-op golden sequence; (b) example #2 (~50 segments) produces the golden trim/reorder/ocr/overlay plan AND drops the injected destructive op; (c) eval deltas match golden; (d) `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0; (e) gitleaks clean (no key in fixtures).
- **dependencies:** WU-plan-rpc (+ consumes WU-evaluate when present).
- **gate cmd:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; pre-commit.
- **parallel?** **Yes** — Wave 4, parallel with WU-evaluate.

---

### WU-panel — `DirectorPanel.tsx` (storyboard/diff/banner/a11y)

- **id:** WU-panel
- **goal:** the renderer surface (DESIGN §7.2-§7.4). Today only `app/renderer/src/panels/ModelsSystemPanel.tsx` exists; `DirectorPanel.tsx` follows its `rpcClient`-injection pattern (`ModelsSystemPanel.tsx:88-106`) for 100% vitest. Implements all design-gate findings F1-F6.
- **files/seams touched:**
  - **new** `app/renderer/src/panels/DirectorPanel.tsx` + `directorPanel.css` + `DirectorPanel.test.tsx` — prompt box → `director.plan`; **storyboard/diff** (Q4: diff over the timeline, NOT side-by-side player); **F1** plain-language summary header (deterministic from `editPlan.ops`, no LLM — e.g. "3 trims, 1 reorder, 47 caption overlays · 2 dropped") + ops grouped by `kind` into collapsible sections (collapsed when > threshold) + op-type filter + drill-down per-op diff; **F2** per-op `status`/`statusReason` rows (dropped = struck-through with reason, failed = engine message + "edit or disable, then re-apply"); **F3** per-data-type cost/egress banner (text-editPlan vs frame-vision/OCR each tied to its own consent gate, frames flagged heaviest cost+privacy, per-function `cacheHit`) sourced from `director.previewCost`; **F4** `rationale`/`statusReason` rendered as **plain-text React nodes only** — no `dangerouslySetInnerHTML` (repo has zero today — grep clean, keep it), no markdown, no link auto-render; the **Apply** button echoes `cacheKey` as `confirmBudget`; eval/before-after view from `director.evaluate`; **F6** "Adjust & re-plan" carrying prior `goal` forward (cache makes re-prompt free), prior plan stays visible until the new one returns.
  - **new** `app/renderer/src/lib/directorTypes.ts` — TS mirror of the EditPlan schema (from WU-dsl's JSON-schema export) so the panel is typed.
  - **a11y (F5, DESIGN §7.4):** keyboard-complete plan review (every op row focusable; expand/collapse, enable/disable-per-op, per-step edit reachable by keyboard; any drag-reorder has move-up/move-down equivalents); SR-announced cost/egress banner + Apply/confirm gate + irreversible-op second-confirm; frame-egress warning carries a **text label** (never color-only) + exposed to AT; `aria-live="polite"` region for `job.progress`/`job.done` (the sibling panel has `role="alert"` only on errors `ModelsSystemPanel.tsx:342` and no live region — DirectorPanel adds it); inherits `aria-label` on root + `role="alert"` on error text (`ModelsSystemPanel.tsx:309/342`).
- **public surface added:** `DirectorPanel` React component (+ its props with injectable `rpcClient` mirroring `ModelsSystemPanelProps.rpcClient` `:88-90`).
- **test strategy (renderer gate `cd app && npx vitest run --coverage`, 100%):** inject a fake `rpcClient` (jsdom). Tests cover: (a) prompt submit → `director.plan` called; (b) **F1** 50-op plan renders the summary header + collapsed groups (NOT 50 flat rows) — assert group count + collapsed state; (c) **F2** dropped op struck-through with its `statusReason`, failed op shows recovery hint (queries by role/text); (d) **F3** banner shows text + frame rows separately, frame-egress text label present, `cacheHit` per function; (e) **F4** a `rationale` containing `<script>`/HTML is rendered as literal text (assert no element injected — XSS-closed); (f) Apply echoes `cacheKey`; (g) **F6** "Adjust & re-plan" pre-fills prior goal + keeps prior plan visible; (h) **F5** keyboard ops (tab to row, enable/disable, move-up/down), `aria-live` region present, frame-egress label exposed to AT — all queried by role/label. Untestable runtime-only lines use inline `/* v8 ignore … -- <reason> */`.
- **acceptance (falsifiable):** (a) `npx vitest run --coverage` exits 0 (100% lines/branches/functions/statements); (b) a `rationale` string of `<img src=x onerror=...>` produces NO DOM element and zero `dangerouslySetInnerHTML` in the bundle (grep + render assert); (c) a 50-op plan renders ≤ a few summary rows by default (grouping proven); (d) the frame-egress warning is present as text and exposed to AT (role/label query) and is not color-only; (e) tsc app passes (gate:2); (f) gitleaks clean.
- **dependencies:** WU-plan-rpc + WU-evaluate (RPC shapes); can begin against the frozen `directorTypes.ts` while WU-eval-harness finishes.
- **gate cmd:** `cd app && npx vitest run --coverage`; pre-commit (oxlint/biome); `tsc` app build (gate:2).
- **parallel?** **Yes** — Wave 5, parallel with WU-eval-harness's tail (different language/dir).

---

## 4. Cross-cutting concerns

- **Single AI path (RAIL).** Every LLM/vision call rides `_run_ai_job` (`handlers.py:1617`) → envelope (`ai_job.py:204/264`) → pool (`provider.py:534/684`) → cache → budget ack. No WU introduces a second transport, job bus, or RPC registration site. **Assert in tests:** new Director modules import no `Provider`/transport directly (planner/validator/eval/apply purity); RPC handlers register only via `register_all` (`handlers.py:1982`).
- **Per-data-type consent (RAIL).** Text (`editPlan`) and frames (`vision`/OCR) are independently gated; the frame gate is evaluated FIRST so a 429 failover cannot reach a non-consented provider (`_resolve_vlm_reranker` `handlers.py:670`, `_frame_consented_vision_settings` `:597`). WU-ocr + WU-panel(F3) + WU-plan-rpc each carry a falsifiable consent-honored assertion.
- **Prompt-injection from media (HIGH, honestly not fully solved on desktop — DESIGN §5).** Layered: (1) structural DATA-fence of transcript/OCR in the planner prompt (WU-dsl); (2) validate-and-reject (WU-dsl) drops impossible/injected ops; (3) human confirm gate is the backstop. WU-eval-harness asserts an injected destructive op is dropped end-to-end. Director must not claim immunity.
- **Reversibility (RAIL).** Apply over a COPY + recorded inverse + stop-on-first-failure auto-rollback (WU-apply); undo (WU-undo). Source manifest is never mutated by Director.
- **Cost honesty (AGENTS.md §9).** N keys ≠ N× quota; the F3 banner shows route+cost, never implies ×N; frame egress flagged heaviest. The cache (`ai_cache.py`, consulted at `ai_job.py:303` per the Hub) makes re-prompt free (WU-panel F6).
- **Standing gate (every WU):** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` + `cd app && npx vitest run --coverage` (100%) + ruff/oxlint/biome (pre-commit) + tsc + basedpyright + gitleaks. Never `--no-verify`; never `git add -A`; stage explicit paths.

---

## 5. Risks & open items for the user

1. **OCR asset version mismatch (DESIGN §9 F7):** `assets/manifest.py:266` URL = `ch_PP-OCRv4` but label `:290` = `PP-OCRv5`. WU-ocr is version-agnostic (loads the manifest slot); the manifest discrepancy itself is a pre-existing asset issue the user may want fixed separately.
2. **regen/stitch backend choice deferred to build (DESIGN §9):** OpenCV vs feature-match for `stitchPanorama`; render-cli pan for `regenScroll`. Both isolated behind injected seams, so the choice does not affect coverage or the WU graph — but it is a real engineering pick at WU-stitch/WU-regen time.
3. **Indirect prompt-injection via media is not fully solved on a desktop host (DESIGN §5):** mitigations are layered, not absolute. Accept-risk decision is the user's.
4. **Execution method (USER DECISION REQUIRED before build):** after the Plan Review Gate passes, choose (1) metaswarm orchestrated, (2) subagent-driven, or (3) parallel session. Per CLAUDE.md this is always asked, never auto-picked. The Wave-2/Wave-4 parallelism above maps cleanly to either orchestrated fan-out or parallel sessions; worktree isolation recommended for the parallel waves (shared `handlers.py` editors must be sequenced).

---

## 6. Definition of Done (v1 MVP)

- All WUs land with gate:3 green (sidecar 100% line+branch via `pytest --cov=media_studio --cov-branch --cov-fail-under=100`; renderer 100% via `npx vitest run --coverage`) + gate:1/2/4/5/6 green + gitleaks clean.
- `director.plan/previewCost/apply/evaluate/undo` registered exclusively through `register_all` (`handlers.py:1982`); every LLM/vision call provably rides `_run_ai_job` + the pool (no parallel path — asserted).
- The two canonical examples (`FEATURE.md:14-15`) decompose to their golden EditPlans and the injected destructive op is dropped (WU-eval-harness).
- Apply is reversible (COPY + inverse + auto-rollback proven), consent is per-data-type and honored, the F1-F6 storyboard/banner/a11y contract is met and tested.
