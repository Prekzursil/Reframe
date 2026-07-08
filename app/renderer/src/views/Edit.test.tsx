// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// The Workspace is the heavy per-video body (owns its own tests); stub it, but
// expose the initialTab Edit threads in (the Task Hub deep-link).
vi.mock('./Workspace', () => ({
  Workspace: ({
    video,
    onBack,
    initialTab,
  }: {
    video: Video;
    onBack: () => void;
    initialTab?: string;
  }) => (
    <div data-testid="workspace" data-video-id={video.id} data-initial-tab={initialTab ?? ''}>
      <button type="button" onClick={onBack}>
        back
      </button>
    </div>
  ),
}));

// The Task Hub owns its own tests; stub it to expose the choices Edit routes on.
vi.mock('./TaskHub', () => ({
  TaskHub: ({
    video,
    lastChoice,
    onChoose,
  }: {
    video: Video;
    lastChoice: string | null;
    onChoose: (c: string) => void;
  }) => (
    <div data-testid="taskhub" data-video-id={video.id} data-last={lastChoice ?? ''}>
      {['reframe', 'subtitles', 'shorts', 'director', 'advanced'].map((c) => (
        <button key={c} type="button" onClick={() => onChoose(c)}>
          {c}
        </button>
      ))}
    </div>
  ),
}));

// Control the persistence surface (hasApi gate + the settings.get/set RPC).
const rpcMock = vi.fn();
let hasApiReturn = true;
vi.mock('../lib/rpc', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  hasApi: () => hasApiReturn,
}));

import { Edit } from './Edit';
import { HUB_CHOICE_KEY } from '../lib/taskHub';

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    id: 'v1',
    path: '/m/a.mp4',
    title: 'A',
    addedAt: '2026-06-27T00:00:00Z',
    durationSec: 100,
    hasTranscript: false,
    ...over,
  };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('<Edit />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({}); // settings.get → no remembered choice
    hasApiReturn = true;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function hub(): HTMLElement {
    return container.querySelector('[data-testid="taskhub"]') as HTMLElement;
  }
  function workspace(): HTMLElement | null {
    return container.querySelector('[data-testid="workspace"]');
  }
  function pick(choice: string): void {
    const btn = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === choice,
    );
    if (!btn) throw new Error(`hub choice "${choice}" not found`);
    act(() => btn.click());
  }

  it('shows the empty state when no video is open', () => {
    act(() => root.render(<Edit video={null} onBack={() => undefined} />));
    expect(container.querySelector('.edit--empty')).toBeTruthy();
    expect(container.querySelector('.edit__empty-title')?.textContent).toBe('No video open');
    // WU-D3: the empty carries the shared ghost-poster anchor (poster + glyph),
    // not the old bare sentence.
    expect(container.querySelector('.edit__empty-poster')).toBeTruthy();
    expect(container.querySelector('.edit__empty-glyph')).toBeTruthy();
    expect(hub()).toBeNull();
    expect(workspace()).toBeNull();
  });

  it('lands on the Task Hub (not the Workspace) when a video is opened', async () => {
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    expect(hub()).toBeTruthy();
    expect(hub().getAttribute('data-video-id')).toBe('v1');
    expect(workspace()).toBeNull();
    expect(rpcMock).toHaveBeenCalledWith('settings.get');
  });

  it('routes the reframe card into the Workspace at the Short-maker tab + persists', async () => {
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    pick('reframe');
    expect(workspace()).toBeTruthy();
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('shortmaker');
    expect(rpcMock).toHaveBeenCalledWith('settings.set', {
      [HUB_CHOICE_KEY]: { v1: 'reframe' },
    });
  });

  it('routes the subtitles card into the Workspace at the Subtitles tab', async () => {
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    pick('subtitles');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('subtitles');
  });

  it('routes the advanced escape into the Workspace default tab (no initial tab)', async () => {
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    pick('advanced');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('');
  });

  it('routes the section cards to the App callbacks and stays on the hub', async () => {
    const onMakeShorts = vi.fn();
    const onDirector = vi.fn();
    act(() =>
      root.render(
        <Edit
          video={makeVideo()}
          onBack={() => undefined}
          onMakeShorts={onMakeShorts}
          onDirector={onDirector}
        />,
      ),
    );
    await flush();
    pick('shorts');
    expect(onMakeShorts).toHaveBeenCalledTimes(1);
    pick('director');
    expect(onDirector).toHaveBeenCalledTimes(1);
    // section cards do not switch to the Workspace (they leave via the App shell).
    expect(workspace()).toBeNull();
  });

  it('tolerates section cards when no App callbacks are wired', async () => {
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    pick('shorts');
    pick('director');
    expect(hub()).toBeTruthy();
  });

  it('resumes a workspace-scoped remembered choice in place (skips the hub)', async () => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({ [HUB_CHOICE_KEY]: { v1: 'subtitles' } });
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    expect(hub()).toBeNull();
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('subtitles');
  });

  it('marks a remembered section choice but stays on the hub', async () => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({ [HUB_CHOICE_KEY]: { v1: 'shorts' } });
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    expect(hub()).toBeTruthy();
    expect(hub().getAttribute('data-last')).toBe('shorts');
  });

  it('tolerates a null settings payload (stays on the hub)', async () => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue(null);
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    expect(hub()).toBeTruthy();
    expect(hub().getAttribute('data-last')).toBe('');
  });

  it('tolerates a settings.get rejection (stays on the hub)', async () => {
    rpcMock.mockReset();
    rpcMock.mockRejectedValue(new Error('read failed'));
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    expect(hub()).toBeTruthy();
  });

  it('does not touch settings when the preload bridge is absent', async () => {
    hasApiReturn = false;
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    expect(rpcMock).not.toHaveBeenCalled();
    // a choice still routes (in-memory), just without a settings.set.
    pick('reframe');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('shortmaker');
    expect(rpcMock).not.toHaveBeenCalled();
  });

  it('re-reads the remembered choice when the opened video changes', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') {
        return Promise.resolve({ [HUB_CHOICE_KEY]: { v1: 'reframe', v2: 'subtitles' } });
      }
      return Promise.resolve({});
    });
    act(() => root.render(<Edit video={makeVideo({ id: 'v1' })} onBack={() => undefined} />));
    await flush();
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('shortmaker');
    // switch to a different video: the effect re-runs and resumes v2's choice.
    act(() => root.render(<Edit video={makeVideo({ id: 'v2' })} onBack={() => undefined} />));
    await flush();
    expect(workspace()!.getAttribute('data-video-id')).toBe('v2');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('subtitles');
  });

  it('preserves other videos when persisting a choice (read-modify-write)', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') {
        return Promise.resolve({ [HUB_CHOICE_KEY]: { v2: 'director' } });
      }
      return Promise.resolve({});
    });
    act(() => root.render(<Edit video={makeVideo({ id: 'v1' })} onBack={() => undefined} />));
    await flush();
    pick('reframe');
    expect(rpcMock).toHaveBeenCalledWith('settings.set', {
      [HUB_CHOICE_KEY]: { v2: 'director', v1: 'reframe' },
    });
  });

  it('ignores a settings.get that resolves after unmount', async () => {
    let resolveGet: (v: unknown) => void = () => undefined;
    rpcMock.mockReset();
    rpcMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGet = resolve;
        }),
    );
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    // unmount BEFORE the settings.get resolves → the late result must be ignored.
    act(() => root.unmount());
    await act(async () => {
      resolveGet({ [HUB_CHOICE_KEY]: { v1: 'subtitles' } });
      await Promise.resolve();
    });
    // nothing rendered (still unmounted); no throw.
    expect(container.querySelector('[data-testid="workspace"]')).toBeNull();
    // re-mount so afterEach's unmount is a safe no-op.
    root = createRoot(container);
  });

  it('forwards the Workspace back control', async () => {
    const onBack = vi.fn();
    act(() => root.render(<Edit video={makeVideo()} onBack={onBack} />));
    await flush();
    pick('advanced');
    act(() =>
      (container.querySelector('[data-testid="workspace"] button') as HTMLButtonElement).click(),
    );
    expect(onBack).toHaveBeenCalled();
  });
});
