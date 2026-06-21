# AI Provider Hub — Design Doc

**Status:** v2 — Design Review Gate findings folded → RE-GATING
**Date:** 2026-06-16
**Owner:** Reframe Media Studio
**Supersedes:** the single-`CloudProvider` seam decision ("local-first now, seam for swap later", grill 2026-06-16) — this is that *swap-later*, generalized.
**Gate-1 verdict:** CHANGES (5 reviewers). Its #1 "Phase-8 vision stack + advisor UI don't exist" finding was a FALSE NEGATIVE caused by a concurrent workflow checking out a pre-phase8 branch in the shared tree during review — those files DO exist on `feat/phase8-moment-finding` (commit `c98bc45`/`a9e93bc`: `vlm_backbone.py`, `smolvlm2.py`, `scorer.py`, `ResourceBar/TierCard/ModelCard`, `panels/ModelsSystemPanel.tsx`). See §11 for the dependency. The other findings are folded below in §11–§16.

---

## 1. Problem & motivation

Media Studio's AI components run **locally** today: an LLM (llama.cpp `qwen3-4b` at `:8088/v1`, used by `features/select.py` and `features/subtitles.py`) plus the heavy Phase-8 vision/audio stack (SmolVLM2, SigLIP-2, ViNet, TransNetV2, PANNs, DOVER). On modest hardware the user must **unload everything to free enough VRAM** to run the good models — a real adoption blocker.

Many **capable models are now available as FREE cloud APIs** (OpenRouter `:free`, Google Gemini free tier), several stronger and/or more multimodal than anything the user can host. The opportunity: **offload the two heaviest components (LLM + Tier-2 vision captioning) to free cloud**, keep only the small specialized numeric nets local (they're light and already tier-gated), and make the whole thing **resilient to free-tier rate limits via multi-key auto-rotation** so jobs never freeze.

## 2. Goals

- **G1 — Cloud offload (LLM + vision):** route the LLM path and the opt-in Tier-2 vision-captioning path to free cloud providers (OpenRouter, Gemini) behind the existing seams, with **local as the always-available fallback**.
- **G2 — Multi-key, multi-provider rotation:** load N API keys (across providers), auto-rotate on `429`/quota-exhaustion so a long job never stalls; even rotate among keys for the *same* model if the user insists on it.
- **G3 — Live usage visibility:** query each key's remaining usage vs. max and show it numerically (requests or tokens, model-dependent) **and** as a colored bar (green=full → yellow → red); multiple loaded APIs **stack** the bars (×N eligible keys), with a vivid "superpowered" color when aggregate headroom is large.
- **G4 — Capability-aware model catalog:** a curated, filterable/orderable catalog labeling each model by capability + quality + cost/limit, e.g. *"🟢 BEST for VISION & multimodal — 10 req/day"*, *"🟡 general, not good not great"*.
- **G5 — Config recommender:** help the user **pair models + functionalities + local** into good end-to-end configurations from *all* available sources (e.g. "Nemotron Ultra → select, Gemini Flash → vision, local Whisper → ASR").
- **G6 — Documentation:** in-app tooltips + a tutorial, AND a standalone docs page (model-pairing guide + provider setup + privacy).
- **G7 — Quality bar:** 100% line+branch sidecar coverage (standing policy); renderer UI tested to 100%; no secrets logged.

## 3. Non-goals

- Replacing the *small specialized numeric* models (ViNet saliency, TransNetV2 scene-cut, PANNs audio, DOVER quality, NeuFlow) — no free chat-API equivalents; they stay local or off via the existing tier selector.
- A hosted backend/keystore service — keys stay **local** on the user's machine (lean, offline-first preserved as an option).
- Paid-tier billing management. We surface the **≥$10 balance → 1000 req/day** OpenRouter threshold as advice only.
- Auto-entering keys — the **user** supplies every key; the app never fabricates or transmits them anywhere but the owning provider.

## 4. Research findings (cited)

- **OpenRouter free tier** (`openrouter.ai/docs/api/reference/limits`): `:free` models → **20 req/min**; daily cap **~50/day under $10 balance, ~1000/day at ≥$10 balance** (balance is a threshold, not spent). Usage/limit query: **`GET /api/v1/key`** (returns usage, limit, rate-limit) + `GET /api/v1/credits`.
- **OpenRouter free models** (`openrouter.ai/models?q=free`) — incl. several stronger than gpt-oss-120b and multimodal:
  - Text/reasoning: Nemotron 3 Ultra 550B (1M ctx), Nemotron 3 Super 120B (1M ctx), Qwen3 Coder 480B (1.05M), Qwen3 Next 80B (262K), gpt-oss-120b (131K), Llama 3.3 70B (131K), Hermes 3 405B.
  - Multimodal/vision: Gemma 4 26B/31B (text+image+video), Nemotron Nano Omni (image+video+audio), Nemotron 12B VL, Nemotron Embed VL 1B (multimodal embeddings).
  - `openrouter/free` — a built-in router that auto-selects an available free model by needed features (tool/vision/structured).
- **Gemini free tier** (`ai.google.dev`): natively multimodal (image/audio/video); per-project RPM/RPD shown in AI Studio (≈10–15 RPM, few-hundred→~1000 RPD by model). ⚠️ **Free-tier prompts may be used by Google to improve products** (paid tier excluded).
- All the above are **OpenAI-compatible** except Gemini's native API (Google also offers an OpenAI-compat endpoint, so a thin adapter or that endpoint suffices).

## 5. Architecture

### 5.1 Sidecar — rotating provider pool (`models/provider.py`)
- New `RotatingProvider(Provider)` wrapping an ordered **pool** of concrete providers, each = `{kind, base_url, model, keys[], capabilities, limits}`.
- **Selection:** pick the first provider/key that is (a) capable of the request kind and (b) not on cooldown.
- **Reactive failover (must-have):** on `429`/quota/5xx → mark that key on cooldown (until its reset window), advance to the next; raise `ProviderError` only when the pool (incl. local) is exhausted. Synchronous fall-through — **never blocks/sleeps the job**.
- **Proactive (optional):** before/under-the-hood poll `GET /api/v1/key` (OpenRouter) / provider usage to skip near-exhausted keys and to feed the live UI (G3). Cached + rate-limited so polling itself doesn't burn quota.
- **Local backstop:** `LocalServerProvider` always last in the pool, so offline still works.
- **Vision path:** extend the `vlm_backbone` / `smolvlm2` seam with a `CloudVisionBackend` that sends frames (base64) to a multimodal cloud model (Gemma 4 / Gemini / Nemotron VL) via the same pool/rotation, behind the Tier-2 toggle. Degrades to local SmolVLM2 or off per existing tiers.
- **Capability registry:** request kinds = `chat`, `vision`, (future `embedding`); each pool entry declares which it serves so rotation only considers eligible keys.

### 5.2 Model catalog + metadata (`models/catalog.py` + a refreshable data file)
- Curated catalog entry per known model: `id, provider, capabilities[], contextTokens, qualityTier (S/A/B/C), costClass (free/paid), limitHint (req/day or tokens), recommendedFor[] tags, notes`.
- Seeded from research; **refreshable** by querying the OpenRouter `/models` API (filter `:free`) so it stays current without a release.
- Drives both the recommender (G5) and the UI labels/filters (G4).

### 5.3 Settings / data model (extends `settings_store`)
- `providers: [{ id, kind, baseUrl, model, apiKeys: [string], enabled, capabilities }]` (multiple keys per entry).
- `routing: { order: [...providerIds], perFunction: { select, subtitles, vision } }` so a function can prefer a specific provider with pool fallback.
- Keys stored locally; **redacted in UI** (show last-4); **never logged**; optional future OS-keychain.

### 5.4 RPC surface
- `providers.list` / `providers.upsert` / `providers.remove` / `providers.testKey` (validates + returns capabilities).
- `providers.usage` → live usage per loaded key (numeric + percent) for the UI bars (G3), cached.
- `providers.recommend` → given loaded sources + desired functions, returns suggested pairings (G5).

### 5.5 Renderer — Provider Hub panel (in System-Advisor)
- **Catalog view (G4):** cards/rows with colored capability+limit badges, e.g. `🟢 BEST: Vision/Multimodal · 10 req/day`, `🟡 General · mid`, `🟣 S-tier reasoning · 1M ctx`. Filter by capability; order by quality / limit / context.
- **Loaded providers + live usage (G3):** per key, numeric "used/max (req or tokens)" + a colored bar (green→yellow→red by remaining %). Multiple keys for a model **stack** into a segmented/× N bar; large aggregate headroom renders a vivid **"superpowered"** (purple/animated) state.
- **Config builder/recommender (G5):** "Build a configuration" — pick quality vs. privacy vs. offline; it proposes a per-function mapping across local+cloud and shows the combined limits/quality.
- Reuses the Phase-8 advisor components (ResourceBar, TierCard, ModelCard) + new ones (UsageBar, ProviderKeyRow, CatalogFilter).

## 6. UX detail — the usage bars (G3)
- Single key: horizontal bar, fill = remaining/max; color ramp green(≥60%)→yellow(30–60%)→red(<30%); numeric label `820 / 1000 req today` or `1.2M / 4M tok`.
- N keys same model: stacked segments (one per key) → effectively `green ×N`; tooltip lists each key's remaining.
- Aggregate headroom high (e.g. ≥3 healthy keys / large total): switch to a vivid **purple "superpowered"** treatment to signal abundance.
- Exhausted/cooldown key: greyed segment + reset-time tooltip; rotation indicator shows the currently-active key.

## 7. Privacy & security
- **Keys:** user-supplied only; local storage; redacted UI; never logged; sent only to their owning provider. (No keystore now; OS-keychain is a future option.)
- **Data egress disclosure (prominent):** using a cloud provider sends transcripts (and, for vision, frames) to that provider. **Gemini free tier and many OpenRouter free models may log/train on inputs** — surfaced as a clear per-provider badge + first-use consent. Local stays the private/offline default.
- **No CAPTCHA/ToS bypass; respect each provider's ToS + rate limits** (rotation is legitimate multi-key use, not evasion).
- **Coverage/secret-scan:** new sidecar code 100% line+branch; gitleaks clean; no keys in fixtures/logs.

## 8. Documentation (G6)
- **In-app:** tooltips on every catalog badge + a short tutorial ("Pick a model", "Add your keys", "Read the usage bars", "Build a config").
- **Separate docs:** `docs/providers/MODEL-GUIDE.md` (per-model best-for + cost/limit + quality), `docs/providers/SETUP.md` (get an OpenRouter/Gemini key, balance threshold, privacy).

## 9. Risks & open questions
- **R1 Gemini native API** differs from OpenAI-compat → thin adapter or use Google's OpenAI-compat endpoint (decide in plan).
- **R2 Usage polling cost** — `GET /api/v1/key` is cheap but per-key; cache + throttle so the UI doesn't burn the rate limit.
- **R3 Vision frame egress** — sending frames is heavier + more privacy-sensitive than text; keep Tier-2 cloud strictly opt-in with explicit consent.
- **R4 Catalog drift** — free models/limits change; the refresh-from-`/models` keeps labels honest; quality tiers are curated (subjective) — mark as guidance.
- **R5 Rotation correctness** — must not double-count a request against a key, must honor per-window cooldowns, must be deterministic/testable (inject a fake clock + fake usage).
- **Q1** Persist usage estimates locally between runs (to avoid re-polling on every launch)?
- **Q2** Should `providers.recommend` consider measured device specs (from the System-Advisor) to balance local vs. cloud automatically?

## 10. Success criteria
- A user with weak hardware can run select + subtitles + Tier-2 vision **entirely on free cloud**, load ≥3 keys, watch live usage bars, and have a long job auto-rotate through keys without freezing — with local fallback if all cloud is exhausted, and clear privacy disclosure throughout. 100% sidecar coverage; renderer UI tested; docs shipped.
- Per-goal measurable acceptance criteria: see **§12**.

---

# v2 — Gate-1 findings folded (2026-06-16)

## 11. Dependency & sequencing (corrects the gate's false "missing files" finding)
- The Phase-8 vision/audio seams (`features/vlm_backbone.py`, `smolvlm2.py`, `scorer.py`) and the advisor UI (`components/ResourceBar|TierCard|ModelCard`, `panels/ModelsSystemPanel.tsx`) **exist on `feat/phase8-moment-finding`** — verified on origin. They are NOT yet on `main`.
- **Therefore Provider Hub builds on the phase-8 branch (or after it merges to main).** This is a hard ordering dependency, stated explicitly so no reviewer re-flags it: Provider Hub WUs that touch the vision seam (G1-vision) start only once phase-8 is the base.
- The LLM-path WUs (`models/provider.py`, `select.py`, `subtitles.py`, `settings_store.py`) depend on nothing from phase-8 and can start immediately.

## 12. MVP vs later — explicit cut line (with vision IN scope, just sequenced)
Vision offload stays in scope (user directive); it is **WU-3**, not punted.

| WU | Scope | Phase |
|---|---|---|
| **WU-1 — Rotation core (MVP)** | `RotatingProvider` pool over `models/provider.py`: ordered providers, multi-key, reactive 429/5xx failover with per-window cooldown, local backstop, deterministic (injected clock + fake usage). Wire `select`/`subtitles` to it. | **MVP** |
| **WU-2 — Catalog + usage + keys UI (MVP)** | Static curated `catalog.py`; `providers.{list,upsert,remove,testKey,usage}` RPC; Provider Hub panel: capability/cost badges, per-key live usage bar (single-unit), add/redact keys, consent gate. | **MVP** |
| **WU-3 — Vision offload** | `CloudVisionBackend` behind the `vlm_backbone`/`smolvlm2` seam (Gemma 4 / Gemini / Nemotron VL); Tier-2 opt-in + frame-egress consent. *Depends on §11.* | Phase-2 |
| **WU-4 — Recommender + catalog auto-refresh** | `providers.recommend` (rules table; device-aware per §15-Q2); refresh catalog from OpenRouter `/models`. | Phase-2 |
| **WU-5 — Stacked + "superpowered" usage UX** | N-key stacking (same-unit only, §13), the "superpowered" state (§14), animated polish. | Phase-2 |

MVP = WU-1 + WU-2 (delivers ~80% of value: cloud LLM with rotation + a usable hub + per-key usage). Each WU is independently shippable, 100% sidecar coverage + renderer tested.

## 13. Usage-bar unit rule (finding #4/#6)
- Keys are **requests-limited** (OpenRouter `:free` → req/min + req/day) OR **tokens-limited** (Gemini → TPM/RPD). **These units MUST NOT be summed into one bar.**
- A stacked bar aggregates **only keys of the same unit** for the same model/provider group. Mixed-unit pools render as **separate grouped bars** (a "requests" group and a "tokens" group), each labeled with its unit.
- Each segment shows `used/max` in its native unit (`820/1000 req today` or `1.2M/4M tok`). Aggregation across units is forbidden in code (a typed `UsageUnit` enum gates it; a test asserts mixed-unit pools never sum).

## 14. The "superpowered" state — defined (finding #5)
- It is a **precise, explained** state, not decoration: triggered when **≥3 keys of the same unit are simultaneously "healthy"** (each >60% remaining) for a given function — meaning long jobs are very unlikely to stall.
- Visual: the same-unit stacked bar switches to a vivid purple treatment **with an always-present text label + tooltip**: *"3+ keys healthy — long jobs won't stall (auto-rotates across them)."*
- Color is never the only signal (accessibility, §16). If the trigger is borderline/unclear, it is NOT shown (better absent than confusing). This state is droppable to Phase-2 (WU-5) without affecting MVP.

## 15. Resolved open questions (finding #7)
- **Q1 (persist usage between runs): YES.** Cache last-known per-key usage locally (timestamped) so the UI shows immediately on launch without re-polling; mark data **stale** when older than a threshold (default 10 min) — stale bars render desaturated with a "last checked Xm ago" tooltip, and a refresh re-polls `GET /api/v1/key`.
- **Q2 (recommender device-aware): YES, in WU-4.** `providers.recommend` consumes the System-Advisor device probe (RAM/VRAM) to balance local vs. cloud: weak hardware → prefer cloud for LLM+vision, keep only light numeric nets local; strong hardware → offer local-first with cloud as overflow. Until WU-4, the catalog + manual selection cover it.

## 16. Measurable per-goal acceptance criteria (finding #3)
- **G1 (offload):** with a valid cloud key + `useCloud`, `select` and `subtitles` issue zero local-LLM calls (asserted via injected transport spy); with no key, they fall back to local (existing behavior, unchanged tests stay green). WU-3: Tier-2 vision routes frames to the cloud backend when enabled, local SmolVLM2 when not.
- **G2 (rotation):** a job issuing K requests across M keys each capped at C completes iff K ≤ Σ(remaining); on a `429` the pool advances to the next eligible key and emits one `rotation` event per failover; the throttled key is skipped until its window resets (injected fake clock); the call **never sleeps/blocks** (asserted: no `time.sleep` on the hot path). When the whole pool (incl. local) is exhausted → a single `ProviderError`, not a hang.
- **G3 (usage bars):** bar color matches remaining-% thresholds exactly (green ≥60, yellow 30–60, red <30); req-limited and token-limited keys are never summed (§13); data older than the staleness threshold is visibly flagged (§15-Q1).
- **G4 (catalog):** every quality label renders as **dated, curated guidance** ("our pick · as of <date>"), never as an objective benchmark (finding #5); filter-by-capability and order-by (quality/limit/context) work over the catalog.
- **G5 (recommender):** a "good" recommendation = a per-function mapping where (a) every chosen provider is *capable* of that function, (b) the combined limits cover a stated target job size, and (c) it respects the user's privacy/offline preference; asserted on fixtures (weak-device → cloud-heavy mapping; offline-pref → local-only mapping; capability mismatch → never proposed).
- **G6 (docs):** in-app tooltips on every badge + a 4-step tutorial; standalone `docs/providers/MODEL-GUIDE.md` + `SETUP.md` shipped.
- **Privacy/consent (finding #7-consent):** consent is **per-provider AND per-data-type** — separate explicit opt-in for sending *text* (transcripts) vs *frames* (vision), each with the provider's train-on-input disclosure; frames (more sensitive, R3) require their own confirmation distinct from text; recorded per-provider, revocable in settings.
- **Quality:** 100% line+branch sidecar coverage; renderer UI tested; gitleaks clean (no keys in logs/fixtures/errors).
