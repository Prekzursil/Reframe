# Reframe AI Program — Converged Program (grill deliverable → plan input)

Companion to `GRILL-DECISION-LOG.md` (the ~29-decision audit trail). This is the one-page synthesis that feeds the PLAN stage.

**THE BET (F1):** local-first wedge — local by default, uncapped, transcript-native, bring-your-own-free-key. Cloud is an opt-in accelerator, never required. Hosted-model gimmicks stay off the critical path.

**ORDER (F2):** Provider Hub first, scoped Director second.

## Critical path (S2)
0. **⛔ G1 — FIX PREVIEW** (a subtitle visibly renders in preview). Hard gate before any preview-dependent build / `/metaswarm:start`. **First build WU.**
1. **Merge phase-8 → main** (S1) — branch the Hub off clean main.
2. **Substrate:** ProviderPool/rotation (multi-PROVIDER stack, same-provider = failover; reactive 429/header-driven, no-sleep hot path; local backstop = embedded llama.cpp + auto-detected Ollama/LM Studio) + AI-Job envelope (A2) + AI-call cache (A3) + pre-flight budget (P1) + graceful-degradation tested (P2). **Cover BOTH LLM seams** — `get_provider` AND `translation.get_translator(...ModelRunner)` (gate-2 CTO finding).
3. **Hub UI:** static multi-provider catalog with per-task tiers + privacy flags (CATALOG-SEED.md); data-driven usage bars (multi-provider stacking + "superpowered", colorblind-safe + reduced-motion + WCAG); presets + per-function customize (PH3); keys (user-brings, redacted, never-logged, RPC returns key-free — gate-2 Security); per-data-type consent (SE1); **vision offload CloudVisionBackend via the smolvlm2 seam** (PH4, after phase-8; gate-2 Architect).
4. **Director v1 (D1):** conversational agent + typed tool-call plan (A1 DSL; D3 hard-validate-reject); toolbox T-stitch / T-scroll / T-ocr-list / T-transcript-edit / T-qa / T-silence; honest-about-limits. **Proof = BC-list scroll-smooth + list-extract (D2)** then 50-Q&A cost-stress; planner model chosen via an eval harness (D4).
5. **Demand-driven follow-ons:** batch queue + repurpose graph (N5), templates, multi-platform reframe/caption presets, semantic footage index, device-aware auto-recommender, AI best-frame thumbnails.

## Also IN (not gimmicks)
Filler-word/silence one-click removal (N1) · speaker diarization — finish existing diarize.py/pyannote (N3) · transcript-as-timeline editing (in the Director toolbox).

## DROPPED / non-goals
DROP: gaze-correction, AI avatars. **Phase-2 explicit non-goal:** generated b-roll, music-gen (hosted-model + licensing = the per-minute-cost + privacy loss that IS the product).

## UX / QoL
Project-relative saves + reveal (UX1) · resume = autosave manifest + recent-projects + resumable jobs (UX2) · per-project export presets (UX3) · auto poster-frame thumbnails now (UX4) · shared availability badges across advisor + hub (UX5) · universal progress/cancel/reveal via the envelope (UX6).

## Safety
Frames local-only default + train-on-input a first-class catalog axis + per-data-type consent (SE1) · multi-provider rotation only, no account-farming, "N keys ≠ N× quota" honored (SE2) · deepfake consent/provenance DEFERRED per the user (SE3) — revisit before any public distribution · security: scrub provider error bodies, RPC never returns a full key, telemetry posture (gate-2 Security — fold into plan).

## Design-Gate-2 (v2 = CHANGES) findings to FOLD into the plan
- **CTO:** rotation must cover BOTH LLM seams (get_provider + translation/ModelRunner); fix the subtitles acceptance to exercise the production path (not the legacy injected one).
- **Security:** error-body scrub + RPC key-redaction invariant + telemetry posture (+ tests).
- **Designer:** dual-limit (req AND token) bar UX; colorblind-safe non-color zone signals; reduced-motion + WCAG for "superpowered".
- **Architect:** vision cloud backend extends the **smolvlm2** seam (not vlm_backbone).
- **PM (non-blocking):** define a default target-job-size; a first-run local-vs-cloud chooser.

## MVP line
preview-fix + phase-8 merge + rotation pool + AI-Job envelope + cache + budget + simplified Hub UI (catalog / keys / usage / presets / consent, both LLM seams) + vision offload. Director, batch queue, templates, and the rest = subsequent WUs.

## NEXT (after this grill)
1. Write the PLAN from the decision log (+ fold the gate-2 findings + CATALOG-SEED). 2. Plan Review Gate (3 adversarial: feasibility · completeness · scope/alignment). 3. Ask the user the execution method (metaswarm orchestrated / subagent-driven / parallel). 4. Build, starting with G1 (preview fix).
