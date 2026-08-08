// transitions.ts — the PURE renderer-side transition catalogue, guards and op builder.
//
// The sidecar owns the render (`media_studio/features/transitions.py`: xfade for
// video, acrossfade for audio, one boundary per extra clip). This module owns what
// the USER picks, and the two things the picker is obliged to show them BEFORE they
// commit to a render:
//
//   1. the real output duration — a transition OVERLAPS, so the timeline gets
//      SHORTER than the sum of the clips (`transitionOutputMs`), unlike a join;
//   2. that the render always re-encodes (`transitionReencodeNote`) — xfade has to
//      decode and recomposite both sides of every boundary, so it can never be a
//      stream copy.
//
// It also mirrors the engine's hard precondition (`transitionBlocker`): every clip
// must OUTLAST the transition it hosts. Enforcing it here means the user is stopped
// in the picker with a named clip instead of after a failed render.
//
// PURITY: no React, no rpc, no DOM — every export is a pure function, so the picker
// component stays a thin render shell and this logic is covered in isolation.

import type { DirectorOp } from './rpc';

/** A transition style id — mirrors the sidecar `transitions.TRANSITION_STYLES` keys. */
export type TransitionStyleId =
  | 'circleClose'
  | 'circleOpen'
  | 'dissolve'
  | 'fadeBlack'
  | 'fadeWhite'
  | 'slideLeft'
  | 'slideRight'
  | 'wipeDown'
  | 'wipeLeft'
  | 'wipeRight'
  | 'wipeUp';

/** One pickable transition: the wire id plus how it is described to the user. */
export interface TransitionStyle {
  id: TransitionStyleId;
  /** The human name shown on the control (never the raw wire id). */
  label: string;
  /** One plain-language line describing what the viewer will see. */
  blurb: string;
}

/**
 * The pickable transitions, in the SAME sorted order as the sidecar's
 * `STYLE_IDS = tuple(sorted(TRANSITION_STYLES))`. Order and membership are pinned
 * by this module's unit test and cross-checked against the Python side by the
 * sidecar's `test_transition_ts_parity`, because a drift between the two lists
 * would be invisible at runtime until a render failed with "unknown style".
 */
export const TRANSITION_STYLES: readonly TransitionStyle[] = [
  { id: 'circleClose', label: 'Circle close', blurb: 'The next clip closes in from a shrinking circle.' },
  { id: 'circleOpen', label: 'Circle open', blurb: 'The next clip opens out from a growing circle.' },
  { id: 'dissolve', label: 'Cross dissolve', blurb: 'The two clips blend through each other. The safe default.' },
  { id: 'fadeBlack', label: 'Fade through black', blurb: 'Dips to black between the clips — reads as a scene break.' },
  { id: 'fadeWhite', label: 'Fade through white', blurb: 'Dips to white between the clips — brighter, more upbeat.' },
  { id: 'slideLeft', label: 'Slide left', blurb: 'The next clip pushes the current one off to the left.' },
  { id: 'slideRight', label: 'Slide right', blurb: 'The next clip pushes the current one off to the right.' },
  { id: 'wipeDown', label: 'Wipe down', blurb: 'The next clip sweeps in from the top edge.' },
  { id: 'wipeLeft', label: 'Wipe left', blurb: 'The next clip sweeps in from the right edge.' },
  { id: 'wipeRight', label: 'Wipe right', blurb: 'The next clip sweeps in from the left edge.' },
  { id: 'wipeUp', label: 'Wipe up', blurb: 'The next clip sweeps in from the bottom edge.' },
];

/** The least opinionated boundary treatment — matches the sidecar `DEFAULT_STYLE`. */
export const DEFAULT_TRANSITION_STYLE: TransitionStyleId = 'dissolve';

/** Default transition length in ms — matches the sidecar `DEFAULT_DURATION_MS`. */
export const DEFAULT_TRANSITION_MS = 500;
/** Floor in ms — below this a dissolve is indistinguishable from a hard cut. */
export const MIN_TRANSITION_MS = 100;
/** Ceiling in ms — past this the transition dominates the clips it joins. */
export const MAX_TRANSITION_MS = 5000;

/** The label for a style id, falling back to the raw id for an unknown one. */
export function transitionStyleLabel(id: TransitionStyleId): string {
  return TRANSITION_STYLES.find((style) => style.id === id)?.label ?? id;
}

/**
 * Coerce a requested length to whole milliseconds inside the sidecar's accepted
 * range. A non-finite value (an empty/garbled number input) falls back to the
 * default rather than propagating NaN into the op params.
 */
export function clampTransitionMs(ms: number): number {
  if (!Number.isFinite(ms)) return DEFAULT_TRANSITION_MS;
  return Math.max(MIN_TRANSITION_MS, Math.min(MAX_TRANSITION_MS, Math.trunc(ms)));
}

/**
 * The real output length: the sum of the clips MINUS one overlap per boundary.
 *
 * This is the number the picker shows, and it is the whole point of the control —
 * a join makes the timeline longer by the length of what you added, a transition
 * makes it shorter than that by the overlap. Mirrors the sidecar's
 * `transitions.total_duration_sec`.
 */
export function transitionOutputMs(clipDurationsMs: readonly number[], transitionMs: number): number {
  const total = clipDurationsMs.reduce((sum, ms) => sum + ms, 0);
  return total - Math.max(0, clipDurationsMs.length - 1) * transitionMs;
}

/**
 * Why this selection cannot be transitioned, or `null` when it can.
 *
 * Mirrors the engine's precondition (`transitions.xfade_offsets`): at least two
 * clips, and every clip strictly LONGER than the transition it must host — a clip
 * that is not would be wholly consumed by the overlap, which ffmpeg renders as
 * garbage rather than refusing. Checked here so the user is stopped in the picker,
 * with the offending clip named, rather than after a wasted render.
 */
export function transitionBlocker(
  clipDurationsMs: readonly number[],
  transitionMs: number,
): string | null {
  if (clipDurationsMs.length < 2) {
    return 'A transition needs at least two clips — there is no boundary to treat.';
  }
  const seconds = (ms: number) => (ms / 1000).toFixed(1);
  for (const [index, ms] of clipDurationsMs.entries()) {
    if (ms <= transitionMs) {
      return `Clip ${index + 1} (${seconds(ms)}s) is shorter than the ${seconds(transitionMs)}s transition it would host.`;
    }
  }
  return null;
}

/**
 * The render-cost disclosure shown beside the picker, or `''` when there is no
 * boundary yet (nothing to disclose). Kept as data, not a static string, so the
 * boundary count is always the real one.
 */
export function transitionReencodeNote(clipCount: number): string {
  if (clipCount < 2) return '';
  const boundaries = clipCount - 1;
  const word = boundaries === 1 ? 'boundary' : 'boundaries';
  return `Transitions re-encode: the video is recomposited at ${boundaries} transition ${word}, so this export takes longer than a plain join and cannot be a lossless copy.`;
}

/** The inputs a user's picker selection turns into a wire op. */
export interface TransitionOpInput {
  /** The op id (caller-owned so the plan's ids stay unique and deterministic). */
  id: string;
  /** Paths of the clips joined AFTER the current source, in order. */
  clips: readonly string[];
  style?: TransitionStyleId;
  durationMs?: number;
}

/**
 * Build a wire-valid `transition` op from a picker selection.
 *
 * `span` is null on purpose: a transition acts on the JUNCTION between clips, not
 * on a source range, and the sidecar validator deliberately keeps `transition` out
 * of its span-required set for exactly that reason.
 *
 * The `rationale` is derived LOCALLY and deterministically from the selection —
 * it is not model text, so the storyboard row reads as what the user chose.
 */
export function buildTransitionOp(input: TransitionOpInput): DirectorOp {
  const style = input.style ?? DEFAULT_TRANSITION_STYLE;
  const durationMs = clampTransitionMs(input.durationMs ?? DEFAULT_TRANSITION_MS);
  return {
    id: input.id,
    kind: 'transition',
    span: null,
    params: { clips: [...input.clips], style, durationMs },
    reversible: true,
    rationale: `${transitionStyleLabel(style)} · ${(durationMs / 1000).toFixed(1)}s`,
    status: 'planned',
    statusReason: null,
  };
}
