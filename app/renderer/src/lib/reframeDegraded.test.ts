// Tests for the reframe "degraded" (WU-3 no-silent-fallback) reader.
import { describe, it, expect } from 'vitest';
import {
  REFRAME_DEGRADED_KEY,
  reframeDegradedNotice,
  countDegraded,
  describeDegraded,
} from './reframeDegraded';

describe('reframeDegradedNotice', () => {
  it('reads a full sidecar notice off a clip', () => {
    expect(
      reframeDegradedNotice({
        path: '/out/1.mp4',
        reframeDegraded: {
          type: 'reframe.degraded',
          message: 'reframe: speaker tracking unavailable (no subject) — used center crop',
          reason: 'no subject',
        },
      }),
    ).toEqual({
      type: 'reframe.degraded',
      message: 'reframe: speaker tracking unavailable (no subject) — used center crop',
      reason: 'no subject',
    });
  });

  it('omits `reason` when the sidecar sent none (never invents one)', () => {
    expect(reframeDegradedNotice({ reframeDegraded: { type: 't', message: 'm' } })).toEqual({
      type: 't',
      message: 'm',
    });
  });

  it('defaults a missing/non-string `type` to the empty string', () => {
    expect(reframeDegradedNotice({ reframeDegraded: { type: 7, message: 'm' } })).toEqual({
      type: '',
      message: 'm',
    });
  });

  it('treats a blank/whitespace `reason` as absent', () => {
    expect(reframeDegradedNotice({ reframeDegraded: { message: 'm', reason: '   ' } })).toEqual({
      type: '',
      message: 'm',
    });
  });

  it('returns null for a healthy clip (no false-positive badge)', () => {
    expect(reframeDegradedNotice({ path: '/out/1.mp4' })).toBeNull();
  });

  it.each([
    ['null', null],
    ['undefined', undefined],
    ['a string', 'reframeDegraded'],
    ['a notice that is not an object', { reframeDegraded: 'degraded' }],
    ['a null notice', { reframeDegraded: null }],
    ['a notice with no message', { reframeDegraded: { type: 't' } }],
    ['a notice with a blank message', { reframeDegraded: { type: 't', message: '  ' } }],
    ['a notice with a non-string message', { reframeDegraded: { message: 12 } }],
  ])('returns null for %s', (_label, input) => {
    expect(reframeDegradedNotice(input)).toBeNull();
  });

  it('exposes the wire key it reads (pinned by the conformance test)', () => {
    expect(REFRAME_DEGRADED_KEY).toBe('reframeDegraded');
  });
});

describe('countDegraded', () => {
  it('counts only the clips carrying a notice', () => {
    expect(
      countDegraded([
        { path: '/a.mp4' },
        { path: '/b.mp4', reframeDegraded: { type: 't', message: 'm' } },
        { path: '/c.mp4', reframeDegraded: { type: 't', message: 'm2' } },
      ]),
    ).toBe(2);
  });

  it('is zero for an empty list', () => {
    expect(countDegraded([])).toBe(0);
  });
});

describe('describeDegraded', () => {
  // The summary states the COUNT only. It must not paraphrase the cause: the two
  // producers share one notice type but mean different things (a center crop vs a
  // single-speaker tracker), so a summary that names an outcome would be false for
  // one of them. The per-clip line shows the sidecar's own message instead.
  it('summarises how many clips degraded', () => {
    expect(
      describeDegraded([
        { path: '/a.mp4' },
        { path: '/b.mp4', reframeDegraded: { type: 't', message: 'm' } },
      ]),
    ).toBe('Reframe degraded on 1 of 2 clip(s) — see the note on each file below.');
  });

  it('returns null when nothing degraded (no scary banner on a clean export)', () => {
    expect(describeDegraded([{ path: '/a.mp4' }])).toBeNull();
  });

  it('does not name an outcome the notice may not support', () => {
    const summary = describeDegraded([{ reframeDegraded: { type: 't', message: 'm' } }]);
    expect(summary).not.toContain('center crop');
    expect(summary).not.toContain('centre crop');
  });
});
