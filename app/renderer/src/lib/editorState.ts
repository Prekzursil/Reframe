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
// `cropPlan`, an Edit phase reads `cues`/`playhead`, etc. `cropPlan` is therefore
// carried here as an opaque cross-phase value the Caption phase never mutates, so
// the shared context is already reusable by that phase without a second store.
//
// Everything here is IMMUTABLE — every action returns a NEW state object.

import type { Cue } from './rpc';
import { type CaptionDesign, DEFAULT_CAPTION_DESIGN } from './captionDesign';
import type { CaptionOverride } from './captionOverride';
import type { CaptionBox } from './captionPosition';

/** A source-absolute preview window (structurally a Player `PlayerWindow`). */
export interface EditorWindow {
  start: number;
  end: number;
}

/**
 * Opaque cross-phase crop plan. Owned/edited by the REFRAME phase; the Caption
 * pilot only carries it (never mutates it) so the shared editor state is already
 * reusable by that phase without introducing a second store. Kept intentionally
 * loose — the Reframe phase will refine the shape when it adopts this container.
 */
export interface CropPlan {
  readonly engine?: string;
  readonly keyframes?: readonly unknown[];
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

/**
 * Build the initial editor state from a seed. The playhead starts at the window
 * in-point; nothing is selected; the caption design defaults to the shipped
 * default when none is supplied.
 */
export function initialEditorState(seed: EditorSeed): EditorState {
  return {
    video: seed.video,
    cues: seed.cues ?? [],
    cropPlan: seed.cropPlan ?? null,
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
      return { ...state, cropPlan: action.cropPlan };
    default:
      return state;
  }
}
