# Reframe Model Guide — best-for, cost, limits, privacy

**Dated guidance · as of 2026-06-16.** These are *our picks*, not objective
benchmarks. Free tiers churn constantly — re-verify each provider's current
limits and training policy at signup. You bring your own API key for every
provider; Reframe never ships keys.

This guide mirrors the machine-readable catalog in
`sidecar/media_studio/models/catalog.py` (seeded from `CATALOG-SEED.md`). The Hub
surfaces the same data in the UI as "our pick · as of \<date\>".

## The five Reframe tasks

| # | Task | What it does |
|---|------|--------------|
| 1 | Moment-Find / Select | Find the best clips/moments in a transcript |
| 2 | Caption / Title / Hook | Generate captions, titles, hooks |
| 3 | Translation | Translate subtitles |
| 4 | Vision / OCR | Read on-screen text / understand frames |
| 5 | Edit-Plan Gen | Generate structured edit plans (JSON) |

Grades: **S** (best) · A · B · C · **n/a** (cannot serve this task).

## Catalog (per-task fitness)

| Provider | Model | Free limits | Ctx | Modality | Train-on-input (privacy) | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|---|---|---|---|---|
| Groq | GPT-OSS-120B | 30 RPM / 1K RPD / 200K TPD | 128K | Text | No — **SAFE** | S | A | A | n/a | S |
| Groq | Llama 3.3 70B | 30 RPM / 1K RPD / 100K TPD | 128K | Text | No — **SAFE** | A | S | S | n/a | A |
| Cerebras | Qwen3-235B | ~30 RPM / 1M tok/day | 128K | Text | Unverified — **CONDITIONAL** | S | A | A | n/a | S |
| Cerebras | Llama 3.3 70B | ~30 RPM / 1M tok/day | 128K | Text | Unverified — **CONDITIONAL** | A | S | S | n/a | A |
| SambaNova | Llama 3.1 405B | ~10–30 RPM / ~200K tok/day | 128K | Text | Claims no collection — **SAFE** | A | A | A | n/a | A |
| Google AI Studio | Gemini 2.5 Flash | 15 RPM / 1500 RPD / ~1M TPM | ~1M | Vision | **YES (free trains)** — **AVOID** | S | A | A | S | S |
| Google AI Studio | Gemini 2.5 Flash-Lite | 30 RPM / 1500 RPD | ~1M | Vision | **YES (free trains)** — **AVOID** | A | S | A | S | A |
| GitHub Models | GPT-4o-mini | ~15 RPM / 150 RPD (prototyping) | 128K | Vision | No-train (not prod) — **SAFE** | B | A | A | A | B |
| Mistral | Pixtral | Experiment ~1B tok/mo (phone verify) | 128K | Vision | Trains by default; opt-out — **CONDITIONAL** | B | A | S | A | B |
| Cloudflare | Workers AI (Llama 3.1 / Qwen 2.5) | 10K Neurons/day | **2K–8K (limiting)** | Text | No-train — **SAFE** | C | B | B | n/a | C |
| OpenRouter | DeepSeek/Qwen `:free` (text) | 20 RPM / 50 RPD (→1000 after one-time $10) | ≤128K | Text | Downstream may train unless ZDR — **CONDITIONAL** | A | A | A | n/a | A |
| OpenRouter | Gemma/Nemotron-VL `:free` (vision) | 20 RPM / ~50–200 RPD | ≤256K | Vision | Downstream may train; set ZDR — **CONDITIONAL** | n/a | n/a | n/a | B | n/a |
| OpenAI | API (paid; ~no free) | credits | 128K+ | Vision | No-train by default (API) — **SAFE** | A | A | A | A | A |

## Top pick per task

1. **Moment-Find / Select → Groq GPT-OSS-120B** — reasoning + 200K TPD + no-train. Cerebras Qwen3-235B is the fallback (more quota, but train-policy unverified).
2. **Caption / Title / Hook → Groq Llama 3.3 70B** — fast, generous, safe.
3. **Translation → Groq Llama 3.3 70B** for volume; **Mistral** for EU-language quality (flip the opt-out toggle first).
4. **Vision / OCR → Gemini 2.5 Flash-Lite** — best free OCR + ~1M context. ⚠️ The free tier **trains on your input** → use **GitHub GPT-4o-mini** or **paid Gemini/OpenAI** for private/PII frames.
5. **Edit-Plan Gen → Groq GPT-OSS-120B** — best free structured-JSON output + no-train.

## Privacy tiers

- **SAFE for transcripts:** Groq (best), OpenAI API, SambaNova, Cloudflare (tiny context). Cerebras is *likely* safe but its ToS is unverified — treat as CONDITIONAL.
- **SAFE for frames:** GitHub GPT-4o-mini, Cloudflare VLMs (low OCR quality), paid Gemini, OpenAI API.
- **CONDITIONAL (flip opt-out / ZDR first):** Mistral Experiment, OpenRouter `:free`, Cerebras (unverified).
- **AVOID for real user data:** **Google AI Studio free (Gemini)** — the free tier trains and human review is possible (outside EEA/UK/CH). This is the biggest privacy flag in the catalog.

## ⛔ "N keys = N× quota" is FALSE — add DIFFERENT providers, not more accounts

Rate limits are governed **per-account / globally**, not per-key. OpenRouter says
this verbatim: *"Making additional accounts or API keys will not affect your rate
limits, as we govern capacity globally."* The same anti-abuse posture applies to
Google, OpenAI, Mistral, and Groq.

- **Loading two keys from the SAME provider does NOT double your quota** — Reframe
  treats same-provider extra keys as **failover only**, never as ×N quota, and
  will never advertise them that way. Farming multiple accounts at one provider
  also violates ToS.
- **Loading keys from DIFFERENT providers DOES stack legitimately:** a Groq key +
  a Cerebras key + a Gemini key genuinely sum to (Groq quota + Cerebras quota +
  Gemini quota). This is the honest version of "load N APIs and rotate when one
  is consumed."
- → The usage bars and the "superpowered" state stack across **distinct
  providers**. To go faster, **add a key from a provider you don't have yet.**

## Caveats

Free tiers churn. Cerebras train-policy unverified; SambaNova card requirement
unclear; Mistral trains unless you toggle opt-out; Gemini training is
region-dependent; OpenAI's 30-day retention has a legal-hold caveat. Vision on
text-first free providers (Groq Llama 4, Cloudflare LLaVA) is weak for dense
on-screen text — test before relying. GitHub Models is prototyping-only. The
recommended production posture is a **free primary + a paid vision tier behind
it**.
