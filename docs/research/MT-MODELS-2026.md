# MT Model Survey & Tiered-Translation Decision (T3.0, surveyed live 2026-06-12)

Scope: open MT models runnable **<= 6GB VRAM as GGUF via llama.cpp**, for the
`subtitles.translate` + T2 dub pipeline. Every availability claim below was
verified against the live Hugging Face pages on 2026-06-12 (links inline).
Re-verify quant repos + the llama.cpp arch support matrix before each release —
community GGUF repos occasionally get renamed or gated.

**SURVEY-VERDICT: TranslateGemma CONFIRMED as the local stack (4B Q4_K_M tier 1,
12B Q4_K_M tier 2 with partial offload). Aya-Expanse-8B is OVERTURNED as a
shipped tier (verified available, but superseded: Oct-2024 vintage, 23 languages,
CC-BY-NC-4.0, 5.06GB — strictly dominated by TranslateGemma-4B). Hunyuan-MT-7B is
the documented zh-centric alternate. Tier 3 = hosted OpenAI-compatible provider.**

---

## 1. Candidates verified TODAY (2026-06-12)

| Model | Released | Langs | License | GGUF today? | Pinned quant (size) | Fits 6GB? | Verdict |
|---|---|---|---|---|---|---|---|
| **TranslateGemma-4B-it** (Google, Gemma-3-based) | 2026-01-15 | 55 evaluated (+~500 trained pairs) | Gemma | YES — [mradermacher](https://huggingface.co/mradermacher/translategemma-4b-it-GGUF), [SandLogic](https://huggingface.co/SandLogicTechnologies/translategemma-4b-it-GGUF), [NikolayKozloff Q8_0](https://huggingface.co/NikolayKozloff/translategemma-4b-it-Q8_0-GGUF) | `translategemma-4b-it.Q4_K_M.gguf` (2.49GB; Q6_K 3.19GB; Q8_0 4.13GB) | YES, fully resident | **TIER 1 (default)** |
| **TranslateGemma-12B-it** | 2026-01-15 | 55 | Gemma | YES — [mradermacher](https://huggingface.co/mradermacher/translategemma-12b-it-GGUF) | `translategemma-12b-it.Q4_K_M.gguf` (7.4GB; Q4_K_S 7.0GB) | Partial offload only | **TIER 2 (SLOW)** |
| **Aya-Expanse-8B** (Cohere) | 2024-10 | 23 | **CC-BY-NC-4.0** | YES — [bartowski](https://huggingface.co/bartowski/aya-expanse-8b-GGUF), [QuantFactory](https://huggingface.co/QuantFactory/aya-expanse-8b-GGUF), [lmstudio-community](https://huggingface.co/lmstudio-community/aya-expanse-8b-GGUF) | `aya-expanse-8b-Q4_K_M.gguf` (5.06GB) | Barely (small ctx) | Available but **superseded** — fewer langs, older, bigger, NC license |
| **Hunyuan-MT-7B** (Tencent; WMT25: 1st in 30/31 pairs) | 2025-09 | 33–36 incl. zh-minority (yue, bo, ug, mn, kk) | Tencent Hunyuan community | YES — [Mungert](https://huggingface.co/Mungert/Hunyuan-MT-7B-GGUF) (+[Chimera](https://huggingface.co/Mungert/Hunyuan-MT-Chimera-7B-GGUF)) | `Q4_K_M` (4.7GB) | YES | **Alternate tier 2 for zh-centric pairs** (doc-only; not shipped default) |
| **Seed-X-PPO-7B** (ByteDance) | 2025-07 | 28 | — | GGUF exists ([Mungert](https://huggingface.co/Mungert/Seed-X-PPO-7B-GGUF), [Sangto](https://huggingface.co/Sangto/Seed-X-PPO-7B-Q8_0-GGUF)) | 7B Q4 ~4.3GB | YES | **REJECT** — vendor recommends beam search (not llama.cpp default) and warns quantized models are unstable |
| NLLB-200 / "NLLB-next" | 2022 / none found | 200 | CC-BY-NC | NO (encoder-decoder, not a llama.cpp text-gen arch) | — | — | **REJECT** — no successor surfaced in the survey; arch not llama.cpp-servable |
| TowerInstruct-7B / successors (Unbabel) | 2024-01 (v0.2: 2024-03) | 10 | CC-BY-NC | community GGUFs exist | ~4.4GB Q4 | YES | **REJECT** — line moved commercial (TowerLLM, closed weights); open checkpoints are 2024-stale vs TranslateGemma |
| Qwen-MT (Alibaba) | — | — | — | API-only, no open weights found in survey (confidence: medium — re-check) | — | — | Not GGUF-runnable today |

Sources: [TranslateGemma announcement (blog.google, 2026-01-15)](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/) ·
[TranslateGemma tech report (arXiv 2601.09012)](https://arxiv.org/pdf/2601.09012) ·
[google/translategemma-4b-it model card](https://huggingface.co/google/translategemma-4b-it) ·
[Hunyuan-MT tech report (arXiv 2509.05209)](https://arxiv.org/abs/2509.05209) ·
[tencent/Hunyuan-MT-7B](https://huggingface.co/tencent/Hunyuan-MT-7B) ·
[ByteDance-Seed/Seed-X-PPO-7B](https://huggingface.co/ByteDance-Seed/Seed-X-PPO-7B) ·
[Unbabel/TowerInstruct-7B-v0.2](https://huggingface.co/Unbabel/TowerInstruct-7B-v0.2)

Key quality datapoints (Google, WMT24++/MetricX): TranslateGemma-12B **beats the
Gemma-3-27B baseline**; TranslateGemma-4B **rivals the 12B baseline**. That makes a
4B Q4 (2.49GB) the best quality-per-VRAM open MT artifact available today, and it
shares the Gemma-3 arch already proven in llama.cpp.

## 2. The shipped stack (pinned)

| Tier | What | Artifact (PINNED) | VRAM plan |
|---|---|---|---|
| **tier1** — local fast | TranslateGemma-4B-it Q4_K_M | `https://huggingface.co/mradermacher/translategemma-4b-it-GGUF/resolve/main/translategemma-4b-it.Q4_K_M.gguf` (2.49GB, size_mb=2550) | full offload (`-ngl 999`), fits beside nothing else (one-heavy-model lane) |
| **tier2** — local heavy, **label SLOW** | TranslateGemma-12B-it Q4_K_M | `https://huggingface.co/mradermacher/translategemma-12b-it-GGUF/resolve/main/translategemma-12b-it.Q4_K_M.gguf` (7.4GB, size_mb=7580) | **partial offload** (`-ngl 24` default — ~3.7GB of 48 blocks on GPU, rest CPU); UI/progress label "SLOW" |
| **tier3** — hosted | OpenAI-compatible cloud (`models.provider.CloudProvider`) | settings `cloudApiKey` (+ optional `cloudBaseUrl`/`cloudModel`) | none |

Both manifest entries are registered (U4 `assets.manifest.register_asset`) by
`media_studio/models/translation.py` at import, with settings-driven existing-path
detection (`translateGgufPath` / `translateTier2GgufPath` / `modelsDir`).
sha256 left unpinned (A3 "sha-optional"); fill in after the first verified download.

Model switching: the llama.cpp server lane serves ONE GGUF at a time. T3 made
`ModelRunner.start_server` model-identity-aware: requesting a different GGUF
gracefully stops the running server and relaunches with the new model; requesting
the same model reuses the live process. The dub pipeline is BATCHED (A4): translate
ALL cues, then switch models once — never interleave per-cue swaps.

## 3. Routing table (lang -> tier), as encoded in `models/translation.py`

Normalization: case-insensitive, region stripped (`pt-BR` -> `pt`, `zh_Hant` -> `zh`).
Coverage basis: TranslateGemma's 55-language WMT24++ evaluation set (blog confirms
es/fr/zh/hi + low-resource coverage; the full list lives in the tech report —
confidence: high for the codes below, route-to-tier3 is the safe default for
anything uncertain). Tier assignment within the covered set is this survey's
judgment: high/mid-resource -> 4B fast; the low-resource tail (Indic/African/
Icelandic) -> 12B SLOW, where the extra capacity matters most.

| Tier | Languages (ISO 639-1) |
|---|---|
| **tier1** (TranslateGemma-4B, fast) | ar bg ca cs da de el en es et fa fi fr he hi hr hu id it ja ko lt lv ms nb nl no pl pt ro ru sk sl sr sv th tr uk vi zh |
| **tier2** (TranslateGemma-12B, SLOW) | bn gu is kn ml mr pa sw ta te ur zu |
| **tier3** (hosted) | everything else — incl. yue/bo/ug/mn/kk (zh-minority: consider the Hunyuan-MT-7B alternate locally), und/unknown codes |

Fallback chain on tier failure: routed tier first, then the remaining tiers in
ascending order (tier1 -> tier2 -> tier3). A tier that is unconfigured (no GGUF,
no runner, no cloud key) is skipped with a logged reason; if every tier fails the
job surfaces the aggregate error via the `job.done` error payload (A6 lesson 3).

## 4. Re-verify before release

- mradermacher repos are community quants — mirror the two pinned files into a
  controlled bucket or re-pin if renamed. (No official Google GGUF existed at
  survey time.)
- llama.cpp: Gemma-3 arch long-supported; hunyuan-dense supported (Mungert quants
  built against it) — re-confirm if adopting the Hunyuan alternate.
- Tier-2 `-ngl 24` was sized analytically (not measured): re-tune on the real
  6GB card; lower if KV-cache OOMs at subtitle-batch context sizes.
- A/B the 4B-vs-12B routing split on real subtitle samples for your top
  languages; promote/demote codes between tier1/tier2 accordingly.
