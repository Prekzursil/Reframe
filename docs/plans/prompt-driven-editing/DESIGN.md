# Reframe "Director" v1 — Design (Prompt-Driven AI Video Editing)

**Status:** DESIGN (docs only; no feature code). Next gate: Design Review Gate (5 agents) → PLAN → Plan Review Gate (3) → execution-method choice → build.
**Branch:** `feat/director-v1` (off `origin/main`).
**Date:** 2026-06-18.
**Source spec:** [`FEATURE.md`](./FEATURE.md). **Program context:** [`../ai-program/PLAN.md`](../ai-program/PLAN.md) (the shipped "Provider Hub" / AI-Job substrate).

> **RAILS for this doc.** Every capability claim cites real code as `file:line` on this branch. Where a capability does **not** exist, it is labelled **GAP** explicitly — no fabrication. Director **must not** invent a parallel AI path: every LLM/vision call rides the **same** AI-Job envelope (`models/ai_job.py`), the **same** rotation pool (`models/provider.py`), the **same** per-data-type consent + budget + cache, and registers on the **one** RPC site (`handlers.register_all`).
>
> **Coverage-gate correction (load-bearing).** The brief references `.coverage-thresholds.json`; that file **does not exist in this repo** (`ls .coverage-thresholds.json` → not found). The **real** gate is `.github/workflows/quality.yml` **gate:3** (lines 86-95): sidecar `pytest --cov=media_studio --cov-branch --cov-fail-under=100` (`quality.yml:87-92`) + renderer `npx vitest run --coverage` at 100% (`quality.yml:93-95`). All Director code targets those two commands. Plus gate:1/5 lint+format+secrets (`quality.yml:72-73`: ruff/oxlint/biome via pre-commit), gate:2 types (`quality.yml:76-83`: tsc app + tsc render-cli + basedpyright sidecar), gate:4 SAST opengrep (`:97-98`), gate:6 deps osv-scanner (`:104-110`). Never `--no-verify`; never `git add -A`; stage explicit paths.

---

## 0. Two corrections to the research brief (verified on this branch)

These are *good news* — two pieces of substrate the brief assumed were missing already exist:

1. **`editPlan` is ALREADY a routing function.** `models/presets.py:59` —
   `FUNCTIONS = ("select", "subtitles", "translation", "vision", "editPlan")`.
   The brief said Director "must add an `editPlan` function slot"; it is already wired (the `function not in _presets.FUNCTIONS` check at `handlers.py:514` will already accept `"editPlan"`). Director just needs to *use* it via `_provider_for_function("editPlan")` (`handlers.py:575-584`).
2. **The `vision` function already names OCR.** `presets.py:14` documents `vision — Vision / OCR (task 4)`, and `_REQUIRED_CAPABILITY["vision"] = "vision"` (`presets.py:69`), `_VISION_FUNCTIONS = {"vision"}` (`presets.py:62`). The *routing slot* for OCR exists; the **OCR engine itself is still a GAP** (see §2/§7).

Everything else in the brief verified as written.

---

## 1. The Director agent loop (mapped to shipped seams)

Canonical loop (`FEATURE.md:19-24`): **Prompt → Understand → Plan → Preview+Confirm → Apply → Evaluate → (iterate)**. Director is an **orchestrator** over existing engines; it owns no new AI transport.

```
                ┌─────────────────────────────────────────────────────────────┐
   user prompt  │  director.plan(videoId, goal)                                │
  ───────────►  │   1. UNDERSTAND  read cached transcript + phase8 signals +   │
                │      (optional, consented) vision/OCR of frames              │
                │   2. PLAN        editPlan LLM call via _run_ai_job(          │
                │                    feature="director", provider=             │
                │                    _provider_for_function("editPlan"))       │
                │      → typed, ORDERED, REVERSIBLE EditPlan (§2)              │
                │   3. VALIDATE    reject ops vs real clip durations/precond.  │
                │      (NEW; PLAN.md:230 D3) — injected/impossible ops dropped │
                └───────────────┬─────────────────────────────────────────────┘
                                │ returns {planId, editPlan, preview}
                ┌───────────────▼─────────────────────────────────────────────┐
   PREVIEW      │  director.previewCost(planId)  ── delegates to ai.planJob    │
   + CONFIRM    │   returns {route, costEst, willEgress, cacheHit, cacheKey}   │
   (mandatory   │   (handlers.py:1693 ai_plan_job — ZERO provider calls)       │
    human gate) │  ── renderer storyboard/diff view; user OKs / edits / re-    │
                │     prompts. NOTHING applied without confirm (FEATURE.md:23) │
                └───────────────┬─────────────────────────────────────────────┘
                                │ user approves (echoes cacheKey as confirmBudget)
                ┌───────────────▼─────────────────────────────────────────────┐
   APPLY        │  director.apply(planId, confirmBudget?)                      │
   (job on      │   - write a project COPY (NEW apply-engine; §2 GAP-1)        │
    ctx.jobs)   │   - run each op → existing engine (toolbox §2)               │
                │   - emit a REVERSE EditPlan (undo)                           │
                └───────────────┬─────────────────────────────────────────────┘
                                │ {jobId} → job.progress / job.done
                ┌───────────────▼─────────────────────────────────────────────┐
   EVALUATE     │  director.evaluate(planId)  (NEW; §4 GAP)                    │
                │   objective before/after metrics + optional editPlan judge   │
                │   → {score, deltas, beforeAfter} → user accepts or iterates  │
                └─────────────────────────────────────────────────────────────┘
```

### 1.1 Step → reuse table (file:line)

| Step | Reuses (real code) | Status |
|---|---|---|
| **Prompt** | New `director.*` handlers registered at the ONE site `register_all` (`handlers.py:1982`), exactly like `reg("ai.planJob", svc.ai_plan_job)` (`handlers.py:2039`). | NEW handler, existing site |
| **Understand: transcript** | `transcribe.start` job (`handlers.py:1027`) → `features/transcribe.py`; word timing `ctc_align` (`features/ctc_align.py`). Transcript persisted on the project manifest. | EXISTS |
| **Understand: structure/motion** | `phase8.signals` job (`handlers.py:1196`) → `features/scorer.py` unified tri-modal over `motion.py`/`saliency.py`/`scene_transnet.py`/`audio_saliency.py` → `{tracks, present}`. | EXISTS |
| **Understand: on-screen content (read)** | `phase8.select` already resolves the VLM reranker behind a frame-consent gate: `_resolve_vlm_reranker` (`handlers.py:670`), `features/smolvlm2.py` (`SmolVlmReranker`). | PARTIAL — **re-rank only**, NOT text extraction (GAP §2) |
| **Plan** | Pattern = `features/select.py` `select_unified` (`:707`): two-pass system prompt (`:268`), `<think>` strip (`:70,:358`), JSON parse → typed dicts, map-reduce for long sources (`:621`). LLM reached only through the `Provider.chat` seam. | NEW EditPlan; PATTERN exists |
| **Preview + Confirm (cost)** | `director.previewCost` = thin wrapper over `ai.planJob` (`handlers.py:1693`); `plan_ai_job` is PURE (`models/ai_job.py:204`, ZERO calls). Confirm-before-egress = `_enforce_cloud_budget_ack` (`handlers.py:1672-1691`). | Cost/confirm EXISTS; storyboard/diff UI = NEW |
| **Apply** | Per-op → existing engines (§2 toolbox). But **no op-list apply engine / project-copy / undo exists** today. | **GAP** (apply engine, §2 GAP-1) |
| **Evaluate** | No goal-vs-result engine. `features/quality_gate.py`/`features/ranker.py` are candidate scorers, not critique. | **GAP** (§4) |

Every long step rides the **single job bus** — `ctx.jobs.start` (e.g. `handlers.py:982, 1004, 1077, 1227`) returns `{jobId}` and streams `job.progress`/`job.done`. Director's `plan`/`apply`/`evaluate` jobs use the **same** mechanism via `ai_job.run_ai_job` (`models/ai_job.py`), so no new runtime is introduced.

---

## 2. The EditPlan DSL + operation toolbox

### 2.1 EditPlan: typed, validatable, REVERSIBLE

The EditPlan is a **typed document** (like the existing `Candidate` select result — `features/select.py`), so the **planner is a pure function** (`prompt + understanding → EditPlan`) testable to 100% without rendering (`FEATURE.md:40`). Conceptual shape (Python = `@dataclass(frozen=True)` on the sidecar; mirrored TS type in the renderer):

```
EditPlan
  planId        : str            # cache/preview/apply correlation id
  videoId       : str
  goal          : str            # the user prompt (echoed for the eval judge)
  sourceHash    : str            # content hash of the timeline understanding (cache key input)
  ops           : tuple[EditOp]  # ORDERED, deterministic
  inverse       : tuple[EditOp]  # the undo plan (filled at apply-time, §5)

EditOp (tagged union; `kind` selects the variant)
  id            : str            # stable per-op id (undo + per-step user edit + diff anchor)
  kind          : Literal[...]   # see toolbox below
  span          : {startMs, endMs} | None   # source range the op acts on
  params        : Mapping[str, JSON]        # kind-specific, schema-validated
  reversible    : bool           # False ops are GATED (§5)
  rationale     : str            # model's reason (shown in the storyboard diff; NOT trusted as instruction)
  status        : Literal["planned","applied","failed","dropped"]  # per-op lifecycle (§7.3); planner emits "planned"/"dropped", apply engine sets "applied"/"failed"
  statusReason  : str | None     # typed reason: validation-drop cause (§2.1) or apply-failure message (§5); surfaced in the storyboard (§7.3), NOT trusted as instruction
```

**Validation contract (NEW; `PLAN.md:230` D3, risk #3).** Before an EditPlan is ever returned, `director.plan` runs a **validate-and-reject** pass: every op's `span` is hard-checked against the real clip duration / track existence / preconditions; ops referencing impossible ranges or unknown tracks are **dropped** with a typed reason. Dropped ops are **not silently discarded** — they are returned in the EditPlan with `status="dropped"` + a typed `statusReason` (e.g. `span-exceeds-clip`, `unknown-track`, `precondition-unmet`) so the storyboard (§7.3) can show the user *exactly* what was rejected and why; the user otherwise silently gets less than they asked for. This is also the **primary structural defense against prompt-injection** (§5): an op injected by on-screen/spoken text ("delete all clips") cannot apply if it fails validation, and the human confirm gate is the backstop, not the only defense.

**Q1 resolution (`FEATURE.md:45`):** a **new EditPlan DSL** layered *over* the existing track/cue schema — NOT a raw extension of the in-place timeline ops. Rationale: the existing handlers (`subtitles.edit` etc.) mutate `project.data` in place and `project.save()` (`handlers.py:746-761`), which has **no invert/undo contract**; the DSL is the reversibility layer the in-place handlers lack.

### 2.2 Toolbox — each op → existing engine (or NEW)

| `kind` | Description | Calls (file:line) | Reversible? | Status |
|---|---|---|---|---|
| `trim` / `cut` | Drop a span | `features/silencetrim.py`; manifest track edit via `subtitles.edit`-style replace (`handlers.py:746-761`) | yes (inverse = re-insert span) | ENGINE EXISTS; apply-over-copy NEW |
| `removeSilence` | Cut dead air | `features/silencetrim.py` | yes | EXISTS |
| `removeFillers` | Cut "um/uh" | `features/fillers.py` | yes | EXISTS |
| `reorder` | Move a clip | manifest track reorder (immutable replace pattern, `handlers.py:752-759`) | yes (inverse = move back) | ENGINE primitive EXISTS; apply NEW |
| `retime` / `speedRamp` | Change playback speed of a span | `features/zoom.py`/`reframe.py` time params; render-cli | yes (inverse = restore rate) | EXISTS (speed-ramp) |
| `reframe` / `zoomPan` | Crop/zoom/pan | `features/reframe.py`, `features/zoom.py`, `features/stabilize.py` | yes | EXISTS |
| `caption` | Generate/burn captions | `subtitles.generate` (`handlers.py:722`), polish `features/caption_polish.py`, karaoke `features/ctc_align.py`, burn `tracks.burn` (`handlers.py:952`) | yes (inverse = remove track) | EXISTS |
| `translateCaption` | Translate captions | `subtitles.translate` (`handlers.py:776`) — routes via `_run_ai_job` | yes | EXISTS |
| `overlayText` / `lowerThird` | On-screen text / Q&A answer card | `features/caption_remotion.py` (Remotion overlays) | yes (inverse = remove overlay) | EXISTS |
| `export` | EDL/CSV timeline | `features/nle_export.py` `export`/`build_edl`/`clips_to_events` (`:283/:204/:151`) | n/a (read-only artifact) | EXISTS |
| **`stitchPanorama`** | Stitch scrolling frames into one tall image | — | yes (artifact only) | **GAP (NEW)** — no frame-stitch code; `stitch` greps hit only transcript re-stitching (`parakeet_asr.py`, `ctc_align.py`), unrelated |
| **`regenScroll`** | Re-render a **constant-speed** glide over a stitched panorama (NOT a speed-ramp; `PLAN.md:230`) | — | yes (inverse = restore original span) | **GAP (NEW)** |
| **`ocrExtractList`** | Read on-screen list/Q text → `{text, poster}` | routes via `_provider_for_function("vision")` + `_resolve_vlm_reranker` consent gate (`handlers.py:670`); RapidOCR asset slot registered (`assets/manifest.py:264-292`) but **engine unbuilt** | n/a (read-only) | **GAP (NEW)** — SmolVLM2 today only *reorders* candidates (`smolvlm2.py`), does not extract |
| **`applyEngine`** | Walk `ops` over a project COPY, emit `inverse` | — | — | **GAP (NEW)** — `PLAN.md:272` "unretrofittable", build FIRST |

**Q2 resolution (`FEATURE.md:46`):** v1 op set = the examples' core — `trim/cut`, `removeSilence/removeFillers`, `reorder`, `retime`, `reframe/zoomPan`, `caption/overlayText`, plus the four NEW ops needed by the canonical example (`stitchPanorama`, `regenScroll`, `ocrExtractList`, `applyEngine`). Deferred to v2: b-roll insert, multicam, music bed, transitions library.

---

## 3. Canonical example fully decomposed — "Battle Cats list"

The user's example #1 (`FEATURE.md:14`): a screen recording where a long list (e.g. a Battle Cats unit list) is scrolled erratically. Goal prompt: *"smooth the chaotic scroll so the list reads as one easy glide, and extract the list as on-screen text + a poster."*

**Understanding inputs:** `transcribe.start` (any narration) + `phase8.signals` (`handlers.py:1196`) — `motion.py` flags the scroll region and its jerk profile; `scene_transnet.py` confirms it's one continuous shot. Frames consented at Tier-2 → `ocrExtractList` reads the list.

| # | EditOp | Engine (file:line) | Reversible |
|---|---|---|---|
| 1 | `ocrExtractList {span: scrollRegion}` → `{text:[...units], poster}` | `_provider_for_function("vision")` + `_resolve_vlm_reranker` gate (`handlers.py:670`); **NEW OCR engine** over the RapidOCR asset (`assets/manifest.py:264`) | read-only |
| 2 | `stitchPanorama {span: scrollRegion}` → one tall image of the whole list | **NEW** frame-stitch | artifact only |
| 3 | `regenScroll {span: scrollRegion, panorama: <#2>, durationMs, easing:"linear"}` — constant-speed glide replacing the erratic original (NOT a speed-ramp, `PLAN.md:230`) | **NEW** regen renderer (render-cli) | inverse = restore original span |
| 4 | `overlayText {text: <#1>.text}` — render the extracted list as clean on-screen text | `features/caption_remotion.py` | inverse = remove overlay |
| 5 | `export` — write the timeline (optional) | `features/nle_export.py:283` | n/a |

The planner LLM (`editPlan` function, via `_run_ai_job`) emits ops #1-5 ordered; the **validate** pass checks `scrollRegion` against the real clip duration; `director.previewCost` (`ai.planJob`) shows the cost of the OCR vision call + the editPlan LLM call **before** any egress; on confirm, `applyEngine` runs #1-5 on a **project copy** and records the inverse.

**Q&A showcase (example #2, `FEATURE.md:15`)** reuses the same toolbox: transcript segments the ~50 Q/A boundaries → `trim` dead air between answers → `reorder`/`stitch` into a seamless flow → `ocrExtractList` reads the on-screen question/answer text → `overlayText`/`lowerThird` re-renders it cleanly. This is the **cost-stress** case (§6): 50 segments = many LLM+vision calls, which is exactly why every call must ride the rotation pool + budget preview + cache.

---

## 4. Evaluate / critique step (NEW — GAP)

No goal-vs-result engine exists (`features/quality_gate.py`/`ranker.py` score *candidates*, not edits). v1 `director.evaluate`:

**Q3 resolution (`FEATURE.md:47`):** prefer **objective metrics** over an LLM judge (an `editPlan` judge is sycophancy-prone — `PLAN.md` risk; AGENTS.md §7). Compute before/after on the *understanding* signals already available:

| Goal | Objective signal (engine) |
|---|---|
| "smoother scroll" | **motion-jerk reduction** — `features/motion.py` jerk variance before vs after `regenScroll` |
| "seamless flow" | **cut-rhythm regularity** + **silence ratio** — `features/scene_transnet.py` cut intervals + `features/silencetrim.py` dead-air ratio |
| "polished showcase" | OCR-text coverage (#answers with on-screen text present) |

Output: `{score, deltas:{jerk, silenceRatio, cutRhythm}, beforeAfter}`. An **optional** `editPlan` LLM judge can add a qualitative note but **never overrides** the objective deltas, and is itself routed through `_run_ai_job` (no parallel path). The before/after artifact is the artifact the user accepts/iterates on — the human, not the model, is the final arbiter of "smoother".

---

## 5. Reversibility & safety

**Reversibility (`FEATURE.md:37`, `PLAN.md:272` risk #2 "unretrofittable").**
- **Apply writes to a project COPY**, never the source manifest. Today every handler mutates `project.data` in place and `project.save()`s (e.g. `subtitles_edit`, `handlers.py:746-761`) — there is **no copy, no undo**. The `applyEngine` is built FIRST so the invert/undo contract exists before the first Director edit.
- Each `EditOp` carries `reversible`; `applyEngine` records the `inverse` op as it applies, so the whole EditPlan has a one-shot undo.
- **Irreversible ops are GATED:** any op with `reversible=False` requires a second explicit confirm and is excluded from auto-iterate.

**Mid-apply failure & partial-failure recovery (`director.apply`).** Because apply writes to a project COPY (never the source) and records `inverse` per-op as it goes, a failure at op #k of N is **never** a corrupt half-applied source. The defined behavior:
- `applyEngine` applies ops in order; on the first op that throws/fails it **stops** (no further ops run), marks that op `status="failed"` + `statusReason=<engine message>`, and marks the not-yet-reached ops `status="planned"` (unattempted).
- It then **auto-rolls-back the project COPY** by walking the recorded `inverse` of the ops that *did* apply, leaving the COPY equivalent to the pre-apply state — the source manifest was never touched, so "rollback" is just discarding/inverting the COPY. The source is the durable fallback if even the inverse walk fails.
- The job ends `job.done` with the per-op statuses (applied / failed / planned) and the failed op's reason. The renderer surfaces these in the storyboard (§7.3); recovery for the user is to edit/disable the failing op and re-apply, or accept the rolled-back (no-op) result — the design's own undo engine *is* the recovery path, by construction. v1 default is **all-or-nothing auto-rollback** (stop-on-first-failure); a "best-effort partial keep" mode is deferred to PLAN.

**Prompt-injection from media content (`PLAN.md:230/273` risk #3 — HIGH, unmitigated today).** Director feeds transcript text AND OCR'd on-screen text into the planner LLM. The existing `select.py` injects transcript+prompt into one chat with **no instruction/data separation** (`features/select.py:268`). Director's planner prompt MUST:
1. **Structurally fence** all media-derived text (transcript, OCR) as *untrusted DATA*, never instructions, in the system prompt.
2. **Validate-and-reject** every proposed op against real durations/preconditions (§2.1) — an injected `delete all clips` op that references impossible spans is dropped before it can reach apply.
3. Treat the **confirm-before-apply human gate** (`FEATURE.md:23`) as the *backstop*, not the only defense.
> Honest limit (AGENTS.md §7): indirect injection via tool/media output on a desktop host is **not fully solved**; (1)-(3) are layered mitigation, and Director must not claim immunity.

---

## 6. Consent & budget integration (per-data-type; reuse, no parallel path)

Director rides the **same** envelope as `phase8.select` / `subtitles.translate`:

- **Envelope spine.** Director's `plan`/`apply` call `self._run_ai_job(ctx, messages=..., model=..., provider=self._provider_for_function("editPlan"), work=<director_body>, feature="director", label=..., videoId=..., ack=...)` (`handlers.py:1617-1670`). It builds the PURE envelope (`plan_ai_job_envelope` → `ai_job.plan_ai_job`, `handlers.py:1601-1615`, `models/ai_job.py:204`), enforces the ack gate, and runs on `ctx.jobs` with cache-first (`models/ai_job.py:264-308`). The `work` closure returns its own typed dict (the EditPlan / apply result) — exactly as `phase8_select`'s work returns `{candidates}` (`handlers.py:1254-1283`).
- **Rotation pool.** The provider handed to `work` is the pool from `_provider_for_function("editPlan")` (and `"vision"` for OCR), threading per-function routing through `get_provider(..., prefer=_function_prefer(...))` (`handlers.py:575-584, :553-573`). `build_pool_provider`/`RotatingProvider` (`models/provider.py:684, :534`) give failover, 429 cooldown (no hot-path sleep), local backstop last. `"editPlan"` already in `FUNCTIONS` (`presets.py:59`).
- **Budget + confirm.** Director's Preview = `ai.planJob` (`handlers.py:1693`): returns `{route, costEst, willEgress, cacheHit, cacheKey}` with ZERO calls. On apply, `_enforce_cloud_budget_ack` (`handlers.py:1672-1691`) requires the client to echo the envelope `cacheKey` as `confirmBudget` when `confirmCloudBudget` is on AND the run will egress. Critical for the 50-Q&A cost-stress (`FEATURE.md:41,49`).
- **Consent (text vs frames, SEPARATE).** `providers.setConsent` (`providers_set_consent`, `handlers.py:414`). The vision/OCR path MUST resolve through `_resolve_vlm_reranker` (`handlers.py:670`) which evaluates the **frame-egress gate FIRST** and filters the pool to frame-consented providers per-entry via `_frame_consented_vision_settings` (`handlers.py:597-622`), so a 429 failover can never reach a non-consented provider (`PLAN.md:217`). Director's `ocrExtractList` (frames) and `editPlan` (text) are **independently** gated. v1: text routing `cloudSafe`, vision `local` by default (`presets.py:80-83`).
- **Cache.** `models/ai_cache.py` keys `(content-hash, model, params)`, consulted before any call (`models/ai_job.py:303-306`). Re-prompting the SAME source+goal is free — exactly what the iterate-the-prompt loop needs (`FEATURE.md:24`).

> **Honesty note (`PLAN.md:271`, AGENTS.md §9):** N keys ≠ N× quota per account. The cost preview must never imply ×N capacity; frame egress is the heaviest cost+privacy item (`PLAN.md:273`).

---

## 7. RPC surface + renderer surface

### 7.1 Sidecar RPC (new `director.*`, registered at the ONE site)

Registered in `register_all` (`handlers.py:1982`) via `reg(...)`, alongside `reg("ai.planJob", svc.ai_plan_job)` (`handlers.py:2039`) — **nowhere else** (a duplicate name raises at startup, `register_all` docstring `:1989-1991`):

| Method | Body | Reuse |
|---|---|---|
| `director.plan` | understand → editPlan LLM (`_run_ai_job`, `feature="director"`) → validate-and-reject → `{planId, editPlan, preview}` | `handlers.py:1617`, `select.py` pattern |
| `director.previewCost` | thin wrapper → `ai.planJob` route/cost/egress | `handlers.py:1693` |
| `director.apply` | job on `ctx.jobs`: copy project, walk ops → engines (§2), record inverse → `{jobId}` | NEW apply engine + `nle_export`/`caption_remotion`/`reframe`/`tracks.burn` |
| `director.evaluate` | objective before/after metrics (+ optional judge) → `{score, deltas, beforeAfter}` | NEW; reads `motion`/`scene_transnet`/`silencetrim` |
| `director.undo` | apply the stored `inverse` EditPlan | NEW (depends on apply engine) |

All long ops return `{jobId}` + stream `job.progress`/`job.done` (the shipped bus). v1 may fold `previewCost` into the existing `ai.planJob` to avoid surface bloat — decide at PLAN.

### 7.2 Renderer (new Director panel)

Today only `app/renderer/src/panels/ModelsSystemPanel.tsx` exists (consumes the FROZEN `window.api` bridge via the typed `client`/`rpc` from `lib/rpc`, `ModelsSystemPanel.tsx:15-16, :88-106`; it already sets `aria-label` on its root `<section>` `:309` and `role="alert"` on its error line `:342`, but has **no** `aria-live`/keyboard-nav patterns — DirectorPanel adds those, §7.4). NEW `DirectorPanel.tsx` (same `panels/` dir, same `rpcClient` injection pattern for 100% vitest, `:88-106`):
- **Prompt box** → `director.plan`.
- **Plan preview / confirm** — the storyboard/diff (full UX contract in §7.3); **Q4 resolution (`FEATURE.md:48`):** storyboard diff over the timeline (not raw side-by-side player in v1).
- **Cost/egress banner** — per-data-type breakdown (full contract in §7.3, F3); the **Apply** button echoes `cacheKey` as `confirmBudget` (mirrors `_enforce_cloud_budget_ack`).
- **Eval / before-after view** — `director.evaluate` deltas + accept / **re-prompt** (the iterate return edge, §7.3).
Tests inject `rpcClient` (`ModelsSystemPanelProps.rpcClient`, `:88-90`) so the panel hits 100% with fakes.

### 7.3 Storyboard/diff UX contract (preview surface)

The review surface — not just the apply engine — must scale to the cost-stress case (a 50-op Q&A plan, example #2 `FEATURE.md:15`). The storyboard is the product's safety-critical legibility surface; its contract:

**F1 — large-plan legibility (grouping + summary header).** The storyboard does **not** render 50 raw ops as a flat list. Top-level affordance is a **plain-language plan summary header** generated deterministically from `editPlan.ops` (no LLM) — e.g. *"3 trims, 1 reorder, 47 caption overlays · 2 dropped by validation"*. Below it, ops are **grouped by `kind`** into **collapsible** sections (collapsed by default for any group > a small threshold), with an **op-type filter**. The **per-op diff is drill-down** (expand a group → expand an op), so the default view is a few summary rows, not 50. The summary header counts include dropped ops so the user immediately sees the plan is smaller than requested.

**F2 — per-op status in the storyboard.** Every op row shows its `status` (`planned` / `applied` / `failed` / `dropped`) and, for `failed`/`dropped`, the typed `statusReason` (§2.1, §5) as visible text. Validation-dropped ops are shown **struck-through with their reason** (never silently omitted); after apply, failed ops show the engine message and the recovery hint ("edit or disable, then re-apply"). This makes the validate-drop and mid-apply-failure paths legible at the point of decision.

**F3 — per-data-type cost/egress breakdown (not one boolean).** The banner does **not** collapse egress to a single `willEgress` flag. Mirroring the **two independent consent gates** (§6: text-`editPlan` vs frame-`vision`/OCR), it shows a **per-data-type breakdown**, each tied to its own gate state, sourced from the `ai.planJob` route per function:
  - **Text (editPlan)** → route + cost, and whether it egresses (consent: text gate).
  - **Frames (OCR / vision)** → route + cost, and whether frames egress — flagged as the **heaviest cost+privacy item** (`PLAN.md:273`), with the frame-consent gate state shown explicitly ("frames → cloud vision: NOT consented / consented"). A user must never approve frame egress without seeing it called out separately from text egress.
  Plus `cacheHit` per function (re-prompt-is-free signal, §6). The privacy/consent model is the product differentiator; the banner reflects both gates, not a blob. (Honesty note §6: N keys ≠ N× quota — the banner shows route+cost, never implies ×N capacity.)

**F4 — `rationale` / model-text rendering contract (XSS surface).** Each op's `rationale` (and any model-authored `statusReason`) is model-authored text that may echo injected on-screen/spoken content. It is rendered as **plain text only**: React text nodes (`{op.rationale}`), **never** `dangerouslySetInnerHTML`, **no** markdown/rich-text rendering, **no** link auto-detection/auto-rendering. (Repo has zero `dangerouslySetInnerHTML` uses today — grep clean; DirectorPanel keeps it that way. Aligns with the web security rule on `dangerouslySetInnerHTML`.) This closes the renderer XSS surface the "untrusted text" claim (§2.1, §5) implies, and reinforces it is shown, never run.

**F6 — iterate-the-prompt return edge.** The loop *is* the product (`FEATURE.md:23-24`: approve / edit / **re-prompt**). From both the Plan-preview and the Evaluate view, an **"Adjust & re-plan"** affordance carries the prior `goal` text forward (editable, pre-filled) into a fresh `director.plan` call; because cache keys on `(sourceHash, goal, model, params)` (§6), re-prompting the same source is free. The prior plan stays visible until the new one returns, so the user compares rather than loses context.

### 7.4 Accessibility commitment (F5)

The brief asks about a11y and v1 commits to (full WCAG specifics deferred to PLAN):
- **Keyboard-complete plan review.** The storyboard is fully operable by keyboard: every op row is focusable; expand/collapse, **enable/disable per op**, and per-step edit are reachable via keyboard — **never drag-only** (any drag-reorder affordance has a keyboard equivalent, e.g. move-up/move-down buttons).
- **Screen-reader-announced safety gates.** The cost/egress banner and the Apply/confirm gate are screen-reader announced; the **frame-egress warning must NOT be color-only or visual-only** — it carries a text label and is exposed to assistive tech (it is safety-critical). The **irreversible-op second-confirm** (§5) is keyboard-reachable and announced.
- **`aria-live` job progress.** `job.progress`/`job.done` updates render into an `aria-live="polite"` region so progress and the final per-op status (applied/failed/dropped) are announced, not silent. (The sibling panel today has `role="alert"` only on errors `ModelsSystemPanel.tsx:342` and no live region — DirectorPanel adds the live region.)
- **Inherited precedent.** `aria-label` on the panel root and `role="alert"` on error text follow the sibling panel (`ModelsSystemPanel.tsx:309,:342`). All of the above are covered by vitest (jsdom queries by role/label) toward the 100% renderer gate (`quality.yml:93-95`).

---

## 8. GAP summary (build order)

1. **`applyEngine` (apply over a project COPY + invert/undo + stop-on-first-failure auto-rollback, §5)** — FIRST; unretrofittable (`PLAN.md:272`).
2. **`ocrExtractList`** — OCR engine over the registered-but-unbuilt RapidOCR asset (`assets/manifest.py:264`), routed through the existing `vision` consent gate (`handlers.py:670`).
3. **`stitchPanorama`** + **`regenScroll`** — frame stitch + constant-speed regen (no code today).
4. **EditPlan DSL + validate-and-reject** (D3, `PLAN.md:230`) — incl. per-op `status`/`statusReason` (§2.1, surfaced in storyboard).
5. **`director.evaluate`** objective metrics (D4 eval harness, `PLAN.md:230`).
6. **`DirectorPanel.tsx`** — storyboard/diff with grouping + collapsible groups + plain-language summary header (§7.3 F1), per-op status rows incl. drop/failure reasons (F2), per-data-type cost/egress banner (F3), plain-text-only `rationale` rendering (F4), "Adjust & re-plan" iterate edge (F6), and the §7.4 accessibility commitments (F5: keyboard-complete review, SR-announced egress/confirm, `aria-live` progress).

Each lands behind the proven `# pragma: no cover` real-impl-seam pattern (see `smolvlm2.py` `_default_backend_factory`, `provider.py` `_urllib_post_json`) with injected fakes, so the planner/validator/eval stay pure, fully-tested functions hitting `quality.yml` gate:3 (100% line+branch sidecar; 100% vitest renderer).

---

## 9. Open questions resolved here vs deferred to the gate

- **Resolved:** Q1 (new DSL over track schema), Q2 (v1 op set), Q3 (objective metrics over LLM judge), Q4 (storyboard diff).
- **Designer-gate blocking findings resolved (this revision):** F1 large-plan storyboard UX = grouping/collapsible + plain-language summary header, per-op diff as drill-down (§7.3); F2 apply error/partial-failure + validation-drop UX = per-op `status`/`statusReason` surfaced in the storyboard + stop-on-first-failure auto-rollback recovery (§2.1, §5, §7.3); F3 per-data-type cost/egress banner (text-editPlan vs frame-OCR, each tied to its gate) (§7.3); F4 `rationale`/model-text rendering contract = plain-text-only, no `dangerouslySetInnerHTML`/markdown/link auto-render (§7.3); F5 accessibility commitment = keyboard-complete review, SR-announced egress/confirm + irreversible second-confirm, `aria-live` progress (§7.4). (F6 iterate return edge + F7 RapidOCR v4/v5 label note also addressed: F6 in §7.3; F7 — the asset URL is `ch_PP-OCRv4_det_infer.onnx` while the label says PP-OCRv5 in `assets/manifest.py:264`; DESIGN cites the slot only and does not depend on the version, flagged so PLAN does not propagate the confusion into the OCR engine work.)
- **Deferred to Design Review Gate:** Q5 dependency on Provider Hub — **already shipped** (the AI-Job envelope + pool exist on this branch), so Director can start; confirm sequencing at the gate. Exact EditPlan JSON schema, the regen/stitch backend choice, and whether `director.previewCost` is a distinct method or folded into `ai.planJob` go to PLAN.
