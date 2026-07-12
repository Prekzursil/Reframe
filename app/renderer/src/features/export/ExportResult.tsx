// ExportResult.tsx — the TERMINAL export states (v1.5 §4).
//
// Every async surface needs a terminal SUCCESS and a terminal FAILURE/cancel (§8
// DoD). SUCCESS wires to the real output location (a "Show in folder" reveal, the
// OutputTray role) and links INTO Deliver (finishing Phase-5 → batch publish).
// FAILURE surfaces the error in an assertive alert with a recovery action; SUCCESS
// and CANCEL announce their terminal outcome through a polite `role="status"` live
// region so completion reaches SR users too. Status is text + a green/amber/red
// edge, never hue alone. Controlled + presentational.

import React from 'react';
import './export.css';

/** The terminal outcome of a guarded export. */
export type ExportOutcome = 'done' | 'failed' | 'cancelled';

export interface ExportResultProps {
  outcome: ExportOutcome;
  /** The destination that was rendered (e.g. "TikTok"). */
  destination: string;
  /** The written output file paths (SUCCESS only). */
  paths: readonly string[];
  /** The failure message (FAILURE only). */
  error?: string;
  /** Reveal a written file in the OS file explorer (omit when unsupported). */
  onReveal?: (path: string) => void;
  /** Continue into the Deliver (batch/cross-video) surface. */
  onDeliver: () => void;
  /** Start another export of this clip (recovery / repeat). */
  onExportAgain: () => void;
}

export function ExportResult({
  outcome,
  destination,
  paths,
  error,
  onReveal,
  onDeliver,
  onExportAgain,
}: ExportResultProps): React.ReactElement {
  if (outcome === 'done') {
    return (
      <section className="export-result is-done" aria-label="Export result">
        <h3 className="export-result__title">Exported to {destination}</h3>
        <p className="export-result__blurb" role="status">
          Saved to your machine at its current framing — nothing was uploaded.
        </p>
        <ul className="export-result__outputs">
          {paths.map((path) => (
            <li key={path} className="export-result__output">
              <span className="export-result__path">{path}</span>
              {onReveal ? (
                <button
                  type="button"
                  className="export-result__reveal"
                  onClick={() => onReveal(path)}
                >
                  Show in folder
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        <div className="export-result__actions">
          <button type="button" className="export-result__deliver" onClick={onDeliver}>
            Continue to Deliver
          </button>
          <button type="button" className="export-result__again" onClick={onExportAgain}>
            Export another
          </button>
        </div>
      </section>
    );
  }

  const failed = outcome === 'failed';
  return (
    <section className={`export-result is-${outcome}`} aria-label="Export result">
      <h3 className="export-result__title">{failed ? 'Export failed' : 'Export cancelled'}</h3>
      {failed ? (
        <p className="export-result__error" role="alert">
          {error}
        </p>
      ) : (
        <p className="export-result__blurb" role="status">
          No file was written.
        </p>
      )}
      <div className="export-result__actions">
        <button type="button" className="export-result__again" onClick={onExportAgain}>
          Try again
        </button>
      </div>
    </section>
  );
}

export default ExportResult;
