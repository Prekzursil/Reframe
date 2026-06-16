// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Mock the bridge module so the view's rpc calls are controllable.
const rpcMock = vi.fn();
vi.mock('../components/api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: () => () => {},
  hasApi: () => true,
}));

import { Library, POSTER_SEEK_FRACTION, posterSeekTime } from './Library';
import type { Video } from '../components/api';

// ---------------------------------------------------------------------------
// T6 thumbnails: jsdom does not implement HTMLMediaElement; back the bits the
// poster thumbnail touches (pause/currentTime/duration) with deterministic
// per-element stores so tests can drive them (same pattern as Player.test.tsx).
// ---------------------------------------------------------------------------
const pauseMock = vi.fn();
const currentTimes = new WeakMap<HTMLMediaElement, number>();
const durations = new WeakMap<HTMLMediaElement, number>();

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    writable: true,
    value: pauseMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return currentTimes.get(this) ?? 0;
    },
    set(this: HTMLMediaElement, v: number) {
      currentTimes.set(this, v);
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'duration', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return durations.get(this) ?? Number.NaN;
    },
  });
});

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    id: 'v1',
    path: '/movies/talk.mp4',
    title: 'Talk',
    addedAt: '2026-06-11T00:00:00Z',
    durationSec: 605,
    hasTranscript: false,
    ...over,
  };
}

// P2 U2: the picker/drag-drop preload bridge (window.api.openVideos /
// window.api.pathForFile). Library reads it structurally at call time, so the
// tests install a fresh fake bridge per test.
const openVideosMock = vi.fn();
const pathForFileMock = vi.fn();

type TestWindow = Window & { api?: unknown };

function installBridge(overrides: Record<string, unknown> = {}): void {
  (window as TestWindow).api = {
    rpc: (...args: unknown[]) => rpcMock(...args),
    onProgress: () => () => {},
    openVideos: (...args: unknown[]) => openVideosMock(...args),
    pathForFile: (...args: unknown[]) => pathForFileMock(...args),
    ...overrides,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  openVideosMock.mockReset();
  pathForFileMock.mockReset();
  pauseMock.mockClear();
  installBridge();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (window as { api?: unknown }).api;
});

async function flush(turns = 8): Promise<void> {
  // Allow queued microtasks (the rpc/picker promises, sequential multi-add
  // loops) and effects to settle.
  await act(async () => {
    for (let i = 0; i < turns; i += 1) {
      await Promise.resolve();
    }
  });
}

async function renderLibrary(
  onOpen: (v: Video) => void = () => {},
  toast?: (t: { kind: string; message: string }) => void,
): Promise<void> {
  await act(async () => {
    root.render(<Library onOpen={onOpen} toast={toast} />);
  });
  await flush();
}

function addButton(): HTMLButtonElement {
  return container.querySelector('button.library__add-btn') as HTMLButtonElement;
}

async function clickAdd(): Promise<void> {
  await act(async () => {
    addButton().dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

/** Dispatch a native drop event carrying a synthetic DataTransfer file list. */
async function dropFiles(files: File[]): Promise<void> {
  const target = container.querySelector('div.library') as HTMLDivElement;
  const event = new Event('drop', { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'dataTransfer', { value: { files } });
  await act(async () => {
    target.dispatchEvent(event);
  });
  await flush();
}

function errorToasts(): string[] {
  return [...container.querySelectorAll('.library__toast--error')].map(
    (el) => el.textContent ?? '',
  );
}

describe('Library', () => {
  it('lists videos from library.list', async () => {
    rpcMock.mockResolvedValueOnce({
      videos: [makeVideo(), makeVideo({ id: 'v2', title: 'Second' })],
    });
    await renderLibrary();

    expect(rpcMock).toHaveBeenCalledWith('library.list');
    expect(container.textContent).toContain('Talk');
    expect(container.textContent).toContain('Second');
    // 605s -> 10:05
    expect(container.textContent).toContain('10:05');
  });

  it('shows the empty state when there are no videos', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();
    expect(container.textContent).toContain('No videos yet');
  });

  it('multi-adds videos picked via the native dialog (window.api.openVideos)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] }); // initial list
    await renderLibrary();

    openVideosMock.mockResolvedValueOnce(['/clips/a.mp4', '/clips/b.mp4']);
    rpcMock
      .mockResolvedValueOnce({
        video: makeVideo({ id: 'a', title: 'Clip A', path: '/clips/a.mp4' }),
      })
      .mockResolvedValueOnce({
        video: makeVideo({ id: 'b', title: 'Clip B', path: '/clips/b.mp4' }),
      });

    await clickAdd();

    expect(openVideosMock).toHaveBeenCalledTimes(1);
    expect(rpcMock).toHaveBeenCalledWith('library.add', { path: '/clips/a.mp4' });
    expect(rpcMock).toHaveBeenCalledWith('library.add', { path: '/clips/b.mp4' });
    expect(container.textContent).toContain('Clip A');
    expect(container.textContent).toContain('Clip B');
    expect(container.textContent).toContain('Added 2 videos');
  });

  it('does nothing when the picker is cancelled (empty path list)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    openVideosMock.mockResolvedValueOnce([]);
    await clickAdd();

    // Only the initial library.list call — no library.add.
    expect(rpcMock).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll('.library__toast').length).toBe(0);
  });

  it('shows a typed error toast when the openVideos bridge is missing', async () => {
    installBridge({ openVideos: undefined });
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    await clickAdd();

    expect(errorToasts().join(' ')).toContain('Native file picker unavailable');
    expect(rpcMock).toHaveBeenCalledTimes(1); // list only
  });

  it('adds dropped files via drag-drop using the pathForFile bridge (Electron >=32)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    // webUtils.getPathForFile stand-in: name -> absolute path.
    pathForFileMock.mockImplementation((file: File) => `/dropped/${file.name}`);
    rpcMock
      .mockResolvedValueOnce({
        video: makeVideo({ id: 'd1', title: 'Drop One', path: '/dropped/a.mp4' }),
      })
      .mockResolvedValueOnce({
        video: makeVideo({ id: 'd2', title: 'Drop Two', path: '/dropped/b.mp4' }),
      });

    await dropFiles([new File(['x'], 'a.mp4'), new File(['y'], 'b.mp4')]);

    expect(pathForFileMock).toHaveBeenCalledTimes(2);
    expect(rpcMock).toHaveBeenCalledWith('library.add', { path: '/dropped/a.mp4' });
    expect(rpcMock).toHaveBeenCalledWith('library.add', { path: '/dropped/b.mp4' });
    expect(container.textContent).toContain('Drop One');
    expect(container.textContent).toContain('Drop Two');
  });

  it('falls back to legacy File.path when pathForFile is absent', async () => {
    installBridge({ pathForFile: undefined });
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    const file = new File(['x'], 'c.mp4');
    Object.defineProperty(file, 'path', { value: '/legacy/c.mp4' });
    rpcMock.mockResolvedValueOnce({
      video: makeVideo({ id: 'c', title: 'Legacy C', path: '/legacy/c.mp4' }),
    });

    await dropFiles([file]);

    expect(rpcMock).toHaveBeenCalledWith('library.add', { path: '/legacy/c.mp4' });
    expect(container.textContent).toContain('Legacy C');
  });

  it('emits a per-file error toast for a dropped file with no recoverable path', async () => {
    installBridge({ pathForFile: undefined });
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    await dropFiles([new File(['x'], 'nopath.mp4')]);

    expect(errorToasts().join(' ')).toContain('nopath.mp4');
    expect(errorToasts().join(' ')).toContain('no filesystem path');
    expect(rpcMock).toHaveBeenCalledTimes(1); // list only, no add
  });

  it('de-duplicates by id when the same video is added twice', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    pathForFileMock.mockImplementation((file: File) => `/dropped/${file.name}`);
    const dup = makeVideo({ id: 'dup', title: 'Same Video', path: '/dropped/same.mp4' });
    rpcMock.mockResolvedValueOnce({ video: dup }).mockResolvedValueOnce({ video: dup });

    await dropFiles([new File(['x'], 'same.mp4'), new File(['x'], 'same-copy.mp4')]);

    expect(container.querySelectorAll('li.library__item').length).toBe(1);
    expect(container.textContent).toContain('Same Video');
  });

  it('surfaces a per-file typed error toast but continues the batch (bad-file path)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    openVideosMock.mockResolvedValueOnce(['/clips/bad.bin', '/clips/good.mp4']);
    rpcMock.mockRejectedValueOnce(new Error('not a video file')).mockResolvedValueOnce({
      video: makeVideo({ id: 'g', title: 'Good', path: '/clips/good.mp4' }),
    });

    await clickAdd();

    const errors = errorToasts().join(' ');
    expect(errors).toContain('bad.bin');
    expect(errors).toContain('not a video file');
    // The good file still landed.
    expect(container.textContent).toContain('Good');
    expect(container.textContent).toContain('Added 1 video');
  });

  it('routes toasts to the external toast prop when provided (U3 integration seam)', async () => {
    installBridge({ openVideos: undefined });
    const toastSpy = vi.fn();
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary(() => {}, toastSpy);

    await clickAdd();

    expect(toastSpy).toHaveBeenCalledWith({
      kind: 'error',
      message: expect.stringContaining('Native file picker unavailable'),
    });
    // No local fallback strip when the external sink is wired.
    expect(container.querySelectorAll('.library__toast').length).toBe(0);
  });

  it('removes a video via library.remove', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    await renderLibrary();
    expect(container.textContent).toContain('Talk');

    rpcMock.mockResolvedValueOnce({ ok: true });
    const removeBtn = container.querySelector('button.library__remove-btn') as HTMLButtonElement;
    await act(async () => {
      removeBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    expect(rpcMock).toHaveBeenCalledWith('library.remove', { id: 'v1' });
    expect(container.textContent).not.toContain('Talk');
  });

  it('opens a video on click (calls onOpen)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    const onOpen = vi.fn();
    await renderLibrary(onOpen);

    const item = container.querySelector('li.library__item') as HTMLLIElement;
    await act(async () => {
      item.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0].id).toBe('v1');
  });

  it('surfaces a list error', async () => {
    rpcMock.mockRejectedValueOnce(new Error('sidecar down'));
    await renderLibrary();
    expect(container.textContent).toContain('sidecar down');
  });
});

// ---------------------------------------------------------------------------
// T6: poster-frame thumbnails + duration badge
// ---------------------------------------------------------------------------

describe('posterSeekTime', () => {
  it('is ~10% of the duration', () => {
    expect(POSTER_SEEK_FRACTION).toBe(0.1);
    expect(posterSeekTime(605)).toBeCloseTo(60.5);
    expect(posterSeekTime(20)).toBeCloseTo(2);
  });

  it('is 0 for unknown/invalid durations', () => {
    expect(posterSeekTime(0)).toBe(0);
    expect(posterSeekTime(-3)).toBe(0);
    expect(posterSeekTime(Number.NaN)).toBe(0);
  });
});

describe('Library thumbnails (T6)', () => {
  function thumbVideo(): HTMLVideoElement {
    return container.querySelector('video.library__thumb-video') as HTMLVideoElement;
  }

  it('renders a muted metadata-only poster <video> on the mstream URL per card', async () => {
    rpcMock.mockResolvedValueOnce({
      videos: [makeVideo(), makeVideo({ id: 'v 2', title: 'Second' })],
    });
    await renderLibrary();

    const thumbs = container.querySelectorAll('video.library__thumb-video');
    expect(thumbs.length).toBe(2);
    const first = thumbs[0] as HTMLVideoElement;
    // Same URL convention as components/Player.tsx (id percent-encoded).
    expect(first.getAttribute('src')).toBe('mstream://media/v1');
    expect((thumbs[1] as HTMLVideoElement).getAttribute('src')).toBe('mstream://media/v%202');
    expect(first.muted).toBe(true);
    expect(first.getAttribute('preload')).toBe('metadata');
    // jsdom never fires loadedmetadata on its own — no playback was requested.
  });

  it('shows a duration badge formatted mm:ss from durationSec', async () => {
    rpcMock.mockResolvedValueOnce({
      videos: [makeVideo(), makeVideo({ id: 'h1', title: 'Long', durationSec: 3725 })],
    });
    await renderLibrary();

    const badges = [...container.querySelectorAll('.library__thumb-duration')].map(
      (el) => el.textContent,
    );
    expect(badges).toEqual(['10:05', '1:02:05']); // 605s and 3725s
  });

  it('pauses immediately and seeks to ~10% of the element duration on loadedmetadata', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    await renderLibrary();

    const video = thumbVideo();
    durations.set(video, 200); // metadata-reported duration wins when finite
    await act(async () => {
      video.dispatchEvent(new Event('loadedmetadata'));
    });

    expect(pauseMock).toHaveBeenCalledTimes(1);
    expect(video.currentTime).toBeCloseTo(20); // 10% of 200
  });

  it('falls back to the library durationSec when the element duration is unknown', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] }); // durationSec: 605
    await renderLibrary();

    const video = thumbVideo(); // stubbed duration stays NaN
    await act(async () => {
      video.dispatchEvent(new Event('loadedmetadata'));
    });

    expect(video.currentTime).toBeCloseTo(60.5); // 10% of 605
  });

  it('replaces the video with a placeholder on media error, keeping the badge', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    await renderLibrary();

    const video = thumbVideo();
    await act(async () => {
      video.dispatchEvent(new Event('error'));
    });

    expect(container.querySelector('video.library__thumb-video')).toBeNull();
    expect(container.querySelector('.library__thumb-fallback')).not.toBeNull();
    expect(container.querySelector('.library__thumb-duration')?.textContent).toBe('10:05');
  });
});
