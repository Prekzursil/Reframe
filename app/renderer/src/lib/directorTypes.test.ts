// directorTypes.test.ts — the Director panel's PURE presentation logic
// (WU-panel): plan summary (F1), op grouping/collapse (F1), status text +
// recovery hint (F2), cost-row labels + egress warnings (F3). No React/DOM —
// pure functions covered to 100% in isolation.

import { describe, it, expect } from 'vitest';

import {
  GROUP_COLLAPSE_THRESHOLD,
  canMoveOp,
  costRowLabel,
  egressWarning,
  groupOpsByKind,
  isFrameFunction,
  moveOpWithinKind,
  opKindLabel,
  opMoveTargetIndex,
  planKinds,
  pluralize,
  recoveryHint,
  statusLabel,
  summarizePlan,
  toggleOpStatus,
} from './directorTypes';
import type { DirectorCostRow, DirectorEditPlan, DirectorOp, DirectorOpKind } from './rpc';

function op(over: Partial<DirectorOp> = {}): DirectorOp {
  return {
    id: 'op-1',
    kind: 'trim',
    span: [0, 1000],
    params: {},
    reversible: true,
    rationale: '',
    status: 'planned',
    statusReason: null,
    ...over,
  };
}

function plan(ops: DirectorOp[]): DirectorEditPlan {
  return { planId: 'p1', videoId: 'v1', goal: 'g', sourceHash: 'h', ops, inverse: [] };
}

function costRow(over: Partial<DirectorCostRow> = {}): DirectorCostRow {
  return {
    function: 'editPlan',
    route: 'local',
    costEst: 0,
    willEgress: false,
    cacheHit: false,
    cacheKey: 'k',
    ...over,
  };
}

describe('opKindLabel', () => {
  it('maps every known kind to a friendly noun', () => {
    expect(opKindLabel('trim')).toBe('trim');
    expect(opKindLabel('join')).toBe('join');
    expect(opKindLabel('ocrExtractList')).toBe('on-screen text read');
    expect(opKindLabel('overlayText')).toBe('text overlay');
  });
  it('falls back to the raw kind for an unknown value', () => {
    expect(opKindLabel('mystery' as DirectorOpKind)).toBe('mystery');
  });
});

describe('pluralize', () => {
  it('singular for 1, plural otherwise', () => {
    expect(pluralize(1, 'trim')).toBe('1 trim');
    expect(pluralize(3, 'trim')).toBe('3 trims');
    expect(pluralize(0, 'trim')).toBe('0 trims');
  });
});

describe('summarizePlan', () => {
  it('counts non-dropped ops per kind in first-seen order', () => {
    const p = plan([
      op({ id: 'a', kind: 'trim' }),
      op({ id: 'b', kind: 'trim' }),
      op({ id: 'c', kind: 'trim' }),
      op({ id: 'd', kind: 'reorder' }),
      op({ id: 'e', kind: 'overlayText' }),
    ]);
    expect(summarizePlan(p)).toBe('3 trims, 1 reorder, 1 text overlay');
  });
  it('appends a dropped suffix and excludes dropped ops from counts', () => {
    const p = plan([
      op({ id: 'a', kind: 'trim' }),
      op({ id: 'b', kind: 'cut', status: 'dropped', statusReason: 'span-exceeds-clip' }),
      op({ id: 'c', kind: 'cut', status: 'dropped', statusReason: 'unknown-track' }),
    ]);
    expect(summarizePlan(p)).toBe('1 trim · 2 dropped ops');
  });
  it('reports "No changes" for an empty plan', () => {
    expect(summarizePlan(plan([]))).toBe('No changes');
  });
  it('reports "No changes" plus the dropped suffix when every op was dropped', () => {
    const p = plan([op({ id: 'a', kind: 'trim', status: 'dropped' })]);
    expect(summarizePlan(p)).toBe('No changes · 1 dropped op');
  });
});

describe('groupOpsByKind / planKinds', () => {
  it('groups by kind preserving first-seen kind + per-kind op order', () => {
    const ops = [
      op({ id: 'a', kind: 'trim' }),
      op({ id: 'b', kind: 'reorder' }),
      op({ id: 'c', kind: 'trim' }),
    ];
    const groups = groupOpsByKind(ops);
    expect(groups.map((g) => g.kind)).toEqual(['trim', 'reorder']);
    expect(groups[0].ops.map((o) => o.id)).toEqual(['a', 'c']);
    expect(groups[0].label).toBe('trim');
    expect(planKinds(ops)).toEqual(['trim', 'reorder']);
  });
  it('collapses a group larger than the threshold, not a small one', () => {
    const small = groupOpsByKind([op({ id: 'x', kind: 'trim' })]);
    expect(small[0].collapsedByDefault).toBe(false);
    const big = Array.from({ length: GROUP_COLLAPSE_THRESHOLD + 1 }, (_, i) =>
      op({ id: `o${i}`, kind: 'overlayText' }),
    );
    expect(groupOpsByKind(big)[0].collapsedByDefault).toBe(true);
  });
});

describe('statusLabel', () => {
  it('maps each status to its word', () => {
    expect(statusLabel('planned')).toBe('Planned');
    expect(statusLabel('applied')).toBe('Applied');
    expect(statusLabel('failed')).toBe('Failed');
    expect(statusLabel('dropped')).toBe('Dropped');
  });
});

describe('recoveryHint', () => {
  it('offers a recovery hint only for failed ops', () => {
    expect(recoveryHint(op({ status: 'failed' }))).toMatch(/re-apply/);
    expect(recoveryHint(op({ status: 'dropped' }))).toBe('');
    expect(recoveryHint(op({ status: 'planned' }))).toBe('');
  });
});

describe('cost-row helpers', () => {
  it('isFrameFunction is true only for vision', () => {
    expect(isFrameFunction(costRow({ function: 'vision' }))).toBe(true);
    expect(isFrameFunction(costRow({ function: 'editPlan' }))).toBe(false);
  });
  it('costRowLabel names text vs frames', () => {
    expect(costRowLabel(costRow({ function: 'editPlan' }))).toBe('Edit-plan text');
    expect(costRowLabel(costRow({ function: 'vision' }))).toMatch(/frames/i);
  });
  it('egressWarning is empty when local, frame-specific when frames egress', () => {
    expect(egressWarning(costRow({ willEgress: false }))).toBe('');
    expect(egressWarning(costRow({ function: 'vision', willEgress: true }))).toMatch(
      /highest cost and privacy/i,
    );
    expect(egressWarning(costRow({ function: 'editPlan', willEgress: true }))).toBe(
      'Text will leave your machine.',
    );
  });
});

describe('toggleOpStatus', () => {
  it('disables a planned op (planned -> dropped), immutably', () => {
    const ops = [op({ id: 'a', status: 'planned' })];
    const next = toggleOpStatus(ops, 'a');
    expect(next).not.toBe(ops);
    expect(next[0]).not.toBe(ops[0]);
    expect(next[0].status).toBe('dropped');
    expect(ops[0].status).toBe('planned'); // source unchanged
  });
  it('re-enables a dropped op (dropped -> planned) and clears its reason', () => {
    const ops = [op({ id: 'a', status: 'dropped', statusReason: 'span-exceeds-clip' })];
    const next = toggleOpStatus(ops, 'a');
    expect(next[0].status).toBe('planned');
    expect(next[0].statusReason).toBeNull();
  });
  it('disables a non-planned, non-dropped op (e.g. failed -> dropped)', () => {
    const ops = [op({ id: 'a', status: 'failed' })];
    expect(toggleOpStatus(ops, 'a')[0].status).toBe('dropped');
  });
  it('leaves other ops untouched and is a no-op copy for an unknown id', () => {
    const ops = [op({ id: 'a' }), op({ id: 'b', kind: 'reorder' })];
    const next = toggleOpStatus(ops, 'zzz');
    expect(next[0]).toBe(ops[0]);
    expect(next[1]).toBe(ops[1]);
  });
});

describe('opMoveTargetIndex / canMoveOp / moveOpWithinKind', () => {
  it('finds the nearest same-kind neighbour up and down', () => {
    const ops = [op({ id: 'a' }), op({ id: 'b' }), op({ id: 'c' })];
    expect(opMoveTargetIndex(ops, 'b', 'up')).toBe(0);
    expect(opMoveTargetIndex(ops, 'b', 'down')).toBe(2);
  });
  it('skips a different-kind neighbour to the next same-kind op', () => {
    const ops = [op({ id: 'a' }), op({ id: 'x', kind: 'reorder' }), op({ id: 'c' })];
    // "a" (trim) moving down skips the reorder op and targets "c" (trim) at index 2.
    expect(opMoveTargetIndex(ops, 'a', 'down')).toBe(2);
  });
  it('returns -1 at a boundary (first/last of its kind) and for an unknown id', () => {
    const ops = [op({ id: 'a' }), op({ id: 'b' })];
    expect(opMoveTargetIndex(ops, 'a', 'up')).toBe(-1);
    expect(opMoveTargetIndex(ops, 'b', 'down')).toBe(-1);
    expect(opMoveTargetIndex(ops, 'zzz', 'up')).toBe(-1);
  });
  it('canMoveOp mirrors the boundary check', () => {
    const ops = [op({ id: 'a' }), op({ id: 'b' })];
    expect(canMoveOp(ops, 'a', 'down')).toBe(true);
    expect(canMoveOp(ops, 'a', 'up')).toBe(false);
    expect(canMoveOp(ops, 'b', 'down')).toBe(false);
  });
  it('moveOpWithinKind swaps with the same-kind neighbour, immutably', () => {
    const ops = [op({ id: 'a' }), op({ id: 'b' }), op({ id: 'c' })];
    const next = moveOpWithinKind(ops, 'a', 'down');
    expect(next).not.toBe(ops);
    expect(next.map((o) => o.id)).toEqual(['b', 'a', 'c']);
    expect(ops.map((o) => o.id)).toEqual(['a', 'b', 'c']); // source unchanged
  });
  it('moveOpWithinKind at a boundary returns a no-op copy', () => {
    const ops = [op({ id: 'a' }), op({ id: 'b' })];
    const next = moveOpWithinKind(ops, 'a', 'up');
    expect(next).not.toBe(ops);
    expect(next.map((o) => o.id)).toEqual(['a', 'b']);
  });
});
