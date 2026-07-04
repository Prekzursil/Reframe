// playbackProxy.ts — the single-flight, bounded, loud-failure playback-proxy
// orchestration behind the mstream resolver (WU B3).
//
// WHY: before this, the resolver streamed the ORIGINAL library file whenever a
// cached proxy was not yet on disk. For a non-Chromium-decodable source (HEVC,
// WMV, MPEG-2, mkv/HEVC, ...) that made the <video> tag fail with "media error
// code 4" — and a swallowed proxy-build failure left the app silently
// centre-cropping the undecodable source forever.
//
// This module makes the resolver AUTHORITATIVE for playability:
//   * a valid cached proxy is served immediately;
//   * a directly-playable source serves its original path;
//   * a NON-playable source triggers the sidecar proxy build, guarded by a
//     SINGLE-FLIGHT map keyed by videoId so concurrent <video> range requests
//     for one id can never kick duplicate transcodes, and AWAITED with a bound
//     so the request never hangs unbounded;
//   * the build is surfaced to the renderer as an explicit "building" -> "ready"
//     / "error" state (the `notify` seam), and a build FAILURE throws loudly
//     (ProxyBuildFailedError -> HTTP 502) instead of falling back to the raw,
//     undecodable original.
//
// Every I/O seam is injected (the mstream handler wires the real sidecar RPC +
// fs), so the orchestration is unit-tested with no Electron/sidecar/ffmpeg.
import { ProxyBuildFailedError, ProxyBuildingError, SidecarUnavailableError } from './mediaProtocol';

/** The `media.playable` verdict shape the resolver consumes. */
export interface PlayableVerdict {
  /** True when the source (or its cached derivative) plays directly in Chromium. */
  playable: boolean;
  /** A cached remux/proxy path when one already exists (playable:true carries it). */
  proxyPath?: string;
  /** Human-readable reason the source is not directly playable (shown as the note). */
  reason?: string;
}

/** The build lifecycle surfaced to the renderer over the proxy-state channel. */
export type ProxyBuildState = 'building' | 'ready' | 'error';

/** A one-shot timer cancel handle (returned by {@link PlaybackProxyDeps.setTimer}). */
export type CancelTimer = () => void;

export interface PlaybackProxyDeps {
  /** Ask the sidecar whether a videoId plays directly (`media.playable`). */
  probePlayable: (videoId: string) => Promise<PlayableVerdict>;
  /**
   * Build the playback proxy and resolve with its absolute path
   * (`media.proxy.start` + await the job's terminal result). Rejecting means
   * the build failed; the single-flight guard lives ABOVE this, so one call =
   * one transcode.
   */
  buildProxy: (videoId: string) => Promise<string>;
  /** Resolve a videoId to the ORIGINAL library file path (or null if unknown). */
  resolveOriginal: (videoId: string) => Promise<string | null>;
  /** True when a cached proxyPath exists on disk AND is a decodable container. */
  isPlayableFile: (path: string) => Promise<boolean>;
  /** Push a build-state transition to the renderer (proxy-state channel). */
  notify: (videoId: string, state: ProxyBuildState, detail: string) => void;
  /** The bounded-await deadline (ms) after which a still-running build is transient. */
  timeoutMs: number;
  /** One-shot timer seam (default `setTimeout`); injectable so the bound is testable. */
  setTimer?: (fn: () => void, ms: number) => CancelTimer;
}

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function defaultSetTimer(fn: () => void, ms: number): CancelTimer {
  const handle = setTimeout(fn, ms);
  // Never keep the event loop alive just for a proxy-build deadline.
  handle.unref?.();
  return () => clearTimeout(handle);
}

/**
 * Orchestrates playability resolution + single-flight, bounded proxy building.
 * One instance is held by the mstream handler for the whole app lifetime; its
 * in-flight map is what dedupes concurrent builds.
 */
export class PlaybackProxy {
  private readonly inflight = new Map<string, Promise<string>>();
  private readonly setTimer: (fn: () => void, ms: number) => CancelTimer;

  constructor(private readonly deps: PlaybackProxyDeps) {
    this.setTimer = deps.setTimer ?? defaultSetTimer;
  }

  /**
   * Resolve the PLAYABLE path for a library videoId, building a proxy first when
   * the source cannot be decoded. Returns the path to stream, or null when the
   * id is unknown (-> 404 upstream). Throws:
   *   * {@link SidecarUnavailableError} — the sidecar could not answer (transient 503);
   *   * {@link ProxyBuildingError}       — build still running past the bound (transient 503);
   *   * {@link ProxyBuildFailedError}    — build failed (loud 502).
   */
  async resolve(videoId: string): Promise<string | null> {
    const verdict = await this.deps.probePlayable(videoId);
    // A cached remux/proxy wins — but only if it truly exists + is decodable
    // (a stale/half-written verdict.proxyPath must never be served).
    if (verdict.proxyPath && (await this.deps.isPlayableFile(verdict.proxyPath))) {
      return verdict.proxyPath;
    }
    // Directly playable source (no proxy needed): stream the original file.
    if (verdict.playable) {
      return this.deps.resolveOriginal(videoId);
    }
    // Not playable + no cached proxy: build one (single-flight) and await it.
    this.deps.notify(videoId, 'building', verdict.reason ?? 'building playback proxy');
    return this.awaitBounded(videoId, this.singleFlight(videoId));
  }

  /**
   * Return the in-flight build for `videoId`, starting one only if none exists.
   * The stored promise notifies 'ready'/'error' exactly once and evicts itself
   * from the map on settle, so a later request rebuilds a fresh derivative.
   */
  private singleFlight(videoId: string): Promise<string> {
    const existing = this.inflight.get(videoId);
    if (existing) return existing;
    const build = this.deps
      .buildProxy(videoId)
      .then(
        (path) => {
          this.deps.notify(videoId, 'ready', path);
          return path;
        },
        (err: unknown) => {
          this.deps.notify(videoId, 'error', messageOf(err));
          throw err;
        },
      )
      .finally(() => {
        this.inflight.delete(videoId);
      });
    // Mark the shared build "handled": a caller that timed out (ProxyBuildingError)
    // stops awaiting it, and without this its eventual rejection would surface as
    // an unhandled promise rejection. Real awaiters still observe the rejection.
    void build.catch(() => undefined);
    this.inflight.set(videoId, build);
    return build;
  }

  /**
   * Await `build` up to `timeoutMs`. A win returns the path; a rejection becomes
   * a loud {@link ProxyBuildFailedError} (unless it is already a transient
   * Sidecar/Proxy error, which passes through); the deadline yields a transient
   * {@link ProxyBuildingError} while the build keeps running in the background.
   */
  private awaitBounded(videoId: string, build: Promise<string>): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      let settled = false;
      const cancel = this.setTimer(() => {
        if (settled) return;
        settled = true;
        reject(new ProxyBuildingError(`playback proxy still building for ${videoId}`));
      }, this.deps.timeoutMs);
      build.then(
        (path) => {
          if (settled) return;
          settled = true;
          cancel();
          resolve(path);
        },
        (err: unknown) => {
          if (settled) return;
          settled = true;
          cancel();
          if (err instanceof ProxyBuildingError || err instanceof SidecarUnavailableError) {
            reject(err);
          } else {
            reject(new ProxyBuildFailedError(messageOf(err)));
          }
        },
      );
    });
  }
}
