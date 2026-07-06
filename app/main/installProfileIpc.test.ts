// installProfileIpc.test.ts — unit tests for the first-run install-profile choice
// IPC (WU-1c). Electron ipcMain is mocked; the map resolver, persistence and the
// bootstrap kickoff are injected. Pins: single-flight guard, fail-loud on an
// invalid choice (no silent default), persist-then-begin ordering, and the disposer.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
  handle: vi.fn(),
  removeHandler: vi.fn(),
}));

vi.mock('electron', () => ({
  ipcMain: { handle: mocks.handle, removeHandler: mocks.removeHandler },
}));

import {
  INSTALL_PROFILE_CHOOSE_CHANNEL,
  performChooseInstallProfile,
  registerInstallProfileIpc,
  type InstallProfileDeps,
} from './installProfileIpc';
import { InstallProfileError, type ResolvedInstallChoice } from './installProfiles';

const CHOICE: ResolvedInstallChoice = {
  profile: 'default',
  bundles: ['transcription'],
  assets: ['yunet-face-detection', 'lightasd-s3fd', 'lightasd-asd', 'whisper-large-v3-turbo'],
};

function makeDeps(over: Partial<InstallProfileDeps> = {}): {
  deps: InstallProfileDeps;
  resolveChoice: ReturnType<typeof vi.fn>;
  persist: ReturnType<typeof vi.fn>;
  beginBootstrap: ReturnType<typeof vi.fn>;
} {
  const resolveChoice = vi.fn(() => CHOICE);
  const persist = vi.fn();
  const beginBootstrap = vi.fn();
  const deps: InstallProfileDeps = {
    isBootstrapInFlight: vi.fn(() => false),
    resolveChoice,
    persist,
    beginBootstrap,
    ...over,
  };
  return { deps, resolveChoice, persist, beginBootstrap };
}

beforeEach(() => {
  mocks.handle.mockReset();
  mocks.removeHandler.mockReset();
});

describe('performChooseInstallProfile — choose decision', () => {
  it('resolves, persists, then begins bootstrap on a valid choice', async () => {
    const { deps, resolveChoice, persist, beginBootstrap } = makeDeps();
    const res = await performChooseInstallProfile(deps, { profile: 'default' });
    expect(res).toEqual({ ok: true });
    expect(resolveChoice).toHaveBeenCalledWith('default', []);
    expect(persist).toHaveBeenCalledWith(CHOICE);
    expect(beginBootstrap).toHaveBeenCalledWith(CHOICE.assets);
    // persist happens BEFORE begin (so a re-bootstrap can replay even if spawn fails)
    expect(persist.mock.invocationCallOrder[0]).toBeLessThan(
      beginBootstrap.mock.invocationCallOrder[0],
    );
  });

  it('forwards Custom bundles to the resolver', async () => {
    const { deps, resolveChoice } = makeDeps();
    await performChooseInstallProfile(deps, { profile: 'custom', bundles: ['ai-director'] });
    expect(resolveChoice).toHaveBeenCalledWith('custom', ['ai-director']);
  });

  it('treats a non-array bundles field as no bundles', async () => {
    const { deps, resolveChoice } = makeDeps();
    await performChooseInstallProfile(deps, { profile: 'minimum', bundles: 'x' as unknown });
    expect(resolveChoice).toHaveBeenCalledWith('minimum', []);
  });

  it('is single-flight: a choice while a bootstrap runs is a no-op', async () => {
    const { deps, resolveChoice, beginBootstrap } = makeDeps({
      isBootstrapInFlight: vi.fn(() => true),
    });
    const res = await performChooseInstallProfile(deps, { profile: 'full' });
    expect(res.ok).toBe(false);
    expect(res.reason).toContain('already running');
    expect(resolveChoice).not.toHaveBeenCalled();
    expect(beginBootstrap).not.toHaveBeenCalled();
  });

  it('FAILS LOUD on an invalid choice — no persist, no bootstrap (no silent default)', async () => {
    const { deps, persist, beginBootstrap } = makeDeps({
      resolveChoice: vi.fn(() => {
        throw new InstallProfileError('unknown install profile: "bogus"');
      }),
    });
    const res = await performChooseInstallProfile(deps, { profile: 'bogus' });
    expect(res.ok).toBe(false);
    expect(res.reason).toContain('unknown install profile');
    expect(persist).not.toHaveBeenCalled();
    expect(beginBootstrap).not.toHaveBeenCalled();
  });

  it('surfaces a non-typed resolver throw too (never crashes the handler)', async () => {
    const { deps } = makeDeps({
      resolveChoice: vi.fn(() => {
        throw new Error('boom');
      }),
    });
    const res = await performChooseInstallProfile(deps, { profile: 'default' });
    expect(res.ok).toBe(false);
    expect(res.reason).toContain('boom');
  });
});

describe('registerInstallProfileIpc — registration + teardown', () => {
  it('registers the installProfile.choose channel and the disposer removes it', () => {
    const { deps } = makeDeps();
    const dispose = registerInstallProfileIpc(deps);
    expect(mocks.handle).toHaveBeenCalledTimes(1);
    expect(mocks.handle.mock.calls[0][0]).toBe(INSTALL_PROFILE_CHOOSE_CHANNEL);
    dispose();
    expect(mocks.removeHandler).toHaveBeenCalledWith(INSTALL_PROFILE_CHOOSE_CHANNEL);
  });

  it('the registered handler delegates to performChooseInstallProfile with the payload', async () => {
    const { deps, resolveChoice } = makeDeps();
    registerInstallProfileIpc(deps);
    const handler = mocks.handle.mock.calls[0][1] as (e: unknown, p: unknown) => Promise<unknown>;
    await expect(handler({}, { profile: 'full' })).resolves.toEqual({ ok: true });
    expect(resolveChoice).toHaveBeenCalledWith('full', []);
  });

  it('the handler tolerates a missing payload (defaults to an undefined profile)', async () => {
    const { deps } = makeDeps({
      resolveChoice: vi.fn(() => {
        throw new InstallProfileError('unknown install profile: undefined');
      }),
    });
    registerInstallProfileIpc(deps);
    const handler = mocks.handle.mock.calls[0][1] as (e: unknown, p: unknown) => Promise<unknown>;
    await expect(handler({}, undefined)).resolves.toMatchObject({ ok: false });
  });
});
