// repairSetupIpc.test.ts — unit tests for the on-demand "Retry setup / Repair"
// IPC (WU A5). Electron ipcMain is mocked; the bootstrap runner / in-flight
// signal / sidecar (re)start are injected. Pins: single-flight (no second
// concurrent bootstrap), idempotent re-run wiring, (re)start-on-success,
// fail-without-duplicate-reason, throw-is-caught, and the disposer.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  handle: vi.fn(),
  removeHandler: vi.fn(),
}));

vi.mock('electron', () => ({
  ipcMain: { handle: mocks.handle, removeHandler: mocks.removeHandler },
}));

import {
  SETUP_REPAIR_CHANNEL,
  performRepairSetup,
  registerRepairSetupIpc,
  type RepairSetupDeps,
} from './repairSetupIpc';

function makeDeps(over: Partial<RepairSetupDeps> = {}): {
  deps: RepairSetupDeps;
  isBootstrapInFlight: ReturnType<typeof vi.fn>;
  runBootstrap: ReturnType<typeof vi.fn>;
  onBootstrapSucceeded: ReturnType<typeof vi.fn>;
} {
  const isBootstrapInFlight = vi.fn(() => false);
  const runBootstrap = vi.fn(async () => true);
  const onBootstrapSucceeded = vi.fn();
  const deps: RepairSetupDeps = {
    isBootstrapInFlight,
    runBootstrap,
    onBootstrapSucceeded,
    ...over,
  };
  return { deps, isBootstrapInFlight, runBootstrap, onBootstrapSucceeded };
}

beforeEach(() => {
  mocks.handle.mockReset();
  mocks.removeHandler.mockReset();
});

describe('performRepairSetup — repair decision', () => {
  it('re-runs the bootstrap and (re)starts the sidecar on success', async () => {
    const { deps, runBootstrap, onBootstrapSucceeded } = makeDeps();
    const res = await performRepairSetup(deps);
    expect(res).toEqual({ ok: true });
    expect(runBootstrap).toHaveBeenCalledTimes(1);
    expect(onBootstrapSucceeded).toHaveBeenCalledTimes(1);
  });

  it('is single-flight: a second call while a bootstrap runs is a no-op', async () => {
    const { deps, runBootstrap, onBootstrapSucceeded } = makeDeps({
      isBootstrapInFlight: vi.fn(() => true),
    });
    const res = await performRepairSetup(deps);
    expect(res.ok).toBe(false);
    expect(res.reason).toContain('already running');
    // Crucially: it did NOT spawn a second concurrent bootstrap.
    expect(runBootstrap).not.toHaveBeenCalled();
    expect(onBootstrapSucceeded).not.toHaveBeenCalled();
  });

  it('reports ok:false with no duplicate reason on a normal failed run', async () => {
    const { deps, onBootstrapSucceeded } = makeDeps({
      runBootstrap: vi.fn(async () => false),
    });
    const res = await performRepairSetup(deps);
    // The actionable message arrives on the bootstrap-error channel, so no
    // reason is duplicated here.
    expect(res).toEqual({ ok: false });
    expect(onBootstrapSucceeded).not.toHaveBeenCalled();
  });

  it('catches a thrown runner and reports the message (never crashes)', async () => {
    const { deps, onBootstrapSucceeded } = makeDeps({
      runBootstrap: vi.fn(async () => {
        throw new Error('python not found');
      }),
    });
    const res = await performRepairSetup(deps);
    expect(res.ok).toBe(false);
    expect(res.reason).toContain('python not found');
    expect(onBootstrapSucceeded).not.toHaveBeenCalled();
  });
});

describe('registerRepairSetupIpc — registration + teardown', () => {
  it('registers the setup.repair channel and the disposer removes it', () => {
    const { deps } = makeDeps();
    const dispose = registerRepairSetupIpc(deps);
    expect(mocks.handle).toHaveBeenCalledTimes(1);
    expect(mocks.handle.mock.calls[0][0]).toBe(SETUP_REPAIR_CHANNEL);
    dispose();
    expect(mocks.removeHandler).toHaveBeenCalledWith(SETUP_REPAIR_CHANNEL);
  });

  it('the registered handler delegates to performRepairSetup with the deps', async () => {
    const { deps, runBootstrap } = makeDeps();
    registerRepairSetupIpc(deps);
    const handler = mocks.handle.mock.calls[0][1] as () => Promise<unknown>;
    await expect(handler()).resolves.toEqual({ ok: true });
    expect(runBootstrap).toHaveBeenCalledTimes(1);
  });
});
