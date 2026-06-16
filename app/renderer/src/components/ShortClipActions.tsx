// ShortClipActions.tsx — the per-clip action row shared by the Shorts gallery
// (views/Shorts.tsx) and the ShortMaker exported-clips list (P4 §6 / C11).
//
// Pure presentational: it renders Play/Stop, Open folder, Re-export and Delete
// buttons and calls the injected callbacks with the clip path. The aria-labels
// embed a human label so multiple rows on a page stay distinguishable (and
// test-addressable). It owns NO rpc and NO state — both call sites supply the
// behavior, so the destructive confirm + reload live where the data does.
import React from 'react';

export interface ShortClipActionsProps {
  /** Absolute path of the exported clip (passed back to every callback). */
  path: string;
  /** Human label embedded into each button's aria-label (source title / file). */
  label: string;
  /** True while this clip's inline preview is open (Play -> Stop). */
  playing: boolean;
  onPlay: (path: string) => void;
  onOpenFolder: (path: string) => void;
  onReexport: (path: string) => void;
  onDelete: (path: string) => void;
}

export function ShortClipActions({
  path,
  label,
  playing,
  onPlay,
  onOpenFolder,
  onReexport,
  onDelete,
}: ShortClipActionsProps): React.ReactElement {
  return (
    <div className="shorts__actions">
      <button type="button" aria-label={`Play ${label}`} onClick={() => onPlay(path)}>
        {playing ? 'Stop' : 'Play'}
      </button>
      <button
        type="button"
        aria-label={`Open folder for ${label}`}
        onClick={() => onOpenFolder(path)}
      >
        Open folder
      </button>
      <button type="button" aria-label={`Re-export ${label}`} onClick={() => onReexport(path)}>
        Re-export
      </button>
      <button
        type="button"
        className="shorts__delete"
        aria-label={`Delete ${label}`}
        onClick={() => onDelete(path)}
      >
        Delete
      </button>
    </div>
  );
}

export default ShortClipActions;
