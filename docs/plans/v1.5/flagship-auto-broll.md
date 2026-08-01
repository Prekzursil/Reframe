# Reframe v1.5 Flagship — Local Auto-B-Roll: Implementation Plan + Go/No-Go

**Scope:** ONE locked v1.5 flagship — *Local auto-B-roll* (auto-insert relevant B-roll clips/images UNDER the
speaker based on the transcript, using LOCAL assets + LOCAL relevance matching, fully offline).
**Type:** asset RETRIEVAL + compositing (NOT AI dubbing/lip-sync). The TTS/voice-clone licensing minefield does
**not** apply; the models are local text/image **embeddings**.
**Author:** research+design+plan subagent · **Date:** 2026-07-12 · **Repo:** `Prekzursil/Reframe` @ `origin/main`
(`7502e3a`, verified this session). **Mode:** RESEARCH + DESIGN + PLAN only — no repo modified.

---

## 0. VERDICT — `go-with-caveats`

**GO.** Auto-B-roll is a **REUSE-first** feature, not a new-model integration. The hard part — a local,
permissively-licensed, joint image+text embedding engine — **already ships on `origin/main`** and exposes the
exact cross-modal API this feature needs. Every load-bearing claim in the design was verified against source
(§2), every model license was verified against authoritative Hugging Face metadata (§3), and the 100%-branch +
real-functional test strategy is **the established pattern in this codebase** (§8), not an aspiration.

**Not `no-go-licensing`:** there are **five** independent permissive+local options (Apache-2.0 SigLIP-2 ×2,
Apache-2.0 Nomic ×2, MIT OpenCLIP) — the non-permissive models are avoidable, not the only viable ones.

**The caveats (why not a clean `go`) — all resolvable, none blocking:**
1. **CPU latency is unverified (confidence: MEDIUM).** SigLIP-2 so400m (~1.1B params) on CPU-only machines may
   be too slow for interactive use; needs a benchmark spike to lock the CPU-default tier. Mitigated: the index
   is a one-time batchable pass, plus a torch-free ONNX tier (Nomic) and the WSL2-GPU path.
2. **Threshold calibration is per-model and empirical.** SigLIP's sigmoid-loss cosine scale differs from
   softmax-CLIP; a min-similarity threshold tuned for so400m does **not** transfer to base/Nomic/OpenCLIP. Each
   tier needs its own calibrated threshold (a fixture + a small labelled probe set).
3. **Multi-window compositing is the real net-new engineering.** Generalizing the single-overlay `brandkit`
   pattern to N time-gated windows (+ B-roll *video* trim/setpts, not just stills) in one `filter_complex` is
   the highest-risk surface and the reason the real-ffmpeg e2e (WU-BR8) is mandatory.
4. **The license-allowlist CI gate is net-new.** Today licensing is enforced by a free-text `label` + human
   review (the #287 S3FD removal was manual). Automating it (WU-BR7) is the durable guard against a contributor
   swapping in a blocker.

---

## 1. Reviewer-facing summary (the falsifiable claims a fresh reviewer must check)

| # | Design claim | Verified? | Evidence (origin/main) |
|---|---|---|---|
| 1 | A joint image+text embedding engine already exists behind an injectable seam | **YES** | `features/vlm_backbone.py` L294-313: `BackboneBackend` Protocol with `embed_images`→(N,D) **and** `embed_texts`→(M,D) |
| 2 | It is SigLIP-2 so400m, Apache-2.0, pinned to commit `dd658fa…` | **YES** | `vlm_backbone.py` L57-59; `register_backbone_assets()` L470-491 `installer="hf"`, Apache-2.0 label |
| 3 | Image×text cosine in one space already runs | **YES** | `zero_shot_interestingness()` L215-239 (img·tx.T cosine); real backend `get_image_features`/`get_text_features` L74/83 |
| 4 | The RPC contract is at `sidecar/contract/` (NOT `media_studio/contract/`) and never imports media_studio | **YES** | `contract/spec.py` L16-18; `MethodSpec` L185-205; `Binding{NONE,NAMED,SPREAD}` L170-183 |
| 5 | `needs_key=False` methods never enter the key-injection allowlist (the privacy assertion) | **YES** | `contract/generate.py` L69 `needsKeyInjection = spec.needs_key_names()`; `spec.py` L293-295 |
| 6 | Reversibility via a COPY + injected engine table + recorded inverse + auto-rollback exists | **YES** | `features/apply_engine.py` `apply_plan()` L91-149; `director.apply`→`director.undo` in `composition.py` L207-216 |
| 7 | `dedupe_candidates(method='mmr'\|'dpp')` exists, pure numpy | **YES** | `features/diversity.py` L192-246 |
| 8 | The text index build/search pattern to invert cross-modally exists | **YES** | `features/semantic_index.py` `build_corpus`/`search` L45-86; `index.build/search/status/plan` in `composition.py` L190-198 |
| 9 | The library is a SQLite W3C-PROV store with free-text `kind`/`role` + `content_hash` | **YES** | `library.py` `_SCHEMA` L93-105 (`entity.kind/role/content_hash`, `edge` PROV table) |
| 10 | The overlay compositing seam (input0=clip, input1=overlay, `-map 0:a`, argv-list) exists to generalize | **YES** | `features/brandkit.py` `build_logo_overlay_filter/argv` L68-145 (`-map 0:a?` L134-135) |
| 11 | #287 removed no-license S3FD and swapped in MIT YuNet (the licensing precedent) | **YES** | `assets/manifest.py` L439-520 (S3FD removed as "NO license…commercial blocker"; YuNet MIT © Shiqi Yu) |
| 12 | The frames-consent gate fires only on cloud egress; local path never triggers it | **YES** | `models/consent.py` `require_frame_consent` L90-99 (typed `ConsentError`, default-deny) |
| 13 | Dual-registration: POC methods live in BOTH spec.py and composition.py, guarded by parity test | **YES** | 5 POC methods in `spec.py METHODS` L212-273 are all re-registered in `composition.py` L93-262; `tests/test_contract_parity.py` exists |
| 14 | 100% branch coverage + a real-model e2e tier is the established pattern | **YES** | `.coverage-thresholds.json` (sidecar 100% lines+branches); pytest `addopts="-m 'not e2e'"`, markers `unit/integration/e2e`; `test_vlm_backbone.py` covers pure scorers, backend is `# pragma: no cover` |

All 14 hold. The one correction the design itself already makes — contract at `sidecar/contract/` not
`sidecar/media_studio/contract/` — is confirmed correct.

---

## 2. Model adoption — EXACT models + licenses (all HF-metadata-verified 2026-07-12)

**Primary matcher = the model that is already vendored.** Auto-B-roll is a *config swap on one Apache family*,
not a new loader.

| Tier | Model (HF id) | License | Params | Load path | Role | Status |
|---|---|---|---|---|---|---|
| **default / GPU** | `google/siglip2-so400m-patch16-384` | **Apache-2.0** ✓ | 1.14B (SoViT-400M vision + text) | `transformers.AutoModel` (native, no `trust_remote_code`) | PRIMARY image+text matcher | **already vendored** — `vlm_backbone.py`, pinned `dd658faac399…`, registered `installer="hf"` |
| **CPU-default** | `google/siglip2-base-patch16-224` | **Apache-2.0** ✓ | 375M | same `AutoModel` loader (drop-in) | CPU-viable primary | new manifest entry (WU-BR7) |
| **CPU-light image** | `nomic-ai/nomic-embed-vision-v1.5` | **Apache-2.0** ✓ | 93M | **ONNX** (avoids `trust_remote_code`) | torch-free image tower | new entry (WU-BR7) |
| **CPU-light text** | `nomic-ai/nomic-embed-text-v1.5` | **Apache-2.0** ✓ | 137M | **ONNX** | torch-free text tower (pairs with vision above; shared joint space) | new entry (WU-BR7) |
| **MIT fallback** | `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` | **MIT** ✓ | 151M | `open_clip` (or ONNX export) | the clean substitute for OpenAI-CLIP | new entry (WU-BR7) |
| **optional (explainability only)** | `HuggingFaceTB/SmolVLM2-2.2B-Instruct` | **Apache-2.0** | 2.2B | already vendored `features/smolvlm2.py` | caption the matched B-roll ("why this matched") — NOT the matcher | already vendored |

**Sharp implementation notes (load-path security, consistent with the repo's pickle-elimination stance):**
- **SigLIP-2 (so400m/base)** loads via native `transformers` — **no `trust_remote_code`**, cleanest path.
- **Nomic vision/text** carry a `custom_code` tag → the PyTorch path executes repo-hosted modeling code
  (`trust_remote_code=True`). **Use the ONNX artifacts** (both repos ship ONNX) to sidestep code execution —
  matches the repo's `safetensors`-over-`torch.load` discipline. The image + text towers share one joint space
  (both trained on `nomic-embed-v1.5`), so cross-modal cosine is valid.
- **OpenCLIP LAION** weights are MIT and load via `open_clip_torch`; ONNX-exportable for the torch-free path.
- **Pinning:** every new weight enters `manifest.py` with a 40-hex commit + sha256 (the `AssetEntry.__post_init__`
  gate enforces it; HF `resolve` URLs are forced to a commit hash). See §3 for the automated allowlist gate.

**Pairing rule (important):** cross-modal cosine is only valid **within one family's joint space**. Do NOT mix a
SigLIP image embed with a Nomic text embed. A tier is *(image tower, text tower)* from the SAME family:
`(so400m,so400m)`, `(base,base)`, `(nomic-vision,nomic-text)`, `(openclip,openclip)`. The persisted index stores
its `modelId`; `broll.suggest` must refuse a query whose model ≠ the index model (a typed staleness error, re-index).

---

## 3. COMMERCIAL BLOCKERS — verified non-permissive (HARD-AVOID)

Every one confirmed by the HF `license:` metadata tag this session. These are **avoidable**, not the only options —
hence NOT `no-go-licensing`. The trap: they are often *faster on CPU*, so a contributor may reach for one.

| Model / family | HF license tag | Why it's a blocker | The "trap" |
|---|---|---|---|
| `openai/clip-vit-base-patch32` (all `openai/clip-*`) | **NO license tag** | Weights ship with no SPDX license + a research-oriented model card → all-rights-reserved by default for the weights | The obvious "just use CLIP" default |
| `jinaai/jina-clip-v2` (and v1) | **cc-by-nc-4.0** | Non-Commercial — forbidden for a commercialized product | Strong multilingual cross-modal retrieval |
| `apple/MobileCLIP-S2` (S0/S1/S2/B, + MobileCLIP2) | **apple-amlr** | Apple ML Research License = non-commercial | **The CPU-speed trap** — fastest on-device; same class as the no-license S3FD removed in #287 |
| `apple/DFN2B-CLIP-ViT-B-16` (DFN2B/DFN5B) | **apple-amlr** | Apple ML Research License = non-commercial | High-accuracy data-filtered CLIP |
| `facebook/metaclip-2-worldwide-*` (huge/giant/378) **and** MetaCLIP v1 (`facebook/metaclip-*-fullcc2.5b`) | **cc-by-nc-4.0** | Non-Commercial (every variant) | SOTA multilingual worldwide CLIP |

**Adjacent (different feature, noted for the allowlist):** `ViNet-S` video saliency is **CC-BY-NC-SA-4.0** — it is
the *reframe crop-track* model, NOT a B-roll matcher, but the CI allowlist (WU-BR7) should still flag it so a future
"score B-roll by saliency" idea can't smuggle NC weights into the commercial build.

**The durable guard (net-new, WU-BR7):** add a machine-checkable `license` field to `AssetEntry` (SPDX id) and a CI
gate that fails on anything outside `{MIT, Apache-2.0, BSD-*, CC0}` (and on a null/absent license). This automates
the exact discipline the #287 S3FD removal applied by hand.

---

## 4. Architecture — seven stages, each bolted to an existing seam

The pipeline **inverts** the existing semantic-index pattern cross-modally: instead of *text query → text corpus*,
it is *transcript-text query → image-asset corpus*.

```
A. INDEX   broll.index (job)   library assets → embed_images → L2-norm → broll.index.json {vec,modelId,dim,hash}
B. QUERY   broll.suggest (job) transcript segment text → embed_texts (joint space); optional LOCAL query distill
C. RETRIEVE                    per segment: cosine(query, asset vecs)  [semantic_index.search, INVERTED]
D. THRESHOLD                   min-similarity gate → below-threshold = NO candidate  (the OpusClip firewall)
E. DEDUP                       diversity.dedupe_candidates(method='mmr') across segments + per-asset cooldown
F. TIMING  (PURE broll_plan)   anchor to [start,end]; clamp dur; min-gap; coverage cap; snap to shot boundary
G. APPLY   broll.apply (job)   broll_compose argv → apply_engine (COPY + inverse) → overlay track  (REVIEW-FIRST)
```

**Seam map (what each stage reuses vs. builds):**

| Stage | Reuses (verified) | Net-new |
|---|---|---|
| A INDEX | `vlm_backbone.compute_backbone_signals` frame sampling + offline/`models_present` degrade; `library.py` entities; `content_hash` staleness (mirror `_transcript_fp`) | `features/broll_index.py` (persistence + staleness), `broll.index`/`broll.status` handlers |
| B QUERY | `BackboneBackend.embed_texts`; `semantic_index.build_corpus`; local Qwen3 seam (`models/provider.py`) or spaCy/KeyBERT (MIT) for optional distillation — **never a cloud call** | wiring only |
| C RETRIEVE | `semantic_index.search` (inverted: query=segment-text vec, corpus=asset-image vecs) via `diarize.cosine_similarity` | per-segment loop in `broll_plan` |
| D THRESHOLD | — | `MIN_SIMILARITY` gate in `broll_plan` (per-tier calibrated) |
| E DEDUP | `diversity.dedupe_candidates('mmr'\|'dpp')` | cooldown policy |
| F TIMING | `scene_transnet`/`boundary` shot cuts; `silencetrim.py` determinism style; YuNet face box + `chyron_safezone` | `features/broll_plan.py` (PURE) |
| G APPLY | `brandkit.build_logo_overlay_*`; `apply_engine.apply_plan`; `director_op_engines` wired-kind pattern; `tracks.py`/`Project.tracks`; `zoom.py` (Ken-Burns) | `features/broll_compose.py` (argv), `insertBroll` op engine, `broll.apply` handler |

**Face-safe placement — precise:** for **full-frame cutaway** (B-roll replaces the speaker during [S,E]) "covering
the face" is not the risk — the editorial control is the **coverage cap** (≤40-50% of the clip) + not cutting
mid-word (snap to segment/shot boundary). For **PiP/inset**, face-safety = place the inset in a corner the YuNet
face box does NOT occupy (and outside a `chyron_safezone` band). The design's "reuse chyron_safezone + YuNet"
is right for PiP; state it precisely so the implementer doesn't over-apply chyron logic to cutaways.

---

## 5. RPC contract additions (schema-first #282 + dual-registration)

**Add to `sidecar/contract/spec.py`** (stdlib dataclasses; field names are the FROZEN camelCase wire names;
append models to `DATA_MODELS`):

```python
@dataclass
class BrollAsset:        id: str; path: str; kind: str; addedAt: str; thumbPath: str
@dataclass
class BrollSuggestion:   segmentIndex: int; start: float; end: float; assetId: str; score: float; reason: str; layout: str
@dataclass
class BrollStatus:       indexed: bool; assetCount: int; model: str; dim: int; stale: bool
@dataclass
class BrollIndexParams:  force: bool = False
@dataclass
class BrollSuggestParams: videoId: str; threshold: float | None = None; maxCoveragePct: float | None = None
@dataclass
class BrollApplyParams:   videoId: str; suggestions: list[BrollSuggestion]
@dataclass
class BrollAssetParams:   path: str
```
> Only stdlib-supported types (str/int/float/bool/`X | None`/`list[X]`/`dict[str,X]`/nested-dataclass) — anything
> else raises `UnsupportedTypeError` in `schema.py`. `list[BrollSuggestion]` is supported (nested dataclass list).

**Add MethodSpecs** (all `needs_key=False` → NONE appear in `needsKeyInjection` — assert this in a test; it is the
privacy guarantee):

| method | kind | binding | params | result | notes |
|---|---|---|---|---|---|
| `broll.index` | job | NAMED | `BrollIndexParams` | `JobHandle` | embed library via `embed_images`, persist index |
| `broll.suggest` | job | NAMED | `BrollSuggestParams` | `JobHandle & { suggestions?: BrollSuggestion[] }` (import `BrollSuggestion` from `_OWN`) | threshold-gated, ranked |
| `broll.apply` | job | NAMED | `BrollApplyParams` | `JobHandle` | reversible composite |
| `broll.status` | direct | NAMED | `BrollSuggestParams`→`{videoId}` (or a slim `BrollStatusParams{videoId}`) | `BrollStatus` | pure freshness read |
| `broll.assets` | direct | NONE | — | `{ assets: BrollAsset[] }` | list |
| `broll.addAsset` | direct | NAMED | `BrollAssetParams` | `{ asset: BrollAsset }` | mirror of `library.add` |
| `broll.removeAsset` | direct | NAMED | `BrollAssetParams`→`{id}` | `{ removed: bool }` | — |

**Regenerate + guard:**
- Run `python -m contract.generate` from `sidecar/` (emits `contract.schema.json`, `schemas.generated.ts`,
  `client.generated.ts`, `needsKeyInjection.generated.ts`). CI's `test_generated_artifacts_are_current`
  (`generate.check()`) FAILS if skipped.
- **DUAL-REGISTRATION:** #282 is an additive POC (5 methods); ~120 real handlers still register the OLD way in
  `handlers/composition.py::register_all` via `reg(name, handler)`. Wire the 7 B-roll methods in **BOTH**
  `spec.py` AND `composition.py` (a feature module `broll_ops.register(register_fn=reg)` mirrors
  `_silencetrim.register(...)`), guarded by `tests/test_contract_parity.py` (every declared method is really
  registered).

---

## 6. Reversibility + compositing (the two net-new engineering surfaces)

**6a. Reversible apply (`insertBroll` op + `broll.apply`).** Add a WIRED kind `insertBroll` to
`director_op_engines.py` whose engine applies the composite to the project COPY and **returns its inverse op**
(remove the overlay track window). `broll.apply` runs the plan through `apply_engine.apply_plan(plan, project_copy,
engines, …)` → COPY + recorded inverse + stop-on-failure auto-rollback. B-roll lands as a **path-ref overlay track**
on `Project.tracks` (consolidatable via `Project.consolidate`). Undo re-applies the recorded `inverse_plan` (no
re-render) — exactly `director.undo`.

**6b. Compositing argv (`features/broll_compose.py`, PURE).** Generalize `brandkit.build_logo_overlay_filter/argv`:
- **Full-frame cutaway (primary):** each B-roll input scaled+cropped to 1080×1920, overlaid opaque, gated
  `enable='between(t,S,E)'`; `-map 0:a` keeps the speaker's audio, B-roll muted.
- **PiP/inset (optional):** scaled overlay in a face-safe corner (brandkit's `_corner_xy` pattern), same enable gate.
- **N windows in ONE pass:** chain N overlays in a single `filter_complex`, each its own `-i` + scale/crop +
  enable window. **Still image** → `-loop 1`; **B-roll video clip** → `trim=…,setpts=PTS-STARTPTS` to align the
  clip's own timeline into [S,E] (the genuinely new bit beyond brandkit's single still logo).
- Optional subtle **Ken-Burns** via `zoom.py`. argv LIST only, never `shell=True`. Runs through the drained
  `ffmpeg.run` seam.

> This is the highest-risk surface (arg-order, timebase, audio-map, per-window enable). It is why WU-BR8's
> real-ffmpeg e2e (ffprobe dims/duration, B-roll frames present in-window, audio intact, undo round-trips) is
> non-negotiable — a green filter-graph unit test does not prove ffmpeg produced the pixels.

---

## 7. Ethics / consent / offline (a genuine differentiator to surface, not a gate)

This flagship is asset **retrieval + compositing**, NOT generation: it never manipulates a person's voice, face,
or words; it uses the user's OWN local B-roll, LOCAL embeddings (zero frames egress), and preserves the speaker's
original audio (B-roll muted, `-map 0:a`).

- **No consent modal on the default path — by construction.** The `models/consent.py` frames-consent gate
  (`require_frame_consent`) fires ONLY when frames egress to a cloud VLM. The local CLIP path never calls it and
  never egresses → `willEgress=False` on `broll.index`/`suggest`/`apply` (computed exactly like `index.plan`'s
  pure `willEgress`, zero provider calls). No frames-consent prompt, no cloud-budget ack.
- **No deepfake/synthetic-media disclosure** required (no voice/face/words synthesis — unlike the TTS-dub /
  lip-sync flagships, where the NC-weights minefield AND a hard consent gate DO apply). No stock-license/auto-label
  obligation (assets are the user's own, retrieved locally — not third-party stock, not generation).
- **The residual concern is EDITORIAL INTEGRITY**, handled by honest controls (not a modal): (1) hard
  min-similarity threshold; (2) review-before-apply (never auto-committed); (3) visible "why this matched"
  reason + score; (4) full reversibility; (5) coverage cap + face-safe placement; (6) OPTIONAL provenance note
  (C2PA-style "edited with B-roll") if a composited asset depicts an identifiable person — offered, not forced.
- **One conditional gate to preserve:** IF a future variant ever routes transcript text or frames to a CLOUD
  VLM/LLM for query distillation, THAT path MUST re-trigger `require_text_consent` / `require_frame_consent` +
  the budget ack. The recommended design keeps distillation LOCAL (spaCy/KeyBERT MIT, or the local Qwen3 seam),
  so it stays gate-free by construction. **Ship the "100% local — nothing uploaded" badge on the B-roll flow.**

---

## 8. 100% coverage on ML-boundary code — the DETERMINISTIC strategy (not mock-sandwich)

The codebase already proves this pattern: `test_vlm_backbone.py` covers the pure scorers to 100% with hand-built
arrays while `vlm_backbone_backend.py` (the real SigLIP load) is `# pragma: no cover`. Auto-B-roll mirrors it.

**Layer 1 — 100% branch coverage of PURE logic via an injected FAKE backend (the default `-m 'not e2e'` gate).**
Split every module so the deterministic, model-free math is isolated behind a seam:
- `broll_plan.py` (retrieval gate, timing, spacing, coverage, ranking, cooldown), `broll_compose.py` (argv),
  `broll_index.py` (persistence + staleness), the CRUD, and the reversible op are **all pure** — no torch, no
  ffmpeg, no network.
- Inject a **FAKE `BackboneBackend`** returning *canned* embeddings whose cosines you control exactly (e.g. asset
  vectors `[1,0]`,`[0,1]`; segment vector `[0.99,0.14]` → cosine 0.99 vs asset A, 0.14 vs asset B). This makes
  **every branch deterministic**: above/below threshold, tie-break stability, min-gap rejection, coverage-cap
  truncation, cooldown suppression, empty/degenerate inputs, the offline/`models_present=False` degrade path,
  undo. This is *not* a mock-sandwich (asserting the mock was called) — it asserts **real behavior** of the pure
  code over controlled numeric inputs.
- Enforce `.coverage-thresholds.json` (sidecar 100% lines+branches: `pytest --cov=media_studio --cov-branch
  --cov-fail-under=100`) BEFORE PR. The heavy real backends carry `# pragma: no cover`.

**Layer 2 — REAL-model functional e2e (`@pytest.mark.e2e`, EXCLUDED from the coverage gate).** The proof that
retrieval actually discriminates (guards "green-mocked-but-broken"):
- Load the actual SigLIP-2, embed a **dog clip** frame and a **cityscape decoy** frame, embed the query
  *"a dog running"*; **assert the dog clip out-scores the cityscape** and that a semantically-unrelated segment
  falls **below threshold → yields NO insert**. Small, fixed asset fixtures; deterministic assertion on ordering,
  not on absolute score.

**Layer 3 — REAL-ffmpeg integration (`@integration`/`@e2e`).** The proof the composite is correct:
- Run `broll.apply` through real ffmpeg; assert with `ffprobe`: output dims 1080×1920, duration preserved, the
  **main audio stream is intact** (speaker audio not dropped), a **B-roll frame is actually present in its [S,E]
  window** (histogram/NCC match vs the source B-roll, and a NON-window frame matches the speaker), and **undo
  round-trips** (re-apply inverse → manifest/tracks back to pre-apply). 
- Add `broll_plan` + `broll_compose` to the nightly **mutmut** mutation scope (non-blocking) so coverage-blind
  assertions get caught — the harness-level anti-green-mock guard already used for `boundary/zoom/timeline`.

**Why this is honest:** branch coverage proves the *pure logic* is exhaustively exercised deterministically; the
e2e tier proves the *model + ffmpeg actually work*. Neither substitutes for the other; the design mandates both.

---

## 9. WORK UNITS (TDD; tests-first; each ends green + 100% branch on its pure surface)

| id | title | scope (files) |
|---|---|---|
| **BR0** | Contract surface + dual-registration + regen | `sidecar/contract/spec.py` (7 dataclasses→`DATA_MODELS`, 7 `MethodSpec`, all `needs_key=False`); `handlers/composition.py` (register 7 via `broll_ops.register(register_fn=reg)`); run `python -m contract.generate`; `tests/test_contract_parity.py`, `test_generated_artifacts_are_current`, + a test asserting no `broll.*` in `needsKeyInjection` |
| **BR1** | B-roll library CRUD + entity model | `sidecar/media_studio/library.py` (`add_broll/list_broll/remove_broll` reusing the `entity` table: `kind∈{brollImage,brollClip}`, `role='broll'`, `content_hash`); `handlers/library_ops.py` (`broll.assets/addAsset/removeAsset`, thumbnail reuse); `tests/test_broll_library.py` |
| **BR2** | Cross-modal index + staleness | NEW `features/broll_index.py` (PURE persist `broll.index.json {vector,modelId,dim,contentHash,mtime}`, incremental via `content_hash` mirror of `_transcript_fp`); `broll.index` job + `broll.status` direct (reuse `vlm_backbone` embed + offline degrade); `tests/test_broll_index.py` |
| **BR3** | Retrieval + threshold gate + dedup (PURE) | NEW `features/broll_plan.py` (retrieval half): per-segment `embed_texts` query, invert `semantic_index.search`, `MIN_SIMILARITY` gate (below→no candidate), `diversity.dedupe_candidates('mmr')` across segments + per-asset cooldown; `broll.suggest` job wiring; `tests/test_broll_plan_retrieve.py` (FAKE backend, canned cosines) |
| **BR4** | Timing / placement planner (PURE) | `features/broll_plan.py` (timing half): anchor to `[start,end]`, clamp dur (min ~1.5-2.5s, max ≤ seg len, cap ~5s), min-gap, coverage cap, snap to segment/shot boundary (`scene_transnet`/`boundary`), face-safe (coverage for cutaway; YuNet corner for PiP) → `list[BrollInsertion]`; mirror `silencetrim` determinism; `tests/test_broll_plan_timing.py` (hand-built segments) |
| **BR5** | Compositing argv builder (PURE) | NEW `features/broll_compose.py`: generalize `brandkit` — N windows in one `filter_complex`, per-window `-i`+scale/crop+`enable='between(t,S,E)'`, cutaway (opaque 1080×1920) + PiP inset + `-map 0:a` (B-roll muted); still (`-loop 1`) vs video (`trim/setpts`); optional `zoom.py` Ken-Burns; argv-list only; `tests/test_broll_compose.py` (assert exact argv/filtergraph) |
| **BR6** | Reversible apply op + `broll.apply` | `features/director_op_engines.py` (NEW wired kind `insertBroll` returning inverse); `broll.apply` job → `apply_engine.apply_plan` (COPY + inverse + rollback); overlay track on `Project.tracks` (`tracks.py`); undo reuses recorded `inverse_plan`; `tests/test_broll_apply_reversible.py` (fake op engine) |
| **BR7** | Installer tiers + license-allowlist CI | `assets/manifest.py` (+`vlm_backbone` tiering): register `siglip2-base` (CPU-default), `nomic-embed-vision/text` ONNX (torch-free), OpenCLIP-LAION MIT — pinned commit+sha256, `tier∈{optional,gpu}`; **NEW structured `license` SPDX field on `AssetEntry` + CI gate** failing on non-`{MIT,Apache-2.0,BSD,CC0}`/null; `tests/test_assets_license_allowlist.py` |
| **BR8** | Real-model + real-ffmpeg e2e | NEW `tests/test_broll_e2e.py` (`@e2e`): real SigLIP-2 dog-beats-cityscape + below-threshold→no-insert; `@integration` real ffmpeg (ffprobe dims/dur, B-roll frame in-window via NCC, audio intact, undo round-trip); add `broll_plan`/`broll_compose` to mutmut scope |
| **BR9** | UI — Library panel + Auto-B-roll action + review inspector + timeline track | `app/renderer/src/features/…`: B-roll Library panel in #284 content-first Library (scan folder, thumb grid, remove, re-index via `broll.status`); "Auto B-roll" action (index-if-stale→suggest, shared AiJob progress+cancel); suggestion-review in #288 `EditorContext` inspector (per-row thumb/score/reason(+SmolVLM2 caption)/accept-reject-regenerate); threshold + coverage sliders + layout toggle; timeline overlay track (drag/trim) + Apply/Undo; honest "no confident match" state + "100% local" badge; vitest 100% |

**Suggested sequencing:** BR0 → BR1 → BR2 → (BR3 ∥ BR7) → BR4 → BR5 → BR6 → BR8 → BR9. BR7 (models/CI) can run in
parallel with the retrieval work. BR8 gates "done"; BR9 depends on BR0-BR6 handlers existing.

---

## 10. Risks + caveats (with confidence)

| risk | confidence it bites | mitigation |
|---|---|---|
| **CPU latency** — so400m ~1.1B too slow on CPU-only | MEDIUM | Benchmark spike on `siglip2-base` (375M) + Nomic ONNX during BR7; index is one-time batchable; WSL2-GPU path; ship base as CPU-default |
| **Threshold non-transferable across tiers** (SigLIP sigmoid vs softmax scale; SigLIP text ≤64 tokens) | HIGH (a real tuning task) | Per-tier calibrated `MIN_SIMILARITY` constant + a small labelled probe fixture; truncate/summarize long segments before `embed_texts`; store threshold with `modelId` |
| **Multi-window / B-roll-video compositing correctness** | MEDIUM-HIGH | `broll_compose` PURE argv tests + WU-BR8 real-ffmpeg e2e (in-window frame NCC, audio-map, undo round-trip) |
| **Green-mocked-but-broken retrieval** | MEDIUM | Mandatory real-model e2e (dog>cityscape; below-threshold→no insert) + mutmut on the pure planner |
| **License drift** (contributor swaps in a blocker) | LOW-MEDIUM | WU-BR7 structured `license` field + CI allowlist gate (automates #287 discipline) |
| **Irrelevant B-roll** (the #1 OpusClip complaint: "random static images") | — (designed out) | hard threshold + review-first + never auto-apply + cooldown + coverage cap; honest "no confident match" empty state |
| **Contract drift / forgot dual-reg or regen** | LOW | `test_contract_parity` + `test_generated_artifacts_are_current` fail CI |
| **Stale index after library edits** | LOW | `content_hash`+mtime fingerprint; `broll.status.stale`; suggest refuses model-mismatched index |
| **Editorial misrepresentation / likeness** | LOW (policy) | user-owned library + review + visible reason + reversibility + optional provenance note (documented as editorial responsibility, not a synthetic-media gate) |

---

## 11. Open questions / spikes to run first

1. **CPU benchmark spike (blocks tier lock):** measure `siglip2-base` and `nomic-embed-vision` (ONNX) image-embed
   throughput on a representative CPU-only target. Lock the CPU-default tier from data, not assumption.
2. **Threshold calibration probe:** assemble ~20-30 (segment, relevant-asset, decoy-asset) triples per tier; pick
   `MIN_SIMILARITY` at the precision/recall knee. This is a fixture, produced once, versioned with `modelId`.
3. **B-roll representative-frame policy:** one mid-frame vs a few-frame mean-pool for video assets (mean-pool is
   more robust to a bad keyframe; costs a few extra embeds at index time — measure).
4. **Query distillation on/off default:** raw segment text vs spaCy noun-chunks/KeyBERT. Keep LOCAL either way;
   A/B on the probe set. (Local-only keeps the no-consent-gate guarantee intact.)

---

## Sources
- Repo (verified this session, `origin/main` `7502e3a`): `sidecar/media_studio/features/vlm_backbone.py`,
  `vlm_backbone_backend.py`, `diversity.py`, `apply_engine.py`, `semantic_index.py`, `brandkit.py`,
  `chyron_safezone.py`; `sidecar/media_studio/library.py`, `assets/manifest.py`, `models/consent.py`,
  `handlers/composition.py`; `sidecar/contract/spec.py`, `generate.py`; `.coverage-thresholds.json`; `pyproject.toml`.
- License metadata (Hugging Face, 2026-07-12): [siglip2-so400m](https://hf.co/google/siglip2-so400m-patch16-384)
  (apache-2.0), [siglip2-base-224](https://hf.co/google/siglip2-base-patch16-224) (apache-2.0),
  [nomic-embed-vision-v1.5](https://hf.co/nomic-ai/nomic-embed-vision-v1.5) (apache-2.0),
  [nomic-embed-text-v1.5](https://hf.co/nomic-ai/nomic-embed-text-v1.5) (apache-2.0),
  [CLIP-ViT-B-32-laion2B](https://hf.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K) (mit),
  [openai/clip-vit-base-patch32](https://hf.co/openai/clip-vit-base-patch32) (NO license tag),
  [jina-clip-v2](https://hf.co/jinaai/jina-clip-v2) (cc-by-nc-4.0),
  [MobileCLIP-S2](https://hf.co/apple/MobileCLIP-S2) (apple-amlr),
  [DFN2B-CLIP-ViT-B-16](https://hf.co/apple/DFN2B-CLIP-ViT-B-16) (apple-amlr),
  [metaclip-2-worldwide-huge](https://hf.co/facebook/metaclip-2-worldwide-huge-quickgelu) (cc-by-nc-4.0).
- CPU latency (MEDIUM confidence): [Spheron multimodal-embedding benchmarks](https://www.spheron.network/blog/multimodal-embedding-models-gpu-cloud-siglip2-jinaclip-cohere/),
  [mexma-siglip2 "optimize slow CPU inference" thread](https://huggingface.co/visheratin/mexma-siglip2/discussions/2).
- Grounding docs: `reframe-competitor-research.md` (OpusClip "random static images" complaint, B-roll = M-effort
  local edge), `reframe-model-rehosting-dossier.md` (pinning/safetensors discipline; NC vs MIT precedent).
```
