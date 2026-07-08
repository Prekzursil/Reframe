// updater.test.ts — unit tests for the IN-PLACE AUTO-UPDATE state machine (WU-U).
//
// Electron ipcMain is mocked; a fake `autoUpdater` (EventEmitter-like) is
// injected so the whole event -> IPC mapping is exercised WITHOUT electron-updater
// or a packaged app. Pins: autoDownload forced OFF, each autoUpdater event -> its
// UpdateStatus broadcast, the check/download/quitAndInstall handlers (success +
// graceful failure), and the disposer.
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
  type UpdateStatus,
  type UpdateActionResult,
} from './updater';

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
    const { autoUpdater } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    expect(autoUpdater.autoDownload).toBe(false);
  });

  it('maps checking-for-update -> {state:checking}', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('checking-for-update');
    expect(broadcast).toHaveBeenCalledWith({ state: 'checking' });
  });

  it('maps update-available -> {state:available, version}', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('update-available', { version: '1.4.0' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'available', version: '1.4.0' });
  });

  it('update-available with no version falls back to an empty string', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('update-available', {});
    expect(broadcast).toHaveBeenCalledWith({ state: 'available', version: '' });
  });

  it('maps update-not-available -> {state:none}', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('update-not-available', { version: '1.3.0' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'none' });
  });

  it('maps download-progress -> {state:progress, percent} (rounded/clamped)', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('download-progress', { percent: 37.4 });
    expect(broadcast).toHaveBeenCalledWith({ state: 'progress', percent: 37 });
  });

  it('maps update-downloaded -> {state:downloaded, version}', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('update-downloaded', { version: '1.4.0' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'downloaded', version: '1.4.0' });
  });

  it('update-downloaded with no version falls back to an empty string', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('update-downloaded', undefined);
    expect(broadcast).toHaveBeenCalledWith({ state: 'downloaded', version: '' });
  });

  it('maps error(Error) -> {state:error, message} and logs', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    const log = vi.fn();
    registerUpdater({ autoUpdater, broadcast, log });
    emit('error', new Error('ENOTFOUND github.com'));
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'ENOTFOUND github.com' });
    expect(log).toHaveBeenCalledWith(expect.stringContaining('ENOTFOUND github.com'));
  });

  it('error with a non-Error value falls back to a generic message', () => {
    const { autoUpdater, emit } = makeAutoUpdater();
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    emit('error', undefined);
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'update failed' });
  });
});

describe('registerUpdater — renderer-facing ipc handlers', () => {
  it('registers exactly the check/download/quitAndInstall channels', () => {
    const { autoUpdater } = makeAutoUpdater();
    registerUpdater({ autoUpdater, broadcast: vi.fn() });
    const channels = mocks.handle.mock.calls.map((c) => c[0]);
    expect(channels).toEqual([
      UPDATE_CHECK_CHANNEL,
      UPDATE_DOWNLOAD_CHANNEL,
      UPDATE_INSTALL_CHANNEL,
    ]);
  });

  it('the check handler triggers autoUpdater.checkForUpdates and resolves {ok:true}', async () => {
    const { autoUpdater, checkForUpdates } = makeAutoUpdater();
    registerUpdater({ autoUpdater, broadcast: vi.fn() });
    const res = (await handlerFor(UPDATE_CHECK_CHANNEL)()) as UpdateActionResult;
    expect(checkForUpdates).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ ok: true });
  });

  it('a failed check degrades quietly: {ok:false}, an error status, and a log', async () => {
    const { autoUpdater } = makeAutoUpdater({
      checkForUpdates: vi.fn(async () => {
        throw new Error('offline');
      }),
    });
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    const log = vi.fn();
    registerUpdater({ autoUpdater, broadcast, log });
    const res = (await handlerFor(UPDATE_CHECK_CHANNEL)()) as UpdateActionResult;
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('offline');
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'offline' });
    expect(log).toHaveBeenCalledWith(expect.stringContaining('offline'));
  });

  it('the download handler triggers autoUpdater.downloadUpdate and resolves {ok:true}', async () => {
    const { autoUpdater, downloadUpdate } = makeAutoUpdater();
    registerUpdater({ autoUpdater, broadcast: vi.fn() });
    const res = (await handlerFor(UPDATE_DOWNLOAD_CHANNEL)()) as UpdateActionResult;
    expect(downloadUpdate).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ ok: true });
  });

  it('a failed download reports {ok:false} + an error status (never throws)', async () => {
    const { autoUpdater } = makeAutoUpdater({
      downloadUpdate: vi.fn(async () => {
        throw new Error('disk full');
      }),
    });
    const broadcast = vi.fn<(s: UpdateStatus) => void>();
    registerUpdater({ autoUpdater, broadcast });
    const res = (await handlerFor(UPDATE_DOWNLOAD_CHANNEL)()) as UpdateActionResult;
    expect(res).toEqual({ ok: false, reason: 'disk full' });
    expect(broadcast).toHaveBeenCalledWith({ state: 'error', message: 'disk full' });
  });

  it('the install handler calls quitAndInstall (the NSIS in-place upgrade)', () => {
    const { autoUpdater, quitAndInstall } = makeAutoUpdater();
    registerUpdater({ autoUpdater, broadcast: vi.fn() });
    const res = handlerFor(UPDATE_INSTALL_CHANNEL)() as UpdateActionResult;
    expect(quitAndInstall).toHaveBeenCalledTimes(1);
    expect(res).toEqual({ ok: true });
  });

  it('the returned checkForUpdates helper is the same graceful path', async () => {
    const { autoUpdater, checkForUpdates } = makeAutoUpdater();
    const handle = registerUpdater({ autoUpdater, broadcast: vi.fn() });
    await expect(handle.checkForUpdates()).resolves.toEqual({ ok: true });
    expect(checkForUpdates).toHaveBeenCalledTimes(1);
  });
});

describe('registerUpdater — teardown', () => {
  it('dispose removes all three handlers', () => {
    const { autoUpdater } = makeAutoUpdater();
    const handle = registerUpdater({ autoUpdater, broadcast: vi.fn() });
    handle.dispose();
    expect(mocks.removeHandler).toHaveBeenCalledWith(UPDATE_CHECK_CHANNEL);
    expect(mocks.removeHandler).toHaveBeenCalledWith(UPDATE_DOWNLOAD_CHANNEL);
    expect(mocks.removeHandler).toHaveBeenCalledWith(UPDATE_INSTALL_CHANNEL);
  });
});
