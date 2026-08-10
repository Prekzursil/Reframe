// Transcribe.rehydrate.test.tsx — W11: the panel must RE-HYDRATE a persisted
// transcript at mount.
//
// The sidecar persists the finished transcript onto the video's project manifest
// (`handlers/media_ops.py:480-488` `_transcribe_and_persist`) and flips the
// library `hasTranscript` flag, and `project.open({id})` returns it as
// `{project:{transcript}}` (`handlers/library_ops.py:328-337`, CONTRACTS.md §2/§3).
// Before this file, `setTranscript`'s ONLY writer was inside `runTranscription`,
// so re-entering the tab after a completed run showed the BLANK state and offered
// an accent "Start transcription" for a multi-minute GPU job already done.
//
// These tests assert the mount-time READ ITSELF (the `project.open` call and its
// params), not merely that the component renders — a panel that never calls the
// RPC cannot fail a render-only assertion, which is exactly why 100% coverage
// never saw this.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Transcribe from './Transcribe';
import type { MediaStudioApi, Transcript } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
}

function persistedTranscript(over: Partial<Transcript> = {}): Transcript {
  return {
    language: 'ro',
    durationSec: 42.5,
    segments: [
      { start: 0, end: 2, text: 'Buna ziua', words: [{ text: 'Buna', start: 0, end: 1 }] },
      { start: 2, end: 4, text: 'ce faci', words: [{ text: 'ce', start: 2, end: 3 }] },
    ],
    ...over,
  };
}

/** A bridge whose `project.open` resolves whatever the test hands it. */
function makeFakeApi(openResult: unknown = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'project.open') return openResult as T;
      if (method === 'transcribe.start') return { jobId: 'job-t' } as T;
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: () => () => undefined,
    onJobDone: () => () => undefined,
  };
  return { api, calls };
}

describe('<Transcribe /> persisted-transcript rehydrate (W11)', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    vi.useRealTimers();
    await act(async () => {
      root.unmount();
    });
    container.remove();
    delete (globalThis as { api?: unknown }).api;
    vi.restoreAllMocks();
  });

  function install(fake: FakeApi): void {
    (globalThis as { api?: unknown }).api = fake.api;
  }

  async function mount(videoId = 'v1'): Promise<void> {
    await act(async () => {
      root.render(<Transcribe videoId={videoId} />);
    });
  }

  function startBtn(): HTMLButtonElement {
    return [...container.querySelectorAll('button')].find((b) =>
      /transcription|Transcribing/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
  }

  it('READS the persisted transcript at mount via project.open({id})', async () => {
    const fake = makeFakeApi({ project: { transcript: persistedTranscript() } });
    install(fake);
    await mount('v1');

    // The READ itself — asserted against literal expected values, not against
    // whatever the component happened to send.
    expect(fake.calls[0]).toEqual({ method: 'project.open', params: { id: 'v1' } });
    // ...and no GPU job was kicked off to obtain it.
    expect(fake.calls.some((c) => c.method === 'transcribe.start')).toBe(false);
  });

  it('renders the persisted transcript summary + segments without a run', async () => {
    const fake = makeFakeApi({ project: { transcript: persistedTranscript() } });
    install(fake);
    await mount('v1');

    const summary = container.querySelector('.transcript-summary');
    expect(summary).toBeTruthy();
    expect(summary?.textContent).toContain('ro');
    expect(summary?.textContent).toContain('42.5s');
    expect(container.querySelectorAll('.transcript-segments li').length).toBe(2);
    // No progress rail: nothing ran, so nothing may claim to have run.
    expect(container.querySelector('.progress')).toBeNull();
  });

  it('demotes the primary action to a secondary "Re-run transcription" once a transcript exists', async () => {
    const fake = makeFakeApi({ project: { transcript: persistedTranscript() } });
    install(fake);
    await mount('v1');

    const btn = startBtn();
    expect(btn.textContent).toContain('Re-run transcription');
    expect(btn.className).toContain('secondary');
    // Still clickable — a re-run is legitimate, just no longer invited.
    expect(btn.disabled).toBe(false);
  });

  it('keeps the accent "Start transcription" primary when the project has no transcript', async () => {
    const fake = makeFakeApi({ project: { transcript: undefined } });
    install(fake);
    await mount('v1');

    const btn = startBtn();
    expect(btn.textContent).toContain('Start transcription');
    expect(btn.className).not.toContain('secondary');
    expect(container.querySelector('.transcript-summary')).toBeNull();
    // The empty state says so out loud instead of showing a bare button.
    expect(container.querySelector('[data-state="empty"]')).toBeTruthy();
  });

  it('shows a loading state and blocks Start while the read is in flight', async () => {
    const fake = makeFakeApi();
    let resolveOpen: (v: unknown) => void = () => undefined;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation((method: string) =>
      method === 'project.open'
        ? new Promise((res) => {
            resolveOpen = res;
          })
        : Promise.resolve({}),
    );
    install(fake);
    await mount('v1');

    expect(container.querySelector('[data-state="loading"]')).toBeTruthy();
    expect(startBtn().disabled).toBe(true);
    // Neither the empty state nor a summary may be claimed before the read lands.
    expect(container.querySelector('[data-state="empty"]')).toBeNull();
    expect(container.querySelector('.transcript-summary')).toBeNull();

    await act(async () => {
      resolveOpen({ project: { transcript: persistedTranscript() } });
      await Promise.resolve();
    });
    expect(container.querySelector('[data-state="loading"]')).toBeNull();
    expect(container.querySelector('.transcript-summary')?.textContent).toContain('ro');
    expect(startBtn().disabled).toBe(false);
  });

  it('skips the read entirely when there is no videoId', async () => {
    const fake = makeFakeApi({ project: { transcript: persistedTranscript() } });
    install(fake);
    await mount('');

    expect(fake.calls).toHaveLength(0);
    expect(container.querySelector('[data-state="loading"]')).toBeNull();
  });

  it('re-reads when videoId changes and drops the previous video transcript', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      async (method: string, params?: Record<string, unknown>) => {
        fake.calls.push({ method, params });
        if (method !== 'project.open') return {};
        return params?.id === 'v1'
          ? { project: { transcript: persistedTranscript({ language: 'ro' }) } }
          : { project: {} };
      },
    );
    install(fake);
    await mount('v1');
    expect(container.querySelector('.transcript-summary')?.textContent).toContain('ro');

    await act(async () => {
      root.render(<Transcribe videoId="v2" />);
    });
    expect(fake.calls.filter((c) => c.method === 'project.open').map((c) => c.params)).toEqual([
      { id: 'v1' },
      { id: 'v2' },
    ]);
    // v1's transcript must not linger on v2.
    expect(container.querySelector('.transcript-summary')).toBeNull();
    expect(container.querySelector('[data-state="empty"]')).toBeTruthy();
  });

  it('surfaces a failed read as a non-blocking note and still allows a run', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation((method: string) =>
      method === 'project.open'
        ? Promise.reject(new Error('manifest unreadable'))
        : Promise.resolve({ jobId: 'job-t' }),
    );
    install(fake);
    await mount('v1');

    const note = container.querySelector('[data-state="load-error"]');
    expect(note?.textContent).toContain('manifest unreadable');
    // A failed READ is not a failed RUN: no error alert, and Start is live.
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(startBtn().disabled).toBe(false);
  });

  it('stringifies a non-Error read rejection', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation((method: string) =>
      method === 'project.open' ? Promise.reject('boom-string') : Promise.resolve({}),
    );
    install(fake);
    await mount('v1');

    expect(container.querySelector('[data-state="load-error"]')?.textContent).toContain(
      'boom-string',
    );
  });

  it('tolerates a null / transcript-less project payload', async () => {
    const fake = makeFakeApi(null);
    install(fake);
    await mount('v1');

    expect(container.querySelector('.transcript-summary')).toBeNull();
    expect(container.querySelector('[data-state="empty"]')).toBeTruthy();
    expect(container.querySelector('[data-state="load-error"]')).toBeNull();
  });

  it('ignores a stale in-flight read that resolves after videoId changed', async () => {
    const fake = makeFakeApi();
    const resolvers: Record<string, (v: unknown) => void> = {};
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      (method: string, params?: Record<string, unknown>) => {
        fake.calls.push({ method, params });
        if (method !== 'project.open') return Promise.resolve({});
        return new Promise((res) => {
          resolvers[String(params?.id)] = res;
        });
      },
    );
    install(fake);
    await mount('v1');
    await act(async () => {
      root.render(<Transcribe videoId="v2" />);
    });
    // v1's read lands LATE, after the panel already moved to v2.
    await act(async () => {
      resolvers.v1({ project: { transcript: persistedTranscript({ language: 'ro' }) } });
      await Promise.resolve();
    });
    expect(container.querySelector('.transcript-summary')).toBeNull();

    // v2's own read is still authoritative.
    await act(async () => {
      resolvers.v2({ project: { transcript: persistedTranscript({ language: 'sv' }) } });
      await Promise.resolve();
    });
    expect(container.querySelector('.transcript-summary')?.textContent).toContain('sv');
  });

  it('still hydrates under StrictMode double-invoked effects', async () => {
    // `main.tsx:19` wraps the real app in <React.StrictMode>, so in dev every
    // effect runs setup -> cleanup -> setup. The stale guard MUST be per-run
    // (a closure flag), not a component-lifetime ref: a guard that survives the
    // cleanup would discard BOTH reads and leave the panel stuck on "Loading".
    const fake = makeFakeApi({ project: { transcript: persistedTranscript() } });
    install(fake);
    await act(async () => {
      root.render(
        <StrictMode>
          <Transcribe videoId="v1" />
        </StrictMode>,
      );
    });
    expect(container.querySelector('[data-state="loading"]')).toBeNull();
    expect(container.querySelector('.transcript-summary')?.textContent).toContain('ro');
  });

  it('ignores a stale in-flight read that REJECTS after videoId changed', async () => {
    // The failure twin of the test above: v1's read blows up late, after the
    // panel already moved to v2. Painting v1's failure over v2 would tell the
    // user v2's saved transcript is unreadable when it was never even read.
    const fake = makeFakeApi();
    const rejecters: Record<string, (e: unknown) => void> = {};
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      (method: string, params?: Record<string, unknown>) => {
        fake.calls.push({ method, params });
        if (method !== 'project.open') return Promise.resolve({});
        return new Promise((_res, rej) => {
          rejecters[String(params?.id)] = rej;
        });
      },
    );
    install(fake);
    await mount('v1');
    await act(async () => {
      root.render(<Transcribe videoId="v2" />);
    });
    await act(async () => {
      rejecters.v1(new Error('v1 manifest unreadable'));
      await Promise.resolve();
    });
    expect(container.querySelector('[data-state="load-error"]')).toBeNull();
    // v2 is still legitimately loading — the stale failure did not settle it.
    expect(container.querySelector('[data-state="loading"]')).toBeTruthy();

    // v2's OWN failure does surface.
    await act(async () => {
      rejecters.v2(new Error('v2 manifest unreadable'));
      await Promise.resolve();
    });
    expect(container.querySelector('[data-state="load-error"]')?.textContent).toContain(
      'v2 manifest unreadable',
    );
  });
});
