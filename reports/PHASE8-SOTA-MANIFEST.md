# Phase 8 — Advanced Multimodal Moment-Finding: SOTA Build Manifest

**Project:** Reframe Media Studio (local-first desktop video editor)
**Target hardware:** RTX 4050 Laptop, **6 GB VRAM**, sequential **load → infer → unload** (one heavy model at a time)
**Goal:** Find interesting clips/shorts from **VISION + AUDIO + transcript** (not speech-only), work on **silent video**, and improve selection + caption accuracy.
**Compiled:** 2026-06-16 · Verified by 4 parallel web-research agents + spot-checks. Pins reflect repos as of 2026-06-16.
**Source design:** basic-memory note `main/projects/reframe/advanced-moment-finding-upgrade-design-sota-2026-06-16` (research wf `w95s9fw6j`).

---

## ⚠️ COMMERCIAL-LICENSE ALERT (READ FIRST)

The local desktop tool can use everything below. **But the future paid/SaaS platform CANNOT ship these without action.** Five components are non-commercial or encumbered:

| Component | License | Problem for commercial ship | Mitigation |
|---|---|---|---|
| **DOVER** (quality gate) | **S-Lab License 1.0** (NOT MIT — changed 2024-08-12) | Research/non-commercial only | Drop from commercial build, OR replace with a permissive VQA, OR keep local-only |
| **ViNet-S** (saliency) | **CC-BY-NC-SA 4.0** | Non-commercial + ShareAlike (copyleft) | Retrain/replace with a permissive saliency model for the platform, OR keep local-only |
| **Aesthetic-Predictor-V2.5** | **AGPL-3.0** | Network copyleft — taints a hosted service | Reimplement the tiny MLP head on the Apache SigLIP-2 backbone (head is ~KB; AGPL is in the *wrapper*, not the math) |
| **ctc-forced-aligner DEFAULT model** (`mms-300m-1130`) | **CC-BY-NC-4.0** | Non-commercial only | Override default → MIT wav2vec2/HuBERT model (see Decision #1) |
| **pyannote 3.1 weights** | MIT but **GATED** (HF token + accept terms on **two** repos) | Not a license block — a setup/gate friction + upsell | Automate gate acceptance + token at install; MIT permits commercial use |

**Everything else is commercial-OK** (Apache-2.0 / MIT / CC-BY-4.0): SigLIP-2, TransNetV2, PANNs CNN14, NeuFlow_v2, OpenCV, HSEmotion, RapidOCR/PaddleOCR, Parakeet-TDT-0.6B-v3, LightGBM, sherpa-onnx, KeyBERT, all-MiniLM-L6-v2, alt-profanity-check, SmolVLM2-2.2B.

**SmolVLM2 quant caveat:** `bitsandbytes` int8/4-bit is **BROKEN** under transformers for SmolVLM2 (transformers issue #41453). Sub-6 GB route is **BF16 + sequential unload**, or **GGUF via llama.cpp** (a different provider than the transformers `Provider.chat` seam).

---

## Component pins (15)

Field order: **repo/id · version/commit · license (commercial-OK?) · size · VRAM@infer · ONNX · CPU · install · plugs-into · source · confidence.**

### VISUAL

**1. ViNet-S — video saliency** (no-face crop-track + per-frame interestingness curve)
- Repo: `ViNet-Saliency/vinet_v2` — https://github.com/ViNet-Saliency/vinet_v2 (ICASSP-2025 minimalistic repo; arXiv 2502.00397). NOT the older `samyak0210/ViNet`.
- Version: commit `d09066b` (2025-07-21), no tags.
- License: **CC-BY-NC-SA 4.0 — commercial NO.**
- Size: ~36 MB `.pt` (GDrive); ~9.5M params (ViNet-A variant = 148 MB).
- VRAM: est. <1 GB fp16 @224/256 (paper reports >1000 fps); **UNVERIFIED exact**.
- ONNX: NO. CPU: UNVERIFIED.
- Install: UNVERIFIED (no `requirements.txt` surfaced; bare PyTorch + OpenCV inferred).
- Plugs-into: `features/reframe_claudeshorts.py::detect_subject_centers` crop-track + interestingness curve.
- Source: GitHub repo + arXiv 2502.00397. **Confidence: MED.**

**2. SigLIP-2 (SoViT-400M) — shared vision-language backbone** (aesthetic + zero-shot interestingness + embedding novelty)
- Repo: `google/siglip2-so400m-patch16-384` — https://huggingface.co/google/siglip2-so400m-patch16-384 (**patch16**, NOT patch14 — patch14 404s).
- Version: HF `main`, no semver.
- License: **Apache-2.0 — commercial YES.**
- Size: `model.safetensors` 4.54 GB F32 (~1B params) + tokenizer 34 MB.
- VRAM: **~2.3 GB fp16** weights (fits 6 GB); 4.54 GB fp32. **Heaviest single model that is always-on — see VRAM table.**
- ONNX: NO in google repo (Optimum-exportable). CPU: yes (slow).
- Install: `pip install "transformers>=4.49"` then `AutoModel.from_pretrained(..., torch_dtype=torch.float16)`.
- Plugs-into: shared backbone for aesthetic + zero-shot + novelty (one load, 3 uses).
- Source: HF tree + transformers siglip2 docs. **Confidence: HIGH.**

**3. Aesthetic-Predictor-V2.5 — aesthetic scorer**
- Repo: `discus0434/aesthetic-predictor-v2-5` — https://github.com/discus0434/aesthetic-predictor-v2-5 · PyPI https://pypi.org/project/aesthetic-predictor-v2-5/
- Version: `aesthetic-predictor-v2-5==2024.12.18.1`, commit `c0e1556` (2024-12-18).
- License: **AGPL-3.0 — commercial NO/CAUTION (network copyleft).**
- Size: head MLP only (~tens of KB, `aesthetic_predictor_v2_5.pth`).
- VRAM: marginal IF rewired to the shared backbone; **AS-SHIPPED it loads its OWN full SigLIP-1 (~1.7 GB fp16)**.
- ⚠️ **CRITICAL MISMATCH:** hardcodes **SigLIP-1** `google/siglip-so400m-patch14-384` as the default encoder — does **NOT** accept the shared SigLIP-2 backbone out of the box. Either **fork/rewire** to share component #2, or eat a 2nd ~1.7 GB model load (breaks the one-model-at-a-time design). Recommended: reimplement the MLP head against SigLIP-2 (also sidesteps the AGPL wrapper).
- ONNX: NO. CPU: yes.
- Install: `pip install aesthetic-predictor-v2-5`.
- Plugs-into: aesthetic term of the unified scorer.
- Source: GitHub `src/aesthetic_predictor_v2_5/siglip_v2_5.py` + PyPI. **Confidence: HIGH.**

**4. TransNetV2 — shot/scene-cut detection** (catches dissolves PySceneDetect misses)
- Repo: `soCzech/TransNetV2` — https://github.com/soCzech/TransNetV2
- Version: commit `85cef72` (2021-07-28), no tags.
- License: **MIT — commercial YES.**
- Size: weights via git-lfs (TF SavedModel); PyTorch via `convert_weights.py` → `transnetv2-pytorch-weights.pth`; ~5M params, tens of MB (exact MB UNVERIFIED).
- VRAM: <1 GB (UNVERIFIED exact). ONNX: NO. CPU: feasible (inferred).
- Install: `git clone` + `git lfs pull`; TF path: `pip install tensorflow ffmpeg-python pillow`; PyTorch path needs TF once to convert + torch.
- Plugs-into: scene-cut seam (PySceneDetect = CPU fallback, already in the verthor stack).
- Source: GitHub repo + `inference-pytorch/README`. **Confidence: MED-HIGH.**

**5. DOVER — video quality assessment** (late re-ranker demoting shaky/blurry/compressed)
- Repo: `VQAssessment/DOVER` — https://github.com/VQAssessment/DOVER
- Version: commit `f1ddc96` (2024-08-12), latest tag `v0.5.0` (DOVER-Mobile).
- License: **S-Lab License 1.0 — commercial NO** (was MIT, changed 2024-08-12).
- Size: `DOVER.pth` 240 MB; `DOVER++` 240 MB; **DOVER-Mobile** (convnext_v2_femto, 9.86M params, tens of MB — 5.7× smaller).
- VRAM: Mobile <1.9 GB, full higher (both fit 6 GB). Mobile 1.4 s/vid CPU, full 3.6 s.
- ONNX: **YES** (`convert_to_onnx.py`). CPU: YES (both).
- Install: `git clone && cd DOVER && pip install -e .` + download `.pth`. Deps: `torch~=1.13 torchvision opencv-python decord scipy numpy tqdm timm einops scikit-video thop onnx`.
- Plugs-into: late quality re-rank gate in `select.py`.
- Source: GitHub + LICENSE + HF `teowu/DOVER` + requirements.txt. **Confidence: HIGH.**

### AUDIO / MOTION / EMOTION / OCR

**6. PANNs CNN14 — audio tagging** (laughter/applause/music/loudness peaks; replaces fragile `(Applause)` keyword match)
- Repo: PyPI `panns-inference` (https://pypi.org/project/panns-inference/) · src `qiuqiangkong/audioset_tagging_cnn` / `qiuqiangkong/panns_inference`.
- Version: `panns-inference` (latest PyPI; 2024-era), CNN14 checkpoint trained on AudioSet.
- License: **MIT — commercial YES.** (Apache-2.0 per design note; repo is MIT — both permissive, commercial-OK either way.)
- Size: CNN14 checkpoint ~300 MB. PyTorch >= 1.0.
- VRAM: small if GPU; **designed to run on CPU** (no GPU needed). CPU: YES.
- ONNX: not native (PyTorch); exportable.
- Install: `pip install panns-inference`.
- Plugs-into: 3rd audio-saliency scorer term in the unified scorer.
- Source: https://pypi.org/project/panns-inference/ + GitHub `qiuqiangkong/audioset_tagging_cnn`. **Confidence: HIGH** (pkg/license/CPU); MED (exact ckpt MB).

**7. Motion — OpenCV floor (+ optional NeuFlow_v2)**
- **Free floor (no model):** OpenCV `cv2.absdiff` + `cv2.calcOpticalFlowFarneback`. Package `opencv-python`. License **Apache-2.0 — commercial YES.** CPU, no download. `pip install opencv-python`.
- **Optional upgrade:** `neufieldrobotics/NeuFlow_v2` — https://github.com/neufieldrobotics/NeuFlow_v2 · arXiv 2408.10161. License **Apache-2.0 — commercial YES.** ONNX available via `ibaiGorordo/ONNX-NeuFlowV2-Optical-Flow`; PyTorch inference via `ibaiGorordo/NeuFlow_v2-Pytorch-Inference`. 10×–70× faster than prior SOTA, edge-targeted (fits 6 GB easily). Weights size UNVERIFIED (small/edge model).
- Plugs-into: motion-energy scorer (WU0 uses the free floor; NeuFlow optional later).
- Source: GitHub + arXiv 2408.10161. **Confidence: HIGH** (OpenCV/NeuFlow license+ONNX); MED (NeuFlow weights MB).

**8. HSEmotion — facial emotion recognition** (reaction/emotion peaks)
- Repo: PyPI `hsemotion-onnx` (https://pypi.org/project/hsemotion-onnx/) · `av-savchenko/hsemotion-onnx`. (Successor lib: `sb-ai-lab/EmotiEffLib`.)
- Version: `hsemotion-onnx==0.3.1` (2022-12-17). Models: `enet_b0_8_best_vgaf`, `enet_b0_8_best_afew`, `enet_b2_8`.
- License: **Apache-2.0 — commercial YES.**
- Size: EfficientNet-B0 ~5M params (small ONNX). VRAM: minimal. CPU: YES. ONNX: **YES (native).**
- Install: `pip install hsemotion-onnx`.
- Plugs-into: emotion-peak scorer (operates on faces from the existing MediaPipe/face-pose stage).
- Source: https://pypi.org/project/hsemotion-onnx/ + GitHub. **Confidence: HIGH.**

**9. OCR — RapidOCR (recommended) / PaddleOCR** (on-screen/gameplay/tutorial text)
- **Recommended (lighter, ONNX-native):** `rapidocr-onnxruntime` — https://pypi.org/project/rapidocr-onnxruntime/ · version **1.4.4** (2025-01-17). License **Apache-2.0 — commercial YES.** Cross-platform OnnxRuntime OCR; **PP-OCRv5 models supported** in the RapidOCR ecosystem. CPU: YES. `pip install rapidocr-onnxruntime`. (Note: the newer unified `rapidocr` package also exists with later 2025 versions.)
- **Alternative:** `paddleocr` (PP-OCRv5 mobile). License **Apache-2.0 — commercial YES.** Heavier dep tree (PaddlePaddle); prefer RapidOCR for the 6 GB-sequential budget.
- Plugs-into: OCR text-presence signal in the shared visual timeline.
- Source: https://github.com/RapidAI/RapidOCR/releases + PyPI. **Confidence: HIGH.**

### SPEECH

**10. Parakeet-TDT-0.6B-v3 — multilingual ASR** (primary; whisper-turbo int8 = fallback)
- Repo: `nvidia/parakeet-tdt-0.6b-v3` — https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3 (v3 = 25-lang European; distinct from v2 English-only). **Not gated.**
- Version: released 2025-08-14; built for **NeMo 2.4**; pin README commit `575de92` or `revision="main"`.
- License: **CC-BY-4.0 — commercial YES** (attribution).
- Size: ~2.4 GB (0.6B params); fp16 ~1.2 GB.
- VRAM: ~2–3 GB per chunked segment — **fits 6 GB only with audio CHUNKING** (full-context long-attention wants A100-80GB; must segment on the 4050).
- ONNX/CPU: NeMo CPU works but slow; **OpenVINO/ONNX export exists** (`FluidInference/parakeet-tdt-0.6b-v3-ov`) = viable CPU/iGPU fallback.
- Install: `pip install -U nemo_toolkit['asr']` (NeMo 2.4+ + PyTorch).
- Languages: **CONFIRMED 25 European incl. Romanian.** WER 6.34% (English Open-ASR) / 11.97% (Fleurs multilingual). (Design note's "6.32%" ≈ the English figure.)
- Plugs-into: `transcribe.py` ASR via the WhisperLoader-style seam.
- Source: HF model card + `FluidInference/parakeet-tdt-0.6b-v3-ov`. **Confidence: HIGH** (existence/license/langs/framework); MED (exact 6 GB chunk VRAM — no published per-config number).

**11. ctc-forced-aligner — word-timing 2nd pass** (karaoke timing)
- Repo: PyPI `ctc-forced-aligner` (https://pypi.org/project/ctc-forced-aligner/) · src `MahmoudAshraf97/ctc-forced-aligner` · DEFAULT model `MahmoudAshraf/mms-300m-1130-forced-aligner`.
- Version: package **1.0.2** (2025-02-09); default model = MMS-300M conversion, 158-lang, ungated.
- License: **package code = BSD (commercial OK). DEFAULT MODEL (mms-300m) = CC-BY-NC-4.0 → NON-commercial ONLY.** Commercial alternatives (MIT, Meta): `WAV2VEC2_ASR_LARGE_LV60K_960H`, `WAV2VEC2_ASR_LARGE_960H`, `HUBERT_ASR_LARGE/XLARGE`.
- Size: package 22 kB; MMS-300M ~1.2 GB; wav2vec2-large alts ~1.2–1.3 GB.
- VRAM: ~1–2 GB (author: ≥5× less mem than TorchAudio aligner) — well under 6 GB.
- ONNX/CPU: **YES** — ONNXRuntime AND PyTorch backends; CPU fully supported (`--device`); needs FFmpeg.
- Install: `pip install ctc-forced-aligner` (pass a non-default model id for commercial use).
- Plugs-into: word-timing 2nd pass after ASR (caption karaoke).
- Source: PyPI + GitHub + HF model card. **Confidence: HIGH.** → **See Decision #1.**

**12. pyannote.audio 3.1 — speaker diarization** (net-new; speaker labels for selection/captions)
- Repo: PyPI `pyannote-audio` (**pin `==3.1.1`**, https://pypi.org/project/pyannote-audio/3.1.1/) · pipeline `pyannote/speaker-diarization-3.1` (https://huggingface.co/pyannote/speaker-diarization-3.1).
- Version: **pin `pyannote-audio==3.1.1`** (current PyPI latest = 4.0.4 needs torch≥2.8, so MUST pin). Pipeline 3.1 = pure PyTorch (onnxruntime removed).
- License: **CODE = MIT (commercial OK).** Weights `speaker-diarization-3.1` + dependency `pyannote/segmentation-3.0` = MIT but **GATED** (accept terms + contact info, HF token). Gate = contact collection + pyannoteAI upsell, **NOT** a commercial-use prohibition → commercial OK.
- Size: ~1.6 GB total (segmentation + embedding). VRAM: ~1.5–2 GB (fits 6 GB easily). CPU: supported (slower).
- Install: `pip install pyannote-audio==3.1.1` → accept gate at **BOTH** `pyannote/speaker-diarization-3.1` AND `pyannote/segmentation-3.0` → pass `use_auth_token=<HF_TOKEN>` to `Pipeline.from_pretrained`.
- Plugs-into: net-new diarization feature.
- Source: HF model card + PyPI. **Confidence: HIGH** (version/MIT code/two-gate+token); MED (no explicit "commercial-OK" sentence on the card — MIT permits it). → **See Decision #3.**

### VIDEO-LLM / SELECTION / CAPTIONS

**13. SmolVLM2-2.2B-Instruct — on-device video-LLM** (Tier-2 re-rank of top-K)
- Repo: `HuggingFaceTB/SmolVLM2-2.2B-Instruct` — https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct
- Version: rev `482adb5` (main, 2025-04-08); **transformers `==4.49.0`** (the v4.49.0-SmolVLM-2 line).
- License: **Apache-2.0 — commercial YES.**
- Size: ~4.5 GB BF16 on disk; **~5.2 GB runtime VRAM** for video inference — **6 GB-TIGHT, CANNOT co-run; full sequential load/unload required.**
- ONNX: only for the 500M variant, NOT 2.2B. CPU: impractical.
- **Quant:** `bitsandbytes` int8/4-bit is **BROKEN** under transformers (issue #41453). Sub-6 GB route = **GGUF via llama.cpp/Ollama** (`ggml-org/SmolVLM2-2.2B-Instruct-GGUF`) — a different provider than `Provider.chat`. **Do NOT assume bnb-int8 works.**
- Install: `pip install "transformers==4.49.0" num2words` (+ optional `flash-attn accelerate`).
- Plugs-into: `Provider.chat` seam / Tier-2 multimodal re-rank — **off by default on-device.**
- Source: HF blog `smolvlm2.md` + transformers #41453. **Confidence: HIGH** (id/license/VRAM/transformers); MED (disk size). → **See Decision #2.**

**14. Selection — DPP-MAP + MMR + LGBMRanker**
- **DPP-MAP fast greedy (Cholesky):** pure NumPy, no package. Ref: Chen/Zhang/Zhou NeurIPS 2018 (arXiv 1709.05135). CPU. https://proceedings.neurips.cc/paper_files/paper/2018/hash/dbbf603ff0e99629dda5d75b6f75f966-Abstract.html. **Confidence: HIGH.**
- **MMR diversity:** pure NumPy, no package. Ref: Carbonell & Goldstein SIGIR 1998. CPU. **Confidence: HIGH.**
- **LGBMRanker (LambdaMART):** `lightgbm` — https://pypi.org/project/lightgbm/ · version **4.6.0** (2025-02-15). License **MIT — commercial YES.** ~1–3 MB, CPU (`objective=lambdarank`), trains on the user's local `feedback.jsonl` (OpusClip-style virality flywheel, zero model download). `pip install lightgbm==4.6.0`. https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRanker.html. **Confidence: HIGH.**
- Plugs-into: `select.py` final ranking + diversity (no near-duplicate picks). → **See Decision #3.**

**15. Caption polish (WU9) — sherpa-onnx + KeyBERT + alt-profanity-check + Netflix CPS/CPL**
- **sherpa-onnx punct + casing:** `sherpa-onnx` — https://pypi.org/project/sherpa-onnx/ · version **1.13.3** (2026-06-15); models from `k2-fsa/sherpa-onnx` releases. Engine **Apache-2.0 — commercial YES** (model files are ModelScope-converted; verify model license before redistribution). For a **tiny** footprint use the EN-only `sherpa-onnx-online-punct-en-2024-08-06`; the zh-en CT-Transformer int8 is **72 MB** (NOT ~7 MB — design-note correction). CPU, ONNX-native. `pip install sherpa-onnx==1.13.3` + download model tarball. **Confidence: HIGH.**
- **KeyBERT (emphasis keywords):** `keybert` — https://pypi.org/project/keybert/ · version **0.9.0** (2025-02-07). License **MIT — commercial YES.** Pkg tiny; reuses `sentence-transformers/all-MiniLM-L6-v2` (~80–90 MB, 22.7M params). CPU. `pip install keybert==0.9.0`. **Confidence: HIGH.**
- **alt-profanity-check (masking):** `alt-profanity-check` — https://pypi.org/project/alt-profanity-check/ · version **1.7.1**. License **MIT — commercial YES.** Tiny sklearn linear-SVM (pins to its scikit-learn version), CPU, fast. `pip install alt-profanity-check==1.7.1` (match scikit-learn). **Confidence: HIGH.**
- **Netflix CPS/CPL gate:** RULES CONSTANT, no model. Netflix Timed Text Style Guide: **CPS max 17 (adult) / 13 (children), CPL max 42 chars/line (Latin), min gap 2 frames, max 2 lines.** https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977. **Confidence: HIGH.**
- Plugs-into: caption segmentation/punct/casing/emphasis/profanity polish (replaces greedy char-packing).

---

## 6 GB VRAM-fit table (sequential load → infer → unload)

The design runs **one heavy model at a time**. Below is each stage's resident VRAM in isolation. **As long as each stage unloads before the next loads, the whole stack fits 6 GB.** No two GPU models are ever co-resident.

| Stage / model | dtype | VRAM resident | Fits 6 GB alone? | Notes |
|---|---|---|---|---|
| OpenCV motion floor | — | 0 (CPU) | ✅ | no model |
| DPP / MMR / LGBMRanker | — | 0 (CPU) | ✅ | pure NumPy + sklearn-class |
| PANNs CNN14 (audio) | fp32 | ~0 GPU (CPU-designed) | ✅ | runs on CPU |
| ViNet-S (saliency) | fp16 | <1 GB (est.) | ✅ | small; VRAM unverified-exact |
| TransNetV2 (scene cuts) | fp16 | <1 GB | ✅ | ~5M params |
| HSEmotion (emotion) | onnx | <0.5 GB | ✅ | EfficientNet-B0 |
| RapidOCR (OCR) | onnx | <1 GB (CPU-capable) | ✅ | ONNX runtime |
| NeuFlow_v2 (optional motion) | fp16/onnx | <1 GB | ✅ | edge-optimized |
| DOVER / DOVER-Mobile (quality) | fp16 | Mobile <1.9 GB / full higher | ✅ | both fit |
| ctc-forced-aligner | fp16 | ~1–2 GB | ✅ | |
| pyannote 3.1 (diarization) | fp16 | ~1.5–2 GB | ✅ | |
| **SigLIP-2 backbone** | **fp16** | **~2.3 GB** | ✅ | heaviest "light" model; serves aesthetic+zero-shot+novelty in one load |
| **Parakeet-TDT-0.6B-v3 (ASR)** | **fp16** | **~2–3 GB (chunked)** | ✅ **only if audio is CHUNKED** | full-context wants 80 GB — MUST segment |
| **SmolVLM2-2.2B (Tier-2 video-LLM)** | **bf16** | **~5.2 GB** | ⚠️ **TIGHT — fits alone, CANNOT co-run** | off by default; bnb-int8 broken → BF16+unload or GGUF |

**Flagged components that need care to fit 6 GB:**
1. **SmolVLM2-2.2B (~5.2 GB)** — fits *alone* but with almost no headroom; absolutely cannot co-run with any other GPU model; int8 quant broken (use BF16+unload or GGUF/llama.cpp). **This is the only true 6 GB-tight item.**
2. **Parakeet-TDT-0.6B-v3** — fits *only with audio chunking*; naive full-context decode will OOM.
3. **Aesthetic-Predictor-V2.5 as-shipped** — would load a *second* ~1.7 GB SigLIP-1 unless rewired to share the SigLIP-2 backbone. Rewire required to honor the one-model-at-a-time budget.

**Verdict: the stack fits 6 GB sequentially** with two hard rules — (a) chunk audio for Parakeet, (b) SmolVLM2 runs alone (and is opt-in). The Tier-0 numeric floor (motion+audio+saliency+OCR+selection) is all small/CPU and never approaches the limit.

---

## Build order — WU0 → WU9 (impact/effort ordered)

Each work unit lands clean under the existing gates (TDD, 100% line+branch coverage) and plugs into current injectable seams.

| WU | Scope | Acceptance criterion (1-line) |
|---|---|---|
| **WU0** | Motion-energy (OpenCV) + DPP/MMR diversity + LGBMRanker scaffold | A **silent** clip yields a non-empty, **deduped, ranked** candidate set with **zero** model downloads. |
| **WU1** | ViNet-S saliency in `detect_subject_centers` + per-frame interestingness curve | **No-face** footage produces a per-frame interestingness curve **and** valid crop centers. |
| **WU2** | PANNs audio-saliency as 3rd scorer term | A laughter/applause peak is detected **without** any `(Applause)` transcript keyword. |
| **WU3** | TransNetV2 scene-cut seam | A **dissolve** that PySceneDetect misses is caught by TransNetV2 (CPU fallback still works). |
| **WU4** | Shared SigLIP-2 backbone (aesthetic + zero-shot interestingness + novelty) | **One** backbone load serves all 3 sub-scores (no 2nd SigLIP load). |
| **WU5** | Unified tri-modal scorer in `select.py` (graceful degrade to visual-only) | Scorer returns ranked moments with audio **and** transcript **absent** (silent-video path). |
| **WU6** | ctc-forced-aligner karaoke word-timing | Word timings align to reference within tolerance; commercial-safe model id selectable. |
| **WU7** | Parakeet-TDT-0.6B-v3 ASR via WhisperLoader seam | **Romanian** transcript produced via the loader seam; whisper-turbo fallback still works; audio chunked to fit 6 GB. |
| **WU8** | SmolVLM2-2.2B multimodal re-rank (Tier-2, opt-in) | Top-K reorders via the video-LLM; model **loads alone within 6 GB** and unloads after. |
| **WU9** | Caption polish (punct/casing/segmentation/emphasis/profanity) | Punct+casing applied, segmentation honors **Netflix CPS≤17 / CPL≤42**, emphasis keywords + profanity masking present. |

---

## 3 OPEN DECISIONS (for the user — NOT decided here)

**Decision #1 — ctc-forced-aligner default model license.**
The package default `mms-300m-1130-forced-aligner` is **CC-BY-NC-4.0 (non-commercial only)** — unusable if the editor ships commercially. To stay commercial, override the default with an **MIT wav2vec2/HuBERT** model (e.g. `WAV2VEC2_ASR_LARGE_LV60K_960H`). Tradeoff: MMS = 158-lang multilingual; wav2vec2-960H is English-centric, so **non-English word-timing needs a language-matched MIT wav2vec2/VoxPopuli variant**. *Question: accept CC-BY-NC for the local tool and swap to MIT only for the platform, or standardize on MIT models everywhere from the start?*

**Decision #2 — SmolVLM2 opt-in (heavy) vs default.**
SmolVLM2-2.2B is **~5.2 GB VRAM, 6 GB-tight, cannot co-run, and `bnb` int8 is broken** (transformers #41453); the comfortable sub-6 GB route is GGUF/llama.cpp, a **different provider** than the transformers `Provider.chat` seam. *Question: keep it strictly opt-in/off-by-default on-device (Tier-2 only when the user asks), or invest in the GGUF/llama.cpp provider to make it more routinely usable?*

**Decision #3 — keep LGBMRanker + pyannote diarization in scope?**
- **LGBMRanker:** MIT, ~1–3 MB, CPU-only, zero model download, trains locally on `feedback.jsonl` — **low cost/risk; recommend keep.**
- **pyannote 3.1:** heavier (torch, ~1.6 GB gated HF weights on **two** repos, HF-token setup friction; MIT-but-gated). Cost/risk concentrates here, not in LGBMRanker. *Question: keep pyannote diarization in Phase 8 scope (accept the gate-acceptance + token setup burden), or defer it to a later phase and ship Phase 8 without speaker labels?*

---

## Appendix — what stays OFF the critical path / cloud-only

- **SMART** (QVHighlights SOTA) — needs 24 GB+ VRAM → **cloud-platform only**, never on the 4050.
- PySceneDetect, YOLO-seg, ByteTrack, MediaPipe face-pose, base saliency — **already in the verthor CV stack** (computed during reframe); Phase 8 *adds* semantic/audio/emotion/motion/OCR signals on top.
