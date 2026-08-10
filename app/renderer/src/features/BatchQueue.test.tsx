// BatchQueue.test.tsx — the primary folder→shorts flow + live a11y + resume.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type {
  BatchConsent,
  BatchState,
  BatchSummary,
  DoneEvent,
  ProgressEvent,
  Template,
  Video,
} from '../lib/rpc';

const libListMock = vi.fn();
const tmplListMock = vi.fn();
const batchListMock = vi.fn();
const batchCreateMock = vi.fn();
const batchPlanMock = vi.fn();
const batchStartMock = vi.fn();
const batchStatusMock = vi.fn();
const batchResumeMock = vi.fn();
const batchCancelMock = vi.fn();
const batchDeleteMock = vi.fn();
const settingsGetMock = vi.fn();

let progressCbs: Array<(e: ProgressEvent) => void> = [];
// Typed as the REAL bridge types it: `window.api.onJobDone` always relays a
// `{jobId, result?}` payload. The mock previously invoked the callback with no
// argument at all, which is a shape the preload cannot produce and which hid the
// fact that the panel was ignoring `jobId` entirely.
let doneCbs: Array<(e: DoneEvent) => void> = [];
/** Fire `job.done` for a jobId (default: the parent job the tests start). */
function fireJobDone(jobId = 'job-1'): void {
  doneCbs.forEach((c) => c({ jobId }));
}

vi.mock('../lib/rpc', () => ({
  client: {
    library: { list: (...a: unknown[]) => libListMock(...a) },
    templates: { list: (...a: unknown[]) => tmplListMock(...a) },
    batch: {
      list: (...a: unknown[]) => batchListMock(...a),
      create: (...a: unknown[]) => batchCreateMock(...a),
      plan: (...a: unknown[]) => batchPlanMock(...a),
      start: (...a: unknown[]) => batchStartMock(...a),
      status: (...a: unknown[]) => batchStatusMock(...a),
      resume: (...a: unknown[]) => batchResumeMock(...a),
      cancel: (...a: unknown[]) => batchCancelMock(...a),
      delete: (...a: unknown[]) => batchDeleteMock(...a),
    },
    settings: { get: (...a: unknown[]) => settingsGetMock(...a) },
  },
  onProgress: (cb: (e: ProgressEvent) => void) => {
    progressCbs.push(cb);
    return () => {
      progressCbs = progressCbs.filter((c) => c !== cb);
    };
  },
  onJobDone: (cb: (e: DoneEvent) => void) => {
    doneCbs.push(cb);
    return () => {
      doneCbs = doneCbs.filter((c) => c !== cb);
    };
  },
}));

import { BatchQueue, announceTransitions } from './BatchQueue';

const VIDEOS: Video[] = [
  {
    id: 'v1',
    path: '/v1',
    title: 'Episode One',
    addedAt: '',
    durationSec: 60,
    hasTranscript: false,
  },
  {
    id: 'v2',
    path: '/v2',
    title: 'Episode Two',
    addedAt: '',
    durationSec: 60,
    hasTranscript: false,
  },
];
const TEMPLATES: Template[] = [
  { id: 't1', name: 'House style', steps: [], defaultControls: {}, exportTargets: ['tiktok'] },
];

function summary(over: Partial<BatchSummary> = {}): BatchSummary {
  return {
    id: 'bA',
    name: 'Prior run',
    templateId: 't1',
    status: 'partial',
    createdAt: 1,
    counts: { total: 3, done: 1, error: 0, skipped: 0, queued: 2, running: 0, cancelled: 0 },
    ...over,
  };
}

function consent(over: Partial<BatchConsent> = {}): BatchConsent {
  return {
    decisions: [
      {
        videoId: 'v1',
        action: 'run',
        skipReason: null,
        confirmBudget: null,
        willEgress: true,
        cacheHit: false,
      },
      {
        videoId: 'v2',
        action: 'skip',
        skipReason: 'would egress',
        confirmBudget: null,
        willEgress: true,
        cacheHit: false,
      },
    ],
    willRun: 1,
    willSkip: 1,
    costEst: {},
    budget: {},
    ...over,
  };
}

function state(items: BatchState['items'], over: Partial<BatchState> = {}): BatchState {
  return {
    id: 'bNew',
    name: 'Batch run',
    templateId: 't1',
    status: 'running',
    createdAt: 2,
    items,
    ...over,
  };
}

let container: HTMLElement;
let root: Root;

async function render(props: { resumeId?: string } = {}): Promise<void> {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<BatchQueue {...props} />);
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

/**
 * Mount WITHOUT the trailing microtask flush, so the initial `reload()` stays in
 * flight. It MUST assign the module-level `container`/`root` or the shared
 * `afterEach` unmounts the previous test's tree and leaks this one.
 */
function renderPending(): void {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(<BatchQueue />);
  });
}

beforeEach(() => {
  progressCbs = [];
  doneCbs = [];
  libListMock.mockResolvedValue({ videos: VIDEOS });
  tmplListMock.mockResolvedValue({ templates: TEMPLATES });
  batchListMock.mockResolvedValue({ batches: [] });
  batchCreateMock.mockResolvedValue({ batch: state([{ videoId: 'v1', status: 'queued' }]) });
  batchPlanMock.mockResolvedValue({ consent: consent() });
  batchStartMock.mockResolvedValue({ jobId: 'job-1' });
  batchStatusMock.mockResolvedValue({ batch: state([{ videoId: 'v1', status: 'queued' }]) });
  batchResumeMock.mockResolvedValue({ jobId: 'job-2' });
  batchCancelMock.mockResolvedValue({ ok: true });
  batchDeleteMock.mockResolvedValue({ ok: true });
  // The §9.1 budget setting defaults ON (settings_store confirmCloudBudget=True).
  settingsGetMock.mockResolvedValue({ confirmCloudBudget: true });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

function findText(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll('button')].find((b) => b.textContent === text);
}

function clickText(text: string): void {
  const btn = findText(text);
  if (!btn) throw new Error(`button not found: ${text}`);
  act(() => btn.dispatchEvent(new MouseEvent('click', { bubbles: true })));
}

describe('BatchQueue', () => {
  it('loads videos, templates and the incomplete-batch list', async () => {
    batchListMock.mockResolvedValue({ batches: [summary()] });
    await render();
    expect(libListMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain('Episode One');
    expect(container.querySelector('.batch-queue__resume')?.textContent).toContain('Prior run');
    // remaining = 3 - 1 done - 0 skipped = 2
    expect(container.textContent).toContain('2 of 3 left');
  });

  it('renders an empty state instead of a bare Sources legend', async () => {
    // The Sources fieldset was a bare `{videos.map(...)}` with no fallback, so a
    // fresh install rendered `<legend>Sources</legend>` and nothing else.
    libListMock.mockResolvedValue({ videos: [] });
    tmplListMock.mockResolvedValue({ templates: [] });
    await render();
    expect(container.querySelector('.batch-queue__empty')).not.toBeNull();
    // The Template <select> stays mounted (other tests query it directly).
    expect(container.querySelector('select[aria-label="Template"]')).not.toBeNull();
    expect(container.querySelector('.batch-queue__template-hint')).not.toBeNull();
  });

  it('names the unmet precondition behind the disabled Run button', async () => {
    libListMock.mockResolvedValue({ videos: [] });
    tmplListMock.mockResolvedValue({ templates: [] });
    await render();
    const run = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Run batch',
    ) as HTMLButtonElement;
    expect(run.disabled).toBe(true); // PASSES today — proves canRun is genuinely false
    const id = run.getAttribute('aria-describedby');
    expect(id).not.toBeNull();
    // A native `disabled` button is out of the tab order, so the VISIBLE sibling is
    // the real fix; the attribute only ties them together.
    expect(container.querySelector(`#${id}`)?.textContent ?? '').toMatch(/source|template/i);
  });

  it('is busy (not empty) while the initial load is in flight', async () => {
    // `reload` awaits Promise.all, so holding library.list holds the whole load.
    // Today that render is byte-identical to the loaded-but-empty render.
    let release!: (v: { videos: Video[] }) => void;
    libListMock.mockReturnValue(
      new Promise<{ videos: Video[] }>((r) => {
        release = r;
      }),
    );
    renderPending();
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    await act(async () => {
      release({ videos: VIDEOS });
      await Promise.resolve();
      await Promise.resolve();
    });
    // The both-states check: the probe must go from satisfied to unsatisfiable.
    expect(container.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it('clears the busy state when the initial load FAILS', async () => {
    libListMock.mockRejectedValueOnce(new Error('load-bad'));
    await render();
    expect(container.querySelector('[aria-busy="true"]')).toBeNull();
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('load-bad');
  });

  it('disables Run until a source AND template are chosen', async () => {
    await render();
    const run = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Run batch',
    ) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    const run2 = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Run batch',
    ) as HTMLButtonElement;
    expect(run2.disabled).toBe(false);
  });

  it('runs a batch (gate ON): create → plan → consent card → acknowledge → start → rows', async () => {
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    // toggle off + on to cover both toggle branches
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchCreateMock).toHaveBeenCalledWith('Batch run', 't1', ['v1']);
    // §9.1 gate ON: the run/skip split is previewed via batch.plan (no job
    // started) and the consent card mounts with named, attributed skips;
    // batch.start is DEFERRED until the user acknowledges cloud egress.
    expect(batchPlanMock).toHaveBeenCalledWith('bNew', {
      confirmCloudBudget: true,
      acknowledged: false,
    });
    expect(container.querySelector('.batch-consent__split')?.textContent).toContain(
      '1 of 2 sources will run',
    );
    expect(container.querySelector('.batch-consent__skip')?.textContent).toContain('Episode Two');
    expect(batchStartMock).not.toHaveBeenCalled();
    // Acknowledge cloud egress -> start (BOTH flags threaded) -> live rows.
    await act(async () => {
      clickText('Acknowledge cloud egress for this batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchStartMock).toHaveBeenCalledWith('bNew', {
      confirmCloudBudget: true,
      acknowledged: true,
    });
    expect(container.querySelector('.batch-queue__rows')).not.toBeNull();
  });

  it('start with no jobId key skips the status refresh (jobIdOf -> "")', async () => {
    // Gate OFF: Run goes straight to start, exercising the jobId === '' arm.
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    batchStartMock.mockResolvedValueOnce({});
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    batchStatusMock.mockClear();
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
    });
    expect(batchStatusMock).not.toHaveBeenCalled();
  });

  it('start with a non-string jobId is treated as no jobId', async () => {
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    batchStartMock.mockResolvedValueOnce({ jobId: 123 });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    batchStatusMock.mockClear();
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
    });
    expect(batchStatusMock).not.toHaveBeenCalled();
  });

  it('start with a primitive (non-object) result is treated as no jobId', async () => {
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    batchStartMock.mockResolvedValueOnce(null);
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    batchStatusMock.mockClear();
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
    });
    expect(batchStatusMock).not.toHaveBeenCalled();
  });

  it('announces on source-transition only (debounced), not per pct tick', async () => {
    // Gate OFF so Run starts the batch directly and tracks parentJobId = job-1.
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
    });
    const fire = (m: string, pct: number): void =>
      act(() => progressCbs.forEach((c) => c({ jobId: 'job-1', pct, message: m })));
    fire('source 1/2 · A · step 1/2', 10);
    const region = container.querySelector('.batch-livestatus__aggregate');
    expect(region?.textContent).toBe('source 1/2 · A · step 1/2');
    // same source, new pct -> no change
    fire('source 1/2 · A · step 2/2', 40);
    expect(region?.textContent).toBe('source 1/2 · A · step 1/2');
    // new source -> updates
    fire('source 2/2 · B · step 1/2', 60);
    expect(container.querySelector('.batch-livestatus__aggregate')?.textContent).toBe(
      'source 2/2 · B · step 1/2',
    );
  });

  it('refreshes durable state on job.done and announces terminal flips', async () => {
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
    });
    // next status: v1 done, v2 error
    batchStatusMock.mockResolvedValue({
      batch: state(
        [
          { videoId: 'v1', status: 'done' },
          { videoId: 'v2', status: 'error', error: 'boom' },
        ],
        { status: 'partial' },
      ),
    });
    await act(async () => {
      fireJobDone();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-livestatus__log')?.textContent).toContain(
      'Episode One — done',
    );
    expect(container.querySelector('.batch-livestatus__alert')?.textContent).toContain(
      'Episode Two — failed: boom',
    );
  });

  it('job.done with no active batch is a no-op', async () => {
    await render();
    batchStatusMock.mockClear();
    await act(async () => {
      fireJobDone();
      await Promise.resolve();
    });
    expect(batchStatusMock).not.toHaveBeenCalled();
  });

  it('renders skip + error detail tokens on rows', async () => {
    // Gate OFF so Run starts + pulls the status snapshot that carries the tokens.
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    batchStatusMock.mockResolvedValue({
      batch: state([
        { videoId: 'v1', status: 'skipped', skipReason: 'would egress' },
        { videoId: 'v2', status: 'error', error: 'kaboom' },
      ]),
    });
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__row-reason')?.textContent).toBe('would egress');
    expect(container.querySelector('.batch-queue__row-error')?.textContent).toBe('kaboom');
    expect(container.querySelector('.batch-queue__row-status')?.textContent).toBe('Skipped');
  });

  it('resumes an incomplete batch from the list', async () => {
    batchListMock.mockResolvedValue({ batches: [summary()] });
    await render();
    await act(async () => {
      clickText('Resume');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchResumeMock).toHaveBeenCalledWith('bA');
  });

  it('removes an abandoned batch from the resume list', async () => {
    // Every Run click persists a durable record BEFORE the default-ON consent gate,
    // so an abandoned run stays `queued` forever in "Incomplete batches" (and in
    // the tab badge + launch toast) with no in-app removal. `batch.delete` shipped
    // end-to-end; only the affordance was missing.
    batchListMock
      .mockResolvedValueOnce({ batches: [summary({ id: 'bA', status: 'queued' })] })
      .mockResolvedValueOnce({ batches: [] });
    await render();
    await act(async () => {
      clickText('Remove');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchDeleteMock).toHaveBeenCalledWith('bA');
    expect(batchListMock).toHaveBeenCalledTimes(2); // the reload
    expect(container.querySelector('.batch-queue__resume')).toBeNull();
  });

  it('surfaces a remove failure with an Error message (instanceof arm)', async () => {
    batchListMock.mockResolvedValue({ batches: [summary()] });
    batchDeleteMock.mockRejectedValueOnce(new Error('delete-boom'));
    await render();
    await act(async () => {
      clickText('Remove');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('delete-boom');
  });

  it('surfaces a remove failure on a non-Error rejection (Delete failed)', async () => {
    batchListMock.mockResolvedValue({ batches: [summary()] });
    batchDeleteMock.mockRejectedValueOnce('x');
    await render();
    await act(async () => {
      clickText('Remove');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('Delete failed');
  });

  it('surfaces a refused resume instead of clobbering the live progress gate', async () => {
    // The sidecar refuses a resume while a parent job is still live and answers
    // with the {jobId: null} no-op shape. Two things must hold: the panel must NOT
    // overwrite the tracked parent jobId with '' (that makes the onProgress gate
    // drop every event for the run that IS in flight, freezing the bar and the
    // a11y announcer), and the click must not be silently dead.
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    batchListMock.mockResolvedValue({ batches: [summary()] });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
    });
    const barNow = (): string | null | undefined =>
      container
        .querySelector('.batch-queue__live [role="progressbar"]')
        ?.getAttribute('aria-valuenow');
    act(() =>
      progressCbs.forEach((c) => c({ jobId: 'job-1', pct: 44, message: 'source 1/2 · A' })),
    );
    expect(barNow()).toBe('44'); // PASSES today — proves the live gate tracks job-1
    batchResumeMock.mockResolvedValueOnce({ jobId: null, status: 'running' });
    await act(async () => {
      clickText('Resume');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const notice = container.querySelector('.batch-queue__notice');
    expect(notice).not.toBeNull();
    expect(notice?.textContent).toContain('already running');
    // ...and the live run's progress still applies.
    act(() =>
      progressCbs.forEach((c) => c({ jobId: 'job-1', pct: 66, message: 'source 2/2 · B' })),
    );
    expect(barNow()).toBe('66');
  });

  it('deep-links a resume on mount via resumeId', async () => {
    await render({ resumeId: 'bZ' });
    expect(batchResumeMock).toHaveBeenCalledWith('bZ');
  });

  it('surfaces load / run / status / resume failures', async () => {
    libListMock.mockRejectedValueOnce(new Error('load-bad'));
    await render();
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('load-bad');
  });

  it('shows a generic load error on non-Error rejection', async () => {
    libListMock.mockRejectedValueOnce('x');
    await render();
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('Failed to load');
  });

  it('surfaces a run failure', async () => {
    batchCreateMock.mockRejectedValueOnce('x');
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('Run failed');
  });

  it('surfaces a status failure during run', async () => {
    // Gate OFF so Run reaches the status refresh whose rejection sets the error.
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    batchStatusMock.mockRejectedValueOnce('x');
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('Status failed');
  });

  it('surfaces a resume failure', async () => {
    batchResumeMock.mockRejectedValueOnce('x');
    await render({ resumeId: 'bZ' });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('Resume failed');
  });

  it('a progress event after a batch exists updates the live pct bar', async () => {
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() =>
      progressCbs.forEach((c) => c({ jobId: 'job-1', pct: 73, message: 'source 1/1 · A' })),
    );
    const bar = container.querySelector('.batch-queue__live [role="progressbar"]');
    expect(bar?.getAttribute('aria-valuenow')).toBe('73');
  });

  it('keeps the last live pct when the terminal status snapshot omits it', async () => {
    // `pct` is a live-ONLY overlay: `_merge_live_status` (batch.py) adds nothing
    // once the parent job is finished, so the terminal `batch.status` snapshot has
    // no pct and the bar fell back to `pct ?? 0` — width 0% / aria-valuenow="0"
    // beside its own "done" label and a full row of terminal tokens.
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
    });
    const barNow = (): string | null | undefined =>
      container
        .querySelector('.batch-queue__live [role="progressbar"]')
        ?.getAttribute('aria-valuenow');
    act(() => progressCbs.forEach((c) => c({ jobId: 'job-1', pct: 100, message: 'done' })));
    expect(barNow()).toBe('100'); // PASSES today — proves the live overlay arrived
    batchStatusMock.mockResolvedValue({
      batch: state([{ videoId: 'v1', status: 'done' }], { status: 'done' }),
    });
    await act(async () => {
      fireJobDone();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(barNow()).toBe('100'); // FAILS today with "0"
  });

  it('surfaces a status failure with an Error message (instanceof arm)', async () => {
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    batchStatusMock.mockRejectedValueOnce(new Error('status-boom'));
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('status-boom');
  });

  it('a progress event before any batch is IGNORED (no tracked parent jobId)', async () => {
    await render();
    expect(container.querySelector('.batch-queue__live')).toBeNull();
    // No batch has started, so parentJobIdRef is '' — the guard drops every event
    // (an untracked jobId must never move the aggregate or the pct bar).
    act(() => progressCbs.forEach((c) => c({ jobId: 'x', pct: 50, message: 'source 1/1 · A' })));
    expect(container.querySelector('.batch-livestatus__aggregate')?.textContent).toBe('');
    expect(container.querySelector('.batch-queue__live')).toBeNull();
  });

  it('ignores a foreign sub-job progress event but applies the parent batch jobId', async () => {
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    // A per-source SUB-job (its own jobId, local 0-100 pct) must NOT hijack the
    // aggregate pct bar or the a11y announcement.
    const barNow = (): string | null | undefined =>
      container
        .querySelector('.batch-queue__live [role="progressbar"]')
        ?.getAttribute('aria-valuenow');
    act(() => progressCbs.forEach((c) => c({ jobId: 'sub-9', pct: 88, message: 'reframe 88%' })));
    expect(barNow()).not.toBe('88');
    expect(container.querySelector('.batch-livestatus__aggregate')?.textContent).not.toBe(
      'reframe 88%',
    );
    // The PARENT batch jobId (job-1) does apply.
    act(() =>
      progressCbs.forEach((c) =>
        c({ jobId: 'job-1', pct: 42, message: 'source 1/2 · A · step 1/2' }),
      ),
    );
    expect(barNow()).toBe('42');
    expect(container.querySelector('.batch-livestatus__aggregate')?.textContent).toBe(
      'source 1/2 · A · step 1/2',
    );
  });

  it('threads confirmCloudBudget:false when the user disabled the budget gate', async () => {
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchStartMock).toHaveBeenCalledWith('bNew', { confirmCloudBudget: false });
  });

  it('tracks the resumed run parent jobId so its progress applies (stale ignored)', async () => {
    batchListMock.mockResolvedValue({ batches: [summary()] });
    batchStatusMock.mockResolvedValue({ batch: state([{ videoId: 'v1', status: 'running' }]) });
    await render();
    await act(async () => {
      clickText('Resume');
      await Promise.resolve();
      await Promise.resolve();
    });
    const barNow = (): string | null | undefined =>
      container
        .querySelector('.batch-queue__live [role="progressbar"]')
        ?.getAttribute('aria-valuenow');
    // A stale prior-run jobId is ignored...
    act(() => progressCbs.forEach((c) => c({ jobId: 'job-1', pct: 5, message: 'stale' })));
    expect(barNow()).not.toBe('5');
    // ...the resumed run's jobId (job-2) applies.
    act(() =>
      progressCbs.forEach((c) => c({ jobId: 'job-2', pct: 61, message: 'source 1/1 · A' })),
    );
    expect(barNow()).toBe('61');
  });

  it('a tracked-jobId progress event before the first status snapshot is safely dropped (batch null)', async () => {
    // resume() sets the parent jobId BEFORE its status snapshot populates `batch`.
    // A matching progress event in that window passes the jobId gate but must hit
    // the `batch ? … : prev` null-guard (no malformed batch, no live panel).
    batchListMock.mockResolvedValue({ batches: [summary()] });
    let resolveStatus!: (v: { batch: BatchState }) => void;
    batchStatusMock.mockReturnValue(
      new Promise<{ batch: BatchState }>((r) => {
        resolveStatus = r;
      }),
    );
    await render();
    await act(async () => {
      clickText('Resume');
      await Promise.resolve();
      await Promise.resolve();
    });
    // status is still pending -> batch is null (no live panel yet).
    expect(container.querySelector('.batch-queue__live')).toBeNull();
    act(() => progressCbs.forEach((c) => c({ jobId: 'job-2', pct: 30, message: 'x' })));
    expect(container.querySelector('.batch-queue__live')).toBeNull();
    // Let the status resolve so the flow completes cleanly.
    await act(async () => {
      resolveStatus({ batch: state([{ videoId: 'v1', status: 'running' }]) });
      await Promise.resolve();
      await Promise.resolve();
    });
  });

  it('surfaces a run failure with an Error message (instanceof arm)', async () => {
    batchCreateMock.mockRejectedValueOnce(new Error('create-boom'));
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('create-boom');
  });

  it('surfaces a resume failure with an Error message (instanceof arm)', async () => {
    batchResumeMock.mockRejectedValueOnce(new Error('resume-boom'));
    await render({ resumeId: 'bZ' });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('resume-boom');
  });

  it('uses the template chosen from the select when running', async () => {
    tmplListMock.mockResolvedValue({
      templates: [
        { id: 't1', name: 'House style', steps: [], defaultControls: {}, exportTargets: [] },
        { id: 't2', name: 'Captioned', steps: [], defaultControls: {}, exportTargets: [] },
      ],
    });
    await render();
    const select = container.querySelector('select[aria-label="Template"]') as HTMLSelectElement;
    const selSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')!
      .set!;
    act(() => {
      selSetter.call(select, 't2');
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
    });
    expect(batchCreateMock).toHaveBeenCalledWith('Batch run', 't2', ['v1']);
  });

  it('keeps the default template when none load (empty list)', async () => {
    tmplListMock.mockResolvedValue({ templates: [] });
    await render();
    const select = container.querySelector('select[aria-label="Template"]') as HTMLSelectElement;
    expect(select.options.length).toBe(0);
  });

  async function runToConsentCard(): Promise<void> {
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it('surfaces an acknowledge/start failure with an Error message (instanceof arm)', async () => {
    batchStartMock.mockRejectedValueOnce(new Error('ack-boom'));
    await runToConsentCard();
    expect(batchStartMock).not.toHaveBeenCalled();
    await act(async () => {
      clickText('Acknowledge cloud egress for this batch');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('ack-boom');
  });

  it('surfaces an acknowledge/start failure on a non-Error rejection (Run failed)', async () => {
    batchStartMock.mockRejectedValueOnce('x');
    await runToConsentCard();
    await act(async () => {
      clickText('Acknowledge cloud egress for this batch');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('Run failed');
  });

  it('keeps the default-ON gate when settings.get rejects (consent card still shown)', async () => {
    // The mount read of the §9.1 setting fails -> the fail-safe keeps the gate ON,
    // so Run still previews the consent split and defers batch.start.
    settingsGetMock.mockRejectedValueOnce(new Error('no-settings'));
    await runToConsentCard();
    expect(batchPlanMock).toHaveBeenCalledWith('bNew', {
      confirmCloudBudget: true,
      acknowledged: false,
    });
    expect(container.querySelector('.batch-consent__split')).not.toBeNull();
    expect(batchStartMock).not.toHaveBeenCalled();
  });

  // ---- W08: a running batch can be CANCELLED from the UI --------------------
  //
  // `batch.cancel` shipped end-to-end (client.ts:805 -> batch.py BatchService.cancel,
  // which sets the parent job's cooperative cancel flag) but the panel called
  // list/status/start/create/plan/resume/delete and NEVER cancel — so a batch that
  // was mid-flight could only be stopped by killing the app.

  /** Gate OFF -> Run -> one live source, so the live panel is mounted. */
  async function runToLiveBatch(): Promise<void> {
    settingsGetMock.mockResolvedValue({ confirmCloudBudget: false });
    batchStatusMock.mockResolvedValue({ batch: state([{ videoId: 'v1', status: 'running' }]) });
    await render();
    const cb = container.querySelectorAll('.batch-queue__source input')[0] as HTMLInputElement;
    act(() => cb.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it('offers Cancel only while the batch is unsettled, and cancels the parent job', async () => {
    await runToLiveBatch();
    // Present while a source is still running…
    expect(findText('Cancel')).toBeDefined();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchCancelMock).toHaveBeenCalledWith('bNew');
    // …and GONE once every source is terminal (nothing left to cancel). The
    // both-states check: the affordance must appear AND disappear, so a rule that
    // always renders it fails here too.
    batchStatusMock.mockResolvedValue({
      batch: state([{ videoId: 'v1', status: 'done' }], { status: 'done' }),
    });
    await act(async () => {
      fireJobDone();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancel')).toBeUndefined();
  });

  it('does NOT offer Cancel before the batch has actually started (consent window)', async () => {
    // Gate ON: `batch.create` mounts the live panel (queued rows, 0% bar) while
    // `batch.start` is still deferred behind the consent card, so no parent job
    // exists yet. Offering Cancel there would be a control whose ONLY possible
    // outcome is the {ok:false} "nothing to cancel" reply — a fresh dead click on
    // the very surface this change exists to de-deaden.
    await runToConsentCard();
    expect(container.querySelector('.batch-queue__rows')).not.toBeNull();
    expect(findText('Cancel')).toBeUndefined();
    // …and it appears as soon as a parent job IS tracked (the both-states check).
    await act(async () => {
      clickText('Acknowledge cloud egress for this batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancel')).toBeDefined();
  });

  it('surfaces a refused cancel (ok:false) as a notice, never as a failure', async () => {
    // `BatchService.cancel` answers {ok: false} when THIS sidecar process tracks no
    // parent job for the batch (post-restart, or the job was evicted) — nothing was
    // cancelled, but nothing failed either, so it must announce politely.
    batchCancelMock.mockResolvedValueOnce({ ok: false });
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')).toBeNull();
    expect(container.querySelector('.batch-queue__notice')?.textContent).toContain(
      'no running job',
    );
  });

  it('surfaces a cancel failure with an Error message (instanceof arm)', async () => {
    batchCancelMock.mockRejectedValueOnce(new Error('cancel-boom'));
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('cancel-boom');
  });

  it('surfaces a cancel failure on a non-Error rejection (Cancel failed)', async () => {
    batchCancelMock.mockRejectedValueOnce('x');
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__error')?.textContent).toBe('Cancel failed');
  });

  // ---- W09: retryErrors reaches the wire ------------------------------------
  //
  // `batch.resume` accepts {id, retryErrors?} and the sidecar implements it
  // (batch.py:477/490 resumable_video_ids, :938 the param read), but the renderer
  // never sent it. Consequence, measured against derive_status (batch.py:172): a
  // `partial` aggregate means EVERY item is already terminal, so the default
  // resume selects nothing, no job starts, and the sidecar returns the
  // {jobId: null} no-op shape — every Resume button on a partial batch is dead.

  const partialWithErrors = (): BatchSummary =>
    summary({
      status: 'partial',
      counts: { total: 3, done: 1, error: 2, skipped: 0, queued: 0, running: 0, cancelled: 0 },
    });

  it('offers Retry errors only when a batch has failed sources, and sends retryErrors', async () => {
    batchListMock.mockResolvedValue({ batches: [partialWithErrors()] });
    await render();
    await act(async () => {
      clickText('Retry errors');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchResumeMock).toHaveBeenCalledWith('bA', { retryErrors: true });
  });

  it('omits Retry errors on a batch with no failed sources', async () => {
    // The other direction of the same affordance: a queued/running batch has
    // nothing to retry, so offering the control would be a lie.
    batchListMock.mockResolvedValue({ batches: [summary()] });
    await render();
    expect(findText('Resume')).toBeDefined();
    expect(findText('Retry errors')).toBeUndefined();
  });

  it('says nothing is left to resume on a TERMINAL no-op, not "already running"', async () => {
    // The sidecar reuses ONE {jobId: null} wire shape for two very different
    // refusals: "the parent job is still live" (status queued/running) and
    // "nothing was resumable" (a terminal aggregate). The panel announced the
    // live-run message for both, so a partial batch reported that it was
    // "already running" when in fact it had finished and had nothing to re-run.
    batchListMock.mockResolvedValue({ batches: [partialWithErrors()] });
    batchResumeMock.mockResolvedValueOnce({ jobId: null, status: 'partial' });
    await render();
    await act(async () => {
      clickText('Resume');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    const notice = container.querySelector('.batch-queue__notice')?.textContent ?? '';
    expect(notice).toContain('Nothing left to resume');
    expect(notice).not.toContain('already running');
  });

  it('says nothing is left to RETRY when the retry itself is a no-op', async () => {
    batchListMock.mockResolvedValue({ batches: [partialWithErrors()] });
    batchResumeMock.mockResolvedValueOnce({ jobId: null, status: 'error' });
    await render();
    await act(async () => {
      clickText('Retry errors');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector('.batch-queue__notice')?.textContent).toContain(
      'Nothing left to retry',
    );
  });

  // ---- W09, the ALL-ERROR batch --------------------------------------------
  //
  // The case the brief actually names, and the one the first pass missed while
  // fixing `partial`. `derive_status` gives a run whose every source failed the
  // TERMINAL aggregate `error`; `isIncomplete` is {queued, running, partial}; so
  // `incompleteBatches` filtered it out and the panel rendered NO row for it —
  // not a dead Resume button, no button at all, and no route back to the failures
  // from anywhere in the app.

  const allErrors = (): BatchSummary =>
    summary({
      id: 'bErr',
      name: 'All failed',
      status: 'error',
      counts: { total: 3, done: 0, error: 3, skipped: 0, queued: 0, running: 0, cancelled: 0 },
    });

  it('surfaces an ALL-ERROR batch, which the incomplete list structurally cannot', async () => {
    batchListMock.mockResolvedValue({ batches: [allErrors()] });
    await render();
    // Both states in one assertion pair: the batch is genuinely absent from the
    // resume surface (so a fix that only touched that list could not reach it)…
    expect(container.querySelector('.batch-queue__resume')).toBeNull();
    // …and present on the retry surface, with its failure count named.
    const row = container.querySelector('.batch-queue__retry-row');
    expect(row?.textContent).toContain('All failed');
    expect(row?.textContent).toContain('3 of 3 failed');
    await act(async () => {
      clickText('Retry errors');
      await Promise.resolve();
      await Promise.resolve();
    });
    // A PLAIN resume here can never re-enqueue an `error` item, so the only
    // control offered is the one that passes the flag.
    expect(findText('Resume')).toBeUndefined();
    expect(batchResumeMock).toHaveBeenCalledWith('bErr', { retryErrors: true });
  });

  it('removes an all-error batch from the retry surface', async () => {
    batchListMock
      .mockResolvedValueOnce({ batches: [allErrors()] })
      .mockResolvedValueOnce({ batches: [] });
    await render();
    await act(async () => {
      clickText('Remove');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchDeleteMock).toHaveBeenCalledWith('bErr');
    expect(container.querySelector('.batch-queue__retry')).toBeNull();
  });

  it('never lists the same batch on BOTH the resume and retry surfaces', async () => {
    // `partial` with errors is resumable AND retryable; it must keep its single
    // row on the resume surface rather than being duplicated below it.
    batchListMock.mockResolvedValue({ batches: [partialWithErrors(), allErrors()] });
    await render();
    expect(container.querySelectorAll('.batch-queue__resume-row').length).toBe(1);
    expect(container.querySelectorAll('.batch-queue__retry-row').length).toBe(1);
    expect(container.querySelector('.batch-queue__retry-row')?.textContent).toContain('All failed');
  });

  it('offers no retry surface for a terminal batch with no failed sources', async () => {
    batchListMock.mockResolvedValue({
      batches: [
        summary({
          status: 'done',
          counts: { total: 2, done: 2, error: 0, skipped: 0, queued: 0, running: 0, cancelled: 0 },
        }),
      ],
    });
    await render();
    expect(container.querySelector('.batch-queue__retry')).toBeNull();
  });

  // ---- W08 follow-up: Cancel must not outlive its own parent job ------------

  /** A snapshot the runner really produces after an unwind: cancelled + queued. */
  const unwoundSnapshot = (): { batch: BatchState } => ({
    batch: state(
      [
        { videoId: 'v1', status: 'cancelled' },
        { videoId: 'v2', status: 'queued' },
      ],
      { status: 'running' },
    ),
  });

  it('retires Cancel when the PARENT job ends, even with items still queued', async () => {
    // The dead click the first pass created. `batchSettled` cannot end the run:
    // the runner unwinds at the first observed cancel and leaves every source it
    // never reached `queued` ON DISK, so those items are non-terminal forever.
    // With only the settled gate, Cancel stayed enabled after the job was already
    // terminal, and pressing it hit `JobRegistry.cancel` on a finished job — which
    // returns True and does nothing (jobs.py:829-836): ok:true, no notice, no
    // change. The parent `job.done` is the only signal that retires it.
    batchStatusMock.mockResolvedValue(unwoundSnapshot());
    await runToLiveBatch();
    expect(findText('Cancel')).toBeDefined(); // PASSES today — the control is live
    await act(async () => {
      fireJobDone('job-1');
      await Promise.resolve();
      await Promise.resolve();
    });
    // The items are STILL not all terminal here, so `batchSettled` is false and a
    // gate built only on it keeps rendering the button. FAILS before the teardown.
    expect(container.querySelector('.batch-queue__rows')).not.toBeNull();
    expect(findText('Cancel')).toBeUndefined();
    expect(findText('Cancelling…')).toBeUndefined();
  });

  it('keeps Cancel alive when a per-source SUB-job finishes', async () => {
    // The other direction: a batch fans out sub-jobs that each emit their own
    // `job.done`, so the teardown must key on the tracked PARENT jobId or the
    // control would vanish the moment the first source completed.
    batchStatusMock.mockResolvedValue(unwoundSnapshot());
    await runToLiveBatch();
    await act(async () => {
      fireJobDone('sub-9');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancel')).toBeDefined();
  });

  it('makes an accepted Cancel observable and unrepeatable until it unwinds', async () => {
    // Cancellation is cooperative, so the row legitimately stays "Running" for a
    // while. Without a local pending state the click produced NO observable change
    // whatsoever, which is indistinguishable from a dead control — and a second
    // press re-flagged an already-flagged job for another ok:true no-op.
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(batchCancelMock).toHaveBeenCalledTimes(1);
    const pending = findText('Cancelling…');
    expect(pending).toBeDefined();
    expect(pending?.disabled).toBe(true);
    expect(findText('Cancel')).toBeUndefined();
    // A disabled control cannot fire a second RPC.
    act(() => pending?.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(batchCancelMock).toHaveBeenCalledTimes(1);
  });

  it('releases the pending state when the cancel was refused (ok:false)', async () => {
    // Nothing is unwinding, so "Cancelling…" would be a lie; the control returns.
    batchCancelMock.mockResolvedValueOnce({ ok: false });
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancelling…')).toBeUndefined();
    expect(findText('Cancel')).toBeDefined();
  });

  it('releases the pending state when the cancel THROWS', async () => {
    batchCancelMock.mockRejectedValueOnce(new Error('cancel-boom'));
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancelling…')).toBeUndefined();
    expect(findText('Cancel')).toBeDefined();
  });

  it('clears a pending cancel when a NEW run starts', async () => {
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancelling…')).toBeDefined();
    await act(async () => {
      clickText('Run batch');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancelling…')).toBeUndefined();
  });

  it('clears a pending cancel when a resume starts a fresh parent job', async () => {
    batchListMock.mockResolvedValue({ batches: [summary()] });
    await runToLiveBatch();
    await act(async () => {
      clickText('Cancel');
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancelling…')).toBeDefined();
    await act(async () => {
      clickText('Resume');
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(findText('Cancelling…')).toBeUndefined();
  });
});

describe('announceTransitions (pure)', () => {
  const titleFor = (id: string): string => id.toUpperCase();
  it('pushes polite for done and assertive for error; silent for non-terminal', () => {
    const polite: string[] = [];
    let assertive = '';
    const next = state([
      { videoId: 'a', status: 'done' },
      { videoId: 'b', status: 'error', error: 'x' },
      { videoId: 'c', status: 'running' },
    ]);
    announceTransitions(
      null,
      next,
      titleFor,
      (fn) => polite.splice(0, polite.length, ...fn(polite)),
      (t) => {
        assertive = t;
      },
    );
    expect(polite).toEqual(['A — done']);
    expect(assertive).toBe('B — failed: x');
  });

  it('does not re-announce an item that was already terminal', () => {
    const polite: string[] = [];
    const prev = state([{ videoId: 'a', status: 'done' }]);
    const next = state([{ videoId: 'a', status: 'done' }]);
    announceTransitions(
      prev,
      next,
      titleFor,
      (fn) => polite.splice(0, polite.length, ...fn(polite)),
      () => {},
    );
    expect(polite).toEqual([]);
  });

  it('carries the last known pct forward when the next snapshot omits it', () => {
    const prev = state([{ videoId: 'a', status: 'running' }], { pct: 100 });
    const next = state([{ videoId: 'a', status: 'done' }], { status: 'done' });
    expect(
      announceTransitions(
        prev,
        next,
        titleFor,
        () => {},
        () => {},
      ).pct,
    ).toBe(100);
  });

  it('lets a defined next pct win over the carried one', () => {
    const prev = state([{ videoId: 'a', status: 'running' }], { pct: 10 });
    const next = state([{ videoId: 'a', status: 'running' }], { pct: 55 });
    expect(
      announceTransitions(
        prev,
        next,
        titleFor,
        () => {},
        () => {},
      ).pct,
    ).toBe(55);
  });

  it('never carries a DIFFERENT batch pct forward (the resume refresh path)', () => {
    // `resume` calls refreshBatch(id) WITHOUT resetting `batch`, so an evicted or
    // already-terminal resume would otherwise leak the previous batch's pct.
    const prev = state([{ videoId: 'a', status: 'running' }], { id: 'bOld', pct: 90 });
    const next = state([{ videoId: 'a', status: 'running' }], { id: 'bNew' });
    expect(
      announceTransitions(
        prev,
        next,
        titleFor,
        () => {},
        () => {},
      ).pct,
    ).toBeUndefined();
  });

  it('ignores a terminal status with no announcement mapping is impossible (cancelled is polite)', () => {
    const polite: string[] = [];
    const next = state([{ videoId: 'a', status: 'cancelled' }]);
    announceTransitions(
      null,
      next,
      titleFor,
      (fn) => polite.splice(0, polite.length, ...fn(polite)),
      () => {},
    );
    expect(polite).toEqual(['A — cancelled']);
  });
});
