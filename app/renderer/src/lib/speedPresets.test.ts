// speedPresets.test.ts — full-branch coverage of the pure speed/re-time model.
//
// The window + the "is this sendable" predicate MIRROR the sidecar's authority
// (`sidecar/media_studio/features/speed.py` SPEED_MIN / SPEED_MAX /
// resolve_factor). These tests pin the mirror so the two cannot drift apart
// unnoticed: a factor this module calls sendable must be one the sidecar accepts.

import { describe, expect, it } from 'vitest';

import {
  SPEED_MAX,
  SPEED_MIN,
  SPEED_PRESETS,
  clampFactor,
  isRetimeFactor,
  retimedDuration,
  speedLabel,
} from './speedPresets';

describe('the factor window', () => {
  it('brackets 1x on both sides (slow motion AND speed-up are reachable)', () => {
    expect(SPEED_MIN).toBeLessThan(1);
    expect(SPEED_MAX).toBeGreaterThan(1);
  });

  it('matches the sidecar authority in speed.py', () => {
    // If this fails, one side moved and the other did not — fix BOTH.
    expect(SPEED_MIN).toBe(0.1);
    expect(SPEED_MAX).toBe(10);
  });
});

describe('SPEED_PRESETS', () => {
  it('offers slow motion AND speed-up, including the 1.5x the brief calls for', () => {
    const factors = SPEED_PRESETS.map((p) => p.factor);
    expect(factors.some((f) => f < 1)).toBe(true);
    expect(factors).toContain(1.5);
    expect(factors.some((f) => f > 1.5)).toBe(true);
  });

  it('every preset is a factor the sidecar would accept', () => {
    for (const preset of SPEED_PRESETS) {
      expect(isRetimeFactor(preset.factor)).toBe(true);
    }
  });

  it('has unique ids and non-empty labels', () => {
    const ids = SPEED_PRESETS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const preset of SPEED_PRESETS) expect(preset.label.length).toBeGreaterThan(0);
  });

  it('offers NO ramp preset — a keyframed ramp is not implemented anywhere', () => {
    // Guard against a future edit advertising a capability the engine lacks:
    // build_retime_argv takes ONE scalar factor, so every preset must be constant.
    for (const preset of SPEED_PRESETS) {
      expect(Number.isFinite(preset.factor)).toBe(true);
      expect(preset.label.toLowerCase()).not.toContain('ramp');
    }
  });
});

describe('clampFactor', () => {
  it('leaves an in-window factor alone', () => {
    expect(clampFactor(1.5)).toBe(1.5);
    expect(clampFactor(0.5)).toBe(0.5);
  });

  it('clamps below the floor and above the ceiling', () => {
    expect(clampFactor(0.001)).toBe(SPEED_MIN);
    expect(clampFactor(999)).toBe(SPEED_MAX);
  });

  it('keeps the exact bounds', () => {
    expect(clampFactor(SPEED_MIN)).toBe(SPEED_MIN);
    expect(clampFactor(SPEED_MAX)).toBe(SPEED_MAX);
  });

  it('falls back to 1x for a non-finite input (a slider can emit NaN)', () => {
    expect(clampFactor(Number.NaN)).toBe(1);
    expect(clampFactor(Number.POSITIVE_INFINITY)).toBe(1);
  });
});

describe('isRetimeFactor', () => {
  it('accepts an in-window factor either side of 1x', () => {
    expect(isRetimeFactor(0.5)).toBe(true);
    expect(isRetimeFactor(2)).toBe(true);
  });

  it('rejects exactly 1x — the sidecar refuses it as a no-op', () => {
    expect(isRetimeFactor(1)).toBe(false);
  });

  it('rejects out-of-window values', () => {
    expect(isRetimeFactor(0.05)).toBe(false);
    expect(isRetimeFactor(11)).toBe(false);
  });

  it('rejects non-numeric and non-finite input', () => {
    expect(isRetimeFactor('2')).toBe(false);
    expect(isRetimeFactor(null)).toBe(false);
    expect(isRetimeFactor(undefined)).toBe(false);
    expect(isRetimeFactor(Number.NaN)).toBe(false);
  });
});

describe('retimedDuration', () => {
  it('speeding up shortens, slowing down lengthens', () => {
    expect(retimedDuration(60, 2)).toBe(30);
    expect(retimedDuration(60, 0.5)).toBe(120);
  });

  it('an unknown source duration stays unknown (0)', () => {
    expect(retimedDuration(0, 2)).toBe(0);
    expect(retimedDuration(-5, 2)).toBe(0);
    expect(retimedDuration(Number.NaN, 2)).toBe(0);
  });

  it('a non-positive factor cannot produce a duration', () => {
    expect(retimedDuration(60, 0)).toBe(0);
  });
});

describe('speedLabel', () => {
  it('names the direction so the number is never ambiguous', () => {
    expect(speedLabel(0.5)).toContain('slower');
    expect(speedLabel(2)).toContain('faster');
  });

  it('drops a trailing zero so 2x is not "2.00x"', () => {
    expect(speedLabel(2)).toContain('2x');
    expect(speedLabel(1.5)).toContain('1.5x');
    expect(speedLabel(0.25)).toContain('0.25x');
  });

  it('calls 1x what it is', () => {
    expect(speedLabel(1)).toBe('1x (no change)');
  });
});
