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
import React, { useCallback, useEffect, useRef, useState } from 'react';
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
  /**
   * Fired when a badge's fix action is clicked (parent owns the routing).
   *
   * F36: may return a Promise. When it does, the roll-up marks that capability's
   * button busy for the whole action and RE-READS `readiness.summary` when it
   * settles — otherwise the badge kept displaying the pre-fix status for the rest
   * of the mount (the only cure was leaving and re-entering the sub-tab).
   */
  onAction?: (action: ReadinessAction) => void | Promise<void>;
}

/**
 * F36: action kinds that NAVIGATE AWAY instead of fixing anything in place.
 * `ModelsSystemPanel.handleReadinessAction` returns early for these and calls
 * `onOpenProviders()`, which routes to another Settings section and UNMOUNTS this
 * tree — so a busy flash and a post-action refetch there would be a lie plus a
 * wasted RPC on a dying tree.
 */
function navigatesAway(action: ReadinessAction): boolean {
  return action.kind === 'openProviders' || action.kind === 'setConsent';
}

export function ReadinessRollup({
  rpcClient,
  title = 'Readiness',
  onAction,
}: ReadinessRollupProps): React.ReactElement {
  /* v8 ignore next -- the `?? client` default runs in the real app + the WU2 resilience test (window.api missing); most tests inject rpcClient. */
  const api = rpcClient ?? client;
  const [items, setItems] = useState<ReadinessItem[] | null>(null);
  const [error, setError] = useState<string>('');
  // F36: the capability whose fix action is in flight (drives the badge's busy).
  const [pending, setPending] = useState<string | null>(null);
  // F36: liveness as a REF, not the mount effect's closure — the post-action
  // refresh outlives that closure (an `assets.ensure` job can run for minutes),
  // so it needs a guard the unmount actually flips for it too.
  const aliveRef = useRef<boolean>(true);

  // F36: extracted so BOTH the mount effect and the post-action path re-read it.
  // It deliberately does NOT reset `items` to null — keeping the previous rows
  // visible stops the refresh flashing the "Checking what's ready…" skeleton.
  const load = useCallback((): void => {
    // WU2 resilience: the bridge access is EAGER — `api.readiness.summary()`
    // reaches through the preload bridge, which throws SYNCHRONOUSLY when
    // window.api is missing (before Promise.resolve can wrap it, so `.catch`
    // below never sees it). Guard it sync-safely so a missing bridge degrades to
    // an inline error here instead of a thrown-through blank screen.
    try {
      Promise.resolve(api.readiness.summary())
        .then((res) => {
          if (aliveRef.current) setItems(Array.isArray(res?.items) ? res.items : []);
        })
        .catch((err: unknown) => {
          if (aliveRef.current) setError(errText(err));
        });
    } catch (err) {
      setError(errText(err));
    }
  }, [api]);

  useEffect(() => {
    aliveRef.current = true;
    setError('');
    setItems(null);
    load();
    return () => {
      aliveRef.current = false;
    };
  }, [load]);

  // F36: forward the action, hold the button busy for its whole duration, then
  // re-read the summary so the badge shows the POST-fix truth in place.
  const runAction = useCallback(
    (action: ReadinessAction, capability: string): void => {
      if (navigatesAway(action)) {
        onAction?.(action);
        return;
      }
      setPending(capability);
      Promise.resolve(onAction?.(action))
        // The PARENT owns the failure surface (it sets its own `error`); the
        // roll-up must not invent a second one. It still refreshes, because a
        // partially-successful ensure can legitimately change readiness.
        .catch(() => undefined)
        .finally(() => {
          if (aliveRef.current) {
            setPending(null);
            load();
          }
        });
    },
    [load, onAction],
  );

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
          Checking what’s ready…
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
                onAction={(action) => runAction(action, item.capability)}
                busy={pending === item.capability}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default ReadinessRollup;
