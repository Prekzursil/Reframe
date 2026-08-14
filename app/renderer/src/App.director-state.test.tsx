// App.director-state.test.tsx — F32: an unapplied Director plan must survive a
// top-level tab switch.
//
// WHY THIS FILE EXISTS SEPARATELY FROM App.test.tsx: that suite mocks
// `./views/Director` (App.test.tsx:102) with a marker div, so the whole Director
// subtree — and therefore this defect — is invisible to it. Here the REAL Director
// view (and the real composed DirectorPanel) mounts, so the route switch genuinely
// unmounts the subtree the way it does in the shipped app.
//
// The heavy SIBLING views (Library / Make Shorts / Settings) are still stubbed:
// their realness is irrelevant to "does Director state survive leaving the tab",
// and stubbing them keeps a setup failure from masquerading as the defect.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { DirectorEditPlan, DirectorOp, DirectorPreview, Video } from './lib/rpc';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- fixtures ---------------------------------------------------------------

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    id: 'vid-1',
    path: '/movies/talk.mp4',
    title: 'Talk',
    addedAt: '2026-06-11T00:00:00Z',
    durationSec: 600,
    hasTranscript: false,
    ...over,
  };
}

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

const PLAN: DirectorEditPlan = {
  planId: 'plan-1',
  videoId: 'vid-1',
  goal: 'tighten the pacing',
  sourceHash: 'h',
  ops: [op({ id: 'op-1', kind: 'trim' }), op({ id: 'op-2', kind: 'reorder' })],
  inverse: [],
};

/** `summarizePlan(PLAN)` as first planned (both ops enabled). */
const PLANNED_SUMMARY = '1 trim, 1 reorder';
/** …and after op-1 is dropped — the witness that the REVIEW DECISION survived. */
const REVIEWED_SUMMARY = '1 reorder · 1 dropped op';

// `route` is an OBJECT on the wire (ai_job.py `_route_json`), never a string —
// mirror the sidecar, not the declared type.
const PREVIEW: DirectorPreview = {
  perFunction: [
    {
      function: 'editPlan',
      route: { providers: ['groq'], degradeChain: [], cacheHit: false, willEgress: true },
      costEst: 10,
      willEgress: true,
      cacheHit: false,
      cacheKey: 'CK-TEXT',
    },
  ],
};

// ---- mocks -----------------------------------------------------------------

const rpcMock = vi.fn();
const libraryListMock = vi.fn();
const batchListMock = vi.fn();
const setRoutingPolicyMock = vi.fn();
const settingsGetMock = vi.fn();
const settingsSetMock = vi.fn();
const cuesMock = vi.fn();
const planMock = vi.fn();
const previewCostMock = vi.fn();

/** The real preload job-event relay, driven by the test. */
const doneCbs = new Set<(e: { jobId: string; result?: unknown }) => void>();
function emitDone(event: { jobId: string; result?: unknown }): void {
  for (const cb of doneCbs) cb(event);
}

vi.mock('./lib/rpc', () => ({
  rpc: (...a: unknown[]) => rpcMock(...a),
  hasApi: () => true,
  onProgress: () => () => undefined,
  onJobDone: (cb: (e: { jobId: string; result?: unknown }) => void) => {
    doneCbs.add(cb);
    return () => doneCbs.delete(cb);
  },
  // REQUIRED since Refine lands on the Workspace (owner-locked G-7 invariant 2):
  // this file mocks neither ./views/Edit nor ./views/Workspace, so it now mounts the
  // REAL Workspace, which subscribes to `proxy.state` on mount. Without this export
  // every test here dies with "No onProxyState export is defined on the ./lib/rpc
  // mock" — a mock gap exposed by the routing change, not a defect in either.
  onProxyState: () => () => undefined,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
    batch: { list: (...a: unknown[]) => batchListMock(...a) },
    models: { setRoutingPolicy: (...a: unknown[]) => setRoutingPolicyMock(...a) },
    settings: {
      get: (...a: unknown[]) => settingsGetMock(...a),
      set: (...a: unknown[]) => settingsSetMock(...a),
    },
    captions: { cues: (...a: unknown[]) => cuesMock(...a) },
    director: {
      plan: (...a: unknown[]) => planMock(...a),
      previewCost: (...a: unknown[]) => previewCostMock(...a),
    },
  },
}));

// Sibling views stubbed (they own their own suites); `./views/Director` is
// DELIBERATELY NOT mocked — mocking it is what blinds App.test.tsx to this defect.
vi.mock('./views/Library', () => ({
  Library: ({ onOpen }: { onOpen: (v: Video) => void }) => (
    <div data-testid="library">
      <button type="button" onClick={() => onOpen(makeVideo())}>
        open-video
      </button>
      {/* A SECOND video, so the per-video isolation rule can be exercised through
          the real shell + provider rather than only as a unit test. */}
      <button type="button" onClick={() => onOpen(makeVideo({ id: 'vid-2', title: 'Other' }))}>
        open-other-video
      </button>
    </div>
  ),
}));
vi.mock('./views/MakeShorts', () => ({ MakeShorts: () => <div data-testid="makeshorts" /> }));
vi.mock('./views/Settings', () => ({ Settings: () => <div data-testid="settings" /> }));
vi.mock('./components/JobQueue', () => ({
  JobQueue: () => <div />,
  JOBQUEUE_PANEL_ID: 'jobqueue-panel',
}));
vi.mock('./components/SidecarBanner', () => ({ SidecarBanner: () => <div /> }));
// Same doctrine as the sibling views above, applied to a Workspace feature panel
// this suite never exercises. `open-video` routes through the real Edit ->
// Workspace, whose panel module graph is resolved during the test; adding the
// v1.5 Transcript-edit panel pushed the FIRST case past the 5s default timeout
// (measured: 3/3 fail at the default, 3/3 pass at --testTimeout=30000, so it is a
// transform-cost cliff, not a behaviour break). Stubbing the panel keeps this
// suite measuring Director state instead of module-graph cost. UNVERIFIED whether
// CI's Linux runner would have crossed the same cliff — settled by reverting this
// mock and reading the gate-tests-coverage vitest step; the stub is correct either
// way because the panel is irrelevant here.
vi.mock('./features/TranscriptEditor', () => ({ default: () => <div /> }));
// CORRECTION to the paragraph above, measured 2026-08-10 while remediating the
// W21 review. A review objection proposed adding the same stub for the Dub panel
// (also `lazy()` at `views/Workspace.tsx:42`) on the premise that a lazy sibling
// panel's module graph is paid for by this suite. An executable probe REFUTES the
// module-EVALUATION half of that premise for BOTH panels: a `throw` planted at
// module top-level in `features/Dub.tsx` did NOT fire here, and the same probe in
// `features/TranscriptEditor.tsx` (with its mock above temporarily disabled) did
// NOT fire either — while the identical Dub probe DID fire in
// `features/Dub.test.tsx`, so the detector is known-good in the loading state.
// Neither panel is evaluated by this suite; `lazy()` defers the import until the
// tab is rendered, and this suite never leaves the Director tab. A Dub stub would
// therefore have saved nothing, so none was added. (Scope: EVALUATION is what the
// probe measures. Whether Vite still TRANSFORMS an unevaluated dynamic import is
// NOT measured here — the timings could not settle it, see below.)
//
// The timeout risk is real anyway, and its real cause is machine load, not this
// file's imports. Measured on this box, three runs per configuration, first case:
// without a Dub stub 2607 / 1542 / 1158 ms, with one 3438 / 3005 / 2770 ms — the
// spread is larger than any effect and the ordering inverts, i.e. the single
// 3628ms datapoint the objection cited is a load artifact, exactly like the
// earlier 3/3 timeout. Against a 5000ms default that is a coin-flip on a busy
// runner, so the margin is removed explicitly instead of by proxy.
vi.setConfig({ testTimeout: 30_000 });

import { App } from './App';

// ---- harness ---------------------------------------------------------------

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  doneCbs.clear();
  rpcMock.mockReset();
  rpcMock.mockResolvedValue({});
  libraryListMock.mockReset();
  libraryListMock.mockResolvedValue({ videos: [] });
  batchListMock.mockReset();
  batchListMock.mockResolvedValue({ batches: [] });
  setRoutingPolicyMock.mockReset();
  setRoutingPolicyMock.mockResolvedValue({ routingPolicy: { global: 'local', overrides: {} } });
  settingsGetMock.mockReset();
  // Keep the focus-trapped first-run tour CLOSED; otherwise it sits over the panel.
  settingsGetMock.mockResolvedValue({ directorOnboardingSeen: true });
  settingsSetMock.mockReset();
  settingsSetMock.mockResolvedValue({});
  cuesMock.mockReset();
  cuesMock.mockResolvedValue({ cues: [] });
  planMock.mockReset();
  planMock.mockResolvedValue({ jobId: 'job-plan' });
  previewCostMock.mockReset();
  previewCostMock.mockResolvedValue(PREVIEW);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

/**
 * Flush pending work. Uses a MACROTASK (`setTimeout 0`), not just microtasks: the
 * Director route is a `lazy(() => import('./views/Director'))`, and a microtask-only
 * flush leaves the Suspense fallback ("Loading…") on screen — which then fails as
 * "no element for textarea[data-action=goal]" and looks exactly like the defect.
 */
async function flush(times = 4): Promise<void> {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

function $(sel: string): HTMLElement {
  const el = container.querySelector(sel);
  if (!el) throw new Error(`no element for ${sel}`);
  return el as HTMLElement;
}

function tab(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.toptab'));
  const found = btns.find((b) => b.querySelector('.toptab__label')?.textContent === label);
  if (!found) throw new Error(`tab "${label}" not found`);
  return found;
}

/**
 * L5 G-6: Director is no longer a rail destination — it is Produce's second MODE.
 * Reaching it is now two clicks (Produce, then Director), and leaving Produce
 * unmounts it exactly as leaving the old tab did, so the F32 defect this suite
 * measures is unchanged.
 */
function modeTab(label: string): HTMLButtonElement {
  const btns = Array.from(
    container.querySelectorAll<HTMLButtonElement>('.app__destination [role="tab"]'),
  );
  const found = btns.find((b) => b.textContent === label);
  if (!found) throw new Error(`mode tab "${label}" not found`);
  return found;
}

/** Navigate to Produce, then its Director mode. */
async function goToDirector(): Promise<void> {
  await click(tab('Produce'));
  await click(modeTab('Director'));
}

async function click(el: HTMLElement): Promise<void> {
  await act(async () => {
    el.click();
  });
  await flush();
}

/** Find a button in the Library stub by its exact text. */
function buttonByText(text: string): HTMLElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('button'));
  const found = btns.find((b) => b.textContent === text);
  if (!found) throw new Error(`button "${text}" not found`);
  return found;
}

async function typeGoal(text: string): Promise<void> {
  const ta = $('textarea[data-action="goal"]') as HTMLTextAreaElement;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value',
  )?.set;
  await act(async () => {
    setter?.call(ta, text);
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await flush(1);
}

/**
 * Drive the shell to a REVIEWED Director plan: open a video, enter the Director
 * tab, plan, land the plan on `job.done`, then drop one op.
 */
async function planAndReview(): Promise<void> {
  // Warm the lazy chunk's module cache. Without this the `lazy()` import stays
  // pending for the whole test and every assertion fails on the Suspense fallback.
  await import('./views/Director');
  await act(async () => {
    root.render(<App />);
  });
  await flush();
  // Open a video (routes into Edit), then switch to the Director tab.
  await click(buttonByText('open-video'));
  await goToDirector();
  // The Director route is lazy — give Suspense room to resolve it.
  await flush(6);
  await typeGoal(PLAN.goal);
  await click($('button[data-action="plan"]'));
  await act(async () => {
    emitDone({ jobId: 'job-plan', result: { planId: PLAN.planId, editPlan: PLAN, preview: '{}' } });
  });
  await flush();
  // Precondition (passes BOTH before and after the fix): the storyboard is up.
  expect($('[data-testid="plan-summary"]').textContent).toBe(PLANNED_SUMMARY);
  // One review decision: drop op-1. The plain-language summary re-derives from the
  // edited plan, so it is itself a witness that the decision landed.
  await click($('button[data-action="op-disable"][data-op="op-1"]'));
  expect($('.director-op[data-op-id="op-1"]').getAttribute('data-status')).toBe('dropped');
  expect($('[data-testid="plan-summary"]').textContent).toBe(REVIEWED_SUMMARY);
}

// ---- the test --------------------------------------------------------------

describe('App — Director session state across a tab switch (F32)', () => {
  it('keeps an unapplied plan, its goal and its review decisions when the user leaves and returns', async () => {
    await planAndReview();

    // Leave the Director tab and come back. This UNMOUNTS the whole Director
    // subtree (App's renderRoute switch), which is what used to discard the plan.
    await click(tab('Library'));
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="plan-summary"]')).toBeNull();
    await goToDirector();
    await flush(6);

    // The plan, the goal it was made from, and the review decision all survive.
    // Asserting the REVIEWED summary (not the as-planned one) is what proves the
    // keep/drop decision came back too, rather than just a pristine re-fetched plan.
    expect($('[data-testid="plan-summary"]').textContent).toBe(REVIEWED_SUMMARY);
    expect(($('textarea[data-action="goal"]') as HTMLTextAreaElement).value).toBe(PLAN.goal);
    expect($('.director-op[data-op-id="op-1"]').getAttribute('data-status')).toBe('dropped');
    expect($('.director-op[data-op-id="op-2"]').getAttribute('data-status')).toBe('planned');
    // director.plan was NOT re-run: recovery must not cost another plan pass.
    expect(planMock).toHaveBeenCalledTimes(1);
  });

  it('re-fetches the cost/egress banner for a restored plan (preview is transient)', async () => {
    await planAndReview();
    expect(container.querySelector('.director-cost')).not.toBeNull();

    await click(tab('Library'));
    await goToDirector();
    await flush(6);

    // `preview` is deliberately NOT hoisted (it is cheaply re-fetchable by planId),
    // so the restored plan must re-request it or the banner + the budget ack that
    // gates Apply would be silently missing after every re-entry.
    expect(container.querySelector('.director-cost')).not.toBeNull();
    expect(previewCostMock).toHaveBeenCalledWith(PLAN.planId);
    expect(previewCostMock.mock.calls.length).toBeGreaterThan(1);
  });

  it('serves a CLEAN Director form when a DIFFERENT video is opened', async () => {
    await planAndReview();

    // Open a different video, then return to Director. vid-1's session must NOT be
    // served for vid-2 — applying it would run vid-1's ops against the wrong source.
    await click(tab('Library'));
    await click(buttonByText('open-other-video'));
    await goToDirector();
    await flush(6);

    expect(container.querySelector('[data-testid="plan-summary"]')).toBeNull();
    expect(($('textarea[data-action="goal"]') as HTMLTextAreaElement).value).toBe('');
  });
});
