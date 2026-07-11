// directorHandoff.ts — the PURE per-phase hand-off model for the Director screen.
//
// The redesign directive (§4 "Director"): the Director's output must land as
// REVIEWABLE per-phase diffs — cuts -> Edit, keyframes -> Caption, crop -> Reframe —
// and NOTHING is applied until the user confirms. This module is that hand-off's
// PURE core: the op-kind -> phase routing map, the ordered routing contract the
// screen shows while planning, and the LIVE "landing zone" status derived from the
// shared editor state (does this video already hold a transcript / crop plan the
// diffs land against). No React, no DOM — so it is exhaustively unit-testable and
// the screen stays a thin render shell (mirrors directorTypes' pure-helper split).

import type { DirectorOpKind } from './directorTypes';
import { type EditorState, transcriptReady } from './editorState';

/** The three phases a Director edit decomposes into (each its own review surface). */
export type HandoffPhase = 'edit' | 'caption' | 'reframe';

/**
 * Which review phase each Director op-kind's diff lands in. The three the
 * direction names (cuts -> Edit, caption timing -> Caption, crop -> Reframe) plus
 * their siblings. Terminal/analysis kinds (an export render, an on-screen-text
 * read) are NOT reviewable phase diffs and map to null. Total over DirectorOpKind
 * (the Record type enforces it), so `phaseForOpKind` needs no fallback branch.
 */
const PHASE_BY_OP_KIND: Readonly<Record<DirectorOpKind, HandoffPhase | null>> = {
  trim: 'edit',
  cut: 'edit',
  join: 'edit',
  removeSilence: 'edit',
  removeFillers: 'edit',
  reorder: 'edit',
  retime: 'edit',
  reframe: 'reframe',
  zoomPan: 'reframe',
  stitchPanorama: 'reframe',
  regenScroll: 'reframe',
  caption: 'caption',
  translateCaption: 'caption',
  overlayText: 'caption',
  lowerThird: 'caption',
  export: null,
  ocrExtractList: null,
};

/** The review phase an op-kind's diff lands in, or null when it is not a phase diff. */
export function phaseForOpKind(kind: DirectorOpKind): HandoffPhase | null {
  return PHASE_BY_OP_KIND[kind];
}

/** One row of the per-phase hand-off contract shown on the Director screen. */
export interface HandoffRoute {
  phase: HandoffPhase;
  /** What KIND of change routes here, in plain language (never op-kind jargon). */
  change: string;
  /** The destination phase name as it appears in the app rail. */
  destination: string;
  /** One quiet line describing the reviewable diff that lands there. */
  blurb: string;
}

/**
 * The ordered hand-off contract: the three review phases a Director edit lands in,
 * in the order the direction names them (cuts -> Edit, keyframes -> Caption,
 * crop -> Reframe). Rendered as the "where your edit lands" legend so the review-
 * per-phase promise is legible while the user plans.
 */
export const HANDOFF_ROUTES: readonly HandoffRoute[] = [
  {
    phase: 'edit',
    change: 'Cuts & pacing',
    destination: 'Edit',
    blurb: 'Trims, cuts and reordering arrive as reviewable timeline edits.',
  },
  {
    phase: 'caption',
    change: 'Caption timing',
    destination: 'Caption',
    blurb: 'Caption cues and on-screen text arrive as reviewable word timing.',
  },
  {
    phase: 'reframe',
    change: 'Crop & framing',
    destination: 'Reframe',
    blurb: 'Reframing and zoom nudges arrive as a reviewable crop plan.',
  },
];

/** The live status of one review phase's landing zone (what diffs land against). */
export interface LandingZone {
  phase: HandoffPhase;
  /** True when the target already holds the baseline content the diffs build on. */
  ready: boolean;
  /** A short, jargon-free status line (single-sourced here for the screen + tests). */
  status: string;
}

/**
 * Derive each phase's landing-zone status from the shared editor state — the
 * baseline a Director diff would land against. Edit is always ready (there is
 * always a source timeline); Caption is ready once a transcript exists (its cues
 * are the word timing the Director re-times); Reframe is ready once a crop plan
 * exists (else framing starts from center). Pure + total: one entry per phase, in
 * the same order as {@link HANDOFF_ROUTES}.
 */
export function landingZones(state: EditorState): LandingZone[] {
  const transcript = transcriptReady(state);
  const wordCount = state.cues.length;
  const hasCrop = state.cropPlan !== null;
  return [
    {
      phase: 'edit',
      ready: true,
      status: 'Timeline ready — cuts land as reviewable edits.',
    },
    {
      phase: 'caption',
      ready: transcript,
      status: transcript
        ? `Transcript ready — ${wordCount} ${wordCount === 1 ? 'word' : 'words'} to re-time.`
        : 'No transcript yet — the Director reads the speech first.',
    },
    {
      phase: 'reframe',
      ready: hasCrop,
      status: hasCrop
        ? 'Crop plan in place — framing nudges land on it.'
        : 'No crop plan yet — framing starts from center.',
    },
  ];
}

/** A hand-off route merged with its live landing-zone status (what the screen renders). */
export interface HandoffRow extends HandoffRoute {
  ready: boolean;
  status: string;
}

/**
 * Merge each {@link HANDOFF_ROUTES} row with its {@link landingZones} status,
 * aligned by position (both lists are the three phases in the same order). The
 * screen maps these directly, so the review contract + the live baseline render as
 * one row per phase.
 */
export function handoffRows(state: EditorState): HandoffRow[] {
  const zones = landingZones(state);
  return HANDOFF_ROUTES.map((route, i) => ({
    ...route,
    ready: zones[i].ready,
    status: zones[i].status,
  }));
}

/**
 * The brand's signature trust line, kept VERBATIM (§4 "Director" voice) — rendered
 * in the AA-safe quiet step on the screen, never the rejected #50555F. Single-
 * sourced here so the wording can never silently drift (matches DirectorPanel's
 * own intro).
 */
export const TRUST_REVERSIBLE =
  'The Director plans a reviewable, reversible edit — nothing is applied until you confirm.';

/**
 * The verbatim per-data-type egress beat — identical to the string directorTypes'
 * `egressWarning` surfaces for a text-egressing op, so the privacy voice reads the
 * same everywhere the Director speaks it.
 */
export const TRUST_TEXT_EGRESS = 'Text will leave your machine.';
