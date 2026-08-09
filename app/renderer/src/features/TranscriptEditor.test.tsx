// TranscriptEditor.test.tsx — the transcript-native editing pane (v1.5 flagship #2).
//
// Drives the four sidecar RPCs behind a fake `api` bridge (mirroring
// Refine.test.tsx):
//   transcript.get({videoId})                 -> {transcript}            (DIRECT)
//   transcript.previewEdit({videoId, edits})  -> {plan}                  (DIRECT)
//   transcript.applyEdit({videoId, edits})    -> {jobId} -> job.done {path, editId}
//   transcript.undoEdit({videoId})            -> {editId, path}          (DIRECT)

// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';
import TranscriptEditor, {
  errMessage,
  extractApply,
  extractPlan,
  extractTranscript,
  undoPath,
} from './TranscriptEditor';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const TRANSCRIPT = {
  language: 'en',
  durationSec: 10,
  segments: [
    {
      start: 0,
      end: 3.5,
      text: 'we um should ship',
      words: [
        { wordId: 'w0-0', segmentIndex: 0, wordIndex: 0, text: 'we', start: 0, end: 0.5 },
        { wordId: 'w0-1', segmentIndex: 0, wordIndex: 1, text: 'um', start: 1, end: 1.4 },
        { wordId: 'w0-2', segmentIndex: 0, wordIndex: 2, text: 'should', start: 2, end: 2.5 },
        { wordId: 'w0-3', segmentIndex: 0, wordIndex: 3, text: 'ship', start: 3, end: 3.5 },
      ],
    },
  ],
};

const PLAN = {
  keeps: [
    [0, 3],
    [3.5, 10],
  ],
  stats: {
    wordsDeleted: 1,
    deletedSec: 0.5,
    fillersRemoved: 0,
    fillerSeconds: 0,
    silenceRemovedSec: 0,
    keptSec: 9.5,
    removedSec: 0.5,
  },
  cues: [],
  rejected: [],
};

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(overrides: Record<string, unknown> = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const table: Record<string, unknown> = {
    'transcript.get': { transcript: TRANSCRIPT },
    'transcript.previewEdit': { plan: PLAN },
    'transcript.applyEdit': { jobId: 'job-t' },
    'transcript.undoEdit': { editId: 'tedit-1', path: '/lib/in.mp4' },
    ...overrides,
  };
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      const value = table[method];
      if (value instanceof Error) throw value;
      return (value ?? {}) as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb) => {
      progressCbs.push(cb);
      return () => {
        progressCbs = progressCbs.filter((c) => c !== cb);
      };
    },
    onJobDone: (cb) => {
      doneCbs.push(cb);
      return () => {
        doneCbs = doneCbs.filter((c) => c !== cb);
      };
    },
  };
  return {
    api,
    calls,
    fireProgress: (ev) => progressCbs.slice().forEach((cb) => cb(ev)),
    fireDone: (ev) => doneCbs.slice().forEach((cb) => cb(ev)),
  };
}

describe('extractTranscript', () => {
  it('pulls a transcript with segments', () => {
    expect(extractTranscript({ transcript: TRANSCRIPT })).toEqual(TRANSCRIPT);
  });
  it('is null when absent, null, or shapeless', () => {
    expect(extractTranscript({})).toBeNull();
    expect(extractTranscript(null)).toBeNull();
    expect(extractTranscript({ transcript: { segments: 'nope' } })).toBeNull();
  });
});

describe('extractPlan', () => {
  it('pulls the plan from a previewEdit result', () => {
    expect(extractPlan({ plan: PLAN })).toEqual(PLAN);
  });
  it('is null when absent or shapeless', () => {
    expect(extractPlan({})).toBeNull();
    expect(extractPlan({ plan: { keeps: [], stats: null } })).toBeNull();
  });
});

describe('extractApply', () => {
  it('reads the output path and edit id', () => {
    expect(extractApply({ path: '/out/in.edited.mp4', editId: 'tedit-1' })).toEqual({
      path: '/out/in.edited.mp4',
      editId: 'tedit-1',
    });
  });
  it('tolerates a null editId (a pass-through apply)', () => {
    expect(extractApply({ path: '/lib/in.mp4', editId: null })).toEqual({
      path: '/lib/in.mp4',
      editId: null,
    });
  });
  it('is null without a path', () => {
    expect(extractApply({})).toBeNull();
    expect(extractApply(null)).toBeNull();
  });
});

describe('errMessage', () => {
  it('uses an Error message verbatim', () => {
    expect(errMessage(new Error('ffmpeg exit 1'))).toBe('ffmpeg exit 1');
  });
  it('stringifies a non-Error throw', () => {
    expect(errMessage('bridge went away')).toBe('bridge went away');
  });
});

describe('undoPath', () => {
  it('reads the restored path', () => {
    expect(undoPath({ path: '/lib/in.mp4' })).toBe('/lib/in.mp4');
  });
  it('is empty when the result names no path', () => {
    expect(undoPath({ editId: 'tedit-1' })).toBe('');
  });
});

describe('<TranscriptEditor />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  async function mount(api?: MediaStudioApi): Promise<void> {
    await act(async () => {
      root.render(<TranscriptEditor videoId="v1" api={api} />);
    });
  }

  const word = (id: string): HTMLButtonElement =>
    container.querySelector<HTMLButtonElement>(`button[data-word-id="${id}"]`) as HTMLButtonElement;

  const action = (name: string): HTMLButtonElement =>
    container.querySelector<HTMLButtonElement>(
      `button[data-action="${name}"]`,
    ) as HTMLButtonElement;

  async function click(el: HTMLButtonElement): Promise<void> {
    await act(async () => {
      el.click();
      await Promise.resolve();
    });
  }

  /** Click Apply, then deliver the job's terminal `job.done` payload. */
  async function applyAndFinish(
    fake: FakeApi,
    result: unknown,
    progress?: ProgressEvent,
  ): Promise<void> {
    await click(action('apply'));
    if (progress) {
      await act(async () => {
        fake.fireProgress(progress);
      });
    }
    await act(async () => {
      fake.fireDone({ jobId: 'job-t', result });
    });
  }

  it('loads the transcript on mount and renders one button per word', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(fake.calls[0]).toEqual({ method: 'transcript.get', params: { videoId: 'v1' } });
    expect(container.querySelectorAll('button[data-word-id]')).toHaveLength(4);
    expect(word('w0-2').textContent).toBe('should');
  });

  it('falls back to the global api bridge when no prop is given', async () => {
    const fake = makeFakeApi();
    (globalThis as unknown as { api?: unknown }).api = fake.api;
    await mount();
    expect(container.querySelectorAll('button[data-word-id]')).toHaveLength(4);
    (globalThis as unknown as { api?: unknown }).api = undefined;
  });

  it('shows an empty state (and disables Preview) when there is no transcript', async () => {
    const fake = makeFakeApi({ 'transcript.get': { transcript: null } });
    await mount(fake.api);
    expect(container.querySelector('[data-state="empty"]')).not.toBeNull();
    expect(action('preview').disabled).toBe(true);
  });

  it('surfaces a load failure', async () => {
    const fake = makeFakeApi({ 'transcript.get': new Error('sidecar down') });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar down');
  });

  it('strikes a word on click and restores it on a second click', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(word('w0-1'));
    expect(word('w0-1').dataset.deleted).toBe('true');
    expect(container.querySelector('[data-section="editedText"]')?.textContent).toBe(
      'we should ship',
    );
    expect(container.querySelector('[data-stat="removedSec"]')?.textContent).toBe('0.4');
    await click(word('w0-1'));
    expect(word('w0-1').dataset.deleted).toBe('false');
    expect(container.querySelector('[data-section="editedText"]')?.textContent).toBe(
      'we um should ship',
    );
  });

  it('previews the cut with the exact EditSpans for the struck words', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    expect(fake.calls.at(-1)).toEqual({
      method: 'transcript.previewEdit',
      params: { videoId: 'v1', edits: [{ op: 'delete', wordId: 'w0-3' }] },
    });
    expect(container.querySelector('[data-stat="planRemovedSec"]')?.textContent).toBe('0.5');
    expect(container.querySelector('[data-stat="keeps"]')?.textContent).toBe('2');
  });

  it('labels the Preview button in-flight while the plan is pending', async () => {
    let release: (value: unknown) => void = () => {};
    const pending = new Promise<unknown>((resolve) => {
      release = resolve;
    });
    const fake = makeFakeApi({ 'transcript.previewEdit': pending });
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    expect(action('preview').textContent).toBe('Previewing…');
    expect(action('preview').disabled).toBe(true);
    await act(async () => {
      release({ plan: PLAN });
    });
    expect(action('preview').textContent).toBe('Preview cut');
  });

  it('reports edits the sidecar dropped', async () => {
    const rejected = {
      ...PLAN,
      rejected: [{ index: 0, op: 'reorder', reason: 'reorder-deferred' }],
    };
    const fake = makeFakeApi({ 'transcript.previewEdit': { plan: rejected } });
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    expect(container.querySelector('[data-stat="rejected"]')?.textContent).toContain(
      'reorder-deferred',
    );
  });

  it('surfaces a preview failure', async () => {
    const fake = makeFakeApi({ 'transcript.previewEdit': new Error('no plan') });
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('no plan');
  });

  it('keeps Apply disabled until a preview exists, then applies and shows the cut file', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(word('w0-3'));
    expect(action('apply').disabled).toBe(true);
    await click(action('preview'));
    expect(action('apply').disabled).toBe(false);

    await applyAndFinish(
      fake,
      { path: '/out/in.edited.mp4', editId: 'tedit-1' },
      { jobId: 'job-t', pct: 40, message: 're-cutting' },
    );

    expect(container.querySelector('[data-section="result"] code')?.textContent).toBe(
      '/out/in.edited.mp4',
    );
    expect(container.querySelector('[data-stat="editId"]')?.textContent).toBe('tedit-1');
    expect(action('undo').disabled).toBe(false);
  });

  it('striking another word after a preview re-disables Apply', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    expect(action('apply').disabled).toBe(false);
    await click(word('w0-1'));
    expect(action('apply').disabled).toBe(true);
  });

  it('shows no result section when the apply job returns no path', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    await applyAndFinish(fake, {});
    expect(container.querySelector('[data-section="result"]')).toBeNull();
  });

  it('surfaces an apply failure', async () => {
    const fake = makeFakeApi({ 'transcript.applyEdit': new Error('ffmpeg exit 1') });
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    await click(action('apply'));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('ffmpeg exit 1');
  });

  it('treats a missing jobId as nothing to wait for', async () => {
    const fake = makeFakeApi({ 'transcript.applyEdit': {} });
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    await click(action('apply'));
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('undo restores the previous path and clears the edit id', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    await applyAndFinish(fake, { path: '/out/in.edited.mp4', editId: 'tedit-1' });

    await click(action('undo'));
    expect(fake.calls.at(-1)).toEqual({
      method: 'transcript.undoEdit',
      params: { videoId: 'v1', editId: 'tedit-1' },
    });
    expect(container.querySelector('[data-section="result"] code')?.textContent).toBe(
      '/lib/in.mp4',
    );
    expect(action('undo').disabled).toBe(true);
  });

  it('surfaces an undo failure', async () => {
    const fake = makeFakeApi({ 'transcript.undoEdit': new Error('nothing to undo') });
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    await applyAndFinish(fake, { path: '/out/in.edited.mp4', editId: 'tedit-1' });
    await click(action('undo'));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('nothing to undo');
  });

  it('ignores progress for a different job', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(word('w0-3'));
    await click(action('preview'));
    await applyAndFinish(
      fake,
      { path: '/out/in.edited.mp4', editId: 'tedit-1' },
      { jobId: 'someone-else', pct: 99, message: 'not mine' },
    );
    expect(container.textContent).not.toContain('not mine');
  });
});
