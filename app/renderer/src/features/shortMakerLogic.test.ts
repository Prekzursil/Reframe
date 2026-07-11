// shortMakerLogic.test.ts — targeted unit tests for the pure logic helpers that
// the ShortMaker component tests don't already exercise end-to-end:
// resolveWindowApi, moveSelection, previewWindow's sourceStart fallback, the
// reviewReducer's non-matching-id paths, and errMsg's every branch.
import { afterEach, describe, expect, it } from 'vitest';

import {
  type Candidate,
  type ReviewItem,
  errMsg,
  moveSelection,
  nudgeCandidate,
  previewWindow,
  resolveWindowApi,
  reviewReducer,
  toReviewItems,
} from './shortMakerLogic';

function cand(over: Partial<Candidate> = {}): Candidate {
  return {
    rank: 1,
    start: 100,
    end: 140,
    durationSec: 40,
    hook: 'h',
    why: 'w',
    score: 90,
    sourceStart: 100,
    ...over,
  };
}

describe('resolveWindowApi', () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  it('returns the window.api bridge when present', () => {
    const api = { rpc: async () => ({}), onProgress: () => () => undefined };
    (globalThis as { window?: unknown }).window = { api };
    expect(resolveWindowApi()).toBe(api);
  });

  it('returns undefined when window or window.api is absent', () => {
    (globalThis as { window?: unknown }).window = {};
    expect(resolveWindowApi()).toBeUndefined();
  });
});

describe('moveSelection', () => {
  const items = toReviewItems([
    cand({ rank: 1, sourceStart: 1 }),
    cand({ rank: 2, sourceStart: 2 }),
    cand({ rank: 3, sourceStart: 3 }),
  ]);

  it('returns null for an empty list', () => {
    expect(moveSelection([], 'anything', 1)).toBeNull();
  });

  it('selects the first row when the current id is unknown/absent', () => {
    expect(moveSelection(items, null, 1)).toBe('1@1');
    expect(moveSelection(items, 'no-such-id', -1)).toBe('1@1');
  });

  it('moves down/up and clamps at the ends', () => {
    expect(moveSelection(items, '1@1', 1)).toBe('2@2');
    expect(moveSelection(items, '2@2', -1)).toBe('1@1');
    expect(moveSelection(items, '1@1', -1)).toBe('1@1'); // clamp at top
    expect(moveSelection(items, '3@3', 1)).toBe('3@3'); // clamp at bottom
  });
});

// nudgeCandidate — the in-point (sourceStart) MUST move with `start` so the
// preview window AND the exported cut honour a start-nudge (not a no-op).
describe('nudgeCandidate sourceStart tracking', () => {
  it('moves sourceStart in lockstep with start on a start-nudge', () => {
    const c = nudgeCandidate(cand({ start: 100, end: 140, durationSec: 40, sourceStart: 100 }), 5, 0);
    expect(c.start).toBe(105);
    expect(c.sourceStart).toBe(105);
    // the invariant that keeps preview + export authoritative:
    expect(c.sourceStart).toBe(c.start);
  });

  it('previewWindow honours a start-nudge (in-point actually moves)', () => {
    const c = nudgeCandidate(cand({ start: 100, end: 140, durationSec: 40, sourceStart: 100 }), 5, 0);
    // was a no-op before the fix (previewWindow read the stale sourceStart=100).
    expect(previewWindow(c)).toEqual({ start: 105, end: 140 });
  });

  it('a window-slide (equal start+end delta) slides, not stretches — duration preserved', () => {
    const base = cand({ start: 100, end: 140, durationSec: 40, sourceStart: 100 });
    const c = nudgeCandidate(base, 5, 5);
    // both edges shift by +5 -> the whole window slides, duration unchanged.
    expect(c.durationSec).toBe(base.durationSec);
    const win = previewWindow(c);
    expect(win.start).toBe(105);
    expect(win.end).toBe(145);
    expect(win.end - win.start).toBe(base.durationSec);
  });

  it('clamps sourceStart at 0 when a start-nudge would go negative', () => {
    const c = nudgeCandidate(cand({ start: 3, end: 40, durationSec: 37, sourceStart: 3 }), -10, 0);
    expect(c.start).toBe(0);
    expect(c.sourceStart).toBe(0);
  });
});

describe('previewWindow', () => {
  it('uses sourceStart when present', () => {
    expect(previewWindow(cand({ sourceStart: 50, end: 90 }))).toEqual({ start: 50, end: 90 });
  });

  it('falls back to start when sourceStart is nullish', () => {
    const c = cand({ start: 12, end: 40 });
    // Force the nullish-coalescing fallback path.
    (c as { sourceStart?: number }).sourceStart = undefined;
    expect(previewWindow(c)).toEqual({ start: 12, end: 40 });
  });

  it('keeps end >= start', () => {
    expect(previewWindow(cand({ sourceStart: 100, end: 50 }))).toEqual({ start: 100, end: 100 });
  });
});

describe('reviewReducer non-matching ids', () => {
  const state: ReviewItem[] = toReviewItems([cand({ rank: 1, sourceStart: 1 })]);

  it('approve/discard/pending leave non-matching items untouched', () => {
    expect(reviewReducer(state, { type: 'approve', id: 'nope' })).toEqual(state);
    expect(reviewReducer(state, { type: 'discard', id: 'nope' })).toEqual(state);
  });

  it('nudge leaves a non-matching item untouched (identity map branch)', () => {
    const out = reviewReducer(state, { type: 'nudge', id: 'nope', deltaStart: 1, deltaEnd: 1 });
    expect(out[0].current).toEqual(state[0].current);
  });

  it('reset leaves a non-matching item untouched', () => {
    const nudged = reviewReducer(state, {
      type: 'nudge',
      id: '1@1',
      deltaStart: 0,
      deltaEnd: 5,
    });
    const out = reviewReducer(nudged, { type: 'reset', id: 'nope' });
    expect(out[0].current.end).toBe(nudged[0].current.end); // unchanged
  });
});

describe('errMsg', () => {
  it('returns the message of an Error', () => {
    expect(errMsg(new Error('boom'))).toBe('boom');
  });
  it('returns a string error verbatim', () => {
    expect(errMsg('just a string')).toBe('just a string');
  });
  it('stringifies an object with a message field', () => {
    expect(errMsg({ message: 42 })).toBe('42');
  });
  it('falls back to a generic message for anything else', () => {
    expect(errMsg(null)).toBe('Unknown error');
    expect(errMsg(123)).toBe('Unknown error');
    expect(errMsg({ noMessage: true })).toBe('Unknown error');
  });
});
