// Tests for the renderer mirror of the OpusClip HOOK-CARD overlay + virality-rank
// gating (WU SP2).
//
// Pure-logic assertions PLUS a DRIFT GUARD that reads the REAL sidecar source
// (`hook_card.py`) and asserts the shared constants match — so the live preview
// palette / upper-third anchor / top-N default / 5 s window can never silently
// diverge from the libass burn (the same defence the karaoke preset uses).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import type { Candidate } from '../features/shortMakerLogic';
import {
  HOOK_CARD_FILL_HEX,
  HOOK_CARD_TEXT_HEX,
  HOOK_CARD_DEFAULT_TOP_N,
  HOOK_CARD_DEFAULT_SEC,
  HOOK_CARD_MIN_SEC,
  HOOK_CARD_MAX_SEC,
  HOOK_CARD_TOP_FRACTION,
  HOOK_CARD_MIN_ORDER_WIDTH,
  clampHookCardTopN,
  clampHookCardSec,
  selectHookCardRanks,
  orderPrefix,
  rankOrderedStem,
  hookCardEndSec,
  hookCardOverlayStyle,
} from './hookCardPreset';

// app/renderer/src/lib -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
const SIDECAR_HOOK_CARD = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'features', 'hook_card.py');

function cand(rank: number): Candidate {
  return { rank } as Candidate;
}

describe('hookCardPreset constants (WU SP2)', () => {
  it('pins the OpusClip card palette + defaults', () => {
    expect(HOOK_CARD_FILL_HEX).toBe('#FFFFFF');
    expect(HOOK_CARD_TEXT_HEX).toBe('#000000');
    expect(HOOK_CARD_DEFAULT_TOP_N).toBe(10);
    expect(HOOK_CARD_DEFAULT_SEC).toBe(5.0);
    expect(HOOK_CARD_MIN_SEC).toBe(0.5);
    expect(HOOK_CARD_MAX_SEC).toBe(30.0);
    expect(HOOK_CARD_TOP_FRACTION).toBe(0.12);
    expect(HOOK_CARD_MIN_ORDER_WIDTH).toBe(2);
  });

  it('DRIFT GUARD: matches the sidecar hook_card.py source', () => {
    const py = readFileSync(SIDECAR_HOOK_CARD, 'utf-8');
    const num = (name: string): number => {
      const m = py.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, 'm'));
      if (!m) throw new Error(`sidecar constant ${name} not found`);
      return Number(m[1]);
    };
    const str = (name: string): string => {
      const m = py.match(new RegExp(`^${name}\\s*=\\s*"([^"]+)"`, 'm'));
      if (!m) throw new Error(`sidecar constant ${name} not found`);
      return m[1];
    };
    expect(str('HOOK_CARD_FILL_HEX')).toBe(HOOK_CARD_FILL_HEX);
    expect(str('HOOK_CARD_TEXT_HEX')).toBe(HOOK_CARD_TEXT_HEX);
    expect(num('HOOK_CARD_DEFAULT_TOP_N')).toBe(HOOK_CARD_DEFAULT_TOP_N);
    expect(num('HOOK_CARD_DEFAULT_SEC')).toBe(HOOK_CARD_DEFAULT_SEC);
    expect(num('HOOK_CARD_MIN_SEC')).toBe(HOOK_CARD_MIN_SEC);
    expect(num('HOOK_CARD_MAX_SEC')).toBe(HOOK_CARD_MAX_SEC);
    expect(num('HOOK_CARD_TOP_FRACTION')).toBe(HOOK_CARD_TOP_FRACTION);
    expect(num('HOOK_CARD_MIN_ORDER_WIDTH')).toBe(HOOK_CARD_MIN_ORDER_WIDTH);
  });
});

describe('clampHookCardTopN', () => {
  it('rounds + floors a positive count', () => {
    expect(clampHookCardTopN(3)).toBe(3);
    expect(clampHookCardTopN(2.6)).toBe(3);
    expect(clampHookCardTopN(0)).toBe(1);
    expect(clampHookCardTopN(-4)).toBe(1);
  });
  it('defaults for non-number / non-finite', () => {
    expect(clampHookCardTopN('x')).toBe(HOOK_CARD_DEFAULT_TOP_N);
    expect(clampHookCardTopN(undefined)).toBe(HOOK_CARD_DEFAULT_TOP_N);
    expect(clampHookCardTopN(NaN)).toBe(HOOK_CARD_DEFAULT_TOP_N);
  });
});

describe('clampHookCardSec', () => {
  it('clamps into the [MIN, MAX] window', () => {
    expect(clampHookCardSec(4)).toBe(4);
    expect(clampHookCardSec(0.2)).toBe(HOOK_CARD_MIN_SEC);
    expect(clampHookCardSec(999)).toBe(HOOK_CARD_MAX_SEC);
  });
  it('defaults for non-positive / non-number / non-finite', () => {
    expect(clampHookCardSec(0)).toBe(HOOK_CARD_DEFAULT_SEC);
    expect(clampHookCardSec(-1)).toBe(HOOK_CARD_DEFAULT_SEC);
    expect(clampHookCardSec('5')).toBe(HOOK_CARD_DEFAULT_SEC);
    expect(clampHookCardSec(Infinity)).toBe(HOOK_CARD_DEFAULT_SEC);
  });
});

describe('selectHookCardRanks (top-N by virality rank)', () => {
  const cfg = (enabled: boolean, topN: number) => ({ enabled, topN, durationSec: 5 });

  it('keeps the N smallest ranks only', () => {
    const got = selectHookCardRanks([3, 1, 5, 2, 4].map(cand), cfg(true, 2));
    expect([...got].sort((a, b) => a - b)).toEqual([1, 2]);
  });
  it('returns all when topN exceeds the batch', () => {
    const got = selectHookCardRanks([2, 1].map(cand), cfg(true, 10));
    expect([...got].sort((a, b) => a - b)).toEqual([1, 2]);
  });
  it('is empty when disabled', () => {
    expect(selectHookCardRanks([1, 2].map(cand), cfg(false, 2)).size).toBe(0);
  });
  it('is empty for no candidates', () => {
    expect(selectHookCardRanks([], cfg(true, 2)).size).toBe(0);
  });
  it('falls back to 1-based position when a rank is non-finite', () => {
    const got = selectHookCardRanks([{ rank: NaN } as Candidate, cand(9)], cfg(true, 1));
    expect([...got]).toEqual([1]); // position 1 wins the single slot
  });
});

describe('orderPrefix + rankOrderedStem', () => {
  it('zero-pads to the max-rank width (min 2)', () => {
    expect(orderPrefix(1, 9)).toBe('01');
    expect(orderPrefix(2, 41)).toBe('02');
    expect(orderPrefix(41, 41)).toBe('41');
    expect(orderPrefix(7, 100)).toBe('007');
    expect(orderPrefix(3, 0)).toBe('03'); // max<1 -> width floor
  });
  it('builds the NN-base stem', () => {
    expect(rankOrderedStem('talk', 1, 41)).toBe('01-talk');
    expect(rankOrderedStem('talk', 12, 41)).toBe('12-talk');
  });
});

describe('hookCardEndSec (first ~5 s time-box)', () => {
  it('caps the window to the clip length when known', () => {
    expect(hookCardEndSec(5, 30)).toBe(5);
    expect(hookCardEndSec(5, 3)).toBe(3);
    expect(hookCardEndSec(5, 0)).toBe(5);
    expect(hookCardEndSec(0, 0)).toBe(HOOK_CARD_DEFAULT_SEC);
  });
});

describe('hookCardOverlayStyle', () => {
  it('is a white box with bold black text in the upper third', () => {
    expect(hookCardOverlayStyle()).toEqual({
      background: '#FFFFFF',
      color: '#000000',
      fontWeight: 700,
      topFraction: HOOK_CARD_TOP_FRACTION,
    });
  });
});
