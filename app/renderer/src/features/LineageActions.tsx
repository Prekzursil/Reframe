import React, { useCallback, useState } from 'react';

import type { RegenerateResult, RevealResult } from '../lib/rpc';

// LineageActions.tsx — L5 asset-detail actions (DESIGN §3.4 + GATE L5).
//
// The "Reveal source" / "Regenerate" buttons the L4 card deliberately did NOT
// stub. Every side-effect is an INJECTED handler (no rpc/bridge import), so this
// component unit-tests with plain fakes:
//   * Reveal source -> resolve the by-path source and open it in the OS file
//     explorer. A MISSING source is surfaced LOUDLY (role="alert") and reveals a
//     "Relink…" affordance — never silently skipped.
//   * Regenerate -> replay the producing op against the still-by-path source;
//     refuses (loud) when the source is gone, offering the relink first.
//   * Relink… -> pick the moved file; the sidecar re-points ONLY on a whole-file
//     BLAKE3 match, so a wrong/mismatched file is rejected loudly.
//
// No jargon ("provenance"/"PROV" never shown, §3.5): copy is "source" / "history".

export interface LineageAssetRef {
  /** The asset id the actions operate on. */
  id: string;
  /** Its human title (for accessible button names). */
  title: string;
}

/** The injected L5 action slice (the renderer wires the rpc/bridge-backed one). */
export interface LineageActionHandlers {
  /** `library.reveal {id}` — resolve the by-path source file(s). */
  reveal(id: string): Promise<RevealResult>;
  /** `library.regenerate {id}` — the replay descriptor (op + params). */
  regenerate(id: string): Promise<RegenerateResult>;
  /** Re-run the producing op the descriptor names (the renderer re-dispatches it). */
  runRegenerate(descriptor: RegenerateResult): Promise<void>;
  /** `library.relink {id, path}` — hash-verified re-point of a moved source. */
  relink(id: string, path: string): Promise<void>;
  /** Reveal a path in the OS file explorer (true on success). Optional -> degrades. */
  openInFolder?(path: string): Promise<boolean>;
  /** Pick the moved file when relinking (null when cancelled). Optional -> degrades. */
  pickRelinkTarget?(): Promise<string | null>;
}

export interface LineageActionsProps {
  /** The asset the actions operate on. */
  asset: LineageAssetRef;
  /** The injected action handlers. */
  actions: LineageActionHandlers;
}

type Status = { kind: 'idle' } | { kind: 'info' | 'success' | 'error'; message: string };

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function LineageActions({ asset, actions }: LineageActionsProps): React.ReactElement {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  // The source paths a reveal/regenerate found missing on disk — drives the
  // "Relink…" affordance. Empty = no relink offered.
  const [missing, setMissing] = useState<string[]>([]);

  // Shared run wrapper: serialise via `busy`, surface any throw LOUDLY.
  const run = useCallback(async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      setStatus({ kind: 'error', message: errText(err) });
    } finally {
      setBusy(false);
    }
  }, []);

  const handleReveal = useCallback(() => {
    void run(async () => {
      const res = await actions.reveal(asset.id);
      if (res.sources.length === 0) {
        setMissing([]);
        setStatus({ kind: 'info', message: 'This item has no source file on record.' });
        return;
      }
      if (res.missing.length > 0) {
        setMissing(res.missing);
        setStatus({ kind: 'error', message: `Source file is missing: ${res.missing.join(', ')}` });
        return;
      }
      setMissing([]);
      if (!actions.openInFolder) {
        setStatus({ kind: 'info', message: 'Revealing files is not available in this build.' });
        return;
      }
      const ok = await actions.openInFolder(res.sources[0].path);
      setStatus(
        ok
          ? { kind: 'success', message: 'Opened the source location.' }
          : { kind: 'error', message: 'Could not reveal the source location.' },
      );
    });
  }, [actions, asset.id, run]);

  const handleRegenerate = useCallback(() => {
    void run(async () => {
      const res = await actions.regenerate(asset.id);
      if (!res.ready) {
        setMissing(res.missing);
        setStatus({
          kind: 'error',
          message: `Can't regenerate — source file is missing: ${res.missing.join(', ')}`,
        });
        return;
      }
      setMissing([]);
      await actions.runRegenerate(res);
      setStatus({ kind: 'success', message: 'Regenerating from the original source…' });
    });
  }, [actions, asset.id, run]);

  const handleRelink = useCallback(() => {
    void run(async () => {
      if (!actions.pickRelinkTarget) {
        setStatus({ kind: 'info', message: 'Relinking is not available in this build.' });
        return;
      }
      const chosen = await actions.pickRelinkTarget();
      if (!chosen) {
        return; // cancelled — leave the existing status untouched
      }
      await actions.relink(asset.id, chosen);
      setMissing([]);
      setStatus({ kind: 'success', message: 'Relinked and verified the source file.' });
    });
  }, [actions, asset.id, run]);

  return (
    <div className="lineage-actions">
      <div className="lineage-actions__buttons">
        <button
          type="button"
          className="lineage-actions__btn"
          disabled={busy}
          onClick={handleReveal}
        >
          Reveal source
        </button>
        <button
          type="button"
          className="lineage-actions__btn"
          disabled={busy}
          onClick={handleRegenerate}
        >
          Regenerate
        </button>
        {missing.length > 0 ? (
          <button
            type="button"
            className="lineage-actions__btn lineage-actions__btn--relink"
            disabled={busy}
            onClick={handleRelink}
          >
            Relink…
          </button>
        ) : null}
      </div>
      {status.kind === 'idle' ? null : (
        <p
          className={`lineage-actions__status lineage-actions__status--${status.kind}`}
          role={status.kind === 'error' ? 'alert' : 'status'}
        >
          {status.message}
        </p>
      )}
    </div>
  );
}

export default LineageActions;
