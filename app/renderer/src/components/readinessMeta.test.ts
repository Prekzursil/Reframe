// readinessMeta.test.ts — WU-8 pins for the pure readiness label/class/hint map
// + the action accessible-name builder. Status is distinguished by TEXT (the
// label), never hue alone (WCAG 1.4.1); every status + action kind is table-tested
// and the defensive fallbacks are exercised.
import { describe, expect, it } from 'vitest';
import type { ReadinessAction, ReadinessStatus } from '../lib/rpc';
import {
  READINESS_CLASS,
  READINESS_HINT,
  READINESS_LABEL,
  providerDisplayName,
  readinessActionLabel,
  readinessClass,
  readinessHint,
  readinessLabel,
} from './readinessMeta';

const STATUSES: ReadinessStatus[] = [
  'ready',
  'needsDownload',
  'needsKey',
  'needsConsent',
  'unavailable',
];

describe('readinessLabel', () => {
  it('returns the exact visible label for all five statuses', () => {
    expect(readinessLabel('ready')).toBe('Ready');
    expect(readinessLabel('needsDownload')).toBe('Needs download');
    expect(readinessLabel('needsKey')).toBe('Needs key');
    expect(readinessLabel('needsConsent')).toBe('Needs consent');
    expect(readinessLabel('unavailable')).toBe('Unavailable');
  });
  it('every status maps to a non-empty text label (use-of-color guard)', () => {
    for (const status of STATUSES) {
      expect(readinessLabel(status).length).toBeGreaterThan(0);
    }
  });
  it('falls back to the raw status for an unknown value (defensive)', () => {
    expect(readinessLabel('mystery' as ReadinessStatus)).toBe('mystery');
  });
});

describe('readinessClass', () => {
  it('returns the status class for all five statuses', () => {
    for (const status of STATUSES) {
      expect(readinessClass(status)).toBe(READINESS_CLASS[status]);
      expect(readinessClass(status).startsWith('is-')).toBe(true);
    }
  });
  it('falls back to "" for an unknown value (defensive)', () => {
    expect(readinessClass('mystery' as ReadinessStatus)).toBe('');
  });
});

describe('readinessHint', () => {
  it('returns a non-empty hint for all five statuses', () => {
    for (const status of STATUSES) {
      expect(readinessHint(status)).toBe(READINESS_HINT[status]);
      expect(readinessHint(status).length).toBeGreaterThan(0);
    }
  });
  it('falls back to "" for an unknown value (defensive)', () => {
    expect(readinessHint('mystery' as ReadinessStatus)).toBe('');
  });
});

describe('label maps are complete', () => {
  it('every status has a label, class, and hint entry', () => {
    for (const status of STATUSES) {
      expect(READINESS_LABEL[status]).toBeTruthy();
      expect(READINESS_CLASS[status]).toBeTruthy();
      expect(READINESS_HINT[status]).toBeTruthy();
    }
  });
});

describe('readinessActionLabel', () => {
  it('names the verb + capability for assets.ensure (article-led, reads mid-sentence)', () => {
    const action: ReadinessAction = { kind: 'assets.ensure', assets: ['siglip2-so400m'] };
    expect(readinessActionLabel(action, 'Multimodal')).toBe('Download the Multimodal model');
  });
  it('names the add-key action', () => {
    const action: ReadinessAction = { kind: 'openProviders', provider: 'gpt' };
    expect(readinessActionLabel(action, 'AI: select')).toBe('Add a provider key');
  });
  it('display-names the provider for setConsent (never a raw lowercase slug)', () => {
    const action: ReadinessAction = { kind: 'setConsent', provider: 'gpt' };
    expect(readinessActionLabel(action, 'AI: vision')).toBe('Grant consent for OpenAI');
  });
  it('falls back to a generic provider name when setConsent omits the provider', () => {
    const action = { kind: 'setConsent' } as ReadinessAction;
    expect(readinessActionLabel(action, 'AI: vision')).toBe('Grant consent for the provider');
  });
  it('falls back to the capability label for an unknown action kind (defensive)', () => {
    const action = { kind: 'mystery' } as unknown as ReadinessAction;
    expect(readinessActionLabel(action, 'Some capability')).toBe('Some capability');
  });
});

describe('providerDisplayName', () => {
  it('maps known provider slugs to their proper brand name (never lowercase)', () => {
    expect(providerDisplayName('openai')).toBe('OpenAI');
    expect(providerDisplayName('gpt')).toBe('OpenAI');
    expect(providerDisplayName('claude')).toBe('Anthropic');
    expect(providerDisplayName('groq')).toBe('Groq');
    expect(providerDisplayName('local')).toBe('On-device');
  });
  it('is case-insensitive on the slug lookup', () => {
    expect(providerDisplayName('OpenAI')).toBe('OpenAI');
    expect(providerDisplayName('GROQ')).toBe('Groq');
  });
  it('title-cases an unknown slug so it never leaks bare lowercase', () => {
    expect(providerDisplayName('my-proxy')).toBe('My Proxy');
    expect(providerDisplayName('some_vendor')).toBe('Some Vendor');
  });
  it('drops empty segments from a delimiter-padded slug (defensive)', () => {
    expect(providerDisplayName('-edge-')).toBe('Edge');
  });
});
