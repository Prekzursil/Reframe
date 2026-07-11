// parity.test.ts — proves the GENERATED client wrappers produce byte-identical
// JSON-RPC wire calls to the hand-written client.ts for the v1.5 POC slice, and
// that the generated needsKeyInjection predicate covers both branches. This is
// the round-trip parity evidence: same method name + same params object, so the
// generated client can replace the hand-written wrappers with zero wire change.

import { afterEach, describe, expect, it, vi } from 'vitest';

import { client } from '../client';
import { clientGenerated } from './client.generated';
import { needsKeyInjection } from './needsKeyInjection.generated';

/** Install a fake preload bridge whose `rpc` is a spy (mirrors client.ce.test.ts). */
function installApi(): ReturnType<typeof vi.fn> {
  const rpc = vi.fn().mockResolvedValue({});
  (globalThis as { window?: { api?: unknown } }).window = {
    api: { rpc, onProgress: vi.fn(() => () => {}) },
  };
  return rpc;
}

/** Invoke `call`, returning the single `rpc(method, params)` wire call it produced. */
async function wireOf(call: () => Promise<unknown>): Promise<unknown[]> {
  const rpc = installApi();
  await call();
  return rpc.mock.lastCall as unknown[];
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  vi.restoreAllMocks();
});

describe('generated client <-> hand-written client wire parity (POC slice)', () => {
  it('ping — identical, no params arg', async () => {
    const hand = await wireOf(() => client.ping());
    const gen = await wireOf(() => clientGenerated.ping());
    expect(gen).toEqual(hand);
    // The shared rpc() runtime forwards `params` (undefined here) to the bridge,
    // so a no-param method reaches the bridge spy as [method, undefined].
    expect(gen).toEqual(['ping', undefined]);
  });

  it('library.add — { path }', async () => {
    const hand = await wireOf(() => client.library.add('/videos/a.mp4'));
    const gen = await wireOf(() => clientGenerated.library.add('/videos/a.mp4'));
    expect(gen).toEqual(hand);
    expect(gen).toEqual(['library.add', { path: '/videos/a.mp4' }]);
  });

  it('settings.get — no params arg', async () => {
    const hand = await wireOf(() => client.settings.get());
    const gen = await wireOf(() => clientGenerated.settings.get());
    expect(gen).toEqual(hand);
    expect(gen).toEqual(['settings.get', undefined]);
  });

  it('settings.set — the values object is forwarded verbatim', async () => {
    const values = { useCloud: true, activePreset: 'balanced' };
    const hand = await wireOf(() => client.settings.set(values));
    const gen = await wireOf(() => clientGenerated.settings.set(values));
    expect(gen).toEqual(hand);
    expect(gen).toEqual(['settings.set', values]);
  });

  it('shortmaker.select — { videoId, prompt, controls } (a key-injection method)', async () => {
    const controls = { count: 3, aspect: '9:16' };
    const hand = await wireOf(() => client.shortmaker.select('v1', 'best bits', controls));
    const gen = await wireOf(() => clientGenerated.shortmaker.select('v1', 'best bits', controls));
    expect(gen).toEqual(hand);
    expect(gen).toEqual(['shortmaker.select', { videoId: 'v1', prompt: 'best bits', controls }]);
  });

  it('providers.revealKey — default index 0 (a key-injection method)', async () => {
    const hand = await wireOf(() => client.providers.revealKey('openrouter'));
    const gen = await wireOf(() => clientGenerated.providers.revealKey('openrouter'));
    expect(gen).toEqual(hand);
    expect(gen).toEqual(['providers.revealKey', { id: 'openrouter', index: 0 }]);
  });

  it('providers.revealKey — explicit index threads through', async () => {
    const hand = await wireOf(() => client.providers.revealKey('openrouter', 2));
    const gen = await wireOf(() => clientGenerated.providers.revealKey('openrouter', 2));
    expect(gen).toEqual(hand);
    expect(gen).toEqual(['providers.revealKey', { id: 'openrouter', index: 2 }]);
  });
});

describe('generated needsKeyInjection predicate', () => {
  it('classifies the two key-injection methods true, the rest false', () => {
    expect(needsKeyInjection('shortmaker.select')).toBe(true);
    expect(needsKeyInjection('providers.revealKey')).toBe(true);
    expect(needsKeyInjection('ping')).toBe(false);
    expect(needsKeyInjection('library.add')).toBe(false);
    expect(needsKeyInjection('settings.get')).toBe(false);
    expect(needsKeyInjection('settings.set')).toBe(false);
  });
});
