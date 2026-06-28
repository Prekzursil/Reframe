// advisorMeta.test.ts — pure helper coverage for the Models & System panel.
import { describe, it, expect } from 'vitest';
import {
  TIGHT_FRACTION,
  VERDICT_LABEL,
  componentAsset,
  fillPct,
  fillZone,
  fmtMb,
  fmtMbOrUnknown,
  licenseChip,
  presetLabel,
  presetTier,
  prettyName,
  verdictClass,
  verdictHint,
  verdictLabel,
} from './advisorMeta';

describe('verdict maps', () => {
  it('labels each verdict', () => {
    expect(verdictLabel('ok')).toBe('Will run');
    expect(verdictLabel('degraded')).toBe('Tight');
    expect(verdictLabel('unavailable')).toBe("Won't run");
    expect(VERDICT_LABEL.ok).toBe('Will run');
  });
  it('classes each verdict', () => {
    expect(verdictClass('ok')).toBe('is-ok');
    expect(verdictClass('degraded')).toBe('is-degraded');
    expect(verdictClass('unavailable')).toBe('is-unavailable');
  });
  it('hints each verdict', () => {
    expect(verdictHint('ok')).toContain('Fits');
    expect(verdictHint('degraded')).toContain('tight');
    expect(verdictHint('unavailable')).toContain('not run');
  });
  it('falls back for an unknown verdict value', () => {
    // @ts-expect-error — deliberately passing an out-of-union value for the guard.
    expect(verdictLabel('bogus')).toBe('bogus');
    // @ts-expect-error
    expect(verdictClass('bogus')).toBe('');
    // @ts-expect-error
    expect(verdictHint('bogus')).toBe('');
  });
});

describe('fmtMb', () => {
  it('formats GB and MB', () => {
    expect(fmtMb(2048)).toBe('2.0 GB');
    expect(fmtMb(512)).toBe('512 MB');
  });
  it('em-dashes null/zero/negative/NaN', () => {
    expect(fmtMb(null)).toBe('—');
    expect(fmtMb(undefined)).toBe('—');
    expect(fmtMb(0)).toBe('—');
    expect(fmtMb(-5)).toBe('—');
    expect(fmtMb(Number.NaN)).toBe('—');
  });
});

describe('fmtMbOrUnknown (F3 — null-RAM UX)', () => {
  it('formats a real megabyte count like fmtMb', () => {
    expect(fmtMbOrUnknown(32000)).toBe('31.3 GB');
    expect(fmtMbOrUnknown(512)).toBe('512 MB');
  });
  it('reads "unknown" (never "undefined MB") for an undetectable probe', () => {
    expect(fmtMbOrUnknown(null)).toBe('unknown');
    expect(fmtMbOrUnknown(undefined)).toBe('unknown');
    expect(fmtMbOrUnknown(0)).toBe('unknown');
    expect(fmtMbOrUnknown(-5)).toBe('unknown');
    expect(fmtMbOrUnknown(Number.NaN)).toBe('unknown');
  });
});

describe('fillPct / fillZone', () => {
  it('clamps fraction to 0..100', () => {
    expect(fillPct(3000, 6000)).toBe(50);
    expect(fillPct(8000, 6000)).toBe(100);
  });
  it('guards bad totals/used', () => {
    expect(fillPct(100, 0)).toBe(0);
    expect(fillPct(100, null)).toBe(0);
    expect(fillPct(null, 6000)).toBe(0);
    expect(fillPct(-1, 6000)).toBe(0);
  });
  it('zones tight above the threshold, ok below', () => {
    expect(fillZone(5500, 6000)).toBe('tight');
    expect(fillZone(3000, 6000)).toBe('ok');
    expect(fillZone(0, 6000)).toBe('ok');
    expect(fillZone(100, 0)).toBe('ok');
    expect(TIGHT_FRACTION).toBeCloseTo(0.85);
  });
});

describe('prettyName', () => {
  it('maps special component ids', () => {
    expect(prettyName('vlm_backbone')).toContain('SigLIP-2');
    expect(prettyName('smolvlm2')).toContain('SmolVLM2');
  });
  it('title-cases + de-snakes unknowns', () => {
    expect(prettyName('foo_bar')).toBe('Foo bar');
    expect(prettyName('zeta')).toBe('Zeta');
  });
});

describe('licenseChip', () => {
  it('commercial vs local-only', () => {
    expect(licenseChip(true)).toEqual({ label: 'Commercial OK', cls: 'is-commercial' });
    expect(licenseChip(false)).toEqual({ label: 'Local-only', cls: 'is-local-only' });
  });
});

describe('preset helpers', () => {
  it('labels known presets and passes through unknowns', () => {
    expect(presetLabel('tier0-numeric')).toContain('Tier 0');
    expect(presetLabel('tier2-vlm')).toContain('Tier 2');
    expect(presetLabel('mystery')).toBe('mystery');
  });
  it('maps presets to tier numbers (default 0)', () => {
    expect(presetTier('tier0-numeric')).toBe(0);
    expect(presetTier('tier1-multimodal')).toBe(1);
    expect(presetTier('tier2-vlm')).toBe(2);
    expect(presetTier('mystery')).toBe(0);
  });
});

describe('componentAsset', () => {
  it('maps model-backed components to their asset', () => {
    expect(componentAsset('smolvlm2')).toBe('smolvlm2-2.2b');
    expect(componentAsset('vlm_backbone')).toBe('siglip2-so400m');
  });
  it('returns null for zero-download floors', () => {
    expect(componentAsset('motion')).toBeNull();
    expect(componentAsset('diversity')).toBeNull();
  });
});
