// timelineOps.property.test.ts — fast-check property + model-based tests for the
// PURE cue operations (WU-B test-hardening).
//
// Append-only: this file ADDS coverage; it touches no source and no existing
// test. A fixed seed + bounded numRuns keep the vitest gate deterministic.
//
// Invariants (timelineOps.ts contract):
//   * renumber yields sequential 1..N indices and never mutates its input,
//   * structural ops (splitAt / mergeAt) preserve a 1..N index sequence,
//   * every list op keeps each cue's duration >= MIN_CUE_SEC and never lets a
//     cue cross its neighbors,
//   * dragEdge / retimeAt return the input array reference when nothing legal
//     changes (so callers can ===-check),
//   * the undo/redo history is bounded at MAX_HISTORY and undo∘push is identity,
//   * a RANDOM SEQUENCE of edit commands always lands on a well-formed,
//     non-overlapping, minimum-duration-respecting cue list.

import fc from 'fast-check';
import { describe, expect, it } from 'vitest';

import {
  MAX_HISTORY,
  MIN_CUE_SEC,
  canRedo,
  canUndo,
  createHistory,
  cueRectStyle,
  dragEdge,
  type History,
  mergeAt,
  pushHistory,
  redo,
  renumber,
  retimeAt,
  splitAt,
  timeFromClientX,
  undo,
  type Cue,
} from './timelineOps';

fc.configureGlobal({ numRuns: 75, seed: 0x5eed, endOnFailure: true });

// ---------------------------------------------------------------------------
// arbitraries
// ---------------------------------------------------------------------------

const wordText = fc
  .array(fc.stringMatching(/^[a-z]{1,5}$/), { maxLength: 6 })
  .map((words) => words.join(' '));

/** A well-formed, non-overlapping, minimum-duration-respecting cue list. */
const cueList = fc
  .array(
    fc.record({
      gap: fc.double({ min: 0, max: 5, noNaN: true }),
      dur: fc.double({ min: MIN_CUE_SEC, max: 8, noNaN: true }),
      text: wordText,
    }),
    { minLength: 0, maxLength: 8 },
  )
  .map((specs) => {
    let t = 0;
    return specs.map((s, i): Cue => {
      const start = t + s.gap;
      const end = start + s.dur;
      t = end;
      return { index: i + 1, start, end, text: s.text };
    });
  });

// ---------------------------------------------------------------------------
// shared structural checks
// ---------------------------------------------------------------------------

function assertWellFormed(cues: readonly Cue[]): void {
  cues.forEach((c, i) => {
    expect(c.index).toBe(i + 1);
    expect(c.end - c.start).toBeGreaterThanOrEqual(MIN_CUE_SEC - 1e-9);
    if (i > 0) {
      // never crosses the previous cue's end (non-overlapping)
      expect(c.start).toBeGreaterThanOrEqual(cues[i - 1].end - 1e-9);
    }
  });
}

// ---------------------------------------------------------------------------
// renumber
// ---------------------------------------------------------------------------

describe('renumber (property)', () => {
  it('produces sequential 1..N indices without mutating input', () => {
    fc.assert(
      fc.property(cueList, (cues) => {
        const snapshot = cues.map((c) => ({ ...c }));
        const out = renumber(cues);
        expect(out.map((c) => c.index)).toEqual(cues.map((_, i) => i + 1));
        expect(cues).toEqual(snapshot); // input untouched
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// structural list ops
// ---------------------------------------------------------------------------

describe('splitAt / mergeAt (property)', () => {
  it('splitAt keeps a 1..N sequence and respects MIN_CUE_SEC', () => {
    fc.assert(
      fc.property(
        cueList,
        fc.nat(),
        fc.double({ min: 0, max: 50, noNaN: true }),
        (cues, posSeed, t) => {
          if (cues.length === 0) return;
          const pos = posSeed % cues.length;
          const out = splitAt(cues, pos, t);
          // either unchanged (un-splittable) or grew by exactly one cue
          expect(out.length === cues.length || out.length === cues.length + 1).toBe(true);
          assertWellFormed(out);
        },
      ),
    );
  });

  it('mergeAt keeps a 1..N sequence and never overlaps', () => {
    fc.assert(
      fc.property(cueList, fc.nat(), (cues, posSeed) => {
        if (cues.length === 0) return;
        const pos = posSeed % cues.length;
        const out = mergeAt(cues, pos);
        expect(out.length === cues.length || out.length === cues.length - 1).toBe(true);
        assertWellFormed(out);
      }),
    );
  });

  it('an out-of-range position returns the SAME array reference', () => {
    fc.assert(
      fc.property(cueList, fc.integer({ min: -5, max: 20 }), (cues, pos) => {
        if (pos >= 0 && pos < cues.length) return; // only test invalid positions
        expect(splitAt(cues, pos, 1)).toBe(cues);
        expect(mergeAt(cues, pos)).toBe(cues);
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// edge / retime clamping
// ---------------------------------------------------------------------------

describe('dragEdge / retimeAt (property)', () => {
  it('dragEdge never violates MIN_CUE_SEC or crosses neighbors', () => {
    fc.assert(
      fc.property(
        cueList.filter((c) => c.length > 0),
        fc.nat(),
        fc.constantFrom<'start' | 'end'>('start', 'end'),
        fc.double({ min: -10, max: 60, noNaN: true }),
        (cues, posSeed, edge, t) => {
          const pos = posSeed % cues.length;
          const out = dragEdge(cues, pos, edge, t);
          const c = out[pos];
          expect(c.end - c.start).toBeGreaterThanOrEqual(MIN_CUE_SEC - 1e-9);
          if (pos > 0) expect(c.start).toBeGreaterThanOrEqual(cues[pos - 1].end - 1e-9);
          if (pos + 1 < cues.length) expect(c.end).toBeLessThanOrEqual(cues[pos + 1].start + 1e-9);
        },
      ),
    );
  });

  it('retimeAt keeps the cue inside the neighbor gap', () => {
    fc.assert(
      fc.property(
        cueList.filter((c) => c.length > 0),
        fc.nat(),
        fc.double({ min: -5, max: 60, noNaN: true }),
        fc.double({ min: -5, max: 60, noNaN: true }),
        (cues, posSeed, start, end) => {
          const pos = posSeed % cues.length;
          const out = retimeAt(cues, pos, start, end);
          // unchanged when the gap can't hold a minimum cue; else well-clamped
          if (out === cues) return;
          const c = out[pos];
          expect(c.end - c.start).toBeGreaterThanOrEqual(MIN_CUE_SEC - 1e-9);
          if (pos > 0) expect(c.start).toBeGreaterThanOrEqual(cues[pos - 1].end - 1e-9);
          if (pos + 1 < cues.length) expect(c.end).toBeLessThanOrEqual(cues[pos + 1].start + 1e-9);
        },
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// view helpers
// ---------------------------------------------------------------------------

describe('view helpers (property)', () => {
  it('timeFromClientX stays within [0, duration]', () => {
    fc.assert(
      fc.property(
        fc.double({ min: -1000, max: 4000, noNaN: true }),
        fc.double({ min: 1, max: 2000, noNaN: true }),
        fc.double({ min: 0.1, max: 600, noNaN: true }),
        (clientX, width, duration) => {
          const t = timeFromClientX(clientX, 0, width, duration);
          expect(t).toBeGreaterThanOrEqual(0);
          expect(t).toBeLessThanOrEqual(duration);
        },
      ),
    );
  });

  it('cueRectStyle percentages are in [0,100] and width is non-negative', () => {
    fc.assert(
      fc.property(
        cueList.filter((c) => c.length > 0),
        fc.double({ min: 0, max: 600, noNaN: true }),
        (cues, duration) => {
          const { leftPct, widthPct } = cueRectStyle(cues[0], duration);
          expect(leftPct).toBeGreaterThanOrEqual(0);
          expect(leftPct).toBeLessThanOrEqual(100);
          expect(widthPct).toBeGreaterThanOrEqual(0);
        },
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// undo/redo history (property)
// ---------------------------------------------------------------------------

describe('history (property)', () => {
  it('undo after push returns the prior present', () => {
    fc.assert(
      fc.property(cueList, cueList, (a, b) => {
        const h0 = createHistory(a);
        const h1 = pushHistory(h0, b);
        if (b === a) {
          expect(h1).toBe(h0); // same-ref push is a no-op
          return;
        }
        expect(h1.present).toBe(b);
        expect(canUndo(h1)).toBe(true);
        expect(undo(h1).present).toBe(a);
      }),
    );
  });

  it('history.past is bounded at MAX_HISTORY across many pushes', () => {
    fc.assert(
      fc.property(fc.array(cueList, { minLength: 0, maxLength: 130 }), (states) => {
        let h = createHistory([]);
        for (const s of states) h = pushHistory(h, [...s]); // fresh ref each push
        expect(h.past.length).toBeLessThanOrEqual(MAX_HISTORY);
      }),
    );
  });

  it('redo undoes an undo (round-trip)', () => {
    fc.assert(
      fc.property(cueList, cueList, (a, b) => {
        fc.pre(b !== a);
        const h = pushHistory(createHistory(a), b);
        const undone = undo(h);
        expect(canRedo(undone)).toBe(true);
        expect(redo(undone).present).toBe(b);
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// model-based: random sequences of edit commands (fc.commands)
// ---------------------------------------------------------------------------

interface Model {
  length: number;
}

class TimelineModel {
  cues: Cue[];
  history: History;
  constructor(initial: Cue[]) {
    this.cues = initial;
    this.history = createHistory(initial);
  }
  apply(next: Cue[]): void {
    this.history = pushHistory(this.history, next);
    this.cues = this.history.present;
  }
}

const SplitCmd = (pos: number, t: number): fc.Command<Model, TimelineModel> => ({
  check: () => true,
  run: (_m, r) => {
    const p = r.cues.length === 0 ? 0 : pos % r.cues.length;
    r.apply(splitAt(r.cues, p, t));
    assertWellFormed(r.cues);
  },
  toString: () => `split(${pos},${t})`,
});

const MergeCmd = (pos: number): fc.Command<Model, TimelineModel> => ({
  check: () => true,
  run: (_m, r) => {
    const p = r.cues.length === 0 ? 0 : pos % r.cues.length;
    r.apply(mergeAt(r.cues, p));
    assertWellFormed(r.cues);
  },
  toString: () => `merge(${pos})`,
});

const DragCmd = (
  pos: number,
  edge: 'start' | 'end',
  t: number,
): fc.Command<Model, TimelineModel> => ({
  check: () => true,
  run: (_m, r) => {
    const p = r.cues.length === 0 ? 0 : pos % r.cues.length;
    if (r.cues.length > 0) r.apply(dragEdge(r.cues, p, edge, t));
    assertWellFormed(r.cues);
  },
  toString: () => `drag(${pos},${edge},${t})`,
});

const UndoCmd: fc.Command<Model, TimelineModel> = {
  check: () => true,
  run: (_m, r) => {
    r.history = undo(r.history);
    r.cues = r.history.present;
    assertWellFormed(r.cues);
  },
  toString: () => 'undo',
};

describe('timeline edit sequences (model-based)', () => {
  it('any command sequence lands on a well-formed cue list', () => {
    const commands = fc.commands(
      [
        fc
          .tuple(fc.nat(), fc.double({ min: 0, max: 40, noNaN: true }))
          .map(([p, t]) => SplitCmd(p, t)),
        fc.nat().map((p) => MergeCmd(p)),
        fc
          .tuple(
            fc.nat(),
            fc.constantFrom<'start' | 'end'>('start', 'end'),
            fc.double({ min: -5, max: 50, noNaN: true }),
          )
          .map(([p, e, t]) => DragCmd(p, e, t)),
        fc.constant(UndoCmd),
      ],
      { maxCommands: 20 },
    );
    fc.assert(
      fc.property(cueList, commands, (initial, cmds) => {
        fc.modelRun(
          () => ({ model: { length: initial.length }, real: new TimelineModel(initial) }),
          cmds,
        );
      }),
    );
  });
});
