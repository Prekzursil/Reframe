# Reframe Provider Setup — bring your own free API key

**Dated guidance · as of 2026-06-16.** Reframe runs AI **locally by default** and
never requires the cloud. Cloud is opt-in acceleration: you supply a free API key
from one or more providers, and Reframe rotates across them (with your local model
as the always-available backstop). You bring every key — Reframe ships none.

See `MODEL-GUIDE.md` for which model is best for each task and its privacy posture.

## TL;DR — the honest way to go faster

> **Add keys from DIFFERENT providers, not more accounts at one provider.**
> "N keys = N× quota" is **false** — rate limits are per-account / global. A second
> Groq key does **not** double your Groq quota (it's failover only). A Groq key +
> a Cerebras key + a Gemini key **do** stack. See the ⛔ section below.

## Get a free key (per provider)

### Groq — best free transcript provider (SAFE, no-train)
1. Sign up at <https://console.groq.com>.
2. Create an API key under **API Keys**.
3. Paste it into Reframe → Models & System → Providers.
- Free limits: 30 RPM / 1K RPD / 200K TPD (GPT-OSS-120B) — generous and SAFE.

### Cerebras — biggest free token budget (train-policy UNVERIFIED)
1. Sign up at <https://cloud.cerebras.ai>.
2. Create an API key.
3. ~1M tokens/day free. **Confirm the training/retention policy at signup** —
   it's unverified, so Reframe marks it CONDITIONAL. Don't send PII until you've
   read the ToS.

### Google AI Studio (Gemini) — best free OCR, but ⚠️ AVOID for private data
1. Get a key at <https://aistudio.google.com/apikey>.
2. Use Google's **OpenAI-compatible** endpoint (or Reframe's adapter).
- ⚠️ **The free tier TRAINS on your input** and human review is possible (outside
  EEA/UK/CH). Use Gemini-free only for non-sensitive frames. For private/PII
  frames, use **GitHub GPT-4o-mini** or **paid** Gemini/OpenAI instead.

### GitHub Models — SAFE vision for prototyping
1. Use a GitHub token with the Models scope (<https://github.com/marketplace/models>).
2. GPT-4o-mini, ~15 RPM / 150 RPD. No-train, but **prototyping only** — not for
   production volume.

### Mistral — strong EU-language translation (flip opt-out FIRST)
1. Sign up at <https://console.mistral.ai> (phone verification for the free
   Experiment tier, ~1B tokens/month).
2. **Mistral trains by default.** Turn the training opt-out toggle ON in your
   account settings **before** sending any real data. Reframe marks it CONDITIONAL.

### SambaNova — large 405B model, SAFE-ish
1. Sign up at <https://cloud.sambanova.ai>.
2. ~10–30 RPM / ~200K tokens/day. Claims no prompt collection; card requirement
   may apply.

### Cloudflare Workers AI — SAFE but tiny context
1. Create a key in your Cloudflare dashboard (Workers AI).
2. 10K Neurons/day, no-train — but the **2K–8K context is limiting** for long
   transcripts.

### OpenRouter — many models behind one key (set ZDR for privacy)
1. Sign up at <https://openrouter.ai>, create a key.
2. Use the `:free` model variants.
3. **The $10 threshold:** with **under $10 lifetime** spend you get **50
   requests/day**; a **one-time $10** top-up (it never expires) raises that to
   **1000 requests/day**. The 20 RPM cap applies throughout.
4. **Privacy:** downstream providers **may train** on your input unless you enable
   **Zero Data Retention (ZDR)** in your OpenRouter settings. Do that first.

### OpenAI API — the paid SAFE backstop
1. Create a key at <https://platform.openai.com/api-keys>.
2. No-train by default on the API (a 30-day retention with a legal-hold caveat).
   Effectively no free tier — this is the paid backstop behind the free providers.

## Privacy: per-data-type consent

Reframe asks for **separate** consent to send **text** (transcripts) vs **frames**
(vision) to each provider, and shows the provider's train-on-input disclosure
before first use. Frame egress requires its own confirmation. Either consent is
independently revocable. No AI inputs or keys ever leave your machine except to
the provider **you** chose.

## Keys are never logged or echoed

Your keys are stored locally and shown only as the last 4 characters in the UI.
Reframe never returns a full key over its RPC layer and scrubs keys out of any
provider error message. (See the security invariants in the AI program plan.)

## ⛔ "N keys = N× quota" is FALSE (per-ACCOUNT, not per-key)

OpenRouter, verbatim: *"Making additional accounts or API keys will not affect
your rate limits, as we govern capacity globally."* The same anti-abuse posture
applies to Google, OpenAI, Mistral, and Groq.

- **Same provider, more keys → NO extra quota.** Reframe uses a second
  same-provider key as **failover only** and never advertises it as ×N quota.
  Farming multiple accounts at one provider violates ToS.
- **Different providers → real stacking.** Groq + Cerebras + Gemini genuinely sum
  their quotas. This is the legitimate version of "load N APIs, rotate when one is
  consumed."
- → To go faster, **add a key from a provider you don't already have.** The usage
  bars and the "superpowered" state count **distinct providers**, never multiple
  keys at one provider.

## Reminder

Free tiers churn — re-verify limits and training policies at signup; this snapshot
is dated 2026-06-16. Production posture: a **free primary + a paid vision tier
behind it**, with your **local model as the always-available backstop**.
