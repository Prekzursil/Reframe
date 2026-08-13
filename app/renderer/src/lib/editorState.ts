// editorState.ts — the shared EDITOR STATE primitive (v1.5 Caption pilot).
//
// The redesign's load-bearing pattern is "inspector-over-shared-stage": a single
// editor state (the video + its cues + the crop plan + the caption design + the
// playhead + the current selection) that a Stage, a Timeline, and an Inspector
// all read and write, so those panels become THIN CONSUMERS instead of layout
// owners. This module is that state's PURE core — the reducer, its actions, and a
// couple of selectors — with NO React and NO DOM, so it is exhaustively unit
// testable. The React binding (Provider + `useEditor`) lives in
// `features/EditorContext.tsx`; the caption panels consume it.
//
// Reusability note: the Caption phase is the pilot, so `design` is a
// `CaptionDesign` today. The OTHER four redesigned phases reuse THIS same state
// container (that is the whole point of extracting it) — a Reframe phase edits
// `cropPlan`, an Edit phase reads `cues`/`playhead`, etc. The Caption phase still
// never mutates `cropPlan`; it only carries it, so the shared context is reusable
// by the Reframe phase without a second store.
//
// `cropPlan` USED to be fully opaque ("the Reframe phase will refine the shape
// when it adopts this container"). It now carries a real, previewable rect —
// `CropFraming` — reusing the `Crop = [x, y, w, h]` source-pixel type the per-shot
// override layer and the sidecar `reframe_override` contract already agree on
// (`reframeOverride.ts`), so there is ONE crop model rather than two. Only the
// per-engine `keyframes` stay loose; the rect does not, because the rect is the
// one field a crop preview must be able to read.
//
// Everything here is IMMUTABLE — every action returns a NEW state object.

import type { Cue } from './rpc';
import { type CaptionDesign, DEFAULT_CAPTION_DESIGN } from './captionDesign';
import type { CaptionOverride } from './captionOverride';
import type { CaptionBox } from './captionPosition';
import { type Crop, clampCrop } from './reframeOverride';

/** A source-absolute preview window (structurally a Player `PlayerWindow`). */
export interface EditorWindow {
  start: number;
  end: number;
}

/**
 * A crop rect PLUS the source frame it is measured against. Both halves are
 * required to be previewable at all: `[x, y, w, h]` in source pixels says
 * nothing about where it lands on screen until you know the frame it is a
 * fraction of. `Crop` is the SAME type the per-shot override layer and the
 * sidecar `reframe_override` contract already use, so a plan built here is
 * byte-compatible with the shot decisions the Reframe engine emits.
 */
export interface CropFraming {
  /** `[x, y, w, h]` in SOURCE pixels (matches the R0 ReframeTrace crop). */
  readonly crop: Crop;
  /** Source frame width the rect is expressed against (positive, finite). */
  readonly sourceWidth: number;
  /** Source frame height the rect is expressed against (positive, finite). */
  readonly sourceHeight: number;
}

/**
 * The crop as 0..1 fractions of the source frame — the form a preview overlay
 * consumes, because it scales to whatever size a stage happens to render at.
 */
export interface CropViewport {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/**
 * Cross-phase crop plan. Owned/edited by the REFRAME phase; the Caption pilot
 * only carries it (never mutates it) so the shared editor state is already
 * reusable by that phase without introducing a second store.
 *
 * `framing` is the rect the plan resolves to — the field a crop preview reads.
 * `engine` and `keyframes` stay loose on purpose: the per-engine keyframe shape
 * is still the producer's business, and nothing in the app reads it yet.
 */
export interface CropPlan {
  readonly engine?: string;
  readonly keyframes?: readonly unknown[];
  readonly framing?: CropFraming;
}

/** The media the editor is working on. */
export interface EditorVideo {
  /** Library video id — played as `mstream://media/<id>`. */
  videoId?: string;
  /** Direct src override (wins over videoId). */
  src?: string;
  /** The source-absolute preview window the cues re-base against. */
  window: EditorWindow;
  /** The video duration (source seconds) when known. */
  durationSec?: number;
}

/** The whole shared editor state a Stage / Timeline / Inspector read + write. */
export interface EditorState {
  video: EditorVideo;
  /** Word-level caption cues (source-absolute seconds). */
  cues: Cue[];
  /** Cross-phase crop plan (Reframe-owned; carried, not edited, here). */
  cropPlan: CropPlan | null;
  /** The caption design (style + box + within-template override). */
  design: CaptionDesign;
  /** The playhead in source-absolute seconds. */
  playhead: number;
  /** The selected cue index, or null when nothing is selected. */
  selection: number | null;
}

/** The minimum seed needed to build an initial editor state. */
export interface EditorSeed {
  video: EditorVideo;
  cues?: Cue[];
  cropPlan?: CropPlan | null;
  design?: CaptionDesign;
}

/** True for a real, positive, finite measurement — a size safe to divide by. */
function isPositiveSize(n: number): boolean {
  return Number.isFinite(n) && n > 0;
}

/**
 * Build a previewable framing from a raw rect and its source frame, or null
 * when those numbers cannot describe one. Loud-vs-quiet is deliberate:
 * `clampCrop` THROWS on a degenerate rect because a renderer has nothing to
 * draw from it, but this is the STATE boundary, so it mirrors `clampSelection`
 * instead and resolves an unusable input to "no framing". A malformed or stale
 * plan can therefore never push NaN into a preview.
 */
export function cropFraming(
  crop: Crop,
  sourceWidth: number,
  sourceHeight: number,
): CropFraming | null {
  if (!isPositiveSize(sourceWidth) || !isPositiveSize(sourceHeight)) return null;
  const [x, y, w, h] = crop;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (!isPositiveSize(w) || !isPositiveSize(h)) return null;
  return { crop: clampCrop(crop, sourceWidth, sourceHeight), sourceWidth, sourceHeight };
}

/**
 * Normalise a plan on its way INTO state — the single funnel both doors (seed
 * and `setCropPlan`) run through, so an invariant holds for every consumer: a
 * stored `framing` is always previewable. An unusable rect is DROPPED while the
 * plan itself survives (the "is there a crop plan" consumers keep working); an
 * off-frame rect is pulled inside; an already-valid plan is returned BY
 * REFERENCE so merely carrying a plan stays allocation-free.
 */
function normalizeCropPlan(plan: CropPlan | null): CropPlan | null {
  if (plan === null) return null;
  const { framing } = plan;
  if (framing === undefined) return plan;
  const usable = cropFraming(framing.crop, framing.sourceWidth, framing.sourceHeight);
  if (usable === null) return { ...plan, framing: undefined };
  if (usable.crop.every((v, i) => v === framing.crop[i])) return plan;
  return { ...plan, framing: usable };
}

/**
 * Build the initial editor state from a seed. The playhead starts at the window
 * in-point; nothing is selected; the caption design defaults to the shipped
 * default when none is supplied.
 */
export function initialEditorState(seed: EditorSeed): EditorState {
  return {
    video: seed.video,
    cues: seed.cues ?? [],
    cropPlan: normalizeCropPlan(seed.cropPlan ?? null),
    design: seed.design ?? DEFAULT_CAPTION_DESIGN,
    playhead: seed.video.window.start,
    selection: null,
  };
}

/** Every mutation the shared editor state supports (discriminated union). */
export type EditorAction =
  | { type: 'setPlayhead'; playhead: number }
  | { type: 'setCues'; cues: Cue[] }
  | { type: 'setVideo'; video: EditorVideo }
  | { type: 'setDesign'; design: CaptionDesign }
  | { type: 'setStyle'; style: string }
  | { type: 'setOverride'; override: CaptionOverride | undefined }
  | { type: 'setBox'; box: CaptionBox }
  | { type: 'selectCue'; index: number | null }
  | { type: 'setCropPlan'; cropPlan: CropPlan | null };

/** True once at least one caption cue exists — the transcript-present gate. */
export function transcriptReady(state: EditorState): boolean {
  return state.cues.length > 0;
}

/**
 * The stored crop as 0..1 fractions of the source frame, or null when this
 * state holds no rect to show. This is the read a crop PREVIEW makes: multiply
 * by the rendered stage size to get the overlay box. Division is safe by
 * construction — every door into `cropPlan` runs `normalizeCropPlan`, so a
 * stored framing always carries a positive finite source frame.
 */
export function cropViewport(state: EditorState): CropViewport | null {
  const framing = state.cropPlan?.framing;
  if (framing === undefined) return null;
  const [x, y, w, h] = framing.crop;
  return {
    x: x / framing.sourceWidth,
    y: y / framing.sourceHeight,
    width: w / framing.sourceWidth,
    height: h / framing.sourceHeight,
  };
}

/**
 * Clamp a requested selection index to a valid cue index, else null. A null
 * request, a non-integer, or an out-of-range index all resolve to "no selection"
 * so a stale selection can never point past a shortened cue list.
 */
export function clampSelection(index: number | null, cueCount: number): number | null {
  if (index === null) return null;
  if (!Number.isInteger(index) || index < 0 || index >= cueCount) return null;
  return index;
}

/**
 * The pure editor reducer. Every case returns a NEW state object (immutable);
 * caption sub-actions rebuild only the `design` slice. Re-basing the selection
 * on `setCues` keeps it valid when the cue list shrinks. An unknown action is a
 * no-op (returns the same state).
 */
export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case 'setPlayhead':
      return { ...state, playhead: action.playhead };
    case 'setCues':
      return {
        ...state,
        cues: action.cues,
        selection: clampSelection(state.selection, action.cues.length),
      };
    case 'setVideo':
      return { ...state, video: action.video, playhead: action.video.window.start };
    case 'setDesign':
      return { ...state, design: action.design };
    case 'setStyle':
      return { ...state, design: { ...state.design, style: action.style } };
    case 'setOverride':
      return { ...state, design: { ...state.design, override: action.override } };
    case 'setBox':
      return { ...state, design: { ...state.design, box: action.box } };
    case 'selectCue':
      return { ...state, selection: clampSelection(action.index, state.cues.length) };
    case 'setCropPlan':
      return { ...state, cropPlan: normalizeCropPlan(action.cropPlan) };
    default:
      return state;
  }
}
