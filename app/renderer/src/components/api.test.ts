// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest';
import { rpc, onProgress, hasApi } from './api';

afterEach(() => {
  // Clean the injected bridge between tests.
  delete (window as { api?: unknown }).api;
});

describe('api bridge helpers', () => {
  it('hasApi reflects bridge presence', () => {
    expect(hasApi()).toBe(false);
    (window as { api?: unknown }).api = { rpc: vi.fn(), onProgress: vi.fn() };
    expect(hasApi()).toBe(true);
  });

  it('rpc forwards method + params to window.api.rpc', async () => {
    const rpcFn = vi.fn().mockResolvedValue({ ok: true });
    (window as { api?: unknown }).api = { rpc: rpcFn, onProgress: vi.fn() };
    const res = await rpc('library.list');
    expect(rpcFn).toHaveBeenCalledWith('library.list', undefined);
    expect(res).toEqual({ ok: true });

    await rpc('library.add', { path: '/a.mp4' });
    expect(rpcFn).toHaveBeenCalledWith('library.add', { path: '/a.mp4' });
  });

  it('onProgress forwards the callback and returns the unsubscribe', () => {
    const unsub = vi.fn();
    const onProgFn = vi.fn().mockReturnValue(unsub);
    (window as { api?: unknown }).api = { rpc: vi.fn(), onProgress: onProgFn };
    const cb = () => {};
    const returned = onProgress(cb);
    expect(onProgFn).toHaveBeenCalledWith(cb);
    expect(returned).toBe(unsub);
  });

  it('rpc throws a clear error when the bridge is absent', () => {
    expect(() => rpc('ping')).toThrow(/window\.api bridge is not available/);
  });
});
