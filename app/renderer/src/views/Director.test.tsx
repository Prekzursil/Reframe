// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Video } from '../lib/rpc';
import { Director } from './Director';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const cuesMock = vi.fn();
let hasApiReturn = true;

vi.mock('../lib/rpc', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/rpc')>();
  return {
    ...actual,
    hasApi: () => hasApiReturn,
    client: {
      ...actual.client,
      captions: { cues: (...args: unknown[]) => cuesMock(...args) },
    },
  };
});

// The DirectorPanel owns its own comprehensive tests; stub it so the view test
// exercises ONLY the screen (shell + EditorContext seeding + cue load + hand-off).
// The marker echoes the threaded video id + exposes the empty-state CTA.
vi.mock('../panels/DirectorPanel', () => ({
  DirectorPanel: ({
    video,
    onChooseVideo,
  }: {
    video: Video | null;
    onChooseVideo?: () => void;
  }) => (
    <div data-testid="director-panel" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onChooseVideo}>
        choose-video
      </button>
    </div>
  ),
}));

const VIDEO: Video = {
  id: 'v1',
  path: '/clips/x.mp4',
  title: 'My Clip',
  addedAt: '2026-01-01',
  durationSec: 20,
  hasTranscript: false,
};
const CUES = [
  { index: 1, start: 2, end: 3, text: 'Hello' },
  { index: 2, start: 6, end: 7, text: 'world' },
];

let container: HTMLDivElement;
let root: Root;
const onChooseVideo = vi.fn();

beforeEach(() => {
  cuesMock.mockReset();
  onChooseVideo.mockReset();
  hasApiReturn = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function render(video: Video | null): void {
  act(() => {
    root.render(<Director video={video} onChooseVideo={onChooseVideo} />);
  });
}

describe('Director view', () => {
  it('renders the editorial shell with the serif hero + the DirectorPanel', () => {
    render(null);
    expect(q('.director-view__title')?.textContent).toBe('Direct the edit');
    expect(q('[data-testid="director-panel"]')).not.toBeNull();
  });

  it('shows the DirectorPanel empty state (no hand-off) when no video is open', () => {
    render(null);
    // No video -> the DirectorPanel carries its own "No video open" CTA; the
    // per-phase hand-off (which needs editor state) is not mounted.
    expect(q('[data-testid="director-panel"]')?.getAttribute('data-video-id')).toBe('');
    expect(q('.director-handoff')).toBeNull();
    expect(cuesMock).not.toHaveBeenCalled();
  });

  it('routes back to the Library from the shell back control', () => {
    render(null);
    act(() => q<HTMLButtonElement>('.director-view__back')?.click());
    expect(onChooseVideo).toHaveBeenCalledTimes(1);
  });

  it('threads the DirectorPanel CTA back to the Library', () => {
    render(null);
    act(() => q<HTMLButtonElement>('[data-testid="director-panel"] button')?.click());
    expect(onChooseVideo).toHaveBeenCalledTimes(1);
  });

  it('seeds the editor, loads cues via the typed client, and shows the hand-off', async () => {
    cuesMock.mockResolvedValue({ cues: CUES });
    render(VIDEO);
    await flush();
    expect(cuesMock).toHaveBeenCalledWith('v1');
    expect(q('[data-testid="director-panel"]')?.getAttribute('data-video-id')).toBe('v1');
    expect(q('.director-handoff')).not.toBeNull();
    // The loaded transcript makes the Caption landing zone read as ready.
    expect(q('[data-phase="caption"]')?.getAttribute('data-ready')).toBe('yes');
    expect(q('.director-view__error')).toBeNull();
  });

  it('handles an empty cues payload as a pending Caption zone', async () => {
    cuesMock.mockResolvedValue({});
    render(VIDEO);
    await flush();
    expect(q('[data-phase="caption"]')?.getAttribute('data-ready')).toBe('no');
    expect(q('.director-view__error')).toBeNull();
  });

  it('surfaces a cue-load failure as an alert', async () => {
    cuesMock.mockRejectedValue(new Error('load boom'));
    render(VIDEO);
    await flush();
    expect(q('.director-view__error')?.textContent).toBe('load boom');
    expect(q('.director-view__error')?.getAttribute('role')).toBe('alert');
  });

  it('stringifies a non-Error rejection', async () => {
    cuesMock.mockRejectedValue('weird failure');
    render(VIDEO);
    await flush();
    expect(q('.director-view__error')?.textContent).toBe('weird failure');
  });

  it('no-ops the cue RPC when the preload bridge is unavailable', async () => {
    hasApiReturn = false;
    render(VIDEO);
    await flush();
    expect(cuesMock).not.toHaveBeenCalled();
    // The hand-off still renders; its Caption zone is simply pending.
    expect(q('.director-handoff')).not.toBeNull();
    expect(q('[data-phase="caption"]')?.getAttribute('data-ready')).toBe('no');
  });
});
