// directorTypes.ts — the renderer's pure logic + presentation helpers for the
// Director panel (WU-panel). The EditPlan wire TYPES live in lib/rpc.ts (the one
// frozen-schema source mirrored from the sidecar `edit_plan.edit_plan_json_schema`
// + the `director_*` handler payloads); this module re-exports them for panel
// imports and adds the PURE, fully-tested presentation transforms the panel uses:
//
//   * `opKindLabel` — a friendly noun for an op kind (deterministic, no LLM).
//   * `summarizePlan` — the F1 plain-language header ("3 trims, 1 reorder …
//     · 2 dropped"), derived deterministically from `editPlan.ops`.
//   * `groupOpsByKind` — the F1 collapsible grouping (ops grouped by kind,
//     order-stable), with the collapse decision when a group exceeds a threshold.
//   * `statusLabel` / `recoveryHint` — the F2 per-op status text.
//   * `costRowLabel` / `isFrameFunction` — the F3 per-data-type banner text
//     (frames flagged heaviest cost+privacy via a TEXT label, never color-only).
//
// PURITY: no React, no rpc, no DOM — every export is a pure function so the panel
// stays a thin render shell and the logic is covered to 100% in isolation.

import type { DirectorCostRow, DirectorEditPlan, DirectorOp, DirectorOpKind } from './rpc';

export type {
  DirectorApplyResult,
  DirectorCostRow,
  DirectorEditPlan,
  DirectorEval,
  DirectorMetrics,
  DirectorOp,
  DirectorOpKind,
  DirectorOpStatus,
  DirectorPlanResult,
  DirectorPreview,
} from './rpc';

/**
 * Default collapse threshold for an op group (F1): a group with MORE than this
 * many ops renders collapsed by default so a 50-op plan shows a few summary rows,
 * not 50 flat rows. Exported so the panel and its tests share one constant.
 */
export const GROUP_COLLAPSE_THRESHOLD = 5;

/** Friendly singular nouns per op kind (deterministic — no model text). */
const OP_KIND_LABELS: Record<DirectorOpKind, string> = {
  trim: 'trim',
  cut: 'cut',
  removeSilence: 'silence removal',
  removeFillers: 'filler removal',
  reorder: 'reorder',
  retime: 'retime',
  reframe: 'reframe',
  zoomPan: 'zoom/pan',
  caption: 'caption',
  translateCaption: 'caption translation',
  overlayText: 'text overlay',
  lowerThird: 'lower-third',
  export: 'export',
  stitchPanorama: 'panorama stitch',
  regenScroll: 'scroll regen',
  ocrExtractList: 'on-screen text read',
};

/** A friendly noun for an op kind (falls back to the raw kind if unknown). */
export function opKindLabel(kind: DirectorOpKind): string {
  return OP_KIND_LABELS[kind] ?? kind;
}

/** Pluralize `label` for `count` (naive English: append "s" when not 1). */
export function pluralize(count: number, label: string): string {
  return count === 1 ? `1 ${label}` : `${count} ${label}s`;
}

/**
 * The F1 plain-language plan summary, derived ONLY from `ops` (no LLM). Counts
 * the NON-dropped ops per kind in first-seen order ("3 trims, 1 reorder, 47 text
 * overlays") and appends a "· N dropped" suffix when any op was dropped. An
 * all-dropped/empty plan yields "No changes".
 */
export function summarizePlan(plan: DirectorEditPlan): string {
  const counts = new Map<DirectorOpKind, number>();
  let dropped = 0;
  for (const op of plan.ops) {
    if (op.status === 'dropped') {
      dropped += 1;
      continue;
    }
    counts.set(op.kind, (counts.get(op.kind) ?? 0) + 1);
  }
  const parts: string[] = [];
  for (const [kind, count] of counts) {
    parts.push(pluralize(count, opKindLabel(kind)));
  }
  const head = parts.length > 0 ? parts.join(', ') : 'No changes';
  return dropped > 0 ? `${head} · ${pluralize(dropped, 'dropped op')}` : head;
}

/** One collapsible op group (F1): all ops of one kind, in original order. */
export interface OpGroup {
  kind: DirectorOpKind;
  label: string;
  ops: DirectorOp[];
  /** Collapsed by default when the group exceeds {@link GROUP_COLLAPSE_THRESHOLD}. */
  collapsedByDefault: boolean;
}

/**
 * Group ops by kind (F1), preserving first-seen kind order AND per-kind op order.
 * A group larger than the collapse threshold starts collapsed so a big plan never
 * renders as a flat wall of rows.
 */
export function groupOpsByKind(ops: readonly DirectorOp[]): OpGroup[] {
  const byKind = new Map<DirectorOpKind, DirectorOp[]>();
  for (const op of ops) {
    const bucket = byKind.get(op.kind);
    if (bucket) {
      bucket.push(op);
    } else {
      byKind.set(op.kind, [op]);
    }
  }
  const groups: OpGroup[] = [];
  for (const [kind, kindOps] of byKind) {
    groups.push({
      kind,
      label: opKindLabel(kind),
      ops: kindOps,
      collapsedByDefault: kindOps.length > GROUP_COLLAPSE_THRESHOLD,
    });
  }
  return groups;
}

/** The set of op kinds present in a plan (for the F1 op-type filter), in order. */
export function planKinds(ops: readonly DirectorOp[]): DirectorOpKind[] {
  return groupOpsByKind(ops).map((g) => g.kind);
}

/** Human-readable status word for an op row (F2). */
export function statusLabel(status: DirectorOp['status']): string {
  switch (status) {
    case 'applied':
      return 'Applied';
    case 'failed':
      return 'Failed';
    case 'dropped':
      return 'Dropped';
    /* v8 ignore next 2 -- the switch is exhaustive over OpStatus; "planned" is the default arm. */
    default:
      return 'Planned';
  }
}

/**
 * The F2 recovery hint for a FAILED op ("edit or disable, then re-apply"), or the
 * empty string for any non-failed op (dropped rows show the reason, not a hint).
 */
export function recoveryHint(op: DirectorOp): string {
  return op.status === 'failed' ? 'Edit or disable this step, then re-apply.' : '';
}

/**
 * Toggle one op's enabled/disabled state in a plan's ops list (WU-director-
 * controls), returning a NEW array (immutable; the source is never mutated). A
 * `dropped` op becomes `planned` (re-enabled); ANY other op becomes `dropped`
 * (disabled). Re-enabling clears the stale `statusReason` so a previously-dropped
 * op no longer shows the drop reason once it is back in the plan. An unknown id
 * returns the same logical list (a no-op copy).
 */
export function toggleOpStatus(ops: readonly DirectorOp[], opId: string): DirectorOp[] {
  return ops.map((o) => {
    if (o.id !== opId) return o;
    return o.status === 'dropped'
      ? { ...o, status: 'planned', statusReason: null }
      : { ...o, status: 'dropped' };
  });
}

/** A move direction for a storyboard op control (F5 reorder). */
export type OpMoveDirection = 'up' | 'down';

/**
 * Index of the same-KIND neighbour of `opId` in `ops` for a move in `dir`, or
 * `-1` when `opId` is the first/last op of its kind (a boundary — the control is
 * disabled there). Reordering is WITHIN a kind so the move is visible: the
 * storyboard groups ops by kind, so swapping past a different-kind neighbour
 * would be an invisible no-op.
 */
export function opMoveTargetIndex(
  ops: readonly DirectorOp[],
  opId: string,
  dir: OpMoveDirection,
): number {
  const idx = ops.findIndex((o) => o.id === opId);
  if (idx < 0) return -1;
  const kind = ops[idx].kind;
  const step = dir === 'up' ? -1 : 1;
  for (let i = idx + step; i >= 0 && i < ops.length; i += step) {
    if (ops[i].kind === kind) return i;
  }
  return -1;
}

/** True when `opId` can move `dir` within its kind (i.e. it is not at a boundary). */
export function canMoveOp(
  ops: readonly DirectorOp[],
  opId: string,
  dir: OpMoveDirection,
): boolean {
  return opMoveTargetIndex(ops, opId, dir) >= 0;
}

/**
 * Move one op `up`/`down` past its nearest same-kind neighbour, returning a NEW
 * ops array (immutable). A boundary move (no same-kind neighbour in `dir`) is a
 * no-op copy so the caller can call unconditionally.
 */
export function moveOpWithinKind(
  ops: readonly DirectorOp[],
  opId: string,
  dir: OpMoveDirection,
): DirectorOp[] {
  const idx = ops.findIndex((o) => o.id === opId);
  const target = opMoveTargetIndex(ops, opId, dir);
  if (target < 0) return ops.slice();
  const next = ops.slice();
  [next[idx], next[target]] = [next[target], next[idx]];
  return next;
}

/** True when a cost row is the frame/vision data type (heaviest cost+privacy). */
export function isFrameFunction(row: DirectorCostRow): boolean {
  return row.function === 'vision';
}

/** A friendly data-type label for a cost row (F3): text vs frames. */
export function costRowLabel(row: DirectorCostRow): string {
  return isFrameFunction(row) ? 'On-screen frames (vision/OCR)' : 'Edit-plan text';
}

/**
 * The F3 egress warning TEXT for a cost row, or "" when it stays local. Frames
 * carry an explicit privacy+cost warning; text a lighter egress note. ALWAYS a
 * text label — never color-only (a11y F5).
 */
export function egressWarning(row: DirectorCostRow): string {
  if (!row.willEgress) return '';
  return isFrameFunction(row)
    ? 'Frames will leave your machine — highest cost and privacy impact.'
    : 'Text will leave your machine.';
}
