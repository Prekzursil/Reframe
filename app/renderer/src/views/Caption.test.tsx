// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Caption } from './Caption';
import type { Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const cuesMock = vi.fn();
const generateMock = vi.fn();
let hasApiReturn = true;

vi.mock('../lib/rpc', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/rpc')>();
  return {
    ...actual,
    hasApi: () => hasApiReturn,
    client: {
      ...actual.client,
      captions: { cues: (...args: unknown[]) => cuesMock(...args) },
      subtitles: {
        ...actual.client.subtitles,
        generate: (...args: unknown[]) => generateMock(...args),
      },
    },
  };
});

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
const onBack = vi.fn();

beforeEach(() => {
  cuesMock.mockReset();
  generateMock.mockReset();
  onBack.mockReset();
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
    root.render(<Caption video={video} onBack={onBack} />);
  });
}

describe('Caption view', () => {
  it('shows a no-video empty state that routes back to the Library', () => {
    render(null);
    expect(q('.caption-view__empty-title')?.textContent).toBe('Open a video to caption');
    act(() => q<HTMLButtonElement>('.caption-view__back')?.click());
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(cuesMock).not.toHaveBeenCalled();
  });

  it('loads existing cues via the typed client and shows the editing surface', async () => {
    cuesMock.mockResolvedValue({ cues: CUES });
    render(VIDEO);
    await flush();
    expect(cuesMock).toHaveBeenCalledWith('v1');
    expect(q('.caption-view__title')?.textContent).toBe('My Clip');
    expect(q('.caption-gallery')).not.toBeNull();
    expect(q('.caption-clip-lane')).not.toBeNull();
    expect(q('.caption-inspector__empty')).toBeNull();
  });

  it('gates on transcript, then generates + reloads cues on request', async () => {
    cuesMock.mockResolvedValueOnce({}).mockResolvedValueOnce({ cues: CUES });
    generateMock.mockResolvedValue({});
    render(VIDEO);
    await flush();
    // no cues yet -> the inspector's generate gate
    expect(q('.caption-inspector__empty')).not.toBeNull();
    act(() => q<HTMLButtonElement>('.caption-inspector__generate')?.click());
    await flush();
    expect(generateMock).toHaveBeenCalledWith('v1');
    expect(cuesMock).toHaveBeenCalledTimes(2);
    expect(q('.caption-gallery')).not.toBeNull();
  });

  it('surfaces a cue-load failure', async () => {
    cuesMock.mockRejectedValue(new Error('load boom'));
    render(VIDEO);
    await flush();
    expect(q('.caption-view__error')?.textContent).toBe('load boom');
  });

  it('stringifies a non-Error rejection', async () => {
    cuesMock.mockRejectedValue('weird failure');
    render(VIDEO);
    await flush();
    expect(q('.caption-view__error')?.textContent).toBe('weird failure');
  });

  it('surfaces a generate failure', async () => {
    cuesMock.mockResolvedValue({});
    generateMock.mockRejectedValue(new Error('gen boom'));
    render(VIDEO);
    await flush();
    act(() => q<HTMLButtonElement>('.caption-inspector__generate')?.click());
    await flush();
    expect(q('.caption-view__error')?.textContent).toBe('gen boom');
  });

  it('no-ops RPC when the bridge is unavailable', async () => {
    hasApiReturn = false;
    render(VIDEO);
    await flush();
    expect(cuesMock).not.toHaveBeenCalled();
    expect(q('.caption-inspector__empty')).not.toBeNull();
    act(() => q<HTMLButtonElement>('.caption-inspector__generate')?.click());
    await flush();
    expect(generateMock).not.toHaveBeenCalled();
  });
});
