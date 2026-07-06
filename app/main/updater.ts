// updater.ts — main-process IN-PLACE AUTO-UPDATE wiring (WU-U).
//
// Reframe ships as an NSIS installer + portable zip and, until now, a new
// version meant a manual uninstall/reinstall. This module wires
// `electron-updater`'s `autoUpdater` to a GitHub-Releases feed so a running,
// PACKAGED copy notices a newer release, lets the user confirm the download, and
// then quitAndInstall()s the NSIS in-place upgrade — which PRESERVES userData
// (the DPAPI keystore `secure-keys.json` + settings + the relocatable data root).
//
// DECISIONS (user-chosen): GitHub feed + auto-check-on-launch, `autoDownload` OFF
// (the user confirms in the renderer's UpdateBanner before any bytes download).
//
// UNSIGNED BUILD: the app has no code-signing certificate (electron-builder ships
// with CSC off — see electron-builder.yml). electron-updater therefore skips
// publisher-signature verification, and Windows SmartScreen may warn when the
// downloaded installer runs. That is expected; we deliberately do NOT add signing.
//
// TESTABILITY: the real `autoUpdater` (an electron-updater singleton that reads
// `app-update.yml`, only present in a packaged build) is INJECTED, mirroring the
// injected-deps shape of `repairSetupIpc.ts`/`dataFolderIpc.ts`. main.ts casts
// the real singleton to {@link AutoUpdaterLike} and provides the broadcast; tests
// pass a fake so the whole event -> IPC state machine is exercised without
// electron-updater or a packaged app. `ipcMain` is mocked in tests.
import { ipcMain } from 'electron';

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
 * `downloaded`/`error`/`none` without any main-process knowledge.
 */
export type UpdateStatus =
  | { state: 'checking' }
  | { state: 'available'; version: string }
  | { state: 'none' }
  | { state: 'progress'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string };

/** Subset of electron-updater's `UpdateInfo` this module reads. */
export interface UpdateInfoLike {
  version?: string;
}

/** Subset of electron-updater's `ProgressInfo` this module reads. */
export interface ProgressInfoLike {
  percent?: number;
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
  on(event: string, listener: (...args: never[]) => void): unknown;
  checkForUpdates(): Promise<unknown>;
  downloadUpdate(): Promise<unknown>;
  quitAndInstall(): void;
}

/** Outcome of a renderer-triggered check/download (never throws to the caller). */
export interface UpdateActionResult {
  ok: boolean;
  reason?: string;
}

/** Wiring main.ts injects (keeps this module free of Electron window/IO). */
export interface UpdaterDeps {
  /** The electron-updater singleton (cast) — injected for testability. */
  autoUpdater: AutoUpdaterLike;
  /** Fan-out a status to every live renderer (main.ts owns the window set). */
  broadcast: (status: UpdateStatus) => void;
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
 * Every event maps to one {@link UpdateStatus} variant; every action is wrapped so
 * a rejection becomes a loud-but-safe `{ ok:false }` + an `error` status rather
 * than an unhandled rejection. `autoDownload` is forced OFF so nothing downloads
 * until the user confirms.
 */
export function registerUpdater(deps: UpdaterDeps): UpdaterHandle {
  const { autoUpdater, broadcast } = deps;
  const log = deps.log ?? ((): void => {});

  // The user confirms the download in the UpdateBanner (autoDownload OFF).
  autoUpdater.autoDownload = false;

  autoUpdater.on('checking-for-update', () => broadcast({ state: 'checking' }));
  autoUpdater.on('update-available', (info: UpdateInfoLike) =>
    broadcast({ state: 'available', version: info?.version ?? '' }),
  );
  autoUpdater.on('update-not-available', () => broadcast({ state: 'none' }));
  autoUpdater.on('download-progress', (progress: ProgressInfoLike) =>
    broadcast({ state: 'progress', percent: toPercent(progress?.percent) }),
  );
  autoUpdater.on('update-downloaded', (info: UpdateInfoLike) =>
    broadcast({ state: 'downloaded', version: info?.version ?? '' }),
  );
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

  ipcMain.handle(UPDATE_CHECK_CHANNEL, () => checkForUpdates());
  ipcMain.handle(UPDATE_DOWNLOAD_CHANNEL, () => downloadUpdate());
  ipcMain.handle(UPDATE_INSTALL_CHANNEL, (): UpdateActionResult => {
    // quitAndInstall runs the NSIS in-place upgrade (preserves userData). It quits
    // the app, so this resolves optimistically for the caller's fire-and-forget.
    autoUpdater.quitAndInstall();
    return { ok: true };
  });

  const dispose = (): void => {
    ipcMain.removeHandler(UPDATE_CHECK_CHANNEL);
    ipcMain.removeHandler(UPDATE_DOWNLOAD_CHANNEL);
    ipcMain.removeHandler(UPDATE_INSTALL_CHANNEL);
  };

  return { dispose, checkForUpdates };
}
