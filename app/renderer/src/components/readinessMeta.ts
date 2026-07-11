// readinessMeta.ts — pure, test-pinned helpers for the unified readiness roll-up
// (`readiness.summary`, WU-8). Mirrors advisorMeta's shape: a status -> label /
// status-class / plain-language hint map plus the per-action accessible-name
// builder. No React, no I/O — keeping the branchy copy here lets ReadinessBadge
// (WU-9) stay a thin render shell and pins the WCAG-1.4.1 "status by text, never
// hue alone" guarantee in one covered place.
import type { ReadinessAction, ReadinessStatus } from '../lib/rpc';

/** Readiness status -> the short visible badge label (text, not color). */
export const READINESS_LABEL: Record<ReadinessStatus, string> = {
  ready: 'Ready',
  needsDownload: 'Needs download',
  needsKey: 'Needs key',
  needsConsent: 'Needs consent',
  unavailable: 'Unavailable',
};

/** Readiness status -> the status modifier class (drives the pill tint). */
export const READINESS_CLASS: Record<ReadinessStatus, string> = {
  ready: 'is-ready',
  needsDownload: 'is-needs-download',
  needsKey: 'is-needs-key',
  needsConsent: 'is-needs-consent',
  unavailable: 'is-unavailable',
};

/** Readiness status -> a one-line plain-language gloss (badge tooltip). */
export const READINESS_HINT: Record<ReadinessStatus, string> = {
  ready: 'Ready to use right now — nothing to install or configure.',
  needsDownload: 'Needs a one-time model download before it can run.',
  needsKey: 'Routed to a cloud provider that has no API key yet — add one to enable it.',
  needsConsent: 'Has a key but needs your consent to send data to the cloud provider.',
  unavailable: 'Not available here (download blocked offline, or no runnable path).',
};

/** Map a readiness status to its label (unknown -> the raw status, defensive). */
export function readinessLabel(status: ReadinessStatus): string {
  return READINESS_LABEL[status] ?? status;
}

/** Map a readiness status to its status class (unknown -> "", defensive). */
export function readinessClass(status: ReadinessStatus): string {
  return READINESS_CLASS[status] ?? '';
}

/** Map a readiness status to its plain-language hint (unknown -> "", defensive). */
export function readinessHint(status: ReadinessStatus): string {
  return READINESS_HINT[status] ?? '';
}

/**
 * Human display name for a raw provider id/slug (§8 Voice). A lowercase config
 * slug ("openai", "gpt", "local") must NEVER leak into a user-visible string.
 * Known providers map to their proper brand name; anything else is title-cased
 * so an unusual slug still reads as words, never bare lowercase. In this app's
 * routing a `gpt`/`openai` slug denotes OpenAI and `claude` denotes Anthropic,
 * so each aliases to the brand a user recognises.
 */
export const PROVIDER_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  openai: 'OpenAI',
  gpt: 'OpenAI',
  anthropic: 'Anthropic',
  claude: 'Anthropic',
  google: 'Google',
  gemini: 'Google',
  'google-ai-studio': 'Google AI Studio',
  groq: 'Groq',
  cerebras: 'Cerebras',
  sambanova: 'SambaNova',
  mistral: 'Mistral',
  openrouter: 'OpenRouter',
  'github-models': 'GitHub Models',
  local: 'On-device',
};

/** Map a raw provider id to a display name (known brand, else title-cased). */
export function providerDisplayName(id: string): string {
  const known = PROVIDER_DISPLAY_NAMES[id.toLowerCase()];
  if (known) return known;
  return id
    .split(/[-_\s]+/)
    .filter((word) => word.length > 0)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * The capability-tied accessible name for a readiness fix action. Never
 * icon-only: the returned string names BOTH the verb and the capability/provider
 * so screen readers announce a self-describing control (WU-9 a11y requirement).
 * The provider is display-named (never a raw slug) and the capability is
 * article-led ("the <capability> model") so it reads naturally mid-sentence.
 * An unknown action kind falls back to the capability label (defensive).
 */
export function readinessActionLabel(action: ReadinessAction, capabilityLabel: string): string {
  const builders: Record<ReadinessAction['kind'], () => string> = {
    'assets.ensure': () => `Download the ${capabilityLabel} model`,
    openProviders: () => 'Add a provider key',
    setConsent: () =>
      action.provider
        ? `Grant consent for ${providerDisplayName(action.provider)}`
        : 'Grant consent for the provider',
  };
  return (builders[action.kind] ?? (() => capabilityLabel))();
}
