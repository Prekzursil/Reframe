// ExportProgress.tsx — determinate export progress + a REAL cancel (v1.5 §4).
//
// The Wave-0 real-cancel needs its UI home here: a DETERMINATE bar (never the
// forever-spinning optimistic pill the redesign rejects), the percent in amber
// tabular-nums mono, a polite aria-live status line, and a live Cancel that maps to
// `job.cancel`. Controlled + presentational: the parent (the Export view) owns the
// progress stream + the cancel handler.

import React from 'react';
import './export.css';

export interface ExportProgressProps {
  /** The destination being rendered (e.g. "TikTok"). */
  destination: string;
  /** Determinate progress 0-100. */
  pct: number;
  /** The current step message (announced politely). */
  message: string;
  /** Cancel the in-flight render (maps to job.cancel). */
  onCancel: () => void;
}

export function ExportProgress({
  destination,
  pct,
  message,
  onCancel,
}: ExportProgressProps): React.ReactElement {
  return (
    <section className="export-progress" aria-label="Exporting">
      <div className="export-progress__head">
        <h3 className="export-progress__title">Exporting to {destination}</h3>
        <span className="export-progress__pct">{Math.round(pct)}%</span>
      </div>
      <progress
        className="export-progress__track"
        max={100}
        value={pct}
        aria-label="Export progress"
      />
      <p className="export-progress__message" role="status" aria-live="polite">
        {message}
      </p>
      <button type="button" className="export-progress__cancel" onClick={onCancel}>
        Cancel export
      </button>
    </section>
  );
}

export default ExportProgress;
