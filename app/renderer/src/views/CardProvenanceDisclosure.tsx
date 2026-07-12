// CardProvenanceDisclosure.tsx — v1.5 shell-polish: demote the Library card's
// source/storage "plumbing" behind a per-card disclosure (fixes the re-introduced
// "Library foregrounds plumbing" P1). The resting card is poster + title + shorts
// + compact status; the source path / on-disk state / Show-in-folder / Relink /
// Keep-a-copy tail only appears when the user opens this disclosure.
//
// It mirrors the CapabilitiesChip disclosure pattern (a real toggle <button> with
// aria-expanded + aria-controls + a caret) and, like it, is LAZY: the heavy
// <LibraryProvenance> body mounts only once opened, so a resting library of N cards
// fires zero reveal/pin probes. Per the WAI-ARIA disclosure pattern the controlled
// panel element is ALWAYS rendered and merely toggles its `hidden` attribute, so a
// resting card's aria-controls is never a dangling IDREF (the panel is present but
// empty + hidden until opened). The wrapper is a plain <div>, NOT a <section> — a
// per-card landmark would mint N identical "region"s across the Library; the toggle
// button already names the disclosure. The toggle is a SIBLING of the card's
// open-button (never nested), so no nested-interactive control is introduced.
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
    <div className="card-provenance">
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

      {/* Panel is ALWAYS rendered so aria-controls resolves at rest; `hidden`
          collapses it and the heavy provenance body stays lazy until opened. */}
      <div id={panelId} className="card-provenance__panel" hidden={!open}>
        {open ? <LibraryProvenance video={video} handlers={handlers} /> : null}
      </div>
    </div>
  );
}

export default CardProvenanceDisclosure;
