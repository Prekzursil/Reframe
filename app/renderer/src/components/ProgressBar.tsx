import React from 'react';

export interface ProgressBarProps {
  /** 0..100 (values are clamped). */
  pct: number;
  /** Optional label shown alongside the bar. */
  message?: string;
}

/** Clamp an arbitrary number into the 0..100 progress range. */
export function clampPct(pct: number): number {
  if (Number.isNaN(pct)) return 0;
  if (pct < 0) return 0; // also catches -Infinity
  if (pct > 100) return 100; // also catches +Infinity
  return pct;
}

/** A determinate progress bar driven by a 0..100 percentage. */
export function ProgressBar({ pct, message }: ProgressBarProps): React.ReactElement {
  const value = clampPct(pct);
  return (
    <div className="progress">
      <div
        className="progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
      >
        <div className="progress__fill" style={{ width: `${value}%` }} />
      </div>
      {message !== undefined && message !== '' ? (
        <span className="progress__label">{message}</span>
      ) : null}
    </div>
  );
}

export default ProgressBar;
