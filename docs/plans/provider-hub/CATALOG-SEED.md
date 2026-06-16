# Provider Hub — Catalog Seed (research 2026-06-16)

Seed for `catalog.py` + the SETUP/MODEL-GUIDE docs. From the `free-api-provider-survey` research pass (`wf_e4773258`). **Free tiers churn — re-verify at signup; do not hardcode against this snapshot.** User brings their own key for every provider.

## Catalog table — per-Reframe-task fitness
Tasks: **1**=Moment-Find/Select · **2**=Caption/Title/Hook · **3**=Translation · **4**=Vision/OCR · **5**=Edit-Plan Gen. Scale S(best)/A/B/C/n-a.

| Provider | Model | Free limits | OpenAI-compat | Train-on-input (privacy) | Modality | Ctx | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Groq | GPT-OSS-120B | 30 RPM / 1K RPD / 200K TPD | Yes | No (no-retention default) — SAFE | Text | 128K | S | A | A | n/a | S |
| Groq | Llama 3.3 70B | 30 RPM / 1K RPD / 100K TPD | Yes | No — SAFE | Text | 128K | A | S | S | n/a | A |
| Cerebras | Qwen3-235B | ~30 RPM / **1M tok/day** | Yes | Unverified (likely no-train) | Text | ~128K | S | A | A | n/a | S |
| Cerebras | Llama 3.3 70B | ~30 RPM / 1M tok/day | Yes | Unverified | Text | 128K | A | S | S | n/a | A |
| SambaNova | Llama 3.1 405B | ~10–30 RPM / ~200K tok/day | Yes | Claims no prompt collection — SAFE-ish | Text | 128K | A | A | A | n/a | A |
| Google AI Studio | Gemini 2.5 Flash | 15 RPM / 1500 RPD / ~1M TPM | Partial | **YES free trains (outside EEA/UK/CH) — AVOID private** | Vision | ~1M | S | A | A | S | S |
| Google AI Studio | Gemini 2.5 Flash-Lite | 30 RPM / 1500 RPD | Partial | **YES — AVOID private** | Vision | ~1M | A | S | A | S | A |
| GitHub Models | GPT-4o-mini | ~15 RPM / 150 RPD (prototyping) | Yes | No-train (not for prod) — SAFE-ish | Vision | 128K | B | A | A | A | B |
| Mistral | Pixtral | Experiment ~1B tok/mo (phone verify) | Yes | **Trains by default; opt-out toggle** — CONDITIONAL | Vision | 128K | B | A | S | A | B |
| Cloudflare Workers AI | Llama 3.1 / Qwen 2.5 | 10K Neurons/day | Partial+REST | No-train — SAFE | Text | **2K–8K (limiting)** | C | B | B | n/a | C |
| OpenRouter | DeepSeek/Qwen `:free` | 20 RPM / 50 RPD (→1000 after one-time $10) | Yes | **Downstream may train unless ZDR** — CONDITIONAL | Text | ≤128K | A | A | A | n/a | A |
| OpenRouter | Gemma/Nemotron-VL `:free` | 20 RPM / ~50–200 RPD | Yes | **Downstream may train; set ZDR** — CONDITIONAL | Vision | ≤256K | n/a | n/a | n/a | B | n/a |
| OpenAI API | (paid; ~no free) | credits | Yes | No-train by default (API) — SAFE | Vision | 128K+ | A | A | A | A | A |

## Top pick per task
1. **Moment-find/select → Groq GPT-OSS-120B** (reasoning + 200K TPD + no-train; Cerebras Qwen3-235B fallback).
2. **Caption/title/hook → Groq Llama 3.3 70B** (fast, generous, safe).
3. **Translation → Groq Llama 3.3 70B** (volume) / Mistral Large (EU-language quality, opt-out first).
4. **Vision/OCR → Gemini 2.5 Flash-Lite** (best free OCR + 1M ctx) — ⚠️ free trains → **GitHub GPT-4o-mini or paid Gemini for private/PII frames**.
5. **Edit-plan gen → Groq GPT-OSS-120B** (best free JSON/structured + no-train).

## Privacy tiers
- **SAFE for transcripts:** Groq (best), OpenAI API, SambaNova, Cloudflare (tiny ctx). Cerebras likely-safe but ToS unverified.
- **SAFE for frames:** GitHub GPT-4o-mini, Cloudflare VLMs (low OCR quality), paid Gemini, OpenAI API.
- **CONDITIONAL (flip opt-out/ZDR first):** Mistral Experiment, OpenRouter `:free`.
- **AVOID for real user data:** **Google AI Studio free (Gemini)** — free trains, human review possible (outside EEA/UK/CH). Biggest privacy flag.

## ⛔ CRITICAL — "N keys = N× quota" is FALSE (per-ACCOUNT, not per-key)
OpenRouter docs verbatim: *"Making additional accounts or API keys will not affect your rate limits, as we govern capacity globally."* Free caps: <$10 lifetime → 50 RPD; ≥$10 one-time (never expires) → 1000 RPD; 20 RPM throughout. Same applies to Google/OpenAI/Mistral/Groq anti-abuse ToS. **Implications:**
- Multi-key rotation for the SAME provider does NOT multiply quota and violates ToS → **the Hub must NOT advertise stacked same-provider keys as ×N quota.**
- **Multi-PROVIDER rotation IS legitimate + does stack:** a Groq key + a Cerebras key + a Gemini key genuinely sum to (Groq quota + Cerebras quota + Gemini quota). This is the honest version of the user's "load N APIs, rotate when one is consumed" vision.
- → Usage bars + "superpowered" stack across **distinct providers**, never multiple same-provider keys. Recommender + docs say: "add keys from different providers; don't farm multiple accounts at one provider."

## Caveats
Free tiers churn; Cerebras train-policy unverified; SambaNova card-requirement unclear; Mistral trains unless toggled; Gemini training is region-dependent; OpenAI 30-day retention has a legal-hold caveat; vision on text-first free providers (Groq Llama 4, Cloudflare LLaVA) is weak for dense on-screen text — test before relying; GitHub Models = prototyping only. Production = free primary + a paid vision tier behind it.
