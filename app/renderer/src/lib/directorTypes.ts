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
  join: 'join',
  transition: 'transition',
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

/**
 * The op kinds the sidecar's apply engine has NO adapter for yet — a MIRROR of
 * `media_studio.models.edit_plan.DEFERRED_OP_KINDS`, which is the single source
 * of truth. TypeScript cannot read the Python union, so the two are stated twice
 * on purpose and pinned by `sidecar/tests/test_director_op_kind_parity.py`
 * (it parses THIS array) — change one, change both.
 *
 * The kinds stay in `DirectorOpKind` and keep their labels: a cached or
 * previously-saved plan may still contain one and must render. What changed is
 * that they are no longer presented as available — `opKindLabel` marks them, and
 * the planner is no longer told it may emit them at all.
 */
export const DEFERRED_OP_KINDS: readonly DirectorOpKind[] = [
  'stitchPanorama',
  'regenScroll',
  'ocrExtractList',
];

/** The suffix appended to a deferred kind's label so the UI never over-promises. */
export const UNAVAILABLE_SUFFIX = ' (unavailable)';

/** True when `kind` has a wired engine, i.e. an op of this kind can actually run. */
export function isOpKindAvailable(kind: DirectorOpKind): boolean {
  return !DEFERRED_OP_KINDS.includes(kind);
}

/** The bare noun for an op kind, with NO availability marker (pluralizable). */
function opKindNoun(kind: DirectorOpKind): string {
  return OP_KIND_LABELS[kind] ?? kind;
}

/**
 * A friendly noun for an op kind (falls back to the raw kind if unknown).
 *
 * A kind with no engine is labelled `… (unavailable)`. Doing it HERE rather than
 * in the panel means every surface that names a kind — the storyboard rows, the
 * op-type filter, the plan summary — tells the same truth without each having to
 * remember to ask.
 */
export function opKindLabel(kind: DirectorOpKind): string {
  const noun = opKindNoun(kind);
  return isOpKindAvailable(kind) ? noun : `${noun}${UNAVAILABLE_SUFFIX}`;
}

/** Pluralize `label` for `count` (naive English: append "s" when not 1). */
export function pluralize(count: number, label: string): string {
  return count === 1 ? `1 ${label}` : `${count} ${label}s`;
}

/**
 * "3 trims" / "2 panorama stitchs (unavailable)" — a counted op-kind phrase.
 *
 * The availability marker is attached AFTER pluralizing the bare noun. Feeding
 * `opKindLabel` straight into {@link pluralize} would produce
 * "2 panorama stitch (unavailable)s", pluralizing the parenthetical instead of
 * the noun. (The bare plural stays the naive append-"s" of {@link pluralize} —
 * "stitchs", not "stitches"; this fixes marker placement, not English.)
 */
export function opKindCountLabel(count: number, kind: DirectorOpKind): string {
  const counted = pluralize(count, opKindNoun(kind));
  return isOpKindAvailable(kind) ? counted : `${counted}${UNAVAILABLE_SUFFIX}`;
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
    parts.push(opKindCountLabel(count, kind));
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
export function canMoveOp(ops: readonly DirectorOp[], opId: string, dir: OpMoveDirection): boolean {
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

/**
 * A readable label for a cost row's resolved route.
 *
 * `row.route` is an OBJECT on the wire (`ai_job.py:164-171`), so it can never be
 * rendered directly — doing so threw "Objects are not valid as a React child" on
 * every successful plan. This flattens it to the provider chain the user cares
 * about: the ordered providers, then the degrade fallbacks after a separator.
 *
 * Defensive on purpose: the sidecar may send an empty provider list for a purely
 * local route, and a stale/partial payload may omit the arrays entirely. Both
 * degrade to a meaningful word rather than "undefined" or a blank span.
 */
export function routeLabel(row: DirectorCostRow): string {
  const route = row.route as Partial<DirectorCostRow['route']> | null | undefined;
  const providers = Array.isArray(route?.providers) ? route.providers.filter(Boolean) : [];
  const degrade = Array.isArray(route?.degradeChain) ? route.degradeChain.filter(Boolean) : [];
  if (providers.length === 0 && degrade.length === 0) return 'local';
  const primary = providers.length > 0 ? providers.join(' → ') : 'local';
  return degrade.length > 0 ? `${primary} (falls back to ${degrade.join(' → ')})` : primary;
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
