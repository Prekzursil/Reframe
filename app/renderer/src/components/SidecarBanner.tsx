// SidecarBanner.tsx — self-healing "Restart sidecar" surface.
//
// When the supervisor gives up auto-restarting the Python sidecar it pushes
// `sidecar.status` = 'down'. Instead of leaving the app dead with only a toast
// ("sidecar is not running") and no recovery, we show a NON-BLOCKING banner with
// a [Restart] action wired to window.api.restartSidecar() (which resets the
// crash-budget window and respawns). While a restart is in flight we show
// "Restarting…"; the banner clears once the supervisor reports 'running'.
//
// Bridge access is structural (the renderer never imports the preload module),
// so the banner degrades to inert when the bridge is absent (tests/early boot).
import React, { useCallback, useEffect, useState } from 'react';

/** Mirror of sidecar.ts SidecarState / preload SidecarStatus. */
export type SidecarStatus = 'running' | 'restarting' | 'down';

/** Mirror of preload MediaApi RepairSetupResult (WU A5). */
export interface RepairSetupResult {
  /** true when the re-run bootstrap fully provisioned the core runtime. */
  ok: boolean;
  /**
   * Human-readable reason when `ok` is false — surfaced in the banner. Absent
   * when the loud failure arrives separately via the bootstrap-error channel.
   */
  reason?: string;
}

interface SidecarBridge {
  restartSidecar?: () => Promise<{ ok: boolean }>;
  onSidecarStatus?: (cb: (status: SidecarStatus) => void) => () => void;
  /**
   * First-run setup failure relay (WU-1 FAIL-LOUD). The main process forwards
   * bootstrap.py's terminal `FAILED:bootstrap …` line — an ACTIONABLE message
   * (what failed + where + how to fix) — so a broken first run is never a silent
   * empty app. Returns an unsubscribe fn.
   */
  onBootstrapError?: (cb: (message: string) => void) => () => void;
  /**
   * WU A5: re-run the idempotent first-run bootstrap on demand ("Retry setup /
   * Repair"). Lets a user whose first run partially failed recover WITHOUT
   * waiting for the next launch. Resolves `{ ok }` — true once the core runtime
   * is provisioned and the sidecar (re)started; false (with an optional reason)
   * on a failed or already-running attempt.
   */
  repairSetup?: () => Promise<RepairSetupResult>;
}

/** Read the preload-injected bridge without a global Window augmentation. */
function bridge(): SidecarBridge | null {
  return (globalThis as { window?: { api?: SidecarBridge } }).window?.api ?? null;
}

/**
 * Renders nothing while the sidecar is healthy. On 'down' it shows the recovery
 * banner; clicking [Restart] flips to a "Restarting…" state and invokes
 * restartSidecar(). A failed restart ({ok:false}) re-offers the button so the
 * user can try again (A6.3: never swallow the failure).
 */
export function SidecarBanner(): React.ReactElement | null {
  // 'running' is the optimistic default: absent any 'down' event the app is fine.
  const [status, setStatus] = useState<SidecarStatus>('running');
  const [busy, setBusy] = useState(false);
  // First-run setup failure message (WU-1). null = no failure; a non-empty
  // string is the actionable error to surface (takes precedence over status).
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  // WU A5: true while a re-run bootstrap ("Retry setup") is in flight, so the
  // banner shows progress instead of re-offering the button.
  const [repairing, setRepairing] = useState(false);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.onSidecarStatus !== 'function') return;
    const unsubscribe = api.onSidecarStatus((next) => {
      setStatus(next);
      // Any supervisor-driven transition clears our local "busy" optimism: a
      // fresh 'running'/'down'/'restarting' from main is authoritative.
      setBusy(false);
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.onBootstrapError !== 'function') return;
    return api.onBootstrapError((message) => setBootstrapError(message ? message : null));
  }, []);

  const onRestart = useCallback(() => {
    const api = bridge();
    if (!api || typeof api.restartSidecar !== 'function') return;
    setBusy(true);
    api
      .restartSidecar()
      .then((result) => {
        // ok:true -> wait for the 'running' status push to clear the banner;
        // keep the optimistic "Restarting…" until then. ok:false -> re-offer.
        if (!result || result.ok !== true) setBusy(false);
      })
      .catch(() => {
        // Surface the failure by re-enabling the button (don't swallow).
        setBusy(false);
      });
  }, []);

  const onRepair = useCallback(() => {
    const api = bridge();
    if (!api || typeof api.repairSetup !== 'function') return;
    setRepairing(true);
    api
      .repairSetup()
      .then((result) => {
        setRepairing(false);
        if (result.ok === true) {
          // Success: clear the actionable error so the banner falls back to the
          // (now-healthy) sidecar status stream.
          setBootstrapError(null);
        } else if (result.reason) {
          // Loud failure with a fresh reason — replace the message; the button
          // returns for another attempt.
          setBootstrapError(result.reason);
        }
        // A reason-less failure keeps the prior actionable message (the
        // bootstrap-error channel may push a fresh one) and re-offers the button.
      })
      .catch(() => {
        // Never swallow: re-offer Retry by dropping the in-flight state.
        setRepairing(false);
      });
  }, []);

  // First-run setup failure wins: it means there is no sidecar to restart. We
  // show the ACTIONABLE message plus a "Retry setup" button that re-runs the
  // idempotent bootstrap on demand (WU A5) — so a half-failed first run is
  // recoverable in place, without waiting for the next launch.
  if (bootstrapError !== null) {
    return (
      <div className="sidecar-banner sidecar-banner--error" role="alert" aria-live="assertive">
        <span className="sidecar-banner__message">{bootstrapError}</span>
        {repairing ? (
          <span className="sidecar-banner__repairing">Retrying setup…</span>
        ) : (
          <button
            type="button"
            className="sidecar-banner__repair"
            data-action="repair"
            onClick={onRepair}
          >
            Retry setup
          </button>
        )}
      </div>
    );
  }

  if (status === 'running') return null;

  const restarting = busy || status === 'restarting';

  return (
    <div className="sidecar-banner" role="alert" aria-live="assertive">
      <span className="sidecar-banner__message">
        {restarting ? 'Restarting sidecar…' : 'Sidecar stopped'}
      </span>
      {restarting ? null : (
        <button type="button" className="sidecar-banner__action" onClick={onRestart}>
          Restart
        </button>
      )}
    </div>
  );
}

export default SidecarBanner;
