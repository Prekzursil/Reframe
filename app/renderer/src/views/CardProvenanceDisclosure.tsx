// CardProvenanceDisclosure.tsx — v1.5 shell-polish: demote the Library card's
// source/storage "plumbing" behind a per-card disclosure (fixes the re-introduced
// "Library foregrounds plumbing" P1). The resting card is poster + title + shorts
// + compact status; the source path / on-disk state / Show-in-folder / Relink /
// Keep-a-copy tail only appears when the user opens this disclosure.
//
// It mirrors the CapabilitiesChip disclosure pattern (a real toggle <button> with
// aria-expanded + aria-controls + a caret) and, like it, is LAZY: <LibraryProvenance>
// mounts only once opened, so a resting library of N cards fires zero reveal/pin
// probes. The toggle is a SIBLING of the card's open-button (never nested), so no
// nested-interactive control is introduced.
import React, { useId, useState } from 'react';

import {
  LibraryProvenance,
  type ProvenanceHandlers,
  type ProvenanceVideo,
} from '../features/LibraryProvenance';
import '../components/library-cards.css';

export interface CardProvenanceDisclosureProps {
  /** The card's asset (id + by-path source + title). */
  video: ProvenanceVideo;
  /** The injected L5 provenance handlers passed straight to <LibraryProvenance>. */
  handlers: ProvenanceHandlers;
}

export function CardProvenanceDisclosure({
  video,
  handlers,
}: CardProvenanceDisclosureProps): React.ReactElement {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <section className="card-provenance" aria-label="Source & storage">
      <button
        type="button"
        className="card-provenance__toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="card-provenance__label">{'Source & storage'}</span>
        <span className="card-provenance__caret" aria-hidden="true">
          {open ? '▴' : '▾'}
        </span>
      </button>

      {open ? (
        <div id={panelId} className="card-provenance__panel">
          <LibraryProvenance video={video} handlers={handlers} />
        </div>
      ) : null}
    </section>
  );
}

export default CardProvenanceDisclosure;
