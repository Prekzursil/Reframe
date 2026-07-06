// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Mock the bridge module so the view's rpc calls are controllable.
const rpcMock = vi.fn();
vi.mock('../components/api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: () => () => {},
  hasApi: () => true,
}));

// WU-14: the library home renders <ReadinessRollup>, which loads
// `readiness.summary` through the canonical lib/rpc `client`. Stub that client so
// the roll-up resolves to an empty set in these tests (the roll-up has its own
// dedicated suite); the rest of lib/rpc stays real for the type re-exports.
const readinessSummaryMock = vi.fn(
  async (): Promise<{ items: ReadinessItem[] }> => ({ items: [] }),
);
vi.mock('../lib/rpc', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/rpc')>();
  return {
    ...actual,
    client: { ...actual.client, readiness: { summary: () => readinessSummaryMock() } },
  };
});

import { Library } from './Library';
import type { Video } from '../components/api';
import type { ReadinessItem } from '../lib/rpc';
import { videoThumbnailSrc } from '../components/useVideoThumbnail';

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    id: 'v1',
    path: '/movies/talk.mp4',
    title: 'Talk',
    addedAt: '2026-06-11T00:00:00Z',
    durationSec: 605,
    hasTranscript: false,
    // WU-14: an already-persisted poster path serves immediately via
    // useVideoThumbnail (no on-demand `library.thumbnail` rpc), so the existing
    // rpc-call-count assertions stay exact. Thumbnail-specific tests override it.
    thumbnailPath: '/data/thumbnails/v1.jpg',
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
  readinessSummaryMock.mockClear();
  readinessSummaryMock.mockResolvedValue({ items: [] });
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

    // A11Y: the open affordance is now the inner <button>, not the <li> itself.
    const open = container.querySelector('.library__item-open') as HTMLButtonElement;
    await act(async () => {
      open.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0].id).toBe('v1');
  });

  it('surfaces a list error', async () => {
    rpcMock.mockRejectedValueOnce(new Error('sidecar down'));
    await renderLibrary();
    expect(container.textContent).toContain('sidecar down');
  });

  it('stringifies a non-Error list rejection', async () => {
    rpcMock.mockRejectedValueOnce('plain string failure');
    await renderLibrary();
    expect(container.querySelector('.library__error')?.textContent).toContain(
      'plain string failure',
    );
  });

  it('emits a typed error toast when library.add returns no video', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    openVideosMock.mockResolvedValueOnce(['/clips/empty.mp4']);
    // add resolves but with no `video` field
    rpcMock.mockResolvedValueOnce({});
    await clickAdd();

    const errors = errorToasts().join(' ');
    expect(errors).toContain('empty.mp4');
    expect(errors).toContain('returned no video');
    // no success toast because nothing was actually added
    expect(container.textContent).not.toContain('Added');
  });

  it('shows an error toast when the picker (openVideos) itself rejects', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    openVideosMock.mockRejectedValueOnce(new Error('dialog crashed'));
    await clickAdd();

    expect(errorToasts().join(' ')).toContain('dialog crashed');
  });

  it('ignores a second Add click while a batch is already adding', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    // First click: picker returns a path; hold library.add unresolved so `adding`
    // stays true across the second click.
    let resolveAdd: (v: unknown) => void = () => {};
    openVideosMock.mockResolvedValueOnce(['/clips/slow.mp4']);
    rpcMock.mockImplementationOnce(
      () =>
        new Promise((res) => {
          resolveAdd = res;
        }),
    );

    await act(async () => {
      addButton().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    // mid-flight: button is disabled / labelled "Adding…"
    expect(addButton().disabled).toBe(true);

    // A second click while adding must be a no-op (handlePick early-returns).
    await act(async () => {
      addButton().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(openVideosMock).toHaveBeenCalledTimes(1);

    // finish the in-flight add
    await act(async () => {
      resolveAdd({ video: makeVideo({ id: 'slow', title: 'Slow', path: '/clips/slow.mp4' }) });
    });
    await flush();
    expect(container.textContent).toContain('Slow');
  });

  it('shows a typed error toast when pickerBridge is absent (no window.api)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();
    // Remove the bridge entirely so pickerBridge() returns null.
    delete (window as { api?: unknown }).api;

    await clickAdd();

    expect(errorToasts().join(' ')).toContain('Native file picker unavailable');
  });

  it('falls back to legacy File.path when pathForFile throws', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    // pathForFile is wired but throws -> the catch falls through to legacy .path.
    pathForFileMock.mockImplementation(() => {
      throw new Error('bridge boom');
    });
    const file = new File(['x'], 'thrown.mp4');
    Object.defineProperty(file, 'path', { value: '/legacy/thrown.mp4' });
    rpcMock.mockResolvedValueOnce({
      video: makeVideo({ id: 't', title: 'Thrown', path: '/legacy/thrown.mp4' }),
    });

    await dropFiles([file]);

    expect(rpcMock).toHaveBeenCalledWith('library.add', { path: '/legacy/thrown.mp4' });
    expect(container.textContent).toContain('Thrown');
  });

  it('treats an empty-string pathForFile result as no path (legacy fallback)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    // pathForFile returns '' -> not accepted; no legacy .path either -> error toast.
    pathForFileMock.mockReturnValue('');
    await dropFiles([new File(['x'], 'blank.mp4')]);

    expect(errorToasts().join(' ')).toContain('blank.mp4');
    expect(errorToasts().join(' ')).toContain('no filesystem path');
  });

  it('is a no-op when a drop carries no files', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    await dropFiles([]);
    // only the initial list — no add, no toasts.
    expect(rpcMock).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll('.library__toast').length).toBe(0);
  });

  it('shows and clears the drag-over drop hint on dragover/dragleave', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    const lib = container.querySelector('div.library') as HTMLDivElement;
    const dragOver = new Event('dragover', { bubbles: true, cancelable: true });
    Object.defineProperty(dragOver, 'dataTransfer', { value: { dropEffect: '' } });
    await act(async () => {
      lib.dispatchEvent(dragOver);
    });
    await flush();
    expect(container.querySelector('.library__drophint')).not.toBeNull();
    expect(lib.className).toContain('library--dragover');

    await act(async () => {
      lib.dispatchEvent(new Event('dragleave', { bubbles: true }));
    });
    await flush();
    expect(container.querySelector('.library__drophint')).toBeNull();
    expect(lib.className).not.toContain('library--dragover');
  });

  it('tolerates a dragover with no dataTransfer (sets the hint anyway)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    const lib = container.querySelector('div.library') as HTMLDivElement;
    // No dataTransfer property -> the `if (event.dataTransfer)` guard is false.
    await act(async () => {
      lib.dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(container.querySelector('.library__drophint')).not.toBeNull();
  });

  it('restores the list and surfaces an error when library.remove fails', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    await renderLibrary();
    expect(container.textContent).toContain('Talk');

    rpcMock.mockRejectedValueOnce(new Error('delete failed'));
    const removeBtn = container.querySelector('button.library__remove-btn') as HTMLButtonElement;
    await act(async () => {
      removeBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    // optimistic removal rolled back -> the video is back
    expect(container.textContent).toContain('Talk');
    expect(container.querySelector('.library__error')?.textContent).toContain('delete failed');
  });

  it('exposes the open affordance as a real, labelled <button> (keyboard-native)', async () => {
    // A11Y: the row open action is a native <button> (was a role="button" <li>
    // with a custom Enter/Space handler — which nested the focusable Remove
    // button and tripped axe nested-interactive/only-listitems). A native button
    // is keyboard-operable by the platform, so there is no custom key handler to
    // test; instead assert the semantic contract that makes it accessible.
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    const onOpen = vi.fn();
    await renderLibrary(onOpen);

    const open = container.querySelector('.library__item-open') as HTMLButtonElement;
    expect(open.tagName).toBe('BUTTON');
    expect(open.getAttribute('aria-label')).toBe('Open Talk');
    // The <li> is a plain list item (no button role / tabindex) so the <ul> only
    // contains list items and the open/remove buttons are SIBLINGS, not nested.
    const item = container.querySelector('li.library__item') as HTMLLIElement;
    expect(item.getAttribute('role')).toBeNull();
    expect(item.getAttribute('tabindex')).toBeNull();
  });

  it('renders the transcript badge only for videos that have a transcript', async () => {
    rpcMock.mockResolvedValueOnce({
      videos: [
        makeVideo({ id: 'with', title: 'WithT', hasTranscript: true }),
        makeVideo({ id: 'without', title: 'NoT', hasTranscript: false }),
      ],
    });
    await renderLibrary();

    const badges = container.querySelectorAll('.library__badge');
    expect(badges.length).toBe(1);
    expect(badges[0].textContent).toContain('T');
  });

  it('renders the placeholder duration badge for an unknown duration', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo({ durationSec: 0 })] });
    await renderLibrary();
    expect(container.querySelector('.library__thumb-duration')?.textContent).toBe('--:--');
  });

  it('uses the whole path as the baseName when it ends in a separator (toast text)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    // Path ending in a slash -> baseName's last component is empty -> falls back
    // to the full path. The add fails so the toast text carries that baseName.
    openVideosMock.mockResolvedValueOnce(['/clips/folder/']);
    rpcMock.mockRejectedValueOnce(new Error('is a directory'));
    await clickAdd();

    expect(errorToasts().join(' ')).toContain('/clips/folder/');
    expect(errorToasts().join(' ')).toContain('is a directory');
  });

  it('dismisses a fallback toast when its × button is clicked', async () => {
    installBridge({ openVideos: undefined });
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    await clickAdd(); // produces a "Native file picker unavailable" error toast
    expect(container.querySelectorAll('.library__toast').length).toBe(1);

    const dismiss = container.querySelector('button.library__toast-dismiss') as HTMLButtonElement;
    await act(async () => {
      dismiss.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(container.querySelectorAll('.library__toast').length).toBe(0);
  });

  it('treats a library.list result without a videos field as an empty list', async () => {
    // result.videos is undefined -> the `result?.videos ?? []` fallback runs.
    rpcMock.mockResolvedValueOnce({});
    await renderLibrary();
    expect(container.textContent).toContain('No videos yet');
    expect(container.querySelectorAll('li.library__item').length).toBe(0);
  });

  it('treats a non-array openVideos result as an empty pick (no add)', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    // openVideos resolves a non-array -> `Array.isArray(paths) ? paths : []`
    // takes the `: []` arm, so addPaths gets [] and short-circuits.
    openVideosMock.mockResolvedValueOnce(null as unknown as string[]);
    await clickAdd();

    expect(openVideosMock).toHaveBeenCalledTimes(1);
    // Only the initial library.list — no library.add for a non-array pick.
    expect(rpcMock).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll('.library__toast').length).toBe(0);
  });

  it('tolerates a drop event with no dataTransfer at all', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();

    // No dataTransfer property -> `event.dataTransfer?.files ?? []` yields [].
    const target = container.querySelector('div.library') as HTMLDivElement;
    await act(async () => {
      target.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
    });
    await flush();

    // No add, no toasts, no crash.
    expect(rpcMock).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll('.library__toast').length).toBe(0);
  });

  it('auto-expires a fallback toast after its TTL and clears timers on unmount', async () => {
    vi.useFakeTimers();
    try {
      // Build directly (renderLibrary uses real microtask flushing which is fine
      // under fake timers, but keep this self-contained).
      installBridge({ openVideos: undefined });
      rpcMock.mockResolvedValue({ videos: [] });
      await act(async () => {
        root.render(<Library onOpen={() => {}} />);
      });
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      await act(async () => {
        addButton().dispatchEvent(new MouseEvent('click', { bubbles: true }));
      });
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(container.querySelectorAll('.library__toast').length).toBe(1);

      // Advance past TOAST_TTL_MS (6000ms) -> the expiry timer removes it.
      await act(async () => {
        vi.advanceTimersByTime(6001);
      });
      expect(container.querySelectorAll('.library__toast').length).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

// ---------------------------------------------------------------------------
// WU-14: poster-frame thumbnails (useVideoThumbnail) + the readiness roll-up
// ---------------------------------------------------------------------------

describe('Library thumbnails (WU-14 useVideoThumbnail wiring)', () => {
  it('renders the thumb: <img> poster per card when a thumbnailPath exists', async () => {
    rpcMock.mockResolvedValueOnce({
      videos: [makeVideo(), makeVideo({ id: 'v2', title: 'Second' })],
    });
    await renderLibrary();

    const imgs = container.querySelectorAll('img.library__thumb-img');
    expect(imgs.length).toBe(2);
    // Served immediately through the thumb: mstream resolver (no on-demand rpc).
    expect(imgs[0].getAttribute('src')).toBe(videoThumbnailSrc('/data/thumbnails/v1.jpg'));
    // A persisted poster short-circuits the hook -> no library.thumbnail call.
    expect(rpcMock).not.toHaveBeenCalledWith('library.thumbnail', expect.anything());
    // No glyph fallback while the poster resolves.
    expect(container.querySelector('.library__thumb-fallback')).toBeNull();
  });

  it('treats an absent thumbnailPath (undefined) as no poster -> generates on demand', async () => {
    // thumbnailPath omitted entirely -> the `video.thumbnailPath ?? ''` fallback.
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo({ thumbnailPath: undefined })] });
    rpcMock.mockResolvedValueOnce({ thumbnailPath: '/data/thumbnails/u.jpg' });
    await renderLibrary();

    expect(rpcMock).toHaveBeenCalledWith('library.thumbnail', { id: 'v1' });
    const img = container.querySelector('img.library__thumb-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe(videoThumbnailSrc('/data/thumbnails/u.jpg'));
  });

  it('generates the poster on demand when a card has no thumbnailPath', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo({ thumbnailPath: '' })] });
    rpcMock.mockResolvedValueOnce({ thumbnailPath: '/data/thumbnails/gen.jpg' });
    await renderLibrary();

    expect(rpcMock).toHaveBeenCalledWith('library.thumbnail', { id: 'v1' });
    const img = container.querySelector('img.library__thumb-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe(videoThumbnailSrc('/data/thumbnails/gen.jpg'));
  });

  it('falls back to the glyph when on-demand generation yields no poster', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo({ thumbnailPath: '' })] });
    rpcMock.mockRejectedValueOnce(new Error('no poster'));
    await renderLibrary();

    expect(container.querySelector('img.library__thumb-img')).toBeNull();
    expect(container.querySelector('.library__thumb-fallback')).not.toBeNull();
    // Duration badge still renders.
    expect(container.querySelector('.library__thumb-duration')?.textContent).toBe('10:05');
  });

  it('falls back to the glyph when the poster <img> fails to load', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    await renderLibrary();

    const img = container.querySelector('img.library__thumb-img') as HTMLImageElement;
    await act(async () => {
      img.dispatchEvent(new Event('error'));
    });

    expect(container.querySelector('img.library__thumb-img')).toBeNull();
    expect(container.querySelector('.library__thumb-fallback')).not.toBeNull();
    expect(container.querySelector('.library__thumb-duration')?.textContent).toBe('10:05');
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
});

// ---------------------------------------------------------------------------
// L4: the Lineage-view toggle + asset provenance drawer
// ---------------------------------------------------------------------------

describe('Library lineage view (L4)', () => {
  const EMPTY_LINEAGE = {
    id: 'v1',
    entity: null,
    ancestors: [],
    descendants: [],
    provenance: null,
  };

  function lineageToggle(): HTMLButtonElement {
    return container.querySelector('.library__lineage-toggle') as HTMLButtonElement;
  }

  async function click(el: HTMLElement): Promise<void> {
    await act(async () => {
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
  }

  it('opens an asset provenance drawer (not the Workspace) while in Lineage view', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    const onOpen = vi.fn();
    await renderLibrary(onOpen);

    const toggle = lineageToggle();
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    await click(toggle);
    expect(toggle.getAttribute('aria-pressed')).toBe('true');

    // The card open affordance re-labels itself for the history action.
    const open = container.querySelector('.library__item-open') as HTMLButtonElement;
    expect(open.getAttribute('aria-label')).toBe('Show history of Talk');

    rpcMock.mockResolvedValueOnce(EMPTY_LINEAGE);
    await click(open);

    // Lineage view diverts the click to the drawer — onOpen is NOT called.
    expect(onOpen).not.toHaveBeenCalled();
    expect(rpcMock).toHaveBeenCalledWith('library.lineage', { id: 'v1' });
    const drawer = container.querySelector('.lineage-panel');
    expect(drawer?.getAttribute('aria-label')).toBe('Lineage of Talk');
  });

  it('closes the drawer via its close button', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    await renderLibrary();

    await click(lineageToggle());
    rpcMock.mockResolvedValue(EMPTY_LINEAGE);
    await click(container.querySelector('.library__item-open') as HTMLButtonElement);
    expect(container.querySelector('.lineage-panel')).not.toBeNull();

    await click(container.querySelector('.lineage-panel__close') as HTMLButtonElement);
    expect(container.querySelector('.lineage-panel')).toBeNull();
  });

  it('closes any open drawer when leaving Lineage view', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    await renderLibrary();

    const toggle = lineageToggle();
    await click(toggle);
    rpcMock.mockResolvedValue(EMPTY_LINEAGE);
    await click(container.querySelector('.library__item-open') as HTMLButtonElement);
    expect(container.querySelector('.lineage-panel')).not.toBeNull();

    // Toggling the view off drops the open drawer.
    await click(toggle);
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    expect(container.querySelector('.lineage-panel')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// WU-1f: per-card source provenance (path + on-disk/missing badge + relink)
// ---------------------------------------------------------------------------

describe('Library source provenance (WU-1f)', () => {
  function provenanceHandlers() {
    return {
      reveal: vi.fn(async () => ({
        id: 'v1',
        sources: [
          { id: 'v1', path: '/movies/talk.mp4', title: 'Talk', exists: true, relinkable: true },
        ],
        missing: [] as string[],
      })),
      pinHash: vi.fn(async () => ({})),
      relink: vi.fn(async () => {}),
      openInFolder: vi.fn(async () => true),
      pickRelinkTarget: vi.fn(async () => null),
    };
  }

  it('renders a provenance row per card and drops the legacy compact path line', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [makeVideo()] });
    const handlers = provenanceHandlers();
    await act(async () => {
      root.render(<Library onOpen={() => {}} provenance={handlers} />);
    });
    await flush();

    // The provenance row renders (with the clear full path) and calls reveal.
    expect(container.querySelector('.library-provenance')).not.toBeNull();
    expect(container.querySelector('.library-provenance__path')?.textContent).toBe(
      '/movies/talk.mp4',
    );
    expect(handlers.reveal).toHaveBeenCalledWith('v1');
    // The legacy tiny grey path line is replaced by the provenance row.
    expect(container.querySelector('.library__item-path')).toBeNull();
  });
});

describe('Library readiness roll-up (WU-14)', () => {
  it('renders the ReadinessRollup section on the library home', async () => {
    rpcMock.mockResolvedValueOnce({ videos: [] });
    await renderLibrary();
    expect(container.querySelector('.readiness-rollup')).not.toBeNull();
    expect(readinessSummaryMock).toHaveBeenCalled();
  });

  it('forwards a roll-up action to the onReadinessAction prop', async () => {
    readinessSummaryMock.mockResolvedValue({
      items: [
        {
          capability: 'tr',
          label: 'Translation',
          status: 'needsKey',
          blockedBy: 'no key',
          action: { kind: 'openProviders' },
        },
      ],
    });
    rpcMock.mockResolvedValueOnce({ videos: [] });
    const onReadinessAction = vi.fn();
    await act(async () => {
      root.render(<Library onOpen={() => {}} onReadinessAction={onReadinessAction} />);
    });
    await flush();

    const btn = container.querySelector(
      '.readiness-rollup button.readiness-badge__action',
    ) as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    expect(onReadinessAction).toHaveBeenCalledWith({ kind: 'openProviders' });
  });
});
