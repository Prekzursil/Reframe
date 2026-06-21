// providersKeysLogic.test.ts — pure logic for Providers & Keys (WU-PROVIDERS).
import { describe, it, expect } from 'vitest';
import type { CatalogEntry, ProviderEntry, ReadinessAction } from '../lib/rpc';
import {
  actionSection,
  consentOf,
  providerOptions,
  providerStatus,
  statusLabel,
} from './providersKeysLogic';

function catEntry(provider: string, overrides: Partial<CatalogEntry> = {}): CatalogEntry {
  return {
    id: `${provider}-model`,
    provider,
    model: 'A Model',
    capabilities: ['text'],
    contextTokens: 128000,
    perTaskTier: {},
    costClass: 'free',
    freeLimits: '30 RPM',
    freeLimitScore: 70,
    unit: 'token',
    trainsOnInput: false,
    privacyTier: 'SAFE',
    recommendedFor: [],
    notes: '',
    asOfDate: '2026-06-16',
    ...overrides,
  };
}

describe('providerOptions (catalog dedup → picker)', () => {
  it('dedups multiple model rows per provider to one option, first-seen order', () => {
    const opts = providerOptions([
      catEntry('Groq', { freeLimits: 'first', model: 'GPT-OSS' }),
      catEntry('Groq', { freeLimits: 'second', model: 'Llama' }),
      catEntry('Cerebras', { freeLimits: 'cb', trainsOnInput: 'conditional' }),
    ]);
    expect(opts.map((o) => o.meta.label)).toEqual(['Groq', 'Cerebras']);
    // Keeps the FIRST row's display facts per provider.
    expect(opts[0].freeLimits).toBe('first');
    expect(opts[1].trainsOnInput).toBe('conditional');
  });

  it('skips providers without connection meta (no base URL to add a key)', () => {
    const opts = providerOptions([catEntry('Groq'), catEntry('Totally Unknown Provider')]);
    expect(opts.map((o) => o.meta.label)).toEqual(['Groq']);
  });
});

describe('providerStatus + statusLabel', () => {
  const withKeys: ProviderEntry = { id: 'groq', provider: 'Groq', apiKeys: ['…WXYZ'] };
  const noKeys: ProviderEntry = { id: 'groq', provider: 'Groq', apiKeys: [] };
  const missingKeys: ProviderEntry = { id: 'groq', provider: 'Groq' };

  it('needs-key when there are no keys (regardless of test state)', () => {
    expect(providerStatus(noKeys, undefined)).toBe('needs-key');
    expect(providerStatus(noKeys, true)).toBe('needs-key');
    expect(providerStatus(missingKeys, false)).toBe('needs-key');
  });

  it('configured when keyed but untested or test failed', () => {
    expect(providerStatus(withKeys, undefined)).toBe('configured');
    expect(providerStatus(withKeys, false)).toBe('configured');
  });

  it('working only when a key passed validation', () => {
    expect(providerStatus(withKeys, true)).toBe('working');
  });

  it('labels each status with text (never hue alone)', () => {
    expect(statusLabel('needs-key')).toBe('Needs key');
    expect(statusLabel('configured')).toBe('Configured');
    expect(statusLabel('working')).toBe('Working');
  });
});

describe('consentOf', () => {
  it('reads a provider consent block, defaulting absent fields to false', () => {
    expect(consentOf({ Groq: { text: true } }, 'Groq')).toEqual({ text: true, frames: false });
    expect(consentOf({ Groq: { text: true, frames: true } }, 'Groq')).toEqual({
      text: true,
      frames: true,
    });
  });

  it('returns all-false for an unknown provider or absent map', () => {
    expect(consentOf({}, 'Groq')).toEqual({ text: false, frames: false });
    expect(consentOf(undefined, 'Groq')).toEqual({ text: false, frames: false });
  });
});

describe('actionSection (readiness nav routing)', () => {
  it('routes download actions to models and key/consent actions to providers', () => {
    const ensure: ReadinessAction = { kind: 'assets.ensure', assets: ['x'] };
    const openKey: ReadinessAction = { kind: 'openProviders', provider: 'Groq' };
    const consent: ReadinessAction = { kind: 'setConsent', provider: 'Groq' };
    expect(actionSection(ensure)).toBe('models');
    expect(actionSection(openKey)).toBe('providers');
    expect(actionSection(consent)).toBe('providers');
  });
});
