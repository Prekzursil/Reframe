# Design Review Gate #1 — verdict: ITERATE (2026-06-11)

5/5 reviewers CHANGES-REQUIRED. Core calls sound (compute/UI split, Provider abstraction, trains_on_data gate,
license-first models, honest 6GB reality). Fold these into DESIGN.md before planning.

| Reviewer | Top required change |
|---|---|
| PM | Define P1 as a product ACCEPTANCE TEST (input length, # share-worthy clips, end-to-end time on 4050), not a feature checklist |
| Architect | Specify job/progress IPC contract + VRAM-aware scheduler with exclusive GPU lanes + real cancellation |
| Designer | Add Information Architecture (launch screen, nav, flagship↔tools); collapse engine/model choices into outcome-based controls |
| Security | Model-weight download integrity (SHA-256/signed manifest, safetensors-over-pickle, verify-before-load) — currently absent = RCE/supply-chain hole |
| CTO | Hardware/OS support matrix (tiers) + two de-risking spikes (local-4B short-selection quality; sidecar VRAM orchestration) BEFORE committing P1 |

## Required changes (R1–R8)
- **R1 IPC/VRAM spine:** **stdio JSON-RPC** (not a localhost HTTP port — kills port-collision + unauth-loopback); job = id + persisted status + progress-event schema + real cancellation; **VRAM-aware scheduler w/ exclusive GPU lanes** (whisper/LLM/verthor/Remotion never co-resident-OOM — enforced, not by convention); sidecar supervision (spawn/health/restart; atomic temp+rename asset writes).
- **R2 Security invariants:** (a) weight-download integrity = SHA-256/signed manifest in the signed installer, verify-before-load, **safetensors over pickle** (pickle only via weights_only); (b) subprocess = argv-list only (never shell=True), canonicalize+confine paths, validate numeric args, treat subtitle cue text as data (escape libass); (c) API keys in OS secret store (DPAPI/Keychain/libsecret), excluded from the shareable project folder; (d) egress consent boundary = local-by-default + explicit per-provider first-use consent + persistent warning for any trains_on_data route.
- **R3 P1 launch bar:** concrete acceptance test (e.g. "from a 10-min talk, 3 of 5 proposed clips share-worthy without re-editing", + time budget on the 4050).
- **R4 Long-video stance + spike:** flagship is weakest where privacy/offline wedge is weakest (long arc-spanning → cloud wins; local 4B map-reduce only). Run a **local-4B short-selection quality spike on real long video BEFORE locking P1**, then pick: (a) scope P1 to short/medium + long=escalation-only, or (b) commit free-hosted Gemini-Flash escalation + no-train gate into P1.
- **R5 IA + outcome controls:** add Information Architecture; primary control = **3-tier posture (Private-Offline / Free-Better / Best-Cloud)**, per-task model grid → Advanced; collapse engines (reframe = smart default+override; captions = style picker w/ "premium animated" toggle; never expose "verthor vs claude-shorts" / "node vs no-node"); spec the ranked-candidate review UI (rank + rationale + approve/nudge/regenerate/discard non-destructive).
- **R6 Engine interfaces:** one `ReframeEngine` + one `CaptionEngine` interface; **P1 = verthor + libass ONLY**; claude-shorts + Remotion premium captions = ONE shared Node/Remotion subsystem in **P3** (don't integrate Remotion twice; engines not co-equal).
- **R7 Support matrix + download subsystem:** tiered HW/OS matrix (Tier-1 = RTX 4050/Win/CUDA validated; Mac-Metal/AMD/CPU = supported-vs-best-effort + honest perf); first-run model-download subsystem = resumable + checksummed (R2a) + mirror fallback + disk preflight + offline-bundle option + onboarding UX (start on hosted while local downloads).
- **R8 Resolve P1-gating decisions + guardrails:** lock (i) local default 4B vs 8B, (ii) hosted prompt→short posture (→ is the no-train gate P1?), (iii) top target languages, (iv) project file format copy-vs-reference. Add explicit P1 **non-goals** (timeline editor, TTS/dub, Remotion, claude-shorts, full transcode wrapper) + a de-scope cut-line. Honest SaaS seam: Provider abstraction + pipeline stages + map-reduce + capability model **port**; shell + IPC + single-tenant orchestration + local asset store **replaced** (add a thin asset-store interface, do NOT pre-build multi-tenancy). ffmpeg = "media ops the suite needs, presets-first," not a HandBrake clone. Chatterbox + 8B-resident = toggle-only, pending on-4050 bench.

## Next: fold R1–R8 + the 4 user decisions into DESIGN.md → re-gate (light) or proceed to plan.
