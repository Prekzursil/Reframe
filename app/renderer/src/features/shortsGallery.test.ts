// shortsGallery.test.ts — the pure produced-shorts virality-dashboard helpers
// (V1.1 WU R5). Covers the sort modes/labels, the non-destructive sort order
// (virality-first headline, recency fallback, missing-score sink, deterministic
// ties) and the mm:ss duration formatter. No React / no window.api.
import { describe, it, expect } from 'vitest';

import {
  type ShortsSort,
  SHORTS_SORT_MODES,
  SHORTS_SORT_LABELS,
  sortByCreatedAt,
  sortShorts,
  formatShortDuration,
} from './shortsGallery';
import type { ShortInfo } from '../lib/rpc';

function short(over: Partial<ShortInfo> = {}): ShortInfo {
  return {
    id: 'sid',
    path: '/out/clip.mp4',
    videoId: 'v1',
    sourceTitle: 'Talk',
    template: '',
    viralityPct: 50,
    durationSec: 30,
    width: 1080,
    height: 1920,
    createdAt: 1_700_000_000,
    thumbnailPath: '',
    hook: '',
    ...over,
  };
}

describe('shortsGallery sort modes', () => {
  it('lists virality first (the headline) then recent, with human labels', () => {
    expect(SHORTS_SORT_MODES).toEqual<ShortsSort[]>(['virality', 'recent']);
    expect(SHORTS_SORT_LABELS.virality).toBe('Virality score');
    expect(SHORTS_SORT_LABELS.recent).toBe('Recent');
  });
});

describe('sortByCreatedAt', () => {
  it('orders newest-first without mutating the input', () => {
    const input = [
      short({ id: 'a', createdAt: 1 }),
      short({ id: 'b', createdAt: 3 }),
      short({ id: 'c', createdAt: 2 }),
    ];
    expect(sortByCreatedAt(input).map((s) => s.id)).toEqual(['b', 'c', 'a']);
    // Input array untouched (immutability).
    expect(input.map((s) => s.id)).toEqual(['a', 'b', 'c']);
  });
});

describe('sortShorts', () => {
  it('orders by recency under "recent" mode', () => {
    const input = [
      short({ id: 'a', createdAt: 1 }),
      short({ id: 'b', createdAt: 3 }),
      short({ id: 'c', createdAt: 2 }),
    ];
    expect(sortShorts(input, 'recent').map((s) => s.id)).toEqual(['b', 'c', 'a']);
  });

  it('orders by viralityPct descending under "virality" mode', () => {
    const input = [
      short({ id: 'a', viralityPct: 40 }),
      short({ id: 'b', viralityPct: 90 }),
      short({ id: 'c', viralityPct: 70 }),
    ];
    expect(sortShorts(input, 'virality').map((s) => s.id)).toEqual(['b', 'c', 'a']);
  });

  it('sinks shorts with no virality below scored ones', () => {
    const unscored = short({ id: 'u', viralityPct: null });
    const scored = short({ id: 's', viralityPct: 10 });
    expect(sortShorts([unscored, scored], 'virality').map((s) => s.id)).toEqual(['s', 'u']);
  });

  it('treats a non-finite (NaN) viralityPct as unscored', () => {
    const nan = short({ id: 'nan', viralityPct: Number.NaN });
    const scored = short({ id: 'scored', viralityPct: 5 });
    expect(sortShorts([nan, scored], 'virality').map((s) => s.id)).toEqual(['scored', 'nan']);
  });

  it('breaks equal-virality ties by newest createdAt (deterministic)', () => {
    const older = short({ id: 'older', viralityPct: 60, createdAt: 1 });
    const newer = short({ id: 'newer', viralityPct: 60, createdAt: 2 });
    expect(sortShorts([older, newer], 'virality').map((s) => s.id)).toEqual(['newer', 'older']);
  });

  it('never mutates the input under virality mode', () => {
    const input = [short({ id: 'a', viralityPct: 1 }), short({ id: 'b', viralityPct: 2 })];
    sortShorts(input, 'virality');
    expect(input.map((s) => s.id)).toEqual(['a', 'b']);
  });
});

describe('formatShortDuration', () => {
  it('renders mm:ss (zero-padded, rounded)', () => {
    expect(formatShortDuration(42.4)).toBe('00:42');
    expect(formatShortDuration(65)).toBe('01:05');
    expect(formatShortDuration(600)).toBe('10:00');
  });

  it('renders a placeholder for non-finite / non-positive input', () => {
    expect(formatShortDuration(0)).toBe('--:--');
    expect(formatShortDuration(-3)).toBe('--:--');
    expect(formatShortDuration(Number.NaN)).toBe('--:--');
    expect(formatShortDuration(Number.POSITIVE_INFINITY)).toBe('--:--');
  });
});
