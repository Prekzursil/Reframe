# Reframe "Intelligence" Bundle — PLAN

> Status: PLAN (docs only — no feature code in this branch).
> Branch: `feat/intelligence-design` off `origin/main`. BUILD lands on its OWN branch off `origin/main`.
> Companion to `docs/plans/intelligence/DESIGN.md` (commit `2409de0`, blockers resolved `a2eeb67`).
> Every WU is grounded in real code (file:line). Capability gaps are named, not assumed.

This PLAN decomposes the three DESIGN capabilities into work units (WUs), each
with: goal · files touched · test strategy (fakes at the ffmpeg/model/socket/OCR
seams) · **falsifiable** acceptance criteria · explicit per-WU gate commands. A
dependency graph and parallelism notes follow.

---

## 0. Ground truth verified at PLAN time (resolving the DESIGN's "confirm in PLAN" items)

These were re-verified against the working tree on this branch so WUs build on facts, not assumptions:

| Item | DESIGN gap | PLAN finding (file:line) |
|------|-----------|--------------------------|
| Assets download RPC signature | **G-B2** | `assets.ensure({names:[str]}) → {jobId}` is a **long job** (`assets/rpc.py:40-63` `make_ensure_handler`; validates `names` non-empty str array, rejects unknown via `manifest.get_asset`). Apply's "download missing" step calls `assets.ensure({names:[assetName,...]})`. `assets.list`/`assets.cancel` also exist (`rpc.py:97-99`). |
| Text-consent seam | **G-A5** | `consent.text_consent_granted` (`consent.py:85`) + `DATA_TYPE_TEXT` (`consent.py:37`) exist; **NO** `require_text_consent`, **NO** `_text_consented_settings` pool filter. Only `require_frame_consent` (`consent.py:90`) + `_frame_consented_vision_settings` (`handlers.py:597-623`, per-entry, rotation-safe) exist. Seam is genuinely NEW. |
| Frame-consent filter pattern to mirror | **G-A5** | `_frame_consented_vision_settings` (`handlers.py:597-623`) filters `settings["providers"]` to frame-consented entries via `consent.frame_consent_granted`, returns a NEW dict (pure). The text filter mirrors this exactly. |
| Provider transport for embeddings | **G-A1** | `provider.py` uses **stdlib urllib only** (`provider.py:35-36,91`), POST `{base_url}/v1/chat/completions` (`:20`); GET `/models` used by local detect (`:73-74`). No `embed`. New embedder reuses `_urllib_request_json` shape, POST `/v1/embeddings`. |
| Vision frame seams to reuse | **G-C1/G-C2** | `_default_clip_frame_loader` (`smolvlm2.py:338`, cv2, `FRAMES_PER_CLIP=8` `:60`), `_default_frame_encoder` (`:239`, `# pragma: no cover` prod seam), `rank_clips` (`:96`), `parse_rerank_order` (`:145`). No frame `imwrite` exists → G-C2 adds one pragma-excluded seam. |
| Thumbnail write target | **G-C2** | `shorts.thumbnail_path(clip_path) → Path` (`shorts.py:102`); `shorts.read_metadata` (`:168`). No `write_metadata` for `thumbnailFrameSec` yet → WU-C adds metadata write. |
| Function routing + task tiers | **G-A2** | `FUNCTIONS=("select","subtitles","translation","vision","editPlan")` (`presets.py:59`); `_REQUIRED_CAPABILITY` defaults "text", vision="vision" (`presets.py:68-69`); `_FUNCTION_TASK_NAMES` maps each function→catalog `Task` (`presets.py:225-231`); `_function_prefer` reads `routing.perFunction[fn].provider` (`handlers.py:553-573`). Adding `"index"` requires a row in all three. |
| Feature register pattern | — | Feature modules expose `register(*, ..., register_fn=None) -> Service`; `register_fn` defaults to `protocol.register`, tests inject a fake (e.g. `shorts.py:463`, `diarize.py:374`). `register_all` (`handlers.py:1982`) is the ONE call site. New modules follow this. |
| Job-envelope wiring | — | `_run_ai_job` (`handlers.py:1617`) is the one place a handler plans+runs+budget-gates an envelope; `plan_ai_job_envelope` (`:1601`). Custom `work` body = `AiWork=Callable[[ctx,AiJob,provider],dict]` (`ai_job.py:261`, driven `:311`). |
| Gate commands (CI = ground truth) | **G-GEN** | From `.github/workflows/quality.yml`: pre-commit (ruff+oxlint+biome+gitleaks) `pre-commit run --all-files`; tsc `cd app && npx tsc --noEmit`; basedpyright `basedpyright`; pytest `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`; vitest `cd app && npx vitest run --coverage` (thresholds:100 in vitest config); opengrep SAST (gate:4); **osv-scanner deps (gate:6 — `osv-scanner scan source --config=osv-scanner.toml --no-resolve --lockfile=app/package-lock.json --lockfile=app/render-cli/package-lock.json --lockfile=sidecar/requirements.lock.txt`, `quality.yml:110-117`)**. |

**Renderer note:** the renderer sources live at `app/renderer/src/...` but the
Node toolchain root is `app/` (CI runs `npm ci`, `npx tsc`, `npx vitest` with
`working-directory: app`). All renderer gate commands below run from `app/`.

---

## 1. Work-unit catalog

WU order follows DESIGN §6: **B (Recommender, highest reuse) → C (Best-Frame) →
A (Semantic Index, carries the embedder gaps)**. Each capability is split into a
sidecar-pure WU, a handler/RPC WU, and a renderer WU so they can be reviewed (and
some, parallelised) independently. Every WU is sized to hit 100% line+branch on
its own files.

Legend for acceptance: **AC** = falsifiable acceptance criterion (a test could
fail it). Each WU's gate block is the BLOCKING set that must pass before COMMIT.

---

### WU-0 — Branch + scaffolding (no feature logic)
**Goal.** Cut the BUILD branch off `origin/main`; add empty test-discovered
module stubs only if needed to keep the tree importable. No behavior.
**Files.** (branch only) — `git switch -c feat/intelligence` off `origin/main`.
No source files created here (avoids dead-code coverage failures).
**Test strategy.** None (no code). Verify the existing suite still green on the
fresh branch so later WUs start from a known-100% baseline.
**AC.**
- (a) Branch `feat/intelligence` exists off current `origin/main` HEAD.
- (b) `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` passes on the untouched tree (baseline proof).
- (c) `cd app && npx vitest run --coverage` passes untouched.
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` ; `cd app && npx vitest run --coverage`.
**Dep.** none.

---

## Capability B — Device-Aware Auto-Recommender (do first; ~80% reuse, lowest gap)

### WU-B1 — `features/recommender.py` (PURE core) — resolves **G-B1**
**Goal.** A pure function turning the EXISTING advisor output into an actionable
plan. No probe, no GPU, no socket.
**Files (NEW).** `sidecar/media_studio/features/recommender.py`,
`sidecar/tests/test_recommender.py`.
**Signature.** `recommend(report, present, detected_local, asr_engines, *, offline, commercial=False) -> Recommendation` where
`Recommendation = {preset, routing:{perFunction:{fn:{provider}}}, asrEngine, downloads:[{assetName,label,sizeMb,reason}], rationale:[str]}`.
**Reuse (inputs, injected — not called here).** Shapes from `advise_for_hardware`
(`system_advisor.py:681`) + `recommended_preset` (`:484`), `_models_present_map`
(`handlers.py:1305`), `detect_local_servers` (`local_detect.py:107`),
`asr.engines` (`handlers.py:1175`). All passed in as plain dicts/lists.
**Decision logic (testable, deterministic).** preset = report's
`recommended_preset`; for each function pick a route preferring (1) a detected
local server, else (2) local backstop on privacy, else (3) the preset's catalog
route; `downloads` = runnable-but-missing components (present-map ∧ advisor
"runnable") minus anything covered by a detected local server; `asrEngine` = best
available from `asr_engines`; `rationale` = one human string per decision;
`offline=True` drops all download-requiring + cloud proposals.
**Test strategy.** Pure: feed fake report/present/detected/asr dicts. Cover every
branch — privacy vs balanced vs bestFreeCloud preset; component runnable vs not;
local server present vs absent; offline True/False; commercial True/False;
already-installed (no download) vs missing; empty/malformed advisor report
(→ "could not detect", G-B1 fallback shape). No mocks of cv2/torch/sockets (none used).
**AC.**
- (a) Given a fake report with `recommended_preset="privacy"`, output `preset=="privacy"` and EVERY `routing.perFunction[fn].provider` is the local sentinel — FALSIFIABLE: a cloud provider in any slot fails.
- (b) Given a runnable-but-missing whisper component and `offline=False`, `downloads` contains exactly its `assetName`; with `offline=True` `downloads==[]`.
- (c) Given a detected Ollama server that serves the needed model, that function routes to the local server and its `assetName` is NOT in `downloads`.
- (d) Malformed/empty report → a typed "unavailable" Recommendation (empty downloads, `rationale` explains, no exception).
- (e) `recommender.py` hits 100% line+branch alone.
**Gate.** `cd sidecar && python -m pytest tests/test_recommender.py --cov=media_studio.features.recommender --cov-branch --cov-fail-under=100` ; then full-suite gate before COMMIT.
**Dep.** WU-0.

### WU-B2 — `system.recommend` handler + RPC registration
**Goal.** Thin handler composing the real probe/advisor/detect/asr seams and
`recommender.recommend`; register `system.recommend` in `register_all`.
**Files.** `sidecar/media_studio/handlers.py` (new `system_recommend` method +
`reg("system.recommend", ...)` inside `register_all` `:1982`),
`sidecar/tests/test_handlers_recommend.py` (or extend existing handler tests).
**Reuse.** Calls `system_probe`/`advise_for_hardware`/`_models_present_map`/
`detect_local_servers`/`asr.engines` (all existing) then `recommender.recommend`.
Direct-return (cheap; composes direct-return probes — DESIGN §2.3).
**Params.** `{commercial?:bool}` → `{recommendation:{...}}`.
**Test strategy.** Inject fakes for the probe/advisor/detect seams via the
Services constructor seams (mirroring how existing handler tests stub probes);
assert the handler forwards their outputs into `recommender.recommend` and returns
its result verbatim. Cover: happy path, `commercial` passthrough, a seam raising
(→ typed error), offline path forwarded.
**AC.**
- (a) `system.recommend` is in `register_all`'s registered method set — FALSIFIABLE via a registry-introspection test (mirrors existing register tests).
- (b) Handler passes `offline` from `offline.is_offline` and `commercial` from params straight into `recommender.recommend` (assert via spy).
- (c) Calling with no probe data available returns the G-B1 "unavailable" recommendation, NOT an exception.
- (d) Zero provider calls occur (it composes probes only) — FALSIFIABLE: a fake provider asserts it is never invoked.
- (e) handler + new lines 100% line+branch.
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
**Dep.** WU-B1.

### WU-B3 — Renderer recommendation card + Apply flow
**Goal.** "Recommended for your machine" card in `ModelsSystemPanel.tsx`; one-click
Apply via EXISTING mutation RPCs. No new mutation path.
**Files.** `app/renderer/src/panels/ModelsSystemPanel.tsx` (card + Apply),
`app/renderer/src/panels/ModelsSystemPanel.test.tsx` (new or extend),
`app/renderer/src/lib/rpc.ts` (add `Recommendation` interface + `system.recommend`
method signature).
**Apply wiring (reuse only).** `providers.applyPreset` (preset), per-function
deltas via `providers.setFunctionModel`, `settings.set({asrEngine})`, and
`assets.ensure({names:[...]})` for downloads (G-B2 confirmed §0).
**A11y (DESIGN §2.6, vitest thresholds:100 ⇒ each is test-asserted).**
`<section aria-labelledby>` + heading; rationale as `<ul>`; Apply `<button
type="button">` accessible name "Apply recommended settings"; `aria-busy` while
applying; polite live region announces outcome; loading / unavailable (G-B1) /
error (`role="alert"`) / already-optimal states all explicit.
**Test strategy.** Mock `rpc()` and `onProgress`/`onJobDone` (existing test idiom,
e.g. `ModelsSystemPanel`/`Assets.test.tsx`). Drive each UX state and assert the
exact ARIA attributes + that Apply calls `applyPreset`/`setFunctionModel`/
`settings.set`/`assets.ensure` with the recommended values. Cover the "already
optimal" no-op path and the unavailable path.
**AC.**
- (a) The card is queryable by its accessible heading; rationale renders as list items (count == rationale length) — FALSIFIABLE.
- (b) Clicking Apply with a recommendation containing a download issues exactly one `assets.ensure({names:[that asset]})` call (spy on `rpc`).
- (c) While Apply runs the button has `aria-busy="true"` and is disabled; on done a polite live region contains the outcome text.
- (d) Unavailable recommendation renders the announced "Could not detect your hardware" message, NOT a blank card; error path renders `role="alert"`.
- (e) Already-optimal renders Apply disabled with the reason as its accessible name.
- (f) Touched renderer files hit vitest thresholds:100.
**Gate.** `cd app && npx tsc --noEmit && npx vitest run --coverage` ; `pre-commit run --files app/renderer/src/panels/ModelsSystemPanel.tsx app/renderer/src/panels/ModelsSystemPanel.test.tsx app/renderer/src/lib/rpc.ts`.
**Dep.** WU-B2 (for the live method) — but the TSX/test can be written against a mocked `rpc` in parallel with B2 and only integration-verified after B2 merges.

---

## Capability C — AI Best-Frame Thumbnail (highest frame-seam reuse)

### WU-C1 — `features/best_frame.py` (PURE core) — resolves **G-C1**
**Goal.** Pure prompt-build + reply-parse + argmax/score shaping for picking the
best frame index. No cv2, no model — frames + replies injected.
**Files (NEW).** `sidecar/media_studio/features/best_frame.py`,
`sidecar/tests/test_best_frame.py`.
**Functions.** `build_select_prompt(n) -> str` (one multimodal instruction "which
of the N numbered frames is the best thumbnail and why"); `parse_best_index(reply,
n) -> int` (forgiving, clamps to `range(n)`, mirrors `parse_rerank_order`
`smolvlm2.py:145`); `shape_result(index, frame_times, scores) ->
{frameTimeSec, score}`.
**Test strategy.** Pure. Cover parse: valid "frame 3", out-of-range, no number
found (→ default 0), multiple numbers (take first/declared), n==1. Cover prompt
shape for n frames. Cover shape_result mapping index→time.
**AC.**
- (a) `parse_best_index("the best is frame 4", 8) == 3` (1-based reply → 0-based) — and `parse_best_index("garbage", 8) == 0` (deterministic fallback). FALSIFIABLE.
- (b) `parse_best_index` never returns an index outside `range(n)` for any string — property-style assertion over crafted inputs.
- (c) `shape_result` maps the chosen index to the matching `frameTimeSec` from the injected `frame_times`.
- (d) 100% line+branch on `best_frame.py`.
**Gate.** `cd sidecar && python -m pytest tests/test_best_frame.py --cov=media_studio.features.best_frame --cov-branch --cov-fail-under=100` ; full suite before COMMIT.
**Dep.** WU-0.

### WU-C2 — Frame scorer seam + frame `imwrite` seam — resolves **G-C1/G-C2**
**Goal.** A `score_frames(frames, prompt) -> list[float]` backend seam (reusing
`CloudVlmBackend` by treating each frame as a 1-frame "clip") and a
pragma-excluded `_default_thumbnail_writer(frame, path)` cv2 `imwrite` seam.
**Files.** extend `sidecar/media_studio/features/best_frame.py` (scorer dispatch +
writer seam injection point), `sidecar/tests/test_best_frame.py`.
**Reuse.** `CloudVlmBackend._image_part` (`smolvlm2.py:288`), `rank_clips`
(`:96`), `_default_frame_encoder` (`:239`). The cv2 `imwrite` mirrors
`_default_frame_encoder`'s `# pragma: no cover - prod seam` (G-C2; `smolvlm2.py:239`).
**Test strategy.** Inject a fake scorer returning known per-frame scores and a
fake writer recording its `(frame,path)` call — argmax selection + write target
are asserted against fakes; the real cv2 `imwrite` is the only pragma-excluded
line (mirrors the established pattern, keeps 100%).
**AC.**
- (a) Given injected scores `[0.1,0.9,0.3]`, the picker selects index 1 and calls the (fake) writer with `thumbnail_path(clip)` — FALSIFIABLE.
- (b) The real cv2 writer is the ONLY `# pragma: no cover` line added; everything else is covered (verified by the 100% gate with that single pragma).
- (c) 100% line+branch on `best_frame.py` (incl. the new scorer dispatch).
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
**Dep.** WU-C1.

### WU-C3 — `thumbnail.select` job handler + thumbnail metadata write
**Goal.** Register `thumbnail.select` as a custom `work`-body AI job through
`_run_ai_job`; resolve clip span; sample frames via the existing loader; score;
write the JPEG/PNG via `shorts.thumbnail_path`; record `thumbnailFrameSec`.
**Files.** `sidecar/media_studio/handlers.py` (new `thumbnail_select` method +
`reg("thumbnail.select", ...)` in `register_all`), `sidecar/media_studio/features/
shorts.py` (add `write_metadata`/`thumbnailFrameSec` if absent — verified absent §0),
`sidecar/tests/test_handlers_thumbnail.py`, `sidecar/tests/test_shorts.py` (extend).
**Scope note — `settings.autoThumbnail` (DESIGN §3.4).** DESIGN names an optional
`settings.autoThumbnail` (bool) to auto-run best-frame at the end of
`shortmaker.export`, **default off in MVP**. This bundle delivers ONLY the explicit
per-clip `thumbnail.select` action (handler here + the WU-C4 button); the
auto-on-export wiring is **explicitly OUT of this MVP bundle** (the setting would
default off anyway, so it ships no user-visible behavior). Flagged follow-up: add
the `settings.autoThumbnail` default + an opt-in hook in `shortmaker.export` to
call `thumbnail.select` post-export. No PLAN WU implements it.
**Reuse (the EXACT decision tree, DESIGN §3.2).** `_resolve_vlm_reranker`-style
resolver (`handlers.py:670`): frame-consented cloud pool first
(`_vision_pool(_frame_consented_vision_settings(...))` `:597/:624`) → local weights
→ midpoint-frame fallback (off). Per-function routing `"vision"` (`presets.py:59`)
unchanged. Envelope via `_run_ai_job` (`:1617`) for cancel/degrade/budget
(`Budget.egressKinds.frames` `ai_job.py:159`); cache key includes clip span + frame
params. Clip span from selection cache (`candidates` `handlers.py:1404`) or explicit
`{path,start,end}`. Frame loader `_default_clip_frame_loader` (`smolvlm2.py:338`).
**Test strategy.** Inject a fake frame-loader (returns N synthetic frames), a fake
scorer, a fake writer, and fake settings (consent on/off). Cover: cloud path
(frame-consented), local-weights path, **degrade-to-midpoint** path (no consent +
no weights → deterministic midpoint, zero egress, job still succeeds), cache hit
(scorer NOT called), cancel mid-job, candidate-id resolution vs explicit span,
unconsented provider DROPPED at pool build (rotation-safe — assert a non-consented
entry never receives a frame).
**AC.**
- (a) `thumbnail.select` is registered in `register_all` — FALSIFIABLE via registry introspection.
- (b) With NO frame consent and NO local weights, the job's done payload `frameTimeSec` equals the clip midpoint and the (fake) scorer is NEVER called — FALSIFIABLE (degrade-to-midpoint, zero egress).
- (c) With one consented + one NON-consented cloud entry, the non-consented entry never receives any frame (per-entry pool filter) — FALSIFIABLE via a spy.
- (d) A second identical call is a cache hit (scorer not invoked twice).
- (e) Done payload shape == `{frameTimeSec, thumbnailPath, score}`; `shorts` metadata records `thumbnailFrameSec`.
- (f) Cancel before scoring leaves no thumbnail written.
- (g) handler + shorts changes 100% line+branch (cv2 imwrite the single pragma from WU-C2).
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
**Dep.** WU-C2.

### WU-C4 — Renderer "Pick best frame" action + thumbnail swap
**Goal.** Per-clip "Pick best frame" button in `ProducedShorts.tsx`; announce the
swap; surface the degrade-to-midpoint note (NOT silent).
**Files.** `app/renderer/src/features/ProducedShorts.tsx`,
`app/renderer/src/features/ProducedShorts.test.tsx` (extend),
`app/renderer/src/lib/rpc.ts` (`thumbnail.select` signature + `BestFrame` result type).
**A11y (DESIGN §3.6).** `<button type="button">` accessible name "Pick the best
thumbnail frame for <title>" (mirrors `ProducedShorts.tsx:60` `aria-label`);
`aria-busy`/disabled while the job runs; polite live region announces "Thumbnail
updated to the frame at 0:07" and updates `<img alt>`; degrade note "No vision
model available — used the middle frame" is visible AND announced; error
`role="alert"`. Job progress via existing `onProgress` (`rpc.ts:434`), completion
via `onJobDone` (`:436`).
**Test strategy.** Mock `rpc`/`onProgress`/`onJobDone` (existing
`ProducedShorts.test.tsx` idiom). Drive: running state (aria-busy), success swap
(img src + alt + live announce), degrade-to-midpoint note rendered+announced,
error (`role="alert"`).
**AC.**
- (a) The button has the per-clip accessible name including the title — FALSIFIABLE.
- (b) On job done, the thumbnail `<img>` `src` updates AND a polite live region contains the "frame at <time>" text.
- (c) A degrade-to-midpoint done payload renders the visible+announced midpoint note (NOT a silent swap).
- (d) Touched renderer files hit vitest thresholds:100.
**Gate.** `cd app && npx tsc --noEmit && npx vitest run --coverage` ; `pre-commit run --files app/renderer/src/features/ProducedShorts.tsx app/renderer/src/features/ProducedShorts.test.tsx app/renderer/src/lib/rpc.ts`.
**Dep.** WU-C3 (live method); TSX/test writable in parallel against mocked `rpc`.

---

## Capability A — Semantic Index (carries the embedder gaps)

### WU-A1 — Text-consent seam — resolves **G-A5** (privacy-critical, do BEFORE any cloud index route)
**Goal.** Add the missing text-consent gate so transcript text cannot egress to a
non-consented provider — the text analog of the frame path.
**Files.** `sidecar/media_studio/models/consent.py` (new `require_text_consent`),
`sidecar/media_studio/handlers.py` (new `_text_consented_settings` pool filter),
`sidecar/tests/test_consent.py` (extend), `sidecar/tests/test_handlers_consent.py`
(extend).
**Reuse (mirror exactly).** `require_frame_consent` (`consent.py:90`) →
`require_text_consent(settings, provider)` raising the same typed `ConsentError`
using `text_consent_granted` (`consent.py:85`) + `DATA_TYPE_TEXT` (`consent.py:37`).
`_frame_consented_vision_settings` (`handlers.py:597-623`) →
`_text_consented_settings(settings)` filtering `settings["providers"]` per-entry
via `consent.text_consent_granted`, returning a NEW dict (pure), so a 429 failover
can never rotate transcript text onto an unconsented provider.
**Scope note.** Wiring this seam into the EXISTING text functions
(translation/select/subtitles) is explicitly OUT of this bundle (DESIGN §4 G-A5)
— this WU introduces the seam and uses it ONLY for `index`. Flag the follow-up.
**Test strategy.** Pure/handler tests with fake settings: consent granted/denied;
provider id resolution (`provider`/`id`/`cloud` fallback, mirror frame filter);
empty/malformed `providers`; the per-entry drop (mixed consented/unconsented list
→ only consented kept); original settings never mutated.
**AC.**
- (a) `require_text_consent` raises `ConsentError` for a non-text-consented provider and returns `None` when granted — FALSIFIABLE.
- (b) `_text_consented_settings` drops a non-text-consented entry from a mixed providers list while keeping the consented one; original dict unchanged.
- (c) Local-backstop (no key) entries are unaffected (never egress) — matches frame-filter invariant.
- (d) 100% line+branch on the new lines.
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
**Dep.** WU-0. (Independent of B and C — parallelisable.)

### WU-A2 — Embedder seam — resolves **G-A1** (+ feeds G-A3)
**Goal.** `Embedder.embed(texts) -> list[list[float]]` Protocol with an
OpenAI-`/v1/embeddings`-compatible impl (stdlib urllib, local backstop last).
**Files.** `sidecar/media_studio/models/embedder.py` (NEW; PLAN picks NEW module
over extending `provider.py` to keep the chat transport untouched),
`sidecar/tests/test_embedder.py`.
**Reuse.** The stdlib urllib transport shape from `provider.py:91`
(`_urllib_request_json`) — POST `{base_url}/v1/embeddings`; injectable transport
so tests never open a socket (mirrors `provider.py:7` "wrapped behind an
injectable transport"). Local backstop = a deterministic local embedder seam.
**Test strategy.** Inject a fake transport returning a canned `/v1/embeddings`
JSON; assert request body shape (`{input:[...], model}`), response parse
(`data[].embedding`), batch handling, error mapping (HTTP error → typed),
empty-input guard. The one real socket line is `# pragma: no cover` (mirrors
provider transport).
**AC.**
- (a) `embed(["a","b"])` issues ONE POST to `/v1/embeddings` with `input==["a","b"]` (fake transport spy) and returns the parsed `data[].embedding` vectors — FALSIFIABLE.
- (b) Empty input returns `[]` without a transport call.
- (c) HTTP error → typed error (not a raw urllib exception).
- (d) 100% line+branch (single socket pragma).
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
**Dep.** WU-0. (Parallelisable with WU-A1.)

### WU-A3 — `"index"` function + task-tier mapping — resolves **G-A2** (+ G-A3 asset)
**Goal.** Make embeddings a first-class routable function and pin a local
embedding asset.

**DECISION (sizing the blast radius — this WU takes the smaller, buildable path).**
The catalog `Task` enum has exactly five members (`catalog.py:36-40`:
`MOMENT_FIND/CAPTION/TRANSLATION/VISION/EDIT_PLAN`) and `_tiers(t1..t5)` is a
**positional 5-arg** builder (`catalog.py:135-149`) called by **all 13** frozen
seed rows (`per_task_tier=_tiers(...)` ×13, `catalog.py`). The adapter resolves
each function's task with a **bracket** lookup `entry.per_task_tier[task]`
(`presets.py:252`, via `_catalog.Task[name]` `:273`) — NOT `.get` — so a brand-new
`Task.EMBED` would `KeyError` at `_AdaptedEntry.__init__` (`presets.py:252`) for
**every** row, breaking `apply_preset` for **all** presets, not just `index`.
Adding a real `EMBED` tier would therefore require: extend `Task` (`:36`), extend
`_tiers` to a 6th positional arg (`:135`), add an EMBED column + grade to **all 13**
seed rows, and update `recommended_for`/`order_by`/serialization
(`catalog.py:128,132,449`) + their tests. That is a multi-file catalog rewrite
disproportionate to an MVP routing seam. **PLAN therefore reuses an EXISTING text
task: `_FUNCTION_TASK_NAMES["index"] = "MOMENT_FIND"`** (the primary text-capable
task; every text-capable seed row already grades it, so the bracket lookup
resolves with zero catalog edits). This keeps `index` routable today; promoting it
to a dedicated `EMBED` tier (better embedding-specific ranking) is a flagged
post-MVP follow-up that owns the full catalog change above.

**Files.** `sidecar/media_studio/models/presets.py` (add `"index"` to `FUNCTIONS`
`:59`, `_REQUIRED_CAPABILITY["index"]="text"` `:68`, `_FUNCTION_TASK_NAMES["index"]
="MOMENT_FIND"` `:225` — an EXISTING `Task`, so no `catalog.py` change is needed),
`sidecar/media_studio/assets/manifest.py` (register a small local embedder
`AssetEntry` via `register_asset` `:134`, mirroring whisper/qwen `:181/:188`),
`sidecar/tests/test_presets.py`, `sidecar/tests/test_manifest.py` (extend each).
**NOT touched:** `catalog.py` (no new `Task`/`_tiers`/seed-row columns — see DECISION).
**Reuse.** `register_asset`/`get_asset` (`manifest.py:134/156`); the existing
`hf`/`download`/`env` installer machinery (no new installer type); the existing
`Task.MOMENT_FIND` grades already present on all 13 seed rows.
**Test strategy.** Assert `"index"` appears in `FUNCTIONS`, has required-capability
"text", maps to the `MOMENT_FIND` task; `apply_preset` produces an `index` route
for every preset (the bracket lookup at `presets.py:252` resolves because every
text-capable row already grades `MOMENT_FIND` — this is the AC-(b) falsifier);
the new asset is retrievable via `get_asset` with a pinned sha. All pure.
**AC.**
- (a) `presets.FUNCTIONS` contains `"index"` and `_FUNCTION_TASK_NAMES["index"]=="MOMENT_FIND"` (an existing `catalog.Task` member) — FALSIFIABLE.
- (b) `apply_preset` produces a `routing.perFunction["index"]` route for **every** preset with NO `KeyError` at `_AdaptedEntry.__init__` (`presets.py:252`) — i.e. the chosen task resolves against all 13 seed rows' `per_task_tier` (local route under privacy). FALSIFIABLE: a missing/foreign `Task` raises and fails this.
- (c) `get_asset(<embedder name>)` returns a registered `AssetEntry` with a non-empty sha + installer.
- (d) 100% line+branch on the changed modules.
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
**Dep.** WU-0. (Parallelisable with WU-A1/A2.)
**Follow-up (flagged, out of bundle).** Dedicated `EMBED` task tier: extend
`Task` (`catalog.py:36`), `_tiers` → 6th arg (`:135`), add an EMBED grade column to
all 13 seed rows + update `best_grade_score`/`grade_for`/serialization
(`:128,132,449`) and tests. Improves embedding-specific ranking; not required for MVP routing.

### WU-A4 — `features/semantic_index.py` (PURE core)
**Goal.** Build the segment corpus from a `Transcript`; cosine top-K against a
query vector; shape hits. No model; vectors injected.
**Files (NEW).** `sidecar/media_studio/features/semantic_index.py`,
`sidecar/tests/test_semantic_index.py`.
**Functions.** `build_corpus(transcript) -> list[str]` (segment texts, from
`Transcript.segments` `transcribe.py:6`); `search(query_vec, segment_vecs,
segments, top_k) -> [{segmentIndex,start,end,text,score}]` using EXISTING
`diarize.cosine_similarity` (`diarize.py:75`, length-guarded).
**Reuse.** `cosine_similarity` (`diarize.py:75`) directly — no re-derived math.
**Test strategy.** Pure: fake transcript + fake segment vectors + fake query vec;
assert ordering by cosine desc, top-K truncation, tie handling, empty transcript,
top_k > segment count, dimension-mismatch guard (delegated to cosine_similarity).
**AC.**
- (a) Given orthogonal-ish fake vectors, `search` returns segments ordered by descending cosine and truncated to `top_k` — FALSIFIABLE.
- (b) Empty transcript → `[]`; `top_k` larger than corpus → all segments, no error.
- (c) Each hit carries the correct `segmentIndex/start/end/text` from the source segment.
- (d) 100% line+branch on `semantic_index.py`.
**Gate.** `cd sidecar && python -m pytest tests/test_semantic_index.py --cov=media_studio.features.semantic_index --cov-branch --cov-fail-under=100` ; full suite before COMMIT.
**Dep.** WU-0 (uses existing `cosine_similarity`). Logic-independent of A1/A2/A3.

### WU-A5 — `index.*` handlers + RPC registration + sidecar persistence
**Goal.** `index.build` (long job, custom `work` body), `index.search`,
`index.status`; persist vectors per-video; gate cloud egress by the NEW
text-consent seam + existing budget ack.
**Files.** `sidecar/media_studio/handlers.py` (three handler methods + their
`reg(...)` lines in `register_all` `:1982`; persistence read/write helpers),
`sidecar/tests/test_handlers_index.py`.
**Decision (resolving DESIGN §1.4 deferral).** Vectors persist to a **sidecar
file** `projects/<videoId>.index.json` (`{model,dim,builtAt,vectors:[...]}`), NOT
the manifest body, to keep the manifest small.
**Decision (resolving DESIGN §1.3 "direct-return vs job — decide in PLAN").**
`index.build` is a **long job** (custom `work` body via `_run_ai_job`
`handlers.py:1617`; `done.result = {segmentCount, model, builtAt, dim}`).
`index.search` and `index.status` are **direct-return** RPCs (no job/envelope):
`index.search` makes ONE short query-embedding call then a pure cosine over
already-persisted vectors, so an inline cloud round-trip is acceptable and a job
envelope would add latency for no cancel/degrade benefit; `index.status` is a pure
file read. **Because `index.search`'s inline query embedding is itself a cloud
egress when routed to cloud (DESIGN §1.3/§1.5), the direct-return path is NOT a
silent provider call: it builds its embedder pool through `_text_consented_settings`
(WU-A1) and routes the call through `_enforce_cloud_budget_ack`
(`handlers.py:1672`) — the SAME text-consent + budget gate as `index.build`.**
**Reuse.** `_run_ai_job` (`handlers.py:1617`) for `index.build`'s embedding call
(`capability="text"`, custom `work` body); `_text_consented_settings` (WU-A1) at
`index` pool build so transcript text drops non-consented entries per-entry;
`_enforce_cloud_budget_ack` (`handlers.py:1672`) for the budget gate — applied to
the `index.build` job AND to the direct-return `index.search` query embedding (per
the §1.3 decision above); `_text_consented_settings` (WU-A1) at the `index.search`
pool build too, so the inline query egress also drops non-consented entries
per-entry (rotation-safe); `_ai_cache` (`handlers.py:1570`) for the query
embedding; `_function_prefer("index")` (`:553`) for routing; transcript from
`project.data["transcript"]`
(`handlers.py:1069`); `semantic_index.search` (WU-A4) + `embedder.embed` (WU-A2).
`index.search` over an unbuilt index returns a typed INVALID_PARAMS "build the
index first" mirroring `subtitles_generate` (`handlers.py:733`).
**Test strategy.** Inject fake embedder + fake job registry + fake settings
(consent on/off; cloud vs local route). Cover: build job happy path (vectors
persisted, status reflects built), build with cloud route + text-consent denied
→ non-consented entry DROPPED (rotation-safe), build with budget-ack required,
search built (top-K hits), **search with a cloud `index` route + text-consent
DENIED → the query text never reaches the non-consented provider (per-entry filter
on the search path)**, **search with a cloud route + `confirmCloudBudget` on and no
ack → typed budget-ack error before any egress / with ack → proceeds**, search
unbuilt (typed "build first"), search query embedding is a cache hit on repeat,
status before/after build, idempotent rebuild overwrites. Persistence uses tmp_path
(no real network).
**AC.**
- (a) `index.build`/`index.search`/`index.status` all registered in `register_all` — FALSIFIABLE via registry introspection.
- (b) After `index.build`, `index.status` returns `{built:true, segmentCount==len(segments), model, builtAt, dim}` and the sidecar JSON exists — FALSIFIABLE.
- (c) On the `index.build` path: with a cloud `index` route and text consent DENIED for a provider, that provider never receives transcript text (per-entry filter from WU-A1) — FALSIFIABLE via spy.
- (c2) **On the `index.search` path (privacy-critical, G-A5): with a cloud `index` route and text consent DENIED for a provider, the inline query-embedding egress never delivers the query text to that non-consented provider** — FALSIFIABLE via a spy on the (fake) embedder/transport asserting the non-consented entry receives no call. (Mirrors (c) for the search egress DESIGN §1.3/§1.5 elevated to a named safety requirement.)
- (c3) **On the `index.search` path: when `confirmCloudBudget` is on and the call lacks the `confirmCloudBudget`/`confirmBudget` ack, the query embedding does NOT egress and a typed budget-ack error is raised (via `_enforce_cloud_budget_ack` `handlers.py:1672`); with the ack present the search proceeds** — FALSIFIABLE: a fake provider asserts zero calls in the unacked case, ≥1 in the acked case.
- (d) `index.search` on an unbuilt video returns the typed "build the index first" error (not an empty list, not a crash).
- (e) A repeated identical `index.search` query embedding is served from cache (embedder embed-call count does not increase).
- (f) Rebuild overwrites the sidecar (idempotent), `builtAt` advances.
- (g) handler + new lines 100% line+branch.
**Gate.** `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100`.
**Dep.** WU-A1, WU-A2, WU-A3, WU-A4.

### WU-A6 — Renderer `SemanticSearch.tsx` + Workspace mount
**Goal.** Search box + keyboard-operable results in `Workspace.tsx`; build/building/
empty/error states; seek-on-activate.
**Files.** `app/renderer/src/features/SemanticSearch.tsx` (NEW),
`app/renderer/src/features/SemanticSearch.test.tsx` (NEW),
`app/renderer/src/views/Workspace.tsx` (mount), `app/renderer/src/lib/rpc.ts`
(`IndexHit`/`IndexStatus` types + the three method signatures).
**A11y (DESIGN §1.6).** Labelled search input (`<label htmlFor=
"semantic-search-query">` or `aria-label`), submit on Enter + `type="submit"`
button named "Search"; results = real focusable controls (`<button>` rows in
`<ul>` or `role="listbox"/option`), Enter/Space/click seeks the player + moves
focus deliberately; each row's accessible name = timestamp + snippet; polite
`aria-live` announces "Searching…"/result count/"No matches"; build CTA when
`index.status.built===false`; building progress via `onProgress` (`rpc.ts:434`) +
`onJobDone` (`:436`); error `role="alert"` (mirror `Workspace.tsx:176`).
**Test strategy.** Mock `rpc`/`onProgress`/`onJobDone`. Drive every state: not
built (CTA + disabled box), building (progress + disabled), built+results
(keyboard activation seeks), empty result (announced "No matches"), error
(`role="alert"`), search-unbuilt fallback alert. Assert each ARIA attribute.
**AC.**
- (a) Results render as focusable buttons; pressing Enter on a hit calls the player seek with that hit's start — FALSIFIABLE (not a click-only div).
- (b) Empty result renders AND announces "No matches for '<query>'" via the live region (not a silent blank list).
- (c) `index.status.built===false` renders the "Build the search index" CTA and a disabled search box; clicking it calls `index.build`.
- (d) Building state shows the polite progress region; on `onJobDone` the box enables.
- (e) Touched renderer files hit vitest thresholds:100.
**Gate.** `cd app && npx tsc --noEmit && npx vitest run --coverage` ; `pre-commit run --files app/renderer/src/features/SemanticSearch.tsx app/renderer/src/features/SemanticSearch.test.tsx app/renderer/src/views/Workspace.tsx app/renderer/src/lib/rpc.ts`.
**Dep.** WU-A5 (live methods); TSX/test writable in parallel against mocked `rpc`.

---

## WU-FINAL — Full-bundle gate + docs
**Goal.** One pass of **every** BLOCKING gate across the whole bundle (all 6 CI
gate groups in `.github/workflows/quality.yml` — gate:1+5 lint/format/secrets,
gate:2 types, gate:3 tests+coverage, gate:4 SAST, gate:6 deps); update any
user-facing docs (no feature code).
**Test strategy.** Run the entire CI gate set locally (the §0 commands) green.
**AC.**
- (a) `pre-commit run --all-files` clean (gate:1 + gate:5 — ruff/oxlint/biome/gitleaks).
- (b) `cd app && npx tsc --noEmit` + `cd app/render-cli && npx tsc -p . --noEmit` clean (gate:2).
- (c) `basedpyright` clean (gate:2).
- (d) `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` passes (gate:3).
- (e) `cd app && npx vitest run --coverage` passes (thresholds:100) (gate:3).
- (f) `opengrep scan --config .quality/opengrep --error ... app sidecar` clean (gate:4).
- (g) **`osv-scanner scan source --config=osv-scanner.toml --no-resolve --lockfile=app/package-lock.json --lockfile=app/render-cli/package-lock.json --lockfile=sidecar/requirements.lock.txt` reports 0 actionable CVEs (gate:6 — `gate-deps osv-scanner`, `quality.yml:110-117`).** This bundle is docs-only on `feat/intelligence-design`; the BUILD branch adds NO new runtime dependency, so no lockfile changes are expected — but WU-FINAL still runs this gate to honor the "every BLOCKING gate" claim, and any incidental lockfile churn must pass it.
**Gate.** all of (a)-(g) (the full CI command set — all 6 gate groups). NEVER `--no-verify`; NEVER `git add -A` (stage only the WU's declared files; verify `git diff --cached --name-only` before each commit).
**Dep.** all WUs.

---

## 2. Dependency graph

```
WU-0 (branch + green baseline)
 ├─ B  ── WU-B1 (recommender PURE) ── WU-B2 (system.recommend handler) ── WU-B3 (renderer card)
 │
 ├─ C  ── WU-C1 (best_frame PURE) ── WU-C2 (scorer+imwrite seam) ── WU-C3 (thumbnail.select handler) ── WU-C4 (renderer action)
 │
 └─ A  ── WU-A1 (text-consent seam, G-A5) ─┐
          WU-A2 (embedder seam, G-A1) ─────┤
          WU-A3 ("index" fn + task map + asset)┤
          WU-A4 (semantic_index PURE) ──────┴── WU-A5 (index.* handlers + persistence) ── WU-A6 (renderer search)
                                                              ▲
                                          (A5 needs A1,A2,A3,A4)

ALL ── WU-FINAL (full-bundle gate + docs)
```

Critical path (longest): `WU-0 → WU-A1/A2/A3/A4 (parallel) → WU-A5 → WU-A6 → WU-FINAL`.

## 3. Parallelism notes

- **Three capability lanes (A, B, C) are independent** after WU-0 — different
  files, no shared mutable source except `handlers.py` (register_all) and
  `rpc.ts`. Run them as up to 3 parallel lanes.
- **Shared-file contention = `handlers.py` (`register_all`) and `rpc.ts`.** WU-B2,
  WU-C3, WU-A5 each add `reg(...)` lines; WU-B3, WU-C4, WU-A6 each add to `rpc.ts`.
  To avoid the known parallel-worktree index-contamination failure mode, EITHER
  run each lane in its own `git worktree` (isolated index) OR serialize the
  register_all / rpc.ts edits and use scoped `git add <files>` (never `git add -A`);
  verify `git diff --cached --name-only` before every commit.
- **Within Capability A, WU-A1/A2/A3/A4 are mutually independent** (consent.py /
  embedder.py / presets+manifest / semantic_index.py — disjoint files; WU-A3 does
  NOT touch catalog.py per its DECISION) and fan out 4-wide; they all converge at WU-A5.
- **Renderer WUs (B3, C4, A6) can be authored in parallel with their sidecar
  handler WUs** against a mocked `rpc`, then integration-verified once the handler
  lands. They share only `rpc.ts` (serialize that one file's edits).
- **Recommended schedule:** Wave-1 = WU-0; Wave-2 = {B1, C1, A1, A2, A3, A4}
  (6-wide); Wave-3 = {B2, C2, A4→done}; Wave-4 = {B3, C3, A5}; Wave-5 = {C4, A6};
  Wave-6 = WU-FINAL.

## 4. Per-WU gate command summary (BLOCKING, never `--no-verify`)

| Scope | Command (working dir) |
|-------|------------------------|
| Sidecar tests + 100% branch cov | `cd sidecar && python -m pytest --cov=media_studio --cov-branch --cov-fail-under=100` |
| Single-module fast cov (during dev) | `cd sidecar && python -m pytest tests/<wu_test>.py --cov=media_studio.<module> --cov-branch --cov-fail-under=100` |
| Renderer tests + thresholds:100 | `cd app && npx vitest run --coverage` |
| Renderer types | `cd app && npx tsc --noEmit` (+ `cd app/render-cli && npx tsc -p . --noEmit`) |
| Sidecar types | `basedpyright` |
| Lint/format/secrets (ruff+oxlint+biome+gitleaks) | `pre-commit run --files <changed files>` (full: `pre-commit run --all-files`) |
| SAST (gate:4) | `opengrep scan --config .quality/opengrep --error --exclude .venv --exclude node_modules --exclude dist --exclude out app sidecar` |
| Deps / CVEs (gate:6) | `osv-scanner scan source --config=osv-scanner.toml --no-resolve --lockfile=app/package-lock.json --lockfile=app/render-cli/package-lock.json --lockfile=sidecar/requirements.lock.txt` (run in WU-FINAL; docs-only bundle expects no lockfile changes) |

Every COMMIT runs the lane-relevant subset; WU-FINAL runs the full set. Stage only
the WU's declared files (`git add <paths>`); confirm `git diff --cached --name-only`
before committing; never `git add -A`; never `git push --force` without approval.
