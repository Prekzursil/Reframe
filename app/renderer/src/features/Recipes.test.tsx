// Recipes.test.tsx — tests for the Pipeline Recipes panel (system-advanced).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Recipes, {
  type Recipe,
  RECIPE_PRESETS,
  buildRecipeFromPreset,
  doneErrorMessage,
} from './Recipes';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

const SAVED: Recipe[] = [
  {
    id: 'r1',
    name: 'Transcribe + label speakers',
    steps: [
      { method: 'transcribe.start', params: { videoId: 'v1' }, label: 'Transcribe' },
      { method: 'diarize.start', params: { videoId: 'v1' }, label: 'Label speakers' },
    ],
  },
];

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(initial: Recipe[]): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  let listed = initial;
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'recipes.list') return { recipes: listed } as T;
      if (method === 'recipes.save') {
        const recipe = (params as { recipe: Omit<Recipe, 'id'> }).recipe;
        listed = [...listed, { id: 'new', ...recipe }];
        return { recipe: listed[listed.length - 1] } as T;
      }
      if (method === 'recipes.delete') {
        listed = listed.filter((r) => r.id !== (params as { id: string }).id);
        return { ok: true } as T;
      }
      if (method === 'recipes.run') return { jobId: 'job-9' } as T;
      return {} as T;
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

describe('buildRecipeFromPreset', () => {
  it('stamps the active videoId into the steps', () => {
    const preset = RECIPE_PRESETS[0];
    const recipe = buildRecipeFromPreset(preset, 'vidX');
    expect(recipe.name).toBe(preset.name);
    expect(recipe.steps[0].params.videoId).toBe('vidX');
  });

  it('preset with a ref step keeps the $N reference', () => {
    const preset = RECIPE_PRESETS.find((p) => p.id === 'transcribe-subtitles-translate')!;
    const recipe = buildRecipeFromPreset(preset, 'vidX');
    const translate = recipe.steps.find((s) => s.method === 'subtitles.translate')!;
    expect(translate.params.trackId).toBe('$1.track.id');
  });
});

describe('doneErrorMessage', () => {
  it('extracts the error payload message', () => {
    expect(doneErrorMessage({ error: { message: 'offline', type: 'OfflineError' } })).toBe(
      'offline',
    );
  });
  it('null for success', () => {
    expect(doneErrorMessage({ results: [] })).toBeNull();
  });
});

describe('<Recipes />', () => {
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

  async function mount(api: MediaStudioApi, videoId = 'v1'): Promise<void> {
    await act(async () => {
      root.render(<Recipes videoId={videoId} api={api} />);
    });
  }

  it('lists saved recipes and the presets', async () => {
    const fake = makeFakeApi(SAVED);
    await mount(fake.api);
    expect(fake.calls[0]).toEqual({ method: 'recipes.list', params: undefined });
    expect(container.querySelector('li[data-recipe="r1"]')?.textContent).toContain('2 step(s)');
    expect(container.querySelectorAll('li[data-preset]').length).toBe(RECIPE_PRESETS.length);
  });

  it('saving a preset stamps the videoId and refreshes', async () => {
    const fake = makeFakeApi([]);
    await mount(fake.api, 'vidZ');
    const addBtn = container.querySelector(
      'li[data-preset] button[data-action="add-preset"]',
    ) as HTMLButtonElement;
    await act(async () => {
      addBtn.click();
    });
    const saveCall = fake.calls.find((c) => c.method === 'recipes.save');
    const recipe = (saveCall?.params as { recipe: Recipe }).recipe;
    expect(recipe.steps[0].params.videoId).toBe('vidZ');
  });

  it('running a recipe starts recipes.run, shows progress, then done', async () => {
    const fake = makeFakeApi(SAVED);
    await mount(fake.api);
    const runBtn = container.querySelector(
      'button[data-action="run"][data-recipe="r1"]',
    ) as HTMLButtonElement;
    await act(async () => {
      runBtn.click();
    });
    expect(fake.calls.find((c) => c.method === 'recipes.run')?.params).toEqual({ id: 'r1' });

    await act(async () => {
      fake.fireProgress({ jobId: 'job-9', pct: 50, message: 'step 1/2 · Transcribe' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('50%');
    expect(container.querySelector('.progress')?.textContent).toContain('Transcribe');

    await act(async () => {
      fake.fireDone({ jobId: 'job-9', result: { results: [{}, {}] } });
    });
    expect(container.querySelector('.progress')).toBeNull(); // run finished
  });

  it('surfaces a job.done error from the run', async () => {
    const fake = makeFakeApi(SAVED);
    await mount(fake.api);
    const runBtn = container.querySelector(
      'button[data-action="run"][data-recipe="r1"]',
    ) as HTMLButtonElement;
    await act(async () => {
      runBtn.click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-9',
        result: { error: { message: 'Offline mode is on', type: 'OfflineError' } },
      });
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('Offline mode is on');
  });

  it('deleting a recipe calls recipes.delete', async () => {
    const fake = makeFakeApi(SAVED);
    await mount(fake.api);
    const delBtn = container.querySelector(
      'button[data-action="delete"][data-recipe="r1"]',
    ) as HTMLButtonElement;
    await act(async () => {
      delBtn.click();
    });
    expect(fake.calls.find((c) => c.method === 'recipes.delete')?.params).toEqual({ id: 'r1' });
  });

  it('shows empty state when no recipes', async () => {
    const fake = makeFakeApi([]);
    await mount(fake.api);
    expect(container.querySelector('.asset-empty')?.textContent).toContain('No recipes yet');
  });
});
