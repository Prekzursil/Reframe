import React, { useCallback, useEffect, useState } from 'react';

import { LineageActions, type LineageActionHandlers } from './LineageActions';
import { LineageCard } from './LineageCard';
import type { LineageNode, LineageResult } from '../lib/rpc';
import './lineage.css';

// LineagePanel.tsx — L4 asset-detail drawer (DESIGN §3.4).
//
// Opened from the Library "Lineage" view for one asset. Fetches
// `library.lineage {id}` (injected so it is trivially testable + lane-decoupled)
// and renders the provenance card (LineageCard) plus the "Made from" /
// "Used to make" expanders (PROV ancestors/descendants). A fetch failure is
// surfaced LOUDLY (role="alert") — never a silent empty drawer.

export interface LineageAsset {
  id: string;
  title: string;
}

export interface LineagePanelProps {
  /** The asset whose provenance to show. */
  asset: LineageAsset;
  /** Injected `library.lineage` loader (Library passes the bridge-backed one). */
  loadLineage: (id: string) => Promise<LineageResult>;
  /** Close the drawer. */
  onClose: () => void;
  /**
   * Optional L5 action slice (reveal source / regenerate / relink). When present,
   * the drawer renders the action row under the provenance card; absent -> the
   * card stays read-only (the L4 behaviour). Injected so unit tests stay decoupled.
   */
  actions?: LineageActionHandlers;
}

type Phase =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'loaded'; result: LineageResult };

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Display text for one ancestor/descendant node (loud about missing sources). */
function nodeText(node: LineageNode): string {
  if ('missing' in node) {
    return `${node.id} — no longer in your library`;
  }
  return node.title === '' ? node.id : node.title;
}

/** One PROV relation expander ("Made from ▸" / "Used to make ▸"). */
function NodeList({
  heading,
  nodes,
}: {
  heading: string;
  nodes: LineageNode[];
}): React.ReactElement {
  return (
    <details className="lineage-panel__rel">
      <summary className="lineage-panel__rel-summary">
        {heading} ({nodes.length})
      </summary>
      {nodes.length === 0 ? (
        <p className="lineage-panel__rel-empty">Nothing yet.</p>
      ) : (
        <ul className="lineage-panel__rel-list">
          {nodes.map((node) => (
            <li
              key={node.id}
              className={`lineage-panel__rel-item${'missing' in node ? ' lineage-panel__rel-item--missing' : ''}`}
            >
              {nodeText(node)}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

export function LineagePanel({
  asset,
  loadLineage,
  onClose,
  actions,
}: LineagePanelProps): React.ReactElement {
  const [phase, setPhase] = useState<Phase>({ status: 'loading' });

  useEffect(() => {
    let live = true;
    setPhase({ status: 'loading' });
    loadLineage(asset.id)
      .then((result) => {
        if (live) setPhase({ status: 'loaded', result });
      })
      .catch((err: unknown) => {
        if (live) setPhase({ status: 'error', message: errText(err) });
      });
    return () => {
      live = false;
    };
  }, [asset.id, loadLineage]);

  const handleClose = useCallback(() => {
    onClose();
  }, [onClose]);

  return (
    <aside className="lineage-panel" aria-label={`Lineage of ${asset.title}`}>
      <header className="lineage-panel__header">
        <h2 className="lineage-panel__title">{asset.title}</h2>
        <button
          type="button"
          className="lineage-panel__close"
          aria-label="Close lineage"
          onClick={handleClose}
        >
          ×
        </button>
      </header>

      {phase.status === 'loading' ? (
        <p className="lineage-panel__loading">Loading history…</p>
      ) : phase.status === 'error' ? (
        <p className="lineage-panel__error" role="alert">
          Could not load history: {phase.message}
        </p>
      ) : (
        <div className="lineage-panel__body">
          <LineageCard entity={phase.result.entity} provenance={phase.result.provenance} />
          {actions ? <LineageActions asset={asset} actions={actions} /> : null}
          <NodeList heading="Made from" nodes={phase.result.ancestors} />
          <NodeList heading="Used to make" nodes={phase.result.descendants} />
        </div>
      )}
    </aside>
  );
}

export default LineagePanel;
