// providerMeta.ts — renderer-side per-provider connection metadata (WU-PROVIDERS).
//
// The curated catalog (`providers.catalog`) is PURE quality/privacy metadata: it
// deliberately carries NO API base URLs and NO console (sign-up) URLs (see
// `models/catalog.py` — "There are NO keys, URLs, or runtime fields here"). But
// the Providers & Keys panel needs three concrete, non-secret facts to add a key:
//
//   * the stable provider SLUG used as the `providers.upsert` id (e.g. "groq"),
//   * the OpenAI-compatible API BASE URL the rotation pool + `providers.testKey`
//     call (e.g. "https://api.groq.com/openai/v1"),
//   * the CONSOLE URL where the user gets a free key (the "Get a free key" link).
//
// None of these live in code anywhere (verified: no sidecar registry, no renderer
// constants). The console URLs are sourced VERBATIM from `docs/providers/SETUP.md`
// (dated 2026-06-16); the base URLs are the providers' well-known public
// OpenAI-compatible endpoints. All are public, non-secret presentation metadata —
// the user still brings their own key. Re-verify against SETUP.md at build time
// (free tiers + endpoints churn).
//
// Keyed by the catalog's `provider` DISPLAY name (e.g. "Groq") so a catalog row
// resolves to its connection meta with no slug guessing. `free` mirrors the
// catalog cost posture (FREE/FREEMIUM ⇒ a free key exists; PAID ⇒ no free link).
//
// `defaultModel` is LOAD-BEARING, not cosmetic: the sidecar egress pool and
// `providers.testKey` BOTH fall back to `DEFAULT_CLOUD_MODEL = "gpt-4o-mini"`
// (provider.py) when an entry carries no model — and that id 404s on every
// non-OpenAI provider, so a valid key would validate as "Key failed" and the
// provider would be unusable at egress. So we store a REAL per-provider API model
// id on add. These are the providers' well-known public default model ids (NOT
// the catalog's human display names like "Llama 3.3 70B"); re-verify at build
// time — free model ids churn.
//
// Cloudflare Workers AI is intentionally OMITTED: its OpenAI-compatible base URL
// embeds a per-account id (`/accounts/<ACCOUNT_ID>/ai/v1`) we cannot fill without
// a provider-editing UI, so a one-click add could never resolve. `providerOptions`
// skips catalog providers with no meta, so this drops cleanly.

/** Connection + sign-up metadata for one provider (non-secret, public). */
export interface ProviderMeta {
  /** Stable slug used as the `providers.upsert` id (e.g. "groq"). */
  slug: string;
  /** Display name — matches the catalog `provider` field (e.g. "Groq"). */
  label: string;
  /** OpenAI-compatible API base URL (`{baseUrl}/chat/completions`). */
  baseUrl: string;
  /**
   * A real API model id for this provider's OpenAI-compatible endpoint, used as
   * the entry's default model (validation ping + egress). NOT a display name.
   */
  defaultModel: string;
  /** Console URL to get a free/API key (the "Get a free key" link target). */
  consoleUrl: string;
  /** True when a free tier exists (a "Get a free key" link is offered). */
  free: boolean;
}

/**
 * Per-provider connection metadata, keyed by the catalog DISPLAY name. Console
 * URLs are verbatim from `docs/providers/SETUP.md`; base URLs are the providers'
 * public OpenAI-compatible endpoints. Frozen so callers cannot mutate the shared
 * table.
 */
export const PROVIDER_META: Readonly<Record<string, ProviderMeta>> = Object.freeze({
  Groq: {
    slug: 'groq',
    label: 'Groq',
    baseUrl: 'https://api.groq.com/openai/v1',
    defaultModel: 'llama-3.3-70b-versatile',
    consoleUrl: 'https://console.groq.com',
    free: true,
  },
  Cerebras: {
    slug: 'cerebras',
    label: 'Cerebras',
    baseUrl: 'https://api.cerebras.ai/v1',
    defaultModel: 'llama-3.3-70b',
    consoleUrl: 'https://cloud.cerebras.ai',
    free: true,
  },
  SambaNova: {
    slug: 'sambanova',
    label: 'SambaNova',
    baseUrl: 'https://api.sambanova.ai/v1',
    defaultModel: 'Meta-Llama-3.1-405B-Instruct',
    consoleUrl: 'https://cloud.sambanova.ai',
    free: true,
  },
  'Google AI Studio': {
    slug: 'google-ai-studio',
    label: 'Google AI Studio',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    defaultModel: 'gemini-2.5-flash',
    consoleUrl: 'https://aistudio.google.com/apikey',
    free: true,
  },
  'GitHub Models': {
    slug: 'github-models',
    label: 'GitHub Models',
    baseUrl: 'https://models.inference.ai.azure.com',
    defaultModel: 'gpt-4o-mini',
    consoleUrl: 'https://github.com/marketplace/models',
    free: true,
  },
  Mistral: {
    slug: 'mistral',
    label: 'Mistral',
    baseUrl: 'https://api.mistral.ai/v1',
    defaultModel: 'mistral-large-latest',
    consoleUrl: 'https://console.mistral.ai',
    free: true,
  },
  OpenRouter: {
    slug: 'openrouter',
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    defaultModel: 'deepseek/deepseek-chat-v3-0324:free',
    consoleUrl: 'https://openrouter.ai',
    free: true,
  },
  'OpenAI API': {
    slug: 'openai',
    label: 'OpenAI API',
    baseUrl: 'https://api.openai.com/v1',
    defaultModel: 'gpt-4o-mini',
    consoleUrl: 'https://platform.openai.com/api-keys',
    free: false,
  },
});

/** Look up a provider's connection meta by its catalog display name (or null). */
export function providerMeta(displayName: string): ProviderMeta | null {
  return PROVIDER_META[displayName] ?? null;
}
