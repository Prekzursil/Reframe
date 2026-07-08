// lineageActionsClient.test.ts — the rpc/bridge-backed L5 action slice wiring.
// Covers: each rpc forward (reveal/regenerate/relink/runRegenerate incl. the
// null-params fallback) and the fail-soft bridge adapters (openInFolder /
// pickRelinkTarget) across present/absent/empty bridge shapes.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { lineageActions } from './lineageActionsClient';

const rpcMock = vi.fn();

type TestWindow = Window & { api?: unknown };

function installBridge(overrides: Record<string, unknown> = {}): void {
  (window as TestWindow).api = {
    rpc: (...args: unknown[]) => rpcMock(...args),
    onProgress: () => () => {},
    ...overrides,
  };
}

beforeEach(() => {
  rpcMock.mockReset();
  rpcMock.mockResolvedValue(undefined);
  installBridge();
});

afterEach(() => {
  delete (window as { api?: unknown }).api;
});

describe('lineageActions — rpc forwards', () => {
  it('reveal / regenerate / relink forward their params', async () => {
    await lineageActions.reveal('v1');
    expect(rpcMock).toHaveBeenCalledWith('library.reveal', { id: 'v1' });
    await lineageActions.regenerate('v1');
    expect(rpcMock).toHaveBeenCalledWith('library.regenerate', { id: 'v1' });
    await lineageActions.relink('v1', '/new.mp4');
    expect(rpcMock).toHaveBeenCalledWith('library.relink', { id: 'v1', path: '/new.mp4' });
  });

  it('pinHash forwards the id (WU-1f relink baseline)', async () => {
    await lineageActions.pinHash('v1');
    expect(rpcMock).toHaveBeenCalledWith('library.pinHash', { id: 'v1' });
  });

  it('runRegenerate re-dispatches the op with its params', async () => {
    await lineageActions.runRegenerate({
      id: 'v1',
      op: 'shorts.select',
      params: { preset: 'punchy' },
      missing: [],
      ready: true,
    });
    expect(rpcMock).toHaveBeenCalledWith('shorts.select', { preset: 'punchy' });
  });

  it('runRegenerate falls back to {} when params is null', async () => {
    await lineageActions.runRegenerate({
      id: 'v1',
      op: 'shorts.select',
      params: null,
      missing: [],
      ready: true,
    });
    expect(rpcMock).toHaveBeenCalledWith('shorts.select', {});
  });
});

describe('lineageActions — managed keep-a-copy slice (WU-3b2)', () => {
  it('status forwards to library.managedStatus', async () => {
    rpcMock.mockResolvedValue({ sizeBytes: 0, capBytes: 1, count: 0, entries: [] });
    await lineageActions.managed!.status();
    expect(rpcMock).toHaveBeenCalledWith('library.managedStatus', undefined);
  });

  it('keep forwards the id and UNWRAPS the {managed} envelope', async () => {
    const managed = { entityId: 'v1', originalPath: '/o.mp4', managedPath: '/m.mp4' };
    rpcMock.mockResolvedValue({ managed });
    const row = await lineageActions.managed!.keep('v1');
    expect(rpcMock).toHaveBeenCalledWith('library.keepCopy', { id: 'v1' });
    expect(row).toBe(managed);
  });

  it('evict forwards the id to library.managedEvict', async () => {
    await lineageActions.managed!.evict('v1');
    expect(rpcMock).toHaveBeenCalledWith('library.managedEvict', { id: 'v1' });
  });
});

describe('lineageActions — openInFolder (fail-soft)', () => {
  it('delegates to the bridge when present', async () => {
    const openInFolder = vi.fn(async () => true);
    installBridge({ openInFolder });
    expect(await lineageActions.openInFolder!('/p.mp4')).toBe(true);
    expect(openInFolder).toHaveBeenCalledWith('/p.mp4');
  });

  it('returns false when the bridge lacks openInFolder', async () => {
    installBridge(); // no openInFolder
    expect(await lineageActions.openInFolder!('/p.mp4')).toBe(false);
  });

  it('returns false when there is no window.api at all', async () => {
    delete (window as { api?: unknown }).api;
    expect(await lineageActions.openInFolder!('/p.mp4')).toBe(false);
  });
});

describe('lineageActions — pickRelinkTarget (fail-soft)', () => {
  it('returns the first picked path', async () => {
    installBridge({ openVideos: vi.fn(async () => ['/a.mp4', '/b.mp4']) });
    expect(await lineageActions.pickRelinkTarget!()).toBe('/a.mp4');
  });

  it('returns null when the picker yields nothing', async () => {
    installBridge({ openVideos: vi.fn(async () => []) });
    expect(await lineageActions.pickRelinkTarget!()).toBeNull();
  });

  it('returns null on a non-array picker result', async () => {
    installBridge({ openVideos: vi.fn(async () => null as unknown as string[]) });
    expect(await lineageActions.pickRelinkTarget!()).toBeNull();
  });

  it('returns null when the bridge lacks openVideos', async () => {
    installBridge(); // no openVideos
    expect(await lineageActions.pickRelinkTarget!()).toBeNull();
  });
});
