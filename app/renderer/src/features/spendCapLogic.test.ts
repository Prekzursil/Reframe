// spendCapLogic.test.ts — the pure money/zone helpers for the Monthly spend cap.

import { describe, it, expect } from 'vitest';
import type { SpendInfo } from '../lib/rpc';
import {
  centsToDollars,
  dollarsToCents,
  formatDollars,
  progressCeilingCents,
  progressFraction,
  progressPercent,
  spendZone,
  zoneGlyph,
  zoneMessage,
  type SpendZone,
} from './spendCapLogic';

function info(over: Partial<SpendInfo> = {}): SpendInfo {
  return {
    month: '2026-06',
    monthToDateCents: 0,
    softLimitCents: 0,
    hardLimitCents: 0,
    enforceHardLimit: false,
    isEstimate: false,
    ...over,
  };
}

describe('centsToDollars / formatDollars', () => {
  it('renders a 2-dp dollar string', () => {
    expect(centsToDollars(1250)).toBe('12.50');
    expect(centsToDollars(100)).toBe('1.00');
    expect(centsToDollars(5)).toBe('0.05');
  });

  it('coerces zero / negative / non-finite to 0.00', () => {
    expect(centsToDollars(0)).toBe('0.00');
    expect(centsToDollars(-500)).toBe('0.00');
    expect(centsToDollars(Number.NaN)).toBe('0.00');
    expect(centsToDollars(Number.POSITIVE_INFINITY)).toBe('0.00');
  });

  it('rounds fractional cents to the nearest cent', () => {
    expect(centsToDollars(1250.6)).toBe('12.51');
  });

  it('formatDollars prefixes a $', () => {
    expect(formatDollars(1250)).toBe('$12.50');
    expect(formatDollars(0)).toBe('$0.00');
  });
});

describe('dollarsToCents', () => {
  it('parses a dollar string to integer cents', () => {
    expect(dollarsToCents('12.50')).toBe(1250);
    expect(dollarsToCents('1')).toBe(100);
    expect(dollarsToCents('0.05')).toBe(5);
  });

  it('rounds to the nearest cent', () => {
    expect(dollarsToCents('12.005')).toBe(1201);
    expect(dollarsToCents('0.004')).toBe(0);
  });

  it('coerces blank / non-numeric / negative / zero to 0', () => {
    expect(dollarsToCents('')).toBe(0);
    expect(dollarsToCents('abc')).toBe(0);
    expect(dollarsToCents('-5')).toBe(0);
    expect(dollarsToCents('0')).toBe(0);
  });
});

describe('spendZone', () => {
  it('no-cap when neither soft nor hard is set', () => {
    expect(spendZone(info({ monthToDateCents: 999 }))).toBe('no-cap');
  });

  it('ok when under the soft cap', () => {
    expect(spendZone(info({ monthToDateCents: 500, softLimitCents: 1000 }))).toBe('ok');
  });

  it('ok when only a hard cap is set and MTD is under it', () => {
    expect(spendZone(info({ monthToDateCents: 500, hardLimitCents: 1000 }))).toBe('ok');
  });

  it('near at/over the soft cap but under the hard cap', () => {
    expect(
      spendZone(info({ monthToDateCents: 1000, softLimitCents: 1000, hardLimitCents: 5000 })),
    ).toBe('near');
    expect(
      spendZone(info({ monthToDateCents: 1200, softLimitCents: 1000, hardLimitCents: 5000 })),
    ).toBe('near');
  });

  it('blocked at/over the hard cap (hard wins over soft)', () => {
    expect(
      spendZone(info({ monthToDateCents: 5000, softLimitCents: 1000, hardLimitCents: 5000 })),
    ).toBe('blocked');
    expect(
      spendZone(info({ monthToDateCents: 9000, softLimitCents: 1000, hardLimitCents: 5000 })),
    ).toBe('blocked');
  });

  it('clamps a negative MTD to 0 before classifying', () => {
    expect(spendZone(info({ monthToDateCents: -100, softLimitCents: 1000 }))).toBe('ok');
  });

  it('treats a zero/absent soft as not-set even with a hard cap', () => {
    expect(
      spendZone(info({ monthToDateCents: 100, softLimitCents: 0, hardLimitCents: 1000 })),
    ).toBe('ok');
  });
});

describe('progressCeilingCents / progressFraction / progressPercent', () => {
  it('uses the hard cap as the ceiling when set', () => {
    expect(progressCeilingCents(info({ softLimitCents: 1000, hardLimitCents: 5000 }))).toBe(5000);
  });

  it('falls back to the soft cap when only soft is set', () => {
    expect(progressCeilingCents(info({ softLimitCents: 1000 }))).toBe(1000);
  });

  it('reports a zero ceiling when neither is set', () => {
    expect(progressCeilingCents(info())).toBe(0);
  });

  it('fraction is 0 with no ceiling', () => {
    expect(progressFraction(info({ monthToDateCents: 500 }))).toBe(0);
  });

  it('fraction is MTD / ceiling, clamped to [0,1]', () => {
    expect(progressFraction(info({ monthToDateCents: 2500, hardLimitCents: 5000 }))).toBe(0.5);
    expect(progressFraction(info({ monthToDateCents: -100, hardLimitCents: 5000 }))).toBe(0);
    expect(progressFraction(info({ monthToDateCents: 9000, hardLimitCents: 5000 }))).toBe(1);
  });

  it('percent is a whole number 0..100', () => {
    expect(progressPercent(info({ monthToDateCents: 2500, hardLimitCents: 5000 }))).toBe(50);
    expect(progressPercent(info({ monthToDateCents: 1234, hardLimitCents: 5000 }))).toBe(25);
    expect(progressPercent(info())).toBe(0);
  });
});

describe('zoneGlyph', () => {
  it('maps each zone to a distinct non-color glyph', () => {
    const glyphs: Record<SpendZone, string> = {
      'no-cap': zoneGlyph('no-cap'),
      ok: zoneGlyph('ok'),
      near: zoneGlyph('near'),
      blocked: zoneGlyph('blocked'),
    };
    expect(glyphs.blocked).toBe('⛔');
    expect(glyphs.near).toBe('⚠');
    expect(glyphs.ok).toBe('✓');
    expect(glyphs['no-cap']).toBe('ℹ');
    // All four glyphs are distinct (the icon carries the signal, not color).
    expect(new Set(Object.values(glyphs)).size).toBe(4);
  });
});

describe('zoneMessage', () => {
  it('blocked copy distinguishes enforced vs not-enforced', () => {
    expect(zoneMessage('blocked', true)).toContain('blocked');
    expect(zoneMessage('blocked', false)).toContain('not enforced');
  });

  it('near / ok / no-cap copy', () => {
    expect(zoneMessage('near', false)).toContain('Near the soft cap');
    expect(zoneMessage('ok', false)).toContain('Within budget');
    expect(zoneMessage('no-cap', false)).toContain('No spend cap set');
  });
});
