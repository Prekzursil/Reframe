// DirectorPanel.test.tsx — the AI Director (prompt-driven editing) panel:
// prompt -> director.plan job -> storyboard/diff (F1 summary + collapsible groups
// + op-type filter), F2 per-op status/reason rows + failed recovery hint, F3
// per-data-type cost/egress banner (frames heaviest), F4 plain-text rationale
// (XSS-closed, no dangerouslySetInnerHTML), apply echoing the budget cacheKey,
// F6 adjust-&-re-plan keeping the prior plan visible, objective eval + undo, and
// F5 a11y (keyboard rows, aria-live progress, text egress labels).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Opt into React's act() testing environment so state updates are flushed
// deterministically (mirrors the component-hook tests in this repo).
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  DirectorPanel,
  asApplyResult,
  asPlanResult,
  errText,
  type JobEventBridge,
} from './DirectorPanel';
import type {
  DirectorApplyResult,
  DirectorEditPlan,
  DirectorEval,
  DirectorOp,
  DirectorPlanResult,
  DirectorPreview,
  DoneEvent,
  ProgressEvent,
  client as RealClient,
} from '../lib/rpc';

// ---- pure-helper coverage --------------------------------------------------

describe('pure helpers', () => {
  it('errText handles Error and non-Error', () => {
    expect(errText(new Error('boom'))).toBe('boom');
    expect(errText(42)).toBe('42');
  });
  it('asPlanResult narrows valid / rejects invalid', () => {
    expect(asPlanResult(null)).toBeNull();
    expect(asPlanResult(7)).toBeNull();
    expect(asPlanResult({ planId: 1 })).toBeNull();
    expect(asPlanResult({ planId: 'p', editPlan: 'x' })).toBeNull();
    const ok = { planId: 'p', editPlan: { ops: [] }, preview: '{}' };
    expect(asPlanResult(ok)).toBe(ok);
  });
  it('asApplyResult narrows valid / rejects invalid', () => {
    expect(asApplyResult(undefined)).toBeNull();
    expect(asApplyResult(0)).toBeNull();
    expect(asApplyResult({ planId: 'p' })).toBeNull();
    expect(asApplyResult({ planId: 'p', opsStatus: 'x' })).toBeNull();
    const ok = { planId: 'p', opsStatus: [], projectCopyPath: '/c' };
    expect(asApplyResult(ok)).toBe(ok);
  });
});

// ---- fixtures --------------------------------------------------------------

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

function planFixture(ops: DirectorOp[], goal = 'make it smooth'): DirectorEditPlan {
  return { planId: 'plan-1', videoId: 'vid-1', goal, sourceHash: 'h', ops, inverse: [] };
}

function previewFixture(over: Partial<DirectorPreview> = {}): DirectorPreview {
  return {
    perFunction: [
      {
        function: 'editPlan',
        route: 'groq',
        costEst: 10,
        willEgress: true,
        cacheHit: false,
        cacheKey: 'CK-TEXT',
      },
      {
        function: 'vision',
        route: 'cloud-vlm',
        costEst: 50,
        willEgress: true,
        cacheHit: true,
        cacheKey: 'CK-VIS',
      },
    ],
    ...over,
  };
}

function evalFixture(over: Partial<DirectorEval> = {}): DirectorEval {
  return {
    score: 0.82,
    deltas: { jerk: 0.5, cutRhythm: -0.2, silenceRatio: 0.1, ocrCoverage: 0.3 },
    beforeAfter: {
      before: { jerk: 1, cutRhythm: 1, silenceRatio: 0.4, ocrCoverage: 0.2 },
      after: { jerk: 0.5, cutRhythm: 1.2, silenceRatio: 0.3, ocrCoverage: 0.5 },
    },
    judgeNote: null,
    ...over,
  };
}

// ---- fake client + controllable job-event bus ------------------------------

interface FakeClient {
  client: typeof RealClient;
  calls: Array<{ method: string; args: unknown[] }>;
}

interface FakeOpts {
  plan?: DirectorPlanResult;
  preview?: DirectorPreview;
  applyResult?: DirectorApplyResult;
  undoResult?: DirectorApplyResult;
  evaluation?: DirectorEval;
  rejectPlan?: boolean;
  rejectApply?: boolean;
  rejectUndo?: boolean;
  rejectPreview?: boolean;
  rejectEvaluate?: boolean;
  /** previewCost resolves a falsy value (exercises the `?? null` arm). */
  falsyPreview?: boolean;
  /** evaluate resolves a falsy value (exercises the `?? null` arm). */
  falsyEvaluate?: boolean;
}

function makeClient(o: FakeOpts = {}): FakeClient {
  const calls: FakeClient['calls'] = [];
  const fake = {
    director: {
      plan: vi.fn(async (videoId: string, goal: string) => {
        calls.push({ method: 'director.plan', args: [videoId, goal] });
        if (o.rejectPlan) throw new Error('plan failed');
        return { jobId: 'job-plan' };
      }),
      previewCost: vi.fn(async (planId: string) => {
        calls.push({ method: 'director.previewCost', args: [planId] });
        if (o.rejectPreview) throw new Error('preview failed');
        if (o.falsyPreview) return undefined;
        return o.preview ?? previewFixture();
      }),
      apply: vi.fn(async (planId: string, confirmBudget?: string) => {
        calls.push({ method: 'director.apply', args: [planId, confirmBudget] });
        if (o.rejectApply) throw new Error('apply failed');
        return { jobId: 'job-apply' };
      }),
      undo: vi.fn(async (planId: string) => {
        calls.push({ method: 'director.undo', args: [planId] });
        if (o.rejectUndo) throw new Error('undo failed');
        return { jobId: 'job-undo' };
      }),
      evaluate: vi.fn(async (planId: string) => {
        calls.push({ method: 'director.evaluate', args: [planId] });
        if (o.rejectEvaluate) throw new Error('evaluate failed');
        if (o.falsyEvaluate) return undefined;
        return o.evaluation ?? evalFixture();
      }),
    },
  };
  return { client: fake as unknown as typeof RealClient, calls };
}

/** A controllable job-event bus the test drives to emit progress / job.done. */
function makeJobEvents(): JobEventBridge & {
  emitProgress(event: ProgressEvent): void;
  emitDone(event: DoneEvent): void;
  progressSubs: number;
  doneSubs: number;
} {
  const progressCbs = new Set<(e: ProgressEvent) => void>();
  const doneCbs = new Set<(e: DoneEvent) => void>();
  const bus = {
    progressSubs: 0,
    doneSubs: 0,
    onProgress(cb: (e: ProgressEvent) => void): () => void {
      bus.progressSubs += 1;
      progressCbs.add(cb);
      return () => {
        bus.progressSubs -= 1;
        progressCbs.delete(cb);
      };
    },
    onJobDone(cb: (e: DoneEvent) => void): () => void {
      bus.doneSubs += 1;
      doneCbs.add(cb);
      return () => {
        bus.doneSubs -= 1;
        doneCbs.delete(cb);
      };
    },
    emitProgress(event: ProgressEvent): void {
      for (const cb of progressCbs) cb(event);
    },
    emitDone(event: DoneEvent): void {
      for (const cb of doneCbs) cb(event);
    },
  };
  return bus;
}

// ---- DOM harness -----------------------------------------------------------

let container: HTMLDivElement;
let root: Root;
let events: ReturnType<typeof makeJobEvents>;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  events = makeJobEvents();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function mount(c: FakeClient): Promise<void> {
  await act(async () => {
    root.render(<DirectorPanel rpcClient={c.client} jobEvents={events} />);
  });
  await flush();
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function $(sel: string): HTMLElement {
  const el = container.querySelector(sel);
  if (!el) throw new Error(`no element for ${sel}`);
  return el as HTMLElement;
}

function $all(sel: string): HTMLElement[] {
  return Array.from(container.querySelectorAll(sel)) as HTMLElement[];
}

async function setGoal(text: string): Promise<void> {
  const ta = $('textarea[data-action="goal"]') as HTMLTextAreaElement;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value',
  )?.set;
  await act(async () => {
    setter?.call(ta, text);
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function clickPlan(): Promise<void> {
  await act(async () => {
    $('button[data-action="plan"]').click();
  });
  await flush();
}

async function emitPlanDone(c: FakeClient, plan: DirectorEditPlan): Promise<void> {
  await act(async () => {
    events.emitDone({
      jobId: 'job-plan',
      result: { planId: plan.planId, editPlan: plan, preview: '{}' },
    });
  });
  await flush();
  void c;
}

/** End-to-end: plan a fixture plan and wait for its storyboard. */
async function planTo(c: FakeClient, plan: DirectorEditPlan): Promise<void> {
  await mount(c);
  await setGoal(plan.goal);
  await clickPlan();
  await emitPlanDone(c, plan);
}

// ---- tests -----------------------------------------------------------------

describe('DirectorPanel', () => {
  it('(a) submitting the prompt calls director.plan with the goal', async () => {
    const c = makeClient();
    await mount(c);
    expect(events.progressSubs).toBe(1);
    expect(events.doneSubs).toBe(1);
    await setGoal('make it smooth');
    await clickPlan();
    expect(c.calls.find((x) => x.method === 'director.plan')?.args).toEqual([
      'make it smooth',
      'make it smooth',
    ]);
    // F5: progress region is SR-announced.
    const prog = $('[data-section="progress"]');
    expect(prog.getAttribute('aria-live')).toBe('polite');
    expect(prog.textContent).toBe('Planning…');
  });

  it('blank prompt or whitespace does not call director.plan (button disabled)', async () => {
    const c = makeClient();
    await mount(c);
    expect(($('button[data-action="plan"]') as HTMLButtonElement).disabled).toBe(true);
    await setGoal('   ');
    expect(($('button[data-action="plan"]') as HTMLButtonElement).disabled).toBe(true);
    // Submitting the form directly is also a no-op for whitespace.
    await act(async () => {
      $('form.director-prompt').dispatchEvent(
        new Event('submit', { bubbles: true, cancelable: true }),
      );
    });
    await flush();
    expect(c.calls.some((x) => x.method === 'director.plan')).toBe(false);
  });

  it('(b) a 50-op plan renders grouped collapsible sections, not 50 flat rows', async () => {
    const ops = Array.from({ length: 50 }, (_, i) =>
      op({ id: `o${i}`, kind: 'overlayText', rationale: `caption ${i}` }),
    );
    ops.push(op({ id: 'trim-1', kind: 'trim' }));
    const c = makeClient();
    await planTo(c, planFixture(ops, 'q&a showcase'));
    // F1 summary header (deterministic).
    expect($('[data-testid="plan-summary"]').textContent).toBe('50 text overlays, 1 trim');
    // Two groups; the big overlayText group is collapsed by default.
    const groups = $all('details.director-group');
    expect(groups.length).toBe(2);
    const overlay = $('details[data-kind="overlayText"]') as HTMLDetailsElement;
    expect(overlay.open).toBe(false);
    const trim = $('details[data-kind="trim"]') as HTMLDetailsElement;
    expect(trim.open).toBe(true);
  });

  it('the op-type filter narrows the visible groups', async () => {
    const ops = [op({ id: 'a', kind: 'trim' }), op({ id: 'b', kind: 'reorder' })];
    const c = makeClient();
    await planTo(c, planFixture(ops));
    expect($all('details.director-group').length).toBe(2);
    const select = $('select[data-action="kind-filter"]') as HTMLSelectElement;
    await act(async () => {
      select.value = 'reorder';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await flush();
    const visible = $all('details.director-group');
    expect(visible.length).toBe(1);
    expect(visible[0].getAttribute('data-kind')).toBe('reorder');
  });

  it('single-kind plan shows no op-type filter', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })]));
    expect(container.querySelector('select[data-action="kind-filter"]')).toBeNull();
  });

  it('(c) F2: dropped op shows its reason; failed op shows a recovery hint', async () => {
    const ops = [
      op({ id: 'd1', kind: 'cut', status: 'dropped', statusReason: 'span-exceeds-clip' }),
      op({ id: 'f1', kind: 'reframe', status: 'failed', statusReason: 'engine boom' }),
    ];
    const c = makeClient();
    await planTo(c, planFixture(ops));
    expect($('[data-testid="status-d1"]').textContent).toBe('Dropped');
    expect($('[data-testid="reason-d1"]').textContent).toBe('span-exceeds-clip');
    expect($('[data-testid="status-f1"]').textContent).toBe('Failed');
    expect($('[data-testid="hint-f1"]').textContent).toMatch(/re-apply/);
    // Dropped row carries no recovery hint.
    expect(container.querySelector('[data-testid="hint-d1"]')).toBeNull();
  });

  it('(d) F3: cost banner shows text + frame rows separately; frame egress flagged', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a' })]));
    const rows = $all('.director-cost__row');
    expect(rows.length).toBe(2);
    const frame = $('.director-cost__row[data-function="vision"]');
    expect(frame.classList.contains('is-frame')).toBe(true);
    // Per-function egress text labels (never color-only).
    expect($('[data-testid="egress-vision"]').textContent).toMatch(/highest cost and privacy/i);
    expect($('[data-testid="egress-editPlan"]').textContent).toBe('Text will leave your machine.');
    // cacheHit surfaced per function.
    expect(frame.textContent).toMatch(/cached/i);
  });

  it('cost banner omits the egress label for a local (no-egress) row', async () => {
    const c = makeClient({
      preview: previewFixture({
        perFunction: [
          {
            function: 'editPlan',
            route: 'local',
            costEst: 0,
            willEgress: false,
            cacheHit: false,
            cacheKey: 'CK',
          },
        ],
      }),
    });
    await planTo(c, planFixture([op({ id: 'a' })]));
    expect(container.querySelector('[data-testid="egress-editPlan"]')).toBeNull();
    expect($('.director-cost__row[data-function="editPlan"]').getAttribute('data-egress')).toBe(
      'no',
    );
  });

  it('(e) F4: a rationale containing HTML renders as literal text (XSS-closed)', async () => {
    const evil = '<img src=x onerror="alert(1)"><script>steal()</script>';
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'x', kind: 'trim', rationale: evil })]));
    const rationale = $('.director-op__rationale');
    // Rendered as text — the literal string, with NO injected element.
    expect(rationale.textContent).toBe(evil);
    expect(rationale.querySelector('img')).toBeNull();
    expect(rationale.querySelector('script')).toBeNull();
    // No dangerouslySetInnerHTML anywhere in the rendered tree.
    expect(container.innerHTML).not.toContain('<img src=x');
  });

  it('(f) Apply echoes the budget cacheKey as confirmBudget and surfaces statuses', async () => {
    const c = makeClient({
      applyResult: {
        planId: 'plan-1',
        opsStatus: [op({ id: 'a', kind: 'trim', status: 'applied' })],
        projectCopyPath: '/copy',
        inversePlan: planFixture([]),
      },
    });
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    // The first preview row's cacheKey is echoed.
    expect(c.calls.find((x) => x.method === 'director.apply')?.args).toEqual(['plan-1', 'CK-TEXT']);
    // job.done -> applied statuses surface; eval/undo controls appear.
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: {
          planId: 'plan-1',
          opsStatus: [op({ id: 'a', kind: 'trim', status: 'applied' })],
          projectCopyPath: '/copy',
        },
      });
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Applied');
    expect(container.querySelector('button[data-action="evaluate"]')).not.toBeNull();
    expect(container.querySelector('button[data-action="undo"]')).not.toBeNull();
  });

  it('evaluate surfaces the objective score + deltas; judge note shown but labeled', async () => {
    const c = makeClient({ evaluation: evalFixture({ judgeNote: 'looks great' }) });
    await planTo(c, planFixture([op({ id: 'a' })]));
    // Apply first so the evaluate button exists.
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: { planId: 'plan-1', opsStatus: [op({ id: 'a' })], projectCopyPath: '/c' },
      });
    });
    await flush();
    await act(async () => {
      $('button[data-action="evaluate"]').click();
    });
    await flush();
    expect($('[data-testid="eval-score"]').textContent).toBe('Objective score: 82%');
    expect($('[data-testid="delta-jerk"]').textContent).toBe('jerk: +0.500');
    expect($('[data-testid="delta-cutRhythm"]').textContent).toBe('cutRhythm: -0.200');
    expect($('[data-testid="judge-note"]').textContent).toMatch(/does not affect score/);
  });

  it('evaluate without a judge note omits the note line', async () => {
    const c = makeClient({ evaluation: evalFixture({ judgeNote: null }) });
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: { planId: 'plan-1', opsStatus: [op({ id: 'a' })], projectCopyPath: '/c' },
      });
    });
    await flush();
    await act(async () => {
      $('button[data-action="evaluate"]').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="judge-note"]')).toBeNull();
  });

  it('undo re-applies the inverse and clears the applied/eval state', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: {
          planId: 'plan-1',
          opsStatus: [op({ id: 'a', status: 'applied' })],
          projectCopyPath: '/c',
        },
      });
    });
    await flush();
    await act(async () => {
      $('button[data-action="undo"]').click();
    });
    await flush();
    expect(c.calls.find((x) => x.method === 'director.undo')?.args).toEqual(['plan-1']);
    await act(async () => {
      events.emitDone({
        jobId: 'job-undo',
        result: {
          planId: 'plan-1',
          opsStatus: [op({ id: 'a', status: 'planned' })],
          projectCopyPath: '/c2',
        },
      });
    });
    await flush();
    // After undo the evaluate/undo controls are gone (applied=false).
    expect(container.querySelector('button[data-action="evaluate"]')).toBeNull();
    expect($('[data-testid="status-a"]').textContent).toBe('Planned');
  });

  it('(F6) Adjust & re-plan pre-fills the prior goal and keeps the prior plan visible', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })], 'first goal'));
    await act(async () => {
      $('button[data-action="adjust"]').click();
    });
    await flush();
    // Prior goal carried into the box; prior plan still on screen.
    expect(($('textarea[data-action="goal"]') as HTMLTextAreaElement).value).toBe('first goal');
    expect($('[data-testid="plan-summary"]').textContent).toBe('1 trim');
    // Re-plan: prior plan stays until the new job.done lands.
    await clickPlan();
    expect($('[data-testid="plan-summary"]').textContent).toBe('1 trim'); // still old
    await emitPlanDone(c, planFixture([op({ id: 'b', kind: 'reorder' })], 'first goal'));
    expect($('[data-testid="plan-summary"]').textContent).toBe('1 reorder');
    // Re-plan keeps the SAME videoId (carried from the prior plan).
    const planCalls = c.calls.filter((x) => x.method === 'director.plan');
    expect(planCalls[1].args[0]).toBe('vid-1');
  });

  it('(F5) op rows are keyboard-focusable with enable/disable + move controls', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim', status: 'dropped' })]));
    const row = $('.director-op[data-op-id="a"]');
    expect(row.getAttribute('tabindex')).toBe('0');
    // Dropped op offers "Enable"; non-dropped offers "Disable".
    expect($('button[data-action="op-disable"][data-op="a"]').textContent).toBe('Enable');
    expect(container.querySelector('button[data-action="op-up"][data-op="a"]')).not.toBeNull();
    expect($('button[data-action="op-down"][data-op="a"]').getAttribute('aria-label')).toBe(
      'Move down',
    );
    // Root has an accessible name.
    expect($('section.director-panel').getAttribute('aria-label')).toBe('AI Director');
  });

  it('non-dropped op offers a Disable control', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim', status: 'planned' })]));
    expect($('button[data-action="op-disable"][data-op="a"]').textContent).toBe('Disable');
  });

  // ---- WU-director-controls: the per-op controls are WIRED (were inert) -------

  it('clicking Disable toggles a planned op to dropped (and back), updating the summary', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim', status: 'planned' })]));
    expect($('[data-testid="status-a"]').textContent).toBe('Planned');
    // Click Disable -> dropped (status row + summary reflect it).
    await act(async () => {
      $('button[data-action="op-disable"][data-op="a"]').click();
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Dropped');
    expect($('.director-op[data-op-id="a"]').getAttribute('data-status')).toBe('dropped');
    expect($('[data-testid="plan-summary"]').textContent).toBe('No changes · 1 dropped op');
    expect($('button[data-action="op-disable"][data-op="a"]').getAttribute('aria-pressed')).toBe(
      'true',
    );
    // Click again -> re-enabled (Enable label, back to planned).
    await act(async () => {
      $('button[data-action="op-disable"][data-op="a"]').click();
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Planned');
    expect($('[data-testid="plan-summary"]').textContent).toBe('1 trim');
  });

  it('re-enabling a dropped op clears its drop reason', async () => {
    const c = makeClient();
    await planTo(
      c,
      planFixture([op({ id: 'a', kind: 'trim', status: 'dropped', statusReason: 'too-long' })]),
    );
    expect($('[data-testid="reason-a"]').textContent).toBe('too-long');
    await act(async () => {
      $('button[data-action="op-disable"][data-op="a"]').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="reason-a"]')).toBeNull();
    expect($('[data-testid="status-a"]').textContent).toBe('Planned');
  });

  it('clicking Move down/up reorders same-kind ops within their group', async () => {
    const c = makeClient();
    await planTo(
      c,
      planFixture([
        op({ id: 'a', kind: 'trim', rationale: 'first' }),
        op({ id: 'b', kind: 'trim', rationale: 'second' }),
      ]),
    );
    const ids = () => $all('.director-op[data-op-id]').map((el) => el.getAttribute('data-op-id'));
    expect(ids()).toEqual(['a', 'b']);
    await act(async () => {
      $('button[data-action="op-down"][data-op="a"]').click();
    });
    await flush();
    expect(ids()).toEqual(['b', 'a']);
    // Move it back up.
    await act(async () => {
      $('button[data-action="op-up"][data-op="a"]').click();
    });
    await flush();
    expect(ids()).toEqual(['a', 'b']);
  });

  it('move buttons are disabled at a same-kind boundary (first/last)', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' }), op({ id: 'b', kind: 'trim' })]));
    // "a" is first of its kind -> up disabled, down enabled.
    expect(($('button[data-action="op-up"][data-op="a"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(($('button[data-action="op-down"][data-op="a"]') as HTMLButtonElement).disabled).toBe(
      false,
    );
    // "b" is last of its kind -> down disabled.
    expect(($('button[data-action="op-down"][data-op="b"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
    // A disabled boundary button carries an explanatory title (reason).
    expect($('button[data-action="op-up"][data-op="a"]').getAttribute('title')).toMatch(
      /first of its kind/i,
    );
  });

  it('keyboard: Enter on the focusable row toggles the op; Space does too', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim', status: 'planned' })]));
    const row = $('.director-op[data-op-id="a"]');
    await act(async () => {
      row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Dropped');
    // Space toggles back.
    await act(async () => {
      row.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Planned');
  });

  it('keyboard: ArrowDown/ArrowUp on the row reorder same-kind ops', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' }), op({ id: 'b', kind: 'trim' })]));
    const ids = () => $all('.director-op[data-op-id]').map((el) => el.getAttribute('data-op-id'));
    await act(async () => {
      $('.director-op[data-op-id="a"]').dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }),
      );
    });
    await flush();
    expect(ids()).toEqual(['b', 'a']);
    await act(async () => {
      $('.director-op[data-op-id="a"]').dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }),
      );
    });
    await flush();
    expect(ids()).toEqual(['a', 'b']);
  });

  it('keyboard: an unhandled key, and a move key at a boundary, are no-ops', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' }), op({ id: 'b', kind: 'trim' })]));
    const ids = () => $all('.director-op[data-op-id]').map((el) => el.getAttribute('data-op-id'));
    const rowA = $('.director-op[data-op-id="a"]');
    // Unhandled key: nothing changes.
    await act(async () => {
      rowA.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', bubbles: true }));
    });
    await flush();
    expect(ids()).toEqual(['a', 'b']);
    expect($('[data-testid="status-a"]').textContent).toBe('Planned');
    // ArrowUp on the first-of-kind op is a boundary no-op.
    await act(async () => {
      rowA.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    });
    await flush();
    expect(ids()).toEqual(['a', 'b']);
    // ArrowDown on the last-of-kind op is a boundary no-op.
    await act(async () => {
      $('.director-op[data-op-id="b"]').dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }),
      );
    });
    await flush();
    expect(ids()).toEqual(['a', 'b']);
  });

  it('a keydown bubbling from a child button is NOT hijacked by the row handler', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim', status: 'planned' })]));
    // Pressing Enter while a Move button is focused must keep the BUTTON's own
    // native activation — the row's onKeyDown must ignore the bubbled event
    // (target !== currentTarget), so the op is NOT toggled by the row.
    await act(async () => {
      $('button[data-action="op-up"][data-op="a"]').dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Planned');
  });

  it('controls are disabled (and keyboard inert) after the plan is applied', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' }), op({ id: 'b', kind: 'trim' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: {
          planId: 'plan-1',
          opsStatus: [op({ id: 'a', status: 'applied' }), op({ id: 'b', status: 'applied' })],
          projectCopyPath: '/c',
        },
      });
    });
    await flush();
    // Post-apply: the Disable control is disabled with an explanatory title.
    const disable = $('button[data-action="op-disable"][data-op="a"]') as HTMLButtonElement;
    expect(disable.disabled).toBe(true);
    expect(disable.getAttribute('title')).toMatch(/before you apply/i);
    // Keyboard activation is inert post-apply (status unchanged).
    await act(async () => {
      $('.director-op[data-op-id="a"]').dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Applied');
  });

  it('move controls render Lucide-style inline SVG icons (no emoji/glyph)', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })]));
    const upBtn = $('button[data-action="op-up"][data-op="a"]');
    const svg = upBtn.querySelector('svg.director-op__icon');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
    expect(svg?.querySelectorAll('path').length).toBe(2);
    // The legacy arrow glyph is gone (accessible name comes from aria-label).
    expect(upBtn.textContent).not.toContain('↑');
    expect(upBtn.getAttribute('aria-label')).toBe('Move up');
  });

  it('progress events for the active job update the SR region', async () => {
    const c = makeClient();
    await mount(c);
    await setGoal('go');
    await clickPlan();
    await act(async () => {
      events.emitProgress({ jobId: 'job-plan', pct: 40, message: 'Understanding…' });
    });
    await flush();
    expect($('[data-section="progress"]').textContent).toBe('Understanding…');
    // A progress event for a DIFFERENT job is ignored.
    await act(async () => {
      events.emitProgress({ jobId: 'other', pct: 99, message: 'nope' });
    });
    await flush();
    expect($('[data-section="progress"]').textContent).toBe('Understanding…');
  });

  it('a job.done for a stale/unknown job is ignored', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })]));
    // No pending job now; a stray done must not throw or change the plan.
    await act(async () => {
      events.emitDone({
        jobId: 'ghost',
        result: { planId: 'x', editPlan: planFixture([]), preview: '' },
      });
    });
    await flush();
    expect($('[data-testid="plan-summary"]').textContent).toBe('1 trim');
  });

  it('a malformed plan job.done surfaces an error and keeps no plan', async () => {
    const c = makeClient();
    await mount(c);
    await setGoal('go');
    await clickPlan();
    await act(async () => {
      events.emitDone({ jobId: 'job-plan', result: { nope: true } });
    });
    await flush();
    expect($('p.error').textContent).toBe('Planning returned an unexpected result.');
    expect(container.querySelector('[data-testid="plan-summary"]')).toBeNull();
  });

  it('a malformed apply job.done surfaces an apply error', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({ jobId: 'job-apply', result: { bad: 1 } });
    });
    await flush();
    expect($('p.error').textContent).toBe('Apply returned an unexpected result.');
  });

  it('a malformed undo job.done surfaces an undo error', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: { planId: 'plan-1', opsStatus: [op({ id: 'a' })], projectCopyPath: '/c' },
      });
    });
    await flush();
    await act(async () => {
      $('button[data-action="undo"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({ jobId: 'job-undo', result: { bad: 1 } });
    });
    await flush();
    expect($('p.error').textContent).toBe('Undo returned an unexpected result.');
  });

  it('director.plan rejection surfaces an error and clears busy', async () => {
    const c = makeClient({ rejectPlan: true });
    await mount(c);
    await setGoal('go');
    await clickPlan();
    expect($('p.error').textContent).toBe('plan failed');
    expect(($('button[data-action="plan"]') as HTMLButtonElement).disabled).toBe(false);
    expect($('[data-section="progress"]').textContent).toBe('');
  });

  it('previewCost resolving falsy yields no cost banner (?? null arm)', async () => {
    const c = makeClient({ falsyPreview: true });
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })]));
    expect(container.querySelector('.director-cost')).toBeNull();
    expect($('[data-testid="plan-summary"]').textContent).toBe('1 trim');
  });

  it('evaluate resolving falsy clears the eval view (?? null arm)', async () => {
    const c = makeClient({ falsyEvaluate: true });
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: { planId: 'plan-1', opsStatus: [op({ id: 'a' })], projectCopyPath: '/c' },
      });
    });
    await flush();
    await act(async () => {
      $('button[data-action="evaluate"]').click();
    });
    await flush();
    expect(container.querySelector('.director-eval')).toBeNull();
  });

  it('apply opsStatus missing an op id falls back to the planned op (?? o arm)', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' }), op({ id: 'b', kind: 'reorder' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    // Apply result only carries a status for op "a"; op "b" falls back to planned.
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: {
          planId: 'plan-1',
          opsStatus: [op({ id: 'a', kind: 'trim', status: 'applied' })],
          projectCopyPath: '/c',
        },
      });
    });
    await flush();
    expect($('[data-testid="status-a"]').textContent).toBe('Applied');
    expect($('[data-testid="status-b"]').textContent).toBe('Planned');
  });

  it('apply with no preview loaded sends an undefined confirmBudget (?. chain)', async () => {
    const c = makeClient({ preview: { perFunction: [] } });
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    expect(c.calls.find((x) => x.method === 'director.apply')?.args).toEqual(['plan-1', undefined]);
  });

  it('previewCost rejection surfaces an error (plan still shows)', async () => {
    const c = makeClient({ rejectPreview: true });
    await planTo(c, planFixture([op({ id: 'a', kind: 'trim' })]));
    expect($('p.error').textContent).toBe('preview failed');
    expect($('[data-testid="plan-summary"]').textContent).toBe('1 trim');
    expect(container.querySelector('.director-cost')).toBeNull();
  });

  it('apply rejection surfaces an error and clears busy', async () => {
    const c = makeClient({ rejectApply: true });
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    expect($('p.error').textContent).toBe('apply failed');
    expect($('[data-section="progress"]').textContent).toBe('');
  });

  it('undo rejection surfaces an error', async () => {
    const c = makeClient({ rejectUndo: true });
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: { planId: 'plan-1', opsStatus: [op({ id: 'a' })], projectCopyPath: '/c' },
      });
    });
    await flush();
    await act(async () => {
      $('button[data-action="undo"]').click();
    });
    await flush();
    expect($('p.error').textContent).toBe('undo failed');
  });

  it('evaluate rejection surfaces an error', async () => {
    const c = makeClient({ rejectEvaluate: true });
    await planTo(c, planFixture([op({ id: 'a' })]));
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    await act(async () => {
      events.emitDone({
        jobId: 'job-apply',
        result: { planId: 'plan-1', opsStatus: [op({ id: 'a' })], projectCopyPath: '/c' },
      });
    });
    await flush();
    await act(async () => {
      $('button[data-action="evaluate"]').click();
    });
    await flush();
    expect($('p.error').textContent).toBe('evaluate failed');
  });

  it('clicking Apply/Adjust/Evaluate/Undo while busy is a no-op (guards)', async () => {
    const c = makeClient();
    await planTo(c, planFixture([op({ id: 'a' })]));
    // Enter a busy state via apply (no job.done yet -> still busy).
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    const applyCallsBefore = c.calls.filter((x) => x.method === 'director.apply').length;
    // A second apply click while busy must not fire again.
    await act(async () => {
      $('button[data-action="apply"]').click();
    });
    await flush();
    expect(c.calls.filter((x) => x.method === 'director.apply').length).toBe(applyCallsBefore);
    // Adjust while busy is a no-op too (goal unchanged from blank-after-plan).
    const goalBefore = ($('textarea[data-action="goal"]') as HTMLTextAreaElement).value;
    await act(async () => {
      $('button[data-action="adjust"]').click();
    });
    await flush();
    expect(($('textarea[data-action="goal"]') as HTMLTextAreaElement).value).toBe(goalBefore);
  });

  it('unsubscribes from the job-event bus on unmount', async () => {
    const c = makeClient();
    await mount(c);
    expect(events.progressSubs).toBe(1);
    expect(events.doneSubs).toBe(1);
    await act(async () => {
      root.unmount();
    });
    expect(events.progressSubs).toBe(0);
    expect(events.doneSubs).toBe(0);
    // Re-mount so afterEach's unmount is a no-op-safe double (guard).
    root = createRoot(container);
  });
});
