// rpc.test.ts — the typed `client` wrappers map to the FROZEN method names +
// param shapes (P4 §2 / C8). The bridge is mocked via a fake `window.api`, so
// these assert the exact wire calls (method string + params) the renderer makes
// for the P4 shorts gallery + captions.cues live-preview cues.

import { describe, it, expect, vi, afterEach } from 'vitest';

import { client, type ShortInfo, type ShortReexportHint } from './rpc';

// ---------------------------------------------------------------------------
// Install a fake preload bridge so `rpc()` resolves through a spy. The module
// reads `globalThis.window?.api` structurally (no Window augmentation), so we
// set it directly per test.
// ---------------------------------------------------------------------------
function installApi(): ReturnType<typeof vi.fn> {
  const rpc = vi.fn().mockResolvedValue({});
  (globalThis as { window?: { api?: unknown } }).window = {
    api: { rpc, onProgress: vi.fn(() => () => {}) },
  };
  return rpc;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  vi.restoreAllMocks();
});

describe('client.shorts (P4 §2 / C6 / C8)', () => {
  it('list forwards {videoId} only when given', async () => {
    const rpc = installApi();
    await client.shorts.list('v1');
    expect(rpc).toHaveBeenCalledWith('shorts.list', { videoId: 'v1' });
  });

  it('list sends an empty params object when no videoId (lists all)', async () => {
    const rpc = installApi();
    await client.shorts.list();
    expect(rpc).toHaveBeenCalledWith('shorts.list', {});
  });

  it('thumbnail forwards {path}', async () => {
    const rpc = installApi();
    await client.shorts.thumbnail('/out/shorts-v1/clip.mp4');
    expect(rpc).toHaveBeenCalledWith('shorts.thumbnail', { path: '/out/shorts-v1/clip.mp4' });
  });

  it('delete forwards {path}', async () => {
    const rpc = installApi();
    await client.shorts.delete('/out/shorts-v1/clip.mp4');
    expect(rpc).toHaveBeenCalledWith('shorts.delete', { path: '/out/shorts-v1/clip.mp4' });
  });

  it('reexport forwards {path}', async () => {
    const rpc = installApi();
    await client.shorts.reexport('/out/shorts-v1/clip.mp4');
    expect(rpc).toHaveBeenCalledWith('shorts.reexport', { path: '/out/shorts-v1/clip.mp4' });
  });

  it('list resolves the {shorts} envelope it is typed for', async () => {
    const rpc = installApi();
    const info: ShortInfo = {
      id: 'abc',
      path: '/out/shorts-v1/clip.mp4',
      videoId: 'v1',
      sourceTitle: 'Talk',
      template: 'bold',
      viralityPct: 82,
      durationSec: 34,
      width: 1080,
      height: 1920,
      createdAt: 1700000000,
      thumbnailPath: '',
      hook: 'The big idea',
    };
    rpc.mockResolvedValueOnce({ shorts: [info] });
    const res = await client.shorts.list('v1');
    expect(res.shorts[0].viralityPct).toBe(82);
  });

  it('reexport resolves the reopen-in-short-maker hint shape', async () => {
    const rpc = installApi();
    const hint: ShortReexportHint = {
      videoId: 'v1',
      candidate: { hook: 'h', template: 'bold', viralityPct: null, durationSec: 30 },
    };
    rpc.mockResolvedValueOnce(hint);
    const res = await client.shorts.reexport('/out/shorts-v1/clip.mp4');
    expect(res.videoId).toBe('v1');
    expect(res.candidate.template).toBe('bold');
  });
});

describe('client.captions (P4 §2 / C7 / C8)', () => {
  it('cues forwards {videoId} and resolves the {cues} envelope (reuses Cue type)', async () => {
    const rpc = installApi();
    rpc.mockResolvedValueOnce({ cues: [{ index: 1, start: 1.0, end: 1.4, text: 'Hi' }] });
    const res = await client.captions.cues('v1');
    expect(rpc).toHaveBeenCalledWith('captions.cues', { videoId: 'v1' });
    expect(res.cues[0].text).toBe('Hi');
  });
});
