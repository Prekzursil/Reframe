import React, { useCallback, useEffect, useRef, useState } from 'react';

import type { ManagedCopy, ManagedStatus } from '../lib/rpc';
import './keep-copy-control.css';

// KeepCopyControl.tsx — WU-3b2: the per-video OPT-IN "Keep a copy" control that
// rides inside <LibraryProvenance>.
//
// The user's durability pain: the library references its videos BY PATH, so a
// source that is moved/renamed/deleted breaks playback. WU-3b1 added an opt-in
// managed byte-copy store (copy the original bytes into the app, make the copy
// AUTHORITATIVE, record the original path as provenance). This control surfaces
// that store per card:
//   * It reads the whole-store snapshot on view (`managed.status`) to learn
//     whether THIS video already has a managed copy, then shows the honest
//     resulting state — "Managed copy" vs "Linked (original only)".
//   * A "Keep a copy" action (only offered when the source is on disk — you can't
//     copy a file that is gone) calls `managed.keep`, showing progress and, on
//     failure, the LOUD sidecar reason (store-full / copy-failed) as a role=alert.
//   * A managed copy can be evicted back to its original via a two-step in-place
//     CONFIRM (never a silent one-click destructive action).
//
// Every side effect is an injected handler so the component unit-tests with plain
// fakes (no rpc/bridge import), mirroring the WU-1f <LibraryProvenance> contract.

/** The injected managed-store handler slice (wired to `library.managedStatus/keepCopy/managedEvict`). */
export interface ManagedCopyHandlers {
  /** `library.managedStatus` — the whole-store snapshot (used to learn this video's state). */
  status(): Promise<ManagedStatus>;
  /** `library.keepCopy {id}` — copy the source into the store; resolves with the managed row. */
  keep(id: string): Promise<ManagedCopy>;
  /** `library.managedEvict {id}` — evict this video's managed copy back to its original. */
  evict(id: string): Promise<void>;
}

export interface KeepCopyControlProps {
  /** The library entity id this control keeps/evicts a copy for. */
  videoId: string;
  /**
   * Whether the source file is currently on disk. Keeping a copy is only offered
   * when true — you cannot copy a source that is missing (that is a relink job).
   */
  sourceExists: boolean;
  /** The injected managed-store handlers. */
  handlers: ManagedCopyHandlers;
}

type ActionStatus = { kind: 'idle' } | { kind: 'info' | 'success' | 'error'; message: string };

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function KeepCopyControl({
  videoId,
  sourceExists,
  handlers,
}: KeepCopyControlProps): React.ReactElement {
  // `undefined` = the store snapshot is still loading; `null` = not managed;
  // a `ManagedCopy` = this video has a managed copy.
  const [managed, setManaged] = useState<ManagedCopy | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [status, setStatus] = useState<ActionStatus>({ kind: 'idle' });

  // Guard async setState against a card that unmounted mid-flight (the library
  // list re-renders/removes cards freely). One coverable branch, funnelled
  // through `guard`, instead of a `live` flag re-checked at every await site.
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

  // On view: read the whole-store snapshot and learn whether THIS video is managed.
  useEffect(() => {
    void (async () => {
      try {
        const snap = await handlers.status();
        const entry = snap.entries.find((e) => e.entityId === videoId) ?? null;
        guard(() => setManaged(entry));
      } catch (err) {
        // A store read failure is surfaced LOUDLY (never a silent "not managed"),
        // and we fall back to the not-managed view so the opt-in is still offered.
        guard(() => {
          setManaged(null);
          setStatus({
            kind: 'error',
            message: `Could not read the managed-copy store: ${errText(err)}`,
          });
        });
      }
    })();
  }, [guard, handlers, videoId]);

  const handleKeep = useCallback(() => {
    setBusy(true);
    setStatus({ kind: 'info', message: 'Keeping a copy…' });
    void (async () => {
      try {
        const row = await handlers.keep(videoId);
        guard(() => {
          setManaged(row);
          setBusy(false);
          setStatus({
            kind: 'success',
            message: 'Kept a managed copy — this now survives the original being moved or deleted.',
          });
        });
      } catch (err) {
        guard(() => {
          setBusy(false);
          setStatus({ kind: 'error', message: `Could not keep a copy: ${errText(err)}` });
        });
      }
    })();
  }, [guard, handlers, videoId]);

  const handleEvict = useCallback(() => {
    setBusy(true);
    setConfirming(false);
    void (async () => {
      try {
        await handlers.evict(videoId);
        guard(() => {
          setManaged(null);
          setBusy(false);
          setStatus({
            kind: 'success',
            message: 'Removed the managed copy; the library now links the original only.',
          });
        });
      } catch (err) {
        guard(() => {
          setBusy(false);
          setStatus({
            kind: 'error',
            message: `Could not remove the managed copy: ${errText(err)}`,
          });
        });
      }
    })();
  }, [guard, handlers, videoId]);

  return (
    <div className="keep-copy">
      {managed === undefined ? (
        <p className="keep-copy__loading">Checking managed copy…</p>
      ) : managed ? (
        <div className="keep-copy__row">
          <span className="keep-copy__badge keep-copy__badge--managed">Managed copy</span>
          <p className="keep-copy__note">
            A copy is kept, so this survives the original being moved or deleted.
          </p>
          {confirming ? (
            <div
              className="keep-copy__confirm"
              role="group"
              aria-label="Confirm removing the managed copy"
            >
              <span className="keep-copy__confirm-q">Remove the managed copy?</span>
              <button
                type="button"
                className="keep-copy__btn keep-copy__btn--danger"
                disabled={busy}
                onClick={handleEvict}
              >
                Remove
              </button>
              <button
                type="button"
                className="keep-copy__btn"
                disabled={busy}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="keep-copy__btn keep-copy__btn--evict"
              disabled={busy}
              onClick={() => setConfirming(true)}
            >
              Remove managed copy
            </button>
          )}
        </div>
      ) : (
        <div className="keep-copy__row">
          <span className="keep-copy__badge keep-copy__badge--linked">Linked (original only)</span>
          {sourceExists ? (
            <>
              <p className="keep-copy__note">
                Only the original file is referenced — if it moves or is deleted, this video breaks.
              </p>
              <button
                type="button"
                className="keep-copy__btn keep-copy__btn--keep"
                disabled={busy}
                onClick={handleKeep}
              >
                Keep a copy
              </button>
            </>
          ) : (
            <p className="keep-copy__note keep-copy__note--warn">
              Keep a copy is unavailable while the source file is missing — relink it first.
            </p>
          )}
        </div>
      )}
      {status.kind === 'idle' ? null : (
        <p
          className={`keep-copy__status keep-copy__status--${status.kind}`}
          role={status.kind === 'error' ? 'alert' : 'status'}
        >
          {status.message}
        </p>
      )}
    </div>
  );
}

export default KeepCopyControl;
