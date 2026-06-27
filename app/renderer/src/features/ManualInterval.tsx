// ManualInterval.tsx — the MANUAL interval shorts mode (V1 IA §h).
//
// The non-AI path in Make Shorts: the user types explicit ranges (e.g. 1:23 ->
// 4:10), each is validated + added to a list, and "Make shorts from ranges"
// turns them into inline export candidates handed to the parent (which runs
// shortmaker.export + shows the Output Tray). All timecode parsing + the
// range -> Candidate mapping lives in the pure manualInterval module.
import React, { useState } from 'react';
import type { Candidate } from '../lib/rpc';
import {
  buildManualCandidates,
  formatTimecode,
  type ManualRange,
  parseTimecode,
} from './manualIntervalLogic';
import './manualInterval.css';

export interface ManualIntervalProps {
  /** Fired with the built inline candidates when the user makes the shorts. */
  onSubmit: (candidates: Candidate[]) => void;
  /** Disable submission while an export is in flight. */
  busy?: boolean;
  /** Disable the whole control (e.g. no video selected yet). */
  disabled?: boolean;
}

/** Manual time-interval shorts builder. */
export function ManualInterval({
  onSubmit,
  busy = false,
  disabled = false,
}: ManualIntervalProps): React.ReactElement {
  const [startText, setStartText] = useState('');
  const [endText, setEndText] = useState('');
  const [ranges, setRanges] = useState<ManualRange[]>([]);
  const [error, setError] = useState<string | null>(null);

  function addRange(): void {
    const start = parseTimecode(startText);
    const end = parseTimecode(endText);
    if (start === null || end === null) {
      setError('Enter a valid start and end time (e.g. 1:23 and 4:10).');
      return;
    }
    if (end <= start) {
      setError('The end time must be after the start time.');
      return;
    }
    setRanges((prev) => [...prev, { start, end }]);
    setStartText('');
    setEndText('');
    setError(null);
  }

  function removeRange(index: number): void {
    setRanges((prev) => prev.filter((_, i) => i !== index));
  }

  function submit(): void {
    onSubmit(buildManualCandidates(ranges));
  }

  return (
    <div className="manual-interval">
      <div className="manual-interval__add">
        <label className="manual-interval__field">
          <span>Start</span>
          <input
            aria-label="Range start"
            type="text"
            placeholder="1:23"
            value={startText}
            disabled={disabled}
            onChange={(e) => setStartText(e.target.value)}
          />
        </label>
        <span className="manual-interval__arrow" aria-hidden="true">
          →
        </span>
        <label className="manual-interval__field">
          <span>End</span>
          <input
            aria-label="Range end"
            type="text"
            placeholder="4:10"
            value={endText}
            disabled={disabled}
            onChange={(e) => setEndText(e.target.value)}
          />
        </label>
        <button type="button" onClick={addRange} disabled={disabled}>
          Add range
        </button>
      </div>

      {error ? (
        <p className="manual-interval__error" role="alert">
          {error}
        </p>
      ) : null}

      {ranges.length > 0 ? (
        <ul className="manual-interval__list">
          {ranges.map((r, i) => (
            <li className="manual-interval__range" key={`${r.start}-${r.end}-${i}`}>
              <span>
                {formatTimecode(r.start)} → {formatTimecode(r.end)}
              </span>
              <button type="button" aria-label="Remove range" onClick={() => removeRange(i)}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <button
        type="button"
        className="manual-interval__make"
        onClick={submit}
        disabled={busy || ranges.length === 0}
      >
        Make shorts from ranges
      </button>
    </div>
  );
}

export default ManualInterval;
