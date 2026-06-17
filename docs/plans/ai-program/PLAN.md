# Reframe AI Provider Hub — Implementation Plan

**Status:** DRAFT for the Plan Review Gate (3 adversarial reviewers: Feasibility · Completeness · Scope/Alignment)
**Date:** 2026-06-17
**Scope authority (LOCKED — do not re-decide):** `CONVERGED-PROGRAM.md` + `GRILL-DECISION-LOG.md` (~29 decisions) + `provider-hub/DESIGN.md` v2 + `provider-hub/CATALOG-SEED.md`.
**Branch base:** `feat/phase8-moment-finding` (commit verified: `provider.py`, `translation.py`, `runner.py`, `smolvlm2.py`, `vlm_backbone.py`, `handlers.py`, `settings_store.py`, `assets/manifest.py`, `jobs.py`, `protocol.py`, and `app/renderer/src/{components/ResourceBar,TierCard,ModelCard}.tsx`, `panels/ModelsSystemPanel.tsx` all present).

---

## 1. Context & locked critical path

Reframe Media Studio runs its AI locally today: an LLM (llama.cpp `qwen3-4b` at `:8088/v1`) reached through **two** seams — `models/provider.py` `get_provider()` (the general chat seam used by `features/select.py` line 588 and `features/subtitles.py` via `make_provider_translator`) **and** `models/translation.py` `get_translator(...) -> TieredTranslator` (the subtitle-translation seam, tier3 = `CloudProvider`) — plus the Phase-8 vision stack (`features/smolvlm2.py` SmolVLM2 re-rank seam, `features/vlm_backbone.py` SigLIP-2). On modest hardware the user must unload models to free VRAM — the adoption blocker the Hub solves by offloading the LLM + Tier-2 vision to **free multi-provider cloud** with rotation, while keeping local as the always-available backstop.

**THE BET (F1):** local-first wedge — local by default, uncapped, transcript-native, bring-your-own-free-key. Cloud is opt-in acceleration, never required.

**Locked critical path (S2):**

0. **G1 — FIX PREVIEW — ✅ DONE** (commit `86d0ec4`; a subtitle visibly renders in preview). This was the hard gate; it is cleared.
1. **WU-merge:** merge `feat/phase8-moment-finding` → `main` (S1). Branch the Hub off clean `main`.
2. **Substrate:** rotation pool over **BOTH** LLM seams + local backstop + Ollama/LM Studio detect (WU-pool) · AI-Job envelope (WU-envelope) · AI-call cache (WU-cache) · pre-flight budget + tested graceful-degradation (WU-budget).
3. **Hub UI:** static multi-provider catalog + per-task tiers + privacy axis (WU-catalog) · keys mgmt + per-data-type consent (WU-keys) · data-driven dual-unit usage bars + superpowered + a11y (WU-usage-ui) · presets + per-function customize (WU-presets) · vision offload `CloudVisionBackend` on the smolvlm2 seam (WU-vision).
4. **Director v1 + demand-driven follow-ons:** LATER WUs (§3), outline only.

**Standing gates (every WU) — the REAL repo gate (`.github/workflows/quality.yml` gate:3, verified on `feat/phase8-moment-finding`):**
- **Sidecar:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` (100% line + branch). Heavy/native seams are excluded with **inline `# pragma: no cover`** on the real-impl seam (the proven pattern — e.g. `smolvlm2.py:210` `_default_backend_factory`, `provider.py:98` `_urllib_post_json`).
- **Renderer:** `cd app && npx vitest run --coverage` (vitest, **NOT jest** — there is no jest config). `app/vitest.config.ts` enforces `thresholds: {lines, branches, functions, statements} = 100`. Genuinely-untestable runtime-only lines use inline **`/* v8 ignore … -- <reason> */`**, never blanket exclude.
- **NOTE:** `.coverage-thresholds.json` does **NOT** exist in this repo. The single source of truth for coverage is `.github/workflows/quality.yml` gate:3 (the two commands above) — cite IT, run THEM.
- gitleaks clean (no keys in logs/fixtures/errors). TDD mandatory (RED→GREEN→refactor).

---

## 2. MVP Work Units

Ordering / dependency graph:

```
WU-merge ──► WU-pool ──► WU-envelope ──► WU-cache ──► WU-budget
                │                                          │
                └────────────► WU-catalog ────────────────┤
                                   │                        ├──► WU-usage-ui
                               WU-keys ──────────────────────┤
                                   │                        ├──► WU-presets
                               WU-pool + phase8 base ─────────► WU-vision
```

WU-pool, WU-catalog, WU-keys are independently startable once WU-merge lands. WU-envelope/cache/budget form the substrate spine. WU-usage-ui depends on WU-pool (usage accounting) + WU-keys (loaded providers) + WU-catalog (units/labels). WU-vision depends on WU-pool + the phase-8 vision base (already in WU-merge).

---

### WU-merge — merge phase-8 → main

- **id:** WU-merge
- **goal:** land `feat/phase8-moment-finding` on `main` so the Hub branches off a clean tree that already contains the vision seams (`smolvlm2.py`, `vlm_backbone.py`) and the advisor UI; avoids a stale long-lived branch (S1).
- **files/seams touched:** no code change — a merge/PR. Touches git history only. Verifies presence of: `sidecar/media_studio/{models/provider.py,models/translation.py,models/runner.py,features/smolvlm2.py,features/vlm_backbone.py,handlers.py,settings_store.py,assets/manifest.py,jobs.py,protocol.py}` and `app/renderer/src/{components/ResourceBar.tsx,TierCard.tsx,ModelCard.tsx},panels/ModelsSystemPanel.tsx}`.
- **public surface added:** none.
- **test strategy:** the existing phase-8 suite must pass on `main` post-merge. Run the REAL gate:3 commands: renderer = `cd app && npx vitest run --coverage` (vitest, NOT jest); sidecar = `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`. No new fakes.
- **acceptance (falsifiable):** (a) `git branch --contains` shows phase-8 tip on `main`; (b) `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0; (c) `npx vitest run --coverage` exits 0 (vitest 100% thresholds met); (d) gitleaks clean on the merge; (e) G1 preview-fix `86d0ec4` is present on `main` (subtitle renders in preview — re-confirm with the existing preview test).
- **dependencies:** none (first build WU; G1 already done).

---

### WU-pool — RotatingProvider over BOTH seams + local backstop + Ollama/LM Studio detect

- **id:** WU-pool
- **goal:** add a multi-PROVIDER rotation pool that fronts the LLM behind a `Provider`-shaped object and is wired into **BOTH** LLM seams (gate-2 CTO finding): the general `get_provider` path AND the `TieredTranslator` tier3/hosted path. Same-provider extra keys = failover only (never advertised ×quota). Local backstop always last. Auto-detect Ollama + LM Studio as additional OpenAI-compatible pool providers (PH5).
- **files/seams touched:**
  - `sidecar/media_studio/models/provider.py` — add `RotatingProvider(Provider)` wrapping an ordered pool of concrete `_OpenAICompatProvider` entries (each `{kind, base_url, model, keys[], capabilities, limits, unit}`); extend `get_provider(settings, *, transport=None)` (the factory at `provider.py:302`; `Transport` already injectable at `provider.py:205`) so that when `settings.providers` is configured it returns a `RotatingProvider` (else the existing Local/Cloud fall-through — unchanged for back-compat). `LocalServerProvider` remains the pool's last entry (backstop).
  - **CLOCK SEAM (P1, mandatory):** `RotatingProvider.__init__` takes an injectable `now: Callable[[], float]` constructor arg (default a module-level default that the tests replace). The module **MUST NOT import `time` or `asyncio.sleep`** — cooldown windows are computed purely from `now()` deltas, and the rotation hot path NEVER sleeps (a throttled key is *skipped*, not waited on). This keeps cooldown logic deterministic and 100%-coverable with a fake clock (no real wall-clock, no `# pragma: no cover` needed on cooldown branches).
  - `sidecar/media_studio/models/translation.py` — the tier3 (`TIER_HOSTED`) materialization in `TieredTranslator._hosted_provider()` (line 454) must use the SAME pool: change the default `hosted_provider_factory` to build the `RotatingProvider` from `settings.providers` (falling back to today's `CloudProvider` when no pool). Tier1/tier2 (local GGUF) stay as-is — the local backstop already lives there.
  - `sidecar/media_studio/models/runner.py` — no change required (Ollama/LM Studio are external OpenAI-compatible servers, not llama.cpp the runner spawns); a new pure helper module (below) holds detection.
  - **new:** `sidecar/media_studio/models/local_detect.py` — pure detection of Ollama (`http://127.0.0.1:11434/v1`) and LM Studio (`http://127.0.0.1:1234/v1`) via the injectable `Transport` (a `GET /models` probe); returns pool entries. No socket under test (transport injected).
  - `sidecar/media_studio/features/select.py` (caller at line 588) + `features/subtitles.py` (`make_provider_translator`, line 269) — NO source change needed (they already consume a duck-typed `Provider.chat`); they get rotation transparently via the factory. The wiring change is in `handlers.py` `self._provider` / `_get_translator` construction.
  - `sidecar/media_studio/handlers.py` — `MediaStudioHandlers.__init__` `self._provider` default (line 107) and `_get_translator` (line 1054/1065) resolve through the pool-aware `get_provider` / `get_translator`. New RPC handlers added in this WU (`ai.planJob`, `providers.*`, `providers.usage`, etc., as those WUs land) are **wired in `handlers.register_all` (`handlers.py:1269`)** — the single composition root that calls `protocol.register`; do NOT register methods anywhere else.
- **public surface added:** `RotatingProvider` class (ctor takes `pool`, `now`); `models.local_detect.detect_local_servers(settings, *, transport) -> list[PoolEntry]`; a `RotationEvent`/`rotation` callback hook on the pool (one event per failover, for the envelope/UI). Settings keys: `providers: [{id, kind, baseUrl, model, apiKeys[], enabled, capabilities[], unit}]`, `routing: {order[], perFunction:{select,subtitles,vision,translation}}`.
- **test strategy (sidecar gate: `pytest --cov=media_studio --cov-branch --cov-fail-under=100`):** inject a **fake `Transport`** (the `provider.py:205` seam) that returns canned responses + raises `ProviderError("LLM HTTP 429: ...")` for chosen keys; inject a **fake clock** (the `now()` ctor arg) for cooldown windows. Tests: rotation advances on 429 to the next eligible key; throttled key skipped until window resets (advance the fake clock, assert re-eligible); pool-exhausted (incl. local backstop) raises a single `ProviderError`, never hangs; `detect_local_servers` returns Ollama/LM Studio entries from a fake `GET /models` and empty list on connection error (no raise). **No-sleep enforcement:** a test asserts `time` / `asyncio.sleep` are not importable references in the module (e.g. assert `not hasattr(provider_module, "time")` / static import-scan), so the cooldown is purely clock-delta math — every cooldown branch is hit with the fake clock at 100% (no `# pragma: no cover` on cooldown). Cover BOTH seams: one test drives `get_provider(...).chat(...)` rotation; a SECOND drives `TieredTranslator` tier3 (`translation.py:454` `_hosted_provider`, via the `hosted_provider_factory` injected at `translation.py:271`) through the same pool (asserts the translator's hosted tier rotated).
- **acceptance (falsifiable):**
  - A job issuing K requests across M distinct-provider keys each capped at C completes iff K ≤ Σ(remaining); on a 429 the pool advances and emits exactly one `rotation` event per failover (gate-2: BOTH seams — assert against `get_provider` AND `TieredTranslator`).
  - Same-provider second key is used ONLY as failover and the pool never reports it as additional quota (a typed `unit`/provider-group check).
  - Local backstop is reached when all cloud keys are exhausted (offline still works).
  - Ollama + LM Studio detected from a fake transport and slotted as pool providers; detection failure degrades silently to no extra providers.
  - No `time.sleep`/`await sleep` anywhere in the module (asserted: `time`/`asyncio` are not imported); cooldown is clock-delta math via the injected `now()`.
  - New RPC handlers (`ai.planJob`, `providers.*`, `providers.usage`) are registered exclusively through `handlers.register_all` (`handlers.py:1269`).
  - gitleaks clean; the key is header-only (never in a log line — assert via a log-capture spy).
- **dependencies:** WU-merge.

---

### WU-envelope — AI-Job envelope (A2)

- **id:** WU-envelope
- **goal:** a typed substrate `{inputs, route, costEst, cacheKey, preview, result, cancel}` over RPC that every AI call rides, so cost-preview, cache, budget, graceful-degradation and universal progress/cancel/reveal (UX6) hang off ONE object. Built on the existing `jobs.py` `Job`/`JobContext`/`JobRegistry` (do not introduce a second job bus).
- **files/seams touched:**
  - **new:** `sidecar/media_studio/models/ai_job.py` — the `AiJob` envelope dataclass + `plan_ai_job(...)` (pure: builds route/costEst/cacheKey from settings + the catalog + the request) + `run_ai_job(envelope, *, jobs, provider_factory, cache, budget)` that executes on a `ctx.jobs` job, emits `job.progress`/`job.done` via the existing `JobContext`.
  - `sidecar/media_studio/handlers.py` — the AI-bearing handlers (`phase8_select` line 734, `subtitles_translate` line 297, and the future Director handlers) route through `run_ai_job`; existing `ctx.jobs.start(job_body)` shape preserved.
  - `app/renderer/src/components/useJob.ts` — extend (or a sibling `useAiJob.ts`) to surface `costEst`/`route`/`preview` from the envelope's `job.progress` payload; reuses the existing `onJobDone` bridge + `JobErrorPayload`.
- **public surface added:** `AiJob` dataclass; `plan_ai_job`, `run_ai_job`; new RPC method `ai.planJob` (pre-flight preview, returns `{route, costEst, cacheHit, willEgress}` WITHOUT executing) registered via `protocol.register`. Renderer: `useAiJob` hook (cost/route/cancel/reveal).
- **test strategy:** `plan_ai_job` is pure → unit-test route/costEst/cacheKey assembly with fixtures. `run_ai_job` driven with a fake `JobRegistry` + fake provider factory + fake cache/budget; assert progress/done emitted, cancel honored (`ctx.cancelled`), and a single `job.done` error payload on exhaustion. Renderer hook tested with an injected rpc client + fake job-done bridge (mirrors `useJob.test.tsx`).
- **acceptance (falsifiable):** (a) `ai.planJob` returns route+costEst+cacheHit+willEgress and performs ZERO provider calls (assert transport spy untouched); (b) every AI job emits progress + a terminal `job.done` (result OR `{error:{message,type}}`); (c) cancel mid-job returns the cancelled status, no provider call after cancel (uses the existing `JobContext.cancelled`/`raise_if_cancelled` from `jobs.py`); (d) reveal-output path present in the done payload (UX6); (e) sidecar `pytest --cov=media_studio --cov-branch --cov-fail-under=100` exits 0 and the renderer hook is tested at vitest 100% (`npx vitest run --coverage`).
- **dependencies:** WU-pool.

---

### WU-cache — AI-call cache (A3)

- **id:** WU-cache
- **goal:** content-hash cache keyed `(content-hash, model, params)` so repeat/re-prompt AI calls are free — makes the free tier usable and the budget honest (best ROI). Cache checked BEFORE any provider call.
- **files/seams touched:**
  - **new:** `sidecar/media_studio/models/ai_cache.py` — `AiCache` (a small on-disk JSON/SQLite store under the data dir) with `key(messages, model, params) -> str` (sha256 of canonicalized request), `get(key)`, `put(key, result)`. Pure key derivation; the store path is injectable (tests use a tmp dir).
  - `sidecar/media_studio/models/ai_job.py` — `run_ai_job` consults `AiCache` first; on hit, skips the provider and emits a `cacheHit` route flag.
  - `sidecar/media_studio/models/provider.py` — optional: a thin `CachingProvider` wrapper is NOT used (cache lives at the envelope layer so BOTH seams + Director share it).
- **public surface added:** `AiCache` class; cache stats surfaced in the envelope route (`cacheHit: bool`). Settings key: `aiCacheEnabled` (default true), `aiCacheDir` (default data-dir/`ai-cache`).
- **test strategy:** pure `key()` determinism (same request → same key; param change → different key); `get/put` round-trip in a tmp dir; `run_ai_job` with a pre-seeded cache asserts the provider transport is NEVER called on a hit. Sidecar gate `pytest --cov=media_studio --cov-branch --cov-fail-under=100` met with tmp-dir fakes only (no real network/model; any unavoidable heavy seam gets inline `# pragma: no cover`).
- **acceptance (falsifiable):** (a) identical `(content-hash, model, params)` returns the cached result with ZERO provider calls (transport spy untouched); (b) any param/model/content change misses; (c) cache disabled → always calls provider; (d) no API key or transcript secret written to the cache in plaintext beyond the user's own local data dir (the cache is local-only, documented); gitleaks clean on fixtures.
- **dependencies:** WU-envelope.

---

### WU-budget — pre-flight cost/egress budget + tested graceful-degradation (P1 + P2)

- **id:** WU-budget
- **goal:** before a cloud AI run, compute and surface "~N requests across K providers, sends X (text/frames) to provider Y — proceed?" (P1) and make graceful-degradation a **tested invariant** (P2): saved config → next provider → local + a visible notice.
- **files/seams touched:**
  - **new:** `sidecar/media_studio/models/budget.py` — `estimate(request, pool, catalog) -> Budget{requests, providers, egressBytes, egressKinds:{text,frames}, withinFreeLimits:bool}` (pure). `degrade_chain(pool) -> [provider, ..., local]` (pure ordering used by rotation + the notice).
  - `sidecar/media_studio/models/ai_job.py` — `plan_ai_job` embeds the `Budget`; `run_ai_job` enforces the degrade chain and emits a `degraded` notice event when it falls through to local.
  - `sidecar/media_studio/models/provider.py` — `RotatingProvider` exposes the degrade event hook the envelope listens to.
- **public surface added:** `Budget` dataclass + `estimate`/`degrade_chain`; the `ai.planJob` response carries `budget`; a `degraded` notice in `job.progress`. Settings keys: `confirmCloudBudget` (default true → planJob must be acknowledged before run); **`defaultTargetJobSize`** — a default target-job-size constant/setting (e.g. one 60-min source → N shorts; the concrete N is open for the user, item §5.6) that `estimate` uses when the request does not pin a size. (Promoted from gate-2 PM finding into ACCEPTANCE per P1 #6.)
- **test strategy:** `estimate` pure with fixtures (text-only request, frame request, mixed); `degrade_chain` ordering; a forced-429-on-all-cloud test asserts the run degrades to local AND emits exactly one `degraded` notice; a no-key test asserts local-only with no egress; **a default-target-job-size test** (see acceptance below) — the budget for a default-size job (the `defaultTargetJobSize` setting) yields a falsifiable WU-budget count. Sidecar gate `pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
- **acceptance (falsifiable):** (a) planJob reports request count, provider list, and egress bytes split by kind (text vs frames) without sending anything; (b) when all cloud providers fail, the job completes on local and emits a visible `degraded` notice (asserted), never hangs; (c) `withinFreeLimits` correctly false when the estimate exceeds the catalog's per-provider free cap; (d) budget never double-counts a request against a key (gate-2/DESIGN R5); (e) **default target-job-size (P1 #6):** with no size pinned on the request, `estimate` uses `defaultTargetJobSize` and returns a falsifiable WU-budget count (a test pins the constant and asserts the exact request count for a default-size job).
- **dependencies:** WU-cache (so the budget can subtract cache hits).

---

### WU-catalog — static multi-provider catalog + per-task tiers + privacy axis

- **id:** WU-catalog
- **goal:** a hand-curated, multi-provider catalog ranking each model by fitness for Reframe's 5 tasks (Moment-Find/Select, Caption/Title/Hook, Translation, Vision/OCR, Edit-Plan Gen) with privacy flags incl. a **train-on-input axis** (SE1). User brings only their API key. Seeded from `CATALOG-SEED.md`. NOT a live `/models` fetch (auto-refresh is a LATER WU).
- **files/seams touched:**
  - **new:** `sidecar/media_studio/models/catalog.py` — `CatalogEntry{id, provider, capabilities[], contextTokens, perTaskTier:{t1..t5: S/A/B/C/na}, costClass, freeLimits, unit (req|token), trainsOnInput: bool|conditional, privacyTier (SAFE|CONDITIONAL|AVOID), recommendedFor[], notes, asOfDate}`; `CATALOG: tuple[CatalogEntry, ...]` seeded verbatim from `CATALOG-SEED.md` (Groq GPT-OSS-120B, Groq Llama 3.3 70B, Cerebras Qwen3-235B/Llama 3.3 70B, SambaNova 405B, Gemini 2.5 Flash/Flash-Lite, GitHub GPT-4o-mini, Mistral Pixtral, Cloudflare, OpenRouter `:free`, OpenAI API). Pure data + filter/order helpers.
  - **new docs:** `docs/providers/MODEL-GUIDE.md` (per-model best-for + cost/limit + privacy, dated) + `docs/providers/SETUP.md` (get a Groq/Cerebras/Gemini key, the OpenRouter $10 threshold note, privacy, **"N keys ≠ N×quota" / add keys from DIFFERENT providers"**).
- **public surface added:** `CatalogEntry`, `CATALOG`, `filter_by_capability`, `order_by(quality|limit|context)`, `top_pick_for_task(task)`. RPC method `providers.catalog` → the catalog as JSON for the UI. No secrets.
- **test strategy:** pure catalog assertions — every entry has all 5 task tiers + a privacy tier + a unit; `top_pick_for_task` returns the seeded picks (task1→Groq GPT-OSS-120B, task4→Gemini Flash-Lite with AVOID-private flag, etc.); filter/order helpers; every quality label carries `asOfDate` (rendered as "our pick · as of <date>", never an objective benchmark). Sidecar gate `pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
- **acceptance (falsifiable):** (a) catalog spans ≥3 distinct providers and ranks each model per the 5 tasks; (b) Gemini-free entry flagged `trainsOnInput=True`/`privacyTier=AVOID` for private data; (c) Groq flagged SAFE no-train; (d) every label is dated guidance; (e) docs `MODEL-GUIDE.md` + `SETUP.md` shipped and the "multi-provider, not multi-account" honesty statement present (matches `CATALOG-SEED.md` ⛔ section).
- **dependencies:** WU-merge (parallel to WU-pool).

---

### WU-keys — key management (user-brings, redacted, never-logged, RPC key-free, per-data-type consent)

- **id:** WU-keys
- **goal:** users supply every key; keys stored locally, redacted in UI (last-4), NEVER logged, and **the RPC layer never returns a full key** (gate-2 Security). The split is the crux: the **provider/translator FACTORY path consumes RAW keys** (via a `get_raw()` accessor) while **every RPC-facing read (`settings_get`, `providers.*`) returns REDACTED (last-4)**. Per-data-type consent: separate explicit opt-in for sending TEXT (transcripts) vs FRAMES (vision), each with the provider's train-on-input disclosure; frames require their own confirmation (SE1). Scrub provider error bodies of any leaked key/secret, ENFORCEABLY (the error class must be able to obtain the key-set to strip).
- **GROUND-TRUTH NOTE (verified):** today `settings_get` returns `self.settings.get()` raw (no redaction); `ProviderError` is constructed inside the free function `_urllib_post_json` (`provider.py:100-106`), which has the **Bearer header but NOT the apiKeys[] set** — so "scrub the error body of all known keys" is NOT achievable as written until the key-set reaches the construction point. This WU fixes both.
- **RAW-vs-REDACTED AUDIT (mandatory deliverable):** enumerate **every** `settings.get()` / settings-read caller that ultimately feeds a provider/translator a key, not just `_get_translator`. The known feed paths are: (1) `get_provider` (`provider.py:302`, `settings.get("cloudApiKey")` at line 320) → `CloudProvider`; (2) `TieredTranslator._hosted_provider` (`translation.py:454`, `settings.get("cloudApiKey")` at line 460) → `CloudProvider`; (3) the new `RotatingProvider` pool build (reads `settings.providers[].apiKeys`); (4) `handlers.MediaStudioHandlers.__init__` `self._provider` (line 107) and `_get_translator` (line 1054/1065). EACH of these must read RAW keys via `SettingsStore.get_raw()`; EVERY OTHER settings read that crosses RPC must read the REDACTED `SettingsStore.get()`. The WU ships a test that asserts this partition holds (a grep/AST-style test enumerating the callers).
- **ENFORCEABLE SCRUB (pick one, stated explicitly):** move `ProviderError` construction for HTTP errors **into the provider class** (`_OpenAICompatProvider`, which holds `self._api_key`) so it can pass its own key-set to `scrub_error_body`, OR thread the key-set down into `_urllib_post_json(...)` as a `secrets: Sequence[str]` arg. CHOSEN: thread `secrets=` into `_urllib_post_json` (smallest change; keeps the free function as the single HTTP path for BOTH providers and the pool). Then "no key in any error body" is an INVARIANT of the construction site, not a hope.
- **files/seams touched:**
  - `sidecar/media_studio/settings_store.py` — extend `DEFAULT_SETTINGS` with `providers` (apiKeys stored), `consent: {perProvider: {text: bool, frames: bool}}`. `SettingsStore.get()` MUST return providers with keys redacted to last-4 (a `redact_keys()` helper); a new **`SettingsStore.get_raw()`** (NOT exposed over RPC) returns full keys for the provider/translator factory path ONLY.
  - **new:** `sidecar/media_studio/models/secrets.py` — `redact(key) -> "…last4"`, `scrub_error_body(text, keys) -> text` (strips every key in `keys` + any `Authorization: Bearer …` pattern from a provider error body before it reaches a log or RPC error).
  - `sidecar/media_studio/models/provider.py` — `_urllib_post_json(..., secrets: Sequence[str] = ())` routes the HTTP error body through `scrub_error_body(detail, secrets)` at the `except urllib.error.HTTPError` branch (`provider.py:100-106`); `_OpenAICompatProvider` passes its key-set (`[self._api_key]` when set) into `_urllib_post_json` so the error never carries the live key. `get_provider`/`RotatingProvider` build providers from RAW keys (from `get_raw()`).
  - `sidecar/media_studio/models/translation.py` — `_hosted_provider` (`line 454`) builds from RAW keys via the injected factory (which the handlers feed from `get_raw()`); the inline `settings.get("cloudApiKey")` fallback (line 460) is the legacy path and must also read RAW.
  - `sidecar/media_studio/handlers.py` — new handlers `providers.list` (redacted), `providers.upsert`, `providers.remove`, `providers.testKey` (validates + returns capabilities, NO key echoed), `providers.setConsent`, registered in `register_all` (`handlers.py:1269`). `settings_get` (line 232) must switch from raw `self.settings.get()` to the REDACTED view. The provider/translator construction in `__init__`/`_get_translator` switches to `get_raw()`.
- **public surface added:** RPC `providers.list|upsert|remove|testKey|setConsent`; `SettingsStore.get_raw()` (internal, never registered); settings keys `providers[].apiKeys`, `consent.perProvider.{text,frames}`. Renderer: an `AddKeyRow`/`ProviderKeyRow` component (last-4 display, paste-to-add, remove) + a per-data-type consent toggle.
- **test strategy (sidecar gate: `pytest --cov=media_studio --cov-branch --cov-fail-under=100`; renderer gate: `npx vitest run --coverage`):** `redact` + `scrub_error_body` pure (a key embedded in an error body is removed; bearer header stripped; multiple keys stripped); **RAW path test:** the provider/translator factory receives the FULL key (assert the built `CloudProvider`/`RotatingProvider` carries the raw key, sourced from `get_raw()`); **REDACTED path test:** `settings_get`/`providers.list` serialized response contains NO full key (substring/regex assertion over the JSON); the RAW-vs-REDACTED partition test enumerating the four feed callers; `testKey` driven with a fake transport asserts capabilities returned and key absent from the response; a **forced-429 test** asserts the live key is absent from the resulting `ProviderError` message (enforceable scrub — not just from a log spy); a log-capture spy asserts no full key in any log line during a failing call. Frame consent gate: a vision call without `consent.perProvider[p].frames` is refused (typed). Renderer: `AddKeyRow`/consent toggle render-tests at vitest 100%.
- **acceptance (falsifiable):** (a) NO RPC method returns a full key — only last-4 (asserted on every providers.* + settings.get response); (b) the provider/translator factory path consumes RAW keys via `get_raw()` while RPC reads return redacted — the partition test enumerates ALL four feed callers and passes; (c) a forced provider 429/4xx error message contains NO live key (scrub is enforced at the construction site via the threaded `secrets=`, asserted directly on `ProviderError`, not only via a log spy); (d) text consent and frame consent are SEPARATE and independently revocable; a vision egress without frame consent is blocked; (e) train-on-input disclosure shown per provider before first use; (f) gitleaks clean on fixtures/logs/errors.
- **dependencies:** WU-pool (pool reads keys) + WU-catalog (capability/privacy metadata).

---

### WU-usage-ui — data-driven dual-unit usage bars + superpowered (a11y)

- **id:** WU-usage-ui
- **goal:** per-key live usage bars driven by **optimistic accounting + 429/rate-limit headers** (NOT a poller); req-limited and token-limited keys are **never summed** (gate-2 Designer dual-limit; DESIGN §13); multi-PROVIDER stacking + a precise "superpowered" state (≥3 same-unit healthy keys across DISTINCT providers, DESIGN §14); colorblind-safe non-color signals + reduced-motion + WCAG (gate-2 Designer; DESIGN §16).
- **SCOPE OVERRIDE (PH1 supersedes DESIGN §12):** the "superpowered" state is **IN MVP** (the user explicitly wanted it — grill decision PH1), built as the **data-driven (no-poller)** version. This one-line override supersedes DESIGN §12's "superpowered = phase-2 scheduling"; here it is purely a derived render state off the already-tracked per-key usage (optimistic decrement + 429 headers), so it adds NO poller and NO scheduler.
- **COVERAGE CONTRADICTION — RESOLVED (P0):** "req-limited and token-limited keys are never summed" cannot be a *typed-out / unreachable* branch and ALSO be 100% branch-covered (an unreachable branch is, by definition, uncoverable without a `# pragma`/`v8 ignore`). Resolution: make **mixed-unit grouping a POSITIVE, tested render path** — given a pool with both `REQ`- and `TOKEN`-unit keys, the component renders **two separate grouped bars** (one per unit) and a test asserts ≥2 groups with no cross-unit sum. The grouping function is exercised on real mixed input, so every branch is hit and the renderer hits vitest 100% with NO ignore. (No `v8 ignore` is needed for this path; reserve inline `/* v8 ignore -- <reason> */` only for genuinely runtime-only guards.)
- **files/seams touched:**
  - `sidecar/media_studio/models/provider.py` / a new `models/usage.py` — `UsageUnit` enum (`REQ`/`TOKEN`); the pool tracks per-key `{used, max, unit, resetAt}` from optimistic decrement + parsed 429/`X-RateLimit-*` headers; `providers.usage` RPC returns it (cached, persisted between runs per DESIGN §15-Q1, stale-flagged >10 min).
  - `sidecar/media_studio/handlers.py` — `providers.usage` handler (cached, no poll burst).
  - **new renderer:** `app/renderer/src/components/UsageBar.tsx` — single-key bar (fill = remaining/max; green ≥60 / yellow 30-60 / red <30 ramp WITH a non-color glyph/pattern + numeric `820/1000 req` or `1.2M/4M tok`); same-unit stacking; the superpowered purple state with an ALWAYS-present text label + tooltip; `prefers-reduced-motion` respected; stale = desaturated + "last checked Xm ago".
  - `app/renderer/src/panels/ModelsSystemPanel.tsx` — host the loaded-providers usage section (reuses `ResourceBar` patterns; adds `UsageBar`).
- **public surface added:** `providers.usage` RPC; `UsageUnit` enum (sidecar); `UsageBar` component. Settings key: persisted `usageCache` (timestamped).
- **test strategy (sidecar gate `pytest --cov=media_studio --cov-branch --cov-fail-under=100`; renderer gate `cd app && npx vitest run --coverage` at 100%):** `UsageUnit` grouping is a POSITIVE path — a test feeds a mixed `REQ`+`TOKEN` pool and asserts the component renders ≥2 SEPARATE grouped bars (no cross-unit sum); the grouping function is covered on real mixed input (NOT an unreachable typed-out branch). Bar color matches the exact thresholds; superpowered fires at exactly ≥3 same-unit healthy keys across DISTINCT providers and NOT at borderline (2 keys, or 3 keys spanning 2 providers); stale data flagged past threshold (fake clock). Renderer: render-tests for each color band + the non-color glyph presence + reduced-motion + the superpowered label text + stale desaturation — all at vitest 100%.
- **acceptance (falsifiable):** (a) req-limited and token-limited keys are NEVER summed into one bar — a mixed pool yields ≥2 grouped bars via a POSITIVELY-tested grouping path (no unreachable/uncovered branch); (b) usage is driven by optimistic accounting + 429 headers, not a poller (no background poll loop — asserted); (c) color is never the only signal (a glyph/pattern + numeric label always present — WCAG); (d) reduced-motion disables animation; (e) superpowered (IN MVP per PH1) = ≥3 same-unit healthy keys across DISTINCT providers with an always-present explicit text label, data-driven (no poller/scheduler).
- **dependencies:** WU-pool + WU-keys + WU-catalog.

---

### WU-presets — presets + per-function customize (PH3)

- **id:** WU-presets
- **goal:** smart presets ("Privacy/offline — all local", "Best free cloud", "Balanced") + a per-function override view (pick the model per task: select / subtitles / translation / vision / edit-plan) with the catalog's per-task ranking suggesting each slot. Full device-aware auto-recommender is a LATER WU.
- **files/seams touched:**
  - **new:** `sidecar/media_studio/models/presets.py` — `PRESETS: {privacy, bestFreeCloud, balanced}` each = a `routing.perFunction` mapping over the catalog + local; `apply_preset(name, settings, catalog) -> routing` (pure); `suggest_for_function(task, catalog, prefs) -> ordered candidates`.
  - `sidecar/media_studio/settings_store.py` — `routing.perFunction` + `activePreset` keys.
  - `sidecar/media_studio/handlers.py` — `providers.applyPreset`, `providers.setFunctionModel` handlers; `select`/`subtitles`/`translation`/`vision` provider factories honor `routing.perFunction` (each function prefers its configured provider, pool fallback).
  - **new renderer:** a Presets + per-function override section in `ModelsSystemPanel.tsx` (reuses `ModelCard`/`TierCard`).
- **public surface added:** RPC `providers.applyPreset`, `providers.setFunctionModel`; settings `routing.perFunction`, `activePreset`, **`firstRunChoiceMade: bool`** (drives the first-run local-vs-cloud chooser, P1 #6). `PRESETS`, `apply_preset`, `suggest_for_function`, `first_run_default(settings) -> "privacy"|"bestFreeCloud"` (pure: returns the privacy/all-local default until the user makes a choice).
- **test strategy:** pure preset application (privacy preset → all-local routing with NO cloud egress; bestFreeCloud → cloud-primary + local fallback; balanced → mixed); `suggest_for_function` returns catalog-ranked candidates per task; capability-mismatch never proposed; **first-run local-vs-cloud chooser** test (see acceptance). Sidecar gate `pytest --cov=media_studio --cov-branch --cov-fail-under=100`; renderer: preset buttons + per-function dropdown render-tests at vitest 100% (`npx vitest run --coverage`).
- **acceptance (falsifiable):** (a) the privacy preset routes EVERY function to local (zero cloud egress — asserted); (b) per-function override actually changes the provider the corresponding seam uses (assert `get_provider`/`get_translator`/vision pick); (c) each slot's suggestion is the catalog's per-task top pick; (d) preset choice persisted per project (UX3 ties in via WU later); (e) **first-run local-vs-cloud chooser (P1 #6):** on first run (`firstRunChoiceMade=false`) the chooser is presented and the default routing is privacy/all-local until the user picks; a test asserts `first_run_default` returns the local-safe default pre-choice and that making a cloud choice flips routing + sets `firstRunChoiceMade=true` (renderer chooser render-test at vitest 100%).
- **dependencies:** WU-catalog + WU-keys (+ WU-pool for routing).

---

### WU-vision — CloudVisionBackend on the smolvlm2 seam (PH4)

- **id:** WU-vision
- **goal:** offload Tier-2 vision captioning/re-rank to a free multimodal cloud model (Gemini / Gemma 4 / Nemotron VL / GitHub GPT-4o-mini) via the SAME rotation pool, behind the Tier-2 opt-in + a SEPARATE frame-egress consent. Extends the **smolvlm2** seam (gate-2 Architect: NOT `vlm_backbone`). Degrades to local SmolVLM2 or off per existing tiers.
- **CRITICAL WIRING PROBLEM (verified ground truth — solved below):**
  1. **The factory carries only settings.** `BackendFactory = Callable[[Mapping[str, Any]], SmolVlmBackend]` (`smolvlm2.py:102`) and `_default_backend_factory(settings)` (`smolvlm2.py:208`) receive ONLY a settings mapping — there is **no pool/transport channel** through that seam, so a `CloudVlmBackend` cannot "just be returned by the factory" and still reach the rotation pool. This MUST be solved, not assumed.
  2. **`phase8_select` does NOT pass `vlm_reranker` today.** `select_unified` accepts `vlm_reranker=` (`select.py:718`), but the `phase8_select` job_body (`handlers.py:759-783`) calls `select_unified(transcript, prompt, controls, provider, tracks=tracks, tier=tier)` with **no `vlm_reranker=`**. Cloud (or any) re-rank is therefore **NET-NEW wiring** in that handler — this is an ADD, not an augmentation of an existing pass.
  3. **There is no frame-egress consent gate in that job_body today** — it is net-new control flow that must be authored inside `phase8_select`.
- **CHOSEN MECHANISM (state explicitly):** **closure-inject the pool into a settings-resolved factory** (preferred over widening `BackendFactory`'s signature, which would touch the Protocol and every existing caller/test). Concretely: `handlers.phase8_select` builds a `vlm_reranker` by closing over the already-resolved rotation pool, e.g. `backend_factory = lambda settings: CloudVlmBackend(pool=self._provider_pool, settings=settings)` (a `partial`/closure), then constructs the reranker the same way the local path constructs `SmolVlmReranker(backend_factory=...)`. The pool is captured in the closure; the `BackendFactory` signature is UNCHANGED (still `settings -> SmolVlmBackend`). The local default closure (`_default_backend_factory`) is the fallback when cloud vision isn't selected.
- **WHERE THE FRAME-EGRESS CONSENT GATE LIVES (net-new control flow):** inside `phase8_select`'s `job_body` (`handlers.py:759-783`), BEFORE choosing the cloud `vlm_reranker`: read `routing.perFunction.vision` + `consent.perProvider[<vision provider>].frames` (from `SettingsStore.get()`); the decision tree is — cloud-vision selected AND frames consent granted → cloud `vlm_reranker` (closure over the pool); else if local SmolVLM2 weights present → local `vlm_reranker`; else → pass `vlm_reranker=None` (degrade to transcript-only, the existing no-rerank path). The gate is the FIRST thing the job does before any frame is read/encoded, so a no-consent run NEVER samples or base64-encodes a frame for egress.
- **files/seams touched:**
  - `sidecar/media_studio/features/smolvlm2.py` — add a `CloudVlmBackend(pool, settings)` implementing the `SmolVlmBackend` Protocol (`rank_clips(frames_per_clip, prompt) -> list[float]`): base64-encodes the sampled frame stacks and sends them through the injected rotation pool's vision-capable providers; returns per-clip scores. The pool arrives via the closure described above, NOT via the `BackendFactory` signature (which stays `settings -> SmolVlmBackend`). The pure half (`build_rerank_prompt`, `parse_rerank_order`, `reorder_by_indices`, `_order_from_scores`) is reused unchanged.
  - `sidecar/media_studio/models/provider.py` — `RotatingProvider` capability registry declares `vision`; vision requests only consider vision-capable pool entries (DESIGN §5.1).
  - `sidecar/media_studio/handlers.py` — **net-new in `phase8_select` (`handlers.py:759-783`):** the frame-consent gate + the cloud-or-local `vlm_reranker` selection, and the changed `select_unified(...)` call now passing `vlm_reranker=<resolved>`. This is the only place the cloud vision path is wired.
- **public surface added:** `CloudVlmBackend(pool, settings)` (in `smolvlm2.py`); reuses `providers.*` + consent. No new RPC.
- **test strategy (sidecar gate `pytest --cov=media_studio --cov-branch --cov-fail-under=100`):** inject a FAKE rotation pool returning canned vision responses → `CloudVlmBackend.rank_clips` returns the right per-clip score count; an n-mismatch still degrades to identity order (existing `_order_from_scores`/`SmolVlmReranker` no-op guard); **consent gate tests on the `phase8_select` job_body** — (i) cloud-vision selected + frames consent → `select_unified` is called with the cloud `vlm_reranker` (assert it was passed; assert the fake transport saw base64 frames); (ii) cloud-vision selected + NO frames consent → `select_unified` called with `vlm_reranker=None` (or local), and assert the fake vision transport was NEVER touched (no frame egress, no base64 encode); (iii) no vision provider / no local weights → `vlm_reranker=None`; rotation across vision providers on 429. No real model, no network (pool/transport + backend fakes; any unavoidable heavy seam gets inline `# pragma: no cover`).
- **acceptance (falsifiable):** (a) with a vision key + Tier-2 + frame consent, `phase8_select` passes a cloud `vlm_reranker` into `select_unified` and frames reach the cloud backend (assert via transport spy); without frame consent, `select_unified` receives `vlm_reranker=None`/local and NO frame is sampled or egressed (transport spy untouched); (b) the cloud path reaches the pool via the CLOSURE (pool captured), and `BackendFactory`'s `settings -> SmolVlmBackend` signature is unchanged (existing smolvlm2 tests stay green); (c) cloud vision rotates across distinct vision providers on 429; (d) the smolvlm2 pure parsing/no-op guards are unchanged; (e) frame consent is the SEPARATE per-data-type gate from text consent (SE1), evaluated FIRST in the job_body; gitleaks clean.
- **dependencies:** WU-pool + WU-keys (frame consent) + phase-8 vision base (WU-merge).

---

## 3. LATER Work Units (outline only)

### 3a. Near-term SURFACE-ONLY WUs (code already exists — do these BEFORE the heavier Director WUs)
These were "Also IN" but are mis-tiered if buried behind Director: the backing code already ships, so each is a thin UI/surface WU, not a build. Re-tiered per P1 #8 to sit near-term (after the MVP substrate, ahead of Director).
- **WU-fillers (N1) — filler-word/silence one-click removal — SURFACE-ONLY.** Local, on existing `audio_saliency` + transcript (`features/fillers.py` + `features/silencetrim.py` already exist). Work = a one-click action wired into the panel + handler; no new heavy logic. Renderer tested at vitest 100%; sidecar handler at `pytest --cov` 100%.
- **WU-diarize (N3) — speaker diarization finish — SURFACE-ONLY.** `features/diarize.py` + `pyannote_backend.py` already exist (heavy backend stays behind its injected/`# pragma: no cover` seam). Work = surface it (the Q&A path is multi-speaker). Pure routing/surface; gates as above.

### 3b. Heavier later program
- **Director v1 (D1/A1/D3/D4):** conversational agent + typed reversible EditPlan/tool-call DSL (extract + invert/undo contract FIRST, A1) + hard-validate-and-reject plans vs real clip duration/preconditions (D3); toolbox **T-stitch** (frame panorama-stitch), **T-scroll** (constant-speed scroll regen from a panorama — NOT a speed-ramp), **T-ocr-list** (OCR/vision list-extract → structured text + poster image), **T-transcript-edit** (transcript-as-timeline), **T-qa** (Q&A-segment stitch), **T-silence** (filler/silence trim). Proof = the BC-list canonical example (scroll-smooth + list-extract) then a 50-Q&A cost-stress; planner model chosen via an **eval harness** (offline clips → known-good plans → measure agreement, D4). Honest-about-limits first-class.
- **Batch queue + repurpose graph (N5):** drop-folder → shorts + captions + thumbnails each, paced vs live usage; gated behind pool+cache+budget+local-fallback.
- **Templates** + **multi-platform reframe/caption presets** (ties to brand kit + UX3 export presets).
- **Semantic footage index** (the substrate for cheap later features).
- **Device-aware auto-recommender** (`providers.recommend` consuming the System-Advisor RAM/VRAM probe; DESIGN §15-Q2) + **catalog auto-refresh** from OpenRouter `/models`.
- **AI best-frame thumbnails (UX4 phase-2)** — beyond the auto poster-frame now.
- *(N1 filler/silence + N3 diarization moved UP to §3a — near-term SURFACE-ONLY, per P1 #8.)*
- **Deepfake consent/provenance (SE3) — DEFERRED** per the user; revisit BEFORE any public distribution. No consent gate / no C2PA-SynthID for now.
- **Non-goals (do NOT build):** gaze-correction, AI avatars, generated b-roll, music-gen (hosted-model + licensing = the per-minute-cost + privacy loss that IS the product, F1/N4).

---

## 4. Cross-cutting concerns

### UX / QoL (fold into the WUs above + LATER)
- **UX1 — outputs project-relative + per-export save-as/reveal**, sensible auto-names (reveal-in-folder via the envelope's done payload, UX6).
- **UX2 — resume:** autosave project manifest + recent-projects + resumable jobs (the `jobs.py` layer already persists; reopen in-progress + resume running/failed).
- **UX3 — export presets remembered per-project** (format/quality/location/naming; ties to WU-presets + brand kit).
- **UX4 — auto poster-frame thumbnails now**; AI best-frame = LATER.
- **UX5 — shared availability badge vocabulary** (downloaded / needs-download / cloud-available) reused by the System-Advisor (`ModelsSystemPanel`) AND the Hub — one component vocabulary.
- **UX6 — universal progress + cancel + reveal via the AI-Job envelope** (WU-envelope is the single mechanism; every long job gets it for free).

### Security invariants (gate-2 Security — non-negotiable, asserted by tests)
- The RPC layer NEVER returns a full key (only last-4) — asserted on every `providers.*` + `settings.get` response (WU-keys). The provider/translator FACTORY path consumes RAW keys via `SettingsStore.get_raw()`; everything that crosses RPC reads the redacted `SettingsStore.get()` (the RAW-vs-REDACTED partition test enumerates ALL four feed callers — WU-keys).
- Keys never logged; provider error bodies scrubbed ENFORCEABLY: the key-set is threaded into `_urllib_post_json(..., secrets=)` (or `ProviderError` is built inside the provider class that holds the key) so `scrub_error_body` strips every live key + bearer header AT the construction site (`provider.py:100-106`) — "no key in any error body" is an invariant asserted directly on `ProviderError`, not just via a log spy (WU-keys).
- Per-data-type consent (text vs frames), independently revocable; frames require their own confirmation (WU-keys + WU-vision).
- Multi-PROVIDER rotation only; same-provider extra keys = failover, never advertised ×quota ("N keys ≠ N×quota" honored, SE2 / `CATALOG-SEED.md`).
- No ToS/CAPTCHA evasion; respect each provider's rate limits.
- gitleaks clean: no keys in logs, fixtures, or error strings.
- Telemetry posture: no AI inputs/keys leave the machine except to the user's chosen provider; documented.

### Standing quality gate (every WU) — the REAL repo gate
The single source of truth is **`.github/workflows/quality.yml` gate:3** (verified on `feat/phase8-moment-finding`). `.coverage-thresholds.json` does NOT exist — do not reference it.
- **Sidecar — 100% line + branch:** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`. Treat any gap as BLOCKING before commit/PR. Heavy seams (real model/network) are isolated behind injected fakes and the real-impl seam carries an **inline `# pragma: no cover`** (the proven pattern — e.g. `_default_backend_factory` at `smolvlm2.py:210`, `_urllib_post_json` at `provider.py:98`). Cooldown/clock logic is NOT pragma'd — it is made deterministic via an injected `now()` and covered with a fake clock.
- **Renderer — vitest 100% (NOT jest):** `cd app && npx vitest run --coverage`. `app/vitest.config.ts` enforces `thresholds: {lines, branches, functions, statements} = 100`. Untestable runtime-only lines use inline **`/* v8 ignore … -- <reason> */`**, never a blanket exclude. Every new component + the panel are tested.
- **TDD mandatory** (RED→GREEN→refactor); no self-certification — independent adversarial review per the metaswarm orchestration loop.

---

## 5. Risks & open items for the user

1. **Rate-limit math (HIGH):** "N keys = N×quota" is FALSE (per-account). The plan honors this (multi-PROVIDER only); the 50-Q&A Director flagship is a LATER cost-stress — **verify empirically per-provider before any ×N UI claim** (SE2). Open: confirm Cerebras/SambaNova train-on-input ToS at signup (catalog marks them unverified).
2. **DSL not extracted yet (HIGH, LATER):** Director's reversible EditPlan/tool contract must be extracted + inverted BEFORE Director writes one edit (A1) — unretrofittable. Flagged so the Director WU starts there, not with edits.
3. **Vision frame egress (MEDIUM):** heavier + more privacy-sensitive than text; the plan gates it behind Tier-2 opt-in + a SEPARATE frame consent + AVOID-private catalog flags. Open: which paid vision tier sits behind the free Gemini for PII frames (GitHub GPT-4o-mini prototyping vs paid Gemini/OpenAI) — user preference.
4. **Catalog drift (MEDIUM):** free tiers churn; the plan ships DATED curated guidance + a LATER `/models` auto-refresh. Re-verify `CATALOG-SEED.md` at build time.
5. **Gemini OpenAI-compat (LOW):** Gemini's native API differs; use Google's OpenAI-compat endpoint or a thin adapter (decide at WU-pool implementation; DESIGN R1).
6. **Default target-job-size + first-run local-vs-cloud chooser (PROMOTED to ACCEPTANCE per P1 #6):** the default target job size is now a tested `defaultTargetJobSize` setting with a falsifiable WU-budget count (WU-budget acceptance (e)), and the first-run local-vs-cloud chooser is a tested acceptance item with a local-safe default pre-choice (WU-presets acceptance (e)). **Still open for the user (a value, not a gap):** what is the concrete default target job size (e.g. one 60-min source → N shorts)? The WU ships with a documented placeholder constant until the user pins N.
7. **Execution method (USER DECISION REQUIRED before build):** after the Plan Review Gate passes, choose: (1) metaswarm orchestrated, (2) subagent-driven, or (3) parallel session. Per CLAUDE.md this is always asked, never auto-picked.

---

## 6. Definition of Done (MVP)

A user on weak hardware can: choose local-vs-cloud on first run (local-safe default), load ≥3 keys from DISTINCT providers, see a static multi-provider catalog ranked per Reframe task with privacy flags, pick a preset or per-function model, run `select` + `subtitles` + `translation` + Tier-2 vision entirely on free cloud with rotation that never freezes (local backstop on full exhaustion; no `time.sleep` on the hot path), watch dual-unit usage bars (req and token never summed — a POSITIVELY-tested mixed-unit grouping; superpowered IN MVP at ≥3 healthy same-unit keys across distinct providers, data-driven; colorblind-safe + reduced-motion + WCAG), preview a cost/egress budget (with a default target-job-size) before each cloud run, and have every job show progress/cancel/reveal — with per-data-type consent (text vs frames; the frame-egress gate evaluated first in `phase8_select`'s job_body) and NO key ever logged or returned over RPC (factory path RAW via `get_raw()`, RPC reads redacted; error bodies scrubbed at the construction site). Both LLM seams (`get_provider` AND `TieredTranslator` tier3 hosted) are covered by rotation; the vision seam reaches the pool via a closure-injected `vlm_reranker` net-newly wired into `phase8_select`.

**Coverage gate (the REAL repo gate — cited everywhere in this plan):** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` (100% line+branch, heavy seams behind inline `# pragma: no cover`) AND `cd app && npx vitest run --coverage` (vitest 100% thresholds, untestable lines via inline `/* v8 ignore */`). There is NO `.coverage-thresholds.json` and NO jest. gitleaks clean.
