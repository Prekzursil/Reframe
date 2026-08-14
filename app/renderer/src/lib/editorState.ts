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
 *
 * NOT LIVE YET — read this before assuming a crop can reach a screen. BOTH doors
 * into `cropPlan` are dead in production: nothing dispatches `setCropPlan`, and
 * all three production `EditorSeed` literals pass only `video` — the `EditorSeed`
 * that each of `views/Caption.tsx`, `views/Director.tsx` and `views/Export.tsx`
 * builds for its provider.
 * `state.cropPlan` is therefore permanently `null` in the shipped app, so
 * `cropViewport` never returns a rect, `exportModel.framingSummary` can only
 * render "Original framing", and `directorHandoff`'s `hasCrop` can only be
 * false. That is PRE-EXISTING and is not something this container broke.
 *
 * Adopting it is NOT a one-line dispatch. `panels/ReframeOverridePanel` already
 * holds the exact `(crop, sourceWidth, sourceHeight)` triple `cropFraming`
 * consumes, but it does not call `useEditor`, its host `features/ReframeCorrect`
 * does not either, and neither sits under an `EditorProvider`: the provider is
 * mounted at exactly three sibling destinations (the `<EditorProvider>` in each
 * of `views/Caption.tsx`, `views/Director.tsx` and `views/Export.tsx`) while that
 * panel reaches the tree down a different spine — the `<Workspace>` element in
 * `views/Edit.tsx`, then the `reframeFix` arm of that view's panel switch, which
 * renders `<ReframeCorrect>` — and `useEditor` (`features/EditorContext.tsx`)
 * throws outside a provider.
 * Wrapping the Workspace in its own provider does not fix it either — the
 * provider is UNCONTROLLED and seeds once, and those destinations render
 * exclusively, so it would be a fourth instance that unmounts on a destination
 * switch and could never be read by Export or the Director handoff. Deciding who
 * OWNS the crop plan across destinations is the real prerequisite.
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
 * Normalise a plan on its way INTO state — the funnel both of this module's CODE
 * paths in (seed and `setCropPlan`) run through, so a stored `framing` is always
 * previewable. That is a correctness property of this module, NOT evidence that
 * either path is live — both are currently dead in production (see `CropPlan`) —
 * and it is not a whole-program guarantee either, because a hand-built
 * `EditorState` reaches no funnel at all (which is why `cropViewport` re-checks).
 * An off-frame rect is pulled inside; an already-valid plan is returned BY
 * REFERENCE so merely carrying a plan stays allocation-free.
 *
 * An unusable rect is DROPPED while the plan itself SURVIVES, which deliberately
 * DECOUPLES "has a crop plan" from "has something to preview". Whoever adopts
 * this container owns that decision, because BOTH of today's consumers key on
 * presence alone and neither looks at the rect: `landingZones`
 * (`lib/directorHandoff.ts`) reports the Reframe zone `ready` with "Crop plan in
 * place — framing nudges land on it.", and `framingSummary`
 * (`features/export/exportModel.ts`) renders
 * "Reframed". For a plan whose rect was dropped, both would say yes while
 * `cropViewport` returns null — the status text promising nudges land on a rect
 * that does not exist. Switching those reads to `cropViewport(state) !== null`
 * is the open decision; it is not this module's to make unilaterally.
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
 * by the rendered stage size to get the overlay box.
 *
 * It re-validates through `cropFraming` instead of trusting `normalizeCropPlan`,
 * because normalisation owns only TWO of the three ways an `EditorState` comes
 * to exist: `initialEditorState` and the `setCropPlan` case both funnel through
 * it, but a state object assembled DIRECTLY does not — and that is not a
 * hypothetical, it is the shape this module's own tests build. TypeScript cannot
 * express "positive and finite", so the compiler cannot stop one either, and
 * marking a field `readonly` would NOT help: `readonly` forbids a later
 * mutation, not an object literal that carries a degenerate frame from birth.
 * So this selector validates its own denominator and resolves an unusable rect
 * to null exactly as `cropFraming` does — it can never emit Infinity or NaN.
 */
export function cropViewport(state: EditorState): CropViewport | null {
  const framing = state.cropPlan?.framing;
  if (framing === undefined) return null;
  const usable = cropFraming(framing.crop, framing.sourceWidth, framing.sourceHeight);
  if (usable === null) return null;
  const [x, y, w, h] = usable.crop;
  return {
    x: x / usable.sourceWidth,
    y: y / usable.sourceHeight,
    width: w / usable.sourceWidth,
    height: h / usable.sourceHeight,
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
