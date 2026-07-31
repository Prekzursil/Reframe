// ShortsGalleryModal.tsx — the produced-shorts gallery/picker (v1.5 §4 P0).
//
// The one-to-many model: a Library card's "N shorts" label opens THIS modal for
// that source video. It reuses the shipped <ProducedShorts/> gallery (poster,
// virality, duration, sort, per-clip actions) on a glass floating surface, so the
// one clip -> many shorts relationship finally has a real home. Each short is
// editable in Studio via `onEdit` (wired to the re-export/open affordance).
//
// Presentational + controlled: the parent (Library) owns which video's gallery is
// open and the shorts list; this owns only the inline-play state + the dialog
// shell (backdrop-close). Motion is neutralised by the global
// prefers-reduced-motion rule in shell.css.
//
// F04: keyboard focus management is delegated to the shared useFocusTrap (Lane 0
// F4 / R-M10), matching the renderer's three other role="dialog" surfaces
// (FirstRunChooser, ModelsOnboarding, DirectorOnboarding). The hook moves focus
// to the close control on mount, traps Tab/Shift+Tab inside the dialog, maps
// Escape to onClose, and restores focus to the Library card's "N shorts" opener
// on unmount — which a local onKeyDown + focus-on-open ref could not do.
import React, { useCallback, useMemo, useState } from 'react';

import { useFocusTrap } from '../hooks/useFocusTrap';
import { ProducedShorts } from '../features/ProducedShorts';
import type { ShortInfo } from '../lib/rpc';
import '../components/library-shell.css';

export interface ShortsGalleryModalProps {
  /** Source video title (the dialog's accessible name + heading). */
  title: string;
  /** This video's produced shorts (already grouped by the parent). */
  shorts: ShortInfo[];
  onClose: () => void;
  /** Reveal a clip in the OS file explorer. */
  onOpenFolder: (path: string) => void;
  /** Delete a produced clip (the parent confirms + removes the file). */
  onDelete: (path: string) => void;
  /** "Edit in Studio" — reopen the short for further editing. */
  onEdit?: (short: ShortInfo) => void;
}

export function ShortsGalleryModal({
  title,
  shorts,
  onClose,
  onOpenFolder,
  onDelete,
  onEdit,
}: ShortsGalleryModalProps): React.ReactElement {
  const [playingShortPath, setPlayingShortPath] = useState('');

  // Trap focus inside the dialog: initial focus on the close control, Tab cycles
  // within, Escape dismisses, focus returns to the opener on unmount.
  const trapRef = useFocusTrap<HTMLDivElement>({
    onEscape: onClose,
    initialFocus: '.shorts-modal__close',
  });

  const play = useCallback((path: string) => {
    setPlayingShortPath((cur) => (cur === path ? '' : path));
  }, []);

  // ProducedShorts' re-export action hands back a clip PATH; map it to the clip so
  // "edit in Studio" gets the full ShortInfo. The path always resolves (it comes
  // from the rendered list), so the lookup is total.
  const byPath = useMemo(() => new Map(shorts.map((s) => [s.path, s])), [shorts]);
  const onReexport = onEdit
    ? (path: string): void => {
        onEdit(byPath.get(path) as ShortInfo);
      }
    : undefined;

  return (
    <div className="shorts-modal__backdrop" onClick={onClose}>
      {/* The dialog stops backdrop-close on inner clicks; it is dismissed by the
          close button or Escape (via the focus trap), so it is not itself an
          interactive control. */}
      <div
        ref={trapRef}
        className="shorts-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Produced shorts for ${title}`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="shorts-modal__head">
          <h2 className="shorts-modal__title">{title}</h2>
          <button
            type="button"
            className="shorts-modal__close"
            aria-label="Close produced shorts"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="shorts-modal__body">
          {shorts.length === 0 ? (
            <p className="shorts-modal__empty">No shorts for this video yet.</p>
          ) : (
            <ProducedShorts
              shorts={shorts}
              playingShortPath={playingShortPath}
              onPlay={play}
              onOpenFolder={onOpenFolder}
              onReexport={onReexport}
              onDelete={onDelete}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default ShortsGalleryModal;
