// preload.test.ts — the contextBridge subscribe bridges (WU-1a review LOW). Pins
// that onProvisioningState / onBootstrapProgress register on the right channel,
// forward ONLY the notification payload to the callback (dropping the
// IpcRendererEvent first arg), and return an unsubscribe that removes exactly the
// listener they added. Electron is mocked; importing preload.ts once runs
// contextBridge.exposeInMainWorld, from which we capture the exposed `api`.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  exposeInMainWorld: vi.fn(),
  on: vi.fn(),
  removeListener: vi.fn(),
  invoke: vi.fn(),
  getPathForFile: vi.fn(),
}));

vi.mock('electron', () => ({
  contextBridge: { exposeInMainWorld: mocks.exposeInMainWorld },
  ipcRenderer: { on: mocks.on, removeListener: mocks.removeListener, invoke: mocks.invoke },
  webUtils: { getPathForFile: mocks.getPathForFile },
}));

import './preload';
import type { BootstrapProgressEvent, MediaApi, ProvisioningState } from './preload';

// Captured once at module load — the object preload.ts hands to exposeInMainWorld.
const api = mocks.exposeInMainWorld.mock.calls[0][1] as MediaApi;

const PROVISIONING_STATE_CHANNEL = 'provisioning.state';
const BOOTSTRAP_PROGRESS_CHANNEL = 'bootstrap.progress';

/** The (event, payload) listener preload registered for the most recent on() call. */
function lastListener(): (event: unknown, payload: unknown) => void {
  return mocks.on.mock.calls.at(-1)![1] as (event: unknown, payload: unknown) => void;
}

beforeEach(() => {
  mocks.on.mockClear();
  mocks.removeListener.mockClear();
});

describe('preload exposes the api on window (contextBridge)', () => {
  it('registered exactly one bridge named "api"', () => {
    expect(mocks.exposeInMainWorld).toHaveBeenCalledWith('api', expect.any(Object));
  });
});

describe('onProvisioningState — forwards only the payload + returns an unsubscribe', () => {
  it('subscribes on provisioning.state and forwards ONLY the payload', () => {
    const cb = vi.fn();
    api.onProvisioningState(cb);
    expect(mocks.on).toHaveBeenCalledWith(PROVISIONING_STATE_CHANNEL, expect.any(Function));

    const payload: ProvisioningState = { active: true };
    // The IpcRendererEvent (first arg) must be dropped — the callback sees payload only.
    lastListener()({ sender: 'evt' }, payload);
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenCalledWith(payload);
  });

  it('the returned unsubscribe removes exactly the listener it added', () => {
    const cb = vi.fn();
    const unsubscribe = api.onProvisioningState(cb);
    const listener = lastListener();
    unsubscribe();
    expect(mocks.removeListener).toHaveBeenCalledWith(PROVISIONING_STATE_CHANNEL, listener);
  });
});

describe('chooseInstallProfile — invokes the choose channel with the payload (WU-1c)', () => {
  it('invokes installProfile.choose with { profile, bundles }', () => {
    mocks.invoke.mockClear();
    void api.chooseInstallProfile('custom', ['ai-director']);
    expect(mocks.invoke).toHaveBeenCalledWith('installProfile.choose', {
      profile: 'custom',
      bundles: ['ai-director'],
    });
  });
});

describe('onBootstrapProgress — forwards only the payload + returns an unsubscribe', () => {
  it('subscribes on bootstrap.progress and forwards ONLY the payload', () => {
    const cb = vi.fn();
    api.onBootstrapProgress(cb);
    expect(mocks.on).toHaveBeenCalledWith(BOOTSTRAP_PROGRESS_CHANNEL, expect.any(Function));

    const payload: BootstrapProgressEvent = { state: 'running', line: 'assets 42.0%' };
    lastListener()({ sender: 'evt' }, payload);
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenCalledWith(payload);
  });

  it('the returned unsubscribe removes exactly the listener it added', () => {
    const cb = vi.fn();
    const unsubscribe = api.onBootstrapProgress(cb);
    const listener = lastListener();
    unsubscribe();
    expect(mocks.removeListener).toHaveBeenCalledWith(BOOTSTRAP_PROGRESS_CHANNEL, listener);
  });
});
