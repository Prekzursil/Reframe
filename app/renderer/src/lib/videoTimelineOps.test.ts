// videoTimelineOps.test.ts — PURE video-lane ops for the direct-manipulation
// editor (the client mirror of sidecar/media_studio/features/video_tracks.py).
//
// The load-bearing contract is that a drag PREVIEW is always something the
// STRICT sidecar will accept: the preview clamps, the sidecar refuses, so a
// clamped preview that the sidecar would reject means the UI shows the user an
// edit that then silently fails to commit. Every test below is about that.

import { describe, expect, it } from 'vitest';

import {
  MAX_HISTORY,
  MIN_CLIP_FRAMES,
  applyClips,
  clipDuration,
  clipRectStyle,
  clipTimelineEnd,
  createHistory,
  findClip,
  frameSourceSpan,
  frameSpan,
  laneRows,
  movePreview,
  neighborGap,
  overlapIn,
  pushHistory,
  redo,
  secondsToFrames,
  snapToFrame,
  splitPreview,
  timelineDuration,
  trimPreview,
  undo,
  type Fps,
  type VideoClip,
  type VideoLane,
} from './videoTimelineOps';

const FPS_CHOICES: readonly Fps[] = [24, 25, 30, 60];

function clip(over: Partial<VideoClip> = {}): VideoClip {
  return { id: 'c1', path: 'a.mp4', srcIn: 1, srcOut: 3, timelineStart: 0, ...over };
}

function lane(clips: VideoClip[], over: Partial<VideoLane> = {}): VideoLane {
  return { id: 'vt1', name: 'Video 1', index: 0, clips, ...over };
}

describe('the frame grid mirrors the sidecar quantizer', () => {
  it('rounds to whole frames and clamps negatives', () => {
    expect(secondsToFrames(1.017, 30)).toBe(31);
    expect(secondsToFrames(-5, 30)).toBe(0);
    expect(snapToFrame(1.017, 30)).toBeCloseTo(31 / 30, 10);
  });

  it('derives duration from the source window, never a stored field', () => {
    const c = clip({ srcIn: 1, srcOut: 3, timelineStart: 5 });
    expect(clipDuration(c)).toBeCloseTo(2, 10);
    expect(clipTimelineEnd(c)).toBeCloseTo(7, 10);
  });
});

describe('a drag preview is always committable', () => {
  it.each(FPS_CHOICES)('trim keeps the timing invariant at %ifps', (fps) => {
    const l = lane([clip({ id: 'c1', srcIn: 1, srcOut: 3, timelineStart: 4 })]);
    const head = trimPreview(l, 'c1', 'start', 4.4, fps);
    const tail = trimPreview(l, 'c1', 'end', 5.6, fps);
    for (const next of [head, tail]) {
      expect(next).not.toBeNull();
      expect(frameSpan(next!, fps)).toBe(frameSourceSpan(next!, fps));
      expect(frameSpan(next!, fps)).toBeGreaterThanOrEqual(MIN_CLIP_FRAMES);
    }
    // a head trim PINS the tail; a tail trim PINS the head
    expect(clipTimelineEnd(head!)).toBeCloseTo(6, 10);
    expect(tail!.timelineStart).toBeCloseTo(4, 10);
  });

  it('clamps a trim past the source head instead of proposing frame -1', () => {
    const l = lane([clip({ id: 'c1', srcIn: 0.5, srcOut: 3, timelineStart: 5 })]);
    const next = trimPreview(l, 'c1', 'start', 0, 30);
    // the handle stops where the media does: srcIn can only reach 0
    expect(next!.srcIn).toBe(0);
    expect(next!.timelineStart).toBeCloseTo(4.5, 10);
    expect(frameSpan(next!, 30)).toBe(frameSourceSpan(next!, 30));
  });

  it('clamps a trim to one frame instead of collapsing the clip', () => {
    const l = lane([clip({ id: 'c1', srcIn: 1, srcOut: 3, timelineStart: 0 })]);
    const next = trimPreview(l, 'c1', 'end', -99, 30);
    expect(frameSpan(next!, 30)).toBe(MIN_CLIP_FRAMES);
  });

  // Two limits bind a head trim and they are NOT the same one. An earlier
  // version of this test asserted the neighbour limit on a clip whose srcIn was
  // already 0 and was REFUTED by the implementation: with no media handle to the
  // left the head cannot move at all, whatever the neighbour allows. Both
  // directions are now pinned so neither limit can regress into the other.
  it('a head trim stops at the SOURCE head when there is no handle left', () => {
    const l = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 2, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 2, timelineStart: 5 }),
    ]);
    const next = trimPreview(l, 'c2', 'start', 0, 30);
    // srcIn is already frame 0 — there is nothing to trim in to, so nothing moves
    expect(next!.srcIn).toBe(0);
    expect(next!.timelineStart).toBeCloseTo(5, 10);
    expect(frameSpan(next!, 30)).toBe(frameSourceSpan(next!, 30));
  });

  it('a head trim stops at the NEIGHBOUR when the handle is long enough', () => {
    const l = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 2, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 10, srcOut: 12, timelineStart: 5 }),
    ]);
    const next = trimPreview(l, 'c2', 'start', 0, 30);
    expect(next!.timelineStart).toBeCloseTo(2, 10); // == c1's end, abutting is legal
    expect(next!.srcIn).toBeCloseTo(7, 10); // the source window followed by 3s
    expect(frameSpan(next!, 30)).toBe(frameSourceSpan(next!, 30));
    expect(overlapIn({ ...l, clips: [l.clips[0], next!] }, 30)).toBeNull();
  });

  it('a boxed-in clip stays put instead of pushing through its neighbour', () => {
    const l = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 2, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 2, timelineStart: 2 }),
    ]);
    // c1 abuts c2, so a tail trim outward and a slide right both have zero room
    expect(trimPreview(l, 'c1', 'end', 99, 30)!.srcOut).toBeCloseTo(2, 10);
    expect(movePreview(l, 'c1', 5, 30)!.timelineStart).toBe(0);
  });

  // A lane can hold an overlap that this module did NOT create — a hand-edited or
  // older manifest. Then there is no legal edit at all, and proposing one anyway
  // would show the user a change the sidecar refuses. Every preview must return
  // null rather than clamp into an illegal value.
  it('proposes nothing on a lane that already overlaps', () => {
    const straddled = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 5, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 2, timelineStart: 1 }),
    ]);
    expect(overlapIn(straddled, 30)).toEqual(['c1', 'c2']);
    expect(trimPreview(straddled, 'c2', 'start', 0, 30)).toBeNull();

    const coincident = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 2, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 2, timelineStart: 0 }),
    ]);
    expect(trimPreview(coincident, 'c1', 'end', 99, 30)).toBeNull();
    expect(movePreview(coincident, 'c1', 99, 30)).toBeNull();
  });

  it('matches the sidecar on a half-frame tie (bankers rounding, not half-up)', () => {
    // 1/12 s at 30fps is exactly 2.5 frames. Python round(2.5) === 2, while
    // Math.round(2.5) === 3 — a one-frame divergence between what the user drags
    // and what the sidecar stores. The mirror must follow Python.
    expect(secondsToFrames(2.5 / 30, 30)).toBe(2);
    expect(secondsToFrames(3.5 / 30, 30)).toBe(4);
  });

  it('moves duration-preserving and clamps into the neighbour gap', () => {
    const l = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 2, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 2, timelineStart: 4 }),
      clip({ id: 'c3', srcIn: 0, srcOut: 2, timelineStart: 8 }),
    ]);
    const next = movePreview(l, 'c2', 99, 30);
    expect(clipDuration(next!)).toBeCloseTo(2, 10); // never trades duration for travel
    expect(clipTimelineEnd(next!)).toBeCloseTo(8, 10); // stops at c3's head
    const back = movePreview(l, 'c2', -99, 30);
    expect(back!.timelineStart).toBeCloseTo(2, 10); // stops at c1's tail
  });

  it('reports the free interval around a clip', () => {
    const l = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 2, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 2, timelineStart: 4 }),
    ]);
    expect(neighborGap(l, 'c2', 30)).toEqual({ lo: 2, hi: Number.POSITIVE_INFINITY });
    expect(neighborGap(l, 'c1', 30)).toEqual({ lo: 0, hi: 4 });
  });

  it('splits losslessly and refuses a cut outside the clip', () => {
    const c = clip({ srcIn: 1, srcOut: 3, timelineStart: 4 });
    const halves = splitPreview(c, 5, 30);
    expect(halves).not.toBeNull();
    const [left, right] = halves!;
    expect(frameSpan(left, 30) + frameSpan(right, 30)).toBe(frameSpan(c, 30));
    expect(clipTimelineEnd(left)).toBeCloseTo(right.timelineStart, 10);
    expect(left.srcOut).toBeCloseTo(right.srcIn, 10);
    expect(left.id).toBe(c.id);
    expect(right.id).not.toBe(c.id);
    expect(splitPreview(c, 99, 30)).toBeNull();
    expect(splitPreview(c, 4, 30)).toBeNull(); // exactly on the head: no left half
  });

  it('returns null for an unknown clip rather than guessing', () => {
    const l = lane([clip()]);
    expect(trimPreview(l, 'ghost', 'end', 1, 30)).toBeNull();
    expect(movePreview(l, 'ghost', 1, 30)).toBeNull();
    expect(neighborGap(l, 'ghost', 30)).toBeNull();
  });
});

describe('lane bookkeeping is immutable', () => {
  it('finds a clip across lanes', () => {
    const lanes = [lane([clip({ id: 'c1' })]), lane([clip({ id: 'c2' })], { id: 'vt2', index: 1 })];
    expect(findClip(lanes, 'c2')?.lane.id).toBe('vt2');
    expect(findClip(lanes, 'ghost')).toBeNull();
  });

  it('replaces a clip in place without mutating the input', () => {
    const lanes = [lane([clip({ id: 'c1' }), clip({ id: 'c2', timelineStart: 5 })])];
    const next = applyClips(lanes, 'c1', [clip({ id: 'c1', timelineStart: 1 })]);
    expect(next).not.toBe(lanes);
    expect(lanes[0].clips[0].timelineStart).toBe(0); // input untouched
    expect(next[0].clips.map((c) => c.id)).toEqual(['c1', 'c2']); // order preserved
    expect(next[0].clips[0].timelineStart).toBe(1);
  });

  it('removes a clip when the replacement list is empty', () => {
    const lanes = [lane([clip({ id: 'c1' }), clip({ id: 'c2', timelineStart: 5 })])];
    expect(applyClips(lanes, 'c1', [])[0].clips.map((c) => c.id)).toEqual(['c2']);
  });

  it('leaves the lanes alone for an unknown clip', () => {
    const lanes = [lane([clip()])];
    expect(applyClips(lanes, 'ghost', [])).toBe(lanes);
  });

  it('touches only the owning lane when several lanes are stacked', () => {
    const lanes = [
      lane([clip({ id: 'c1' })], { id: 'vt1', index: 0 }),
      lane([clip({ id: 'c2', timelineStart: 9 })], { id: 'vt2', index: 1 }),
    ];
    const next = applyClips(lanes, 'c2', [clip({ id: 'c2', timelineStart: 3 })]);
    expect(next[0]).toBe(lanes[0]); // the other lane keeps its identity (no re-render)
    expect(next[1]).not.toBe(lanes[1]);
    expect(next[1].clips[0].timelineStart).toBe(3);
  });

  it('names the overlapping pair, and treats abutting as legal', () => {
    const bad = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 5, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 5, timelineStart: 1 }),
    ]);
    expect(overlapIn(bad, 30)).toEqual(['c1', 'c2']);
    const ok = lane([
      clip({ id: 'c1', srcIn: 0, srcOut: 5, timelineStart: 0 }),
      clip({ id: 'c2', srcIn: 0, srcOut: 5, timelineStart: 5 }),
    ]);
    expect(overlapIn(ok, 30)).toBeNull();
  });

  it('orders lanes by index and totals the timeline', () => {
    const lanes = [
      lane([clip({ id: 'c1', srcIn: 0, srcOut: 2, timelineStart: 0 })], { id: 'b', index: 1 }),
      lane([clip({ id: 'c2', srcIn: 0, srcOut: 2, timelineStart: 4 })], { id: 'a', index: 0 }),
    ];
    expect(laneRows(lanes).map((l) => l.id)).toEqual(['a', 'b']);
    // the timeline's LENGTH is the furthest clip tail, gaps included
    expect(timelineDuration(lanes)).toBeCloseTo(6, 10);
    expect(timelineDuration([])).toBe(0);
  });
});

describe('view helpers', () => {
  it('positions a clip as percentages of the lane', () => {
    expect(clipRectStyle(clip({ srcIn: 0, srcOut: 5, timelineStart: 5 }), 20)).toEqual({
      leftPct: 25,
      widthPct: 25,
    });
    expect(clipRectStyle(clip(), 0)).toEqual({ leftPct: 0, widthPct: 0 });
  });
});

describe('undo/redo over the whole lane set', () => {
  it('steps back and forward, and no-ops at the ends', () => {
    const a = [lane([clip({ id: 'c1' })])];
    const b = [lane([clip({ id: 'c1', timelineStart: 3 })])];
    let h = createHistory(a);
    expect(undo(h)).toBe(h);
    expect(redo(h)).toBe(h);
    h = pushHistory(h, b);
    expect(h.present).toBe(b);
    h = undo(h);
    expect(h.present).toBe(a);
    h = redo(h);
    expect(h.present).toBe(b);
    // pushing the SAME reference is a no-op (a clamped op that changed nothing)
    expect(pushHistory(h, b)).toBe(h);
  });

  it('drops the oldest entry past the cap so a long session cannot grow forever', () => {
    const OVER = 5;
    let h = createHistory([lane([clip({ id: 'c0' })])]);
    for (let i = 1; i <= MAX_HISTORY + OVER; i += 1) {
      h = pushHistory(h, [lane([clip({ id: `c${i}` })])]);
    }
    expect(h.past.length).toBe(MAX_HISTORY);
    // The survivors are the MOST RECENT ones. `past` holds every previous present
    // (c0 .. c{N-1}) trimmed to the last MAX_HISTORY, so the floor is c{OVER}.
    // Derived, not hardcoded, so the expectation cannot drift from the cap.
    expect(h.past[0][0].clips[0].id).toBe(`c${OVER}`);
    expect(h.present[0].clips[0].id).toBe(`c${MAX_HISTORY + OVER}`);
  });
});
