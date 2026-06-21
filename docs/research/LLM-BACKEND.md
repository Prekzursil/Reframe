# LLM / Inference Decision Pack (research wf_24246194-541, 2026-06-11)

Model tags churn monthly — re-verify live `/pricing` + `/rate-limits` + HF Open ASR Leaderboard before each
release; A/B chosen translate/fix models on real subtitle samples in the top-5 languages before locking defaults.

## Per-task recommendations
| Task | Best open (size/quant) | Local on 6GB? | Flagship ceiling | Ship default |
|---|---|---|---|---|
| **Transcribe** | whisper large-v3-turbo (q5_0 ~0.55GB; int8 ~1.5GB VRAM); Parakeet-TDT-0.6B for EU/CPU speed | YES easily | **No — open wins** (cloud only for extreme accents/noise) | whisper-turbo via whisper.cpp/faster-whisper + WhisperX word-timing; large-v3 = max-accuracy toggle |
| **Prompt→Short** | hosted DeepSeek-V3.2 / Qwen3.5-235B / GLM-5 (200K+); self-host Qwen3.5-30B-A3B MoE; on 4050 Qwen3-8B Q4 + map-reduce | only via map-reduce (100K ctx OOMs KV-cache) | **YES — THE flagship case** (vague/creative taste, arc-spanning 50-100K ctx). Gap→~0 with structured prompts + map-reduce | local 4B/8B + map-reduce offline; escalate to free Gemini Flash (1M ctx) or flagship for long/nuanced |
| **Subtitle fix/sync** | timing = WhisperX forced-align (NOT an LLM); correction = Qwen3-8B / Qwen2.5-7B Q4 | YES (ASR then free VRAM then LLM) | mostly no; flagship for noisy/jargon/code-switch/whole-file consistency | WhisperX (timing) + Qwen3-8B Q4 (correct) + "fix-only-clear-errors" + chunk guardrail |
| **Translate** | TranslateGemma-4B Q4 (~2.6GB); step-up 12B Q4 (~6.7GB); low-resource Aya-Expanse-8B (NLLB/MADLAD stale) | YES (4B easily) | partial: high-resource EN↔ES/FR/DE/PT/JP open≈flagship; low-resource/RTL/idiom/creative → Gemini 2.5 Pro/DeepL/Claude | TranslateGemma-4B Q4; route hard pairs to free Gemini Flash or flagship |

**Crossover:** open is good-enough to SHIP for transcribe + subtitle-fix + high-resource translate. Reserve paid cloud for (a) long/ambiguous prompt→short, (b) low-resource/creative translate.

## Hosting matrix
- **Ship-local** — whisper-turbo + Qwen3-4B/8B + TranslateGemma-4B (llama.cpp/whisper.cpp). $0, offline, total privacy (the selling point).
- **Free-hosted** — Groq (Llama-3.3-70B, Whisper ASR $0.04/hr, no-train/ZDR/commercial = SAFEST); Cerebras (1M tok/day, 8K ctx); **Google AI Studio Gemini Flash (1500 RPD, 1M ctx) ⚠️ MAY TRAIN ON INPUTS — never route shipped user content; personal-own-key only**; OpenRouter `:free` (DeepSeek-V3.2/Qwen3.5, 262K). Rotation (Groq+Cerebras+OpenRouter+SambaNova, $10 one-time each) = thousands free req/day via 429-failover.
- **Cheap-paid** — DeepInfra cheapest (Llama-8B $0.06/M, 70B ~$0.12/M); Together/Fireworks/Novita; Mistral.
- **Cloud-flagship** — Claude Opus/Sonnet 4.x, GPT-5.x, Gemini 2.5/3 Pro, DeepL Pro. The two paid toggles.

## Pluggable backend (architecture)
`Provider` interface `{capabilities(), invoke(), stream(), healthcheck()}`; adapters: LocalLlamaCpp/Ollama (OpenAI-compatible), LocalWhisper (ASR), OpenAICompatHosted (Groq/OpenRouter/DeepInfra/Together/SambaNova/Cerebras), GeminiNative (paid/Vertex for user content), AnthropicNative.
- **Capability flags** `{max_context, supports_audio, supports_json_mode, trains_on_data, cost_per_mtok}`; router **refuses trains_on_data=true for user content** unless opted in.
- **Per-task fallback chain**, e.g. `prompt_to_short = [local_qwen, groq_free, openrouter_free, claude_paid]`.
- **map-reduce chunker** = provider-agnostic middleware (small local model handles 2-hr transcript; A/B identical chunks). ASR = separate audio-in adapter (never route audio through chat providers except Groq Whisper).
- Settings UI: per-task rows (Mode ◉Local ○Hosted ○Premium · Model · Fallback) + global "keep everything local" switch + per-provider BYO-key.
- **Defaults:** Transcribe→local whisper-turbo · Fix→local Qwen3-8B · Translate→local TranslateGemma-4B · Prompt→Short→local map-reduce (short) / auto-suggest free Gemini Flash (long).

## Ship-local bundle (offline)
whisper.cpp large-v3-turbo q5_0 (0.55GB) + Qwen3-4B Q4 default (2.5GB; 8B Q4 opt-in 5.0GB) + TranslateGemma-4B Q4 (2.6GB) + runtime ~0.4GB → **~3.4GB (4B) / ~5.9GB (8B)**.
**6GB reality:** 8B "fits" idle ~5.5GB but OOMs at 32K+ ctx (KV-cache) → ship **Qwen3-4B Q4 GPU-resident default**, 8B = accuracy-mode via offload; run **ASR→free VRAM→LLM sequentially** (never whisper+8B resident together); long → map-reduce; **download-on-first-run, don't bake weights into installer**. Runtime = embed **llama.cpp + whisper.cpp** (MIT), NOT Ollama (daemon) / LM Studio (nested Electron, LLM-only no whisper).

## Open questions (user call)
1. **4B vs 8B shipped local default?** (lean: 4B default + 8B opt-in.)
2. **Hosted prompt→short posture:** local-map-reduce-only (free, lower taste) vs free Gemini-Flash (personal own-key only, trains-on-data) vs paid flagship toggle (SaaS) — decides whether the ZDR/no-train gate is built now.
3. **Top target languages** for translate + fix — locks TranslateGemma-4B vs +Aya-Expanse vs flagship routing.
