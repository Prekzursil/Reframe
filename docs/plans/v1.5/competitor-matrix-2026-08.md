# Reframe v1.5 — Competitor Capability Matrix (2026-08)

> **Status:** ACTIVE (audit complete at milestone 3).
> **COVERAGE:** Reframe-side state is **MEASURED** for all 52 capability rows (mechanical
> wire-surface extraction, two independent probes — see §1). Competitor-side is **researched with
> URLs for 15 of 16**: Vidnoz, CapCut, Submagic, OpusClip, Descript (§2.1); Kapwing, VEED, Vizard,
> Klap, HeyGen, Captions.ai (§2.2); AetherCut, Reelify, Bitcut (§2.3). **One cell is still
> inherited** — Diffusion Studio — and **Riverside returned no usable feature results** in the one
> search that targeted it, so its column is `?` rather than measured. Both are named in §7.

## Provenance and honesty contract

- Competitor capability claims carry a **URL**. Reframe state claims carry a **`file:line`**.
- `UNVERIFIED` is inline on the sentence it qualifies and names the settling experiment.
- Sherman-Kent bands: almost-certain 90-99% / likely 55-80% / roughly-even 45-55% /
  unlikely 20-45% / remote 1-20%.
- This **extends** `docs/plans/v1.5/competitor-research.md`, whose own stated gap was *"did NOT
  read the repo (web-only)"*. Closing that gap is this document's primary contribution, and it
  **materially refutes that doc's #1 recommendation** (§4.1).

---

## 1. Method — what I actually measured

**Reframe side (mechanical, not judgement).** Per `fan-out-contract.md` §C4, classification that an
exact algorithm can answer was answered by an algorithm, not by reading and guessing:

1. **Engine layer** — enumerated every `*.py` under `sidecar/media_studio/features/` (91 modules)
   and, for each candidate capability, ran a literal keyword probe over the whole sidecar tree
   excluding `__pycache__` / `site-packages`.
2. **RPC layer** — extracted every registered wire method by regexing `@method("…")`,
   `register…("…"`, and `reg("…"` across the sidecar. Verified against the composition root
   `sidecar/media_studio/handlers/composition.py:90-93` (`reg()` wraps `protocol.register`), which
   confirmed the extraction matches the real registry. Result: **~150 dotted RPC methods**.
3. **UI layer** — extracted every method string reachable from `app/` non-test code.
   **My first detector here was incomplete and I corrected it**: a `rpc\('literal'\)` regex missed
   `system.recommend` and `diarize.rename`, which reach the UI as `api.system.recommend(...)`
   (`app/renderer/src/panels/ModelsSystemPanel.tsx:450`). The corrected detector matches any
   quoted dotted literal in `app/**/*.{ts,tsx,js,mjs,cjs,html}`.
4. **Gap confirmation (second independent probe)** — for each method the regex said was unwired, I
   re-ran a `-SimpleMatch` literal search across **all** app file types **including tests**. Both
   probes agreed on all 7 (§4.2). Per `single-signal-verification.md`, one probe would not have
   been evidence.

**PARTIAL is split by half**: `engine` (feature module exists) / `rpc` (registered on the wire) /
`ui` (reachable from the renderer). A module existing is *not* evidence it is wired; a doc claiming
a feature is *not* evidence at all.

**Competitor side.** WebSearch per vendor, 2026 feature pages + independent reviews. Where a
vendor's own marketing number is the only source (accuracy %, virality-score efficacy) I say so.

---

## 2. Competitor inventories

### 2.1 Deep-researched by me (2026-08)

| Vendor | Capability highlights | Source |
|---|---|---|
| **Vidnoz** | 1,900+ AI avatars; dual-avatar conversation scenes; 2,000+ voices / 140+ languages; voice cloning; **talking photo** (still image → lip-synced speaker, 100+ languages); AI face swap (photo+video, multi-face); video translator with lip-sync preserved ("fully operational for the top 10 languages"); 2,800+ templates. Starter $26.99/mo (15 credits), Business $74.99/mo (+voice clone, +translation). | [vidnoz.com](https://www.vidnoz.com/), [talking-head](https://www.vidnoz.com/talking-head.html), [unite.ai review](https://www.unite.ai/vidnoz-review/), [creatorstackclub](https://www.creatorstackclub.com/software/vidnoz-ai) |
| **CapCut** | AI Auto-Edit; instant captions **130+ languages** (55+ for auto-caption per one source — the two numbers disagree, see note); sound-effect captions `(applause)`; AI Script-to-Video; long-video→multi-shorts with highlight detect + auto-format; AI avatars; TTS 269 voices + voice cloning; background removal; auto-translate captions; upscaling; Seedream 5.0 image gen + Dreamina Seedance 2.0 video gen; Gemini-driven conversational editing. | [capcut.com](https://www.capcut.com/), [solidaitech 2026 guide](https://www.solidaitech.com/2026/05/capcut.html), [freeacademy.ai](https://freeacademy.ai/blog/capcut-ai-features-complete-guide-review-2026) |
| **Submagic** | 150+ caption templates; claimed **99% accuracy / 123 languages** (vendor number, unverifiable); AI B-roll from Storyblocks; Magic Zoom (fast/crash/smooth/expo/linear); **eye-contact correction**; AI Auto-Edit = captions + silence + filler + B-roll + zoom + SFX-on-emphasis + hook title in one pass; AI Avatar Studio; Clean Audio (1-click denoise); translation 100+ languages; auto-reframe→9:16; ThumbMagic thumbnails. | [submagic.co](https://www.submagic.co/), [b-roll](https://www.submagic.co/features/b-roll), [ai-caption](https://www.submagic.co/ai-caption) |
| **OpusClip** | ClipAnything (visual+audio+expression+narrative analysis in parallel); **virality score 0-99**; ReframeAnything object/active-speaker tracking → 9:16 / 1:1 / 16:9; AI B-roll (generated *or* stock); brand templates applied across a batch. | [opus-clip.com](https://opus-clip.com/), [BIGVU test](https://bigvu.tv/blog/opus-clip-tested-2026-where-ai-wins-40-percent-discard/), [theplanettools](https://theplanettools.ai/tools/opusclip) |
| **Descript** | Underlord = **agentic** multi-step co-editor ("remove filler, tighten pauses, add captions, pull three vertical clips"); eye-contact correction incl. glasses/extreme angles; Studio Sound 4.0 (stem-separates voice/background/music, de-reverb); Overdub 3.0 voice clone from 3 min + emotional intonation; filler removal; **generative** B-roll via diffusion; script drafting, summaries, show notes, viral-clip ID. | [descript.com/underlord](https://www.descript.com/underlord), [aitoolsdevpro guide](https://aitoolsdevpro.com/ai-tools/descript-guide/) |

**Note on CapCut's caption-language count:** two 2026 sources give **55+** and **130+**. I did not
resolve which is current — UNVERIFIED; settled by opening CapCut's own auto-caption language picker
in the current build. It does not change any matrix cell (Reframe's own count is what matters).

### 2.2 Also researched by me (2026-08) — cloud majors

| Vendor | Capability highlights | Source |
|---|---|---|
| **Kapwing** | Prompt-to-video; script generator; TTS + **dubbing 40+ languages**; auto-subtitles; **Clean Audio** noise removal; **Smart Cut** silence removal; **B-Roll Generator**; Clip Maker; Repurpose Studio; real-time collaboration. | [kapwing vs veed](https://www.kapwing.com/resources/kapwing-vs-veed-comparison-for-video-creators-in-2026/), [ngram](https://www.ngram.com/blog/kapwing-vs-veed) |
| **VEED** | Fast auto-subtitles; dubbing (many languages); **text-to-video + image-to-video** via own Fabric model *plus* third-party Sora/Veo; AI avatars; AI voice generator; background removal; **eye-contact correction**. | [ngram](https://www.ngram.com/blog/kapwing-vs-veed), [videoai.me](https://videoai.me/compare/kapwing-vs-veed) |
| **Vizard** | Team-oriented repurposing: AI highlight detection → clips, plus collaborative edit/review/approve. | [ngram vizard alternatives](https://www.ngram.com/blog/vizard-alternatives-tested) |
| **Klap** | Premium *visual* positioning — cleaner crops, **4K export**, brand-consistent output; wins head-to-head when "looks like us" beats clip volume. | [uxerwave](https://uxerwave.com/video-audio/opus-clip-vs-vizard-vs-kapwing/), [klap.app](https://klap.app/blog/veed-alternatives) |
| **HeyGen** | **Avatar V** from a 15-second recording (multi-angle stability, long-form); Seedance 2.0 cinematic gen + digital twin interacting with up to 2 others; podcast → social clips in **175+ languages**; new AI Studio (no timeline). | [heygen.com](https://www.heygen.com/), [April 2026 release](https://www.heygen.com/blog/heygen-april-2026-release), [AI Studio](https://help.heygen.com/en/articles/11049655-overview-our-new-ai-studio) |
| **Captions.ai** | AI captions; **AI Twins** (avatar cloned from your own recordings); **AI eye contact** (look at camera while reading a script); AI shorts (auto best-moment → clips for IG/YT/TikTok/LinkedIn). | [fahimai comparison](https://www.fahimai.com/heygen-vs-captions-ai) |

### 2.3 The local-first rivals — the segment Reframe actually competes in

| Vendor | Position | Source |
|---|---|---|
| **AetherCut** | Browser-based, "**nothing uploads — verifiable in DevTools**", **51 AI tools**, 5× realtime export, no signup, 4K, no watermark. Explicit anti-surveillance marketing. | [aethercut.app](https://aethercut.app/), [no-account](https://aethercut.app/free-video-editor-no-account) |
| **Reelify AI** | **Mac / Apple Silicon only.** On-device Edge AI; no frames/audio/metadata leave the Mac ("the pipeline was never designed to send it anywhere"); 1-hour video analysed in **under 90 s**; 5-10× faster than cloud. | [local-ai-video-editor](https://reelifyclips.com/local-ai-video-editor), [no-upload](https://reelifyclips.com/private-video-editing-no-upload) |
| **Bitcut** | **iOS App Store app.** Long → Shorts, AI subtitles with word-level transcription, face-tracking reframe, beat-synchronised editing. | [App Store](https://apps.apple.com/us/app/bitcut-ai-video-editor/id6759696573) |
| **Diffusion Studio** | Not re-measured this pass — the only remaining inherited cell. `[prior]` | `competitor-research.md:5` |

**Strategic read (this changes the competitive framing).** Reframe's platform position is
*better than the prior doc implies*, on two measured grounds:

- **Reelify is Mac-only and Bitcut is iOS-only.** Neither competes with Reframe on Windows at all.
  Confidence: **almost certain (90-99%)** — both vendors state the platform restriction themselves.
- **AetherCut runs in a browser.** That caps it at WebGPU/WASM-class inference, whereas Reframe
  runs a WSL2 GPU path with full PyTorch models (LightASD, TransNetV2, pyannote, Qwen3-VL). Its
  "51 AI tools" count therefore does not imply parity of *model depth*. Confidence that AetherCut
  cannot match Reframe's heaviest local models in-browser: **likely (55-80%)** — inferred from the
  browser runtime constraint, **UNVERIFIED**; settled by loading AetherCut and inspecting whether it
  ships an ONNX/WebGPU bundle or calls a server, which its own DevTools claim invites.

**Correction to the prior research.** `competitor-research.md:11,33` states AetherCut markets an
"AI Director by Claude". I did **not** find that phrase on aethercut.app in this pass; what I found
is "51 AI tools" and anti-surveillance framing. I am **not** claiming the prior doc is wrong — the
site may have changed, or the claim may sit on a page I did not fetch. **UNVERIFIED both ways**;
settled by fetching aethercut.app's feature/pricing pages directly.

---

## 3. THE MATRIX

**Legend.** Competitor columns: `Y` = has it (URL in §2), `-` = does not / not marketed,
`?` = unknown. Reframe: **BUILT** (engine+rpc+ui) · **PARTIAL(x)** (the missing half is named) ·
**MISSING**. Effort S/M/L/XL is *incremental over what already exists*, calibrated against the
measured code. `Cap`=CapCut, `Opus`=OpusClip, `Vid`=Vidnoz, `Desc`=Descript, `Sub`=Submagic;
`Others` covers Kapwing/VEED/Vizard/Klap/HeyGen/Captions.ai and the local-first trio.

**A `-` is weaker evidence than a `Y`.** A `Y` rests on a vendor feature page; a `-` rests on the
capability being absent from the pages I read, which is not proof of absence. Read `-` as
"not marketed as a headline feature", **not** as "cannot do it".

| # | Capability | Cap | Opus | Vid | Desc | Sub | Others | Reframe state (file:line) | Effort |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Auto clip-finding: long → ranked shorts | Y | Y | - | Y | Y | Klap/Vizard/Veed Y | **BUILT** `features/select.py`, `shortmaker.select` @ `handlers/composition.py:144` | — |
| 2 | Candidate ranking / score | ? | Y (0-99) | - | Y | Y | Vizard Y | **BUILT** `features/ranker.py`, `features/scorer.py`; honest-score design in `features/director_eval.py` | — |
| 3 | Virality *prediction* score | - | **Y** | - | - | - | Vizard Y | **MISSING** — deliberate: prior doc argues users distrust it | S |
| 4 | Auto-reframe 16:9→9:16 subject track | Y | Y | - | Y | Y | most Y | **BUILT** `features/reframe.py`; mediapipe face track (26 hits incl. `reframe.py`) | — |
| 5 | **Active-speaker detection (ASD)** | ? | Y | - | ? | Y | AetherCut Y | **BUILT** `features/_lightasd_infer.py` (20 KB), `features/_lightasd/`; engine selectable in UI @ `app/renderer/src/features/shortMakerLogic.ts:261,270` | — |
| 6 | **Multi-speaker split / composite layout** | - | - | - | - | - | ? | **BUILT** `features/reframe_multispeaker.py:382` `decide_layout()` → single/split/composite; debounce `:97,402` | — |
| 7 | Shot / scene detection | Y | Y | - | Y | Y | most Y | **BUILT** `features/scene_transnet.py` (TransNetV2) + `_transnetv2/` | — |
| 8 | Speaker diarization | - | ? | - | Y | ? | Riverside Y | **BUILT** `features/diarize.py`, `pyannote_backend.py`; `diarize.start`/`diarize.rename` + UI `features/Diarize.tsx` | — |
| 9 | Word-level karaoke captions | Y | Y | - | Y | Y | most Y | **BUILT** `features/caption_karaoke.py` (14 KB) | — |
| 10 | Caption template **gallery** (many presets) | Y | Y | - | Y | **Y 150+** | most Y | **PARTIAL(ui)** — engine `features/templates.py`, `templates.list/save/apply` wired; but count/visual gallery ≠ 150 presets. Needs preset *content*, not plumbing | M |
| 11 | Auto-emphasis (power-word styling) | ? | Y | - | ? | Y | ? | **BUILT** `features/emphasis.py` (12 KB), consumed by `caption.py`, `caption_polish.py`, `caption_remotion.py`, `zoom.py` (11 importers) | — |
| 12 | Auto-emoji in captions | Y | Y | - | ? | Y | ? | **BUILT** — 81 `emoji` hits across `caption.py`, `caption_polish.py`, `caption_remotion.py`, `emphasis.py` | — |
| 13 | Caption polish (CPS/CPL/gaps) | ? | ? | - | ? | ? | ? | **BUILT** `features/caption_polish.py` (25 KB), 8 importers | — |
| 14 | Caption translation / multilang | Y | Y | Y | Y | Y | most Y | **BUILT** `subtitles.translate` + `models/translation.py` | — |
| 15 | Custom dictionary / SRT import | - | ? | - | Y | ? | ? | **PARTIAL(ui)** `subtitles.edit` exists; no dictionary module found (0 hits) | S |
| 16 | Burn-in / soft-mux subtitle tracks | Y | Y | - | Y | Y | most Y | **BUILT** `features/subtitles.py`, `tracks.burn`, `tracks.strip` | — |
| 17 | Auto-zoom / punch-in | Y | ? | - | ? | **Y** | ? | **PARTIAL(rpc+ui)** engine `features/zoom.py` exists but has **exactly 1 importer** (`shortmaker.py`) — no standalone RPC, no UI control | S-M |
| 18 | Filler-word removal | Y | Y | - | **Y** | Y | most Y | **BUILT** `features/fillers.py` — **18 importers** (`refine.py`, `silencetrim.py`, `director_op_engines.py`, `emphasis.py`, `shortmaker.py`) | — |
| 19 | Silence / dead-air removal | Y | Y | - | Y | Y | Kapwing **Smart Cut** Y | **PARTIAL(ui)** engine `features/silencetrim.py` (18 KB) + `silence.trim` RPC registered — **ZERO UI references** (§4.2) | S |
| 20 | Bad-take detection | - | ? | - | Y | Y | ? | **PARTIAL(engine)** `features/refine.py` + `refine.apply`/`refine.preview` wired; explicit take-selection unverified | M |
| 21 | Text-based (transcript) editing | Y | - | - | **Y** | - | ? | **PARTIAL(ui)** word-aligned transcript BUILT (`features/ctc_align.py`, `transcribe.py`); delete-word→cut-video UI not found | L |
| 22 | B-roll from **stock** library | Y | Y | Y | **Y** | Y | most Y | **MISSING** — 0 hits for any stock provider. Conflicts with offline-first; deliberate | M (needs cloud) |
| 23 | **B-roll from user's OWN library** (semantic) | - | - | - | - | - | - | **PARTIAL(ui)** `features/semantic_index.py` + `index.build/search/status/plan` wired; *insertion into the edit* not found | M |
| 24 | **Generative** B-roll (diffusion) | Y | Y | Y | **Y** | - | **VEED (Fabric+Sora/Veo), Kapwing, HeyGen (Seedance 2.0)** | **MISSING** — 0 hits for any diffusion/T2V model | L-XL |
| 25 | Hook title / hook card | ? | Y | - | ? | **Y** | ? | **PARTIAL(engine)** renderer BUILT `features/hook_card.py` (4 importers); **LLM text generation** for it not found | S |
| 26 | Thumbnail generation | Y | ? | - | ? | Y (ThumbMagic) | ? | **PARTIAL(engine)** `thumbnail.select` + `features/best_frame.py` (6 importers) = best-frame pick, not *generated* thumbnail | M |
| 27 | Brand kit (fonts/colors/logo) | Y | Y | Y | Y | Y | most Y | **BUILT** `features/brandkit.py`, imported by `shortmaker.py` | — |
| 28 | Batch processing | Y | Y | Y | ? | Y | most Y | **BUILT** `features/batch.py` (52 KB); full `batch.*` RPC set + UI | — |
| 29 | Multi-aspect export matrix | Y | Y | ? | Y | Y | most Y | **BUILT** `features/aspect.py`, `features/export_presets.py` (7 importers), `exportPresets.*` wired | — |
| 30 | AI dubbing (translated TTS VO) | Y | ? | **Y** | ? | Y | Kapwing 40+ langs, VEED Y | **BUILT** `features/tts/dub.py` (`run_dub_pipeline`), registered `tts.dub.start` @ `features/tts/__init__.py:105`; engines `tts/kokoro.py`, `tts/chatterbox.py`; mux via `features/tracks_audio.py:600` | — |
| 31 | Voice cloning | Y | - | **Y** | **Y** | - | ? | **BUILT** `tts.sample.add`, `tts.voices`, `features/tts/chatterbox.py` (zero-shot clone) | — |
| 32 | **Lip-sync to the dub** | - | **Y** | **Y** | - | - | HeyGen Y | **MISSING** — 0 hits for `lipsync`/`latentsync`/`wav2lip` | L |
| 33 | **AI avatars / talking photo** | **Y** | - | **Y** | - | **Y** | **HeyGen Avatar V, Captions.ai AI Twins, VEED Y** | **MISSING** — 0 hits for `avatar` (the 2 keyword hits were `_scheduled`, a use-vs-mention false positive) | XL |
| 34 | **Eye-contact / gaze correction** | - | - | - | **Y** | **Y** | **VEED Y, Captions.ai Y** | **MISSING** — 0 hits for `gaze`/`eye contact` | L |
| 35 | Face swap | - | - | **Y** | - | - | ? | **MISSING** — 0 hits (`insightface` 0) | L |
| 36 | Background removal / greenscreen | **Y** | ? | Y | ? | ? | most Y | **MISSING** — 0 hits (`rembg`, `background remov`) | M |
| 37 | Denoise / "studio sound" | Y | ? | ? | **Y** | **Y** | Kapwing **Clean Audio** Y | **MISSING** — 0 hits (`denoise`, `DeepFilter`) | M |
| 38 | Stem separation (voice/music/bg) | ? | - | - | **Y** | - | ? | **MISSING** — 0 hits (`demucs`) | M |
| 39 | Loudness normalization (LUFS) | ? | ? | - | ? | ? | ? | **PARTIAL(ui)** `features/audiomix.py` has `loudnorm` (35 hits) + `audiomix.normalize` RPC — **ZERO UI** (§4.2) | S |
| 40 | Music bed + auto-ducking | Y | ? | - | Y | ? | most Y | **PARTIAL(ui)** `audiomix.py` `sidechaincompress` (6 hits) + `audiomix.merge` RPC — **ZERO UI** (§4.2) | S |
| 41 | SFX on emphasis words | - | - | - | - | **Y** | ? | **MISSING** — 0 hits (`sfx`, `sound effect`) | S-M |
| 42 | Multi audio-track management | ? | - | - | Y | - | ? | **BUILT** `features/tracks_audio.py` (27 KB); `tracks.audio.{list,mux,replace,strip}` + UI | — |
| 43 | Stabilization | Y | - | - | ? | - | ? | **PARTIAL(ui)** `features/stabilize.py` (21 KB) + `stabilize.run` RPC — **ZERO UI** (§4.2) | S |
| 44 | Upscaling / enhance | **Y** | - | ? | ? | ? | most Y | **MISSING** — 0 hits (`upscal`, `esrgan`) | M |
| 45 | Watermark removal | ? | - | ? | - | - | ? | **MISSING in sidecar** — 0 hits for `ProPainter`. A `video-watermark-removal` skill exists in the *harness*, so the tooling may live outside this tree — UNVERIFIED; settled by `grep -ri propainter` over the whole repo incl. WSL scripts | M |
| 46 | Agentic AI director (1 prompt → N steps) | Y (Gemini) | - | **Y** | - | Y (Auto-Edit) | AetherCut Y | **BUILT** `features/director.py`, `director_op_engines.py` (39 KB), `director_eval.py`; `director.{plan,previewCost,apply,undo,evaluate}` + UI `Director.tsx` — and **reversible**, which no competitor offers | — |
| 47 | Script → video | **Y** | - | Y | Y | - | ? | **MISSING** (needs #24) | L |
| 48 | NLE handoff (FCPXML/EDL) | - | - | - | ? | - | ? | **BUILT** `features/nle_export.py`, `nle.export` RPC + client | — |
| 49 | Social scheduling / publish | Y | ? | ? | Y | Y | most Y | **MISSING** — 0 hits (`oauth`, `publish to`; `schedul` hits were `_scheduled` job-pool, use-vs-mention) | M (needs cloud) |
| 50 | Screen recording | Y | - | - | **Y** | - | Riverside Y | **MISSING** — 2 hits, both in `test_director_golden_plans.py` (fixture text) | M |
| 51 | Collaboration / team review | Y | Y | Y | Y | Y | most Y | **MISSING** — architecturally out of scope (offline-first) | XL |
| 52 | **100% offline / no upload** | **-** | **-** | **-** | **-** | **-** | AetherCut Y (browser), Reelify Y (**Mac only**), Bitcut Y (**iOS only**) | **BUILT** — `features/offline.py`; the whole sidecar is local. **Only Windows-native local-first entrant found** | — |

---

## 4. What the repo audit actually changed

### 4.1 The prior doc's #1 recommendation is already built — REFUTED

`competitor-research.md:8` ranks **"Active-speaker detection + multi-speaker split/switch layouts
(L)"** as the single highest-value thing to steal, and proposes sourcing it from an NVIDIA ASD NIM.
**It is already in the tree and already reachable from the UI:**

- ASD engine: `sidecar/media_studio/features/_lightasd_infer.py` (20,210 bytes) + `features/_lightasd/`
- Fusion + layout: `sidecar/media_studio/features/reframe_multispeaker.py` (68,571 bytes), with
  `decide_layout()` at `:382` returning `single` / `split` (50-50 vertical) / `composite`
  (host top + guests bottom), and anti-flicker debounce at `:97` (`LAYOUT_MIN_DWELL_SEC = 0.5`)
  and `:402` (`debounce_layouts`)
- UI: selectable engine `'reframe_multispeaker'` at `app/renderer/src/features/shortMakerLogic.ts:261`,
  labelled `'Multi-speaker (hybrid, WSL/GPU)'` at `:270`, also in `features/repurposeLogic.ts:55`

Building it again would be **pure waste**. Confidence it is genuinely wired end-to-end:
**likely (55-80%)** — I verified engine + UI-selectable engine name, and did *not* execute a job,
so I have not proven it produces correct output. **UNVERIFIED: whether a multispeaker export
actually renders a split layout.** Settling experiment: run `shortmaker.export` with
`engine=reframe_multispeaker` on a 2-speaker clip and `ffprobe` + eyeball the result — the
`packaged-artifact-smoke` skill's postcondition-probe pattern is the right shape.

Items 11 (auto-emphasis) and 12 (auto-emoji) were also listed as things to *add*
(`competitor-research.md:9`, "auto-emphasis + auto-emoji"). Both are **BUILT**
(`features/emphasis.py`, 11 importers; 81 `emoji` hits across four caption modules). The prior
doc's stated gap — *"auto-zoom/emoji status unknown"* — resolves as: **emoji built, zoom half-built**.

### 4.2 Seven capabilities are fully built and registered but have NO UI

This is the highest-yield finding in the audit: **engine + RPC exist and are wired to
`protocol.METHODS`, but zero references exist anywhere in `app/`** — including tests, main process,
and preload. Verified by two mechanically independent probes (regex extraction, then literal
`-SimpleMatch` across all app file types).

| RPC method | Engine | Competitor pressure |
|---|---|---|
| `silence.trim` | `features/silencetrim.py` (18 KB) | Submagic + Descript + OpusClip + CapCut all ship it |
| `audiomix.normalize` | `features/audiomix.py` — `loudnorm`, 35 hits | platform LUFS targets |
| `audiomix.merge` | `features/audiomix.py` — `sidechaincompress`, 6 hits | music bed + ducking, market-standard |
| `stabilize.run` | `features/stabilize.py` (21 KB) | CapCut |
| `reframe.eval` | `features/reframe_eval.py` (23 KB) | internal quality signal |
| `phase8.signals` | `handlers` → `svc.phase8_signals` | internal |
| `assets.plan` | `assets/` | internal |

The first four are **user-visible competitive features already paid for in engine cost**. Exposing
them is an **S** each — a panel + a typed client wrapper in
`app/renderer/src/lib/rpc/client.ts` (the file already holds a hand-written wrapper for most of the
live surface, so the pattern is established — the exact count lives in
`docs/rpc-contract-v2.md` §1, where a test pins it; repeating it here is what let the
old figure rot). This is the cheapest capability-per-effort work in the whole plan.

Also measured: `features/scroll_regen.py` (12,131 bytes) has **zero importers**. Likely dead code
— **UNVERIFIED**, since my probe cannot see a dynamic/string-keyed import. Settling experiment:
`grep -rn "scroll_regen" sidecar/` including string literals, then delete-and-test.

### 4.3 Reframe's genuine differentiators (not just "offline")

Beyond row 52, two are architecturally distinctive and worth marketing, not just keeping:

- **Reversible AI director.** `director.undo` is registered (`handlers/composition.py:216`) and
  `director.apply` records an inverse over a fresh copy (`:208-216`). Descript's Underlord and
  CapCut's Gemini mode are both fire-and-forget. Confidence no major competitor ships a
  transactional undo of an agentic edit: **likely (55-80%)**, from the absence of any such claim in
  the 6 vendors I researched — absence of a marketing claim is weak evidence, so not higher.
- **Honest scoring instead of a virality oracle.** `features/director_eval.py` +
  `features/feedback.py` (`feedback.record`/`feedback.stats`) is a measured-feedback loop, versus
  OpusClip's 0-99 score. Independent creator data does report 80+ clips outperforming
  ([BIGVU](https://bigvu.tv/blog/opus-clip-tested-2026-where-ai-wins-40-percent-discard/)), so the
  prior doc's "decorative" framing is **too strong** — the score has *some* signal; what is
  unverifiable is the vendor's implied causality.

---

## 5. Local feasibility + licence gate for the MISSING rows

**Licence rule applied:** MIT / Apache-2.0 / BSD only for anything shipping commercially.
**Every licence below is from my training knowledge, NOT from opening the licence file** — flagged
inline. **UNVERIFIED (all rows): the licence as stated.** Settling experiment per row: open the HF
model card + the repo `LICENSE`, and for gated weights confirm whether the *weights* carry the
code's licence (they frequently do not — this is the trap that bites).

| Row | Capability | Candidate open-weights model | Licence (claimed) | Verdict |
|---|---|---|---|---|
| 32 | Lip-sync | **MuseTalk** | MIT | **GO** — best licence/quality ratio |
| 32 | Lip-sync | LatentSync | Apache-2.0 code; weights unclear | CHECK WEIGHTS |
| 32 | Lip-sync | Wav2Lip | **research/non-commercial** | **BLOCKED** |
| 33 | Avatar / talking photo | LivePortrait | MIT code; weights unclear | CHECK WEIGHTS |
| 33 | Avatar | SadTalker | Apache-2.0 code, restrictive ckpts | CHECK WEIGHTS |
| 34 | Eye contact | MediaPipe FaceMesh + custom pupil warp | Apache-2.0 | **GO** — and mediapipe is *already a dependency* (26 hits) |
| 35 | Face swap | InsightFace / inswapper | **non-commercial** | **BLOCKED** |
| 36 | Background removal | RMBG-2.0 | non-commercial | **BLOCKED** |
| 36 | Background removal | BiRefNet / `rembg` (u2net) | MIT / Apache-2.0 | **GO** |
| 37 | Denoise | DeepFilterNet3 | MIT/Apache-2.0 | **GO** |
| 38 | Stem separation | Demucs v4 (htdemucs) | MIT | **GO** |
| 44 | Upscaling | Real-ESRGAN | BSD-3-Clause | **GO** |
| 45 | Watermark inpaint | big-LAMA | Apache-2.0 | **GO** |
| 45 | Watermark inpaint | ProPainter | **S-Lab non-commercial** | **BLOCKED for commercial** |
| 24 | Generative B-roll (image) | FLUX.1-**schnell** | Apache-2.0 | **GO** |
| 24 | Generative B-roll (image) | FLUX.1-dev / SDXL | NC / OpenRAIL++ restrictions | **BLOCKED / CHECK** |
| 24 | Generative B-roll (video) | Wan 2.x | Apache-2.0 | **GO** (heavy VRAM) |
| 24 | Generative B-roll (video) | LTX-Video | custom LTXV licence | **CHECK** |

**Already-licensed-and-present stack** (no new licence risk): Parakeet ASR
(`features/parakeet_asr.py`), Whisper/CTC align (`features/ctc_align.py`), TransNetV2
(`features/_transnetv2/`), LightASD (`features/_lightasd/`), pyannote
(`features/pyannote_backend.py`), SmolVLM2 (`features/smolvlm2.py`), Qwen3-VL
(`features/qwen3vl_backend.py`), EdgeTAM (`features/reframe_edgetam_backend.py`), Kokoro +
Chatterbox TTS (`features/tts/`), PANNs (`features/audio_saliency.py`).

**Note on gated weights:** `sidecar/media_studio/hf_auth.py` exists, so the project already has a
Hugging Face auth path — meaning gated-but-permissive models are *operationally* reachable. That
does not make an NC licence usable.

---

## 6. Ranked build order — the 10 to do first

Score = (market prevalence across the 6 measured majors × user value) ÷ effort, then re-ordered so
the near-free wins land first. Effort is incremental over measured code.

| # | Build | Why now | Effort |
|---|---|---|---|
| 1 | **Expose `silence.trim` in the UI** | Engine done, RPC done, 4/6 majors ship it, zero engine cost | **S** |
| 2 | **Expose `audiomix.merge` + `audiomix.normalize`** | Music bed + ducking + per-platform LUFS; engine done | **S** |
| 3 | **Auto-zoom / punch-in control** | `features/zoom.py` exists with 1 importer; Submagic's Magic Zoom is a headline feature; emphasis timing already available from `emphasis.py` | **S-M** |
| 4 | **Caption template gallery content** (target 20-30, not 150) | Plumbing (`templates.*`) already wired; captions are the #1 loved feature market-wide; this is asset authoring not engineering | **M** |
| 5 | **Hook-title LLM generation** | Renderer exists (`hook_card.py`); only the text-gen step is missing; Submagic + OpusClip both ship it | **S** |
| 6 | **Denoise / "clean audio"** | DeepFilterNet3 MIT; Submagic + Descript both headline it; single-model add | **M** |
| 7 | **Own-library B-roll insertion** | `semantic_index.py` + `index.search` already wired — only the *insert into edit* step is missing. This is the strongest local-only differentiator: on-brand B-roll no cloud tool can match | **M** |
| 8 | **Expose `stabilize.run`** | Engine done (21 KB); rounds out the "does it replace CapCut" story | **S** |
| 9 | **Eye-contact correction** | **4 of the measured majors ship it** (Submagic, Descript, VEED, Captions.ai) and none of the local-first trio does — a clean differentiation win; mediapipe is *already* a dependency (26 hits); Apache-2.0 path | **L** |
| 10 | **Lip-sync for the existing dub** (MuseTalk, MIT) | Dub + voice-clone already BUILT — lip-sync is the missing last mile that makes dubbing shippable; biggest reach multiplier per prior research | **L** |

**Deliberately NOT in the top 10:**
- **AI avatars / talking photo (row 33, XL).** Vidnoz's core product, and the owner named Vidnoz.
  But it is a *different product category* (synthetic presenter) from repurposing real footage, and
  it is the single largest build here. Recommend as an explicit **v1.6 scope decision**, not a v1.5
  gap-close. **This is a judgement call that contradicts a literal reading of "all capabilities of
  Vidnoz" — flagging it for the owner rather than silently dropping it.**
- **Generative B-roll (24), script→video (47)** — XL, and both push against offline-first (VRAM).
- **Stock B-roll (22), social publish (49), collaboration (51)** — all require cloud, which
  contradicts row 52, the product's actual moat.
- **Virality score (3)** — cheap (S) but the prior doc's user-distrust argument stands; ship the
  honest `director_eval` score instead.

---

## 7. Residual gaps and what would settle them

1. **Two of sixteen competitor columns are not measured.** **Riverside** — the one search that
   targeted it returned no usable feature results, so its cells are `?`, and I did not retry with a
   narrower query. **Diffusion Studio** — inherited from `competitor-research.md:5`, never fetched.
   Settle: two targeted WebSearch/WebFetch passes against each vendor's own feature page.
   Confidence this changes the top-10: **remote (1-20%)** — Riverside is a recording/studio product
   and Diffusion Studio is a library, so neither adds a capability row the measured 14 lack.
2. **No capability was executed.** Every Reframe verdict is *static* (module exists, method
   registered, string referenced). A BUILT row could still be broken at runtime. Settle:
   `packaged-artifact-smoke` golden journeys with `ffprobe` postconditions on the produced file.
3. **All 18 licence rows in §5 are from memory, not from a licence file.** This is the single
   highest-risk section for a commercial build. Settle: open each HF model card + repo `LICENSE`,
   and separately confirm the *weights* licence.
4. **"PARTIAL(ui)" does not distinguish "no UI" from "UI exists under a name I did not match."**
   For the 7 in §4.2 the second probe covered all app file types, so those are solid; for rows
   marked PARTIAL on judgement (20, 21, 23, 25, 26) the classification is weaker. Settle: drive the
   built app with `ui-drive` and try to reach each feature.
5. **Effort grades are my estimates**, not decomposed plans. Treat S/M/L/XL as ordinal, not
   as hours.
6. **CapCut caption-language count unresolved** (55+ vs 130+) — see §2.1 note. Immaterial.
