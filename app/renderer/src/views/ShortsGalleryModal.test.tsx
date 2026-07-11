// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { ShortInfo } from '../lib/rpc';

// Isolate the modal from the (separately-covered) ProducedShorts gallery: a
// lightweight stub renders exactly the per-clip affordances the modal wires, so
// each modal handler (play toggle / open-folder / delete / edit-mapping) is
// exercised directly. The REAL ProducedShorts is reused in production.
vi.mock('../features/ProducedShorts', () => ({
  ProducedShorts: ({
    shorts,
    playingShortPath,
    onPlay,
    onOpenFolder,
    onReexport,
    onDelete,
  }: {
    shorts: ShortInfo[];
    playingShortPath: string;
    onPlay: (p: string) => void;
    onOpenFolder: (p: string) => void;
    onReexport?: (p: string) => void;
    onDelete: (p: string) => void;
  }) => (
    <div data-testid="produced-shorts" data-playing={playingShortPath}>
      {shorts.map((s) => (
        <div key={s.id}>
          <button type="button" data-testid={`play-${s.id}`} onClick={() => onPlay(s.path)}>
            play
          </button>
          <button type="button" data-testid={`folder-${s.id}`} onClick={() => onOpenFolder(s.path)}>
            folder
          </button>
          <button type="button" data-testid={`delete-${s.id}`} onClick={() => onDelete(s.path)}>
            delete
          </button>
          {onReexport ? (
            <button type="button" data-testid={`edit-${s.id}`} onClick={() => onReexport(s.path)}>
              edit
            </button>
          ) : null}
        </div>
      ))}
    </div>
  ),
}));

import { ShortsGalleryModal } from './ShortsGalleryModal';

function makeShort(over: Partial<ShortInfo> = {}): ShortInfo {
  return {
    id: 's1',
    path: '/out/s1.mp4',
    videoId: 'v1',
    sourceTitle: 'Talk',
    template: '',
    viralityPct: 90,
    durationSec: 30,
    width: 1080,
    height: 1920,
    createdAt: 1,
    thumbnailPath: '',
    hook: '',
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

interface Handlers {
  onClose?: () => void;
  onOpenFolder?: (p: string) => void;
  onDelete?: (p: string) => void;
  onEdit?: (s: ShortInfo) => void;
  shorts?: ShortInfo[];
}

function renderModal(h: Handlers = {}): void {
  act(() => {
    root.render(
      <ShortsGalleryModal
        title="Talk"
        shorts={h.shorts ?? [makeShort()]}
        onClose={h.onClose ?? (() => {})}
        onOpenFolder={h.onOpenFolder ?? (() => {})}
        onDelete={h.onDelete ?? (() => {})}
        onEdit={h.onEdit}
      />,
    );
  });
}

function dialog(): HTMLElement {
  return container.querySelector('.shorts-modal') as HTMLElement;
}

function click(sel: string): void {
  act(() => {
    (container.querySelector(sel) as HTMLElement).dispatchEvent(
      new MouseEvent('click', { bubbles: true }),
    );
  });
}

describe('ShortsGalleryModal', () => {
  it('renders a labelled dialog reusing ProducedShorts, and focuses the close button', () => {
    renderModal();
    const d = dialog();
    expect(d.getAttribute('role')).toBe('dialog');
    expect(d.getAttribute('aria-modal')).toBe('true');
    expect(d.getAttribute('aria-label')).toBe('Produced shorts for Talk');
    expect(container.querySelector('.shorts-modal__title')?.textContent).toBe('Talk');
    expect(container.querySelector('[data-testid="produced-shorts"]')).not.toBeNull();
    // Focus lands on the close control on open.
    expect(document.activeElement).toBe(container.querySelector('.shorts-modal__close'));
  });

  it('shows an empty message when the video has no shorts', () => {
    renderModal({ shorts: [] });
    expect(container.querySelector('.shorts-modal__empty')?.textContent).toContain('No shorts');
    expect(container.querySelector('[data-testid="produced-shorts"]')).toBeNull();
  });

  it('closes on backdrop click but NOT on an inner (dialog) click', () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    // Inner click is swallowed (stopPropagation) — does not close.
    click('.shorts-modal__title');
    expect(onClose).not.toHaveBeenCalled();
    // Backdrop click closes.
    click('.shorts-modal__backdrop');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on the close button and on Escape, but ignores other keys', () => {
    const onClose = vi.fn();
    renderModal({ onClose });
    click('.shorts-modal__close');
    expect(onClose).toHaveBeenCalledTimes(1);

    act(() => {
      dialog().dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1); // unchanged

    act(() => {
      dialog().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('toggles inline playback of a clip (play then stop)', () => {
    renderModal();
    const shorts = () => container.querySelector('[data-testid="produced-shorts"]');
    expect(shorts()?.getAttribute('data-playing')).toBe('');
    click('[data-testid="play-s1"]');
    expect(shorts()?.getAttribute('data-playing')).toBe('/out/s1.mp4');
    click('[data-testid="play-s1"]'); // same clip again -> stop
    expect(shorts()?.getAttribute('data-playing')).toBe('');
  });

  it('forwards open-folder and delete actions', () => {
    const onOpenFolder = vi.fn();
    const onDelete = vi.fn();
    renderModal({ onOpenFolder, onDelete });
    click('[data-testid="folder-s1"]');
    expect(onOpenFolder).toHaveBeenCalledWith('/out/s1.mp4');
    click('[data-testid="delete-s1"]');
    expect(onDelete).toHaveBeenCalledWith('/out/s1.mp4');
  });

  it('maps the re-export affordance to onEdit(short) when Studio editing is wired', () => {
    const onEdit = vi.fn();
    const short = makeShort({ id: 's7', path: '/out/s7.mp4', hook: 'Hook 7' });
    renderModal({ shorts: [short], onEdit });
    click('[data-testid="edit-s7"]');
    expect(onEdit).toHaveBeenCalledWith(short);
  });

  it('renders no edit affordance when onEdit is absent', () => {
    renderModal();
    expect(container.querySelector('[data-testid="edit-s1"]')).toBeNull();
  });
});
