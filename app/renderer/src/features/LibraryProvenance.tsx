import React, { useCallback, useEffect, useRef, useState } from 'react';

import type { RevealResult } from '../lib/rpc';
import { KeepCopyControl, type ManagedCopyHandlers } from './KeepCopyControl';
import './library-provenance.css';

// LibraryProvenance.tsx — WU-1f: per-card source PROVENANCE for the Library home.
//
// The user's pain: "I have 3 videos and I don't know where they are." Each card
// shows its SOURCE FILE clearly (full path, not a tiny truncated grey line), an
// "On disk / Missing" badge, a "Show in folder" action, and — when a source has
// moved away — a HASH-VERIFIED "Relink…" action (or a loud "relink unavailable"
// when no hash baseline was ever captured).
//
// It reuses the ALREADY-REGISTERED L5 RPCs (`library.reveal` / `library.pinHash`
// / `library.relink`) through injected handlers (no new machinery, unit-testable
// with plain fakes):
//   * On view it `reveal`s the source to learn on-disk state, then LAZILY pins the
//     whole-file hash of a still-present source (`pinHash`) so a later move stays
//     recoverable. The pin is fire-and-forget: the badge renders immediately; the
//     multi-GB hash runs sidecar-side and never blocks the card.
//   * A missing-but-pinned source offers "Relink…" — the sidecar re-points ONLY on
//     an exact whole-file BLAKE3 match, so a wrong file is rejected loudly.
//   * A missing source that was gone before any pin is "relink unavailable" — there
//     is no baseline to verify a re-imported copy against (never a silent guess).

/** The minimal asset shape the provenance row renders (id + by-path source). */
export interface ProvenanceVideo {
  id: string;
  path: string;
  title: string;
}

/**
 * The injected L5 handler slice (the app wires the rpc/bridge-backed
 * `lineageActions`). Every side effect is a handler so this component unit-tests
 * with plain fakes — no rpc/bridge import.
 */
export interface ProvenanceHandlers {
  /** `library.reveal {id}` — resolve the by-path source + its on-disk/relink state. */
  reveal(id: string): Promise<RevealResult>;
  /** `library.pinHash {id}` — pin the whole-file hash baseline of an on-disk source. */
  pinHash(id: string): Promise<unknown>;
  /** `library.relink {id, path}` — hash-verified re-point of a moved source. */
  relink(id: string, path: string): Promise<void>;
  /** Reveal a path in the OS file explorer (true on success). Optional -> degrades. */
  openInFolder?(path: string): Promise<boolean>;
  /** Pick the moved file when relinking (null when cancelled). Optional -> degrades. */
  pickRelinkTarget?(): Promise<string | null>;
  /**
   * WU-3b2: the OPT-IN keep-a-copy managed-store handlers (`library.managedStatus`
   * / `keepCopy` / `managedEvict`). When present, the card renders a per-video
   * keep-a-copy control (managed-status chip + keep/evict actions); absent -> the
   * control is not rendered (the app wires the real one).
   */
  managed?: ManagedCopyHandlers;
}

export interface LibraryProvenanceProps {
  /** The card's asset. */
  video: ProvenanceVideo;
  /** The injected L5 handlers. */
  handlers: ProvenanceHandlers;
}

type Phase =
  | { status: 'checking' }
  | { status: 'error'; message: string }
  | { status: 'unavailable' }
  | { status: 'ok'; exists: boolean; relinkable: boolean; sourcePath: string };

type ActionStatus = { kind: 'idle' } | { kind: 'info' | 'success' | 'error'; message: string };

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function LibraryProvenance({ video, handlers }: LibraryProvenanceProps): React.ReactElement {
  const [phase, setPhase] = useState<Phase>({ status: 'checking' });
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<ActionStatus>({ kind: 'idle' });

  // Guard async setState against a card that unmounted mid-flight (the list
  // re-renders/removes cards freely). One coverable branch instead of a `live`
  // flag re-checked at every await site.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const applyPhase = useCallback((next: Phase) => {
    if (mounted.current) setPhase(next);
  }, []);

  // On view: reveal the source, then lazily pin a still-present source's hash so a
  // later move stays recoverable (the back-fill for pre-WU-1f NULL content_hash).
  useEffect(() => {
    applyPhase({ status: 'checking' });
    void (async () => {
      let result: RevealResult;
      try {
        result = await handlers.reveal(video.id);
      } catch (err) {
        applyPhase({ status: 'error', message: errText(err) });
        return;
      }
      const src = result.sources[0];
      if (!src) {
        applyPhase({ status: 'unavailable' });
        return;
      }
      applyPhase({
        status: 'ok',
        exists: src.exists,
        relinkable: src.relinkable,
        sourcePath: src.path,
      });
      if (src.exists && !src.relinkable) {
        try {
          await handlers.pinHash(video.id);
          applyPhase({ status: 'ok', exists: true, relinkable: true, sourcePath: src.path });
        } catch {
          // Best-effort baseline: leave the source un-pinned. The truthful
          // "relink unavailable" state then applies only IF it later goes missing
          // before a successful re-view — never a masked failure.
        }
      }
    })();
  }, [applyPhase, handlers, video.id]);

  // Serialise user actions via `busy`; surface any throw LOUDLY (role="alert").
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

  const handleShowInFolder = useCallback(
    (path: string) => {
      void run(async () => {
        if (!handlers.openInFolder) {
          setStatus({ kind: 'info', message: 'Revealing files is not available in this build.' });
          return;
        }
        const ok = await handlers.openInFolder(path);
        setStatus(
          ok
            ? { kind: 'success', message: 'Opened the source location.' }
            : { kind: 'error', message: 'Could not reveal the source location.' },
        );
      });
    },
    [handlers, run],
  );

  const handleRelink = useCallback(() => {
    void run(async () => {
      if (!handlers.pickRelinkTarget) {
        setStatus({ kind: 'info', message: 'Relinking is not available in this build.' });
        return;
      }
      const chosen = await handlers.pickRelinkTarget();
      if (!chosen) {
        return; // cancelled — leave the existing status untouched
      }
      await handlers.relink(video.id, chosen);
      setPhase({ status: 'ok', exists: true, relinkable: true, sourcePath: chosen });
      setStatus({ kind: 'success', message: 'Relinked and verified the source file.' });
    });
  }, [handlers, run, video.id]);

  // Show the RESOLVED source path once known (so a successful relink surfaces the
  // new location immediately, before the list re-reads); the prop path until then.
  const displayPath = phase.status === 'ok' ? phase.sourcePath : video.path;

  return (
    <div className="library-provenance">
      <code className="library-provenance__path" title={displayPath}>
        {displayPath}
      </code>
      {phase.status === 'checking' ? (
        <span className="library-provenance__badge library-provenance__badge--checking">
          Checking…
        </span>
      ) : phase.status === 'error' ? (
        <p className="library-provenance__status library-provenance__status--error" role="alert">
          Could not check the source file: {phase.message}
        </p>
      ) : phase.status === 'unavailable' ? (
        <span className="library-provenance__badge library-provenance__badge--unknown">
          Source details unavailable
        </span>
      ) : (
        <div className="library-provenance__row">
          {phase.exists ? (
            <>
              <span className="library-provenance__badge library-provenance__badge--ondisk">
                On disk
              </span>
              <button
                type="button"
                className="library-provenance__btn"
                disabled={busy}
                onClick={() => handleShowInFolder(phase.sourcePath)}
              >
                Show in folder
              </button>
            </>
          ) : phase.relinkable ? (
            <>
              <span className="library-provenance__badge library-provenance__badge--missing">
                Missing
              </span>
              <button
                type="button"
                className="library-provenance__btn library-provenance__btn--relink"
                disabled={busy}
                onClick={handleRelink}
              >
                Relink…
              </button>
            </>
          ) : (
            <>
              <span className="library-provenance__badge library-provenance__badge--missing">
                Missing
              </span>
              <span className="library-provenance__note">
                Relink unavailable — the original was gone before it could be verified.
              </span>
            </>
          )}
        </div>
      )}
      {status.kind === 'idle' ? null : (
        <p
          className={`library-provenance__status library-provenance__status--${status.kind}`}
          role={status.kind === 'error' ? 'alert' : 'status'}
        >
          {status.message}
        </p>
      )}
      {/* WU-3b2: the OPT-IN keep-a-copy control. Only once the source state is
          resolved (`ok`) do we know whether keeping a copy is possible — the
          managed-store snapshot then reports this video's managed/linked state. */}
      {phase.status === 'ok' && handlers.managed ? (
        <KeepCopyControl
          videoId={video.id}
          sourceExists={phase.exists}
          handlers={handlers.managed}
        />
      ) : null}
    </div>
  );
}

export default LibraryProvenance;
