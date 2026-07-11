// updater.test.ts — unit tests for the AUTO-UPDATE state machine + AUTHENTICITY gate.
//
// Electron ipcMain is mocked; a fake `autoUpdater` (EventEmitter-like) and a fake
// verifier are injected so the whole event -> verify -> IPC mapping is exercised
// WITHOUT electron-updater, node crypto, or a packaged app. Pins: autoDownload AND
// autoInstallOnAppQuit forced OFF, each autoUpdater event -> its UpdateStatus
// broadcast, the download-time verify gate (ready only on a passing signature), the
// install gate (refused unless verified + a TOCTOU re-verify), the check/download/
// quitAndInstall handlers (success + graceful failure), and the disposer.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  handle: vi.fn(),
  removeHandler: vi.fn(),
}));

vi.mock('electron', () => ({
  ipcMain: { handle: mocks.handle, removeHandler: mocks.removeHandler },
}));

import {
  UPDATE_CHECK_CHANNEL,
  UPDATE_DOWNLOAD_CHANNEL,
  UPDATE_INSTALL_CHANNEL,
  registerUpdater,
  toPercent,
  type AutoUpdaterLike,
  type DownloadedUpdate,
  type UpdateStatus,
  type UpdateActionResult,
} from './updater';
import type { UpdateVerifyResult } from './updateVerify';

/** Flush pending microtasks/timers so an async verify continuation runs. */
const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

/** A capturing fake autoUpdater: records listeners so tests can emit events. */
function makeAutoUpdater(over: Partial<AutoUpdaterLike> = {}): {
  autoUpdater: AutoUpdaterLike;
  emit: (event: string, arg?: unknown) => void;
  checkForUpdates: ReturnType<typeof vi.fn>;
  downloadUpdate: ReturnType<typeof vi.fn>;
  quitAndInstall: ReturnType<typeof vi.fn>;
} {
  const listeners = new Map<string, (arg: never) => void>();
  const checkForUpdates = vi.fn(async () => undefined);
  const downloadUpdate = vi.fn(async () => undefined);
  const quitAndInstall = vi.fn();
  const autoUpdater: AutoUpdaterLike = {
    autoDownload: true,
    autoInstallOnAppQuit: true,
    on(event: string, listener: (...args: never[]) => void) {
      listeners.set(event, listener as (arg: never) => void);
      return autoUpdater;
    },
    checkForUpdates,
    downloadUpdate,
    quitAndInstall,
    ...over,
  };
  const emit = (event: string, arg?: unknown): void => {
    const fn = listeners.get(event);
    if (fn) fn(arg as never);
  };
  return { autoUpdater, emit, checkForUpdates, downloadUpdate, quitAndInstall };
}

const okVerify = (): ReturnType<typeof vi.fn> =>
  vi.fn(async (_c: DownloadedUpdate): Promise<UpdateVerifyResult> => ({ ok: true }));

/** Wire registerUpdater with a fake autoUpdater + verifier; return the moving parts. */
function setup(
  opts: {
    autoUpdater?: ReturnType<typeof makeAutoUpdater>;
    verifyUpdate?: ReturnType<typeof vi.fn>;
    log?: (message: string) => void;
  } = {},
): {
  au: ReturnType<typeof makeAutoUpdater>;
  broadcast: ReturnType<typeof vi.fn>;
  verifyUpdate: ReturnType<typeof vi.fn>;
  handle: ReturnType<typeof registerUpdater>;
} {
  const au = opts.autoUpdater ?? makeAutoUpdater();
  const broadcast = vi.fn<(s: UpdateStatus) => void>();
  const verifyUpdate = opts.verifyUpdate ?? okVerify();
  const handle = registerUpdater({
    autoUpdater: au.autoUpdater,
    broadcast,
    verifyUpdate,
    log: opts.log,
  });
  return { au, broadcast, verifyUpdate, handle };
}

/** Find the ipcMain.handle callback registered for `channel`. */
function handlerFor(channel: string): () => unknown {
  const call = mocks.handle.mock.calls.find((c) => c[0] === channel);
  if (!call) throw new Error(`no handler registered for ${channel}`);
  return call[1] as () => unknown;
}

beforeEach(() => {
  mocks.handle.mockReset();
  mocks.removeHandler.mockReset();
});

describe('toPercent', () => {
  it('rounds, clamps to 0..100, and defaults non-finite/undefined to 0', () => {
    expect(toPercent(42.7)).toBe(43);
    expect(toPercent(0)).toBe(0);
    expect(toPercent(100)).toBe(100);
    expect(toPercent(150)).toBe(100);
    expect(toPercent(-5)).toBe(0);
    expect(toPercent(undefined)).toBe(0);
    expect(toPercent(Number.NaN)).toBe(0);
    // Non-finite (Infinity) is treated as garbage -> the safe 0 default, not 100.
    expect(toPercent(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe('registerUpdater — event -> IPC state machine', () => {
  it('forces autoDownload OFF (the user confirms the download)', () => {
    const { au } = setup();
    expect(au.autoUpdater.autoDownload).toBe(false);
  });

  it('forces autoInstallOnAppQuit OFF (no silent install-on-quit bypass)', () => {
    const { au } = setup();
    expect(au.autoUpdater.autoInstallOnAppQuit).toBe(false);
  });

  it('maps checking-for-update -> {state:checking}', () => {
    const { au, broadcast } = setup();
    au.emit('checking-for-update');
    expect(broadcast).toHaveBeenCalledWith({ state: 'checking' });
  });

  it('maps update-available -> {state:available, version}', () => {
    const { au, broadcast } = setup();
    au.emit('update-available', { version: '1.4.0' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'available', version: '1.4.0' });
  });

  it('update-available with no version falls back to an empty string', () => {
    const { au, broadcast } = setup();
    au.emit('update-available', {});
    expect(broadcast).toHaveBeenCalledWith({ state: 'available', version: '' });
  });

  it('maps update-not-available -> {state:none}', () => {
    const { au, broadcast } = setup();
    au.emit('update-not-available', { version: '1.3.0' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'none' });
  });

  it('maps download-progress -> {state:progress, percent} (rounded/clamped)', () => {
    const { au, broadcast } = setup();
    au.emit('download-progress', { percent: 37.4 });
    expect(broadcast).toHaveBeenCalledWith({ state: 'progress', percent: 37 });
  });

  it('maps error(Error) -> {state:error, message} and logs', () => {
    const log = vi.fn();
    const { au, broadcast } = setup({ log });
    au.emit('error', new Error('ENOTFOUND github.com'));
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'ENOTFOUND github.com' });
    expect(log).toHaveBeenCalledWith(expect.stringContaining('ENOTFOUND github.com'));
  });

  it('error with a non-Error value falls back to a generic message', () => {
    const { au, broadcast } = setup();
    au.emit('error', undefined);
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'update failed' });
  });
});

describe('registerUpdater — download-time AUTHENTICITY gate', () => {
  it('announces {state:downloaded} ONLY after the signature verifies', async () => {
    const verifyUpdate = okVerify();
    const { au, broadcast } = setup({ verifyUpdate });
    au.emit('update-downloaded', {
      version: '1.5.0',
      downloadedFile: 'C:/cache/media-studio-1.5.0-win-x64.exe',
    });
    // Verification is async: nothing is announced synchronously.
    expect(broadcast).not.toHaveBeenCalled();
    await tick();
    expect(verifyUpdate).toHaveBeenCalledWith({
      version: '1.5.0',
      downloadedFile: 'C:/cache/media-studio-1.5.0-win-x64.exe',
    });
    expect(broadcast).toHaveBeenCalledWith({ state: 'downloaded', version: '1.5.0' });
  });

  it('defaults a missing version/downloadedFile to empty strings for the verifier', async () => {
    const verifyUpdate = okVerify();
    const { au, broadcast } = setup({ verifyUpdate });
    au.emit('update-downloaded', undefined);
    await tick();
    expect(verifyUpdate).toHaveBeenCalledWith({ version: '', downloadedFile: '' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'downloaded', version: '' });
  });

  it('a FAILED signature check broadcasts a rejection error, not {downloaded}', async () => {
    const log = vi.fn();
    const verifyUpdate = vi.fn(
      async (): Promise<UpdateVerifyResult> => ({ ok: false, reason: 'bad signature' }),
    );
    const { au, broadcast } = setup({ verifyUpdate, log });
    au.emit('update-downloaded', { version: '1.5.0', downloadedFile: 'C:/x.exe' });
    await tick();
    expect(broadcast).toHaveBeenCalledWith({
      state: 'error',
      message: 'Update rejected: bad signature',
    });
    expect(broadcast).not.toHaveBeenCalledWith(expect.objectContaining({ state: 'downloaded' }));
    expect(log).toHaveBeenCalledWith(expect.stringContaining('bad signature'));
  });
});

describe('registerUpdater — renderer-facing ipc handlers', () => {
  it('registers exactly the check/download/quitAndInstall channels', () => {
    setup();
    const channels = mocks.handle.mock.calls.map((c) => c[0]);
    expect(channels).toEqual([
      UPDATE_CHECK_CHANNEL,
      UPDATE_DOWNLOAD_CHANNEL,
      UPDATE_INSTALL_CHANNEL,
    ]);
  });

  it('the check handler triggers autoUpdater.checkForUpdates and resolves {ok:true}', async () => {
    const { au } = setup();
    const res = (await handlerFor(UPDATE_CHECK_CHANNEL)()) as UpdateActionResult;
    expect(au.checkForUpdates).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ ok: true });
  });

  it('a failed check degrades quietly: {ok:false}, an error status, and a log', async () => {
    const au = makeAutoUpdater({
      checkForUpdates: vi.fn(async () => {
        throw new Error('offline');
      }),
    });
    const log = vi.fn();
    const { broadcast } = setup({ autoUpdater: au, log });
    const res = (await handlerFor(UPDATE_CHECK_CHANNEL)()) as UpdateActionResult;
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('offline');
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'offline' });
    expect(log).toHaveBeenCalledWith(expect.stringContaining('offline'));
  });

  it('the download handler triggers autoUpdater.downloadUpdate and resolves {ok:true}', async () => {
    const { au } = setup();
    const res = (await handlerFor(UPDATE_DOWNLOAD_CHANNEL)()) as UpdateActionResult;
    expect(au.downloadUpdate).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ ok: true });
  });

  it('a failed download reports {ok:false} + an error status (never throws)', async () => {
    const au = makeAutoUpdater({
      downloadUpdate: vi.fn(async () => {
        throw new Error('disk full');
      }),
    });
    const { broadcast } = setup({ autoUpdater: au });
    const res = (await handlerFor(UPDATE_DOWNLOAD_CHANNEL)()) as UpdateActionResult;
    expect(res).toEqual({ ok: false, reason: 'disk full' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'disk full' });
  });

  it('a non-Error string rejection is surfaced verbatim (errText string branch)', async () => {
    const au = makeAutoUpdater({
      downloadUpdate: vi.fn(async () => {
        throw 'ECONNRESET peer';
      }),
    });
    const { broadcast } = setup({ autoUpdater: au });
    const res = (await handlerFor(UPDATE_DOWNLOAD_CHANNEL)()) as UpdateActionResult;
    expect(res).toEqual({ ok: false, reason: 'ECONNRESET peer' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'ECONNRESET peer' });
  });

  it('the returned checkForUpdates helper is the same graceful path', async () => {
    const { au, handle } = setup();
    await expect(handle.checkForUpdates()).resolves.toEqual({ ok: true });
    expect(au.checkForUpdates).toHaveBeenCalledTimes(1);
  });
});

describe('registerUpdater — install gate (verify + TOCTOU re-verify)', () => {
  it('refuses to install when no update has been downloaded', async () => {
    const { au, broadcast } = setup();
    const res = (await handlerFor(UPDATE_INSTALL_CHANNEL)()) as UpdateActionResult;
    expect(res).toEqual({ ok: false, reason: 'no update has been downloaded' });
    expect(au.quitAndInstall).not.toHaveBeenCalled();
    expect(broadcast).toHaveBeenCalledWith({
      state: 'error',
      message: 'Update rejected: no update has been downloaded',
    });
  });

  it('refuses to install a downloaded update whose signature FAILED', async () => {
    const verifyUpdate = vi.fn(
      async (): Promise<UpdateVerifyResult> => ({ ok: false, reason: 'forged' }),
    );
    const { au } = setup({ verifyUpdate });
    au.emit('update-downloaded', { version: '1.5.0', downloadedFile: 'C:/x.exe' });
    await tick();
    const res = (await handlerFor(UPDATE_INSTALL_CHANNEL)()) as UpdateActionResult;
    expect(res).toEqual({ ok: false, reason: 'update failed verification' });
    expect(au.quitAndInstall).not.toHaveBeenCalled();
  });

  it('installs a verified update after a passing TOCTOU re-verify', async () => {
    const verifyUpdate = okVerify();
    const { au } = setup({ verifyUpdate });
    au.emit('update-downloaded', {
      version: '1.5.0',
      downloadedFile: 'C:/cache/media-studio-1.5.0-win-x64.exe',
    });
    await tick();
    const res = (await handlerFor(UPDATE_INSTALL_CHANNEL)()) as UpdateActionResult;
    expect(res).toEqual({ ok: true });
    expect(au.quitAndInstall).toHaveBeenCalledTimes(1);
    // Verified once at download time, re-verified once at install time (TOCTOU).
    expect(verifyUpdate).toHaveBeenCalledTimes(2);
  });

  it('refuses install when the TOCTOU re-verify fails (file swapped after download)', async () => {
    const verifyUpdate = vi
      .fn<(c: DownloadedUpdate) => Promise<UpdateVerifyResult>>()
      .mockResolvedValueOnce({ ok: true }) // passes at download time
      .mockResolvedValueOnce({ ok: false, reason: 'digest changed' }); // fails at install time
    const { au, broadcast } = setup({ verifyUpdate });
    au.emit('update-downloaded', { version: '1.5.0', downloadedFile: 'C:/x.exe' });
    await tick();
    const res = (await handlerFor(UPDATE_INSTALL_CHANNEL)()) as UpdateActionResult;
    expect(res).toEqual({ ok: false, reason: 're-verification failed: digest changed' });
    expect(au.quitAndInstall).not.toHaveBeenCalled();
    expect(broadcast).toHaveBeenCalledWith({
      state: 'error',
      message: 'Update rejected: re-verification failed: digest changed',
    });
  });
});

describe('registerUpdater — teardown', () => {
  it('dispose removes all three handlers', () => {
    const { handle } = setup();
    handle.dispose();
    expect(mocks.removeHandler).toHaveBeenCalledWith(UPDATE_CHECK_CHANNEL);
    expect(mocks.removeHandler).toHaveBeenCalledWith(UPDATE_DOWNLOAD_CHANNEL);
    expect(mocks.removeHandler).toHaveBeenCalledWith(UPDATE_INSTALL_CHANNEL);
  });
});
