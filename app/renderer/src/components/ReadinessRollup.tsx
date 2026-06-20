// ReadinessRollup.tsx — the unified "what works right now" roll-up (WU-14).
//
// The integration join: it CONSUMES `readiness.summary` (WU-8) and renders one
// shared <ReadinessBadge /> (WU-9) per capability, each with its capability-tied
// fix action. It is the single roll-up surface reused on BOTH the library home
// and the model panel (DESIGN §3.4), so neither panel re-derives readiness.
//
// While the summary is in flight it reuses JobQueue's existing skeleton/empty
// convention (`jobqueue__empty`) rather than inventing a bespoke loader
// (DESIGN §3.4 "Empty / loading states"). A load failure degrades to a quiet
// inline alert — it never blocks the host panel. Actions are forwarded to the
// parent via `onAction` (the parent owns navigation to the providers/assets
// flows), keeping this component a thin, side-effect-free consumer.
import React, { useEffect, useState } from 'react';
import { client, type ReadinessAction, type ReadinessItem } from '../lib/rpc';
import { ReadinessBadge } from './ReadinessBadge';
import './readinessBadge.css';

/** Error text from an unknown thrown value (mirrors the sibling panels). */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export interface ReadinessRollupProps {
  /** Inject the typed client for tests; defaults to the real lib/rpc client. */
  rpcClient?: Pick<typeof client, 'readiness'>;
  /** Section heading; defaults to a neutral label both hosts can reuse. */
  title?: string;
  /** Fired when a badge's fix action is clicked (parent owns the routing). */
  onAction?: (action: ReadinessAction) => void;
}

export function ReadinessRollup({
  rpcClient,
  title = 'Readiness',
  onAction,
}: ReadinessRollupProps): React.ReactElement {
  /* v8 ignore next -- the `?? client` default only runs in the real app; every test injects rpcClient. */
  const api = rpcClient ?? client;
  const [items, setItems] = useState<ReadinessItem[] | null>(null);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    let alive = true;
    setError('');
    setItems(null);
    Promise.resolve(api.readiness.summary())
      .then((res) => {
        if (alive) setItems(Array.isArray(res?.items) ? res.items : []);
      })
      .catch((err: unknown) => {
        if (alive) setError(errText(err));
      });
    return () => {
      alive = false;
    };
  }, [api]);

  return (
    <section className="readiness-rollup" aria-label={title}>
      <h3 className="readiness-rollup__title">{title}</h3>

      {error ? (
        <p className="readiness-rollup__error jobqueue__error" role="alert">
          {error}
        </p>
      ) : items === null ? (
        // Reuse JobQueue's skeleton/empty convention while in flight.
        <div className="jobqueue__empty" aria-busy="true">
          Checking what's ready…
        </div>
      ) : items.length === 0 ? (
        <div className="readiness-rollup__empty">Nothing to report.</div>
      ) : (
        <ul className="readiness-rollup__list">
          {items.map((item) => (
            <li key={item.capability} className="readiness-rollup__row">
              <span className="readiness-rollup__cap">{item.label}</span>
              <ReadinessBadge
                status={item.status}
                capabilityLabel={item.label}
                blockedBy={item.blockedBy || undefined}
                action={item.action}
                onAction={onAction}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default ReadinessRollup;
