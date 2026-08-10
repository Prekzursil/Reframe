// useShortsGallery.test.tsx — behavioral tests for the per-video produced-shorts
// hook. A tiny harness component exposes the hook's API to the test; we drive
// every action (reload success + failure, play toggle, open-folder present/
// absent/error, re-export success/error, delete confirm/cancel/error).
//
// W04 — REVIEWED TEST CHANGE (not a weakening). The three delete tests used to
// stub `globalThis.confirm`. That stub passed whether the gate was the native OS
// confirm or a themed dialog, so it could not tell the two apart and it could not
// have caught W04. They now DRIVE the themed gate the hook renders
// (`gallery.confirmDialog`) and additionally assert the native confirm is never
// called — strictly more than before: the approve path, the cancel path, the
// message content, AND the absence of the native dialog.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { useShortsGallery, type ShortsGallery } from './useShortsGallery';
import type { Api } from './shortMakerLogic';
import type { ShortInfo, ShortReexportHint } from '../lib/rpc';

function short(over: Partial<ShortInfo> = {}): ShortInfo {
  return {
    id: 'sid-1',
    path: '/out/clip-1.mp4',
    videoId: 'v1',
    sourceTitle: 'T',
    template: '',
    viralityPct: null,
    durationSec: 30,
    width: 1080,
    height: 1920,
    createdAt: 0,
    thumbnailPath: '',
    hook: '',
    ...over,
  };
}

describe('useShortsGallery', () => {
  let container: HTMLDivElement;
  let root: Root;
  let gallery: ShortsGallery;
  let setError: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    setError = vi.fn();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  function mount(api: Api, videoId = 'v1', onReexport?: (h: ShortReexportHint) => void) {
    function Harness() {
      gallery = useShortsGallery({ resolvedApi: api, videoId, setError, onReexport });
      return (
        <div data-playing={gallery.playingShortPath} data-count={gallery.videoShorts.length}>
          {gallery.confirmDialog}
        </div>
      );
    }
    act(() => {
      root.render(<Harness />);
    });
  }

  function host() {
    return container.firstElementChild as HTMLElement;
  }

  /** The themed gate's copy, or null while no question is open. */
  function gateBlurb(): string | null {
    return container.querySelector('.confirm-dialog-blurb')?.textContent ?? null;
  }

  function answerGate(approve: boolean): void {
    const sel = approve ? '.confirm-dialog-approve' : '.confirm-dialog-cancel';
    const btn = container.querySelector<HTMLButtonElement>(sel);
    if (!btn) throw new Error(`themed confirm gate is not open (no ${sel})`);
    act(() => btn.click());
  }

  function makeApi(over: Partial<Api> = {}): Api {
    return {
      rpc: vi.fn(async () => ({})) as Api['rpc'],
      onProgress: vi.fn(() => () => {}),
      ...over,
    };
  }

  it('reloadVideoShorts loads shorts.list into state', async () => {
    const rpc = vi.fn(async () => ({ shorts: [short(), short({ id: 'sid-2' })] }));
    mount(makeApi({ rpc: rpc as Api['rpc'] }));
    await act(async () => {
      await gallery.reloadVideoShorts();
    });
    expect(rpc).toHaveBeenCalledWith('shorts.list', { videoId: 'v1' });
    expect(host().getAttribute('data-count')).toBe('2');
  });

  it('reloadVideoShorts coerces a non-array payload to []', async () => {
    const rpc = vi.fn(async () => ({ shorts: 'nope' }));
    mount(makeApi({ rpc: rpc as Api['rpc'] }));
    await act(async () => {
      await gallery.reloadVideoShorts();
    });
    expect(host().getAttribute('data-count')).toBe('0');
  });

  it('reloadVideoShorts clears state on rpc failure', async () => {
    const rpc = vi.fn(async () => {
      throw new Error('list down');
    });
    mount(makeApi({ rpc: rpc as Api['rpc'] }));
    await act(async () => {
      await gallery.reloadVideoShorts();
    });
    expect(host().getAttribute('data-count')).toBe('0');
  });

  it('reloadVideoShorts no-ops without an api or videoId', async () => {
    const rpc = vi.fn(async () => ({ shorts: [short()] }));
    mount(makeApi({ rpc: rpc as Api['rpc'] }), ''); // empty videoId
    await act(async () => {
      await gallery.reloadVideoShorts();
    });
    expect(rpc).not.toHaveBeenCalled();
    expect(host().getAttribute('data-count')).toBe('0');
  });

  it('playShort toggles the inline-playing path (clicking the same one stops it)', () => {
    mount(makeApi());
    act(() => gallery.playShort('/a.mp4'));
    expect(host().getAttribute('data-playing')).toBe('/a.mp4');
    act(() => gallery.playShort('/b.mp4'));
    expect(host().getAttribute('data-playing')).toBe('/b.mp4');
    act(() => gallery.playShort('/b.mp4'));
    expect(host().getAttribute('data-playing')).toBe('');
  });

  it('openShortFolder calls the bridge when present', async () => {
    const openInFolder = vi.fn(async () => true);
    mount(makeApi({ openInFolder }));
    await act(async () => {
      await gallery.openShortFolder('/a.mp4');
    });
    expect(openInFolder).toHaveBeenCalledWith('/a.mp4');
    expect(setError).not.toHaveBeenCalled();
  });

  it('openShortFolder surfaces an error when the bridge is absent', async () => {
    mount(makeApi()); // no openInFolder
    await act(async () => {
      await gallery.openShortFolder('/a.mp4');
    });
    expect(setError).toHaveBeenCalledWith(expect.stringContaining('Open folder is unavailable'));
  });

  it('openShortFolder surfaces the error message when the bridge throws', async () => {
    const openInFolder = vi.fn(async () => {
      throw new Error('explorer dead');
    });
    mount(makeApi({ openInFolder }));
    await act(async () => {
      await gallery.openShortFolder('/a.mp4');
    });
    expect(setError).toHaveBeenCalledWith('explorer dead');
  });

  it('reexportShort fetches the hint and forwards it to onReexport', async () => {
    const hint: ShortReexportHint = {
      videoId: 'v1',
      candidate: { hook: 'h', template: 't', viralityPct: 50, durationSec: 30 },
    };
    const rpc = vi.fn(async () => hint);
    const onReexport = vi.fn();
    mount(makeApi({ rpc: rpc as Api['rpc'] }), 'v1', onReexport);
    await act(async () => {
      await gallery.reexportShort('/a.mp4');
    });
    expect(rpc).toHaveBeenCalledWith('shorts.reexport', { path: '/a.mp4' });
    expect(onReexport).toHaveBeenCalledWith(hint);
    expect(setError).toHaveBeenCalledWith(null); // cleared first
  });

  it('reexportShort is a no-op when there is no api', async () => {
    const onReexport = vi.fn();
    mount(undefined as unknown as Api, 'v1', onReexport);
    await act(async () => {
      await gallery.reexportShort('/a.mp4');
    });
    expect(onReexport).not.toHaveBeenCalled();
    expect(setError).not.toHaveBeenCalled();
  });

  it('reexportShort surfaces an error when the rpc fails', async () => {
    const rpc = vi.fn(async () => {
      throw new Error('reexport boom');
    });
    mount(makeApi({ rpc: rpc as Api['rpc'] }));
    await act(async () => {
      await gallery.reexportShort('/a.mp4');
    });
    expect(setError).toHaveBeenCalledWith('reexport boom');
  });

  it('deleteShort gates on the THEMED dialog, then deletes and reloads on approve', async () => {
    const native = vi.spyOn(globalThis, 'confirm');
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shorts.list') return { shorts: [] };
      return {};
    });
    mount(makeApi({ rpc: rpc as Api['rpc'] }));
    let done!: Promise<void>;
    act(() => {
      done = gallery.deleteShort('/a.mp4');
    });
    // The gate names the clip and states the consequence, and NOTHING has been
    // destroyed while the question is open.
    expect(gateBlurb()).toContain('/a.mp4');
    expect(gateBlurb()).toContain('This removes the exported file.');
    expect(rpc).not.toHaveBeenCalled();

    answerGate(true);
    await act(async () => {
      await done;
    });
    expect(rpc).toHaveBeenCalledWith('shorts.delete', { path: '/a.mp4' });
    expect(rpc).toHaveBeenCalledWith('shorts.list', { videoId: 'v1' });
    // The renderer-blocking native dialog is never reached.
    expect(native).not.toHaveBeenCalled();
    expect(gateBlurb()).toBeNull();
  });

  it('deleteShort is a no-op when the themed gate is declined', async () => {
    const native = vi.spyOn(globalThis, 'confirm');
    const rpc = vi.fn(async () => ({}));
    mount(makeApi({ rpc: rpc as Api['rpc'] }));
    let done!: Promise<void>;
    act(() => {
      done = gallery.deleteShort('/a.mp4');
    });
    answerGate(false);
    await act(async () => {
      await done;
    });
    expect(rpc).not.toHaveBeenCalled();
    expect(native).not.toHaveBeenCalled();
    expect(gateBlurb()).toBeNull();
  });

  it('deleteShort surfaces an error when the delete rpc fails', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shorts.delete') throw new Error('delete denied');
      return {};
    });
    mount(makeApi({ rpc: rpc as Api['rpc'] }));
    let done!: Promise<void>;
    act(() => {
      done = gallery.deleteShort('/a.mp4');
    });
    answerGate(true);
    await act(async () => {
      await done;
    });
    expect(setError).toHaveBeenCalledWith('delete denied');
  });

  it('deleteShort is a no-op without an api, even after the gate is approved', async () => {
    mount(undefined as unknown as Api);
    let done!: Promise<void>;
    act(() => {
      done = gallery.deleteShort('/a.mp4');
    });
    answerGate(true);
    await act(async () => {
      await done;
    });
    expect(setError).not.toHaveBeenCalled();
  });
});
