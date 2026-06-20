# Reframe "Intelligence" Bundle — DESIGN

> Status: DESIGN (docs only — no feature code in this branch).
> Branch: `feat/intelligence-design` off `origin/main`.
> Scope: three capabilities that ride the shipped Provider-Hub AI substrate —
> (1) **Semantic Index** (embed + semantically search the transcript / clips /
> moments), (2) **Device-Aware Auto-Recommender** (recommend models / providers /
> settings per detected hardware), (3) **AI Best-Frame Thumbnail Selection**
> (pick the most engaging frame per clip via the vision seam).

All three are **grounded in real code** in this repo (file:line citations
throughout). Where a needed primitive does not exist yet it is named explicitly
under **Capability Gaps** rather than assumed.

---

## 0. Grounding — the substrate we reuse (cite-first)

Every AI call in Reframe already rides ONE typed substrate. The Intelligence
bundle adds NO second AI path; it plugs into these exact seams:

| Seam | Where | What it gives us |
|------|-------|------------------|
| AI-Job envelope | `sidecar/media_studio/models/ai_job.py:204` `plan_ai_job` (PURE) + `:264` `run_ai_job` | `{inputs, route, costEst, cacheKey, preview, result, cancel}`; cache-first, budget/egress preview, degrade chain, one job bus |
| Custom `work` body on the envelope | `ai_job.py:261` `AiWork = Callable[[ctx, AiJob, provider], dict]`, driven at `:311` `_execute_work` | lets a handler run its own pipeline through the shared cancel-check + degrade-aware provider while keeping its own done-payload shape |
| Rotation pool | `models/provider.py:534` `RotatingProvider`, built by `:684` `build_pool_provider` | failover-only multi-key pool, local backstop always last, `capability=` filter (`"text"`/`"vision"`), `usage()` accounting |
| Per-function routing | `models/presets.py:59` `FUNCTIONS=("select","subtitles","translation","vision","editPlan")`, applied via `presets.apply_preset` (`:179`); resolved per call by `handlers.py:553` `_function_prefer` → `prefer=` into `get_provider`/`build_pool_provider` | "which provider does THIS function prefer", local-only privacy route |
| Consent gate (text vs frames, independently revocable) | `handlers.py:414` `providers_set_consent`; frame-egress enforced PER-ENTRY at pool build time `handlers.py:597` `_frame_consented_vision_settings` + `models/consent.frame_consent_granted` | no frame/text egresses without that provider's consent |
| Budget pre-flight + ack gate | `handlers.py:1693` `ai_plan_job` (`ai.planJob`, ZERO provider calls) + `:1672` `_enforce_cloud_budget_ack` (`confirmCloudBudget` → `ack==cacheKey`) | cost/egress shown and acknowledged before any cloud byte leaves |
| AI content cache | `handlers.py:1570` `_ai_cache` → `models/ai_cache.AiCache` (local-only, `settings.aiCacheDir`) | a cache hit skips the provider entirely |
| Plan helper | `handlers.py:1601` `plan_ai_job_envelope` + `:1617` `_run_ai_job` (the ONE place handlers plan+run+gate-budget an envelope) | the wiring every new AI handler copies |
| The ONE RPC site | `handlers.py:1982` `register_all` (calls `protocol.register`; feature modules ship their own `register()` and are invoked here) | where new `*.*` methods are wired |
| Vision frame seam (REUSE for best-frame) | `features/smolvlm2.py:338` `_default_clip_frame_loader` (8 evenly-spaced frames/clip via cv2, `FRAMES_PER_CLIP=8` `:60`), `:257` `CloudVlmBackend.rank_clips` → OpenAI multimodal `image_url` parts, `:670` handlers `_resolve_vlm_reranker` (consent→cloud, else local weights, else off) | sampling frames + scoring them through the rotation pool with frame-consent already enforced |
| Hardware probe + advisor | `handlers.py:1134` `system_probe` (`system.probe` → `{vramMb,ramMb,cpuCount,gpuPresent}`), `:1152` `system_advisor` (`system.advisor`), `features/system_advisor.py:681` `advise_for_hardware`, `:484` `recommended_preset`, `:1305` `_models_present_map` | the device→capability brain we extend |
| Local-server detect | `models/local_detect.py:107` `detect_local_servers` (Ollama `:11434`, LM Studio `:1234` via `GET /models`) | what local engines are actually running |
| Asset manifest | `assets/manifest.py:61` `AssetEntry`, `:134` `register_asset`, `:156` `get_asset`; day-1 `whisper-large-v3-turbo` `:181` + `qwen3-4b-gguf` `:188`; `hf`/`download`/`env` installers | how a new model weight is pinned + installed |
| Transcript shape (the index source) | `features/transcribe.py:5-7` `Word={text,start,end}` · `Segment={start,end,text,words}` · `Transcript={language,segments,durationSec}`; persisted onto the project manifest at `handlers.py:1069` (`project.data["transcript"]`) | the text we embed |
| Renderer RPC client + types | `app/renderer/src/lib/rpc.ts` (typed `rpc(method,…)`, `Transcript`/`Candidate`/`AdvisorReport` interfaces `:32/:87/:243`); panels `app/renderer/src/panels/ModelsSystemPanel.tsx`; views `app/renderer/src/views/Workspace.tsx`; features `app/renderer/src/features/ShortMaker.tsx`, `Transcribe.tsx`, `ProducedShorts.tsx` | where the UI calls land |

---

## 1. Capability A — Semantic Index ("find where they talk about X")

### 1.1 User value + MVP cut
**Value.** A user with a 90-minute transcript types "where do they talk about
pricing?" and jumps straight to the moments — without scrubbing. It also feeds
the existing short-maker: a semantic query becomes a candidate seed.

**MVP cut (smallest shippable):**
- Embed the **already-produced** transcript at the **segment** granularity
  (`Transcript.segments`, `transcribe.py:6`). No re-transcribe, no clip/moment
  embedding in MVP (those reuse the same index later).
- One RPC `index.search({videoId, query, topK?}) → {hits:[{segmentIndex, start,
  end, text, score}]}`. Cosine over query-embedding vs cached segment-embeddings.
- One build RPC `index.build({videoId}) → {jobId}` (long job: embed all segments,
  persist the vectors). `index.status({videoId}) → {built, segmentCount,
  model, builtAt}`.
- Local-first: embeddings run on the **local** route by default (privacy preset),
  so the default install never egresses transcript text.
- Renderer: a search box in `Workspace.tsx`
  (`app/renderer/src/views/Workspace.tsx`, transcript view) that lists hits.
  Each hit is keyboard-activatable and seeks the player (see §1.6 a11y).

**Explicitly OUT of MVP:** approximate-NN/FAISS (linear cosine is fine for a
single video's few-thousand segments), cross-video search, embedding of
non-transcript media, query rewriting.

### 1.2 Architecture — reuse vs NEW
**Reuse:**
- The AI-Job envelope for the *embedding call itself*: an embedding is an AI call
  with `capability="text"`, so `index.build` plans + runs it through
  `_run_ai_job` (`handlers.py:1617`) with a custom `work` body — inheriting
  cache, budget pre-flight, degrade chain, and the one job bus. (See Gap G-A1:
  the provider seam currently exposes `chat`, not `embed`.)
- The rotation pool + per-function routing: a NEW function name `"index"` is
  added to `presets.FUNCTIONS` (`presets.py:59`) and `_REQUIRED_CAPABILITY`
  (`presets.py:68`) so the user can route embeddings to local / a cloud
  embeddings provider exactly like every other function.
- Budget: `confirmCloudBudget` ack already gates any cloud egress via
  `_enforce_cloud_budget_ack` (`handlers.py:1672`) — embeddings ride the budget
  pre-flight unchanged (the cost gate fires because `_ai_pool()` includes the
  configured cloud providers, so `willEgress=bool(cost.providers)`).
- Consent (NEW seam — see Gap G-A5): **the substrate does NOT yet privacy-gate
  transcript-text egress.** `consent.text_consent_granted` (`consent.py:85`) and
  `DATA_TYPE_TEXT` (`consent.py:37`) exist but are dead code — verified called
  nowhere in `sidecar/` outside their own module + its tests; there is **no**
  `require_text_consent` and **no** `_text_consented_settings` pool filter
  analogous to the frame path (`handlers.py:597`
  `_frame_consented_vision_settings` is the only consent-aware pool filter). So
  the existing text-egress functions (translation/select/subtitles) are guarded
  by the *cost* ack only, not by a privacy/consent gate. Embeddings of a full
  transcript are the most sensitive bulk-PII egress in this bundle (a 90-min
  transcript far exceeds 8 sampled frames), so this capability **adds the missing
  seam** rather than inheriting a non-existent one (see Sec. 1.5 + G-A5).
- The cosine primitive ALREADY exists: `features/diarize.py:75`
  `cosine_similarity(a,b)` (with length-mismatch guard). The search ranker reuses
  it directly rather than re-deriving.
- Persistence: the per-video **project manifest** (`library.Project`,
  `handlers.py:208` `_load_or_create_project`) is the established per-video store;
  the index lives there or in a sibling sidecar file (see §1.4).

**NEW components (sidecar):**
- `features/semantic_index.py` — PURE: build the segment corpus from a
  `Transcript`, compute cosine top-K against a query vector, shape the hits. (No
  model; the embedding vectors are injected, mirroring how every feature module
  keeps the heavy seam out.)
- `models/embedder.py` (or extend `provider.py`) — the embedding seam: an
  `Embedder.embed(texts) -> list[list[float]]` Protocol with an
  OpenAI-`/v1/embeddings`-compatible impl (local llama.cpp/Ollama expose this) +
  the local backstop. This is the substrate the envelope's `work` body drives.
- A NEW `index_build` / `index_search` / `index_status` handler trio on
  `Services` + their `reg(...)` lines in `register_all`.

**NEW (renderer):** `app/renderer/src/features/SemanticSearch.tsx` (+ test) and a
mount point in `Workspace.tsx` (`app/renderer/src/views/Workspace.tsx`); `rpc.ts` gets `IndexHit` / `IndexStatus` types and
the three method signatures.

### 1.3 RPC surface
New `index.*` methods, registered in `register_all` (`handlers.py:1982`):
- `index.build({videoId})` → `{jobId}` — long job; `job.done.result =
  {segmentCount, model, builtAt}`.
- `index.search({videoId, query, topK?=8})` → `{hits:[{segmentIndex, start, end,
  text, score}]}` — embeds the query (cache-keyed), cosine vs stored vectors,
  returns top-K. The query embedding, when routed to cloud, is a (small) egress
  and MUST pass the same text-consent + budget path as `index.build` (it is NOT a
  silent direct provider call). Direct-return (one short embedding call; or job if
  a cloud round-trip is undesirable inline — decide in PLAN).
- `index.status({videoId})` → `{built, segmentCount, model, builtAt, dim}`.

Renderer surface: `rpc('index.build'|'index.search'|'index.status', …)` via the
typed client (`rpc.ts`), progress via the existing `onProgress`/`onJobDone`.

### 1.4 Data / storage + settings keys
- Vectors stored per-video next to the manifest:
  `projects/<videoId>.index.json` (sidecar, NOT the manifest body, to keep the
  manifest small) — `{model, dim, builtAt, vectors:[[float,…],…]}` aligned by
  segment index. (Decision deferred to PLAN: sidecar file vs manifest key
  `project.data["semanticIndex"]`.)
- Settings keys: `routing.perFunction["index"]` (provider route, via existing
  `providers.setFunctionModel`/`applyPreset`); reuse `aiCacheDir` for the
  query-embedding cache. NO new top-level toggle needed beyond routing.
- Catalog: add an `EMBED` task tier so the catalog (`models/catalog.py`,
  surfaced via `providers.catalog`) ranks embedding-capable models — OR reuse the
  text tier for MVP (Gap G-A2).

### 1.5 Reversibility / safety + consent/budget
- Read-only over the transcript; building writes only the index sidecar (delete
  to revert; `index.build` is idempotent — rebuild overwrites).
- Cloud egress (sending transcript text to a cloud embeddings API) is gated by
  TWO checks: (1) a **NEW per-entry text-consent filter** that this capability
  introduces — `consent.require_text_consent` + a `_text_consented_settings`
  pool filter (the text-side analog of `_frame_consented_vision_settings`,
  `handlers.py:597`) that drops any non-text-consented provider entry **at pool
  build time**, so a 429 failover can never rotate transcript text onto a
  provider the user did not consent to; and (2) the existing `confirmCloudBudget`
  ack via `_enforce_cloud_budget_ack` (`handlers.py:1672`). Honest substrate
  state: the consent gate is NEW (G-A5) — `text_consent_granted` exists today
  (`consent.py:85`) but is unused, so without this seam transcript text would
  egress on any cloud route once a key is configured, defeating the
  "default install never egresses transcript text" promise. The MVP MUST ship
  this seam (or, per G-A5, route `index` local-only and document that cloud
  `index` is unavailable until the seam lands) — it must NOT be hand-waved as
  inherited. Default privacy preset → local embeddings → zero egress regardless.
- `index.search`'s inline query embedding is itself a (small) cloud egress when
  routed to cloud; it flows through the SAME text-consent + budget path described
  above (not a silent direct provider call) — see §1.3.
- `index.search` over a not-yet-built index returns a typed
  `INVALID_PARAMS`-style "build the index first" (mirrors
  `subtitles_generate`'s "no transcript yet", `handlers.py:733`).

### 1.6 Accessibility + interaction contract (SemanticSearch surface)
Mounts into `app/renderer/src/views/Workspace.tsx`, which already uses
`role="alert"` for errors (`Workspace.tsx:176/185`) and `role="tabpanel"`
(`:190`); the new surface MUST match these idioms (and the vitest
`thresholds:100` gate means each attribute below is test-asserted).

- **Search input.** A labelled control: `<label htmlFor="semantic-search-query">`
  + `id` on the input (mirrors `Transcribe.tsx:114` `<label htmlFor>`), or an
  `aria-label="Search the transcript"` if no visible label. Submit on Enter and
  via an explicit search button (`type="submit"`, accessible name "Search").
- **Results list = keyboard-operable (WCAG 2.1.1).** Each hit is a real
  focusable control (`<button type="button">` rows inside a `<ul>`, or a
  `role="listbox"`/`role="option"` set), NOT a click-only `<div>`. Activating a
  hit with **Enter/Space OR click** seeks the player; on activation, move/return
  focus deliberately (focus the player region, or keep focus on the hit and
  announce the seek) so the jump-to-topic flow is reachable mouse-free. Each row's
  accessible name includes the timestamp + snippet (e.g. "Seek to 12:04 — '…we
  priced it at…'").
- **Status announcements via `aria-live`.** A polite live region (mirroring
  `Transcribe.tsx:141` `aria-live="polite"` and `Workspace`'s progress idiom)
  announces: "Searching…" while `index.search` runs, the result count on
  completion ("8 matches"), and "No matches" on an empty result. The progress
  region mirrors `Transcribe.tsx:141` (`aria-live="polite"`); the error fallback
  mirrors `Transcribe.tsx:149` (`role="alert"`).
- **UX states (all three explicit):**
  - *Not built yet* — `index.status.built === false`: the search box renders
    disabled with an inline CTA "Build the search index" (a button that calls
    `index.build`); the typed "build the index first" error (§1.5) is surfaced via
    `role="alert"` only as a fallback if a search is attempted unbuilt.
  - *Building* — `index.build` is a long job: show a progress region fed by the
    existing `onProgress` (`rpc.ts:434`) with `aria-live="polite"`, and surface
    completion via `onJobDone` (`rpc.ts:436`); the search box is disabled until
    `index.status.built`.
  - *Empty result* — a visible "No matches for '<query>'" message that is ALSO
    announced (live region above), not a silent blank list.
  - *Error* — `role="alert"` (mirroring `Workspace.tsx:176`).

---

## 2. Capability B — Device-Aware Auto-Recommender

### 2.1 User value + MVP cut
**Value.** On first run (or "re-detect"), the app inspects the machine and
proposes: which preset (`privacy`/`balanced`/`bestFreeCloud`), which ASR engine,
which models to download, and which per-function routes — instead of making the
user reason about VRAM. One click applies it.

**MVP cut:**
- A NEW `system.recommend({commercial?}) → {recommendation}` RPC that composes the
  EXISTING `advise_for_hardware` report into an **actionable plan**: a concrete
  `{preset, routing.perFunction, asrEngine, downloads:[assetName], rationale[]}`.
- The renderer `ModelsSystemPanel.tsx` gains a "Recommended for your machine"
  card with an "Apply" button that calls `providers.applyPreset` (or
  `setFunctionModel` for the per-function deltas) + flips `asrEngine` via
  `settings.set`.
- It does NOT auto-apply; it proposes and the user confirms (one-click apply).

**OUT of MVP:** benchmarking the machine, auto-downloading weights without
consent, continuous background re-detection.

### 2.2 Architecture — reuse vs NEW
**Reuse (this capability is ~80% existing wiring):**
- `system.probe` (`handlers.py:1134`) for `{vramMb,ramMb,cpuCount,gpuPresent}`.
- `advise_for_hardware` (`system_advisor.py:681`) for per-component verdicts +
  runnable `TierStatus` + `recommended_preset` (`:484`).
- `_models_present_map` (`handlers.py:1305`) for what is already installed (so we
  recommend downloads only for missing-but-runnable components).
- `detect_local_servers` (`local_detect.py:107`) so a running Ollama/LM-Studio is
  folded into the recommendation (recommend routing to a local server the user
  already has, before suggesting a download).
- `presets.apply_preset` / `CatalogAdapter` (`presets.py:179/257`) to turn the
  recommended preset into a concrete `routing.perFunction` the Apply step persists
  via the EXISTING `providers.applyPreset` handler — no new mutation path.
- `asr.engines` (`handlers.py:1175`) for the ASR pick.

**NEW components (sidecar):**
- `features/recommender.py` — PURE: `recommend(report, present, detectedLocal,
  asrEngines, offline) -> Recommendation`. Maps the advisor's `recommended_preset`
  + installed-state + detected local servers into `{preset, routing, asrEngine,
  downloads, rationale}`. Fully testable with fake reports (no probe, no GPU).
- A thin `system_recommend` handler on `Services` + its `reg("system.recommend",…)`
  line. It calls the existing probe/advisor/detect seams and `recommender.recommend`.

**NEW (renderer):** a recommendation card + Apply flow in `ModelsSystemPanel.tsx`
(+ test); `rpc.ts` gets a `Recommendation` type and the method signature.

### 2.3 RPC surface
- `system.recommend({commercial?})` → `{recommendation:{preset, routing:{perFunction},
  asrEngine, downloads:[{assetName, label, sizeMb, reason}], rationale:[string]}}`
  — direct-return (cheap; composes existing direct-return probes). Registered in
  `register_all`.
- **No new mutation RPC:** "Apply" reuses `providers.applyPreset` +
  `providers.setFunctionModel` + `settings.set` (`{asrEngine}`) + the assets
  package's existing download RPC (`assets/rpc.py`). This keeps every state change
  on an audited, already-tested path.

### 2.4 Data / storage + settings keys
- Persists nothing new on its own; Apply writes the existing keys
  (`activePreset`, `routing`, `asrEngine`, `firstRunChoiceMade`).
- Optionally stamp `settings.lastRecommendation` (the proposed plan + timestamp)
  so the panel can show "last recommended Xd ago" — read-only diagnostic.

### 2.5 Reversibility / safety + consent/budget
- The recommendation itself is PURE and side-effect-free (read-only probes).
- Apply is reversible: the user can re-pick any preset/route afterward (existing
  `setFunctionModel` flips `activePreset` to `"custom"`, `handlers.py:521`).
- Downloads remain consent-gated by the existing asset-download flow; the
  recommender only *proposes* `downloads`, never triggers them.
- Offline mode (`offline.is_offline`) is honored: a download-requiring component
  is recommended only when not offline, and cloud routes are not proposed when the
  user is on the privacy default unless they opt in (mirrors
  `advise_for_hardware(offline=…)` at `handlers.py:1172`).

### 2.6 Accessibility + interaction contract (Recommendation card)
Mounts in `app/renderer/src/panels/ModelsSystemPanel.tsx`; must match the
codebase's section/label idioms (`aria-label` on every `<section>`, `htmlFor`
labels) and is covered by vitest `thresholds:100`.

- **Card semantics + hierarchy.** The card is a `<section aria-labelledby=…>`
  with a heading (`<h2>`/`<h3>` "Recommended for your machine") so it is a
  navigable landmark; the rationale list renders as a real `<ul>`; the proposed
  preset/routing/downloads are presented as labelled rows, not bare text, so the
  information hierarchy (what changes vs why) is conveyed to assistive tech.
- **Apply button.** `<button type="button">` with a clear accessible name
  ("Apply recommended settings"). After Apply, announce the outcome via a polite
  live region ("Applied: balanced preset, vision → local") so the one-click
  result is perceivable without re-reading the panel; the button reflects a
  pending state (`aria-busy` while `providers.applyPreset`/`setFunctionModel`
  run) and a done state.
- **UX states (explicit):**
  - *Loading* — while `system.recommend` runs, show a polite "Analysing your
    machine…" live region; the Apply button is disabled.
  - *Empty / unavailable* — if probe data is unavailable (no GPU info / advisor
    returns no actionable plan, G-B1), render a visible, announced "Could not
    detect your hardware — pick a preset manually" with a link to the manual
    routing controls, NOT a blank card.
  - *Error* — `role="alert"` (matching the panel's existing error idiom).
  - *Already optimal* — if the current settings already match the recommendation,
    state it ("Your settings already match the recommendation") and present Apply
    as a no-op / disabled with that reason as its accessible name.

---

## 3. Capability C — AI Best-Frame Thumbnail Selection

### 3.1 User value + MVP cut
**Value.** Each produced short gets a thumbnail that is the **most engaging
frame** of the clip (clear face, peak expression, on-screen text), instead of the
first frame. Higher click-through with zero manual frame-scrubbing.

**MVP cut:**
- A NEW `thumbnail.select({videoId, candidateId})` (or `{path, start, end})` →
  `{jobId}`; `job.done.result = {frameTimeSec, thumbnailPath, score}`.
- Reuse the vision pipeline: sample N frames across the clip span, score each for
  "best thumbnail", pick the argmax, encode it to a JPEG/PNG next to the clip.
- Local-first via the SmolVLM2 local backend when weights are present; cloud via
  the frame-consented rotation pool otherwise; **off** (fallback = midpoint frame)
  when neither is available — never blocks export.
- Renderer: a "Pick best frame" action in `ProducedShorts.tsx` /
  `ShortMaker.tsx` that swaps the thumbnail.

**OUT of MVP:** generating a *new* composited thumbnail (text overlay/branding —
that is the brandkit's job); multi-frame A/B; per-platform crops.

### 3.2 Architecture — reuse vs NEW
This is the highest-reuse capability — the frame seam already exists for clip
re-ranking.

**Reuse:**
- `smolvlm2._default_clip_frame_loader` (`smolvlm2.py:338`) samples
  `FRAMES_PER_CLIP` (`:60`) evenly-spaced frames for a span via cv2 — exactly the
  frames a best-frame picker needs.
- `smolvlm2._default_frame_encoder` (`:239`) base64-encodes a frame; the cloud
  multimodal message shape (`CloudVlmBackend._image_part`, `:288`) is the
  per-frame `image_url` part we send.
- `handlers._resolve_vlm_reranker` (`handlers.py:670`) is the EXACT decision tree
  we mirror: frame-consented cloud pool first → local weights → `None`/off. The
  best-frame resolver reuses `_vision_pool` (`:624`) +
  `_frame_consented_vision_settings` (`:597`) so **no frame egresses without that
  provider's frame consent**, enforced per-entry at pool build.
- Per-function routing `"vision"` (`presets.py:59`) already governs the vision
  provider — best-frame uses the same route (no new function name needed; it IS a
  vision task).
- The AI-Job envelope: best-frame runs as a custom `work` body through
  `_run_ai_job` (`handlers.py:1617`) so it gets cancel-check, degrade tracking,
  budget pre-flight (frames are the costly egress kind — `Budget.egressKinds.frames`
  is already modeled, `ai_job.py:159`), and the one job bus. The cache key
  includes the clip span + frame params so a re-pick is a cache hit.
- Thumbnail write path: `features/shorts.py` already owns thumbnail paths
  (`shorts.thumbnail_path`, used at `handlers.py:1519`) — reuse it for the output
  location.

**NEW components (sidecar):**
- `features/best_frame.py` — PURE: `build_select_prompt(frames)` (one multimodal
  message asking "which frame index is the best thumbnail and why"),
  `parse_best_index(reply, n)` (mirrors `smolvlm2.parse_rerank_order`'s
  total/forgiving parse, `smolvlm2.py:145`), and the argmax/score shaping. No cv2,
  no model — frames + replies injected.
- A `BestFrameBackend`/scorer seam analogous to `SmolVlmBackend.rank_clips`
  (`smolvlm2.py:96`) — likely `score_frames(frames, prompt) -> list[float]`. May
  reuse `CloudVlmBackend` directly by treating each frame as a 1-frame "clip".
- A `thumbnail_select` handler on `Services` + `reg("thumbnail.select",…)`.

**NEW (renderer):** a "Pick best frame" button + thumbnail swap in
`ProducedShorts.tsx` (+ test); `rpc.ts` gets the method + `BestFrame` result type.

### 3.3 RPC surface
- `thumbnail.select({videoId, candidateId})` → `{jobId}`; done payload
  `{frameTimeSec, thumbnailPath, score}`. Resolves the clip span from the
  selection cache (`handlers.py:1404` `candidates`) or explicit `{path,start,end}`.
  Registered in `register_all`.

### 3.4 Data / storage + settings keys
- Output: a JPEG/PNG next to the clip (via `shorts.thumbnail_path`); the clip's
  sidecar metadata (`shorts.read_metadata`, `handlers.py:1518`) records
  `thumbnailFrameSec` so a re-export keeps the chosen frame.
- Settings: reuses `routing.perFunction["vision"]`, frame consent, and
  `confirmCloudBudget`. New optional `settings.autoThumbnail` (bool) to run
  best-frame automatically at the end of `shortmaker.export` — default off in MVP.

### 3.5 Reversibility / safety + consent/budget
- Frame egress is the privacy-sensitive path; it is gated PER-ENTRY by frame
  consent at pool-build (`_frame_consented_vision_settings`, `handlers.py:597`) —
  a 429 failover can never reach a non-consented provider. Budget pre-flight shows
  the frame-byte egress before any cloud call.
- Degrade-safe: no consented cloud + no local weights → fall back to the midpoint
  frame (deterministic, zero egress); the export never fails because of
  best-frame.
- Reversible: re-running picks a fresh frame; the original clip is untouched (only
  the thumbnail file + the `thumbnailFrameSec` metadata change).

### 3.6 Accessibility + interaction contract (Pick-best-frame action)
Mounts in `app/renderer/src/features/ProducedShorts.tsx`, which already uses
`aria-label` on its container and per-item controls (`ProducedShorts.tsx:41/57-60`)
plus `aria-hidden` on decorative glyphs (`:63`); the new action MUST match and is
covered by vitest `thresholds:100`.

- **Action button.** A `<button type="button">` with a per-clip accessible name
  ("Pick the best thumbnail frame for <title>"), mirroring the existing
  `aria-label={`Play preview of ${title}`}` pattern (`ProducedShorts.tsx:60`).
  While the job runs it reflects `aria-busy`/disabled.
- **Thumbnail swap is announced.** When the chosen frame replaces the thumbnail,
  a polite live region announces the change ("Thumbnail updated to the frame at
  0:07") and the thumbnail `<img alt>` is updated, so a non-sighted user knows the
  swap happened (a silent `src` change is invisible to AT).
- **UX states (explicit):**
  - *Running* — `thumbnail.select` is a job: progress via existing `onProgress`
    (`rpc.ts:434`) in a polite live region; completion via `onJobDone`
    (`rpc.ts:436`).
  - *Degrade-to-midpoint (NOT silent).* §3.1/§3.5 fall back to the midpoint frame
    when there is no consented cloud + no local weights. The user MUST be told:
    surface a visible + announced note ("No vision model available — used the
    middle frame") rather than silently swapping a possibly-worse thumbnail. This
    keeps "never blocks export" honest without hiding *why* the result is generic.
  - *Error* — `role="alert"` if the job fails for a non-degrade reason.

---

## 4. Capability Gaps (explicit — no fabrication)

| ID | Gap | Impact | Resolution path |
|----|-----|--------|-----------------|
| **G-A1** | The provider seam exposes `chat`/`complete` only (`provider.py:212`), NOT an `embeddings` call. Semantic Index needs `/v1/embeddings`. | Cannot embed without a new method. | Add `Embedder.embed()` (OpenAI-`/v1/embeddings`-compatible, reuses the same stdlib-urllib transport `provider.py:91`) + a local backstop; OR call llama.cpp/Ollama `/v1/embeddings` through a thin new provider class. PLAN decides extend-`provider.py` vs new `models/embedder.py`. |
| **G-A2** | The catalog's task tiers (`models/catalog.py`, via `presets._FUNCTION_TASK_NAMES` `presets.py:225`) have no `EMBED` task; `presets.FUNCTIONS` lacks `"index"`. | Embeddings can't be routed/ranked as a first-class function. | Add the `"index"` function + an `EMBED` catalog task (or reuse the text tier for MVP). Small, additive. |
| **G-A3** | No embedding-model **asset** is registered (`assets/manifest.py` day-1 = whisper + qwen only, `:181/:188`). | A local embeddings model isn't installed/pinned. | Register an `AssetEntry` for a small local embedder (e.g. an ONNX/GGUF sentence model) via `register_asset`. Could also rely on Ollama/LM-Studio embeddings if detected (`local_detect`). |
| **G-A4** | No vector index / ANN; cosine is O(n·dim) linear. | Fine for one video; would not scale to cross-video corpora. | MVP = linear cosine (reuse `diarize.cosine_similarity` `:75`). FAISS/ANN is a post-MVP refinement, OUT of scope. |
| **G-A5** (privacy-critical) | **Transcript-text egress is NOT consent-gated in the substrate.** `consent.text_consent_granted` (`consent.py:85`) + `DATA_TYPE_TEXT` (`consent.py:37`) exist but are dead code (no caller in `sidecar/` outside their own module + tests); there is no `require_text_consent` and no `_text_consented_settings` pool filter (only `_frame_consented_vision_settings` `handlers.py:597` exists). The current text functions (translation/select/subtitles) egress on the *budget* ack alone. | Without a new seam, `index.build`/`index.search` would send a full transcript to any configured cloud provider with no privacy gate, breaking the "default install never egresses transcript text" promise (and a 429 could rotate it to an unconsented provider). | **BUILD MUST add the seam BEFORE any cloud `index` route ships:** (1) `consent.require_text_consent(settings, provider)` mirroring `require_frame_consent` (`consent.py:90`); (2) a `Services._text_consented_settings(settings)` pool filter mirroring `_frame_consented_vision_settings` (`handlers.py:597/620`), applied at `index` pool build so non-text-consented entries are dropped per-entry (rotation-safe). The same seam SHOULD be wired into the existing text functions in a follow-up (out of this bundle's scope, but flagged). **Alternative if descoped:** ship `index` local-only (privacy route) and document that cloud `index` is blocked until G-A5 lands — do NOT claim inherited text-consent. |
| **G-C1** | The vision seam scores **clips** (`SmolVlmBackend.rank_clips` `smolvlm2.py:96`), not single frames for "best thumbnail". | Need a frame-level scorer + prompt. | NEW `best_frame.py` (prompt + parse, PURE) + a `score_frames` seam; can reuse `CloudVlmBackend` by treating each frame as a 1-frame clip. |
| **G-C2** | No JPEG/PNG **write** of a chosen frame (the loader decodes; the encoder only base64s for egress). | Need to persist the picked frame as a thumbnail file. | Add a small cv2 `imwrite` at the (already coverage-excluded) native seam, mirroring `_default_frame_encoder` `smolvlm2.py:239`; output via `shorts.thumbnail_path`. |
| **G-B1** | `advise_for_hardware` returns capability verdicts + a `recommended_preset`, but NOT an actionable download/route/ASR plan. | Recommender must compose, not invent. | NEW PURE `recommender.py` composing existing report + present-map + detected-local into `{preset,routing,asrEngine,downloads,rationale}`. No new probe. |
| **G-B2** | The asset-download trigger lives in `assets/rpc.py` (not re-verified line-by-line here). | Apply's download step depends on that surface. | PLAN must confirm the existing assets download RPC signature before wiring the recommender's "download missing" Apply action; recommender only *proposes* downloads. |
| **G-GEN** | Build gates are strict: sidecar `pytest --cov-branch --cov-fail-under=100` + renderer vitest `thresholds:100` + ruff/oxlint/biome/basedpyright/tsc. | Every NEW pure module + handler + renderer file must hit 100%. | The PURE-core + injected-seam pattern used everywhere here (frames/vectors/reports injected; cv2/torch/sockets behind `# pragma`-excluded prod seams) is exactly what keeps coverage at 100 — follow it. |

---

## 5. Cross-cutting design rules (inherited, restated)

- **No second AI path.** Every AI call (embed, frame-score) rides
  `plan_ai_job`/`run_ai_job` and is registered exactly once in `register_all`.
- **PURE core + injected seam** per existing feature modules (`smolvlm2.py`,
  `presets.py`, `system_advisor.py`): heavy deps (cv2/torch/sockets) live behind
  injectable seams defaulted to lazy `# pragma`-excluded impls; tests drive fakes.
- **Consent + budget are non-bypassable** — frame consent (per-entry,
  rotation-safe) for best-frame is ALREADY enforced; text consent for embeddings
  is a **NEW seam this bundle introduces** (`require_text_consent` +
  `_text_consented_settings` pool filter — G-A5; today `text_consent_granted` is
  dead code, so do NOT treat text-consent as inherited); `confirmCloudBudget` ack
  for any egress is already enforced.
- **Local-first defaults** — privacy preset routes all three to local; the cloud
  path is opt-in and previewed.
- **Reversibility** — index = a deletable sidecar; recommendation = read-only +
  one-click apply over existing mutation RPCs; best-frame = a swappable thumbnail
  file + metadata, original clip untouched.

---

## 6. Branching / build discipline (for the eventual BUILD)
- This bundle works on its OWN branch off `origin/main`.
- BUILD gates (blocking, never `--no-verify`, never `git add -A`): sidecar
  `pytest --cov-branch --cov-fail-under=100`; renderer `vitest` `thresholds:100`;
  `ruff` / `oxlint` / `biome` / `basedpyright` / `tsc`.
- Suggested work-unit order (detail in PLAN.md): Recommender (B) first
  (highest reuse, lowest gap) → Best-Frame (C) → Semantic Index (A, carries the
  embedder gap G-A1/G-A3).
