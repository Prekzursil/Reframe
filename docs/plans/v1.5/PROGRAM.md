# Reframe v1.5 — Program Plan (locked from owner decisions 2026-07-11)

> **Status:** ACTIVE

Synthesized from: 15-agent audit + competitor redo + live visual audit. Owner grill decisions below are FINAL scope.

## Owner decisions (final)
1. **Business model = commercialize + keep-options-open, BUILD-BUT-DON'T-WIRE.** Do ALL the NC→permissive model swaps NOW (mandatory) so commercialization stays possible; build the commercialization scaffolding but **do NOT wire it into the live app** (dormant). No live paywall in v1.5.
2. **Flagship features = ALL FOUR.** Active-speaker + multi-speaker layouts · Transcript-native editing · Local auto-B-roll · Fully-local lip-sync dub.
3. **Sequencing = keystone-refactor-first, then features (1+2+3 combined).** Land the schema-first RPC contract + typed Settings FIRST (de-risks everything), then interleave god-module splits with the feature waves.
4. **Design = FULL pro-shell redesign.** Three-zone shell + best-in-class multi-lane timeline + full IA rebuild + Figma prototypes + evolved Dark-Editorial/Signal-Amber tokens + glass layer + Cmd-K.

## Waves (execution order)

### Wave 0 — De-risk foundation (keystone-first)
- **Schema-first generated RPC contract + typed `Settings`** (retires the 123-method hand-mirror, stale CONTRACTS.md, key-injection allowlist, untyped-settings silent-no-op — one source of truth both sides generate from).
- Sidecar-crash → terminal job event (no more forever-spinning job UI).
- Real cancel + process-tree teardown (Popen+should_cancel on reframe; Job Object/taskkill /T).
- Extend osv gate to torch/GPU/chatterbox lockfiles + unify torch → 2.11.
- Wire ONE real e2e + stdio-RPC contract test into the PR gate (xvfb golden-journey w/ real audio fixture).
- Split the 3 worst god-modules (main.ts, Services, _export_one).

### Wave 1 — Trust / distribution
- ~~Authenticode-signed + attested CI release pipeline (tag-triggered release.yml, pin 4 build SHA-256s, SBOM/provenance, release depends on `quality`).~~
  **REVERSED 2026-08-09 by `docs/plans/v1.5/GRILL-DECISION-QUEUE.md` §F-1:** *"Signing stays NONE (already by design). No SmartScreen concern to solve."* The absent `release.yml` is therefore CORRECT, not an outstanding item. Design docs marked SUPERSEDED.
- Electron 39 (EOL) → 43 + ASAR-integrity fuses + Electronegativity CI. **SHIPPED** — the app runs Electron 43.
- **Licensing swaps (mandatory per decision 1):** ViNet-S (CC-BY-NC-SA) → UNISAL (Apache-2.0); NLLB/Seamless (NC) → MADLAD-400; verify Parakeet/EdgeTAM permissive. Behind existing backend seams.
  - **Translator: DONE, by a different model than planned.** The NC translator was replaced with **Apache-2.0 Qwen3** (tier1 Qwen3-4B / tier2 Qwen3-8B), not MADLAD-400 — the licence objective was met, the named model was not used. Recorded here so the plan stops reading as outstanding. If MADLAD-400 was wanted *specifically*, that is a new decision.
  - **ViNet-S → UNISAL: NOT DONE, and now BLOCKED on a maintainer re-host, not on engineering.** Measured 2026-08-10 (W24). UNISAL was never integrated; the tree still gates ViNet-S off for a commercial build. Findings, each with the probe that produced it:
    - **Licence is NOT the blocker — `rdroste/unisal` really is Apache-2.0.** Two mechanically independent probes: the GitHub `/license` endpoint reports SPDX `Apache-2.0`, and the raw `LICENSE` blob (11,357 bytes, git blob `261eeb9e`) is the verbatim Apache License 2.0 text. The plan's licence premise is CONFIRMED, so the swap remains the right long-term move.
    - **The weights exist but ship ONLY as pickles, and Reframe's load path structurally refuses them.** `training_runs/pretrained_unisal/weights_best.pth` (15,368,928 bytes, blob `f06b52c5`) is in-repo under that same Apache-2.0 grant. But `media_studio/features/_safetensors_loader.py::assert_safetensors_path` permits `.safetensors` ONLY and refuses `.pth` LOUD — a live assertion, not a comment: mutating that gate to accept `.pth` turns `sidecar/tests/test_safetensors_loader.py` RED on three cases (`[weights.pth]`, `[x.safetensors.pth]`, and `test_load_state_dict_refuses_non_safetensors_before_read`). Widening it would re-open the pickle-RCE surface WU I2 closed.
    - **There is a SECOND pickle, and it sits where the gate cannot see it.** The pinned `training_runs/pretrained_unisal/UNISAL.json` sets `cnn_cfg.pretrained: true`, and on that path `unisal/models/MobileNetV2.py` runs `torch.load()` itself against a vendored `unisal/models/weights/mobilenet_v2.pth.tar` (14,205,652 bytes) — inside architecture code, so it bypasses the verify-before-load gate entirely. That directly contradicts `docs/plans/v1.5/model-rehosting.md`, which mandates deleting `torch.load` outright. Constructing with `pretrained=False` and letting the strict checkpoint load supply the backbone MAY avoid this — UNVERIFIED, because it needs torch plus the real weight to try; settle it by loading `weights_best.pth` and diffing its key set against `MobileNetV2`'s `state_dict()` keys.
    - **No safetensors UNISAL exists to point at.** Scoped search: the Hugging Face Hub holds exactly one UNISAL artifact, `litert-community/UniSal-Saliency-LiteRT` — a 6,532,768-byte `unisal_fp16.tflite`, a different runtime family and a third-party conversion of unmeasured fidelity — and the project's own re-host repo `Prekzursil/reframe-asd-weights` contains only `vinet-s-saliency.safetensors` and `transnetv2.safetensors`. So both pickles would need converting and hosting first.
    - **Why no code shipped.** `docs/plans/v1.5/model-rehosting.md` already rules that converting a pickle is "a HOSTING-time, offline, trusted step — NEVER runtime", performed by the maintainer, who then captures the pinned commit and the sha256 of the HOSTED bytes. A manifest `installer="download"` entry cannot be registered without that real sha256 (`assets/manifest.py` raises without a 64-hex pin), and inventing one yields an asset that can never install — saliency permanently degraded, i.e. the exact defect this item exists to fix. Landing the vendored architecture with no loadable weight would be the half-swap this item forbids, so nothing was committed beyond this status block.
    - **API delta, for whoever resumes:** `UNISAL.forward(x, target_size=None, h0=None, return_hidden=False, source="DHF1K", static=None)` takes `[B,T,C,H,W]` and returns `[B,T,1,H,W]` log-softmax maps, against ViNet-S's `[1,C,T,H,W]` → single map. A real rewrite of `saliency_backend.ViNetSaliencyBackend.infer`, but a tractable one behind the existing `SaliencyBackend` seam — the seam itself needs no change.
    - **Correction to this line's previous wording.** It said a commercial build "silently ships worse crop quality". Neither half held. The advisor block is LOUD, not silent: `system_advisor.py:398` returns `spec.reason_block` — "CC-BY-NC-SA 4.0 non-commercial; local-only — dropped for commercial build" — which the UI renders as a reason plus a `Local-only` chip (`advisorMeta.ts::licenseChip`, `ModelCard.tsx`). And the runtime is not gated at all: `features/saliency.py::compute_saliency_signals` never reads `commercial`, so a user who sets it and has the weight installed still gets full ViNet-S crop quality — the exposure is CC-BY-NC-SA weights running in a self-declared commercial context, not a quality degrade. Whether that non-enforcement is deliberate (the advisor is advisory by design) or a gap is a design call left open here, and the licence characterisation is a reading of licence text, not legal advice.
    - **Still open.** The suite remains green because the swap did not happen (`test_handlers_phase8.py::test_system_advisor_commercial_flag_drops_noncommercial` asserts the un-swapped state), which is correct today and must be changed deliberately when the swap lands. Unblocking step, owner action: convert both pickles to safetensors offline, prove tensor equality, host them, and hand back the pinned commit plus each file's sha256.
  - **Forced aligner (not in the original list):** `MahmoudAshraf/mms-300m-1130-forced-aligner` is CC-BY-NC-4.0 and was shipping **undisclosed**. Owner ruling 2026-08-09: disclose it + implement the `allowNonCommercialAligner` opt-in; do NOT swap the default.
- **Commercialization scaffolding, BUILD-BUT-DON'T-WIRE:** licence/edition model, feature-flag gates, edition config — all dormant, no live paywall.

### Wave 2 — Full pro-shell redesign (design track, runs parallel from now)
- Figma prototypes (transpose current app → redesigned three-zone shell + multi-lane timeline).
- IA restructure: collapse the 16+ editor tabs → ~5 phases (Transcribe → Edit → Reframe → Caption → Export); unify the inconsistent nav/brand/top-bar; content-first Library (video grid, readiness demoted).
- Token evolution: surface ladder (never pure #000), glass layer (backdrop-blur floating surfaces), bundled Inter/Geist + IBM Plex Mono + Newsreader (self-hosted, CSP), Cmd-K command palette, motion.
- Fix the WCAG-A hard barrier (mouse-only Timeline → keyboard model) as part of the rebuild.

### Wave 3 — The 4 flagship features (TDD each)
- **Active-speaker + multi-speaker layouts** (NVIDIA ASD NIM local; dynamic cut-to-speaker + 9:16 host/guest split).
- **Transcript-native editing** (delete words → delete video; over existing cues/fillers/silencetrim).
- **Local auto-B-roll** (transcript → concept spans → semantic-match user's OWN indexed library → cutaways).
- **Fully-local lip-sync dub** (translate → TTS → MuseTalk/LatentSync opt-in GPU tier).

### Wave 4 — Close-the-loop + perf + polish
- Reframe trust loop: crop preview + wire the orphaned `ReframeOverridePanel` + confidence badge.
- Viral caption engine (emoji-burst, inline keyword-pop, SFX-on-emphasis, animated word-art, auto-zoom).
- Non-destructive per-clip re-edit; real per-model token pricing (fix the spend-cap "theater").
- GPU encode (nvenc/qsv) + decode-once pipeline + Whisper VAD + Library virtualization.
- Interrupted-job recovery tray + renderer async-error handler + global JobProvider.
- Onboarding coach + progressive ShortMaker disclosure; platform-ready delivery (auto-metadata + one-source→every-platform).
- P2 hardening/modernization opportunistically (CSP, MediaPipe Tasks-API, React 19, FFmpeg-8 AV1, macOS decision-gated).

## Reality note
This is a **major release** (weeks of engineering, not one session). Execution is checkpointed wave-by-wave with fresh adversarial review + the 100% coverage gate per work unit. Design track (Wave 2) runs in parallel from now since it's independent of the refactor.

## Deferred / decision-gated (still open)
- macOS/Apple-Silicon target (owner deferred to a later call — Windows-x64 for v1.5 unless reprioritized).
- Signing route (Azure Trusted Signing vs interim detached-signature) — pick during Wave 1.
- Which flagship ships first within Wave 3 (all 4 are IN; ordering TBD — recommend active-speaker or transcript-editing first as highest-leverage).
