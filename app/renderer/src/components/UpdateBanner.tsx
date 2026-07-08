// UpdateBanner.tsx — WU-U: the non-intrusive IN-PLACE AUTO-UPDATE surface.
//
// The main process (electron-updater) auto-checks GitHub Releases on launch and
// pushes an `update.status` stream. This banner — mirroring SidecarBanner's
// top-pinned, dismissible, non-blocking shape — surfaces only the ACTIONABLE
// states:
//   * available   -> "Update vX available"  + [Download]      (user confirms;
//                     autoDownload is OFF so nothing downloads unprompted),
//   * progress     -> "Downloading N%…"       (live, no button),
//   * downloaded  -> "Update vX is ready"     + [Restart to update]
//                     (quitAndInstall runs the NSIS in-place upgrade, which
//                     PRESERVES userData: the DPAPI keystore + settings + data root),
//   * error        -> shown ONLY after the user engaged (clicked Download), so a
//                     launch-time offline/no-release check degrades QUIETLY.
// 'checking' and 'none' render nothing (silent auto-check).
//
// UNSIGNED BUILD: the app has no code-signing certificate, so Windows SmartScreen
// may warn when the downloaded installer runs during the restart. That is
// expected — we deliberately do not add signing.
//
// Bridge access is structural (the renderer never imports the preload module), so
// the banner degrades to inert when the bridge is absent (tests / dev / early
// boot) — it simply renders nothing.
import React, { useCallback, useEffect, useState } from 'react';

/** Mirror of updater.ts UpdateStatus / preload UpdateStatus. */
export type UpdateStatus =
  | { state: 'checking' }
  | { state: 'available'; version: string }
  | { state: 'none' }
  | { state: 'progress'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string };

/** Mirror of preload UpdateActionResult. */
export interface UpdateActionResult {
  ok: boolean;
  reason?: string;
}

interface UpdateBridge {
  /** Subscribe to the `update.status` lifecycle stream. Returns an unsubscribe fn. */
  onUpdateStatus?: (cb: (status: UpdateStatus) => void) => () => void;
  /** Start downloading the available update (user-confirmed). */
  downloadUpdate?: () => Promise<UpdateActionResult>;
  /** Quit + run the NSIS in-place upgrade for a downloaded update. */
  quitAndInstall?: () => Promise<UpdateActionResult>;
}

/** Read the preload-injected bridge without a global Window augmentation. */
function bridge(): UpdateBridge | null {
  return (globalThis as { window?: { api?: UpdateBridge } }).window?.api ?? null;
}

/** The "Update available" label (guards an empty version from the feed). */
export function availableLabel(version: string): string {
  return version ? `Update v${version} available` : 'An update is available';
}

/** The "downloaded / ready" label (guards an empty version from the feed). */
export function readyLabel(version: string): string {
  return version ? `Update v${version} is ready to install` : 'The update is ready to install';
}

/**
 * Renders nothing while there is nothing to act on (idle / checking / no update /
 * a suppressed launch-time error / a dismissed state). Otherwise shows the
 * matching non-blocking banner. Every async action re-offers its button on
 * failure (A6.3: never swallow), and the dismiss (X) hides the CURRENT state
 * until a new lifecycle state arrives.
 */
export function UpdateBanner(): React.ReactElement | null {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  // True once the user actively engaged (clicked Download). Gates the error
  // banner so a silent launch auto-check that fails offline stays invisible.
  const [engaged, setEngaged] = useState(false);
  // Optimistic in-flight flag for the Download / Restart actions.
  const [busy, setBusy] = useState(false);
  // The state value the user dismissed; a DIFFERENT incoming state re-shows.
  const [dismissedState, setDismissedState] = useState<string | null>(null);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.onUpdateStatus !== 'function') return;
    return api.onUpdateStatus((next) => {
      setStatus(next);
      // Any authoritative push clears the optimistic busy flag (e.g. the first
      // download-progress tick supersedes the "Starting download…" note).
      setBusy(false);
    });
  }, []);

  const onDownload = useCallback(() => {
    const api = bridge();
    if (!api || typeof api.downloadUpdate !== 'function') return;
    setEngaged(true);
    setBusy(true);
    api
      .downloadUpdate()
      .then((result) => {
        // ok:true -> wait for the progress stream to render; ok:false -> re-offer.
        if (!result || result.ok !== true) setBusy(false);
      })
      .catch(() => setBusy(false));
  }, []);

  const onInstall = useCallback(() => {
    const api = bridge();
    if (!api || typeof api.quitAndInstall !== 'function') return;
    setBusy(true);
    api
      .quitAndInstall()
      .then((result) => {
        // Normally the app quits before this resolves; a non-ok result re-offers.
        if (!result || result.ok !== true) setBusy(false);
      })
      .catch(() => setBusy(false));
  }, []);

  if (status === null) return null;
  // A dismissed state stays hidden until a DIFFERENT lifecycle state arrives.
  if (status.state === dismissedState) return null;

  // `status` is narrowed to non-null here, so the dismissed marker is the exact
  // current state value (no defensive fallback branch needed).
  const currentState = status.state;
  const dismiss = (
    <button
      type="button"
      className="update-banner__dismiss"
      aria-label="Dismiss"
      data-action="dismiss"
      onClick={() => setDismissedState(currentState)}
    >
      ×
    </button>
  );

  switch (status.state) {
    case 'available':
      return (
        <div className="update-banner" role="status" aria-live="polite">
          <span className="update-banner__message">{availableLabel(status.version)}</span>
          {busy ? (
            <span className="update-banner__note">Starting download…</span>
          ) : (
            <button
              type="button"
              className="update-banner__action"
              data-action="download"
              onClick={onDownload}
            >
              Download
            </button>
          )}
          {dismiss}
        </div>
      );
    case 'progress':
      return (
        <div className="update-banner" role="status" aria-live="polite">
          <span className="update-banner__message">Downloading {status.percent}%…</span>
          {dismiss}
        </div>
      );
    case 'downloaded':
      return (
        <div className="update-banner update-banner--ready" role="status" aria-live="polite">
          <span className="update-banner__message">{readyLabel(status.version)}</span>
          {busy ? (
            <span className="update-banner__note">Restarting…</span>
          ) : (
            <button
              type="button"
              className="update-banner__action"
              data-action="install"
              onClick={onInstall}
            >
              Restart to update
            </button>
          )}
          {dismiss}
        </div>
      );
    case 'error':
      // Degrade quietly: a failure from the silent launch auto-check (before the
      // user engaged) is never surfaced — only a user-initiated failure shows.
      if (!engaged) return null;
      return (
        <div className="update-banner update-banner--error" role="alert" aria-live="assertive">
          <span className="update-banner__message">Update failed: {status.message}</span>
          {dismiss}
        </div>
      );
    // 'checking' and 'none' are silent (the auto-check must not nag).
    default:
      return null;
  }
}

export default UpdateBanner;
