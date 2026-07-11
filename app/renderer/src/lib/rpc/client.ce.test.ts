// client.ce.test.ts — isolated cross-edit (feature-completion reconcile) coverage
// for the client.ts wrappers WIRED in this pass: batch.plan / batch.consent, the
// transcribe.start `alignWords` trigger, the director.apply reviewed-op forwarding,
// and the reframe.* per-shot correction group. Written as a UNIQUELY-named file so
// it never collides with the shared rpc.test.ts / rpc.property.test.ts; coverage is
// per-source-file, so these still count toward client.ts's 100% branch gate.

import { describe, it, expect, vi, afterEach } from 'vitest';

import { client } from './client';
import type { DirectorOpStatus } from './schemas';
import type { ShotOverride, ShotPlan } from '../reframeOverride';

// Install a fake preload bridge so `rpc()` resolves through a spy (mirrors the
// structural `globalThis.window?.api` read the module uses — no Window augment).
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

describe('client.batch.plan (§9.1 consent preview)', () => {
  it('forwards {id, ...opts} when opts are given (the opts ?? {} truthy side)', async () => {
    const rpc = installApi();
    await client.batch.plan('b1', { confirmCloudBudget: true, acknowledged: false });
    expect(rpc).toHaveBeenCalledWith('batch.plan', {
      id: 'b1',
      confirmCloudBudget: true,
      acknowledged: false,
    });
  });

  it('forwards {id} only when opts are omitted (the opts ?? {} falsy side)', async () => {
    const rpc = installApi();
    await client.batch.plan('b1');
    expect(rpc).toHaveBeenCalledWith('batch.plan', { id: 'b1' });
  });
});

describe('client.batch.consent (read-only run/skip preview)', () => {
  it('forwards {id}', async () => {
    const rpc = installApi();
    await client.batch.consent('b1');
    expect(rpc).toHaveBeenCalledWith('batch.consent', { id: 'b1' });
  });
});

describe('client.transcribe.start (alignWords karaoke trigger)', () => {
  it('sends {videoId} only — no language, no alignWords (both conditionals falsy)', async () => {
    const rpc = installApi();
    await client.transcribe.start('v1');
    expect(rpc).toHaveBeenCalledWith('transcribe.start', { videoId: 'v1' });
  });

  it('threads language + alignWords:true when both are supplied (both conditionals truthy)', async () => {
    const rpc = installApi();
    await client.transcribe.start('v1', 'en', true);
    expect(rpc).toHaveBeenCalledWith('transcribe.start', {
      videoId: 'v1',
      language: 'en',
      alignWords: true,
    });
  });

  it('omits alignWords when explicitly false (alignWords falsy, language truthy)', async () => {
    const rpc = installApi();
    await client.transcribe.start('v1', 'fr', false);
    expect(rpc).toHaveBeenCalledWith('transcribe.start', { videoId: 'v1', language: 'fr' });
  });
});

describe('client.director.apply (reviewed-op forwarding)', () => {
  it('forwards opOverrides + order when a review is supplied (confirmBudget undefined, review truthy)', async () => {
    const rpc = installApi();
    const review = {
      opOverrides: [{ id: 'op-2', status: 'dropped' as DirectorOpStatus }],
      order: ['op-1', 'op-2'],
    };
    await client.director.apply('plan-1', undefined, review);
    expect(rpc).toHaveBeenCalledWith('director.apply', {
      planId: 'plan-1',
      opOverrides: review.opOverrides,
      order: review.order,
    });
  });

  it('forwards confirmBudget and NO review keys when review is absent (confirmBudget defined, review falsy)', async () => {
    const rpc = installApi();
    await client.director.apply('plan-1', 'usd_500');
    expect(rpc).toHaveBeenCalledWith('director.apply', {
      planId: 'plan-1',
      confirmBudget: 'usd_500',
    });
  });
});

describe('client.reframe.* (V1.1 Lane R per-shot correction)', () => {
  it('shotPlan forwards {trace, sourceWidth, sourceHeight, fps}', async () => {
    const rpc = installApi();
    const trace = { shots: [] };
    await client.reframe.shotPlan({ trace, sourceWidth: 1920, sourceHeight: 1080, fps: 30 });
    expect(rpc).toHaveBeenCalledWith('reframe.shotPlan', {
      trace,
      sourceWidth: 1920,
      sourceHeight: 1080,
      fps: 30,
    });
  });

  it('applyOverrides forwards {plan, overrides}', async () => {
    const rpc = installApi();
    const plan: ShotPlan = { sourceWidth: 1920, sourceHeight: 1080, fps: 30, shots: [] };
    const overrides: ShotOverride[] = [{ index: 0, speaker: 'spk-1' }];
    await client.reframe.applyOverrides({ plan, overrides });
    expect(rpc).toHaveBeenCalledWith('reframe.applyOverrides', { plan, overrides });
  });
});
