// client.audiomix.ce.test.ts — isolated cross-edit coverage for the `audiomix.*`
// client wrappers added in this pass (the A/V mixer: sidechain auto-duck + EBU
// R128 loudness normalization). Uniquely named so it never collides with the
// sibling rpc suites; coverage is per-source-file, so these still count toward
// client.ts's 100% branch gate.
//
// Both wrappers are deliberately BRANCH-FREE (a single spread): a long job's
// params are forwarded unconditionally, and `JSON.stringify` drops `undefined`
// keys on the wire, so the sidecar sees exactly the fields the caller set. This
// mirrors the `index.*` group's documented rationale in client.ts.

import { describe, it, expect, vi, afterEach } from 'vitest';

import { client } from './client';

/** Install a fake preload bridge so `rpc()` resolves through a spy. */
function installApi(): ReturnType<typeof vi.fn> {
  const rpc = vi.fn().mockResolvedValue({ jobId: 'job-1' });
  (globalThis as { window?: { api?: unknown } }).window = {
    api: { rpc, onProgress: vi.fn(() => () => {}) },
  };
  return rpc;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  vi.restoreAllMocks();
});

describe('client.audiomix.merge (bed under speaker + auto-duck + loudnorm)', () => {
  it('forwards the full tunable set verbatim', async () => {
    const rpc = installApi();
    await client.audiomix.merge({
      videoId: 'v1',
      bgPath: 'C:/music/bed.mp3',
      bgGainDb: -12,
      duckThreshold: 0.05,
      duckRatio: 6,
      platform: 'tiktok',
    });
    expect(rpc).toHaveBeenCalledWith('audiomix.merge', {
      videoId: 'v1',
      bgPath: 'C:/music/bed.mp3',
      bgGainDb: -12,
      duckThreshold: 0.05,
      duckRatio: 6,
      platform: 'tiktok',
    });
  });

  it('forwards a by-path target with only the required bgPath (engine defaults apply)', async () => {
    const rpc = installApi();
    await client.audiomix.merge({ path: 'C:/clips/talk.mp4', bgPath: 'C:/music/bed.mp3' });
    expect(rpc).toHaveBeenCalledWith('audiomix.merge', {
      path: 'C:/clips/talk.mp4',
      bgPath: 'C:/music/bed.mp3',
    });
  });

  it('resolves the {jobId} handle (a LONG job — {path} arrives on job.done)', async () => {
    installApi();
    await expect(
      client.audiomix.merge({ videoId: 'v1', bgPath: 'C:/music/bed.mp3' }),
    ).resolves.toEqual({ jobId: 'job-1' });
  });
});

describe('client.audiomix.normalize (EBU R128 loudnorm only, no bed)', () => {
  it('forwards {videoId, platform}', async () => {
    const rpc = installApi();
    await client.audiomix.normalize({ videoId: 'v1', platform: 'ebu' });
    expect(rpc).toHaveBeenCalledWith('audiomix.normalize', { videoId: 'v1', platform: 'ebu' });
  });

  it('forwards an explicit loudnessTarget override alongside the platform', async () => {
    const rpc = installApi();
    await client.audiomix.normalize({ videoId: 'v1', platform: 'atsc', loudnessTarget: -24 });
    expect(rpc).toHaveBeenCalledWith('audiomix.normalize', {
      videoId: 'v1',
      platform: 'atsc',
      loudnessTarget: -24,
    });
  });
});
