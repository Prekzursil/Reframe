// CapabilitiesChip.tsx — the Library "Capabilities: N of M installed" disclosure
// (v1.5 §4/§P5). It fixes the redesign's cryptic capabilities chip: it binds a
// real NOUN + a real count (ready / total capabilities) that is SEPARATE from the
// visible card count (a plumbing count must never collide with the video count),
// and it discloses the detail on demand instead of an always-open section.
//
// It reuses the SHIPPED readiness primitives — `readiness.summary` (WU-8) for the
// data and <ReadinessBadge/> (WU-9) for each row — so the status is announced by
// TEXT + role, never hue alone, and the jargon rewrite lands at readinessMeta's
// source (not here). One fetch (no double-load); the eager preload-bridge throw is
// caught sync-safely, exactly as ReadinessRollup guards it.
import React, { useEffect, useId, useState } from 'react';
import { client, type ReadinessAction, type ReadinessItem } from '../lib/rpc';
import { ReadinessBadge } from '../components/ReadinessBadge';
import '../components/readinessBadge.css';
import '../components/library-shell.css';

/** Error text from an unknown thrown value (mirrors the sibling panels). */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export interface CapabilitiesChipProps {
  /** Inject the typed client for tests; defaults to the real lib/rpc client. */
  rpcClient?: Pick<typeof client, 'readiness'>;
  /** Fired when a row's fix action is clicked (parent owns the routing). */
  onAction?: (action: ReadinessAction) => void;
}

export function CapabilitiesChip({
  rpcClient,
  onAction,
}: CapabilitiesChipProps): React.ReactElement {
  const api = rpcClient ?? client;
  const [items, setItems] = useState<ReadinessItem[] | null>(null);
  const [error, setError] = useState<string>('');
  const [open, setOpen] = useState(false);
  const panelId = useId();

  useEffect(() => {
    let alive = true;
    setError('');
    setItems(null);
    // The bridge access is EAGER — `api.readiness.summary()` reaches through the
    // preload bridge, which throws SYNCHRONOUSLY when window.api is missing (before
    // Promise.resolve can wrap it). Guard it sync-safely so a missing bridge
    // degrades to an inline error here instead of a thrown-through blank screen.
    try {
      Promise.resolve(api.readiness.summary())
        .then((res) => {
          if (alive) setItems(Array.isArray(res?.items) ? res.items : []);
        })
        .catch((err: unknown) => {
          if (alive) setError(errText(err));
        });
    } catch (err) {
      setError(errText(err));
    }
    return () => {
      alive = false;
    };
  }, [api]);

  const ready = items ? items.filter((i) => i.status === 'ready').length : 0;
  const total = items ? items.length : 0;
  const label =
    items === null
      ? 'Capabilities: checking…'
      : total === 0
        ? 'Capabilities: none reported'
        : `Capabilities: ${ready} of ${total} installed`;

  return (
    <section className="capabilities-chip" aria-label="Capabilities">
      <button
        type="button"
        className="capabilities-chip__toggle"
        aria-expanded={open}
        aria-controls={panelId}
        aria-busy={items === null && !error}
        disabled={items === null || total === 0}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="capabilities-chip__text">
          {error ? 'Capabilities: unavailable' : label}
        </span>
        <span className="capabilities-chip__caret" aria-hidden="true">
          {open ? '▴' : '▾'}
        </span>
      </button>

      {error ? (
        <p className="capabilities-chip__error" role="alert">
          {error}
        </p>
      ) : null}

      {open && items && total > 0 ? (
        <ul id={panelId} className="capabilities-chip__list">
          {items.map((item) => (
            <li key={item.capability} className="capabilities-chip__row">
              <span className="capabilities-chip__cap">{item.label}</span>
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
      ) : null}
    </section>
  );
}

export default CapabilitiesChip;
