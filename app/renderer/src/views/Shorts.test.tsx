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

vi.mock('../lib/rpc', () => ({
  client: {
    shorts: {
      list: (...a: unknown[]) => listMock(...a),
      delete: (...a: unknown[]) => deleteMock(...a),
      reexport: (...a: unknown[]) => reexportMock(...a),
      thumbnail: (...a: unknown[]) => thumbnailMock(...a),
    },
  },
  hasApi: () => true,
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
});

// ---- component -------------------------------------------------------------

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  listMock.mockReset();
  deleteMock.mockReset();
  reexportMock.mockReset();
  thumbnailMock.mockReset();
  playMock.mockClear();
  pauseMock.mockClear();
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
});
