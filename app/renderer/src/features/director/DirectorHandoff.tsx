// DirectorHandoff.tsx — the "where your edit lands" review surface (§4 Director).
//
// The Director does NOT silently apply: its proposed edit decomposes into
// REVIEWABLE per-phase diffs (cuts -> Edit, keyframes -> Caption, crop -> Reframe).
// This panel makes that promise legible — the routing contract plus each phase's
// LIVE landing-zone status read from the shared editor state (`useEditor`) — and
// restates the brand's reversible-edit + text-egress trust microcopy VERBATIM in
// the AA-safe quiet step (never #50555F). A thin context consumer: it owns no
// editor state, only reads it.

import React from 'react';
import { useEditor } from '../EditorContext';
import { TRUST_REVERSIBLE, TRUST_TEXT_EGRESS, handoffRows } from '../../lib/directorHandoff';
import './directorHandoff.css';

export function DirectorHandoff(): React.ReactElement {
  const { state } = useEditor();
  const rows = handoffRows(state);

  return (
    <aside className="director-handoff" aria-label="Where your edit lands">
      <h3 className="director-handoff__title">Where your edit lands</h3>
      <p className="director-handoff__lede">{TRUST_REVERSIBLE}</p>
      <ol className="director-handoff__routes">
        {rows.map((row) => (
          <li
            key={row.phase}
            className="director-handoff__route"
            data-phase={row.phase}
            data-ready={row.ready ? 'yes' : 'no'}
          >
            <div className="director-handoff__route-head">
              <span className="director-handoff__change">{row.change}</span>
              <span className="director-handoff__arrow" aria-hidden="true">
                →
              </span>
              <span className="director-handoff__dest">{row.destination}</span>
            </div>
            <p className="director-handoff__blurb">{row.blurb}</p>
            <p className="director-handoff__status" data-testid={`zone-${row.phase}`}>
              {row.status}
            </p>
          </li>
        ))}
      </ol>
      <p className="director-handoff__egress">{TRUST_TEXT_EGRESS}</p>
    </aside>
  );
}

export default DirectorHandoff;
