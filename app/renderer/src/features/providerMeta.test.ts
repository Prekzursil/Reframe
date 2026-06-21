// providerMeta.test.ts — the per-provider connection metadata table (WU-PROVIDERS).
// Verifies every catalog provider resolves to a complete, non-secret meta row,
// the free flag matches cost posture (OpenAI = paid), and the lookup misses
// cleanly.
import { describe, it, expect } from 'vitest';
import { PROVIDER_META, providerMeta } from './providerMeta';

describe('providerMeta', () => {
  it('resolves a known provider by its catalog display name', () => {
    const groq = providerMeta('Groq');
    expect(groq).not.toBeNull();
    expect(groq?.slug).toBe('groq');
    expect(groq?.baseUrl).toBe('https://api.groq.com/openai/v1');
    expect(groq?.defaultModel).toBe('llama-3.3-70b-versatile');
    expect(groq?.consoleUrl).toBe('https://console.groq.com');
    expect(groq?.free).toBe(true);
  });

  it('returns null for an unknown provider name', () => {
    expect(providerMeta('Nonexistent')).toBeNull();
  });

  it('marks OpenAI API as paid (no free key link)', () => {
    expect(providerMeta('OpenAI API')?.free).toBe(false);
  });

  it('omits Cloudflare Workers AI (per-account base URL is unresolvable here)', () => {
    expect(providerMeta('Cloudflare Workers AI')).toBeNull();
  });

  it('every meta row has slug, https base, a non-display model id, console URL, free flag', () => {
    const entries = Object.entries(PROVIDER_META);
    expect(entries.length).toBeGreaterThan(0);
    for (const [name, meta] of entries) {
      expect(meta.label).toBe(name);
      expect(meta.slug).toMatch(/^[a-z0-9-]+$/);
      expect(meta.baseUrl).toMatch(/^https:\/\//);
      // A real API model id is non-empty and never a human display name with spaces.
      expect(meta.defaultModel.length).toBeGreaterThan(0);
      expect(meta.defaultModel).not.toMatch(/\s/);
      expect(meta.consoleUrl).toMatch(/^https:\/\//);
      expect(typeof meta.free).toBe('boolean');
    }
  });

  it('exposes a frozen table (callers cannot mutate the shared meta)', () => {
    expect(Object.isFrozen(PROVIDER_META)).toBe(true);
  });
});
