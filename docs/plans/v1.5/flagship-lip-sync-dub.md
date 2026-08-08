# Reframe v1.5 Flagship "Unknown" — Implementation Plan + Go/No-Go

> **Status:** DRAFT

**Author:** flagship-scoping subagent · **Date:** 2026-07-12 · **Mode:** research + design + plan only (no repo edits)
**Repo:** `Prekzursil/Reframe` (Electron + Python sidecar) · **Baseline read from `origin/main`** (local checkout is 10 commits behind)

> **Independent re-verification (2026-07-12, second pass — a fresh reviewer's confirmation).** A second agent independently re-derived this verdict from `origin/main` + live HF license tags + verbatim model READMEs and CONFIRMS it. Load-bearing structural claims re-checked and held:
> - **#287 / WU-L1 already landed:** `assets/manifest.py` states verbatim *"the S3FD face-detector weight (`sfd_face.pth`, formerly asset `lightasd-s3fd`) was REMOVED — it shipped under NO license … YuNet asset (`yunet-face-detection`) via `cv2.FaceDetectorYN`"*; `git grep -i s3fd origin/main` returns **zero live code refs**. Tier B's face-crop stage already has a permissive (MIT) detector in-tree. *(The older re-hosting dossier that lists S3FD as a live G-5 target is STALE — this plan is correct.)*
> - **Qwen3-4B GGUF is ALREADY provisioned** (`QWEN_ASSET_NAME="qwen3-4b-gguf"`, pinned commit `bc640142…`, sha256, `Qwen/Qwen3-4B-GGUF`, `license:apache-2.0`). So WU-A1's Gemma→Qwen3 swap is a **zero-new-download drop-in** on the same llama.cpp `ModelRunner` (whose `start_server` is model-identity-aware). **Correction to the source design:** MADLAD-400 is a **T5 enc-dec** needing a **separate CT2/ONNX runner seam** — it does NOT "drop onto llama.cpp." Lead the swap with **Qwen3-4B (drop-in)**; treat MADLAD as the language-coverage upgrade behind a new seam.
> - **MuseTalk license, verbatim:** its README says *"The trained model are available for any purpose, even commercially"* and *"The code of MuseTalk is released under the MIT License"*, yet the HF metadata tag is `creativeml-openrail-m` (use-restricted, behavioral clauses flow down to end-users). **The tag governs** for a strict MIT/Apache/BSD commercial mandate → Tier B stays a commercial blocker (personal-tier only). Reconcile the tag-vs-README conflict in writing before any commercial lip-sync ship.

---

## 0. Flagship identity (MEDIUM confidence — carry as caveat #1)

"Unknown" arrived as an **unsubstituted template placeholder** — the locked v1.5 codename never got written into the task. The upstream design infers (two independent research streams converging) that it is the **"Fully-local AI Dubbing / Voiceover (+ optional lip-sync)"** flagship. My independent verification agrees this inference is the highest-value reading:

- The sidecar **already ships a translate → TTS dub with no lip-sync** (`sidecar/media_studio/features/tts/`), so "dubbing" is the one v1.5 flagship that is ~85% built and needs *reconcile-not-rebuild*.
- The task's specific warning — *"TTS/voice-clone/lip-sync weights are NC like the no-license S3FD"* — **only fits dubbing**. No other v1.5 candidate (clip-finding, auto-zoom, caption gallery) is a licensing minefield.

**Action:** proceed on the dubbing reading. **Re-dispatch only if** the locked codename was actually clip-finding / auto-zoom / caption-gallery. Dubbing is the single flagship where the licensing analysis is load-bearing, so this work is high-value regardless.

---

## 1. VERDICT — `go-with-caveats` (two-tier: Tier A GO, Tier B COMMERCIAL BLOCKER)

| Tier | Feature | Verdict | Why |
|---|---|---|---|
| **A** | **AI Dubbing** (translate → TTS/voice-clone → ±15%-aligned WAV → AAC → muxed selectable AudioTrack) | **GO** | ~85% built + `origin/main`-verified; every shipping model is **permissive (MIT/Apache) and local**; the *only* commercial-blocking change is swapping the in-tree Gemma MT tier for Qwen3/MADLAD (Apache) behind the existing seam. |
| **B** | **Lip-Sync** (re-lip the on-screen mouth to the dub) | **COMMERCIAL BLOCKER** → personal/non-commercial only, feature-flagged **OFF** in the commercial build | As of 2026-07 there is **NO permissive (MIT/Apache/BSD) video-relip model** — verified live. |

**Not `no-go-licensing`**, because the flagship itself (Tier A) has a complete permissive + local path after one bounded swap. It is **not plain `go`**, because (a) the current shipping path still ships the **Gemma-licensed** MT tier (a real blocker that must be remediated first), and (b) an entire sub-feature (Tier B) cannot ship commercially at all.

A fresh reviewer must be able to confirm two things; both hold:
1. **Models are permissive + local** — yes for Tier A (Kokoro Apache, Chatterbox MIT, Qwen3 Apache, MADLAD Apache, Whisper MIT, YuNet MIT), *after* the Gemma→Qwen3 swap. NC/gated/no-license models are enumerated and quarantined.
2. **The plan is real-functional-verifiable** — yes: the pure pipeline is unit-tested to 100% branch with **deterministic fakes (not mock-sandwiches)**, and a **separate real-footage @e2e golden** (real weights + real ffmpeg, measuring ±15% alignment / MT similarity / SyncNet confidence) is the *actual* DONE bar, excluded from the coverage number.

---

## 2. Architecture as-built (verified against `origin/main`)

The dub pipeline is present and complete. Evidence (all read from `git show origin/main:<path>`):

| File | What it is (verified) |
|---|---|
| `sidecar/media_studio/features/tts/dub.py` | `run_dub_pipeline` — the **frozen A4 batched order**: translate-ALL → **free MT** → synth-ALL → align (±15%) → concat WAV → AAC → mux. `DubService.dub_start` handler. Wire: `tts.dub.start({videoId,trackId,engine,voice?,sampleId?,targetLang?}) → {jobId} → job.done {audioTrack, path}`. **All heavy work is injected** (`translator_factory`, `engines` map, `run`/`duration`, `audio_tracks`, `voice_store`). Branch handling already present: translate-fail→surface (`raise DubError`), MT-free-in-`finally`, `raise_if_cancelled` at each stage, offline guard *before* job spawn, empty-track, count-mismatch, AAC-fail. |
| `.../tts/engine.py` | `TtsEngine` ABC + `synth(cues,voice,lang,out_wav,*,rate=1.0)`; 3 impls (kokoro/edgetts/chatterbox). Stdlib WAV helpers (no numpy needed for tests). |
| `.../tts/kokoro.py` | Default engine = **kokoro-onnx** (onnxruntime, never torch). Pinned GitHub release assets (`kokoro-v1.0.onnx` + `voices-v1.0.bin`), sha256-verified. |
| `.../tts/chatterbox.py` | Voice-clone via **isolated py3.14 CUDA subprocess env** (torch stays OUT of the py3.12 sidecar). `chatterbox-tts==0.1.7`. Ships the inaudible Perth watermark. |
| `.../tts/edgetts.py` | Hosted engine, labeled ONLINE, offline-guarded (refused synchronously before any cue text egresses). |
| `.../tts/align.py` | **FROZEN ±15% recipe**: `ATEMPO_MIN=0.85`, `ATEMPO_MAX=1.15`; pure math (`atempo_factor`, `plan_cue`, `concat_plan`) + injectable ffmpeg; overrun re-flows, never clips. |
| `.../tts/voices.py` | `VoiceStore`; `VoiceSample={id,name,path,durationSec}` — **no consent field yet**; `tts.voices` (union of catalog + cloned samples) / `tts.sample.add` — **no consent gate yet**. |
| `.../models/translation.py` | `TieredTranslator`. **tier1/tier2 = TranslateGemma-4B/12B GGUF (`license:gemma` — BLOCKER)**, tier3 = hosted. `get_translator()` is the factory the dub duck-types. Routing table + fallback chain are clean and model-agnostic. |
| `.../handlers/composition.py` (L296-330) | `_tts.register(...translator_factory=svc._dub_translator...)` — feature-owns-`register()` pattern; **extend, don't rewrite**. |
| `.../handlers/_capabilities.py` | `FeatureSpec` readiness pattern + the **reframe invariant** (core weight always-on; enhancements are SEPARATE loud "download to improve" items, never a silent degrade/block). The template for a `dub` capability. |
| `.../models/consent.py` | An **egress** consent gate (text/frames per-provider) with a typed `ConsentError` + default-deny. This is the *pattern* to mirror for voice-clone consent — but it is NOT itself a voice-clone gate. |

### The #282 schema-first contract (path correction confirmed)
The merged contract lives at **`sidecar/contract/spec.py`** (NOT `sidecar/media_studio/contract/`), with:
- `spec.py` — single source of truth: `MethodSpec`, `DATA_MODELS`, dataclass param/result models, `METHODS` (6 POC methods; **`tts.*` are absent — still on the pre-#282 imperative `protocol.register` path**). `Binding` = NONE/NAMED/SPREAD. Field names are **frozen camelCase** (N815 suppressed).
- `schema.py` — dataclass → JSON Schema + TS. Supported types: `str·int·float·bool·X|None·list[X]·dict[str,X]·nested dataclass`; anything else raises `UnsupportedTypeError` (fails loud). **Every field this plan adds is within that set** (incl. the nested `AudioTrack` inside `DubResult`).
- `generate.py` — emits `contract.schema.json` + 3 TS files; **`contract-source-sha256` drift gate** (`python -m contract.generate --check`) fails CI if `spec.py` changed without regeneration.
- `registry.py` / `validate.py` — `validate_request()` is a **no-op for unmodeled methods** (additive rollout), so migrating `tts.*` is safe before the dispatch validator switches on.

### Already-landed win (#287 — `WU-L1`)
The no-license **S3FD** face weight was **removed** and replaced with **MIT YuNet** (`yunet-face-detection`, `opencv/face_detection_yunet`, `cv2.FaceDetectorYN`). This means Tier B's face-crop stage can reuse a **permissive, already-vendored** detector — the design's "route face detection through YuNet, never S3FD" is already true in-tree.

---

## 3. EXACT models to adopt — with licenses (authoritative HF Hub tags, verified 2026-07-12)

### 3.1 PERMISSIVE (MIT / Apache) — GO for the commercializing owner

| Model (repo) | Role | License (HF tag) | Local? | State |
|---|---|---|---|---|
| **Kokoro-82M** (`hexgrad/Kokoro-82M`) | TTS default (CPU, onnx) | **apache-2.0** | ✅ CPU-viable | already wired |
| **Chatterbox** (`ResembleAI/chatterbox`) | voice-clone TTS (GPU, 23 langs) | **mit** | ✅ optional-GPU | already wired; ships MIT Perth watermark = provenance plus |
| **Qwen3-4B** (`Qwen/Qwen3-4B`) | MT tier1 (prompt-based via GGUF, llama.cpp) | **apache-2.0** | ✅ | **Gemma swap-in** |
| **MADLAD-400-3B-MT** (`google/madlad400-3b-mt`) | MT coverage (400+ langs, T5 enc-dec) | **apache-2.0** | ✅ (CT2/ONNX or GGUF) | coverage upgrade |
| **faster-whisper-large-v3** (`Systran/faster-whisper-large-v3`) | source ASR (produces the cue track the dub consumes) | **mit** | ✅ | unchanged |
| **YuNet** (`opencv/face_detection_yunet`) | face detect (Tier B crop) | **mit** | ✅ | already vendored (#287) |
| **Piper** (`rhasspy/piper-voices`) | *optional* CPU TTS breadth | **mit** (repo) | ✅ | optional — verify per-voice dataset license before shipping a specific voice |
| **MeloTTS-English** (`myshell-ai/MeloTTS-English`) | *optional* CPU TTS breadth | **mit** | ✅ | optional |
| **OpenVoiceV2** (`myshell-ai/OpenVoiceV2`) | *optional* instant voice-clone | **mit** | ✅ | optional (V1 was CC-BY-NC; V2 is MIT — confirmed) |
| **OpenF5-TTS-Base** (`mrfakename/OpenF5-TTS-Base`) | *optional* F5-class, permissive | **apache-2.0** | ✅ | optional — use instead of the CC-BY-NC official F5 |

**Correction to the upstream design:** **Opus-MT** (`Helsinki-NLP/opus-mt-*`) is **`cc-by-4.0`, NOT MIT.** CC-BY-4.0 permits commercial use *with attribution* but is **outside the strict MIT/Apache/BSD gate** the owner mandated. **Recommendation: drop Opus-MT** (Qwen3 + MADLAD + Chatterbox already cover language breadth); if adopted, it needs an explicit attribution-compliance decision, not a silent "MIT" assumption.

### 3.2 COMMERCIAL BLOCKERS — HARD-AVOID in the commercial build (never enter the manifest)

| Model | Role | License (HF tag) | Verdict |
|---|---|---|---|
| **TranslateGemma-4B/12B** (in-tree tier1/tier2; `mradermacher/translategemma-*-GGUF`, base `google/translategemma-*-it`) | MT | **gemma** — "Open Weights", **NOT OSI/permissive**; **gated**; Prohibited-Use Policy; **downstream pass-through** obligation; Google may modify/terminate | **BLOCKER in the CURRENT shipping path** — must swap to Qwen3/MADLAD |
| **XTTS-v2** (`coqui/XTTS-v2`) | voice-clone | **other** (Coqui CPML, non-commercial) | BLOCKER (Coqui defunct) |
| **F5-TTS official** (`SWivid/F5-TTS`) | TTS | **cc-by-nc-4.0** | BLOCKER — use OpenF5 (Apache) |
| **NLLB-200** (`facebook/nllb-200-*`) | MT | **cc-by-nc-4.0** | BLOCKER — the tempting "one-model-dub" trap |
| **SeamlessM4T-v2** (`facebook/seamless-m4t-v2-large`) | speech-to-speech / MT | **cc-by-nc-4.0** | BLOCKER — the other one-model-dub trap |
| **MuseTalk** (`TMElyralab/MuseTalk`) | video relip | **creativeml-openrail-m** (use-restricted) | BLOCKER — Tier B (README prose claims "commercial ok"; the **authoritative HF tag is openrail-m** — the tag governs) |
| **LatentSync** (`ByteDance/LatentSync`) | video relip | **openrail++** (use-restricted) | BLOCKER — Tier B |
| **Wav2Lip** (`Rudrabha/Wav2Lip`) | video relip | **non-commercial / research only** (README) | BLOCKER — Tier B ("for HD commercial model, try Sync Labs") |
| **S3FD** (no-license) | face detect | **NO LICENSE** | already REMOVED in #287 → MIT YuNet |

### 3.3 The load-bearing negative (Tier B): NO permissive video-relip model exists (2026-07)
Verified three independent ways:
1. HF model search, `license:apache-2.0` + lip-sync/talking-face/dubbing → **zero repositories**.
2. HF model search, `license:mit` + lip-sync/talking-head/video-dubbing → **zero repositories**.
3. The three known video-relip models are all non-permissive (MuseTalk openrail-m, LatentSync openrail++, Wav2Lip non-commercial-research).

The permissive avatar-animation models (LivePortrait = MIT, SadTalker = Apache) are the **WRONG architecture** — they synthesize a talking head from a *still image* and **discard the real footage**; they do not re-lip the actual speaker. So even the permissive options cannot do Tier B's job. **Conclusion: Tier B has no commercial path** and ships personal-only, flag-OFF.

### 3.4 Pipeline-dependency diligence (a model's own license ≠ its inference graph clear)
This is the exact trap the dossier caught with S3FD. Before the commercial claim is final:
- **Kokoro** phonemizes via **espeak-ng (GPLv3)**. Verify the sidecar's kokoro-onnx path invokes espeak-ng **as a separate process** (or ships a non-GPL phonemizer / bundled token dict) rather than statically linking `libespeak-ng`. Weights are Apache; the *phonemizer* is the diligence item.
- **Piper** repo is MIT but **individual voices carry their own dataset licenses** — clear each shipped voice per-voice.
- Any MuseTalk-class relip (personal tier) still pulls **S3FD (no-license)**, dwpose, a VAE, and NC testdata — **route ALL face detection through the vendored MIT YuNet** and audit every helper artifact per-file (safetensors, sha256-pinned, verify-before-load).

---

## 4. Work units (id / title / scope) — keystone-first, reconcile-don't-rebuild

> Sequence follows the design's keystone-first order. `WU-U0` and `WU-A1` are the load-bearing keystones (a green baseline + the license remediation that unblocks the shipping path). Tier B (`WU-B1`) is deliberately **last** and gated.

### WU-U0 — Reconcile to `origin/main` + green 100%-branch baseline *(keystone prerequisite)*
Fetch/reconcile the local checkout to `origin/main` (it lacks `sidecar/contract/` from #282 and #287's YuNet swap). Read all #282-touched files via `git show origin/main:<path>`. Run the sidecar suite + `.coverage-thresholds.json` enforcement + `python -m contract.generate --check` to establish a **green baseline before touching any file**. No feature code. **Gate:** coverage clean + drift gate OK.

### WU-A1 — MT license remediation: TranslateGemma → Qwen3 / MADLAD *(the shipping-path blocker fix; keystone)*
Behind the **existing `TieredTranslator` seam** in `models/translation.py` (no pipeline rewrite): replace the tier1/tier2 **Gemma** GGUF registration + routing with permissive Apache picks:
- **tier1 = Qwen3-4B GGUF (Apache)** — prompt-based MT reusing the existing `build_messages` system/user shape through the same llama.cpp `ModelRunner`. *Confirm whether a Qwen3-4B GGUF is already provisioned as the general-LLM asset (reuse = zero new download); otherwise register a new Apache-licensed pin (still permissive, possibly a new download).*
- **tier2 / coverage = MADLAD-400-3B (Apache, 400+ langs)** behind a **CT2/ONNX runner seam** (T5 enc-dec — NOT llama.cpp; a GGUF exists but the CT2 path is the proven one).
- Add an `mtModel` selector (`qwen3` | `madlad` | `opus`-off-by-default).
- **De-register the Gemma assets from the commercial manifest** (personal tier may retain them). New `url`+`sha256`+`commit` pins for the Apache artifacts.
- Keep the routing table + fallback chain unchanged.
- **TDD:** fakes for runner/provider; branches = tier routing, GGUF/CT2 resolution, fallback ordering, MT-free-on-error, mismatched-count, unknown-tier. **Functional gate (WU-A7):** a golden translate on a known sentence pair via the **real** Qwen3 GGUF.

### WU-A2 — Voice-clone CONSENT gate *(legal keystone)*
Extend `VoiceSample` → `{id,name,path,durationSec,consentAttested,consentAt,consentNote}`. Add required `consentAttested:bool` + optional `consentNote` to `tts.sample.add`; `make_sample_add_handler` **rejects add when `consentAttested` is not `True`** (new `INVALID_PARAMS` branch) and persists `consentAt` (timestamp) + `consentNote` into the `voices.json` row. `normalize_sample` backfills legacy rows (`consentAttested` default `False`). Add `tts.sample.list` / `tts.sample.remove` (manage + delete clones and their consent records). Mirror `models/consent.py`'s typed-refusal / default-deny idiom. **TDD:** add-without-consent → typed refusal; add-with-consent → row carries `consentAt`; list/remove; legacy-row backfill.

### WU-A3 — Migrate the `tts.*` surface onto the #282 contract (`spec.py`)
Add to `sidecar/contract/spec.py`:
- **DATA_MODELS (dataclasses, frozen camelCase):**
  - `AudioTrack {id:str, path:str, lang:str, name:str, voice:str|None, isAiGenerated:bool}`
  - `VoiceSample {id, name, path, durationSec, consentAttested:bool, consentAt:str|None, consentNote:str|None}`
  - `Voice {id:str, engine:str, lang:str, name:str}` + `VoiceListResult {voices:list[Voice]}`
  - `DubResult {audioTrack:AudioTrack, path:str}` (nested dataclass — supported by `schema.py`)
- **Param models:** `DubStartParams {videoId, trackId, engine, voice:str|None, sampleId:str|None, targetLang:str|None}`; `SampleAddParams {path, name:str|None, consentAttested:bool, consentNote:str|None}`
- **MethodSpecs:** `tts.dub.start` (`binding=NAMED`, `kind='job'`, `result_ts='JobHandle'` via the `_HAND` import like `shortmaker.select`; job.done resolves `DubResult`; **`needs_key=False`** — keep dub fully-local so it stays False); `tts.voices` (`binding=NONE`, `kind='direct'`, `VoiceListResult`); `tts.sample.add` (`NAMED`, `direct`, `{sample:VoiceSample}`); `tts.sample.list`; `tts.sample.remove`; and the proofread step (`tts.dub.preview` job that runs stage-1 translate-only and returns editable cues WITHOUT synth — or declare reuse of the existing `subtitles.translate`).
- Run `python -m contract.generate` to regenerate all 4 artifacts + satisfy the **sha256 drift gate**. **Keep the hand `_require_str` checks** in `dub.py`/`voices.py`/`_shared.py` until `registry.validate_request` switches on in the migration's later wave (coexist by design). **TDD:** contract-parity test, `--check` green, generated TS/`MethodName` union carries the new methods.

### WU-A4 — Settings surface + parity
Add to **both** `spec.Settings` **and** `settings_store.DEFAULT_SETTINGS` (a parity test asserts they agree): `dubEngine:str|None='kokoro'`, `dubTargetLang:str|None`, `dubSampleId:str|None`, `mtModel:str|None='qwen3'`, `requireVoiceConsent:bool|None=True`, `labelAiAudio:bool|None=True`, `c2paOnExport:bool|None=False`, and (personal-only) `lipSyncEnabled:bool|None=False`. Regenerate the contract. **TDD:** parity test, settings validation (bool/str type checks via `validate.py`).

### WU-A5 — Dub readiness capability (reframe invariant, point-of-use)
Add `FeatureSpec(capability='dub', core=True, assets=('kokoro-v1.0-onnx',...))` to `handlers/_capabilities.py`: **Kokoro READY on its always-on weight**; Chatterbox-env / MADLAD are **SEPARATE loud "download to improve" `assets.ensure` items** — never a silent degrade, never a block (the reframe invariant). Map new Phase components in `_wire.py` `_COMPONENT_ASSETS`. **TDD:** dub ready with kokoro-only; chatterbox missing → `needsDownload`; offline → `unavailable` but the local (kokoro) path still works.

### WU-A6 — "Localize / Dub" UI phase (redesigned phase-rail)
Insert a **Localize / Dub** phase between Caption and Export in the redesigned editor, inheriting the *preview-it/correct-it/nothing-baked-until-Export* pattern (the non-destructive selectable AudioTrack + audition-before-mux maps to it exactly):
- Target-language picker (driven by the permissive translator's coverage table) → kicks the **translate-only proofread**, not a full render.
- **Editable proofread transcript** (per-cue, pre-synth) — where dub quality is actually saved.
- Engine picker with **readiness badges** (Kokoro CPU default / Chatterbox voice-clone GPU-download / optional Piper·MeloTTS CPU) — **EdgeTTS shown ONLY as an explicit "Online" opt-in with an egress warning**.
- Voice picker (built-in catalog ∪ the user's cloned samples; sample id doubles as `sampleId`).
- **Clone-a-voice flow** → file picker → **BLOCKING consent attestation checkbox** ("I own this voice or have written consent to clone it") → optional note → `tts.sample.add`. The checkbox is a first-class gate; add is refused without it.
- **Per-speaker voice assignment** (ties to the active-speaker diarization flagship — guards the competitors' #1 dub-quality killer: wrong speaker count / voice bleed).
- **Audition-before-mux** + original/dub non-destructive toggle.
- **AI-content label** on the dub track + export-time C2PA toggle (Reframe already has a c2patool path) + surface Chatterbox's Perth watermark.
- Job progress (translate/synth/align/assemble bands) + cooperative cancel; failure surfaces the actionable error (e.g. missing MT model → the "download model" readiness item), never a silent stall.
- Consumes the generated **typed client**. **TDD (renderer):** consent checkbox gates the add button; audition plays the WAV; offline refuses hosted engines.

### WU-A7 — Real-footage @e2e golden *(the DONE bar — EXCLUDED from the 100%-branch gate)*
An opt-in `@e2e` tier (marker-gated, real weights, real ffmpeg) that proves *coverage != integration*: a golden interview clip with a known source transcript + a target-language reference voice runs the **real** dub (real Qwen3 MT + real Kokoro/Chatterbox synth + real ffmpeg align/mux) and asserts: (a) translation matches the golden within a similarity threshold; (b) **each dub cue's alignment is inside ±15%**; (c) the muxed AudioTrack is selectable and full-length. Plus a standalone MT golden (sentence pair) and a synth golden (measured duration). This is what catches "green mocked tests but robotic/mistimed audio."

### WU-B1 — *(PERSONAL BUILD ONLY)* Lip-sync module — feature-flagged OFF in commercial
NET-NEW, and explicitly **last + gated**. Follows the repo's pure-core + lazy-Protocol-backend idiom:
- `features/tts/lipsync.py` (pure) + `lipsync_backend.py` (`# pragma: no cover`, ALL torch/diffusers/cv2 imports inside, **isolated GPU subprocess env — never the main py3.12 onnx sidecar**).
- Stages: per-frame face crop via the **vendored MIT YuNet (NOT S3FD)** → audio-conditioned mouth-region latent inpaint (MuseTalk-class) → paste-back → re-encode/re-mux. **Consumes Tier A's muxed dub AudioTrack + the source video.**
- Wire: `tts.lipsync.start({videoId, audioTrackId, faceTrackId?, quality?, likenessConsentAttested})` → `{path, syncConfidence}`; **required `likenessConsentAttested:bool`** ("I have the right to modify this person's on-screen likeness" — the higher-risk act gets the higher bar).
- **MuseTalk weights are openrail-m** → pinned ONLY in the **personal-tier** manifest behind a license-acceptance gate; **never** in the commercial default asset set. In the **commercial build** the `tts.lipsync.start` MethodSpec is **absent OR the handler hard-refuses** (flag OFF); `lipSyncEnabled` stays `False`/absent.
- **Functional gate:** a **SyncNet / LSE-C confidence score across the WHOLE timeline** (never a decorative single-frame check), in the `@e2e` tier.

---

## 5. Consent / ethics gate (MANDATORY — this flagship manipulates a person's voice, words, and face)

Aligned with **EU AI Act Article 50** transparency duties and standard practice (HeyGen/Captions require voice-ownership + written consent; Descript gated Overdub behind consent). Three attachment points:

1. **Voice-clone consent (WU-A2, primary, NEW):** `tts.sample.add` gains a required `consentAttested` + a BLOCKING UI attestation; the handler refuses to store a clone without it and persists a local consent record (`consentAttested + consentAt + consentNote`). No cloning is possible without a stored attestation.
2. **Likeness consent (WU-B1, personal build):** `tts.lipsync.start` gains a required `likenessConsentAttested` with an even more explicit gate; the module additionally carries the OpenRAIL-M / S3FD non-commercial notice. Modifying a real face is the higher-risk act → higher bar.
3. **AI-content disclosure (all output):** the dub AudioTrack is `isAiGenerated`; the UI shows an "AI-generated audio" badge; export offers an opt-in **C2PA** provenance manifest; Chatterbox's inaudible **Perth** watermark is retained and surfaced.

**Scope discipline:** the gate does NOT police the *content* of speech — it gates the *act* of cloning/re-lipping without attested consent and labels the result. Because the pipeline is fully **local**, "no shared-voice training, no third-party data use, no cue-text egress" holds by construction, and all consent records stay on the device (a decisive trust differentiator vs cloud dubbers). Settings `requireVoiceConsent` (default `True`) / `labelAiAudio` (default `True`); disabling them is a conscious, logged user choice, never the default.

---

## 6. 100%-coverage testing strategy for ML-boundary code (deterministic, not mock-sandwich)

The architecture already embodies the right shape (pure core + injected seams). The strategy makes that *functionally* verifiable rather than a green-but-hollow number:

**(1) Two-layer split.**
- **PURE deterministic core** — alignment math (`atempo_factor`/`plan_cue`/`concat_plan`), routing table + fallback chain, prompt build (`build_messages`), the consent predicate, the timeline planner. Tested to **100% branch with NO mocks**: real inputs, real assertions. Fully deterministic by construction.
- **BOUNDARY orchestration** — `dub_start`, `run_dub_pipeline`, `_tier_provider`, the consent handler. Tested with **deterministic FAKES that implement the seam Protocol**, not `MagicMock`.

**(2) Fakes produce REAL artifacts, so wiring bugs actually fail.** A `FakeEngine.synth` writes a **real silent WAV of a computed duration** (e.g. `duration = len(cue.text) * k`); a `FakeTranslator.translate` returns deterministic strings + records that `free()` ran; a `FakeRun` writes a real output file and returns an exit code. Because each stage consumes the previous stage's real bytes, a dropped cue / wrong arg order / mis-ordered stage is caught — the fake feeds the *actual* ±15% aligner and concat writer.

**(3) The anti-mock-sandwich rule.** Never assert "the mock was called with X." Assert on the **observable output**: the produced WAV duration lands in the ±15% window; the concat plan places cue *i* at its subtitle `start`; the `AudioTrack` row carries the right `lang`/`isAiGenerated`; a consent-less `tts.sample.add` raises the typed `INVALID_PARAMS`. This is the difference between "green" and "works."

**(4) Every boundary BRANCH is a named test** (the branches already exist in `dub.py`): translate-fail→surface, **MT-free-on-error (the `finally`)**, cancel at each of the four stages, offline-guard refusal (before job spawn), empty-track, translator count-mismatch, AAC-encode-fail, unknown-engine, missing-`sampleId` (chatterbox), consent-refused, legacy-row backfill. Driving these with deterministic fakes yields **100% branch on the pure + orchestration layers** — which is how `.coverage-thresholds.json` (100% lines/branches/functions/statements) is met.

**(5) The FUNCTIONAL gate is SEPARATE and EXCLUDED from the coverage number** — this is the honest answer to "green mocked tests != works." `WU-A7`'s real-footage `@e2e` golden runs the **real** models + **real** ffmpeg and measures robust metrics: MT similarity to a golden, alignment inside ±15%, and (lip-sync) SyncNet/LSE-C confidence **across the whole timeline**. Coverage proves every branch is reachable and correct on deterministic inputs; the golden proves the real weights produce usable audio. **Both are required for "done"; neither substitutes for the other.**

**(6) `# pragma: no cover` is confined to the true backend edge** — the `chatterbox_runner` subprocess body and `lipsync_backend.py` (the code that imports torch/diffusers/cv2 inside the isolated env), exercised only by `@e2e`. The pure + orchestration layers *around* them hit 100% branch via fakes. This matches the existing repo idiom (subprocess-isolated chatterbox; lazy saliency/scene backends).

**(7) Determinism controls for stochastic engines:** seed Chatterbox in `@e2e`; assert on windows/thresholds/floors (duration bands, similarity ≥ τ, confidence ≥ c), never bit-exact audio. The pure layer needs no seeding — it is deterministic.

---

## 7. Commercial blockers (summary — the `commercialBlockers` list)

1. **Tier B lip-sync has NO permissive video-relip model** (2026-07, triple-verified): MuseTalk = OpenRAIL-M, LatentSync = OpenRAIL++, Wav2Lip = non-commercial-research; HF has **zero** Apache/MIT lip-sync models; the permissive alternatives (LivePortrait/SadTalker) are the wrong architecture (avatar-from-photo). → Tier B ships personal-only, flag-OFF; its OpenRAIL weights never enter the commercial manifest.
2. **In-tree MT tier is Gemma-licensed** (`translategemma-4b/12b` = `license:gemma`: Open Weights, NOT OSI/permissive, gated, Prohibited-Use Policy + downstream pass-through). It is a blocker in the *current shipping path*; **must swap to Qwen3-4B/MADLAD-400 (Apache)** before the "permissive commercial" claim holds (WU-A1).
3. **The one-model-dub trap** — NLLB-200 + SeamlessM4T = CC-BY-NC; XTTS-v2 = CPML-NC; official F5-TTS = CC-BY-NC. HARD-AVOID; enforce a **MIT/Apache/BSD gate at the manifest** so no NC weight can ever be pinned into the commercial build.
4. **Pipeline-dependency licenses ≠ headline weight** — Kokoro's espeak-ng phonemizer is GPLv3 (verify separate-process invocation); Piper voices carry per-voice dataset licenses; any MuseTalk-class relip still pulls S3FD (no-license), dwpose, a VAE, NC testdata → route face detection through MIT YuNet and audit every helper per-file.
5. **Opus-MT is CC-BY-4.0, not MIT** — outside the strict MIT/Apache/BSD gate; drop it, or make an explicit attribution-compliance decision.
6. **Flagship identity is MEDIUM confidence** — "Unknown" was an unsubstituted placeholder; re-dispatch if the locked codename was clip-finding / auto-zoom / caption-gallery rather than AI dubbing.
7. **Legal exposure (EU AI Act Art. 50 + impersonation/deepfake)** — mitigated by the mandatory voice/likeness consent gates + AI-content labeling + C2PA/Perth, but a legal-review checkpoint is warranted before GA.

---

## 8. Sequencing (keystone-first)

```
WU-U0  reconcile + green baseline ─┐  (keystone: nothing else starts until green)
WU-A1  MT Gemma→Qwen3/MADLAD ──────┤  (keystone: unblocks the shipping path)
WU-A2  voice-clone consent gate ───┤  (legal keystone)
WU-A3  contract migration (spec.py)┤  (unblocks typed UI + validators)
WU-A4  settings + parity ──────────┤
WU-A5  dub readiness capability ───┤
WU-A6  Localize/Dub UI phase ──────┤
WU-A7  real-footage @e2e golden ───┘  (the DONE bar; gates default-promotion)
WU-B1  personal lip-sync (flag OFF in commercial) ── LAST, gated
```

**Pre-PR:** run `/self-reflect` + commit knowledge-base updates so learnings land atomically with the code; verify coverage vs `.coverage-thresholds.json`; run the applicable quality/security gates.

---

## 9. Sources (licenses verified 2026-07-12)

HF Hub authoritative tags: `hexgrad/Kokoro-82M` (apache-2.0) · `ResembleAI/chatterbox` (mit) · `Qwen/Qwen3-4B` (apache-2.0) · `google/madlad400-3b-mt` (apache-2.0) · `Systran/faster-whisper-large-v3` (mit) · `rhasspy/piper-voices` (mit) · `myshell-ai/MeloTTS-English` (mit) · `myshell-ai/OpenVoiceV2` (mit) · `mrfakename/OpenF5-TTS-Base` (apache-2.0) · `Helsinki-NLP/opus-mt-en-de` (**cc-by-4.0**) · `coqui/XTTS-v2` (other/CPML) · `facebook/nllb-200-distilled-600M` (cc-by-nc-4.0) · `facebook/seamless-m4t-v2-large` (cc-by-nc-4.0) · `SWivid/F5-TTS` (cc-by-nc-4.0) · `TMElyralab/MuseTalk` (creativeml-openrail-m) · `ByteDance/LatentSync` (openrail++) · `mradermacher/translategemma-4b-it-GGUF` + `google/gemma-3-4b-it` (**gemma**, gated). Gemma-license analysis: mindstudio.ai, wcr.legal, the-decoder.com. Wav2Lip non-commercial: github.com/Rudrabha/Wav2Lip. Tier-B negative: HF model search (apache-2.0 / mit + lip-sync) → zero repositories. Code: `origin/main` `sidecar/media_studio/features/tts/*`, `sidecar/contract/*`, `sidecar/media_studio/handlers/*`, `sidecar/media_studio/models/translation.py`, `.../assets/manifest.py` (#287 YuNet).

---

## 10. Addendum — third-pass deep-dive (net-new verified mechanics; MuseTalk README + source fetched 2026-07-12)

This addendum ADDS to §1-§9 (does not supersede them). It records implementation-critical details a third independent reviewer verified from `origin/main` source + the MuseTalk README/GitHub.

**A. Contract mechanics (precise, so the migration WUs are exact).** `spec.py` is a **5-method POC slice** (`ping`, `library.add`, `settings.get/set`, `shortmaker.select`, `providers.revealKey`); `tts.*` are runtime-only. `registry.validate_request` is **NOT yet wired into dispatch** (migration Wave 2d) → declaring a method in `spec.py` buys **generated TS + drift protection only, NOT runtime param validation**. Therefore every new method must be **BOTH** declared in `spec.py` (regenerate) **AND** registered at runtime via the Style-B `register()` → `handlers/composition.py::register_all` (the `tts` block sits at ~L296-330; the asset side-effect imports at ~L535-547). New `str`-enum-like params (`faceDetect`, `quality`, `rightsBasis`) MUST be **plain `str`, never `Literal`/`Enum`** — `schema.py`'s introspector raises `UnsupportedTypeError` on anything outside `str·int·float·bool·X|None·list[X]·dict[str,X]·nested-dataclass` until migration Wave 1. **Settings parity is THREE places, not two:** a new scalar setting must land in (1) `spec.Settings`, (2) `settings_store.DEFAULT_SETTINGS` (same default), AND (3) the parametrized `_PARITY_KEYS` list in `test_contract_parity.py::test_settings_defaults_match_default_settings` — or the parity/drift gate fails.

**B. MuseTalk personal-tier re-host is a MULTI-component job, not one weight (the README names the graph).** Verbatim README: *"Other open-source models used must comply with their license, such as whisper, ft-mse-vae, dwpose, S3FD, etc."* + *"Test data is restricted to non-commercial research only."* Per-component re-host + license (all safetensors, sha256-pinned, verify-before-load, in the **personal manifest only**):

| Component | Role in MuseTalk | License (verified) | Action |
|---|---|---|---|
| MuseTalk 1.5 UNet (`musetalkV15/unet.pth`) | mouth-only latent inpaint | **creativeml-openrail-m** (tag governs) | personal-tier only, license-acceptance gate |
| sd-vae-ft-mse (`stabilityai/sd-vae-ft-mse`) | VAE encode/decode | **MIT** (safetensors on HF) | re-host clean |
| whisper-tiny (`openai/whisper-tiny`) | audio feature encoder | **Apache-2.0** *(design + §3 said "MIT" — CORRECTION: it is Apache-2.0)* | re-host clean |
| BiSeNet / face-parsing (`zllrunning/face-parsing.PyTorch`) | mouth-region composite mask | **MIT** (verify at re-host) | re-host, verify |
| DWPose | face landmarks/pose | **Apache-2.0** (verify weight/data provenance) | **verify need — likely DROPPABLE for mouth-only** |
| S3FD | face detect (bundled) | **NO LICENSE** | **NEVER pull** → route through vendored MIT YuNet |
| YuNet (`opencv/face_detection_yunet`) | face detect (replacement) | **MIT** | already vendored (#287); reuse bbox |

**C. YuNet bbox reuse is already true in-tree (S3FD genuinely never needed).** `reframe_multispeaker_backend._stage_visual` already runs `cv2.FaceDetectorYN` and returns per-frame `(x, y, w, h)` boxes (via `_lightasd_infer.analyze_visual`). The lip-sync stage feeds MuseTalk THAT bbox — the "route face detection through YuNet, never S3FD" design point is not aspirational, it is a reuse of shipped code.

**D. `musetalk-env` interpreter decision (a real fork, must be resolved in WU-B1).** `assets/manifest.py::PYTHON_KINDS` is only `("host", "chatterbox")`. `chatterbox-env` pins `torch==2.10.0+cu128` on a dedicated **py3.14** embed (`python_kind="chatterbox"`). Before pinning `musetalk-env`, verify MuseTalk 1.5's real torch/diffusers closure: **(a)** if it resolves against torch 2.10 → reuse the `chatterbox` py3.14 interpreter with a SEPARATE `dest` env dir; **(b)** else add a new `PYTHON_KIND="musetalk"` + a third embed (extend `PYTHON_KINDS` + the manager's interpreter resolver). No loose specifiers (A6 lesson 5); ship a hashed lockfile.

**E. GPU-job guarantees come free from `JobRegistry` (verified in `jobs.py`).** Pass `gpu=True` at `ctx.jobs.start`: bounded pool (2 concurrent, `max_gpu_workers=1` serializes gpu jobs so lip-sync never co-resides with another heavy model), per-job **30-min watchdog**, cooperative `raise_if_cancelled` between chunks, and **INTERRUPTED** rehydrate on mid-flight process exit. Staged `release()` between models (mirroring `RealMultiSpeakerBackend`) holds ≤1 model on the 6 GB GPU; chunk-in-time + atomic temp-write + OOM cleanup are the director's job.

**F. Optional local voice-consent VERIFY (strengthens WU-A2 without egress).** Add `tts.voiceConsent.verify({sampleId, livePhrasePath}) → {matched, score}` (direct): the user records a live consent phrase; the **already-vendored ECAPA-TDNN** (SpeechBrain, **Apache-2.0**, used by diarize) cosine-matches its voiceprint to the reference sample for the `'self'` basis — **fully offline, no audio egress**. Framed as good-faith friction, **explicitly never "identity proven."** Differentiator: Descript/ElevenLabs do consent but UPLOAD the voice; Reframe keeps voice + verification 100% local.

**G. Consent shape option.** WU-A2's flat `{consentAttested, consentAt, consentNote}` is sufficient and simplest. If richer policy is wanted, model it as a nested `ConsentAttestation{owned:bool, rightsBasis:str('self'|'written-permission'|'public-figure-commentary'), acknowledgedAt:str}` on the `VoiceSample` (append to `DATA_MODELS`); `normalize_sample` already backfills, so legacy rows stay valid either way. `rightsBasis` stays a plain `str` (see §A).

**Net verdict unchanged: `go-with-caveats`** — commercial AUDIO dub = GO after the (zero-download) Gemma→Qwen3 swap; on-video VISUAL lip-sync = commercial BLOCKER (MuseTalk OpenRAIL-M keystone; no permissive relip model exists), personal-tier only, flag-OFF.
