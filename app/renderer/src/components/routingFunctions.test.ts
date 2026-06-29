// routingFunctions.test.ts — the M5 per-function override vocabulary helpers.
import { describe, it, expect } from 'vitest';
import type { RoutingMode } from '../lib/rpc';
import {
  AI_FUNCTIONS,
  AI_FUNCTION_LABELS,
  OVERRIDE_CHOICES,
  OVERRIDE_LABELS,
  applyOverrideChoice,
  choiceFor,
} from './routingFunctions';

describe('routingFunctions vocabulary', () => {
  it('matches the sidecar canonical function set', () => {
    expect([...AI_FUNCTIONS]).toEqual(['asr', 'select', 'caption', 'translation', 'director']);
  });

  it('labels every function and every choice', () => {
    for (const fn of AI_FUNCTIONS) expect(AI_FUNCTION_LABELS[fn]).toBeTruthy();
    for (const choice of OVERRIDE_CHOICES) expect(OVERRIDE_LABELS[choice]).toBeTruthy();
  });
});

describe('applyOverrideChoice (immutable)', () => {
  it('sets a concrete mode override', () => {
    const out = applyOverrideChoice({}, 'select', 'cloud');
    expect(out).toEqual({ select: 'cloud' });
  });

  it('inherit removes the override', () => {
    const out = applyOverrideChoice({ select: 'cloud' }, 'select', 'inherit');
    expect(out).toEqual({});
  });

  it('does not mutate the input', () => {
    const input: Record<string, RoutingMode> = { asr: 'local' };
    const out = applyOverrideChoice(input, 'select', 'auto');
    expect(input).toEqual({ asr: 'local' });
    expect(out).toEqual({ asr: 'local', select: 'auto' });
  });

  it('overwrites an existing override', () => {
    const out = applyOverrideChoice({ select: 'local' }, 'select', 'auto');
    expect(out).toEqual({ select: 'auto' });
  });
});

describe('choiceFor', () => {
  it('returns the override mode when set', () => {
    expect(choiceFor({ select: 'cloud' }, 'select')).toBe('cloud');
  });

  it('returns inherit when unset', () => {
    expect(choiceFor({}, 'select')).toBe('inherit');
  });

  it('returns inherit for an out-of-enum stored value', () => {
    expect(choiceFor({ select: 'bogus' as RoutingMode }, 'select')).toBe('inherit');
  });
});
