// providersKeysLogic.ts — pure logic for the Providers & Keys panel (WU-PROVIDERS).
//
// Kept separate from the React component so the catalog→picker dedup, the
// per-provider status state machine, and the readiness-action routing are unit
// tested directly (no DOM). No rpc, no React.
import type { CatalogEntry, ProviderConsent, ProviderEntry, ReadinessAction } from '../lib/rpc';
import { PROVIDER_META, type ProviderMeta } from './providerMeta';

/**
 * One pickable provider option for the "add a key" picker: the connection meta
 * (slug/baseUrl/consoleUrl/free) plus the catalog display facts (free limits +
 * privacy posture) for the row. Built by deduping the catalog by `provider`
 * (Groq has multiple model rows → one option) and joining to PROVIDER_META.
 */
export interface ProviderOption {
  meta: ProviderMeta;
  /** The provider's free-limit summary from its first catalog row (display). */
  freeLimits: string;
  /** Coarse privacy posture (SAFE / CONDITIONAL / AVOID) from the catalog. */
  privacyTier: string;
  /** train-on-input disclosure, surfaced before consent is granted. */
  trainsOnInput: boolean | 'conditional';
}

/**
 * Dedup the catalog into one pickable option per provider that HAS connection
 * meta. The catalog lists several model rows per provider (e.g. two Groq rows);
 * we keep the FIRST row's display facts (free limits / privacy) per provider.
 * Providers absent from PROVIDER_META are skipped (we cannot add a key without a
 * base URL). Stable order: first appearance in the catalog.
 */
export function providerOptions(catalog: CatalogEntry[]): ProviderOption[] {
  const seen = new Set<string>();
  const out: ProviderOption[] = [];
  for (const entry of catalog) {
    if (seen.has(entry.provider)) continue;
    const meta = PROVIDER_META[entry.provider];
    if (!meta) continue;
    seen.add(entry.provider);
    out.push({
      meta,
      freeLimits: entry.freeLimits,
      privacyTier: entry.privacyTier,
      trainsOnInput: entry.trainsOnInput,
    });
  }
  return out;
}

/**
 * The three clear status badges a configured provider shows:
 *   * `needs-key`  — the entry exists but has no key yet (or all redacted away),
 *   * `configured` — it has at least one key but has NOT been verified this session,
 *   * `working`    — its key passed a `providers.testKey` validation ping.
 */
export type ProviderStatus = 'needs-key' | 'configured' | 'working';

/** Human label for a status badge (text, never hue alone — WCAG 1.4.1). */
export function statusLabel(status: ProviderStatus): string {
  if (status === 'working') return 'Working';
  if (status === 'configured') return 'Configured';
  return 'Needs key';
}

/**
 * Derive a configured provider's status. `tested` is the last in-session
 * `providers.testKey` outcome for this provider id (true=pass, false=fail,
 * undefined=not tested). A failed test does NOT downgrade below "Configured"
 * (the key is present; it just didn't validate) — only a PASS promotes to
 * "Working". With no keys it is always "Needs key" regardless of test state.
 */
export function providerStatus(entry: ProviderEntry, tested: boolean | undefined): ProviderStatus {
  const keys = Array.isArray(entry.apiKeys) ? entry.apiKeys : [];
  if (keys.length === 0) return 'needs-key';
  if (tested === true) return 'working';
  return 'configured';
}

/** Normalize a provider's consent (absent fields read as not-granted/false). */
export function consentOf(
  perProvider: Record<string, ProviderConsent> | undefined,
  provider: string,
): { text: boolean; frames: boolean } {
  const c = perProvider?.[provider];
  return { text: Boolean(c?.text), frames: Boolean(c?.frames) };
}

/**
 * Which Settings sub-section a readiness fix action routes to. `assets.ensure`
 * (download) stays on Models & System; `openProviders` and `setConsent` route to
 * the Providers & Keys section (this WU's fix for both dead-ends). Pure + total.
 */
export function actionSection(action: ReadinessAction): 'models' | 'providers' {
  return action.kind === 'assets.ensure' ? 'models' : 'providers';
}
