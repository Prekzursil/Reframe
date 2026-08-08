# Reframe Flagship — Active-Speaker + Multi-Speaker Reframing: Spec + Implementation Plan + Go/No-Go

> **Status:** DRAFT

**Author:** workflow subagent (research + design + plan; **no repo files modified**)
**Date:** 2026-07-11
**Repo:** `Prekzursil/Reframe` · checkout `C:/Users/Prekzursil/Documents/GitHub/Reframe`
**Scope:** turn the merged design into an implementation plan + an adversarial go/no-go.
**Grounding read:** the two `.reframe-review` dossiers, the live sidecar source under
`sidecar/media_studio/features/reframe_*`, the PR #282 contract package (`sidecar/contract/*`,
read from `origin/main`), the asset manifest, and the `_lightasd` inference stack.

---

## 0. VERDICT (headline)

**GO — WITH CAVEATS.**

This flagship is **~90 % built and already 100 %-branch-covered on `main`**. The decision is
**"reconcile → finish → harden → wire"**, not "choose a model." The model stack is verified
**permissive (MIT / Apache-2.0 / BSD) and local/offline**, and the remaining work is bounded and
feasible against seams that already exist. A fresh reviewer would agree it is a GO — but would
**insist on five caveats being flagged**, because the owner is commercializing:

1. **S3FD is a live commercial-license blocker** (its weight ships today under *no license*). The
   plan's YuNet swap (WU-L1) is a **BLOCKING gate before any commercial build**.
2. **The `torch.load` pickle path must be eliminated** (safetensors, WU-L2) before commercial ship.
3. **Thresholds are tuned on synthetic fixtures**; AVA saturation → real-world switch errors. Real
   interview/podcast validation via the R0 golden-e2e harness (WU-V1) **gates promoting the engine
   to a default** (it stays explicit opt-in until then).
4. **The working tree is 5 commits stale** (HEAD `8eae986` vs `origin/main 68036fd` = PR #282).
   Reconcile FIRST (WU-F1) or the contract work diverges / re-mints.
5. **pyannote stays a clearly-labeled BYO-HF-token opt-in**, never the default (it is the only
   gated model in the stack; SpeechBrain is token-free).

None of these block *starting*; they are sequencing constraints. Hence **go-with-caveats**, not a
clean "go."

---

## 1. Repo-state reconciliation (do this FIRST — WU-F1)

The dossier and this design were written against a stale tree. Verified live:

| Claim | Reality (verified) |
|---|---|
| HEAD position | `8eae986`, **5 behind** `origin/main` (`68036fd` = PR #282 schema-first contract). |
| `sidecar/contract/*` | **NOT on disk at HEAD** — lands only in PR #282 (`spec.py`, `generate.py`, `schema.py`, `validate.py`, `registry.py`, `generated/contract.schema.json`). |
| "backend seams missing" (dossier) | **STALE** — `saliency_backend.py` **and** `scene_transnet_backend.py` both exist on `origin/main`. |
| reframe feature files | Identical HEAD↔origin/main; only `reframe.py` (+123) and `_capabilities.py` (+6) changed in #282. |

**WU-F1 is a prerequisite**: pull/reconcile to `origin/main`, confirm the contract package +
backend seams are on disk, re-baseline the dossier's stale claims, and run the 100 % gate to
confirm a green baseline **before** any contract or engine work. Reconcile-don't-drop.

---

## 2. Models to adopt — the licensing table (VERIFIED)

Every weight AND its code was license-checked. Confidence graded; citations in §10.

| # | Model / asset | Role in pipeline | Code license | Weight license | Local? | Verdict | Conf. |
|---|---|---|---|---|---|---|---|
| 1 | **LR-ASD** `finetuning_TalkSet.model` (Junhua-Liao/LR-ASD, IJCV 2025) | Visual active-speaker score (lip-motion + A/V sync) | **MIT** | **MIT** (author's own repo) | Yes — vendored `_lightasd`, sha256-pinned on-demand asset | **KEEP** | HIGH — upstream repo + vendored `_lightasd/LICENSE` (© 2025 Liao Junhua) both MIT |
| 2 | **YuNet** `face_detection_yunet_2023mar.onnx` (opencv/face_detection_yunet, © Shiqi Yu) | Face detection (per-frame boxes) | **MIT** | **MIT** | Yes — already vendored (`yunet-face-detection`), the claudeshorts default via `cv2.FaceDetectorYN` | **SWAP-IN** (replaces S3FD) | HIGH — manifest pin + official OpenCV HF mirror |
| 3 | **SpeechBrain VAD-CRDNN** (`speechbrain/vad-crdnn-libriparty`) | Voice-activity / speech regions | **Apache-2.0** | **Apache-2.0** | Yes — HF cache, **token-free** (public, not gated) | **KEEP** | HIGH — SpeechBrain org licensing |
| 4 | **SpeechBrain ECAPA-TDNN** (`speechbrain/spkrec-ecapa-voxceleb`) | Speaker embeddings → diarization | **Apache-2.0** | **Apache-2.0** | Yes — HF cache, token-free | **KEEP** | HIGH — HF model card states Apache-2.0 |
| 5 | **TransNetV2** (soCzech/TransNetV2) | Shot-cut / dissolve detection | **MIT** | **MIT** (derived `.pth`, re-host per dossier) | Yes — degrades to PySceneDetect | **KEEP** (re-host G-2) | HIGH — repo LICENSE = MIT |
| 6 | **PySceneDetect** | CPU shot-cut fallback | **BSD-3-Clause** | n/a | Yes | **KEEP** | HIGH |
| 7 | **EdgeTAM** (facebookresearch/EdgeTAM) | *Optional* occlusion-robust tracker | **Apache-2.0** | **Apache-2.0** ("Our mix", excludes SA-1B) | Yes — vendored, opt-in `reframeTracker="edgetam"` | **KEEP (opt-in)** | HIGH — manifest note verified 2026-07-03 |

**REMOVE (commercial blocker):** **S3FD** `sfd_face.pth` (from `sfzhang15/SFD`) — **NO LICENSE
FILE** (verified: the repo has no `LICENSE`, no About-sidebar license → all-rights-reserved by
copyright default). The rehosting dossier only ever claimed non-commercial. The LR-ASD *code* that
loads it is MIT, but that does **not** relicense the S3FD *weight*. Its removal (WU-L1) is the #1
gate. **Conf. HIGH.**

**OPT-IN ONLY (gated, never default):** **pyannote/speaker-diarization-3.1** — the *code* is MIT but
the *weights are HF-gated* (require an access token + authorization list), which **breaks offline
plug-and-play**. Keep it strictly behind `settings.diarizeBackend="pyannote"` as a clearly-labeled
"bring-your-own-HF-token" opt-in. **Conf. HIGH** (HF gated-repo confirmed).

**Optional forward path (future, non-blocking):** a **sherpa-onnx + 3D-Speaker CAM++** (both
Apache-2.0 ONNX, token-free) diarization backend behind the same `diarize` seam — for torch-less /
CPU-only hosts. Not required for this flagship; noted so it is not re-litigated. **Conf. MEDIUM.**

### 2.1 Rejected alternatives (license reasons — do NOT adopt)

| Rejected | Reason | Owner constraint hit |
|---|---|---|
| **LoCoNet** (SJTUwxz/LoCoNet_ASD) | No LICENSE surfaced = all-rights-reserved; +15–35× params for a ~0.75 pt AVA gap that is noise (UniTalk: LoCoNet 95.2→82.2 in the wild) | commercial + no-NC |
| **NeMo Sortformer / Rev reverb-diarization** | **CC-BY-NC** | no-NC |
| **NVIDIA Maxine ASD NIM** | proprietary EULA + NGC Docker | permissive-only + local |
| **simple_diarizer** | **GPL** (viral) | no-GPL-viral |
| **ViNet-S saliency** (ViNet-Saliency/vinet_v2) | **CC-BY-NC-SA-4.0** — a *different* (no-face) feature; must stay **dead/disabled** in the paid build | no-NC (adjacent trap) |

---

## 3. Architecture recap (what's built, and the one gap)

### 3.1 The canonical pure/heavy seam (already in place)

* **Pure director** (`reframe_multispeaker.py`, ~1.66 k lines, **100 % line+branch covered**): shot
  merging, the `MultiFaceTracker` (greedy-IoU re-id, reset per cut), `OneEuroFilter` smoothing,
  confidence-gated `fuse_active_speaker` (visual × VAD + diarize-agreement bonus), `resolve_speaker_track`
  (HOLD-through-dropout), `decide_layout` + `debounce_layouts`, `map_diarize_to_tracks` (SPEAKER_NN →
  visual-track namespace correlation), `commit_cuts`, `segment_regions` / `plan_render_segments`, the
  `build_filter_complex` / `build_segment_argv` / `build_concat_argv` compositor, and `build_trace`
  → `ReframeTrace`. **No torch/cv2** — exercised with hand-built `ShotAnalysis` fixtures + an injected
  fake `MultiSpeakerBackend`.
* **Heavy backend** (`reframe_multispeaker_backend.py`, `# pragma: no cover`): staged, `release()`d
  between stages (6 GB ceiling): TransNetV2 shots → SpeechBrain diarize → S3FD/YuNet + LR-ASD visual.
  torch/cv2 imported **inside** method bodies.
* **Eval harness** (`reframe_eval.py`, R0): pure trace-vs-golden scoring + a PASS/FAIL gate
  (`shot_f1≥0.9`, `layout_match≥0.85`, `switch_latency≤150 ms`, `speaker_attr≥0.80`, `crop_iou≥0.60`,
  `static_jitter≤baseline`). The real-frame tier is `@e2e`, excluded from the coverage gate.
* **Override layer** (`reframe_override.py`, R2): `plan_from_trace` → editable `ShotPlan`;
  `apply_shot_overrides` → resolved plan + **exact affected-shot set** (re-render only those).

### 3.2 The integration gap (the marketed differentiator, currently missing)

`MultiSpeakerReframeEngine._render` **always** calls `backend.analyze()` then `build_trace()` on a
fresh analysis and renders straight to a file. Consequences (verified in source):

* **No trace producer over the wire** — nothing emits `ReframeTrace`/`ShotPlan` for the UI to edit;
  `reframe.shotPlan` consumes a trace that nothing currently produces.
* **No render-from-edited-plan path** — an edited `ShotPlan` cannot be rendered; every edit would
  re-run the multi-minute GPU analyze.
* **No analysis cache** — edits can't be instant.

The editable timeline + affected-shot-only re-render (the OpusClip-parity escape hatch that
differentiates this from a plain cropper) needs three net-new pieces: **`reframe.analyze`**
(returns `{trace, plan}` without rendering), **`reframe.render`** (renders an externally-supplied
edited plan, affected-only), and a **`ShotAnalysis` cache**. These are WUs E1–E3.

---

## 4. Work-unit decomposition (id · title · scope)

14 work units in 6 waves. Each lands independently behind the 100 % branch gate; the heavy ML is
validated in the opt-in `@e2e` tier (§5). Dependency graph in §6.

### Wave 0 — Reconcile (prerequisite, BLOCKING)

**WU-F1 · Reconcile stale tree + green baseline.**
Pull/reconcile HEAD → `origin/main` (PR #282). Confirm `sidecar/contract/*`, `saliency_backend.py`,
`scene_transnet_backend.py` are on disk. Re-baseline the dossier's stale "seams missing" claim.
Run `pytest --cov=media_studio --cov-branch --cov-fail-under=100` + the renderer vitest gate to
establish a green baseline. **No feature code.** Deliverable: a reconciled tree + a recorded baseline.

### Wave 1 — License remediation (BLOCKING for commercial ship)

**WU-L1 · Swap S3FD → YuNet in the multi-speaker face stage.**
In `_lightasd_infer.analyze_visual`, replace the `S3FD(...).detect_faces(...)` front-end with a
`cv2.FaceDetectorYN` wrapper reusing the already-vendored `yunet-face-detection` asset
(`resolve_yunet_model_path` in `reframe_claudeshorts`). Both emit box geometry → normalize to the
same `(x1,y1,x2,y2)`→`(x,y,w,h)` contract the tracker/crop consume. Drop `lightasd-s3fd` from
`default_models_present`/`availability_reason`. **Coverage:** the swap lives in the `# pragma: no
cover` heavy seam; add pure unit tests for any new box-conversion/geometry helper (numpy-only) and
re-validate the LR-ASD ASD head + face-crop distribution on YuNet boxes in the `@e2e` golden tier
(WU-V1). **Blocking gate #1.**

**WU-L2 · Safetensors re-host + eliminate `torch.load`.**
Complete the dossier's G-5: offline-convert the LR-ASD ASD weight (and any retained detector weight)
`.model`/`.pth` → `.safetensors` (trusted env, `weights_only=True` once, prove tensor-equality),
host on HF single-commit, pin `url`+`sha256`(hosted bytes)+`dest`+`size_mb` in `manifest.py`.
Replace `torch.load` in `_lightasd/asd.py` (and `s3fd/__init__.py` if retained) with
`safetensors.torch.load_file` behind a **load-time format gate** that refuses non-safetensors.
Update `test_assets.py` pins + `_lightasd/__init__.py` `*_WEIGHT_NAME`. **Coverage:** loader-format-gate
branches are pure/testable; the real load stays pragma-excluded. **Blocking gate #2.**

### Wave 2 — Contract additions (schema-first, parity-checked)

**WU-C1 · Wire data-models in `contract/spec.py DATA_MODELS`.**
Add `Segment{startFrame,endFrame,layout}`, `ReframeTrace{shotBoundaries:list[int],
speakerPerFrame:list[str], segments:list[Segment], crops:list[list[float]]}`,
`ShotDecision{index,startFrame,endFrame,speaker,layout,crop:list[float],speakers:list[str]}`,
`ShotPlan{sourceWidth,sourceHeight,fps,shots:list[ShotDecision]}`,
`ShotOverride{index,speaker:str|None,layout:str|None,crop:list[float]|None}`, plus the
`ReframeAnalyzeResult` / `ReframeRenderResult` models. **Introspector constraint (verified in
`schema.py`): only `str/int/float/bool/X|None/list[X]/dict[str,X]/nested-dataclass` — NO tuple**, so
every crop/trace tuple becomes `list[...]`. Field names are the frozen camelCase wire names (N815
suppressed). **Coverage:** a `test_contract_parity.py` case asserts these equal the runtime shapes in
`reframe_eval.py`/`reframe_override.py` (mirrors the Settings↔DEFAULT_SETTINGS parity check).

**WU-C2 · Extend the typed `Settings` model.**
Add `reframeEngine:str`, `diarizeBackend:str`, `reframeAllowSplit:bool`, `reframeAllowComposite:bool`,
`asdConfidenceThreshold:float`, `layoutMinDwellSec:float`, `reframeTracker:str` — all optional,
parity-checked against `media_studio` `DEFAULT_SETTINGS`, so a typo is a compile error not a silent
`None`. Retires the stringly-typed `settings.get("…")` access (finding #6/#7). **Coverage:** parity
test + generator round-trip.

**WU-C3 · Migrate the 3 imperative reframe RPCs to typed MethodSpec.**
`reframe.shotPlan` (`params=ReframeShotPlanParams{trace,sourceWidth,sourceHeight,fps}` → `{plan}`),
`reframe.applyOverrides` (`params={plan,overrides:list[ShotOverride]}` → `{plan, affected:number[]}`),
`reframe.eval` (`params={predicted,reference,fps}` → report; may keep a dict result initially). All
stay `kind="direct"`, `needs_key=False`, and reframe.* stays **OUT** of the `needsKeyInjection`
allowlist. Wire `contract.registry.validate_request` into their dispatch; keep registration through
`composition.py`'s `reg()` (`_key_overlay_wrapper`) seam. **Coverage:** `validate.py` branch tests +
handler tests with a fake registrar (the existing `register(register_fn=…)` pattern).

**WU-C4 · Regenerate + wire the generated artifacts.**
Run `contract/generate.py` → `client.generated.ts`, `schemas.generated.ts`, the `MethodName` union,
`needsKeyInjection.generated.ts`, `contract.schema.json`, Python param validators. Add
`test_contract_parity.py` cases + renderer `parity.test.ts` for the new methods, and
manifest-asset tests pinning the re-hosted safetensors sha256/dest (YuNet + LR-ASD). The
`generate.py --check` staleness gate (byte-stable JSON + source-hash TS) enforces no drift.

### Wave 3 — Engine integration (the missing wiring)

**WU-E1 · `reframe.analyze` (NEW job MethodSpec) — the trace PRODUCER.**
`ts_path=('reframe','analyze')`, `params=ReframeAnalyzeParams{videoId, aspect='9:16',
allowSplit=True, allowComposite=True, allowDegrade=False, diarizeBackend:str|None=None}`,
`binding=NAMED`, `kind='job'`, `needs_key=False`, `result_ts='JobHandle'`. Job body mirrors
`diarize.start` (`ctx.jobs.start(job_body, feature='reframe', gpu=True)` → `{jobId}`), staged
progress `shots→diarize→faces/ASD`, cooperative `should_cancel`. Runs `backend.analyze()` +
`build_trace()` + `plan_from_trace()` **without rendering**; `job.done` =
`ReframeAnalyzeResult{trace, plan, degraded:Notice|None}` (declared as a DATA_MODEL so the renderer's
`useJob<T>` parses it typed). Preserve the typed failure contract: `MultiSpeakerUnavailableError`
(explicit) → typed RPC error; `OfflineError` under offline; auto-degrade → claudeshorts +
`REFRAME_DEGRADED_NOTICE` when `allowDegrade`. **Coverage:** the job body's own branches
(progress/cancel/degrade/error-map) are 100 %-covered via an **injected fake `backend_factory`**
returning a canned `ShotAnalysis`; the real backend stays pragma-excluded.

**WU-E2 · `ShotAnalysis` cache.**
Cache the analysis bundle keyed by `(videoId, aspect, allowSplit, allowComposite)` so edits don't
re-run the GPU. Engine-level, injectable store (in-memory + optional on-disk), size-bounded.
**Coverage:** pure cache key/eviction logic unit-tested; hit/miss branches covered with fakes.

**WU-E3 · `reframe.render` (NEW job MethodSpec) — render an EDITED plan, affected-only.**
`params=ReframeRenderParams{videoId, plan:ShotPlan, aspect='9:16', affectedOnly=True}`,
`binding=NAMED`, `kind='job'`, `needs_key=False`; `job.done={outPath}`. Requires an **engine
extension**: a render-from-external-edited-plan path (today `_render` always rebuilds `build_trace`
from a fresh analysis). Reuse `build_segment_regions`/`plan_render_segments`/`build_segment_argv`/
`build_concat_argv`; re-encode only the affected segments (from `applyOverrides.affected`) and
concat-copy the rest, over the cached `ShotAnalysis`. Atomic temp-write + `os.replace`,
partial-cleanup on OOM (the contract already enforced in `_render_timeline`). **Coverage:** the
new plan→argv path is pure (injected `runner`/`replace_fn`/`remove_fn` seams, as the engine already
does); real ffmpeg only in `@e2e`.

### Wave 4 — UI (OpusClip-parity surfaces)

**WU-U1 · Mode selector + availability/degrade gating.**
Expose `reframe_multispeaker` as a "Multi-speaker (interview/podcast)" mode alongside
auto/claudeshorts/verthor (`REFRAME_ENGINES` already lists it), with `allowSplit`/`allowComposite`
toggles + a `diarizeBackend` picker (SpeechBrain default; **pyannote labeled "bring-your-own-HF-token"
opt-in**). Provisioning card (assets.ensure for YuNet + LR-ASD) + WSL/CUDA banner. Render the three
typed states (`MultiSpeakerUnavailableError`, `OfflineError`, auto-degrade) as **one** degraded badge
(reuse `REFRAME_DEGRADED_NOTICE`) — honor the no-silent-fallback contract.

**WU-U2 · Per-shot editable timeline (the core new surface).**
Render the `ShotPlan` as a shot lane: each shot shows its active-speaker chip, a layout icon
(single/split/composite), and the candidate `shot.speakers`. **Speaker-flip** dropdown (only
candidates allowed → `reframe.applyOverrides`, else a loud `OverrideError`; never a whole-clip
re-render). **Layout switch** (single/split/composite w/ live 9:16 preview: split = 50/50 vstack,
composite = host-top + guests). **Crop nudge** (draggable rect → crop override, clamped by
`reframe_override._clamp_crop`; a degenerate crop is a hard error, not a silent fixup).

**WU-U3 · Speaker ribbon + affected re-render + analyze progress.**
"Who speaks when" lane driven by `speakerPerFrame` with per-speaker face thumbnails (first box of
each visual track) to relabel `SPEAKER_NN`; wire `captionSpeakerLabels`. After edits, show "N shots
changed" (`applyOverrides.affected`) + a "Re-render changed shots" button → `reframe.render(
affectedOnly=true)` (reversible, scoped, never the whole clip). Stream `reframe.analyze` staged
`job.progress` (shots→diarize→faces/ASD) with a cancel button via the existing `useJob` hook; the
cache makes subsequent edits instant.

**WU-U4 · Honest QA-only eval panel.**
Keep the `reframe.eval` gate/metrics as a **hidden QA-only** panel. **Do NOT** surface a fake
decorative "virality/quality score" (the competitor-research lesson — OpusClip's score is
distrusted). If any score is shown, present it as an honest filter with visible reasons.

### Wave 5 — Validation (gates promoting to default)

**WU-V1 · Real-footage re-tuning + golden-e2e (`@e2e`).**
Re-tune `ASD_CONFIDENCE_THRESHOLD` (0.55), `SUBWINDOW_CLUSTER_THRESHOLD` (~0.45),
`LAYOUT_MIN_DWELL_SEC` (0.5) on **real interview/podcast footage** (razvan golden set + WASD/UniTalk),
**never AVA alone** (saturated: LR-ASD 94.45 % AVA → real-world switch errors). Validate the
diarize↔visual binding (`map_diarize_to_tracks`) + the **YuNet-box** LR-ASD ASD head + face-crop
distribution on real footage. Confirm the R0 `run_harness` gate `passed` on the golden set **before
promoting** the engine to a default — until then it stays explicit opt-in (auto = claudeshorts).
This is the `@e2e` tier: opt-in, auto-skipped when the gitignored `REFRAME_GOLDEN_DIR` is absent,
**excluded from the branch gate** (coverage ≠ integration).

---

## 5. Coverage & testing strategy for ML code under a 100 % branch gate

**The gate (verified):** `.coverage-thresholds.json` + `pyproject.toml` → sidecar
`pytest --cov=media_studio --cov-branch --cov-fail-under=100`; renderer 100 % lines/branches/
functions/statements via `vitest.config.ts`. `.coverage-thresholds.json` is the single source of
truth and takes precedence over any skill's own coverage logic. **How ML code hits 100 % branch
without a GPU** — the repo's proven pattern, which every new WU must preserve:

1. **Pure/heavy split at a `Protocol` seam.** Every torch/cv2/ffmpeg/model call lives in a
   `# pragma: no cover` module (`reframe_multispeaker_backend.py`, `_lightasd_infer.py`,
   `_lightasd/s3fd/*`, `diarize_backend.py`, `scene_transnet_backend.py`) whose heavy imports are
   **inside method bodies**, never at module load. The `MultiSpeakerBackend` Protocol (and the
   sibling `DiarizerBackend`/`TransNetBackend`) is the boundary.

2. **Deterministic model-boundary testing = inject a fake backend that returns canned analysis
   arrays.** Tests construct a synthetic `ShotAnalysis` (hand-built `boxes_per_frame` /
   `visual_scores_per_frame` / `diarize_per_frame` / `vad_per_frame`, all length `total_frames`) and
   inject it via `backend_factory`. The **entire director + both new job handlers** (`reframe.analyze`,
   `reframe.render`) run deterministically — no torch, no cv2, no weights, no real video. Every
   boundary branch (staged progress, cooperative cancel, offline-guard, explicit-vs-degrade,
   cache hit/miss, OOM cleanup, error→typed-RPC mapping) is exercised **by the fake**, so it counts
   toward the 100 % branch gate while the real inference is coverage-excluded.

3. **Push testable numeric logic OUT of the pragma'd seam into pure, numpy-only helpers.** The repo
   already does this (`_vad_per_frame`, `_bb_iou`, `_source_frame_index` are real-tested because
   numpy is in the CI env). Any new geometry/box-conversion helper for the YuNet swap (WU-L1) must be
   a pure function tested for real — only the `cv2.FaceDetectorYN` call itself stays pragma'd.

4. **Contract layer is pure stdlib → 100 % is natural.** New dataclasses + MethodSpec entries are
   covered by `test_contract_parity.py` (runtime-shape parity), the `generate.py --check` staleness
   gate (byte-stable JSON + source-hash TS), and per-branch `validate.py` param-validation tests.

5. **Asset/manifest tests pin the re-host** — `test_assets.py` pins the new safetensors
   sha256/dest/url and asserts the asset **names stay stable** (loaders resolve by name).

6. **The real models run ONLY in the opt-in `@e2e` golden tier** (`addopts = -m 'not e2e'`
   deselects it from the gate; a collection guard auto-skips when `REFRAME_GOLDEN_DIR` is absent).
   This is where WU-L1's YuNet-box ASD re-validation and WU-V1's threshold re-tuning + R0 golden run
   live. **Coverage ≠ integration:** pair every heavy-seam change with the `@e2e` tier; do not let a
   100 %-green unit run masquerade as a working pipeline.

7. **Mutation testing (non-blocking nightly, mutmut ≥ 3.6, target 80 %)** is the coverage-blindspot
   backstop on the pure director math — strengthen assertions to kill survivors, never weaken tests.

**Rule of thumb for a fresh contributor:** *if a branch needs a GPU to execute, it belongs in a
pragma'd seam behind a Protocol; if it can execute with a fake/numpy, it must be unit-tested to
100 %; the real model is proven only in `@e2e`.*

---

## 6. Sequencing / dependency graph

```
WU-F1 (reconcile)  ──►  everything
     │
     ├─► WU-L1 (YuNet swap)      ─┐  [BLOCKING gate #1 — before commercial build]
     ├─► WU-L2 (safetensors)     ─┤  [BLOCKING gate #2 — parallelizable with L1]
     │                            │
     ├─► WU-C1 (data models) ─► WU-C2 (Settings) ─► WU-C3 (migrate RPCs) ─► WU-C4 (regenerate)
     │                            │                                              │
     │                            └────────────► WU-E1 (analyze) ─► WU-E2 (cache) ─► WU-E3 (render)
     │                                                     │                         │
     │                                                     └──────────► WU-U1..U4 (UI) ◄┘
     │
     └─► WU-V1 (real-footage tuning + golden-e2e) ◄── depends on L1 (YuNet boxes) + E1..E3
              └─ GATES promoting the engine to a default (stays opt-in until passed)
```

* **L1 + L2** are parallelizable and are the two hard commercial gates.
* **C1→C4** are the contract spine E1/E3 build on (data models + regenerate first).
* **E1 → E2 → E3** are strictly ordered (producer → cache → edited-plan render).
* **U1–U4** consume E1/E3 + the migrated RPCs; U2/U3 are the differentiator.
* **V1** is last and **gates the default-promotion** — never promote on synthetic fixtures.

---

## 7. Adversarial go/no-go (challenges → rebuttals → residual risk)

A fresh-context reviewer with no prior conversation was simulated. Their challenges and the honest
rebuttals:

**Q1. "Are the models REALLY permissive for commercial use?"**
Mostly yes, with one live blocker. LR-ASD **MIT** (verified upstream + vendored LICENSE), SpeechBrain
VAD+ECAPA **Apache-2.0** (verified HF), TransNetV2 **MIT**, YuNet **MIT**, EdgeTAM **Apache-2.0**,
PySceneDetect **BSD-3**. The **only** non-permissive artifact in the *default* path is the **S3FD
weight (no license)** — and the plan removes it (WU-L1). The LR-ASD *weight*
(`finetuning_TalkSet.model`) is from the author's own MIT repo, so it is clean. **Verdict: GO once
WU-L1 lands; the current `main` is NOT commercial-clean until then.**

**Q2. "Are they REALLY local/offline (plug-and-play, no token)?"**
Yes. LR-ASD/YuNet are vendored + sha256-pinned on-demand assets; SpeechBrain VAD+ECAPA load from the
HF cache and are **public/token-free** (unlike pyannote); TransNetV2 needs the dossier re-host but
degrades to PySceneDetect. The **only** gated model is pyannote, and the plan keeps it strictly
opt-in (BYO-token), never default. **Verdict: GO.**

**Q3. "Is the plan feasible, or is this a greenfield ML build in disguise?"**
Feasible — it is ~90 % built. The pure director + eval + override layers are on `main` and already
100 %-branch-covered; the backend seams exist; the contract generator exists. The net-new work is
bounded: the YuNet swap is a *bounded* front-end change (both detectors emit box geometry); the
safetensors re-host is an offline hosting step + a load-time gate + two loader edits; the contract
additions are declarative dataclasses the generator already knows how to emit; and analyze/render/
cache are net-new but wire cleanly onto existing seams (`ctx.jobs.start`, `build_segment_regions`,
`plan_render_segments`, the injectable `runner`/`replace_fn` seams). **Verdict: GO.**

**Q4. "Will it actually work on real footage, or only on synthetic fixtures?"**
Unproven on real footage — this is the **biggest residual risk**. AVA mAP is saturated (LR-ASD
94.45 %), and UniTalk shows top models collapsing in the wild (LoCoNet 95.2→82.2). The thresholds
were tuned on synthetic/small samples. **Mitigation:** WU-V1 re-tunes + validates on real
interview/podcast footage via the R0 golden-e2e harness and **gates the default-promotion** on it;
the engine stays explicit opt-in until the gate passes; the manual per-shot override (WU-U2) is the
required escape hatch for the known two-person-switch failure mode. **Verdict: GO, but do not ship as
a default until WU-V1 passes.**

**Q5. "What about the diarize↔visual binding fragility and off-screen speakers?"**
Real risk: `map_diarize_to_tracks` temporal-correlates SPEAKER_NN onto visual tracks; over/under-
clustering, overlapping speech, and off-screen speakers can bind the crop to the wrong face, and
`resolve_speaker_track`'s HOLD can stick on a stale speaker. **Mitigation:** WU-V1 real-footage
validation + the WU-U2 manual override (flip speaker / nudge crop) as the escape hatch. **Verdict:
acceptable with the override + validation.**

**Q6. "Heavy-job cost / OOM / cancel on a 6 GB WSL host?"**
Handled by design: stages run sequentially with `release()` between them (never two models resident),
the job is cooperatively cancellable (`should_cancel`), the render is atomic-temp + partial-cleanup
on OOM, and the auto-degrade-to-claudeshorts path exists for low-VRAM/CPU-only hosts. WU-E2's cache
prevents re-running analyze on every edit. **Verdict: GO.**

### Residual risks (carry forward, not blockers)

* **S3FD removal is load-bearing** — until WU-L1 + the YuNet-box ASD re-validation land, the paid
  build is not license-clean.
* **Real-world accuracy** — gated by WU-V1; opt-in until proven.
* **ViNet-S NC trap (adjacent)** — must stay dead/disabled in the paid build (do NOT wire it during
  the redesign; the `_motion_center` fallback is the license-clean no-face path).
* **Contract discipline** — the `contract` package must never import `media_studio` (one-way dep);
  dataclass field names are the frozen camelCase wire names; job methods return `JobHandle`
  synchronously with the real payload on `job.done` (declare `*Result` as DATA_MODELS).

---

## 8. What this plan deliberately does NOT do

* Does **not** chase the AVA leaderboard (LoCoNet's ~0.75 pt is noise + a license blocker + 15–35×
  params).
* Does **not** adopt any NC/GPL/gated/proprietary model in the default path.
* Does **not** surface a fake virality score.
* Does **not** wire ViNet-S saliency into the paid build.
* Does **not** make pyannote the default (BYO-token opt-in only).

---

## 9. Definition of Done

* Tree reconciled to `origin/main`; 100 % branch gate green (WU-F1).
* S3FD removed from the default path; YuNet-box LR-ASD ASD head re-validated (`@e2e`) (WU-L1).
* No `torch.load` reachable at runtime; safetensors + load-time format gate; manifest pins hosted
  bytes (WU-L2).
* `reframe.analyze` + `reframe.render` + the migrated RPCs typed in `contract/spec.py`, generated,
  drift-checked, and dispatched through `validate_request` (WU-C1..C4, E1, E3); reframe.* stays out
  of `needsKeyInjection`.
* `ShotAnalysis` cached; edits re-render only affected shots (WU-E2, E3).
* UI: mode selector + degraded badge + editable timeline + speaker/layout/crop overrides + speaker
  ribbon + affected re-render + analyze progress/cancel; no fake score (WU-U1..U4).
* R0 golden-e2e gate `passed` on real footage before the engine is promoted to a default (WU-V1).
* All of the above: 100 % line+branch on the pure/handler tiers; real models proven in `@e2e`.

---

## 10. Sources (with confidence)

* **LR-ASD = MIT** — [github.com/Junhua-Liao/LR-ASD](https://github.com/Junhua-Liao/LR-ASD) (About
  sidebar + LICENSE = MIT); vendored `sidecar/media_studio/features/_lightasd/LICENSE` (MIT © 2025
  Liao Junhua). *Conf. HIGH.*
* **S3FD = no license (blocker)** — [github.com/sfzhang15/SFD](https://github.com/sfzhang15/SFD) (no
  LICENSE file, no About-sidebar license). *Conf. HIGH.*
* **SpeechBrain ECAPA = Apache-2.0** —
  [huggingface.co/speechbrain/spkrec-ecapa-voxceleb](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)
  (model card). VAD-CRDNN (`speechbrain/vad-crdnn-libriparty`) same org/license. *Conf. HIGH.*
* **pyannote-3.1 = MIT-code but HF-gated** —
  [huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
  (extra_gated_fields + access-token required). *Conf. HIGH.*
* **TransNetV2 = MIT** — [github.com/soCzech/TransNetV2](https://github.com/soCzech/TransNetV2) +
  dossier. *Conf. HIGH.*
* **YuNet = MIT** — `opencv/face_detection_yunet` (© 2020 Shiqi Yu), manifest pin. *Conf. HIGH.*
* **EdgeTAM = Apache-2.0** — `facebookresearch/EdgeTAM`, manifest note (verified 2026-07-03). *Conf.
  HIGH.*
* **LoCoNet (rejected)** — [github.com/SJTUwxz/LoCoNet_ASD](https://github.com/SJTUwxz/LoCoNet_ASD)
  (no LICENSE surfaced → all-rights-reserved). *Conf. MEDIUM.*
* **Repo source of truth** — `sidecar/media_studio/features/reframe_multispeaker.py`,
  `reframe_multispeaker_backend.py`, `reframe_eval.py`, `reframe_override.py`, `_lightasd_infer.py`,
  `_lightasd/s3fd/__init__.py`, `diarize_backend.py`, `scene_transnet.py`, `assets/manifest.py`,
  `sidecar/contract/*` (`origin/main`), `handlers/composition.py`, `.coverage-thresholds.json`,
  `sidecar/pyproject.toml`. *Conf. HIGH (read directly).*
* **Dossiers** — `.reframe-review/reframe-model-rehosting-dossier.md`,
  `.reframe-review/reframe-competitor-research.md`. *Conf. HIGH (primary inputs).*
```
