// transitions.test.ts — the pure transition catalogue + op builder (v1.5 transitions).
//
// The renderer half of the transition feature. The sidecar owns the render; this
// module owns what the user PICKS and the two honesty surfaces the picker must
// show before they commit: the real output duration (shorter than the sum of the
// clips) and the fact that a transition always re-encodes.

import { describe, expect, it } from 'vitest';
import {
  DEFAULT_TRANSITION_MS,
  DEFAULT_TRANSITION_STYLE,
  MAX_TRANSITION_MS,
  MIN_TRANSITION_MS,
  TRANSITION_STYLES,
  type TransitionStyleId,
  buildTransitionOp,
  clampTransitionMs,
  transitionBlocker,
  transitionOutputMs,
  transitionReencodeNote,
  transitionStyleBlurb,
  transitionStyleLabel,
} from './transitions';

describe('TRANSITION_STYLES', () => {
  it('mirrors the sidecar STYLE_IDS set, in the same sorted order', () => {
    // The sidecar builds `STYLE_IDS = tuple(sorted(TRANSITION_STYLES))`; a set or
    // order drift between the two sides would be invisible at runtime, so the
    // order is pinned here and cross-checked mechanically by the sidecar's
    // test_transition_ts_parity.
    expect(TRANSITION_STYLES.map((s) => s.id)).toEqual([
      'circleClose',
      'circleOpen',
      'dissolve',
      'fadeBlack',
      'fadeWhite',
      'slideLeft',
      'slideRight',
      'wipeDown',
      'wipeLeft',
      'wipeRight',
      'wipeUp',
    ]);
  });

  it('gives every style a human label and a plain-language blurb', () => {
    for (const style of TRANSITION_STYLES) {
      expect(style.label.length).toBeGreaterThan(0);
      expect(style.blurb.length).toBeGreaterThan(0);
      expect(style.label).not.toBe(style.id); // a label, not the raw wire id
    }
  });

  it('defaults to the cross-dissolve', () => {
    expect(DEFAULT_TRANSITION_STYLE).toBe('dissolve');
    expect(TRANSITION_STYLES.some((s) => s.id === DEFAULT_TRANSITION_STYLE)).toBe(true);
  });
});

describe('transitionStyleLabel', () => {
  it('resolves a known id to its label', () => {
    expect(transitionStyleLabel('dissolve')).toBe('Cross dissolve');
    expect(transitionStyleLabel('fadeBlack')).toBe('Fade through black');
  });

  it('falls back to the raw id for an unknown style', () => {
    // Defensive: a plan from an older/newer sidecar could carry a style this
    // build does not know. Render the id rather than "undefined".
    expect(transitionStyleLabel('starWipe' as TransitionStyleId)).toBe('starWipe');
  });
});

describe('transitionStyleBlurb', () => {
  it('resolves a known id to its blurb', () => {
    expect(transitionStyleBlurb('dissolve')).toMatch(/blend through each other/);
  });

  it('is empty for an unknown style rather than undefined', () => {
    // The picker renders this straight into a <p>; a plan from a newer sidecar
    // could name a style this build has no copy for, and "undefined" must never
    // reach the DOM. Lives here, not in the component, so the guard is testable.
    expect(transitionStyleBlurb('starWipe' as TransitionStyleId)).toBe('');
  });
});

describe('clampTransitionMs', () => {
  it('passes an in-range value through', () => {
    expect(clampTransitionMs(750)).toBe(750);
  });

  it('clamps to the sidecar floor and ceiling', () => {
    expect(clampTransitionMs(1)).toBe(MIN_TRANSITION_MS);
    expect(clampTransitionMs(999_999)).toBe(MAX_TRANSITION_MS);
  });

  it('truncates to whole milliseconds', () => {
    expect(clampTransitionMs(400.9)).toBe(400);
  });

  it('falls back to the default for a non-finite value', () => {
    expect(clampTransitionMs(Number.NaN)).toBe(DEFAULT_TRANSITION_MS);
    expect(clampTransitionMs(Number.POSITIVE_INFINITY)).toBe(DEFAULT_TRANSITION_MS);
  });
});

describe('transitionOutputMs', () => {
  it('SUBTRACTS one overlap per boundary (a transition is not a concat)', () => {
    // 10s + 20s + 30s with a 2s transition = 56s, not 60s. This is the number
    // the picker shows so the user sees the timeline actually get shorter.
    expect(transitionOutputMs([10_000, 20_000, 30_000], 2_000)).toBe(56_000);
    expect(transitionOutputMs([10_000, 10_000], 1_000)).toBe(19_000);
  });

  it('is the plain duration for a single clip (no boundary to overlap)', () => {
    expect(transitionOutputMs([10_000], 1_000)).toBe(10_000);
  });

  it('is zero for no clips', () => {
    expect(transitionOutputMs([], 1_000)).toBe(0);
  });
});

describe('transitionBlocker', () => {
  it('passes a valid selection', () => {
    expect(transitionBlocker([10_000, 20_000], 1_000)).toBeNull();
  });

  it('blocks a single clip — there is no boundary to treat', () => {
    expect(transitionBlocker([10_000], 1_000)).toMatch(/at least two clips/);
  });

  it('blocks a clip that cannot outlast the transition, naming it', () => {
    // Mirrors the engine precondition (transitions.xfade_offsets) so the user is
    // stopped in the picker instead of after a failed render.
    const reason = transitionBlocker([10_000, 400], 1_000);
    expect(reason).toMatch(/Clip 2/);
    expect(reason).toMatch(/shorter than/);
  });

  it('blocks a clip exactly the transition length', () => {
    expect(transitionBlocker([1_000, 10_000], 1_000)).toMatch(/Clip 1/);
  });
});

describe('transitionReencodeNote', () => {
  it('states the cost and the boundary count', () => {
    expect(transitionReencodeNote(3)).toMatch(/re-encode/);
    expect(transitionReencodeNote(3)).toMatch(/2 transition boundaries/);
  });

  it('is singular for one boundary', () => {
    expect(transitionReencodeNote(2)).toMatch(/1 transition boundary/);
  });

  it('is empty below two clips — no boundary, no cost to disclose', () => {
    expect(transitionReencodeNote(1)).toBe('');
  });
});

describe('buildTransitionOp', () => {
  it('builds a wire-valid transition op with the chosen style and duration', () => {
    const op = buildTransitionOp({
      id: 't1',
      clips: ['/b.mp4', '/c.mp4'],
      style: 'wipeLeft',
      durationMs: 1_200,
    });
    expect(op.kind).toBe('transition');
    expect(op.id).toBe('t1');
    expect(op.span).toBeNull(); // a boundary op acts on a junction, not a range
    expect(op.status).toBe('planned');
    expect(op.statusReason).toBeNull();
    expect(op.reversible).toBe(true);
    expect(op.params).toEqual({
      clips: ['/b.mp4', '/c.mp4'],
      style: 'wipeLeft',
      durationMs: 1_200,
    });
  });

  it('defaults the style and duration', () => {
    const op = buildTransitionOp({ id: 't1', clips: ['/b.mp4'] });
    expect(op.params.style).toBe(DEFAULT_TRANSITION_STYLE);
    expect(op.params.durationMs).toBe(DEFAULT_TRANSITION_MS);
  });

  it('clamps an out-of-range duration rather than sending it', () => {
    const op = buildTransitionOp({ id: 't1', clips: ['/b.mp4'], durationMs: 60_000 });
    expect(op.params.durationMs).toBe(MAX_TRANSITION_MS);
  });

  it('writes a deterministic, locally-derived rationale (no model text)', () => {
    const op = buildTransitionOp({
      id: 't1',
      clips: ['/b.mp4'],
      style: 'fadeBlack',
      durationMs: 800,
    });
    expect(op.rationale).toBe('Fade through black · 0.8s');
  });

  it('copies the clips array so the caller cannot mutate the op', () => {
    const clips = ['/b.mp4'];
    const op = buildTransitionOp({ id: 't1', clips });
    clips.push('/c.mp4');
    expect(op.params.clips).toEqual(['/b.mp4']);
  });
});
