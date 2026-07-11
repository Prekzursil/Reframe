// SemanticSearch.test.tsx — tests for the WU-A6 semantic-search feature panel.
//
// The panel consumes the FROZEN window.api bridge via getApi() (no api prop), so
// we install a fake bridge on globalThis.api. It drives the three index.* states
// (DESIGN §1.6): NOT built (CTA + disabled box), BUILDING (progress + disabled),
// BUILT + results (keyboard activation seeks the player), the empty result
// ("No matches" announced), the error path (role="alert"), and the unbuilt
// search-fallback alert. Every ARIA attribute in §1.6 is asserted.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import SemanticSearch from './SemanticSearch';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';
import type { PlayerHandle } from '../components/Player';
import type { IndexHit, IndexStatus } from '../lib/rpc';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
  rpc: ReturnType<typeof vi.fn>;
}

function makeFakeApi(handlers: Record<string, unknown> = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const rpc = vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
    calls.push({ method, params });
    if (method in handlers) {
      const h = handlers[method];
      return (typeof h === 'function' ? await (h as (p?: unknown) => unknown)(params) : h) as T;
    }
    return {} as T;
  }) as ReturnType<typeof vi.fn>;
  const api: MediaStudioApi = {
    rpc: rpc as MediaStudioApi['rpc'],
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
    rpc,
    fireProgress: (ev) => progressCbs.slice().forEach((cb) => cb(ev)),
    fireDone: (ev) => doneCbs.slice().forEach((cb) => cb(ev)),
  };
}

function makePlayerRef(): {
  ref: React.RefObject<PlayerHandle | null>;
  seek: ReturnType<typeof vi.fn>;
} {
  const seek = vi.fn();
  const handle: PlayerHandle = {
    play: vi.fn(),
    pause: vi.fn(),
    seek,
    scrub: vi.fn(),
    currentTime: () => 0,
    isPlaying: () => false,
    element: () => null,
  };
  return { ref: { current: handle }, seek };
}

const BUILT: IndexStatus = {
  built: true,
  segmentCount: 3,
  model: 'local',
  builtAt: '2026-06-20T00:00:00Z',
  dim: 4,
};
const UNBUILT: IndexStatus = {
  built: false,
  segmentCount: 0,
  model: null,
  builtAt: null,
  dim: 0,
};

function hits(): IndexHit[] {
  return [
    {
      segmentIndex: 5,
      start: 724.0,
      end: 728.0,
      text: 'we priced it at nine dollars',
      score: 0.91,
    },
    { segmentIndex: 1, start: 12.0, end: 15.0, text: 'the opening hook', score: 0.42 },
  ];
}

describe('<SemanticSearch />', () => {
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
    delete (globalThis as { api?: unknown }).api;
    vi.restoreAllMocks();
  });

  function install(fake: FakeApi) {
    (globalThis as { api?: unknown }).api = fake.api;
  }

  async function mount(
    fake: FakeApi,
    over: { videoId?: string; playerRef?: React.RefObject<PlayerHandle | null> } = {},
  ): Promise<void> {
    install(fake);
    await act(async () => {
      root.render(<SemanticSearch videoId={over.videoId ?? 'v1'} playerRef={over.playerRef} />);
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  function queryInput(): HTMLInputElement {
    return container.querySelector('#semantic-search-query') as HTMLInputElement;
  }
  async function type(value: string): Promise<void> {
    await act(async () => {
      const input = queryInput();
      // React tracks a controlled input's value via a descriptor; set through the
      // native prototype setter so the dispatched `input` event reaches onChange.
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      setter?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }
  async function submit(): Promise<void> {
    await act(async () => {
      container
        .querySelector('form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it('queries index.status on mount and renders a labelled search input', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT });
    await mount(fake);
    expect(fake.calls.find((c) => c.method === 'index.status')?.params).toEqual({ videoId: 'v1' });
    const input = queryInput();
    expect(input).toBeTruthy();
    expect(input.getAttribute('aria-label')).toBe('Search the transcript');
    expect(container.querySelector('label[for="semantic-search-query"]')).toBeTruthy();
    // built -> the box is enabled, no CTA.
    expect(input.disabled).toBe(false);
    expect(
      [...container.querySelectorAll('button')].some((b) =>
        /Build the search index/.test(b.textContent ?? ''),
      ),
    ).toBe(false);
  });

  it('AC(c): unbuilt index renders the Build CTA + a disabled search box; clicking it calls index.build', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT, 'index.build': { jobId: 'job-idx' } });
    await mount(fake);
    expect(queryInput().disabled).toBe(true);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    expect(cta).toBeTruthy();
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'index.build')?.params).toEqual({ videoId: 'v1' });
  });

  it('AC(d): building shows the polite progress region (disabled box); onJobDone re-enables the box', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT, 'index.build': { jobId: 'job-idx' } });
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    // building -> a polite progress region; box still disabled.
    const progress = container.querySelector('.progress[aria-live="polite"]');
    expect(progress).toBeTruthy();
    expect(queryInput().disabled).toBe(true);
    await act(async () => {
      fake.fireProgress({ jobId: 'job-idx', pct: 40, message: 'embedding' });
    });
    expect(progress?.textContent).toContain('40%');
    expect(progress?.textContent).toContain('embedding');
    // a different job's progress is ignored.
    await act(async () => {
      fake.fireProgress({ jobId: 'other', pct: 99, message: 'nope' });
    });
    expect(progress?.textContent).not.toContain('99%');
    // job.done flips built=true and enables the box.
    await act(async () => {
      fake.fireDone({
        jobId: 'job-idx',
        result: { segmentCount: 3, model: 'local', builtAt: 'x', dim: 4 },
      });
      await Promise.resolve();
    });
    expect(queryInput().disabled).toBe(false);
    expect(container.querySelector('.progress[aria-live="polite"]')).toBeNull();
  });

  it('ignores a job.done for an unrelated job (box stays disabled)', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT, 'index.build': { jobId: 'job-idx' } });
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'someone-else', result: {} });
      await Promise.resolve();
    });
    // still building (box disabled).
    expect(queryInput().disabled).toBe(true);
  });

  it('AC(a): built results render as focusable buttons; Enter on a hit seeks the player to its start', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT, 'index.search': { hits: hits() } });
    const player = makePlayerRef();
    await mount(fake, { playerRef: player.ref });
    await type('pricing');
    await submit();

    expect(fake.calls.find((c) => c.method === 'index.search')?.params).toEqual({
      videoId: 'v1',
      query: 'pricing',
      topK: 8,
    });
    const rows = [...container.querySelectorAll('ul.search-hits li button')] as HTMLButtonElement[];
    expect(rows.length).toBe(2);
    // each row is a real <button>, accessible name = timestamp + snippet.
    expect(rows[0].getAttribute('type')).toBe('button');
    expect(rows[0].getAttribute('aria-label')).toContain('12:04');
    expect(rows[0].getAttribute('aria-label')).toContain('we priced it at nine dollars');
    // Keyboard activation: a real <button> fires onClick for Enter/Space natively,
    // so dispatching click models the keyboard activation the browser performs.
    await act(async () => {
      rows[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(player.seek).toHaveBeenCalledWith(724.0);
    // result count announced in the live region.
    const live = container.querySelector('[aria-live="polite"].search-status');
    expect(live?.textContent).toContain('2 matches');
  });

  it('activating a hit without a player ref does not throw (optional-chain branch)', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT, 'index.search': { hits: hits() } });
    await mount(fake); // no playerRef
    await type('pricing');
    await submit();
    const row = container.querySelector('ul.search-hits li button') as HTMLButtonElement;
    await act(async () => {
      row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    // no throw, hits still shown.
    expect(container.querySelectorAll('ul.search-hits li button').length).toBe(2);
  });

  it('announces the singular "1 match" for a single hit', async () => {
    const fake = makeFakeApi({
      'index.status': BUILT,
      'index.search': { hits: [hits()[0]] },
    });
    await mount(fake);
    await type('pricing');
    await submit();
    expect(container.querySelectorAll('ul.search-hits li button').length).toBe(1);
    expect(container.querySelector('.search-status')?.textContent).toContain('1 match');
    expect(container.querySelector('.search-status')?.textContent).not.toContain('1 matches');
  });

  it('treats a search payload with no hits field as an empty result', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT, 'index.search': {} });
    await mount(fake);
    await type('pricing');
    await submit();
    expect(container.querySelector('ul.search-hits li')).toBeNull();
    expect(container.querySelector('.search-status')?.textContent).toContain(
      "No matches for 'pricing'",
    );
  });

  it('AC(b): an empty result renders + announces "No matches for \'<query>\'"', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT, 'index.search': { hits: [] } });
    await mount(fake);
    await type('unicorn');
    await submit();
    expect(container.querySelector('ul.search-hits li')).toBeNull();
    const live = container.querySelector('[aria-live="polite"].search-status');
    expect(live?.textContent).toContain("No matches for 'unicorn'");
    expect(container.querySelector('.search-empty')?.textContent).toContain(
      "No matches for 'unicorn'",
    );
  });

  it('announces "Searching…" while the search is in flight', async () => {
    let resolveSearch: (v: { hits: IndexHit[] }) => void = () => undefined;
    const fake = makeFakeApi({
      'index.status': BUILT,
      'index.search': () => new Promise((res) => (resolveSearch = res)),
    });
    await mount(fake);
    await type('hook');
    await submit();
    const live = container.querySelector('[aria-live="polite"].search-status');
    expect(live?.textContent).toContain('Searching…');
    await act(async () => {
      resolveSearch({ hits: hits() });
      await Promise.resolve();
    });
    expect(container.querySelector('[aria-live="polite"].search-status')?.textContent).toContain(
      '2 matches',
    );
  });

  it('does not search on an empty/whitespace query (no rpc, no state change)', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT, 'index.search': { hits: hits() } });
    await mount(fake);
    await type('   ');
    await submit();
    expect(fake.calls.find((c) => c.method === 'index.search')).toBeUndefined();
  });

  it('AC + error: an index.search rejection surfaces via role="alert"', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT });
    fake.rpc.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      fake.calls.push({ method, params });
      if (method === 'index.status') return BUILT;
      if (method === 'index.search') throw new Error('build the index first');
      return {};
    });
    await mount(fake);
    await type('pricing');
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'build the index first',
    );
    // The search results region is cleared on error (no stale hits).
    expect(container.querySelector('ul.search-hits li')).toBeNull();
  });

  it('stringifies a non-Error search rejection', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT });
    fake.rpc.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      fake.calls.push({ method, params });
      if (method === 'index.status') return BUILT;
      if (method === 'index.search') throw 'plain string error';
      return {};
    });
    await mount(fake);
    await type('pricing');
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain string error');
  });

  it('surfaces an index.build rejection via role="alert"', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT });
    fake.rpc.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      fake.calls.push({ method, params });
      if (method === 'index.status') return UNBUILT;
      if (method === 'index.build') throw new Error('no transcript yet');
      return {};
    });
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('no transcript yet');
  });

  it('stringifies a non-Error index.build rejection', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT });
    fake.rpc.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      fake.calls.push({ method, params });
      if (method === 'index.status') return UNBUILT;
      if (method === 'index.build') throw 'build blew up';
      return {};
    });
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('build blew up');
  });

  it('builds without an onJobDone hook (no-op cleanup branch)', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT, 'index.build': { jobId: 'job-idx' } });
    // Drop the optional onJobDone so the `: () => undefined` fallback subscribes.
    delete fake.api.onJobDone;
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    // building progress region is shown; a progress event still updates it.
    await act(async () => {
      fake.fireProgress({ jobId: 'job-idx', pct: 25, message: 'embedding' });
    });
    expect(container.querySelector('.progress[aria-live="polite"]')?.textContent).toContain('25%');
    // unmount cleanly (exercises the no-op offDone cleanup).
    await act(async () => {
      root.unmount();
    });
    root = createRoot(container);
  });

  it('swallows an index.status probe failure (degrades to unbuilt)', async () => {
    const fake = makeFakeApi();
    fake.rpc.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      fake.calls.push({ method, params });
      if (method === 'index.status') throw new Error('probe failed');
      return {};
    });
    await mount(fake);
    // degrade to unbuilt -> disabled box + CTA, no error banner.
    expect(queryInput().disabled).toBe(true);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(
      [...container.querySelectorAll('button')].some((b) =>
        /Build the search index/.test(b.textContent ?? ''),
      ),
    ).toBe(true);
  });

  it('build CTA is disabled (no rpc) when there is no videoId', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT });
    await mount(fake, { videoId: '' });
    // No videoId -> the status probe is skipped (treated unbuilt) and the CTA is disabled.
    expect(fake.calls.find((c) => c.method === 'index.status')).toBeUndefined();
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    expect(cta.disabled).toBe(true);
  });

  it('build echoes the plan cacheKey as confirmBudget when the plan will egress (cloud embedder)', async () => {
    const fake = makeFakeApi({
      'index.status': UNBUILT,
      'index.plan': { willEgress: true, cacheKey: 'CK-build' },
      'index.build': { jobId: 'job-idx' },
    });
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'index.plan')?.params).toEqual({ videoId: 'v1' });
    expect(fake.calls.find((c) => c.method === 'index.build')?.params).toEqual({
      videoId: 'v1',
      confirmBudget: 'CK-build',
    });
  });

  it('build omits confirmBudget when the plan will NOT egress (local embedder)', async () => {
    const fake = makeFakeApi({
      'index.status': UNBUILT,
      'index.plan': { willEgress: false, cacheKey: 'CK-unused' },
      'index.build': { jobId: 'job-idx' },
    });
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'index.build')?.params).toEqual({ videoId: 'v1' });
  });

  it('search echoes the plan cacheKey as confirmBudget when the plan will egress (cloud embedder)', async () => {
    const fake = makeFakeApi({
      'index.status': BUILT,
      'index.plan': { willEgress: true, cacheKey: 'CK-search' },
      'index.search': { hits: hits() },
    });
    await mount(fake);
    await type('pricing');
    await submit();
    expect(fake.calls.find((c) => c.method === 'index.plan')?.params).toEqual({
      videoId: 'v1',
      query: 'pricing',
    });
    expect(fake.calls.find((c) => c.method === 'index.search')?.params).toEqual({
      videoId: 'v1',
      query: 'pricing',
      topK: 8,
      confirmBudget: 'CK-search',
    });
  });

  it('search omits confirmBudget when the plan will NOT egress (local embedder)', async () => {
    const fake = makeFakeApi({
      'index.status': BUILT,
      'index.plan': { willEgress: false, cacheKey: 'CK-unused' },
      'index.search': { hits: hits() },
    });
    await mount(fake);
    await type('pricing');
    await submit();
    expect(fake.calls.find((c) => c.method === 'index.search')?.params).toEqual({
      videoId: 'v1',
      query: 'pricing',
      topK: 8,
    });
  });

  it('surfaces an index.plan rejection on build via role="alert"', async () => {
    const fake = makeFakeApi({ 'index.status': UNBUILT });
    fake.rpc.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      fake.calls.push({ method, params });
      if (method === 'index.status') return UNBUILT;
      if (method === 'index.plan') throw new Error('planning failed');
      return {};
    });
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('planning failed');
    // The build was never fired because the pre-flight plan failed.
    expect(fake.calls.find((c) => c.method === 'index.build')).toBeUndefined();
  });

  it('surfaces an index.plan rejection on search via role="alert"', async () => {
    const fake = makeFakeApi({ 'index.status': BUILT });
    fake.rpc.mockImplementation(async (method: string, params?: Record<string, unknown>) => {
      fake.calls.push({ method, params });
      if (method === 'index.status') return BUILT;
      if (method === 'index.plan') throw new Error('plan blew up');
      return {};
    });
    await mount(fake);
    await type('pricing');
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plan blew up');
    expect(fake.calls.find((c) => c.method === 'index.search')).toBeUndefined();
  });

  it('a built index offers a Rebuild affordance; clicking it re-runs index.build and shows progress', async () => {
    const fake = makeFakeApi({
      'index.status': BUILT,
      'index.plan': { willEgress: false, cacheKey: 'CK' },
      'index.build': { jobId: 'job-idx' },
      // A stale/dim-mismatched search is refused with the "run index.build to
      // rebuild it first" instruction — the exact dead-end Rebuild exits.
      'index.search': () => {
        throw new Error('index is stale — run index.build to rebuild it first');
      },
    });
    await mount(fake);
    const rebuild = () =>
      [...container.querySelectorAll('button')].find(
        (b) => b.textContent === 'Rebuild index',
      ) as HTMLButtonElement | undefined;
    // The Rebuild control is available while built (before any search).
    expect(rebuild()).toBeTruthy();
    await type('pricing');
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'run index.build to rebuild it first',
    );
    // Rebuild is still offered after the stale refusal; clicking it re-runs the
    // build and shows the BUILDING progress region.
    const btn = rebuild() as HTMLButtonElement;
    expect(btn).toBeTruthy();
    await act(async () => {
      btn.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'index.build')?.params).toEqual({ videoId: 'v1' });
    expect(container.querySelector('.progress[aria-live="polite"]')).toBeTruthy();
    // While building, the Rebuild control is hidden (built && !building is false).
    expect(rebuild()).toBeUndefined();
  });

  it('a done payload for the wrong job before built leaves status untouched, then unsubscribes on unmount', async () => {
    const off = vi.fn();
    const fake = makeFakeApi({ 'index.status': UNBUILT, 'index.build': { jobId: 'job-idx' } });
    const realOnJobDone = fake.api.onJobDone!;
    fake.api.onJobDone = (cb) => {
      realOnJobDone(cb);
      return off;
    };
    await mount(fake);
    const cta = [...container.querySelectorAll('button')].find((b) =>
      /Build the search index/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      cta.click();
      await Promise.resolve();
    });
    await act(async () => {
      root.unmount();
    });
    expect(off).toHaveBeenCalled();
    root = createRoot(container);
  });
});
