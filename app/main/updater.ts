// updater.ts — main-process IN-PLACE AUTO-UPDATE wiring (WU-U) + AUTHENTICITY gate (WU-U2).
//
// Reframe ships as an NSIS installer + portable zip; electron-updater lets a
// running, PACKAGED copy notice a newer GitHub release, download it (user-confirmed),
// and quitAndInstall() the NSIS in-place upgrade — which PRESERVES userData (the
// DPAPI keystore `secure-keys.json` + settings + the relocatable data root).
//
// AUTHENTICITY (WU-U2): the app is UNSIGNED (no Authenticode/EV cert), and
// electron-updater only proves INTEGRITY (the sha512 block-map in `latest.yml`) — NOT
// authenticity. A party controlling the update feed could serve a malicious
// `latest.yml` + installer and it would apply. This module closes that P0 by gating
// BOTH the "downloaded -> ready" transition AND quitAndInstall() on an Ed25519
// signature check ({@link ./updateVerify}): an update is applied ONLY when a detached
// `.sig` over `version‖sha512(installer)` verifies against the embedded public key. A
// compromised feed cannot forge that signature without the OFFLINE private key. The
// install path RE-verifies immediately before quitAndInstall (closing the TOCTOU
// window where the on-disk file could be swapped after the download-time check), and
// `autoInstallOnAppQuit` is forced OFF so electron-updater cannot silently install a
// downloaded update on quit WITHOUT crossing this gate.
//
// DECISIONS (user-chosen): GitHub feed + auto-check-on-launch, `autoDownload` OFF
// (the user confirms in the renderer's UpdateBanner before any bytes download).
//
// TESTABILITY: the real `autoUpdater` singleton and the verifier are INJECTED,
// mirroring keystore.ts / repairSetupIpc.ts. main.ts casts the real singleton to
// {@link AutoUpdaterLike}, binds the verifier to updateVerify.verifyDownloadedUpdate,
// and provides the broadcast; tests pass fakes so the whole event -> verify -> IPC
// state machine is exercised without electron-updater or a packaged app. `ipcMain`
// is mocked in tests.
import { ipcMain } from 'electron';
import type { UpdateVerifyResult } from './updateVerify';

/** main -> renderer: the current update lifecycle status (fan-out per window). */
export const UPDATE_STATUS_CHANNEL = 'update.status';
/** renderer -> main: trigger a GitHub check (also fired once on launch). */
export const UPDATE_CHECK_CHANNEL = 'update.check';
/** renderer -> main: start downloading the available update (user-confirmed). */
export const UPDATE_DOWNLOAD_CHANNEL = 'update.download';
/** renderer -> main: quit + run the NSIS in-place upgrade for a ready update. */
export const UPDATE_INSTALL_CHANNEL = 'update.quitAndInstall';

/**
 * The update lifecycle, as a discriminated union pushed on {@link
 * UPDATE_STATUS_CHANNEL}. Each `autoUpdater` event maps to exactly one variant so
 * the renderer's UpdateBanner can render `checking`/`available`/`progress`/
 * `downloaded`/`error`/`none` without any main-process knowledge. A FAILED
 * authenticity check reuses the `error` variant (message `Update rejected: …`) — the
 * renderer surface stays unchanged.
 */
export type UpdateStatus =
  | { state: 'checking' }
  | { state: 'available'; version: string }
  | { state: 'none' }
  | { state: 'progress'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string };

/** Subset of electron-updater's `UpdateInfo`/`UpdateDownloadedEvent` this module reads. */
export interface UpdateInfoLike {
  version?: string;
  /** Present on `update-downloaded` (`UpdateDownloadedEvent`): the local installer path. */
  downloadedFile?: string;
}

/** Subset of electron-updater's `ProgressInfo` this module reads. */
export interface ProgressInfoLike {
  percent?: number;
}

/** A downloaded update awaiting (or having passed) the authenticity gate. */
export interface DownloadedUpdate {
  version: string;
  downloadedFile: string;
}

/**
 * The minimal `autoUpdater` surface this module drives. main.ts casts the real
 * electron-updater singleton to this (`as unknown as AutoUpdaterLike`), the SAME
 * structural-cast seam used for `safeStorage`/`SafeStorageLike` — so this module
 * never imports electron-updater and tests can supply a fake.
 */
export interface AutoUpdaterLike {
  /** OFF: the user confirms the download in the renderer before it starts. */
  autoDownload: boolean;
  /**
   * OFF: electron-updater's default is TRUE, which auto-installs a downloaded update
   * on app quit via its own quit handler — WITHOUT crossing this module's IPC/verify
   * gate. Forcing it false closes that silent auto-install-on-quit bypass.
   */
  autoInstallOnAppQuit: boolean;
  on(event: string, listener: (...args: never[]) => void): unknown;
  checkForUpdates(): Promise<unknown>;
  downloadUpdate(): Promise<unknown>;
  quitAndInstall(): void;
}

/** Outcome of a renderer-triggered check/download/install (never throws to the caller). */
export interface UpdateActionResult {
  ok: boolean;
  reason?: string;
}

/** Wiring main.ts injects (keeps this module free of Electron window/IO/crypto). */
export interface UpdaterDeps {
  /** The electron-updater singleton (cast) — injected for testability. */
  autoUpdater: AutoUpdaterLike;
  /** Fan-out a status to every live renderer (main.ts owns the window set). */
  broadcast: (status: UpdateStatus) => void;
  /**
   * Verify a downloaded update's AUTHENTICITY (Ed25519 signature over
   * `version‖sha512`). main.ts binds this to updateVerify.verifyDownloadedUpdate with
   * the file-read + signature-fetch transport + the running app version. Injected so
   * tests exercise the gate with a fake and this module stays crypto/Electron-free.
   */
  verifyUpdate: (candidate: DownloadedUpdate) => Promise<UpdateVerifyResult>;
  /** Optional main-process logger for the diagnostic breadcrumb. Default: no-op. */
  log?: (message: string) => void;
}

/** Handle returned by {@link registerUpdater}. */
export interface UpdaterHandle {
  /** Remove the ipc handlers (called from main.ts will-quit). */
  dispose: () => void;
  /**
   * Trigger a check now (main.ts fires this once on launch). Resolves — never
   * rejects — so a launch-time failure (offline, no release yet) degrades
   * quietly instead of crashing the app.
   */
  checkForUpdates: () => Promise<UpdateActionResult>;
}

/** Extract a human-readable message from an unknown thrown value. */
function errText(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === 'string' && err !== '') return err;
  return 'update failed';
}

/** Clamp/round a raw download-progress percent to an integer 0..100. */
export function toPercent(percent: number | undefined): number {
  const n = typeof percent === 'number' && Number.isFinite(percent) ? percent : 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

/**
 * Wire `autoUpdater`'s events to {@link UPDATE_STATUS_CHANNEL} broadcasts and
 * register the three renderer-facing ipc handlers (check/download/quitAndInstall).
 *
 * Every event maps to one {@link UpdateStatus} variant; every action is wrapped so a
 * rejection becomes a loud-but-safe `{ ok:false }` + an `error` status rather than an
 * unhandled rejection. `autoDownload` is forced OFF so nothing downloads until the
 * user confirms; `autoInstallOnAppQuit` is forced OFF so nothing installs without
 * crossing the authenticity gate. A downloaded update is only announced as `ready`
 * once its Ed25519 signature verifies, and quitAndInstall is refused (and re-verified)
 * unless that check passed.
 */
export function registerUpdater(deps: UpdaterDeps): UpdaterHandle {
  const { autoUpdater, broadcast, verifyUpdate } = deps;
  const log = deps.log ?? ((): void => {});

  // The user confirms the download in the UpdateBanner (autoDownload OFF); nothing
  // auto-installs on quit outside the verify gate (autoInstallOnAppQuit OFF).
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;

  // Authenticity latch: a downloaded update is only installable once its signature
  // verifies. `pending` is the last downloaded candidate (null until one arrives);
  // `verified` gates the install and is reset on every fresh download.
  let pending: DownloadedUpdate | null = null;
  let verified = false;

  const rejectUpdate = (reason: string): void => {
    log(`[updater] update rejected: ${reason}`);
    broadcast({ state: 'error', message: `Update rejected: ${reason}` });
  };

  /** Verify a freshly downloaded update; announce `ready` only on success. */
  const verifyForDownload = async (candidate: DownloadedUpdate): Promise<void> => {
    const result = await verifyUpdate(candidate);
    if (result.ok) {
      verified = true;
      broadcast({ state: 'downloaded', version: candidate.version });
    } else {
      verified = false;
      rejectUpdate(result.reason);
    }
  };

  autoUpdater.on('checking-for-update', () => broadcast({ state: 'checking' }));
  autoUpdater.on('update-available', (info: UpdateInfoLike) =>
    broadcast({ state: 'available', version: info?.version ?? '' }),
  );
  autoUpdater.on('update-not-available', () => broadcast({ state: 'none' }));
  autoUpdater.on('download-progress', (progress: ProgressInfoLike) =>
    broadcast({ state: 'progress', percent: toPercent(progress?.percent) }),
  );
  autoUpdater.on('update-downloaded', (info: UpdateInfoLike) => {
    // AUTHENTICITY GATE: do NOT announce `downloaded`/ready until the signature
    // verifies. Latch a fresh unverified candidate, then verify asynchronously.
    const candidate: DownloadedUpdate = {
      version: info?.version ?? '',
      downloadedFile: info?.downloadedFile ?? '',
    };
    pending = candidate;
    verified = false;
    void verifyForDownload(candidate);
  });
  autoUpdater.on('error', (err: Error) => {
    const message = errText(err);
    log(`[updater] error: ${message}`);
    broadcast({ state: 'error', message });
  });

  const checkForUpdates = async (): Promise<UpdateActionResult> => {
    try {
      await autoUpdater.checkForUpdates();
      return { ok: true };
    } catch (err) {
      const message = errText(err);
      // Degrade quietly on launch (offline / no release yet): log + emit an error
      // status the renderer suppresses unless the user was actively engaged.
      log(`[updater] check failed: ${message}`);
      broadcast({ state: 'error', message });
      return { ok: false, reason: message };
    }
  };

  const downloadUpdate = async (): Promise<UpdateActionResult> => {
    try {
      await autoUpdater.downloadUpdate();
      return { ok: true };
    } catch (err) {
      const message = errText(err);
      log(`[updater] download failed: ${message}`);
      broadcast({ state: 'error', message });
      return { ok: false, reason: message };
    }
  };

  const refuseInstall = (reason: string): UpdateActionResult => {
    rejectUpdate(reason);
    return { ok: false, reason };
  };

  const quitAndInstall = async (): Promise<UpdateActionResult> => {
    if (pending === null) {
      return refuseInstall('no update has been downloaded');
    }
    if (!verified) {
      return refuseInstall('update failed verification');
    }
    // TOCTOU: re-verify the on-disk installer immediately before install — its bytes
    // could have been swapped between the download-time check and now.
    const recheck = await verifyUpdate(pending);
    if (!recheck.ok) {
      verified = false;
      return refuseInstall(`re-verification failed: ${recheck.reason}`);
    }
    // quitAndInstall runs the NSIS in-place upgrade (preserves userData) and quits the
    // app, so this resolves optimistically for the caller's fire-and-forget.
    autoUpdater.quitAndInstall();
    return { ok: true };
  };

  ipcMain.handle(UPDATE_CHECK_CHANNEL, () => checkForUpdates());
  ipcMain.handle(UPDATE_DOWNLOAD_CHANNEL, () => downloadUpdate());
  ipcMain.handle(UPDATE_INSTALL_CHANNEL, () => quitAndInstall());

  const dispose = (): void => {
    ipcMain.removeHandler(UPDATE_CHECK_CHANNEL);
    ipcMain.removeHandler(UPDATE_DOWNLOAD_CHANNEL);
    ipcMain.removeHandler(UPDATE_INSTALL_CHANNEL);
  };

  return { dispose, checkForUpdates };
}
