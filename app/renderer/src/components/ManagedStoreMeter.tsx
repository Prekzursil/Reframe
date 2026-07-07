import React, { useCallback, useEffect, useRef, useState } from 'react';

import type { ManagedStatus } from '../lib/rpc';
import './managed-store-meter.css';

// ManagedStoreMeter.tsx — WU-3b2: the managed-copy store size meter for
// Settings > Storage.
//
// WU-3b1 lets the user keep an app-managed byte-copy of a source video so it
// survives the original being moved or deleted. Those copies accumulate under a
// cumulative cap (LRU-evicted when breached). This panel makes that store
// VISIBLE and MANAGEABLE:
//   * a used / cap meter (with the kept-copy count) driven by `library.managedStatus`,
//   * a per-copy evict affordance (re-point that video back to its original), and
//   * a "Clear all" affordance — every destructive action behind a two-step
//     in-place CONFIRM so nothing frees bytes on a single stray click.
//
// The `rpc` slice is injected so the panel unit-tests with plain fakes (mirrors
// PathsPanel's injected `paths` slice). It REUSES the WU-3b1 managed-store RPCs —
// no parallel store machinery.

/**
 * The thin managed-store RPC slice this panel needs (injectable for tests). Method
 * names match `client.library` so the app can pass that slice DIRECTLY — no adapter.
 */
export interface ManagedStoreRpc {
  /** `library.managedStatus` — the used/cap/count snapshot + kept rows. */
  managedStatus(): Promise<ManagedStatus>;
  /** `library.managedEvict {id}` — evict ONE video's managed copy back to its original. */
  managedEvict(id: string): Promise<unknown>;
  /** `library.managedClear` — evict EVERY managed copy. */
  managedClear(): Promise<unknown>;
}

export interface ManagedStoreMeterProps {
  /** The injected managed-store client slice. */
  rpc: ManagedStoreRpc;
}

const GB = 1024 ** 3;
const MB = 1024 ** 2;
const KB = 1024;

/** Human-readable byte size ("4.0 GB" / "512 B") for the meter + per-row sizes. */
function formatBytes(n: number): string {
  if (n <= 0) return '0 B';
  if (n >= GB) return `${(n / GB).toFixed(1)} GB`;
  if (n >= MB) return `${(n / MB).toFixed(1)} MB`;
  if (n >= KB) return `${(n / KB).toFixed(1)} KB`;
  return `${Math.round(n)} B`;
}

/** Last path component of an original source (a readable per-row label). */
function baseName(p: string): string {
  const parts = p.split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function ManagedStoreMeter({ rpc }: ManagedStoreMeterProps): React.ReactElement {
  const [snapshot, setSnapshot] = useState<ManagedStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [confirmEvict, setConfirmEvict] = useState<string | null>(null);

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const guard = useCallback((apply: () => void) => {
    if (mounted.current) apply();
  }, []);

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const snap = await rpc.managedStatus();
      guard(() => setSnapshot(snap));
    } catch (err) {
      guard(() => setError(errText(err)));
    }
  }, [guard, rpc]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // One runner for both destructive actions: run the op, re-read the snapshot so
  // the meter reflects the freed bytes, and surface any failure LOUDLY.
  const runAction = useCallback(
    (op: () => Promise<unknown>) => {
      setBusy(true);
      setConfirmClear(false);
      setConfirmEvict(null);
      setError(null);
      void (async () => {
        try {
          await op();
          await refresh();
          guard(() => setBusy(false));
        } catch (err) {
          guard(() => {
            setBusy(false);
            setError(errText(err));
          });
        }
      })();
    },
    [guard, refresh],
  );

  const handleEvict = useCallback(
    (id: string) => runAction(() => rpc.managedEvict(id)),
    [runAction, rpc],
  );
  const handleClear = useCallback(() => runAction(() => rpc.managedClear()), [runAction, rpc]);

  const pct =
    snapshot && snapshot.capBytes > 0
      ? Math.min(100, Math.round((snapshot.sizeBytes / snapshot.capBytes) * 100))
      : 0;

  return (
    <section className="managed-meter" aria-label="Managed copies">
      <h3 className="managed-meter__title">Managed copies</h3>
      <p className="managed-meter__lead">
        Keeping a copy stores the original bytes inside the app, so a video survives its source
        being moved or deleted. Copies count toward a capped store.
      </p>

      {error ? (
        <div className="managed-meter__error" role="alert">
          {error}
        </div>
      ) : null}

      {snapshot === null ? (
        error ? null : (
          <div className="managed-meter__loading" role="status" aria-busy="true">
            Loading managed copies…
          </div>
        )
      ) : (
        <>
          <div className="managed-meter__gauge">
            <div className="managed-meter__bar" role="presentation">
              <div className="managed-meter__fill" style={{ width: `${pct}%` }} />
            </div>
            <p className="managed-meter__readout">
              <span className="managed-meter__used">{formatBytes(snapshot.sizeBytes)}</span>
              {' used of '}
              <span className="managed-meter__cap">{formatBytes(snapshot.capBytes)}</span>
              {' cap · '}
              <span className="managed-meter__count">
                {snapshot.count === 1 ? '1 copy' : `${snapshot.count} copies`}
              </span>
            </p>
          </div>

          {snapshot.count === 0 ? (
            <p className="managed-meter__empty">
              No managed copies yet. Use “Keep a copy” on a video in the Library to add one.
            </p>
          ) : (
            <>
              <ul className="managed-meter__list">
                {snapshot.entries.map((entry) => (
                  <li key={entry.entityId} className="managed-meter__row" data-entity={entry.entityId}>
                    <span className="managed-meter__row-name" title={entry.originalPath}>
                      {baseName(entry.originalPath)}
                    </span>
                    <span className="managed-meter__row-size">{formatBytes(entry.sizeBytes)}</span>
                    {confirmEvict === entry.entityId ? (
                      <span className="managed-meter__confirm" role="group" aria-label="Confirm removing this copy">
                        <span className="managed-meter__confirm-q">Remove copy?</span>
                        <button
                          type="button"
                          className="managed-meter__btn managed-meter__btn--danger"
                          disabled={busy}
                          onClick={() => handleEvict(entry.entityId)}
                        >
                          Remove
                        </button>
                        <button
                          type="button"
                          className="managed-meter__btn"
                          disabled={busy}
                          onClick={() => setConfirmEvict(null)}
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="managed-meter__btn managed-meter__btn--evict"
                        aria-label={`Remove the managed copy of ${baseName(entry.originalPath)}`}
                        disabled={busy}
                        onClick={() => setConfirmEvict(entry.entityId)}
                      >
                        Remove
                      </button>
                    )}
                  </li>
                ))}
              </ul>

              <div className="managed-meter__actions">
                {confirmClear ? (
                  <span className="managed-meter__confirm" role="group" aria-label="Confirm clearing all copies">
                    <span className="managed-meter__confirm-q">
                      Remove all {snapshot.count} managed copies?
                    </span>
                    <button
                      type="button"
                      className="managed-meter__btn managed-meter__btn--danger"
                      disabled={busy}
                      onClick={handleClear}
                    >
                      Remove all
                    </button>
                    <button
                      type="button"
                      className="managed-meter__btn"
                      disabled={busy}
                      onClick={() => setConfirmClear(false)}
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="managed-meter__btn managed-meter__btn--clear"
                    disabled={busy}
                    onClick={() => setConfirmClear(true)}
                  >
                    Clear all managed copies
                  </button>
                )}
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

export default ManagedStoreMeter;
