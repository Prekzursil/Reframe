// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const rpcMock = vi.fn();
vi.mock('../components/api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: () => () => {},
  hasApi: () => true,
}));

import { LibraryCard } from './LibraryCard';
import type { LibraryVideo } from './libraryModel';
import { videoThumbnailSrc } from '../components/useVideoThumbnail';

function makeVideo(over: Partial<LibraryVideo> = {}): LibraryVideo {
  return {
    id: 'v1',
    path: '/movies/talk.mp4',
    title: 'Talk',
    addedAt: '2026-06-11T00:00:00Z',
    durationSec: 605,
    hasTranscript: false,
    thumbnailPath: '/data/thumbnails/v1.jpg',
    ...over,
  };
}

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

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  });
}

interface Over {
  video?: LibraryVideo;
  lineageView?: boolean;
  selected?: boolean;
  onToggleSelect?: (id: string) => void;
  onOpen?: (v: LibraryVideo) => void;
  onRemove?: (id: string, e: React.MouseEvent) => void;
  shortsCount?: number;
  onOpenShorts?: (v: LibraryVideo) => void;
  provenance?: ReturnType<typeof provenanceHandlers>;
}

async function renderCard(over: Over = {}): Promise<void> {
  await act(async () => {
    root.render(
      <ul>
        <LibraryCard
          video={over.video ?? makeVideo()}
          lineageView={over.lineageView ?? false}
          selected={over.selected ?? false}
          onToggleSelect={over.onToggleSelect ?? (() => {})}
          onOpen={over.onOpen ?? (() => {})}
          onRemove={over.onRemove ?? (() => {})}
          shortsCount={over.shortsCount ?? 0}
          onOpenShorts={over.onOpenShorts ?? (() => {})}
          provenance={over.provenance}
        />
      </ul>,
    );
  });
  await flush();
}

describe('LibraryCard', () => {
  it('renders the poster, title, added date, and an enriched open aria-label', async () => {
    await renderCard();
    const open = container.querySelector('.library__item-open') as HTMLButtonElement;
    expect(open.getAttribute('aria-label')).toBe('Open Talk, 10:05, no transcript');
    expect(container.querySelector('.library__item-title')?.textContent).toBe('Talk');
    expect(container.querySelector('.library__item-added')?.textContent).toBe('Added 2026-06-11');
    const img = container.querySelector('img.library__thumb-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe(videoThumbnailSrc('/data/thumbnails/v1.jpg'));
    expect(container.querySelector('.library__thumb-duration')?.textContent).toBe('10:05');
  });

  it('omits the added line when the timestamp is unparseable', async () => {
    await renderCard({ video: makeVideo({ addedAt: 'nope' }) });
    expect(container.querySelector('.library__item-added')).toBeNull();
  });

  it('shows the FAILED attention badge before the Transcript chip', async () => {
    await renderCard({ video: makeVideo({ failed: true, hasTranscript: true }) });
    const badges = [...container.querySelectorAll('.library__badge')].map((b) => b.textContent);
    expect(badges).toEqual(['Failed', 'Transcript']);
    expect(container.querySelector('.library__chip--failed')).not.toBeNull();
    expect(container.querySelector('.library__chip--transcript')).not.toBeNull();
  });

  it('renders no chips for a plain video', async () => {
    await renderCard();
    expect(container.querySelector('.library__chips')).toBeNull();
  });

  it('opens the video on click', async () => {
    const onOpen = vi.fn();
    await renderCard({ onOpen });
    act(() => {
      (container.querySelector('.library__item-open') as HTMLButtonElement).dispatchEvent(
        new MouseEvent('click', { bubbles: true }),
      );
    });
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0].id).toBe('v1');
  });

  it('re-labels the open action in lineage view', async () => {
    await renderCard({ lineageView: true });
    expect(
      (container.querySelector('.library__item-open') as HTMLButtonElement).getAttribute(
        'aria-label',
      ),
    ).toBe('Show history of Talk, 10:05, no transcript');
  });

  it('toggles selection via the checkbox', async () => {
    const onToggleSelect = vi.fn();
    await renderCard({ selected: true, onToggleSelect });
    const box = container.querySelector('.library__select-box') as HTMLInputElement;
    expect(box.checked).toBe(true);
    act(() => {
      box.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onToggleSelect).toHaveBeenCalledWith('v1');
  });

  it('removes the video via the Remove control', async () => {
    const onRemove = vi.fn();
    await renderCard({ onRemove });
    act(() => {
      (container.querySelector('.library__remove-btn') as HTMLButtonElement).dispatchEvent(
        new MouseEvent('click', { bubbles: true }),
      );
    });
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove.mock.calls[0][0]).toBe('v1');
  });

  it('shows a "N shorts" label that opens the gallery when the video has shorts', async () => {
    const onOpenShorts = vi.fn();
    await renderCard({ shortsCount: 3, onOpenShorts });
    const label = container.querySelector('.library__shorts-label') as HTMLButtonElement;
    expect(label.textContent).toBe('3 shorts');
    expect(label.getAttribute('aria-label')).toBe('View 3 produced shorts for Talk');
    act(() => {
      label.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onOpenShorts).toHaveBeenCalledTimes(1);
    expect(onOpenShorts.mock.calls[0][0].id).toBe('v1');
  });

  it('pluralizes the shorts label + aria for a single short (never "1 shorts")', async () => {
    await renderCard({ shortsCount: 1 });
    const label = container.querySelector('.library__shorts-label') as HTMLButtonElement;
    expect(label.textContent).toBe('1 short');
    expect(label.getAttribute('aria-label')).toBe('View 1 produced short for Talk');
  });

  it('hides the shorts label when the video has none', async () => {
    await renderCard({ shortsCount: 0 });
    expect(container.querySelector('.library__shorts-label')).toBeNull();
  });

  it('demotes provenance behind a per-card disclosure and drops the legacy path line', async () => {
    const handlers = provenanceHandlers();
    await renderCard({ provenance: handlers });
    // Resting card: the disclosure toggle is present but the plumbing is hidden
    // (and not even fetched) so the card stays poster + title + shorts + status.
    expect(container.querySelector('.card-provenance__toggle')).not.toBeNull();
    expect(container.querySelector('.library-provenance')).toBeNull();
    expect(container.querySelector('.library__item-path')).toBeNull();
    expect(handlers.reveal).not.toHaveBeenCalled();
    // Opening the disclosure reveals the provenance row and triggers the lookup.
    await act(async () => {
      (container.querySelector('.card-provenance__toggle') as HTMLButtonElement).dispatchEvent(
        new MouseEvent('click', { bubbles: true }),
      );
    });
    await flush();
    expect(container.querySelector('.library-provenance')).not.toBeNull();
    expect(handlers.reveal).toHaveBeenCalledWith('v1');
  });

  it('keeps the legacy path line when no provenance is wired', async () => {
    await renderCard();
    expect(container.querySelector('.library__item-path')?.textContent).toBe('/movies/talk.mp4');
  });

  it('falls back to the ▶ glyph when the poster <img> fails to load', async () => {
    await renderCard();
    const img = container.querySelector('img.library__thumb-img') as HTMLImageElement;
    act(() => {
      img.dispatchEvent(new Event('error'));
    });
    expect(container.querySelector('img.library__thumb-img')).toBeNull();
    expect(container.querySelector('.library__thumb-fallback')).not.toBeNull();
  });

  it('falls back to the glyph when on-demand poster generation yields nothing', async () => {
    // thumbnailPath omitted entirely -> the `video.thumbnailPath ?? ''` fallback,
    // then on-demand generation via library.thumbnail (which fails here).
    rpcMock.mockRejectedValueOnce(new Error('no poster'));
    await renderCard({ video: makeVideo({ thumbnailPath: undefined }) });
    expect(rpcMock).toHaveBeenCalledWith('library.thumbnail', { id: 'v1' });
    expect(container.querySelector('img.library__thumb-img')).toBeNull();
    expect(container.querySelector('.library__thumb-fallback')).not.toBeNull();
  });
});
