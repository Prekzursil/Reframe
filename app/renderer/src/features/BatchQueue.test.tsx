// BatchQueue.test.tsx — the primary folder→shorts flow + live a11y + resume.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type {
  BatchConsent,
  BatchState,
  BatchSummary,
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
const settingsGetMock = vi.fn();

let progressCbs: Array<(e: ProgressEvent) => void> = [];
let doneCbs: Array<() => void> = [];

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
    },
    settings: { get: (...a: unknown[]) => settingsGetMock(...a) },
  },
  onProgress: (cb: (e: ProgressEvent) => void) => {
    progressCbs.push(cb);
    return () => {
      progressCbs = progressCbs.filter((c) => c !== cb);
    };
  },
  onJobDone: (cb: () => void) => {
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
  // The §9.1 budget setting defaults ON (settings_store confirmCloudBudget=True).
  settingsGetMock.mockResolvedValue({ confirmCloudBudget: true });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

function clickText(text: string): void {
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent === text);
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
      doneCbs.forEach((c) => c());
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
      doneCbs.forEach((c) => c());
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
      container.querySelector('.batch-queue__live [role="progressbar"]')?.getAttribute('aria-valuenow');
    act(() =>
      progressCbs.forEach((c) => c({ jobId: 'sub-9', pct: 88, message: 'reframe 88%' })),
    );
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
      container.querySelector('.batch-queue__live [role="progressbar"]')?.getAttribute('aria-valuenow');
    // A stale prior-run jobId is ignored...
    act(() => progressCbs.forEach((c) => c({ jobId: 'job-1', pct: 5, message: 'stale' })));
    expect(barNow()).not.toBe('5');
    // ...the resumed run's jobId (job-2) applies.
    act(() => progressCbs.forEach((c) => c({ jobId: 'job-2', pct: 61, message: 'source 1/1 · A' })));
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
