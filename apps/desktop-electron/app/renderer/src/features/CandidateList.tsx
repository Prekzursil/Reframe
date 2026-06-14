// CandidateList.tsx — the Short-maker candidate review list + row (presentational).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget. The
// list is pure given props (the review state + decision/nudge callbacks live in
// ShortMaker); only CandidateRow holds local UI state (the factor-breakdown
// disclosure). ShortMaker re-exports these so existing importers keep one entry.
import React, { useState } from 'react';

import {
  type ReviewItem,
  displayVirality,
  factorEntries,
  fmtTime,
} from './shortMakerLogic';

interface CandidateListProps {
  items: ReviewItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onApprove: (id: string) => void;
  onDiscard: (id: string) => void;
  onReinstate: (id: string) => void;
  onNudge: (id: string, deltaStart: number, deltaEnd: number) => void;
  onReset: (id: string) => void;
}

export function CandidateList(props: CandidateListProps): React.JSX.Element {
  const { items, selectedId, onSelect, onApprove, onDiscard, onReinstate, onNudge, onReset } =
    props;
  return (
    <ol className="sm-candidates" aria-label="Candidate clips">
      {items.map((item) => (
        <CandidateRow
          key={item.id}
          item={item}
          selected={item.id === selectedId}
          onSelect={onSelect}
          onApprove={onApprove}
          onDiscard={onDiscard}
          onReinstate={onReinstate}
          onNudge={onNudge}
          onReset={onReset}
        />
      ))}
    </ol>
  );
}

interface CandidateRowProps {
  item: ReviewItem;
  selected: boolean;
  onSelect: (id: string) => void;
  onApprove: (id: string) => void;
  onDiscard: (id: string) => void;
  onReinstate: (id: string) => void;
  onNudge: (id: string, deltaStart: number, deltaEnd: number) => void;
  onReset: (id: string) => void;
}

/** Default nudge step in seconds. */
export const NUDGE_STEP = 1;

export function CandidateRow(props: CandidateRowProps): React.JSX.Element {
  const { item, selected, onSelect, onApprove, onDiscard, onReinstate, onNudge, onReset } = props;
  const c = item.current;
  const nudged =
    item.current.start !== item.original.start || item.current.end !== item.original.end;
  // P3-C: virality % is the headline number; the legacy LLM score demotes to a
  // tooltip on it. Candidates from pre-P3 payloads keep the old score chip.
  const virality = displayVirality(c.viralityPct);
  const factors = factorEntries(c);
  const [factorsOpen, setFactorsOpen] = useState(false);
  return (
    <li
      className={`sm-candidate sm-${item.status}${selected ? ' sm-selected' : ''}`}
      data-id={item.id}
      data-start={c.start}
      data-end={c.end}
      aria-label={`Candidate rank ${c.rank}`}
      aria-current={selected ? 'true' : undefined}
      onClick={() => onSelect(item.id)}
    >
      <div className="sm-rank-score">
        <span className="sm-rank">#{c.rank}</span>
        {virality !== null ? (
          <span className="sm-virality" aria-label="Virality" title={`Legacy score: ${c.score}`}>
            {virality}
            <span className="sm-virality-pct">%</span>
          </span>
        ) : (
          <span className="sm-score" aria-label="Score">
            {c.score}
          </span>
        )}
        <span className={`sm-status sm-status-${item.status}`}>{item.status}</span>
      </div>

      <p className="sm-hook">{c.hook}</p>
      <p className="sm-why">{c.why}</p>

      {factors.length > 0 && (
        <div className="sm-factors-block">
          <button
            type="button"
            className="sm-factors-toggle"
            aria-label="Factor breakdown"
            aria-expanded={factorsOpen}
            onClick={(e) => {
              e.stopPropagation();
              setFactorsOpen((v) => !v);
            }}
          >
            Factors {factorsOpen ? '▾' : '▸'}
          </button>
          {factorsOpen && (
            <ul className="sm-factors" aria-label="Virality factors">
              {factors.map((f) => (
                <li key={f.key} className="sm-factor" data-factor={f.key} data-value={f.value}>
                  <span className="sm-factor-label">{f.label}</span>
                  <span className="sm-factor-value">{f.value}</span>
                  <span className="sm-factor-bar">
                    <span className="sm-factor-fill" style={{ width: `${f.value}%` }} />
                  </span>
                  {f.note && <span className="sm-factor-note">{f.note}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="sm-times">
        {fmtTime(c.start)}–{fmtTime(c.end)} ({Math.round(c.durationSec)}s)
        {nudged && <span className="sm-nudged"> (nudged)</span>}
      </p>

      <div className="sm-row-actions">
        <button type="button" onClick={() => onNudge(item.id, -NUDGE_STEP, 0)} aria-label="Earlier start">
          ⟸ start
        </button>
        <button type="button" onClick={() => onNudge(item.id, NUDGE_STEP, 0)} aria-label="Later start">
          start ⟹
        </button>
        <button type="button" onClick={() => onNudge(item.id, 0, -NUDGE_STEP)} aria-label="Earlier end">
          ⟸ end
        </button>
        <button type="button" onClick={() => onNudge(item.id, 0, NUDGE_STEP)} aria-label="Later end">
          end ⟹
        </button>
        {nudged && (
          <button type="button" onClick={() => onReset(item.id)} aria-label="Reset boundaries">
            Reset
          </button>
        )}
      </div>

      <div className="sm-row-decide">
        {item.status !== 'approved' && (
          <button type="button" onClick={() => onApprove(item.id)} aria-label="Approve">
            Approve
          </button>
        )}
        {item.status !== 'discarded' && (
          <button type="button" onClick={() => onDiscard(item.id)} aria-label="Discard">
            Discard
          </button>
        )}
        {item.status !== 'pending' && (
          <button type="button" onClick={() => onReinstate(item.id)} aria-label="Reinstate">
            Reinstate
          </button>
        )}
      </div>
    </li>
  );
}
