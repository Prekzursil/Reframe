// timelineOps.ts — PURE cue operations for the timeline subtitle editor (P2 T1).
//
// Everything here is side-effect-free and fully unit-tested (timelineOps.test.ts):
// split / merge / retime / dragEdge with neighbor clamping, plus a thin linear
// undo/redo history bounded at 100 entries (PLAN-P2 T1: "Undo = single linear
// stack — keep thin").
//
// Cue shape is the FROZEN §3 schema `{index, start, end, text}`. Cue `index` is
// 1-based (SRT convention — the sidecar's subtitles.reindex renumbers 1..N), so
// list-level ops renumber with `renumber()` after any structural change. All
// list-level ops take the cue's array POSITION (0-based), not its `index`
// field, and return a NEW array (no mutation); an invalid position returns the
// input array unchanged so callers can `===`-check whether anything happened.

import type { Cue } from '../features/_api';

export type { Cue };

/** Minimum cue duration (seconds) every op preserves. */
export const MIN_CUE_SEC = 0.05;

/** Maximum number of undo steps retained (linear, bounded). */
export const MAX_HISTORY = 100;

/** Edge of a cue being dragged. */
export type CueEdge = 'start' | 'end';

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

/** Clamp `value` into [lo, hi] (callers guarantee lo <= hi). */
function clamp(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), hi);
}

/** Renumber cues 1..N (1-based, SRT convention) as fresh objects. */
export function renumber(cues: readonly Cue[]): Cue[] {
  return cues.map((cue, i) => ({ ...cue, index: i + 1 }));
}

/** True when `pos` addresses a cue in `cues`. */
function validPos(cues: readonly Cue[], pos: number): boolean {
  return Number.isInteger(pos) && pos >= 0 && pos < cues.length;
}

// ---------------------------------------------------------------------------
// cue-level ops (the spec'd split(cue,t) / merge(a,b) / retime primitives)
// ---------------------------------------------------------------------------

/**
 * Split `cue` at time `t` into two cues. `t` is clamped into the splittable
 * interior `[start+MIN, end-MIN]`; a cue shorter than `2*MIN` cannot be split
 * (returns null). Text is divided at the word boundary proportional to the
 * split point, so both halves keep readable text.
 */
export function splitCue(cue: Cue, t: number): [Cue, Cue] | null {
  const span = cue.end - cue.start;
  if (span < 2 * MIN_CUE_SEC) return null;
  const at = clamp(t, cue.start + MIN_CUE_SEC, cue.end - MIN_CUE_SEC);
  const words = cue.text.split(/\s+/).filter(Boolean);
  const frac = (at - cue.start) / span;
  const k = clamp(Math.round(words.length * frac), 0, words.length);
  const first: Cue = { ...cue, end: at, text: words.slice(0, k).join(' ') };
  const second: Cue = { ...cue, start: at, text: words.slice(k).join(' ') };
  return [first, second];
}

/**
 * Merge two cues into one spanning both: `[min(start), max(end)]`, texts
 * joined in time order with a single space (empty halves dropped). Keeps the
 * earlier cue's `index` (list-level callers renumber anyway).
 */
export function mergeCues(a: Cue, b: Cue): Cue {
  const [first, second] = a.start <= b.start ? [a, b] : [b, a];
  const text = [first.text.trim(), second.text.trim()].filter(Boolean).join(' ');
  return {
    index: first.index,
    start: Math.min(a.start, b.start),
    end: Math.max(a.end, b.end),
    text,
  };
}

/**
 * Retime a single cue to `[start, end]` with basic sanity clamping: start is
 * non-negative, and the duration stays >= MIN_CUE_SEC (end is pushed out when
 * the requested window is too small). Neighbor clamping is the LIST-level
 * `retimeAt` / `dragEdge`'s job — this primitive has no neighbors to see.
 */
export function retimeCue(cue: Cue, start: number, end: number): Cue {
  const s = Math.max(0, start);
  const e = Math.max(s + MIN_CUE_SEC, end);
  return { ...cue, start: s, end: e };
}

// ---------------------------------------------------------------------------
// list-level ops (position-based; renumbered; neighbor-aware)
// ---------------------------------------------------------------------------

/** Split the cue at array position `pos` at time `t`. Renumbers. */
export function splitAt(cues: readonly Cue[], pos: number, t: number): Cue[] {
  if (!validPos(cues, pos)) return cues as Cue[];
  const halves = splitCue(cues[pos], t);
  if (halves === null) return cues as Cue[];
  return renumber([...cues.slice(0, pos), ...halves, ...cues.slice(pos + 1)]);
}

/** Merge the cue at `pos` with its NEXT neighbor. Renumbers. */
export function mergeAt(cues: readonly Cue[], pos: number): Cue[] {
  if (!validPos(cues, pos) || pos + 1 >= cues.length) return cues as Cue[];
  const merged = mergeCues(cues[pos], cues[pos + 1]);
  return renumber([...cues.slice(0, pos), merged, ...cues.slice(pos + 2)]);
}

/**
 * The open interval a cue at `pos` may occupy without crossing its neighbors:
 * `[prev.end, next.start]` (0 / +Infinity at the list ends).
 */
function neighborBounds(cues: readonly Cue[], pos: number): { lo: number; hi: number } {
  const lo = pos > 0 ? cues[pos - 1].end : 0;
  const hi = pos + 1 < cues.length ? cues[pos + 1].start : Number.POSITIVE_INFINITY;
  return { lo, hi };
}

/**
 * Retime the cue at `pos` to `[start, end]`, clamped into the neighbor gap
 * `[prev.end, next.start]` and keeping duration >= MIN_CUE_SEC. If the
 * neighbor gap itself is too small to hold a minimum-length cue, the list is
 * returned unchanged (nothing legal to do).
 */
export function retimeAt(cues: readonly Cue[], pos: number, start: number, end: number): Cue[] {
  if (!validPos(cues, pos)) return cues as Cue[];
  const { lo, hi } = neighborBounds(cues, pos);
  if (hi - lo < MIN_CUE_SEC) return cues as Cue[];
  let s = clamp(start, lo, hi - MIN_CUE_SEC);
  let e = clamp(end, s + MIN_CUE_SEC, hi);
  if (e - s < MIN_CUE_SEC) {
    // end hit the ceiling — pull start back to preserve the minimum span.
    s = e - MIN_CUE_SEC;
  }
  const next = cues.map((cue, i) => (i === pos ? { ...cue, start: s, end: e } : cue));
  return next;
}

/**
 * Drag one edge of the cue at `pos` to time `t`, clamping so the cue (a) never
 * crosses its neighbor on that side and (b) keeps >= MIN_CUE_SEC against its
 * own other edge. Returns a new list (untouched cues keep their identity).
 */
export function dragEdge(cues: readonly Cue[], pos: number, edge: CueEdge, t: number): Cue[] {
  if (!validPos(cues, pos)) return cues as Cue[];
  const cue = cues[pos];
  const { lo, hi } = neighborBounds(cues, pos);
  let updated: Cue;
  if (edge === 'start') {
    const s = clamp(t, lo, cue.end - MIN_CUE_SEC);
    updated = { ...cue, start: s };
  } else {
    const e = clamp(t, cue.start + MIN_CUE_SEC, hi);
    updated = { ...cue, end: e };
  }
  return cues.map((c, i) => (i === pos ? updated : c));
}

// ---------------------------------------------------------------------------
// undo/redo — single linear stack, bounded at MAX_HISTORY (PLAN-P2 T1)
// ---------------------------------------------------------------------------

export interface History {
  /** Older states, oldest first. Bounded at MAX_HISTORY entries. */
  past: Cue[][];
  /** The current cue list. */
  present: Cue[];
  /** Undone states, nearest first popped last (LIFO via array end). */
  future: Cue[][];
}

/** A fresh history at `initial`. */
export function createHistory(initial: Cue[]): History {
  return { past: [], present: initial, future: [] };
}

/**
 * Commit `next` as the new present. The old present is pushed onto the past
 * (dropping the OLDEST entry past MAX_HISTORY) and the redo branch is cleared
 * (linear history). A `next` that is the same reference as the present is a
 * no-op so callers can feed clamped ops straight in.
 */
export function pushHistory(h: History, next: Cue[]): History {
  if (next === h.present) return h;
  const past = [...h.past, h.present];
  while (past.length > MAX_HISTORY) past.shift();
  return { past, present: next, future: [] };
}

export function canUndo(h: History): boolean {
  return h.past.length > 0;
}

export function canRedo(h: History): boolean {
  return h.future.length > 0;
}

/** Step back one state (no-op at the floor). */
export function undo(h: History): History {
  if (!canUndo(h)) return h;
  const past = h.past.slice(0, -1);
  const present = h.past[h.past.length - 1];
  return { past, present, future: [...h.future, h.present] };
}

/** Step forward one undone state (no-op when nothing was undone). */
export function redo(h: History): History {
  if (!canRedo(h)) return h;
  const future = h.future.slice(0, -1);
  const present = h.future[h.future.length - 1];
  return { past: [...h.past, h.present], present, future };
}

// ---------------------------------------------------------------------------
// view helpers (pure; used by Timeline.tsx and tested here)
// ---------------------------------------------------------------------------

/** Map a clientX inside a lane rect to a media time in [0, duration]. */
export function timeFromClientX(
  clientX: number,
  rectLeft: number,
  rectWidth: number,
  duration: number,
): number {
  if (rectWidth <= 0 || duration <= 0) return 0;
  return clamp(((clientX - rectLeft) / rectWidth) * duration, 0, duration);
}

/** A cue's left/width as percentages of the lane for absolute positioning. */
export function cueRectStyle(cue: Cue, duration: number): { leftPct: number; widthPct: number } {
  if (duration <= 0) return { leftPct: 0, widthPct: 0 };
  const leftPct = clamp((cue.start / duration) * 100, 0, 100);
  const rightPct = clamp((cue.end / duration) * 100, 0, 100);
  return { leftPct, widthPct: Math.max(rightPct - leftPct, 0) };
}
