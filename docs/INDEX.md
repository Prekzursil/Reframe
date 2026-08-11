# Reframe — documentation index

> **Status:** ACTIVE
> The only map of this tree. **A doc not reachable from here does not exist.**
> `.quality/docs_check.py` enforces that mechanically inside gate:1.

## Anti-drift

Four rules. They are the whole contract; everything below is just the map.

> **R1 — Authority lives in the repo, or it is not authority.**
> If a document is cited by tracked source, by CI, or by another tracked document, it
> MUST be tracked. A `//` comment, a docstring or a doc line may only cite a
> repo-relative path (`docs/plans/v1.5/SCOPE.md §O-1`) — never a bare section number,
> never a machine-local path, never a directory matched by `.gitignore`. Scratch is
> allowed; scratch that is *cited* is a defect.
>
> **R2 — Every doc carries a status line as line 3, from a closed vocabulary.**
> `> **Status:** DRAFT | ACTIVE | SHIPPED <version> (<date>) | SUPERSEDED BY <repo-relative path> (<date>) | ARCHIVED <date>`.
> The template is [`V1.2-FEATURES.md`](V1.2-FEATURES.md):3. A `SHIPPED`/`SUPERSEDED`
> doc keeps its body — the header is the whole correction. Supersession is written
> into the SUPERSEDED file, never only into the superseding one.
>
> **R3 — One subject, one file; a mirror must name its source and be tested.**
> Any table duplicated between a doc and code declares in its first line which side is
> authoritative, and the mirroring side is protected by a conformance test. Precedent:
> `app/renderer/src/lib/captionTemplates.conformance.test.ts`,
> `app/renderer/src/styles/tokens.conformance.test.ts`.
>
> **R4 — New docs go in exactly one of five places.**
> Program/plan → `docs/plans/<program>/`. Shipped-feature record → `docs/`.
> Evidence/measurement → `docs/validation/`. Justification for a numeric constant →
> `docs/research/`. Everything spent → `docs/_archive/<YYYY-MM>/`. Nothing new at repo root.

`docs/plans/v1.5/README.md` states R1 again in v1.5-corpus terms and keeps the
per-file authority table for that corpus; this section is the tree-wide statement and
[`QUALITY-CHARTER.md`](../QUALITY-CHARTER.md) points here rather than repeating it.

### What the gate checks

`python .quality/docs_check.py` — stdlib only, no network, runs inside gate:1 as a
`pre-commit` local hook (the charter's gate list is closed, so this is not a 7th gate):

| rule | check | waivable |
|---|---|---|
| r1 | every authority doc has an R2 status line at line 3 | no |
| r2 | every `docs/**` / `reports/**` path cited by tracked source resolves | `ssot-allow:` on the same line |
| r3 | every live authority doc is linked from this file | no |
| r4 | no `.gitignore`-matched path is cited by tracked source | `ssot-allow:` on the same line |

A waiver must state its reason on the same line and is greppable
(`git grep "ssot-allow:"`), matching the charter's rule-4 suppression idiom.

The gate sits outside `pytest --cov`, outside basedpyright's `include`, and outside
pre-commit's ruff `files:` filter, so nothing else would notice it turning into a
no-op. `python .quality/docs_check_mutations.py` is its both-states proof: it breaks
one rule at a time in a tracked file, requires the gate to go red naming that rule,
and reverts. Run it after any change to `docs_check.py`.

## The SSOT pointers

The five facts that get contradicted most often, and the one place each is decided.

| subject | the ONLY source | enforcer |
|---|---|---|
| coverage numbers | [`.coverage-thresholds.json`](../.coverage-thresholds.json) — 100% lines/branches/functions/statements on both sides | `.github/workflows/quality.yml` gate:3 + `app/vitest.config.ts`. The JSON is the **declaration**; those two are the **enforcement**. |
| the app version | `app/package.json` | `electron-builder.yml` derives the artifact name from it |
| the RPC wire contract | `sidecar/contract/spec.py` (machine) + [`rpc-contract-v2.md`](rpc-contract-v2.md) (doctrine) | `register_all` at `sidecar/media_studio/handlers/composition.py:71` |
| design-token VALUES | `app/renderer/src/styles/tokens.css` | `tokens.conformance.test.ts`; [`design-system.md`](design-system.md) is the portable human spec |
| gate composition + tool pins | [`QUALITY-CHARTER.md`](../QUALITY-CHARTER.md) | `.quality/charter_check.py` |
| provider catalog + free tiers | `sidecar/media_studio/models/catalog.py` | [`providers/`](providers/SETUP.md) is a human mirror, never the source |
| model URLs, commits, sha256 pins | `sidecar/media_studio/assets/manifest.py` | — |
| the chatterbox env pin list | `sidecar/media_studio/features/tts/chatterbox.py` :: `CHATTERBOX_REQUIREMENTS` | `assets/manager.py:617` compares against the tuple; the `.txt` mirrors IT |

## Repo root

| file | charter |
|---|---|
| [`README.md`](../README.md) | the only user-facing description of WHAT SHIPS: the 8 rails, the 8 Settings sections, install + run. |
| [`CHANGELOG.md`](../CHANGELOG.md) | the only release history; every version in `app/package.json` has a heading. |
| [`QUALITY-CHARTER.md`](../QUALITY-CHARTER.md) | the only place gate COMPOSITION and tool VERSION PINS are declared. |
| [`SECURITY.md`](../SECURITY.md) | the only vuln-reporting policy. |
| [`THIRD-PARTY-LICENSES.md`](THIRD-PARTY-LICENSES.md) | the only record of obligations for REDISTRIBUTED BINARIES, and the home of the GPL written source offer for the bundled FFmpeg. Models/fonts are the in-app Settings → Licenses surface instead. |
| [`CONTRACTS.md`](../CONTRACTS.md) | DEMOTED. Historical P1/P2 build contract; decides nothing. The wire contract is [`rpc-contract-v2.md`](rpc-contract-v2.md). |

## Current program — v1.5

| file | charter |
|---|---|
| [`plans/v1.5/README.md`](plans/v1.5/README.md) | how the v1.5 corpus landed, and which file in it is authoritative for what. |
| [`plans/v1.5/SCOPE.md`](plans/v1.5/SCOPE.md) | the only place the v1.5 scope + section numbering is FIXED, and the home of open items inherited from archived plans. |
| [`plans/v1.5/PROGRAM.md`](plans/v1.5/PROGRAM.md) | the owner-locked decision list and per-wave status. |
| [`plans/v1.5/DESIGN-DIRECTION.md`](plans/v1.5/DESIGN-DIRECTION.md) | the IA + screen build-plan authority. Direction only — `tokens.css` owns values. |
| [`plans/v1.5/GRILL-DECISION-QUEUE.md`](plans/v1.5/GRILL-DECISION-QUEUE.md) | the only record of BINDING owner decisions (B-1 / V-1 / F-1 …). |
| [`plans/v1.5/flagship-active-speaker.md`](plans/v1.5/flagship-active-speaker.md) | flagship #1 build spec. |
| [`plans/v1.5/flagship-transcript-editing.md`](plans/v1.5/flagship-transcript-editing.md) | flagship #2 build spec. |
| [`plans/v1.5/flagship-auto-broll.md`](plans/v1.5/flagship-auto-broll.md) | flagship #3 build spec. |
| [`plans/v1.5/flagship-lip-sync-dub.md`](plans/v1.5/flagship-lip-sync-dub.md) | flagship #4 build spec; the only one carrying a TTS/voice-clone licence gate. |
| [`plans/v1.5/signed-release-ci.md`](plans/v1.5/signed-release-ci.md) | the only plan for the missing release workflow. |
| [`plans/v1.5/signed-release-trust-options.md`](plans/v1.5/signed-release-trust-options.md) | **why** Ed25519 beat cosign / SLSA / Authenticode — the only record of the rationale behind `app/main/updateVerify.ts`. |
| [`plans/v1.5/model-rehosting.md`](plans/v1.5/model-rehosting.md) | the NC→permissive re-hosting dossier. Superseded by `docs/plans/v1.5/PROGRAM.md` on ViNet-S. |
| [`plans/v1.5/techprep-dossier.md`](plans/v1.5/techprep-dossier.md) | shipped-design record for the keystore / WS-D stream. |
| [`plans/v1.5/competitor-research.md`](plans/v1.5/competitor-research.md) | external market input; NOT a repo-grounded authority. |
| `plans/v1.5/redesign.html` · `plans/v1.5/shell-audit/` | the rendered pro-shell mock and the 8-shot captured baseline of the pre-redesign shell. |

## Shipped-release records

| file | charter |
|---|---|
| [`ROADMAP.md`](ROADMAP.md) | the only place "what shipped / what is deferred / what ships next" is decided. |
| [`V1.1-FEATURES.md`](V1.1-FEATURES.md) | the v1.1.0 feature record. §1.2's ASS/BGR contract is cited by `features/caption_override.py:17`. |
| [`V1.1-BUILD-NOTES.md`](V1.1-BUILD-NOTES.md) | the v1.1.0 build record, incl. the passed R0 gate. |
| [`V1.2-FEATURES.md`](V1.2-FEATURES.md) | the v1.2.0 feature record — and the R2 status-line template. |
| [`WU-R0-EVAL-HARNESS.md`](WU-R0-EVAL-HARNESS.md) | the only source of the reframe-eval gate thresholds; code cites it. |
| [`WU-R1-MULTISPEAKER-ENGINE.md`](WU-R1-MULTISPEAKER-ENGINE.md) | the only multi-speaker engine spec. |
| [`CLEAN-BOX-FIRST-RUN-SMOKE.md`](CLEAN-BOX-FIRST-RUN-SMOKE.md) | the clean-box first-run acceptance procedure. |

## Contracts, design, providers

| file | charter |
|---|---|
| [`rpc-contract-v2.md`](rpc-contract-v2.md) | the only wire-contract AUTHORITY doc. |
| [`rpc-contract-v2-migration.md`](rpc-contract-v2-migration.md) | the only POC→whole-surface migration path. States the live method count in **exactly one** place (its header note) and defers to `rpc-contract-v2.md` §1 for the probe that produces it; `test_docs_carry_exactly_one_literal_per_quantity` enforces the "exactly one" half, `test_docs_state_the_measured_surface_size` the "still current" half. The previous wording here — *"deliberately states no method count"* — was **false**: the plan states it three times, and CI actively requires it to state it at least once. |
| [`design-system.md`](design-system.md) | the only portable spec of the tokens. |
| [`providers/SETUP.md`](providers/SETUP.md) | human-facing provider setup; mirrors `catalog.py`. |
| [`providers/MODEL-GUIDE.md`](providers/MODEL-GUIDE.md) | human-facing model picks; mirrors `catalog.py`. |

## Wiring — `§`-numbered unit contracts

28 tracked source files cite these by bare `§` id (e.g. `app/main/main.ts` `// ---- WIRING-T5 §2`),
so the ids survive the move out of the repo root; this entry is how they stay findable.

| file | unit |
|---|---|
| [`wiring/WIRING-T1.md`](wiring/WIRING-T1.md) | timeline subtitle editor |
| [`wiring/WIRING-T2.md`](wiring/WIRING-T2.md) · [`T3`](wiring/WIRING-T3.md) · [`T4A`](wiring/WIRING-T4A.md) · [`T4B`](wiring/WIRING-T4B.md) · [`T5`](wiring/WIRING-T5.md) | the remaining T-lane unit contracts |
| [`wiring/WIRING-U1.md`](wiring/WIRING-U1.md) · [`U2`](wiring/WIRING-U2.md) · [`U3`](wiring/WIRING-U3.md) · [`U4`](wiring/WIRING-U4.md) · [`U5`](wiring/WIRING-U5.md) | the U-lane unit contracts |
| [`wiring/WIRING-social-publish.md`](wiring/WIRING-social-publish.md) | C14 direct publish / scheduling: the per-platform feasibility table with sources (two of four platforms cannot publish to a personal account at all), the no-new-secret-store rule, the residuals, and the owner actions |
| [`wiring/WIRING-gaze.md`](wiring/WIRING-gaze.md) | C15 eye-contact / gaze correction — the licence finding, the open owner decision, the honest quality ceiling, and the likeness-gate reconciliation |

## Evidence and measurement

| file | charter |
|---|---|
| [`validation/v15-audit-ledger.md`](validation/v15-audit-ledger.md) | the only audit SSOT: 225 findings actually checked (131 CONFIRMED + 94 REFUTED). Its headline lesson is *volume is not evidence*. |
| `validation/v15-audit-ledger-unverified.md.gz` | the only home of the 2348 unchecked findings. Kept separate on purpose: merging them makes a claim and a verified finding look alike. |
| `validation/tools/` | the only regeneration recipe for the above (`extract_ledger.py`, `join_verdicts.py`, `join_by_agentid.py`), plus `verify_ssot_claims.py` (the drift verifier) and `probe_dependency_pin.py`. |
| [`validation/w5-visual-artifacts.md`](validation/w5-visual-artifacts.md) | the only record of why a visual-diff failure was undiagnosable from CI (both Playwright configs shared one `outputDir`, and Playwright deletes it per run) and of the `workspace-preview` verdict: accumulated baseline drift, not a regression. Carries the prepared `e2e.yml` upload patch. |
| [`../reports/PHASE8-SOTA-MANIFEST.md`](../reports/PHASE8-SOTA-MANIFEST.md) | the only source of the 15-component SOTA table that `features/system_advisor.py:86-88` mirrors. **Unguarded mirror** — R3 wants a conformance test here. |

## Research — justification for numeric constants

| file | charter |
|---|---|
| [`research/MT-MODELS-2026.md`](research/MT-MODELS-2026.md) | why the MT model pins and the ISO routing tables are what they are. |
| [`research/TTS-ENGINES.md`](research/TTS-ENGINES.md) | the TTS engine selection record. |
| [`research/GOLDEN-JOURNEY-FINDINGS-2026-07-07.md`](research/GOLDEN-JOURNEY-FINDINGS-2026-07-07.md) | the held-out end-to-end acceptance findings. |

## Build and run

| file | charter |
|---|---|
| [`build/RUN-CHECKLIST.md`](build/RUN-CHECKLIST.md) | the only run procedure. **DRAFT** — its pins are stale against `sidecar/pyproject.toml`; rewrite pending. |
| [`build/COMPLETENESS-REPORT.md`](build/COMPLETENESS-REPORT.md) | superseded and wrong at the headline, kept because `HIGH-1` / `HIGH-3` finding ids are cited by five live source files. |
| [`build/INTEGRATION-REPORT.md`](build/INTEGRATION-REPORT.md) | same — header, do not delete. |
| [`build/DESIGN-DIRECTION.md`](build/DESIGN-DIRECTION.md) | superseded by `design-system.md`; 9 of its 14 palette values contradict `tokens.css`. Merge-and-archive is tracked as phase-2 item 2.7, not done. |

## Archive

Nothing here is authority. Every file carries a status header naming what replaced it.
Archived plan bundles additionally carry dead `handlers.py:NNN` anchors throughout —
`sidecar/media_studio/handlers.py` was deleted in `c12400c4` (v1.1.0) and is a package
now. Their bodies are left intact as historical record; the header is the correction (R2).

| directory | what is in it |
|---|---|
| `plans/_archive/ai-program/` · `provider-hub/` | the AI-provider-hub program. Shipped as `models/ai_job.py`, `models/provider.py`, `models/catalog.py`. `provider-hub/CATALOG-SEED.md` stays at its archived path — it is the provenance record `catalog.py:7,:164` and `test_catalog.py:4` cite. |
| `plans/_archive/prompt-driven-editing/` | shipped-partial as `features/director.py`, `director_op_engines.py`, `director_eval.py`. The deferred fuller surface is open item O-3 in `plans/v1.5/SCOPE.md`. |
| `plans/_archive/repurpose/` | shipped as `features/{batch,templates,export_presets}.py` + their panels. |
| `plans/_archive/intelligence/` | shipped as `features/{recommender,best_frame,semantic_index}.py`. |
| `plans/_archive/ux-qol/` | shipped as `job_store.py`. |
| `plans/_archive/editing-refine/` | shipped as `features/refine.py`, `features/diarize.py`. |
| `plans/_archive/v1.4-experience-overhaul.md` | the v1.4 plan. Its one unshipped sub-unit (WU-3a3) is open item O-2 in `plans/v1.5/SCOPE.md`. |
| `_archive/2026-06/` | pre-v1.3 plan/gate artifacts (`PLAN-P1`, `PLAN-P2`, `PLAN-P4-REFRAME-OPUSCLIP`, `DESIGN`, `DESIGN-GATE-1`, `V1-GRILL-DECISIONS`, `reframe-v1.3-settings-gaps`), the two P2 build reports, `docs/_archive/2026-06/LLM-BACKEND.md`, and `docs/_archive/2026-06/PR-PURGE-CHECKLIST.md`. |
| `_archive/2026-07/` | `docs/_archive/2026-07/reframe-visual-audit.md` and `docs/_archive/2026-07/reframe-reconcile-audit.md` (both actively wrong — kept as a lesson, see `plans/v1.5/README.md`), and `handoff/` (two v1.4 handoff docs). |

### v1.5 audit fleet (2026-08)

| Doc | What it decides |
|---|---|
| [`plans/v1.5/captions-translation-audit-2026-08.md`](plans/v1.5/captions-translation-audit-2026-08.md) | captions / subtitles / transcription / translation audit + design |
| [`plans/v1.5/competitor-matrix-2026-08.md`](plans/v1.5/competitor-matrix-2026-08.md) | competitor capability matrix vs the measured repo state |
| [`plans/v1.5/distribution-audit-2026-08.md`](plans/v1.5/distribution-audit-2026-08.md) | installer, updater, code-signing and backward-compatibility audit |
| [`plans/v1.5/editing-surface-audit-2026-08.md`](plans/v1.5/editing-surface-audit-2026-08.md) | general video-editing surface audit (what exists vs what a pro editor needs) |
| [`plans/v1.5/uiux-qol-audit-2026-08.md`](plans/v1.5/uiux-qol-audit-2026-08.md) | UI/UX + quality-of-life audit driven against the INSTALLED app |
