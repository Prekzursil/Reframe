// Shorts.test.tsx — tests for the generated-shorts gallery view (P4 §6 / C11).
//
// Strategy mirrors Library.test.tsx: mock the typed `client` (lib/rpc) so the
// view's `shorts.list / shorts.delete / shorts.reexport` calls are controllable,
// render with React 18's react-dom/client + act under jsdom, and drive the card
// actions. The pure helpers (sortByCreatedAt / formatShortDuration) are tested
// without any React render.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Mock the typed client so list/delete/reexport are deterministic.
const listMock = vi.fn();
const deleteMock = vi.fn();
const reexportMock = vi.fn();
const thumbnailMock = vi.fn();
// captions-export: the gallery now also offers a per-card "Package for upload"
// action calling client.package.export — mock it so the wiring is exercisable.
const packageMock = vi.fn();

// hasApi is controllable per-test (default true). A few branches only run when
// the preload bridge is reported absent (refresh's early bail-out).
let hasApiValue = true;
vi.mock('../lib/rpc', () => ({
  client: {
    shorts: {
      list: (...a: unknown[]) => listMock(...a),
      delete: (...a: unknown[]) => deleteMock(...a),
      reexport: (...a: unknown[]) => reexportMock(...a),
      thumbnail: (...a: unknown[]) => thumbnailMock(...a),
    },
    package: {
      export: (...a: unknown[]) => packageMock(...a),
    },
  },
  hasApi: () => hasApiValue,
}));

import { Shorts, sortByCreatedAt, sortShorts, formatShortDuration } from './Shorts';
import type { ShortInfo } from '../lib/rpc';

// jsdom lacks HTMLMediaElement playback; the inline preview Player touches
// play/pause/currentTime — back them with deterministic stores (Library pattern).
const playMock = vi.fn(() => Promise.resolve());
const pauseMock = vi.fn();
const currentTimes = new WeakMap<HTMLMediaElement, number>();

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    writable: true,
    value: playMock,
  });
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
});

function makeShort(over: Partial<ShortInfo> = {}): ShortInfo {
  return {
    id: 's1',
    path: '/exports/shorts-v1/clip-1.mp4',
    videoId: 'v1',
    sourceTitle: 'My Talk',
    template: 'hormozi',
    viralityPct: 87,
    durationSec: 42,
    width: 1080,
    height: 1920,
    createdAt: 1_700_000_000,
    thumbnailPath: '',
    hook: 'The one thing nobody tells you',
    ...over,
  };
}

// ---- pure helpers ----------------------------------------------------------

describe('Shorts pure helpers', () => {
  it('sortByCreatedAt sorts newest first without mutating the input', () => {
    const a = makeShort({ id: 'a', createdAt: 100 });
    const b = makeShort({ id: 'b', createdAt: 300 });
    const c = makeShort({ id: 'c', createdAt: 200 });
    const input = [a, b, c];
    const sorted = sortByCreatedAt(input);
    expect(sorted.map((s) => s.id)).toEqual(['b', 'c', 'a']);
    // immutability: original order untouched.
    expect(input.map((s) => s.id)).toEqual(['a', 'b', 'c']);
  });

  it('formatShortDuration renders mm:ss and a placeholder for bad input', () => {
    expect(formatShortDuration(42.4)).toBe('00:42');
    expect(formatShortDuration(65)).toBe('01:05');
    expect(formatShortDuration(0)).toBe('--:--');
    expect(formatShortDuration(Number.NaN)).toBe('--:--');
  });

  it('sortShorts orders by recency or virality (P4 §7), never mutating input', () => {
    const a = makeShort({ id: 'a', createdAt: 100, viralityPct: 40 });
    const b = makeShort({ id: 'b', createdAt: 300, viralityPct: 90 });
    const c = makeShort({ id: 'c', createdAt: 200, viralityPct: 70 });
    const input = [a, b, c];
    expect(sortShorts(input, 'recent').map((s) => s.id)).toEqual(['b', 'c', 'a']);
    expect(sortShorts(input, 'virality').map((s) => s.id)).toEqual(['b', 'c', 'a']);
    // virality ordering is distinct from recency when they disagree
    const d = makeShort({ id: 'd', createdAt: 999, viralityPct: 10 });
    expect(sortShorts([a, b, d], 'virality').map((s) => s.id)).toEqual(['b', 'a', 'd']);
    expect(input.map((s) => s.id)).toEqual(['a', 'b', 'c']); // immutability
  });

  it('sortShorts sinks shorts with no virality below scored ones', () => {
    const scored = makeShort({ id: 'scored', createdAt: 100, viralityPct: 50 });
    const unscored = makeShort({ id: 'unscored', createdAt: 999, viralityPct: undefined });
    expect(sortShorts([unscored, scored], 'virality').map((s) => s.id)).toEqual([
      'scored',
      'unscored',
    ]);
  });

  it('sortShorts breaks equal-virality ties by newest createdAt', () => {
    const older = makeShort({ id: 'older', createdAt: 100, viralityPct: 80 });
    const newer = makeShort({ id: 'newer', createdAt: 500, viralityPct: 80 });
    // same viralityPct -> the `d !== 0 ? d : b.createdAt - a.createdAt` tie-break runs
    expect(sortShorts([older, newer], 'virality').map((s) => s.id)).toEqual(['newer', 'older']);
  });

  it('sortShorts treats a non-finite (NaN) viralityPct as unscored', () => {
    const nan = makeShort({ id: 'nan', createdAt: 999, viralityPct: Number.NaN });
    const scored = makeShort({ id: 'scored', createdAt: 100, viralityPct: 10 });
    expect(sortShorts([nan, scored], 'virality').map((s) => s.id)).toEqual(['scored', 'nan']);
  });
});

// ---- component -------------------------------------------------------------

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  listMock.mockReset();
  deleteMock.mockReset();
  reexportMock.mockReset();
  thumbnailMock.mockReset();
  packageMock.mockReset();
  playMock.mockClear();
  pauseMock.mockClear();
  hasApiValue = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  // Let the mounted effects' promises settle.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('Shorts view', () => {
  it('loads shorts.list on mount and renders a card per clip', async () => {
    listMock.mockResolvedValue({
      shorts: [
        makeShort({ id: 's1', sourceTitle: 'Talk A' }),
        makeShort({ id: 's2', sourceTitle: 'Talk B' }),
      ],
    });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(listMock).toHaveBeenCalledTimes(1);
    // omitted videoId = list every source's clips (called with NO args).
    expect(listMock).toHaveBeenCalledWith();
    const cards = container.querySelectorAll('.shorts__card');
    expect(cards.length).toBe(2);
    expect(container.textContent).toContain('Talk A');
    expect(container.textContent).toContain('Talk B');
    // virality badge + duration surfaced.
    expect(container.textContent).toContain('87');
    expect(container.textContent).toContain('00:42');
  });

  it('renders the empty state when no clips exist', async () => {
    listMock.mockResolvedValue({ shorts: [] });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('.shorts__empty')).not.toBeNull();
    expect(container.querySelectorAll('.shorts__card').length).toBe(0);
  });

  it('sort toggle reorders the cards by virality without a refetch (P4 §7)', async () => {
    listMock.mockResolvedValue({
      shorts: [
        makeShort({ id: 'low', createdAt: 300, viralityPct: 20 }),
        makeShort({ id: 'high', createdAt: 100, viralityPct: 95 }),
        makeShort({ id: 'mid', createdAt: 200, viralityPct: 60 }),
      ],
    });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    // Default 'recent' order: newest createdAt first => low(300), mid(200), high(100).
    const recentIds = [...container.querySelectorAll('.shorts__card')].map((c) =>
      c.getAttribute('data-id'),
    );
    expect(recentIds).toEqual(['low', 'mid', 'high']);

    // Switch to Virality -> 95,60,20 => high, mid, low. No second list() call.
    const viralityBtn = [...container.querySelectorAll('[aria-label="Sort shorts"] button')].find(
      (b) => b.textContent === 'Virality',
    ) as HTMLButtonElement;
    await act(async () => {
      viralityBtn.click();
    });
    await flush();

    const viralityIds = [...container.querySelectorAll('.shorts__card')].map((c) =>
      c.getAttribute('data-id'),
    );
    expect(viralityIds).toEqual(['high', 'mid', 'low']);
    expect(viralityBtn.getAttribute('aria-pressed')).toBe('true');
    expect(listMock).toHaveBeenCalledTimes(1); // no refetch
  });

  it('Delete confirms, calls shorts.delete with the path, then reloads', async () => {
    listMock
      .mockResolvedValueOnce({
        shorts: [makeShort({ id: 's1', path: '/exports/shorts-v1/a.mp4' })],
      })
      .mockResolvedValueOnce({ shorts: [] });
    deleteMock.mockResolvedValue({ ok: true });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const delBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Delete"]');
    expect(delBtn).not.toBeNull();
    await act(async () => {
      delBtn!.click();
    });
    await flush();

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(deleteMock).toHaveBeenCalledWith('/exports/shorts-v1/a.mp4');
    // reload ran (list called twice total) and the card is gone.
    expect(listMock).toHaveBeenCalledTimes(2);
    expect(container.querySelectorAll('.shorts__card').length).toBe(0);
  });

  it('Delete is a no-op when the user cancels the confirm', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort()] });
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const delBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Delete"]');
    await act(async () => {
      delBtn!.click();
    });
    await flush();

    expect(deleteMock).not.toHaveBeenCalled();
    expect(listMock).toHaveBeenCalledTimes(1);
  });

  it('Open folder routes to window.api.openInFolder with the path', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/shorts-v1/a.mp4' })] });
    const openInFolderMock = vi.fn().mockResolvedValue(true);
    const w = window as unknown as Record<string, unknown>;
    w.api = { openInFolder: openInFolderMock };

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const openBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Open folder"]');
    expect(openBtn).not.toBeNull();
    await act(async () => {
      openBtn!.click();
    });
    await flush();

    expect(openInFolderMock).toHaveBeenCalledWith('/exports/shorts-v1/a.mp4');
    w.api = undefined;
  });

  it('Re-export calls shorts.reexport then the onReexport callback with the hint', async () => {
    listMock.mockResolvedValue({
      shorts: [makeShort({ path: '/exports/shorts-v1/a.mp4', videoId: 'v9' })],
    });
    const hint = {
      videoId: 'v9',
      candidate: { hook: 'h', template: 'neon', viralityPct: 71, durationSec: 30 },
    };
    reexportMock.mockResolvedValue(hint);
    const onReexport = vi.fn();

    await act(async () => {
      root.render(<Shorts onReexport={onReexport} />);
    });
    await flush();

    const reBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Re-export"]');
    expect(reBtn).not.toBeNull();
    await act(async () => {
      reBtn!.click();
    });
    await flush();

    expect(reexportMock).toHaveBeenCalledWith('/exports/shorts-v1/a.mp4');
    expect(onReexport).toHaveBeenCalledWith(hint);
  });

  it('Play mounts an inline preview Player over the exported file', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/shorts-v1/a.mp4' })] });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('video')).toBeNull();
    const playBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Play"]');
    expect(playBtn).not.toBeNull();
    await act(async () => {
      playBtn!.click();
    });
    await flush();

    const video = container.querySelector('video');
    expect(video).not.toBeNull();
    // the short rides the short: id-prefix mstream URL (shortMediaUrl).
    expect(video!.getAttribute('src')).toContain('short%3A');
  });

  it('generates a poster via shorts.thumbnail and serves it over the short: mstream URL (P4 §6)', async () => {
    listMock.mockResolvedValue({
      shorts: [makeShort({ path: '/exports/shorts-v1/a.mp4', thumbnailPath: '' })],
    });
    // No poster yet -> the card asks the sidecar to generate one (idempotent).
    thumbnailMock.mockResolvedValue({ thumbnailPath: '/exports/shorts-v1/a.thumb.jpg' });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(thumbnailMock).toHaveBeenCalledWith('/exports/shorts-v1/a.mp4');
    const img = container.querySelector<HTMLImageElement>('.shorts__thumb-img');
    expect(img).not.toBeNull();
    // The poster rides the short: mstream resolver (NOT a raw fs path).
    expect(img!.getAttribute('src')).toContain('short%3A');
    expect(img!.getAttribute('src')).toContain('a.thumb.jpg');
  });

  it('serves an existing thumbnailPath over mstream without calling shorts.thumbnail', async () => {
    listMock.mockResolvedValue({
      shorts: [
        makeShort({
          path: '/exports/shorts-v1/a.mp4',
          thumbnailPath: '/exports/shorts-v1/a.thumb.jpg',
        }),
      ],
    });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(thumbnailMock).not.toHaveBeenCalled();
    const img = container.querySelector<HTMLImageElement>('.shorts__thumb-img');
    expect(img!.getAttribute('src')).toContain('short%3A');
  });

  it('falls back to the ▶ glyph when poster generation fails', async () => {
    listMock.mockResolvedValue({
      shorts: [makeShort({ path: '/exports/shorts-v1/a.mp4', thumbnailPath: '' })],
    });
    thumbnailMock.mockRejectedValue(new Error('ffmpeg failed'));

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('.shorts__thumb-img')).toBeNull();
    expect(container.querySelector('.shorts__thumb-glyph')).not.toBeNull();
  });

  it('surfaces a list error without throwing', async () => {
    listMock.mockRejectedValue(new Error('sidecar down'));

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('.shorts__error')).not.toBeNull();
    expect(container.textContent).toContain('sidecar down');
  });

  it('stringifies a non-Error list rejection', async () => {
    listMock.mockRejectedValue('raw failure');
    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();
    expect(container.querySelector('.shorts__error')?.textContent).toContain('raw failure');
  });

  it('bails out of refresh (no list call) when the preload bridge is absent', async () => {
    hasApiValue = false;
    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    // refresh returns early -> no shorts.list call, loading cleared, empty state.
    expect(listMock).not.toHaveBeenCalled();
    expect(container.querySelector('.shorts__loading')).toBeNull();
    expect(container.querySelector('.shorts__empty')).not.toBeNull();
  });

  it('shows an error when Open folder has no preload bridge wired', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4' })] });
    // no window.api.openInFolder
    const w = window as unknown as Record<string, unknown>;
    w.api = {};

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const openBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Open folder"]');
    await act(async () => {
      openBtn!.click();
    });
    await flush();

    expect(container.querySelector('.shorts__error')?.textContent).toContain(
      'Open folder is unavailable',
    );
    w.api = undefined;
  });

  it('surfaces an error when the openInFolder bridge rejects', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4' })] });
    const w = window as unknown as Record<string, unknown>;
    w.api = { openInFolder: vi.fn().mockRejectedValue(new Error('explorer crashed')) };

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const openBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Open folder"]');
    await act(async () => {
      openBtn!.click();
    });
    await flush();

    expect(container.querySelector('.shorts__error')?.textContent).toContain('explorer crashed');
    w.api = undefined;
  });

  it('surfaces an error when shorts.reexport rejects', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4' })] });
    reexportMock.mockRejectedValue(new Error('reexport boom'));
    const onReexport = vi.fn();

    await act(async () => {
      root.render(<Shorts onReexport={onReexport} />);
    });
    await flush();

    const reBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Re-export"]');
    await act(async () => {
      reBtn!.click();
    });
    await flush();

    expect(onReexport).not.toHaveBeenCalled();
    expect(container.querySelector('.shorts__error')?.textContent).toContain('reexport boom');
  });

  it('does not require an onReexport callback (optional-chaining) on re-export', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4', videoId: 'v9' })] });
    reexportMock.mockResolvedValue({
      videoId: 'v9',
      candidate: { hook: 'h', template: 't', viralityPct: 5, durationSec: 10 },
    });

    // render WITHOUT onReexport -> the `onReexport?.(hint)` no-call branch runs.
    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const reBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Re-export"]');
    await act(async () => {
      reBtn!.click();
    });
    await flush();

    expect(reexportMock).toHaveBeenCalledWith('/exports/a.mp4');
    expect(container.querySelector('.shorts__error')).toBeNull();
  });

  it('packages a clip for upload and shows the confirmation note', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4' })] });
    packageMock.mockResolvedValue({ path: '/exports/a.zip', manifest: {} });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const pkgBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Package"]');
    expect(pkgBtn).not.toBeNull();
    await act(async () => {
      pkgBtn!.click();
    });
    await flush();

    expect(packageMock).toHaveBeenCalledWith('/exports/a.mp4');
    const note = container.querySelector('.shorts__note');
    expect(note).not.toBeNull();
    expect(note?.textContent).toContain('/exports/a.zip');
  });

  it('surfaces an error when package.export rejects', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4' })] });
    packageMock.mockRejectedValue(new Error('zip failed'));

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const pkgBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Package"]');
    await act(async () => {
      pkgBtn!.click();
    });
    await flush();

    expect(container.querySelector('.shorts__error')?.textContent).toContain('zip failed');
    expect(container.querySelector('.shorts__note')).toBeNull();
  });

  it('surfaces an error when shorts.delete rejects (after confirm)', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4' })] });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    deleteMock.mockRejectedValue(new Error('unlink failed'));

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const delBtn = container.querySelector<HTMLButtonElement>('button[aria-label^="Delete"]');
    await act(async () => {
      delBtn!.click();
    });
    await flush();

    expect(deleteMock).toHaveBeenCalledWith('/exports/a.mp4');
    expect(container.querySelector('.shorts__error')?.textContent).toContain('unlink failed');
  });

  it('toggling Play twice closes the inline preview (same id => null)', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort({ path: '/exports/a.mp4' })] });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const playBtn = () => container.querySelector<HTMLButtonElement>('button[aria-label^="Play"]');
    await act(async () => {
      playBtn()!.click();
    });
    await flush();
    expect(container.querySelector('video')).not.toBeNull();

    // The ShortClipActions Play toggle (now visible) flips playingId back to null.
    const toggle = container.querySelector<HTMLButtonElement>('button[aria-label^="Play"]');
    await act(async () => {
      toggle!.click();
    });
    await flush();
    expect(container.querySelector('video')).toBeNull();
  });

  it('handles a clip with no source title (falls back to the file basename)', async () => {
    listMock.mockResolvedValue({
      shorts: [makeShort({ id: 'nt', sourceTitle: '', path: '/exports/shorts-v1/raw-clip.mp4' })],
    });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('.shorts__card-title')?.textContent).toContain('raw-clip.mp4');
  });

  it('omits the virality badge / caption template / hook when those fields are blank', async () => {
    listMock.mockResolvedValue({
      shorts: [
        makeShort({
          id: 'bare',
          viralityPct: null,
          template: '',
          hook: '',
        }),
      ],
    });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('.shorts__virality')).toBeNull();
    expect(container.querySelector('.shorts__template')).toBeNull();
    expect(container.querySelector('.shorts__hook')).toBeNull();
  });

  it('treats a shorts.list result without a shorts field as an empty list', async () => {
    // res.shorts is undefined -> the `res?.shorts ?? []` fallback runs.
    listMock.mockResolvedValue({});

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('.shorts__empty')).not.toBeNull();
    expect(container.querySelectorAll('.shorts__card').length).toBe(0);
  });

  it('falls back to the full path basename when both title and last component are empty', async () => {
    // sourceTitle '' + a path ending in a separator -> baseName's last component
    // is empty, so the `parts[parts.length - 1] || p` fallback returns the path.
    listMock.mockResolvedValue({
      shorts: [makeShort({ id: 'slash', sourceTitle: '', path: '/exports/shorts-v1/' })],
    });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('.shorts__card-title')?.textContent).toContain(
      '/exports/shorts-v1/',
    );
  });

  it('clicking Recent re-applies the recency order after Virality (sort onClick branch)', async () => {
    listMock.mockResolvedValue({
      shorts: [
        makeShort({ id: 'low', createdAt: 300, viralityPct: 20 }),
        makeShort({ id: 'high', createdAt: 100, viralityPct: 95 }),
        makeShort({ id: 'mid', createdAt: 200, viralityPct: 60 }),
      ],
    });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    const btn = (label: string): HTMLButtonElement =>
      [...container.querySelectorAll('[aria-label="Sort shorts"] button')].find(
        (b) => b.textContent === label,
      ) as HTMLButtonElement;

    // Switch to virality first...
    await act(async () => {
      btn('Virality').click();
    });
    await flush();
    expect(
      [...container.querySelectorAll('.shorts__card')].map((c) => c.getAttribute('data-id')),
    ).toEqual(['high', 'mid', 'low']);

    // ...then click Recent -> the `() => setSortMode('recent')` onClick runs and
    // the cards return to newest-first order.
    await act(async () => {
      btn('Recent').click();
    });
    await flush();
    expect(
      [...container.querySelectorAll('.shorts__card')].map((c) => c.getAttribute('data-id')),
    ).toEqual(['low', 'mid', 'high']);
    expect(btn('Recent').getAttribute('aria-pressed')).toBe('true');
  });

  it('a card renders with no live thumbnail client when hasApi() is false at render time', async () => {
    // Load the gallery while the bridge is present (so cards exist)...
    listMock.mockResolvedValue({
      shorts: [makeShort({ id: 'sx', path: '/exports/a.mp4', thumbnailPath: '' })],
    });
    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();
    expect(container.querySelectorAll('.shorts__card').length).toBe(1);
    const thumbCalls = thumbnailMock.mock.calls.length;

    // ...then drop the bridge and force a re-render via the sort toggle. The
    // ShortCard re-evaluates `hasApi() ? client.shorts : null`, taking the
    // `: null` arm so no thumbnail client is handed to the hook.
    hasApiValue = false;
    const recentBtn = [...container.querySelectorAll('[aria-label="Sort shorts"] button')].find(
      (b) => b.textContent === 'Virality',
    ) as HTMLButtonElement;
    await act(async () => {
      recentBtn.click();
    });
    await flush();

    // Card still present; no NEW thumbnail generation was triggered with a null client.
    expect(container.querySelectorAll('.shorts__card').length).toBe(1);
    expect(thumbnailMock.mock.calls.length).toBe(thumbCalls);
  });

  it('renders the singular "1 clip" count label for a single short', async () => {
    listMock.mockResolvedValue({ shorts: [makeShort()] });

    await act(async () => {
      root.render(<Shorts />);
    });
    await flush();

    expect(container.querySelector('[aria-label="Shorts count"]')?.textContent).toBe('1 clip');
  });
});
