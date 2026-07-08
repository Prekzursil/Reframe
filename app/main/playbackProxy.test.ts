// Tests for playbackProxy.ts (WU B3): the single-flight, bounded, loud-failure
// playback-proxy orchestration that sits between the mstream resolver and the
// sidecar's media.playable / media.proxy.start. Every seam is injected, so no
// Electron app, sidecar, or ffmpeg ever runs.
import { describe, it, expect, vi } from 'vitest';
import { PlaybackProxy, type PlayableVerdict, type PlaybackProxyDeps } from './playbackProxy';
import {
  ProxyBuildFailedError,
  ProxyBuildingError,
  SidecarUnavailableError,
} from './mediaProtocol';

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** A captured timer so the bounded-await deadline is fired by hand (no wall clock). */
interface CapturedTimer {
  fn: () => void;
  ms: number;
  cancel: ReturnType<typeof vi.fn>;
}

function makeDeps(overrides: Partial<PlaybackProxyDeps> = {}): {
  deps: PlaybackProxyDeps;
  notify: ReturnType<typeof vi.fn>;
  timers: CapturedTimer[];
} {
  const notify = vi.fn();
  const timers: CapturedTimer[] = [];
  const deps: PlaybackProxyDeps = {
    probePlayable: vi.fn(
      async () => ({ playable: false, reason: 'needs proxy' }) as PlayableVerdict,
    ),
    buildProxy: vi.fn(async () => '/proxies/v1.mp4'),
    resolveOriginal: vi.fn(async () => '/library/v1.mkv'),
    isPlayableFile: vi.fn(async () => true),
    notify,
    timeoutMs: 5_000,
    setTimer: (fn, ms) => {
      const cancel = vi.fn();
      timers.push({ fn, ms, cancel });
      return cancel;
    },
    ...overrides,
  };
  return { deps, notify, timers };
}

/** Let queued microtasks (the probe/build promise chains) settle. */
async function tick(): Promise<void> {
  for (let i = 0; i < 6; i++) {
    // eslint-disable-next-line no-await-in-loop
    await Promise.resolve();
  }
}

describe('PlaybackProxy.resolve — verdict short-circuits', () => {
  it('returns a valid cached proxy path without building, notifying a DEFINITIVE direct verdict', async () => {
    const { deps, notify } = makeDeps({
      probePlayable: vi.fn(async () => ({ playable: true, proxyPath: '/cache/v1.mp4' })),
      isPlayableFile: vi.fn(async () => true),
    });
    const proxy = new PlaybackProxy(deps);
    expect(await proxy.resolve('v1')).toBe('/cache/v1.mp4');
    expect(deps.buildProxy).not.toHaveBeenCalled();
    expect(deps.resolveOriginal).not.toHaveBeenCalled();
    // WU-1e-fix: the resolver DECIDED the cached proxy is playable — announce it
    // so the renderer advances past 'initial' and a later genuine decode error
    // goes LOUD instead of masking behind a "Building preview…" placeholder.
    expect(notify).toHaveBeenCalledWith('v1', 'direct', '/cache/v1.mp4');
  });

  it('ignores a stale (non-playable-file) cached proxyPath and returns the original, notifying direct with the ORIGINAL path', async () => {
    const { deps, notify } = makeDeps({
      probePlayable: vi.fn(async () => ({ playable: true, proxyPath: '/cache/gone.mp4' })),
      isPlayableFile: vi.fn(async () => false),
      resolveOriginal: vi.fn(async () => '/library/v1.mp4'),
    });
    const proxy = new PlaybackProxy(deps);
    expect(await proxy.resolve('v1')).toBe('/library/v1.mp4');
    expect(deps.buildProxy).not.toHaveBeenCalled();
    // The stale proxyPath is NOT announced — the actually-served original is.
    expect(notify).toHaveBeenCalledWith('v1', 'direct', '/library/v1.mp4');
    expect(notify).not.toHaveBeenCalledWith('v1', 'direct', '/cache/gone.mp4');
  });

  it('returns the original path when playable with no cached proxy, notifying a direct verdict', async () => {
    const { deps, notify } = makeDeps({
      probePlayable: vi.fn(async () => ({ playable: true })),
      resolveOriginal: vi.fn(async () => '/library/v1.mp4'),
    });
    const proxy = new PlaybackProxy(deps);
    expect(await proxy.resolve('v1')).toBe('/library/v1.mp4');
    expect(deps.buildProxy).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith('v1', 'direct', '/library/v1.mp4');
  });

  it('returns null when playable but the original is unknown (-> 404 upstream), notifying NOTHING (no source to decode)', async () => {
    const { deps, notify } = makeDeps({
      probePlayable: vi.fn(async () => ({ playable: true })),
      resolveOriginal: vi.fn(async () => null),
    });
    const proxy = new PlaybackProxy(deps);
    expect(await proxy.resolve('v1')).toBeNull();
    // A 404 has nothing to decode — a 'direct' verdict would be a lie.
    expect(notify).not.toHaveBeenCalled();
  });
});

describe('PlaybackProxy.resolve — build path', () => {
  it('builds a proxy when not playable: notifies building then ready, returns the built path', async () => {
    const { deps, notify } = makeDeps({
      buildProxy: vi.fn(async () => '/proxies/v1.mp4'),
    });
    const proxy = new PlaybackProxy(deps);
    expect(await proxy.resolve('v1')).toBe('/proxies/v1.mp4');
    expect(deps.buildProxy).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenNthCalledWith(1, 'v1', 'building', 'needs proxy');
    expect(notify).toHaveBeenNthCalledWith(2, 'v1', 'ready', '/proxies/v1.mp4');
  });

  it('falls back to a default building detail when the verdict carries no reason', async () => {
    const { deps, notify } = makeDeps({
      probePlayable: vi.fn(async () => ({ playable: false })),
    });
    const proxy = new PlaybackProxy(deps);
    await proxy.resolve('v1');
    expect(notify).toHaveBeenNthCalledWith(1, 'v1', 'building', 'building playback proxy');
  });

  it('cancels the bounded-await timer once the build wins the race', async () => {
    const { deps, timers } = makeDeps();
    const proxy = new PlaybackProxy(deps);
    await proxy.resolve('v1');
    expect(timers).toHaveLength(1);
    expect(timers[0].cancel).toHaveBeenCalledTimes(1);
  });

  it('single-flights concurrent resolves for one videoId (exactly ONE build)', async () => {
    const build = deferred<string>();
    const buildProxy = vi.fn(() => build.promise);
    const { deps } = makeDeps({ buildProxy });
    const proxy = new PlaybackProxy(deps);

    const a = proxy.resolve('v1');
    const b = proxy.resolve('v1');
    await tick();
    expect(buildProxy).toHaveBeenCalledTimes(1);

    build.resolve('/proxies/v1.mp4');
    expect(await a).toBe('/proxies/v1.mp4');
    expect(await b).toBe('/proxies/v1.mp4');
  });

  it('rebuilds after a prior build settled (in-flight entry cleared)', async () => {
    const buildProxy = vi.fn(async () => '/proxies/v1.mp4');
    const { deps } = makeDeps({ buildProxy });
    const proxy = new PlaybackProxy(deps);
    await proxy.resolve('v1');
    await proxy.resolve('v1');
    expect(buildProxy).toHaveBeenCalledTimes(2);
  });
});

describe('PlaybackProxy.resolve — loud failure + transient building', () => {
  it('surfaces a build failure as ProxyBuildFailedError and notifies error (no raw fallback)', async () => {
    const { deps, notify } = makeDeps({
      buildProxy: vi.fn(async () => {
        throw new Error('ffmpeg exited with code 1');
      }),
    });
    const proxy = new PlaybackProxy(deps);
    await expect(proxy.resolve('v1')).rejects.toBeInstanceOf(ProxyBuildFailedError);
    await expect(proxy.resolve('v1')).rejects.toThrow('ffmpeg exited with code 1');
    expect(notify).toHaveBeenCalledWith('v1', 'error', 'ffmpeg exited with code 1');
    // NEVER resolves to the raw original when the proxy build fails.
    expect(deps.resolveOriginal).not.toHaveBeenCalled();
  });

  it('stringifies a non-Error build rejection in the failure message', async () => {
    const { deps, notify } = makeDeps({
      buildProxy: vi.fn(() => Promise.reject('boom-string')),
    });
    const proxy = new PlaybackProxy(deps);
    await expect(proxy.resolve('v1')).rejects.toThrow('boom-string');
    expect(notify).toHaveBeenCalledWith('v1', 'error', 'boom-string');
  });

  it('propagates a SidecarUnavailableError from the build unwrapped (transient 503)', async () => {
    const { deps } = makeDeps({
      buildProxy: vi.fn(async () => {
        throw new SidecarUnavailableError('sidecar restarting');
      }),
    });
    const proxy = new PlaybackProxy(deps);
    await expect(proxy.resolve('v1')).rejects.toBeInstanceOf(SidecarUnavailableError);
  });

  it('propagates a SidecarUnavailableError from the playable probe (does not build)', async () => {
    const { deps } = makeDeps({
      probePlayable: vi.fn(async () => {
        throw new SidecarUnavailableError('sidecar down');
      }),
    });
    const proxy = new PlaybackProxy(deps);
    await expect(proxy.resolve('v1')).rejects.toBeInstanceOf(SidecarUnavailableError);
    expect(deps.buildProxy).not.toHaveBeenCalled();
  });

  it('throws ProxyBuildingError when the build outruns the bound; a later resolve reuses the in-flight build', async () => {
    const build = deferred<string>();
    const buildProxy = vi.fn(() => build.promise);
    const { deps, timers } = makeDeps({ buildProxy });
    const proxy = new PlaybackProxy(deps);

    const first = proxy.resolve('v1');
    await tick();
    expect(timers).toHaveLength(1);
    // Deadline fires while the build is still in flight -> transient building.
    timers[0].fn();
    await expect(first).rejects.toBeInstanceOf(ProxyBuildingError);

    // A retry reuses the SAME in-flight build (no duplicate transcode).
    const second = proxy.resolve('v1');
    await tick();
    expect(buildProxy).toHaveBeenCalledTimes(1);

    build.resolve('/proxies/v1.mp4');
    expect(await second).toBe('/proxies/v1.mp4');
  });
});
