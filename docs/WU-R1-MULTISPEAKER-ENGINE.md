# WU R1 — Hybrid Multi-Speaker Reframe Engine (the flagship)

> **Status:** PURE LAYER + SEAM SHIPPED (100% line+branch). GPU/real-frame tier
> is an **OPERATOR-BLOCKER** (see §7) — the engine is registered + selectable but
> NOT marked "validated" until it clears the R0 eval-harness gate on real frames.
> **Branch:** `feat/v1.1.0` · **Design:** `docs/V1.1-FEATURES.md` §GATE-2 (R1) +
> the R1 design-gate required-changes; basic-memory
> `reframe-multi-speaker-engine-approach-decided-hybrid` /
> `opus-clip-teardown-razvan-gandu`.

This is the committed **public-interface brief** the design-gate required: how the
multi-cut / split / composite output integrates with the single-crop
`ReframeEngine.reframe` contract, the `REFRAME_ENGINES` frozenset + `ENGINES`
registry, the pure decision-layer seam signatures, and the sequential model-load /
free contract.

## 1. What it is

A per-segment **DIRECTOR / decision layer** stacked over the EXISTING parts
(TransNetV2 shot detect + PySceneDetect fallback, mediapipe→HOG→motion detection,
Light-ASD visual active-speaker, `diarize` turns, `audio_saliency` VAD). Instead
of the one tracked crop the `claudeshorts` engine renders, it decides — per shot,
per committed speaker turn — a **single / 50-50 vertical split / composite (host
top + guests bottom)** vertical 9:16 layout.

It is engine **3** (`reframe_multispeaker`) registered in
`reframe.ENGINES` and `export_presets.REFRAME_ENGINES` (renderer mirrors:
`shortMakerLogic.REFRAME_ENGINE_OPTIONS` + `REFRAME_ENGINE_LABELS`, and
`repurposeLogic.REFRAME_ENGINE_OPTIONS`).

## 2. Pipeline (pure half — 100% covered, torch-free)

```
shots:   TransNetV2 (+PySceneDetect fallback)  →  merge_short_shots (~0.5s min;
         boundary = MANDATORY crop reset)        shot_spans
detect:  mediapipe → HOG → motion (backend)    →  MultiFaceTracker (greedy IoU /
                                                  Hungarian-style re-id; stable
                                                  ids WITHIN a shot, reset at cut)
ASD:     Light-ASD visual score  ⊕  diarize    →  fuse_active_speaker (VAD-gated,
         turn  ⊕  audio_saliency VAD              diarize-agreement bonus,
                                                  confidence-gated) → resolve_
                                                  speaker_track (HOLD on dropout)
layout:  concurrent-active count               →  decide_layout (single/split/
                                                  composite) → debounce_layouts
                                                  (min-dwell ~0.5s anti-flicker)
cut:     shot boundaries ∪ committed turns      →  commit_cuts / speaker_turn_frames
                                                  (HARD CUT) ; One-Euro smooth
                                                  (median-prefiltered, dead-zone)
                                                  WITHIN a single-subject run
render:  ffmpeg filter_complex                  →  build_filter_complex (per-region
         (per-region crop→scale→vstack/overlay)   crop→scale→vstack/overlay →
                                                  1080x1920) + build_composite_argv
```

The director's output is a
`reframe_eval.ReframeTrace` (`shotBoundaries`, `speakerPerFrame`, layout
`segments`, per-frame `crops`) — the SAME contract the **R0** eval harness scores
and the **R2** override layer (`reframe_override.plan_from_trace`) edits. So the
flagship engine plugs straight into the existing R0/R2 surfaces with no new wire
shape.

## 3. Public interface (integrates with the single-crop contract)

`MultiSpeakerReframeEngine.reframe(in_path, out_path, aspect, on_progress,
should_cancel, on_notice) -> out_path` — byte-identical signature to the
`verthor` / `claudeshorts` engines, so `shortmaker._lazy_reframe` / `get_engine`
thread it unchanged. The richer multi-region output is internal: the engine emits
ONE 9:16 file at `out_path` exactly like the other engines (the multi-cut/split/
composite is *inside* the clip, decided per segment).

- **Registry:** `reframe.ENGINE_MULTISPEAKER = "reframe_multispeaker"`,
  `reframe.ENGINES["reframe_multispeaker"] = MultiSpeakerReframeEngine`.
- **Selector semantics (P3 contract preserved):** `"auto"` STILL resolves to
  `claudeshorts` with **no WSL probe and notice `None`** — unchanged. The
  multi-speaker engine is **EXPLICIT-only** in the selector
  (`resolve_engine_name("reframe_multispeaker")` returns itself, no probe); the
  availability contract is applied at `reframe()` time, not resolve time.

## 4. Failure-mode contract (mirrors `reframe.py` / GATE-2 + design-gate)

| Situation | Behaviour |
|-----------|-----------|
| EXPLICIT request, WSL/CUDA/weights absent (`allow_degrade=False`) | raise typed **`MultiSpeakerUnavailableError`** naming the real cause — NOT `OfflineError` (its "Turn off Offline mode" message is wrong for a missing GPU) |
| Offline mode ON + weights not cached | raise **`OfflineError`** via `offline.guard_network` (the correct, actionable message) |
| AUTO-attempt (`allow_degrade=True`), host can't run it | degrade to single-speaker `claudeshorts` + a loud **`reframe.degraded`** notice via `make_engine_degrade_notice` (reuses the TYPE, distinct message — NOT `make_degraded_notice`'s "used center crop") |
| Cold-start: first shot, no confident speaker | `claudeshorts.select_dominant` over the shot's faces (deterministic), NEVER a silent center crop; only a truly face-less shot falls to frame centre |
| OOM / model-load / encode failure mid-render | raise **`MultiSpeakerRenderError`** AND clean up the partial output |

**Atomic, lineage-safe write:** the render encodes to `out_path.multispeaker.part`
and is **`os.replace`d onto `out_path` on success ONLY** — an OOM/crash can never
leave a corrupt half-clip at `out_path` for L2 lineage-on-success.

## 5. Heavy-ML seam + sequential model staging (6 GB VRAM)

`MultiSpeakerBackend` is a `Protocol` NEVER imported at module load. The real impl
(`reframe_multispeaker_backend.RealMultiSpeakerBackend`, `# pragma: no cover`) is
built lazily by `_default_backend_factory`. Stages run **sequentially with an
explicit free between** so a 6 GB GPU never holds two models:

```
detect_shots → release() → diarize → release() → faces+Light-ASD+VAD → release()
```

`MultiSpeakerReframeEngine._render` calls `backend.analyze(...)` then
`backend.release()` in a `finally` (freed even on analyze error). The pure decision
layer is torch-free behind the Protocol.

## 6. New deps — F3c integrity pinning

Light-ASD weights (`TaoRuijie/Light-ASD`) register through
`assets.manifest.register_asset` with a **pinned `hf_revision`** (40-hex commit);
**gdown / torch.hub / Google-Drive / git-clone are FORBIDDEN** (they bypass F3c
integrity pinning). Light-ASD ships its weights in its GitHub repo, not on the HF
hub, so — exactly the live `scene_transnet` precedent — `register_multispeaker_assets()`
is an **honest no-op** until an operator confirms a *loader-compatible HF mirror*
and pins its commit hash (a dead/unverified pin is worse than an honest
"unavailable"). `default_models_present` then reports the engine unavailable, so the
pure layer + seam ship and the engine fails loud / degrades per §4.

## 7. R0 eval-harness gate + OPERATOR-BLOCKER

Per design, R1 may be promoted to a *validated default* only after a run of the
**R0 harness** (`reframe_eval.run_harness`, `reframe-eval` CLI) on the private
OpusClip golden set (`Downloads/razvan_gandu`, **gitignored, never committed, not
in the 100% pure tier**) `passed`: shot-F1 ≥ 0.90, speaker-attribution within
tolerance, and `static_shot_jitter` NOT regressed vs the shipped engine baseline.

Because the GPU/real-frame backend cannot run headless in this environment, the
**GPU validation is an operator-blocker**: ship the pure layer + seam; the engine
is registered + selectable but is **NOT** marked validated. OPERATOR ACTION:
(1) confirm a loader-compatible, commit-pinned Light-ASD HF mirror and register it
(§6); (2) run the R0 harness via `reframe-eval --reference <golden> --source <clip>
--engine reframe_multispeaker` (inject a concrete engine runner); (3) confirm the
gate `passed` before promoting it past explicit opt-in.

## 8. Tests

`sidecar/tests/test_reframe_multispeaker.py` (100% line+branch on the pure module
via hand-built fixtures + a fake backend) and the backend import-surface in
`tests/test_phase8_backend_surfaces.py`. Registry/selector/preset integration in
`test_reframe_claudeshorts.py`, `test_reframe.py`, `test_export_presets.py`.
Renderer mirrors: `repurposeLogic.test.ts`, `ShortMaker.test.tsx`.

## 9. v1.2.0 addendum — SpeechBrain pin + detector note

**SpeechBrain declared + pinned in the `reframe-gpu` extra (via #255).** The
audio side of the active-speaker fusion (§1) loads SpeechBrain's pretrained **VAD
(CRDNN)** + **ECAPA-TDNN** diarizer (`reframe_multispeaker_backend` →
`diarize_backend.RealDiarizeBackend`, lazy-imported at run-time only). As of
v1.2.0 that dependency is a **declared, pinned** member of the `reframe-gpu`
extra rather than an implicit host package:

- **`speechbrain==1.0.3`** — the GPU-validated version; a floating install can pull
  an API-incompatible SpeechBrain and break the diarizer's model load. When it (or
  its backend) is unavailable the diarizer **fails loud with a typed error** — it
  never silently degrades the fusion.
- **`huggingface-hub<1.0`** — SpeechBrain 1.0.3 uses the pre-1.0 `huggingface-hub`
  model-fetch API; `huggingface-hub>=1.0` removed/changed it, so the pin keeps the
  pretrained VAD/ECAPA download working.
- **Windows `k2_fsa` gotcha** — SpeechBrain's *optional* ASR/CTC recipes pull
  **`k2` (k2-fsa)**, which has **no prebuilt Windows wheel** and fails to
  `pip install` there. This engine's diarizer uses **only the VAD + ECAPA path**,
  which does **not** require `k2`, so `speechbrain==1.0.3` installs cleanly — do
  **not** pull the k2-backed extras. The GPU tier is provisioned/validated under
  **WSL2 Linux** (`~/reframe-gpu-venv`, torch 2.6.0+cu124; see
  [`V1.1-BUILD-NOTES.md`](V1.1-BUILD-NOTES.md)), where k2 is a non-issue anyway.

  > The `speechbrain==1.0.3` line is owned by PR #255 (it edits
  > `sidecar/pyproject.toml` + `diarize_backend.py`); this section documents the
  > pin, it does not introduce it.

**Detector note (v1.2.0 WU1).** The **default** `claudeshorts` reframer now detects
faces with a single native **YuNet** model (`cv2.FaceDetectorYN`), replacing the
old MediaPipe/haar + HOG path referenced in §1–§2. The multi-speaker engine's own
detection stack (the vendored **S3FD** face detector feeding LR-ASD, in
`features/_lightasd/`) is unchanged.
