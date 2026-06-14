// timelineOps.test.ts — unit tests for the pure cue operations (P2 T1).
//
// DONE-WHEN: every op (incl. clamping) is covered and undo round-trips.

import { describe, it, expect } from 'vitest';

import {
  MAX_HISTORY,
  MIN_CUE_SEC,
  canRedo,
  canUndo,
  createHistory,
  cueRectStyle,
  dragEdge,
  mergeAt,
  mergeCues,
  pushHistory,
  redo,
  renumber,
  retimeAt,
  retimeCue,
  splitAt,
  splitCue,
  timeFromClientX,
  undo,
  type Cue,
} from './timelineOps';

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function cue(index: number, start: number, end: number, text: string): Cue {
  return { index, start, end, text };
}

/** Three well-spaced cues: [0,2] [3,5] [6,8]. */
function threeCues(): Cue[] {
  return [
    cue(1, 0, 2, 'hello world'),
    cue(2, 3, 5, 'second cue'),
    cue(3, 6, 8, 'third one'),
  ];
}

// ---------------------------------------------------------------------------
// renumber
// ---------------------------------------------------------------------------

describe('renumber', () => {
  it('renumbers 1..N regardless of incoming indices', () => {
    const out = renumber([cue(9, 0, 1, 'a'), cue(2, 1, 2, 'b'), cue(2, 2, 3, 'c')]);
    expect(out.map((c) => c.index)).toEqual([1, 2, 3]);
  });

  it('does not mutate the input', () => {
    const input = [cue(9, 0, 1, 'a')];
    renumber(input);
    expect(input[0].index).toBe(9);
  });
});

// ---------------------------------------------------------------------------
// splitCue / splitAt
// ---------------------------------------------------------------------------

describe('splitCue', () => {
  it('splits at t with text divided at the proportional word boundary', () => {
    const halves = splitCue(cue(1, 0, 2, 'hello world'), 1.0);
    expect(halves).not.toBeNull();
    const [a, b] = halves!;
    expect(a.start).toBe(0);
    expect(a.end).toBe(1.0);
    expect(b.start).toBe(1.0);
    expect(b.end).toBe(2);
    expect(a.text).toBe('hello');
    expect(b.text).toBe('world');
  });

  it('clamps t into the splittable interior (low side)', () => {
    const [a, b] = splitCue(cue(1, 10, 12, 'x y'), 9.0)!;
    expect(a.end).toBeCloseTo(10 + MIN_CUE_SEC, 10);
    expect(b.start).toBeCloseTo(10 + MIN_CUE_SEC, 10);
  });

  it('clamps t into the splittable interior (high side)', () => {
    const [a] = splitCue(cue(1, 10, 12, 'x y'), 99)!;
    expect(a.end).toBeCloseTo(12 - MIN_CUE_SEC, 10);
  });

  it('puts all words on one side when t is clamped to an edge', () => {
    const [a, b] = splitCue(cue(1, 0, 10, 'one two three four'), 0)!;
    // t clamps to 0.05 -> frac 0.005 -> k = 0 words on the left.
    expect(a.text).toBe('');
    expect(b.text).toBe('one two three four');
  });

  it('returns null for a cue too short to split', () => {
    expect(splitCue(cue(1, 0, MIN_CUE_SEC, 'tiny'), 0.02)).toBeNull();
  });

  it('handles empty text', () => {
    const [a, b] = splitCue(cue(1, 0, 2, ''), 1)!;
    expect(a.text).toBe('');
    expect(b.text).toBe('');
  });
});

describe('splitAt', () => {
  it('replaces position pos with two cues and renumbers', () => {
    const out = splitAt(threeCues(), 0, 1.0);
    expect(out).toHaveLength(4);
    expect(out.map((c) => c.index)).toEqual([1, 2, 3, 4]);
    expect(out[0].end).toBe(1.0);
    expect(out[1].start).toBe(1.0);
    // later cues untouched in VALUE — but renumbered (line above pins [1,2,3,4]),
    // so the former cue 2 now carries index 3.
    expect(out[2]).toEqual({ ...threeCues()[1], index: 3 });
  });

  it('returns the SAME array for an invalid position', () => {
    const input = threeCues();
    expect(splitAt(input, -1, 1)).toBe(input);
    expect(splitAt(input, 3, 1)).toBe(input);
    expect(splitAt(input, 0.5, 1)).toBe(input);
  });

  it('returns the SAME array when the cue is unsplittable', () => {
    const input = [cue(1, 0, MIN_CUE_SEC, 'tiny')];
    expect(splitAt(input, 0, 0.01)).toBe(input);
  });
});

// ---------------------------------------------------------------------------
// mergeCues / mergeAt
// ---------------------------------------------------------------------------

describe('mergeCues', () => {
  it('spans both cues and joins texts in time order', () => {
    const merged = mergeCues(cue(1, 0, 2, 'hello world'), cue(2, 3, 5, 'second cue'));
    expect(merged).toEqual({ index: 1, start: 0, end: 5, text: 'hello world second cue' });
  });

  it('is order-independent (joins by time, not argument order)', () => {
    const merged = mergeCues(cue(2, 3, 5, 'later'), cue(1, 0, 2, 'earlier'));
    expect(merged.start).toBe(0);
    expect(merged.end).toBe(5);
    expect(merged.text).toBe('earlier later');
    expect(merged.index).toBe(1); // earlier cue's index survives
  });

  it('drops empty halves from the joined text', () => {
    expect(mergeCues(cue(1, 0, 1, '  '), cue(2, 1, 2, 'kept')).text).toBe('kept');
    expect(mergeCues(cue(1, 0, 1, 'kept'), cue(2, 1, 2, '')).text).toBe('kept');
  });
});

describe('mergeAt', () => {
  it('merges pos with its next neighbor and renumbers', () => {
    const out = mergeAt(threeCues(), 0);
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual({ index: 1, start: 0, end: 5, text: 'hello world second cue' });
    expect(out[1].index).toBe(2);
  });

  it('returns the SAME array when pos is the last cue or invalid', () => {
    const input = threeCues();
    expect(mergeAt(input, 2)).toBe(input);
    expect(mergeAt(input, -1)).toBe(input);
    expect(mergeAt(input, 99)).toBe(input);
  });
});

// ---------------------------------------------------------------------------
// retimeCue / retimeAt
// ---------------------------------------------------------------------------

describe('retimeCue', () => {
  it('applies new times', () => {
    expect(retimeCue(cue(1, 0, 2, 'a'), 1, 4)).toEqual(cue(1, 1, 4, 'a'));
  });

  it('clamps a negative start to 0', () => {
    expect(retimeCue(cue(1, 0, 2, 'a'), -5, 2).start).toBe(0);
  });

  it('enforces the minimum duration by pushing end out', () => {
    const out = retimeCue(cue(1, 0, 2, 'a'), 1, 1);
    expect(out.end - out.start).toBeCloseTo(MIN_CUE_SEC, 10);
  });
});

describe('retimeAt', () => {
  it('retimes within the neighbor gap, keeping untouched cue identity', () => {
    const input = threeCues();
    const out = retimeAt(input, 1, 2.5, 5.5);
    expect(out[1].start).toBe(2.5);
    expect(out[1].end).toBe(5.5);
    expect(out[0]).toBe(input[0]);
    expect(out[2]).toBe(input[2]);
  });

  it('clamps start to the previous cue end', () => {
    const out = retimeAt(threeCues(), 1, 1.0, 5);
    expect(out[1].start).toBe(2); // prev.end
  });

  it('clamps end to the next cue start', () => {
    const out = retimeAt(threeCues(), 1, 3, 7.5);
    expect(out[1].end).toBe(6); // next.start
  });

  it('first cue clamps start at 0, last cue end is unbounded', () => {
    const cues = threeCues();
    expect(retimeAt(cues, 0, -3, 1)[0].start).toBe(0);
    expect(retimeAt(cues, 2, 6, 1000)[2].end).toBe(1000);
  });

  it('preserves the minimum duration when the window collapses', () => {
    const out = retimeAt(threeCues(), 1, 5.99, 6.0);
    const c = out[1];
    expect(c.end - c.start).toBeGreaterThanOrEqual(MIN_CUE_SEC - 1e-9);
    expect(c.end).toBeLessThanOrEqual(6); // still inside the neighbor gap
    expect(c.start).toBeGreaterThanOrEqual(2);
  });

  it('returns the SAME array when the neighbor gap cannot hold a cue', () => {
    const tight = [cue(1, 0, 2, 'a'), cue(2, 2, 4, 'b'), cue(3, 4.01, 6, 'c')];
    // gap for pos 1 is [2, 4.01] — fine; make a truly impossible one:
    const impossible = [cue(1, 0, 2, 'a'), cue(2, 2, 2.04, 'b'), cue(3, 2.04, 6, 'c')];
    expect(retimeAt(impossible, 1, 0, 10)).toBe(impossible);
    expect(retimeAt(tight, 1, 2.5, 3.5)).not.toBe(tight);
  });

  it('returns the SAME array for an invalid position', () => {
    const input = threeCues();
    expect(retimeAt(input, 5, 0, 1)).toBe(input);
  });
});

// ---------------------------------------------------------------------------
// dragEdge
// ---------------------------------------------------------------------------

describe('dragEdge', () => {
  it('moves the start edge freely inside the gap', () => {
    const out = dragEdge(threeCues(), 1, 'start', 2.5);
    expect(out[1].start).toBe(2.5);
    expect(out[1].end).toBe(5);
  });

  it('clamps the start edge to the previous cue end', () => {
    const out = dragEdge(threeCues(), 1, 'start', 0.5);
    expect(out[1].start).toBe(2); // prev.end
  });

  it('clamps the start edge against its own end (min duration)', () => {
    const out = dragEdge(threeCues(), 1, 'start', 4.999);
    expect(out[1].start).toBeCloseTo(5 - MIN_CUE_SEC, 10);
  });

  it('moves the end edge freely inside the gap', () => {
    const out = dragEdge(threeCues(), 1, 'end', 5.5);
    expect(out[1].end).toBe(5.5);
  });

  it('clamps the end edge to the next cue start', () => {
    const out = dragEdge(threeCues(), 1, 'end', 7.5);
    expect(out[1].end).toBe(6); // next.start
  });

  it('clamps the end edge against its own start (min duration)', () => {
    const out = dragEdge(threeCues(), 1, 'end', 3.001);
    expect(out[1].end).toBeCloseTo(3 + MIN_CUE_SEC, 10);
  });

  it('first cue start clamps at 0; last cue end is unbounded', () => {
    const cues = threeCues();
    expect(dragEdge(cues, 0, 'start', -4)[0].start).toBe(0);
    expect(dragEdge(cues, 2, 'end', 500)[2].end).toBe(500);
  });

  it('keeps untouched cues identical (reference equality)', () => {
    const input = threeCues();
    const out = dragEdge(input, 1, 'end', 5.5);
    expect(out[0]).toBe(input[0]);
    expect(out[2]).toBe(input[2]);
    expect(out[1]).not.toBe(input[1]);
  });

  it('returns the SAME array for an invalid position', () => {
    const input = threeCues();
    expect(dragEdge(input, 7, 'end', 5)).toBe(input);
  });
});

// ---------------------------------------------------------------------------
// undo/redo history
// ---------------------------------------------------------------------------

describe('history', () => {
  it('push -> undo restores the previous state (round-trip)', () => {
    const initial = threeCues();
    let h = createHistory(initial);
    const after = splitAt(initial, 0, 1.0);
    h = pushHistory(h, after);
    expect(h.present).toBe(after);
    h = undo(h);
    expect(h.present).toBe(initial);
  });

  it('undo -> redo round-trips back to the op result', () => {
    const initial = threeCues();
    const after = mergeAt(initial, 0);
    let h = pushHistory(createHistory(initial), after);
    h = redo(undo(h));
    expect(h.present).toBe(after);
  });

  it('round-trips EVERY op through undo', () => {
    const initial = threeCues();
    const ops: Array<(c: Cue[]) => Cue[]> = [
      (c) => splitAt(c, 0, 1.0),
      (c) => mergeAt(c, 0),
      (c) => retimeAt(c, 1, 2.5, 5.5),
      (c) => dragEdge(c, 1, 'end', 5.5),
      (c) => dragEdge(c, 1, 'start', 2.5),
    ];
    for (const op of ops) {
      const h = pushHistory(createHistory(initial), op(initial));
      expect(undo(h).present).toBe(initial);
      expect(redo(undo(h)).present).toBe(h.present);
    }
  });

  it('multi-step undo walks back in order', () => {
    const s0 = threeCues();
    const s1 = splitAt(s0, 0, 1.0);
    const s2 = mergeAt(s1, 2);
    let h = pushHistory(pushHistory(createHistory(s0), s1), s2);
    h = undo(h);
    expect(h.present).toBe(s1);
    h = undo(h);
    expect(h.present).toBe(s0);
    expect(canUndo(h)).toBe(false);
  });

  it('a new push clears the redo branch (linear history)', () => {
    const s0 = threeCues();
    const s1 = splitAt(s0, 0, 1.0);
    let h = pushHistory(createHistory(s0), s1);
    h = undo(h);
    expect(canRedo(h)).toBe(true);
    const s1b = mergeAt(s0, 1);
    h = pushHistory(h, s1b);
    expect(canRedo(h)).toBe(false);
    expect(h.present).toBe(s1b);
  });

  it('undo at the floor and redo at the tip are no-ops', () => {
    const h = createHistory(threeCues());
    expect(undo(h)).toBe(h);
    expect(redo(h)).toBe(h);
  });

  it('pushing the same reference is a no-op', () => {
    const h = createHistory(threeCues());
    expect(pushHistory(h, h.present)).toBe(h);
  });

  it('is bounded at MAX_HISTORY past entries (oldest dropped)', () => {
    const states: Cue[][] = [];
    for (let i = 0; i <= MAX_HISTORY + 25; i += 1) {
      states.push([cue(1, i, i + 1, `state ${i}`)]);
    }
    let h = createHistory(states[0]);
    for (let i = 1; i < states.length; i += 1) h = pushHistory(h, states[i]);
    expect(h.past).toHaveLength(MAX_HISTORY);
    // Undo all the way down: the floor is state[len-1-MAX_HISTORY], not state 0.
    while (canUndo(h)) h = undo(h);
    expect(h.present).toBe(states[states.length - 1 - MAX_HISTORY]);
  });
});

// ---------------------------------------------------------------------------
// view helpers
// ---------------------------------------------------------------------------

describe('timeFromClientX', () => {
  it('maps a click position to media time', () => {
    expect(timeFromClientX(500, 0, 1000, 100)).toBe(50);
    expect(timeFromClientX(250, 50, 400, 60)).toBe(30);
  });

  it('clamps into [0, duration]', () => {
    expect(timeFromClientX(-20, 0, 1000, 100)).toBe(0);
    expect(timeFromClientX(5000, 0, 1000, 100)).toBe(100);
  });

  it('degrades to 0 for a zero-width rect or zero duration', () => {
    expect(timeFromClientX(500, 0, 0, 100)).toBe(0);
    expect(timeFromClientX(500, 0, 1000, 0)).toBe(0);
  });
});

describe('cueRectStyle', () => {
  it('computes left/width percentages', () => {
    expect(cueRectStyle(cue(1, 25, 50, 'x'), 100)).toEqual({ leftPct: 25, widthPct: 25 });
  });

  it('clamps cues that overflow the duration', () => {
    const style = cueRectStyle(cue(1, 90, 150, 'x'), 100);
    expect(style.leftPct).toBe(90);
    expect(style.widthPct).toBe(10);
  });

  it('degrades to zero for a zero duration', () => {
    expect(cueRectStyle(cue(1, 0, 1, 'x'), 0)).toEqual({ leftPct: 0, widthPct: 0 });
  });
});
