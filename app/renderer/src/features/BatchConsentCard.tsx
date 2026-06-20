// BatchConsentCard.tsx — the pre-run batch consent summary (DESIGN §9 / §9.1).
//
// Rendered BEFORE batch.start from the pure `plan_consent` surface (zero provider
// calls). Shows the N-run / K-skip split, the per-source egress/cache-hit flags,
// the named skip list WITH reasons (visible-skip contract §9.1 — a skipped source
// is attributed, never silently absent), and a single "Acknowledge cloud egress"
// control. When `confirmCloudBudget` is OFF the card is informational only and
// requires no ack (all sources run).
//
// Pure presentational: the parent owns the consent data + the ack/run RPCs.
import React from 'react';
import type { BatchConsent } from '../lib/rpc';

export interface BatchConsentCardProps {
  consent: BatchConsent;
  /** Whether the per-call budget gate is on (drives ack requirement). */
  confirmCloudBudget: boolean;
  /** Whether the user has acknowledged cloud egress for this batch. */
  acknowledged: boolean;
  onAcknowledge: () => void;
  /** Map a videoId to a display title (falls back to the id). */
  titleFor: (videoId: string) => string;
}

/** The batch consent summary card (run/skip split + named, attributed skips). */
export function BatchConsentCard({
  consent,
  confirmCloudBudget,
  acknowledged,
  onAcknowledge,
  titleFor,
}: BatchConsentCardProps): React.ReactElement {
  const skips = consent.decisions.filter((d) => d.action === 'skip');
  const ackNeeded = confirmCloudBudget && !acknowledged;

  return (
    <section className="batch-consent" aria-label="Cloud egress consent">
      <h3 className="batch-consent__title">Before this batch runs</h3>
      <p className="batch-consent__split">
        {consent.willRun} of {consent.willRun + consent.willSkip} sources will run;{' '}
        {consent.willSkip} skipped
      </p>

      {skips.length > 0 ? (
        <div className="batch-consent__skips">
          <h4 className="batch-consent__skips-title">Skipped sources</h4>
          <ul>
            {skips.map((d) => (
              <li key={d.videoId} className="batch-consent__skip">
                <span className="batch-consent__skip-title">{titleFor(d.videoId)}</span>
                <span className="batch-consent__skip-reason"> — {d.skipReason ?? 'skipped'}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {confirmCloudBudget ? (
        <button
          type="button"
          className="batch-consent__ack"
          aria-pressed={acknowledged}
          disabled={acknowledged}
          onClick={onAcknowledge}
        >
          {acknowledged ? 'Cloud egress acknowledged' : 'Acknowledge cloud egress for this batch'}
        </button>
      ) : (
        <p className="batch-consent__info">
          No cloud-budget confirmation needed — all sources run.
        </p>
      )}

      {ackNeeded ? (
        <p className="batch-consent__hint" role="note">
          Acknowledge egress to run the cloud sources; otherwise they are skipped (and re-runnable
          later).
        </p>
      ) : null}
    </section>
  );
}

export default BatchConsentCard;
