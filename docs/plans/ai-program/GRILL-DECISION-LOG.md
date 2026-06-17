# Reframe AI Program — Extensive Grill Decision Log

**Date:** 2026-06-16 · **Mode:** expansion + better-ideas + red-team + scope-change
**Inputs:** Provider Hub DESIGN.md v2 (Design Gate v2 = CHANGES), Director FEATURE.md, 6-lens divergence brainstorm (`wf_4f88631b`), live code seams.
**Status:** ✅ GRILL COMPLETE (all ~29 decisions answered 2026-06-16/17). This log is the authoritative decision spine → feeds the PLAN stage. **A grill is not a build.** See "CONVERGED PROGRAM" at the bottom.

---

## Decision queue (≈22) — answered inline as we go

### Foundation / Ambition
- **F1** — Primary user + the core bet: local-first wedge vs feature-parity? — *rec: (a) local-first wedge* — **ANSWER: ✅ (a) LOCAL-FIRST WEDGE** (privacy/high-volume creator; local by default + uncapped + transcript-native + BYO-free-key; cloud opt-in accelerator only; gimmicks off critical path).
- **F2** — Headline + what ships first: Hub vs Director? — *rec: (a) Hub-first, scoped Director second* — **ANSWER: _pending_**

### ⛔ Gate / Blocker (user-flagged 2026-06-16)
- **G1 (BLOCKER)** — **Preview pipeline is broken** ("preview still doesn't work at all" → subtitles/visual output cannot be tested). MUST be fixed + verified **before `/metaswarm:start` of any preview-dependent AI feature** (subtitles, captions, Director, reframe — anything whose output is visually validated in preview). Decision when reached: scope the preview fix as the FIRST build WU and make "preview renders + a subtitle shows on it" a tested acceptance gate before the AI program proceeds. — **ANSWER: gated (fix-first); scope/priority _pending_ at Sequencing.**

### UI/UX & QoL & Persistence (user-requested category)
- **UX1** — Output save model: where do generated artifacts (shorts/exports/captions/thumbnails) save by default — fixed data-root `output/`, per-export chooser, or project-relative? naming scheme? — *rec: project-relative under the data root + a per-export "save as / reveal in folder", sensible auto-names* — **_pending_**
- **UX2** — Project resume / pick-up: how does a user reopen an in-progress project + resume running/failed jobs after closing the app? (project-manifest autosave, recent-projects list, job-resume) — *rec: autosave project manifest + recent-projects + resumable jobs (the jobs layer already persists)* — **_pending_**
- **UX3** — Save/export options: format/quality/location/naming choices + reusable export presets (ties to brand kit + platform presets). — *rec: export presets object, remembered per-project* — **_pending_**
- **UX4** — Thumbnailing: auto-generate thumbnails for projects/library/clips/shorts; where surfaced; AI title-frame pick? — *rec: auto poster-frame now (cheap), AI best-frame pick as a phase-2 add* — **_pending_**
- **UX5** — Availability indicators: surface what's downloaded vs needs-download vs cloud-available across models/features (System-Advisor + Provider Hub) consistently. — *rec: one shared "availability" badge vocabulary reused by advisor + hub* — **_pending_**
- **UX6** — General QoL: undo/redo, autosave, progress + cancel on every long job, clear error surfacing, keyboard shortcuts, "reveal output". — *rec: make progress/cancel + reveal-output universal via the AI-Job envelope (A2)* — **_pending_**

### Scope: Provider Hub
- **PH1** — Usage UI: full superpowered bars+poller vs one-number+optimistic? — *rec: (b) one number, drop superpowered* — **_pending_**
- **PH2** — Catalog source. — **ANSWER: ✅ STATIC CURATED, MULTI-PROVIDER, PER-TASK RANKING.** Catalog is hand-curated AND spans many providers; it ranks each model by **fitness for Reframe's specific tasks** (moment-finding, caption/title writing, vision/OCR, translation, edit-planning). User **brings only their API key** (makes their own account at the provider); Reframe surfaces which models they can pick + recommends. Not a live /models fetch.
- **PH3** — Config intelligence. — **ANSWER: ✅ PRESETS + PER-FUNCTION CUSTOMIZE + SUGGESTIONS.** Smart presets ('Privacy/offline-all-local', 'Best free cloud', 'Balanced') + a per-function override view (pick the model per task) with catalog per-task ranking suggesting each slot. Full device-aware auto-recommender = phase-2.
- **PH4** — Vision offload. — **ANSWER: ✅ BUILD NOW (speculatively, in the Hub MVP)** — CloudVisionBackend + dual text/frame consent, built proactively (NOT deferred to Director). DEPENDENCY: still requires the phase-8 merge first (vision seams live on `feat/phase8`). Pool vision-aware from day one.
- **PH5** *(new, spawned by PH2)* — Local-LLM backend. — **ANSWER: ✅ BOTH** — keep zero-setup embedded llama.cpp default ("just works", no install) AND auto-detect Ollama + LM Studio as additional local pool providers (OpenAI-compatible endpoints slot into the same rotation pool).
- **PH6** *(new, spawned by PH2)* — Multi-provider survey + per-task ranking: which free/cheap API providers to feature + how "fitness for task" is expressed. — **ANSWER: research running (`provider-survey`) → fold result into the catalog + present for confirmation.** User brings only the API key; catalog tags each model with per-Reframe-task tiers.

### Scope: Director
- **D1** — Director v1 shape. — **ANSWER: ✅ CONVERSATIONAL AGENT + PIPELINE TOOLBOX** (canonical target = the real Claude+Descript "Battle Cats list" chat the user pasted). Director = an agent that understands a natural request, reasons + picks/sequences the right multi-stage pipeline, produces MULTIPLE deliverables, and is HONEST about limits. Transcript-as-timeline is ONE tool, not the whole thing.
  - **Canonical example (BC list video):** input = jerky manual screen-scroll, no audio. Output 1 = SMOOTH video — NOT a speed-ramp; real fix = **panorama-stitch all frames → regenerate constant-speed scroll** (agent must know speed-ramping a manual scroll won't work). Output 2 = **extract the list** as structured text AND a long high-res "poster" image (OCR/vision → text + composed image). Title card + music optional.
  - **Spawned tool-pipelines (each typed + testable, agent invokes them):** T-stitch (frame panorama-stitch for scrolling content); T-scroll (constant-speed scroll regen from a panorama); T-ocr-list (OCR/vision list-extract → structured text + poster image); T-transcript-edit (transcript-as-timeline cut/reorder); T-qa (Q&A-segment stitch); T-silence (filler/silence trim). Agent = orchestrator; honesty-about-limits is first-class.
  - Implication: MORE than a templated recipe — user explicitly wants the agentic experience. A1 (typed plan/tool contract) is essential; the "edit plan" is really an agent tool-call plan. D2/D4 reframed.
- **D2** — Flagship proof: scroll-smoothing vs Q&A-stitch? — *rec: (b) Q&A (real cost-stress)* — **_pending_**
- **D3** — Edit-plan parsing: clamp vs hard-validate-and-reject? — *rec: (b) hard validate* — **_pending_**
- **D4** — Free-model plan quality: assume vs eval harness at gate? — *rec: (b) eval harness* — **_pending_**

### New directions to add / drop
- **N1** — Filler-word/silence one-click pre-pass? — *rec: ADD (S, local)* — **_pending_**
- **N2** — Transcript-as-timeline editing as keystone? — *rec: ADD (may BE Director v1)* — **_pending_**
- **N3** — Speaker diarization on transcribe? — *rec: ADD (M)* — **_pending_**
- **N4** — Engagement gimmicks (b-roll/gaze/avatars/music-gen)? — *rec: DROP gaze+avatars; emoji/text overlays only; generated b-roll+music = phase-2 non-goal* — **_pending_**
- **N5** — Quota-aware batch queue + repurpose graph? — *rec: ADD, gated behind pool+cache+budget* — **_pending_**

### Architecture / force-multipliers
- **A1** — Extract EditPlan DSL + invert contract before Director writes edits? — *rec: YES* — **_pending_**
- **A2** — AI-Job envelope (cost/preview/cancel/cache) as substrate now? — *rec: YES (with pool+cache)* — **_pending_**
- **A3** — AI-call cache before first cloud feature? — *rec: YES (best ROI)* — **_pending_**

### Sequencing / priority
- **S1** — Merge phase-8 → main before any Hub UI? — *rec: (a) merge first* — **_pending_**
- **S2** — Confirm critical path order. — *rec: phase8-merge → pool/rotation → Hub UI(simplified) → Director Q&A → demand-driven rest* — **_pending_**

### Safety / ethics / legal
- **SE1** — Frame egress + train-on-input default/gating? — *rec: frames local-only default; train-on-input a catalog axis; per-data-type consent* — **_pending_**
- **SE2** — Multi-key rotation ToS + verify per-key vs per-account cap? — *rec: verify empirically before ×N UI; no sock-puppet farming* — **_pending_**
- **SE3** — Voice-clone + Director deepfake consent/watermark? — *rec: consent gate now, content-credentials (C2PA/SynthID) ship later* — **_pending_**

### Process
- **P1** — Pre-flight cost/egress budget a WU-1 requirement? — *rec: YES* — **_pending_**
- **P2** — Graceful-degradation a tested invariant? — *rec: YES* — **_pending_**

---

## Top NEW directions (beyond stated ask)
1. Transcript-as-timeline editing — the genuine Descript moat; Reframe already owns word-level CTC alignment; may be the right framing of Director v1.
2. Quota-aware Batch Queue + Repurpose Graph — turns the Hub from infra into a felt superpower; must gate on budget+local-fallback.
3. AI-Job envelope + semantic footage index — the substrate that makes every later feature cheap.

## Top RISKS to force a decision on
1. **Rate-limit math** may invalidate the 50-Q&A flagship + "×N keys = ×N quota" may be a literal lie if cap is per-account. → verify empirically; budget+cache+batch a WU-1 requirement.
2. **DSL never extracted** → undo/diff/batch/templates re-implement edit representation incompatibly; reversibility unretrofittable. → decide op-set + invert contract before Director writes one edit.
3. **Engagement-gimmick drift** re-introduces per-minute cost + privacy loss (the things that ARE the product) + irreversible frame train-on-input leak. → keep gimmicks off critical path + out of "local by default".

---

## DECISIONS (filled as answered)
| # | Decision | Notes |
|---|----------|-------|
| F1 | **Local-first wedge** | privacy/high-volume creator; local default + uncapped + transcript-native + BYO-free-key; cloud opt-in only; gimmicks off critical path |
| G1 | **Preview-broken = hard gate** | fix preview (subtitle visible in preview) BEFORE /metaswarm:start of any preview-dependent AI build; first build WU |
| F2 | **Hub-first, scoped Director second** | rotation pool is Director's substrate + ships standalone value; Director Q&A proves the pool under load |
| PH1 | **Rich usage bars, data-driven not poll-driven** | keep visual bars + 'superpowered' (≥3 healthy keys) but drive from optimistic accounting + 429/rate-limit headers, not a poller; colorblind-safe + reduced-motion |
| PH2 | **Static multi-provider catalog, per-task fitness ranking; user brings key** | many free/cheap providers featured + ranked per Reframe task; user makes own account + brings API key; spawned PH5 (local via Ollama/LM Studio) + PH6 (provider survey) |
| PH3 | **Presets + per-function customize + suggestions** | 3 presets + per-task model override w/ catalog ranking; full device-aware auto = phase-2 |
| PH4 | **Build vision offload now (in Hub MVP)** | CloudVisionBackend + dual text/frame consent; DEP: needs phase-8 merge first |
| PH5 | **Both local backends** | embedded llama.cpp zero-setup default + auto-detect Ollama/LM Studio as pool providers |
| PH6 | **Catalog seeded (`CATALOG-SEED.md`)** | Groq GPT-OSS-120B + Cerebras Qwen3-235B = reasoning/JSON (no-train); Gemini Flash = vision (⚠️trains free); per-task tiers + privacy flags. **KEY: "N keys=N×quota" is FALSE — per-ACCOUNT; only MULTI-PROVIDER rotation stacks legitimately.** |
| D1 | **Director = conversational agent + pipeline toolbox** | canonical = the Claude+Descript BC-list chat; scroll=panorama-stitch+regen (not speed-ramp); list-extract=OCR→text+poster; multi-deliverable; honest-about-limits; tools T-stitch/T-scroll/T-ocr-list/T-transcript-edit/T-qa/T-silence |
| PH1↻ / SE2 | **Multi-provider rotation; same-provider keys = failover-only** | quota/×N bars stack across DISTINCT providers only; 2nd same-provider key = transient failover, never advertised as ×quota; docs steer to diversify providers; no account-farming |
| D3 | **Hard-validate plans (reject, never clamp)** | out-of-bounds ops rejected + re-prompted vs real clip duration + preconditions; trust gate |
| N1 | **ADD filler-word/silence one-click removal** | local, on existing audio_saliency+transcript; table-stakes |
| N3 | **ADD/finish speaker diarization** | diarize.py + pyannote_backend exist; surface it (Q&A is multi-speaker) |
| N4 | **Drop gaze+avatars; overlays only; gen-broll+music=phase-2 non-goal** | follows F1; no hosted-model gimmicks on critical path / in "local by default" |
| A1 | **Extract typed reversible EditPlan/tool contract FIRST** | op-set + invert/undo before Director writes an edit; unretrofittable otherwise |
| A3 | **AI-call cache (content-hash) before first cloud feature** | (content-hash,model,params) key; makes free tier usable + re-prompt cheap |
| P1 | **Pre-flight cost/egress budget = WU-1 requirement** | "~N requests across K providers, sends X to Y — proceed?"; gates over-promising |
| P2 | **Graceful-degradation = tested invariant** | saved config → next-provider → local + visible notice, asserted in tests |
| A2 | **Build AI-Job envelope substrate now** | {inputs,route,cost-est,cache-key,preview,result,cancel} over RPC; A1/A3/P1/P2/UX6 hang off it |
| N5 | **Batch queue + repurpose graph = post-MVP gated WU** | drop folder→shorts+captions+thumbnails each, paced vs live usage; ships after pool+cache+budget+local-fallback |
| SE3 | **Defer all deepfake consent/provenance** (user's explicit call) | no consent gate / no content-credentials for now; outputs stay local by default; revisit BEFORE any public distribution of the app |
| D2 | **BC-list (scroll-smooth + list-extract) = v1 proof; Q&A = cost-stress proof** | prove Director on the user's canonical example, then 50-Q&A as the rate-limit stress test |
| D4 | **Free-model plan-quality eval harness at the gate** | offline clips→known-good-plans→measure agreement; pick planner model on evidence |
| S1 | **Merge phase-8 → main BEFORE Hub UI** | branch Hub off clean main; avoids stale-tree/long-lived-branch problem |
| S2 | **Critical path locked** | preview-fix(G1) → merge phase8 → pool/rotation+envelope+cache+budget+degradation → Hub UI(+vision) → Director v1(BC-list+Q&A) → demand-driven rest |
| SE1 | **Frames local-only default; train-on-input a catalog axis; per-data-type consent** | frames never auto-egress; Gemini-free flagged AVOID-for-private; text vs frame consent separate; optional PII warn |
| UX1 | **Outputs project-relative + per-export save-as/reveal** | sensible auto-names; reveal-in-folder; no forced single dump |
| UX2 | **Resume = autosave manifest + recent-projects + resumable jobs** | reopen in-progress project + resume running/failed jobs |
| UX3 | **Export presets remembered per-project** | format/quality/location/naming presets tied to brand+platform |
| UX4 | **Auto poster-frame thumbnails now; AI best-frame phase-2** | cheap immediate thumbnails; smarter pick later |
| UX5 | **Shared availability badge vocabulary** | downloaded/needs-download/cloud-available reused by advisor + hub |
| UX6 | **Universal progress+cancel+reveal via AI-Job envelope** | every long job, free off A2 |
