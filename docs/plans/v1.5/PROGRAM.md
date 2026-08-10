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
- **Schema-first generated RPC contract + typed `Settings`** (retires the hand-mirrored method surface, stale CONTRACTS.md, key-injection allowlist, untyped-settings silent-no-op — one source of truth both sides generate from). *The surface size deliberately is NOT stated here: this line said `123-method` until 2026-08-11, which was 73% of the real count and is the exact literal Wave 0's own eng-day estimate was mis-sized from. It is measured and test-pinned in `docs/rpc-contract-v2.md` §1; read it there.*
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
  - **ViNet-S → UNISAL: NOT DONE, and the current state inverts the decision's purpose.** UNISAL was never integrated; instead the tree gates ViNet-S OFF for a commercial build, so a commercial build silently ships **worse crop quality** — the exact outcome decision 1 exists to prevent. Still open; the tests currently assert the un-swapped state as correct, so the suite is green *because* the swap did not happen.
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
