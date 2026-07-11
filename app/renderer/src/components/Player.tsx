// Player.tsx — the real HTML5 video player (P2 U1).
//
// Plays library media over the privileged `mstream://` protocol (served with
// HTTP Range support by app/main/mediaProtocol.ts), or any direct `src` the
// caller already has (e.g. a converted file or an explicit proxy URL).
//
// Two modes:
//   * full playback — plain <video> with native controls (Workspace player);
//   * window mode — `window={{start, end}}` (source-absolute seconds, i.e.
//     a Candidate's `sourceStart` .. `sourceStart + durationSec`): the player
//     seeks to `start` once metadata is available and stops (or loops) at
//     `end`, so ShortMaker can preview a candidate's exact cut.
//
// An imperative handle (play/pause/seek/scrub/currentTime/isPlaying/element)
// is exposed via ref for keyboard-review and timeline click-to-seek callers.
//
// The window math (`clampToWindow` / `windowEndReached`) and the URL builder
// (`mediaUrl` / `resolveSrc`) are exported pure functions, unit-tested in
// Player.test.tsx.
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import './player.css';

// CONTRACT-NOTE: scheme + host mirror app/main/mediaProtocol.ts (MEDIA_SCHEME /
// MEDIA_HOST). The renderer must not import a main-process module, so the tiny
// constants are duplicated here; the URL SHAPE is the frozen seam.
const MEDIA_SCHEME = 'mstream';
const MEDIA_HOST = 'media';

/**
 * Tolerance (seconds) for declaring the window end reached. `timeupdate`
 * fires only a few times per second, so an exact `>= end` comparison would
 * routinely overshoot; the epsilon keeps the stop tight without re-encoding.
 */
export const WINDOW_END_EPSILON = 0.05;

/** An in/out playback window in SOURCE-absolute seconds (see Candidate §3). */
export interface PlayerWindow {
  /** Window start in the source video (a candidate's `sourceStart`). */
  start: number;
  /** Window end in the source video (`sourceStart + durationSec`). */
  end: number;
}

/** The imperative surface exposed through `ref`. */
export interface PlayerHandle {
  /** Begin/resume playback (resolves play() rejections silently). */
  play(): void;
  /** Pause playback. */
  pause(): void;
  /** Seek to an absolute source time (clamped into the window when set). */
  seek(timeSec: number): void;
  /** Alias of seek for scrub-bar drags (same clamping). */
  scrub(timeSec: number): void;
  /** The current playback position (source-absolute seconds). */
  currentTime(): number;
  /** True while actively playing (not paused, not ended). */
  isPlaying(): boolean;
  /** The underlying <video> element (null before mount). */
  element(): HTMLVideoElement | null;
}

export interface PlayerProps {
  /** Library video id — played as `mstream://media/<id>`. */
  videoId?: string;
  /** Direct source override (converted file, explicit proxy URL, blob, ...). Wins over videoId. */
  src?: string;
  /** In/out window for candidate preview (source-absolute seconds). */
  window?: PlayerWindow | null;
  /** In window mode: loop back to `start` instead of stopping at `end`. */
  loop?: boolean;
  /** Start playing as soon as possible (window mode: after the initial seek). */
  autoPlay?: boolean;
  /** Show native controls (default true). */
  controls?: boolean;
  muted?: boolean;
  className?: string;
  /**
   * Bump this to force the <video> to RE-FETCH the same `src` WITHOUT remounting
   * the element (shake-free proxy swap). When the Workspace/ShortMaker proxy build
   * finishes, the mstream URL is unchanged but now resolves to the cached proxy;
   * incrementing `reloadToken` calls `video.load()` so Chromium re-requests it,
   * keeping the element (and its listeners/handle) alive instead of a key-remount
   * that visibly restarts the player.
   */
  reloadToken?: number;
  /** Fired on every timeupdate with the source-absolute position. */
  onTimeUpdate?: (timeSec: number) => void;
  /** Fired when playback ends — including a window-mode stop at `end`. */
  onEnded?: () => void;
  /**
   * Fired when the <video> raises a load/decode `error` (e.g. the mstream
   * resolver 404s or Chromium cannot decode the source). Surfaces the failure to
   * the caller so a blank frame is explained instead of silently shown.
   */
  onError?: (message: string) => void;
}

/** Build the playback URL for a library videoId (see mediaProtocol.ts). */
export function mediaUrl(videoId: string): string {
  return `${MEDIA_SCHEME}://${MEDIA_HOST}/${encodeURIComponent(videoId)}`;
}

/**
 * P4 (§6, C10): the playback URL for an EXPORTED short clip (not a library
 * video). Rides the mstream:// protocol with the `short:<absolute path>` id
 * form, which main.ts resolves inside the exports root (traversal-guarded).
 * Clones the `dubMediaUrl` pattern: the prefixed path stays a single encoded
 * path segment so `videoIdFromUrl` decodes it intact.
 */
export function shortMediaUrl(path: string): string {
  return `${MEDIA_SCHEME}://${MEDIA_HOST}/${encodeURIComponent(`short:${path}`)}`;
}

/**
 * UX/QoL (WU-4): the `<img src>` URL for a SOURCE-library poster frame. Rides
 * the mstream:// protocol with the `thumb:<absolute path>` id form, which
 * main.ts resolves ONLY inside the thumbnails root (traversal-guarded, WU-3).
 * Mirrors `shortMediaUrl` exactly — the prefixed path stays a single encoded
 * segment so `videoIdFromUrl` decodes it intact.
 */
export function thumbMediaUrl(path: string): string {
  return `${MEDIA_SCHEME}://${MEDIA_HOST}/${encodeURIComponent(`thumb:${path}`)}`;
}

/** Resolve the effective <video> src: explicit `src` wins, else mstream URL. */
export function resolveSrc(videoId?: string, src?: string): string {
  if (src) return src;
  if (videoId) return mediaUrl(videoId);
  return '';
}

/** Clamp a source-absolute time into the window (identity when no window). */
export function clampToWindow(timeSec: number, win?: PlayerWindow | null): number {
  if (!win) return timeSec;
  return Math.min(Math.max(timeSec, win.start), win.end);
}

/** True once `timeSec` is within EPSILON of (or past) the window end. */
export function windowEndReached(
  timeSec: number,
  win?: PlayerWindow | null,
  epsilon: number = WINDOW_END_EPSILON,
): boolean {
  if (!win) return false;
  return timeSec >= win.end - epsilon;
}

/** play() returns a promise in real Chromium; swallow AbortError-style rejections. */
function safePlay(video: HTMLVideoElement): void {
  try {
    void Promise.resolve(video.play()).catch(() => undefined);
  } catch {
    /* jsdom / detached element — playback errors are non-fatal for the UI */
  }
}

export const Player = forwardRef<PlayerHandle, PlayerProps>(function Player(props, ref) {
  const {
    videoId,
    src,
    window: win = null,
    loop = false,
    autoPlay = false,
    controls = true,
    muted = false,
    className,
    reloadToken,
    onTimeUpdate,
    onEnded,
    onError,
  } = props;

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const resolvedSrc = resolveSrc(videoId, src);

  // Latest-value refs so the once-bound listeners never go stale and the
  // listener effect doesn't re-bind on every parent render.
  const winRef = useRef<PlayerWindow | null>(win);
  winRef.current = win;
  const loopRef = useRef(loop);
  loopRef.current = loop;
  const callbacksRef = useRef({ onTimeUpdate, onEnded, onError });
  callbacksRef.current = { onTimeUpdate, onEnded, onError };
  // Re-entry guard for the window-end stop: assigning `currentTime = w.end`
  // queues another `timeupdate` in real Chromium (even while paused), which still
  // satisfies `windowEndReached` and would re-run the stop — a duplicate onEnded
  // and a redundant same-value seek. The flag fires the stop exactly once per
  // arrival at the out point and re-arms when the head returns inside the window
  // (or the player loops).
  const stoppedAtEndRef = useRef(false);

  // Window mode: position the playhead at the window start once metadata is
  // available (seeking before HAVE_METADATA is silently dropped by Chromium).
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !win) return undefined;
    let done = false;
    const seekToStart = (): void => {
      if (done) return;
      done = true;
      video.currentTime = win.start;
      if (autoPlay) safePlay(video);
    };
    // Always listen: a proxy-swap `video.load()` resets readyState and re-fires
    // `loadedmetadata`, so the listener must stay armed to re-seek the window
    // start instead of leaving the reloaded stream parked at t=0. (A readyState>=1
    // early-return that skipped this left post-load() previews stuck at t=0.)
    video.addEventListener('loadedmetadata', seekToStart);
    if (video.readyState >= 1 /* HAVE_METADATA */) {
      // Metadata already present (cached src / a re-render before any reload):
      // seek now, then re-arm `done` so a later load()-driven `loadedmetadata`
      // re-seeks too. A same-load duplicate metadata event stays a no-op because
      // it only fires once per load, so the user's own scrub is never clobbered.
      seekToStart();
      done = false;
    }
    return () => video.removeEventListener('loadedmetadata', seekToStart);
    // `reloadToken` is a dep so a proxy-swap reload (video.load() re-fires
    // loadedmetadata) re-seeks the window start instead of staying at t=0.
  }, [win?.start, win?.end, resolvedSrc, autoPlay, reloadToken]); // eslint-disable-line react-hooks/exhaustive-deps

  // Single listener pass: report time, enforce the window end (stop or loop),
  // and surface a load/decode error so a blank frame is never silent.
  useEffect(() => {
    const video = videoRef.current;
    // defensive: the <video> ref is always attached before this mount-effect runs
    // (React sets refs before effects), so `video` is never null here.
    /* v8 ignore next */
    if (!video) return undefined;
    const handleTimeUpdate = (): void => {
      const t = video.currentTime;
      callbacksRef.current.onTimeUpdate?.(t);
      const w = winRef.current;
      if (!w || !windowEndReached(t, w)) {
        // Head is back inside the window (or there is no window): re-arm so the
        // next arrival at the out point fires the stop exactly once.
        stoppedAtEndRef.current = false;
        return;
      }
      if (loopRef.current) {
        stoppedAtEndRef.current = false;
        video.currentTime = w.start;
        safePlay(video);
        return;
      }
      if (stoppedAtEndRef.current) return; // already stopped at this out point
      stoppedAtEndRef.current = true;
      video.pause();
      video.currentTime = w.end; // snap the playhead exactly onto the out point
      callbacksRef.current.onEnded?.();
    };
    const handleEnded = (): void => {
      callbacksRef.current.onEnded?.();
    };
    const handleError = (): void => {
      // video.error is a MediaError (code 1-4) in real Chromium; jsdom leaves it
      // null when an `error` event is dispatched manually, so fall back to a
      // generic message rather than dereferencing a null.
      const code = video.error?.code;
      callbacksRef.current.onError?.(code ? `media error (code ${code})` : 'media failed to load');
    };
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('ended', handleEnded);
    video.addEventListener('error', handleError);
    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('ended', handleEnded);
      video.removeEventListener('error', handleError);
    };
  }, []);

  // Proxy-swap reload: when `reloadToken` CHANGES (not on first mount), re-fetch
  // the same `src` via video.load() so the now-ready proxy is picked up WITHOUT
  // remounting the element (shake-free). The window effect re-seeks to win.start
  // after the reload's loadedmetadata, so candidate previews stay positioned.
  const lastReloadToken = useRef(reloadToken);
  useEffect(() => {
    if (reloadToken === lastReloadToken.current) return;
    lastReloadToken.current = reloadToken;
    const video = videoRef.current;
    // defensive: ref is attached before effects run; guarded for type-safety.
    /* v8 ignore next */
    if (!video) return;
    video.load();
  }, [reloadToken]);

  useImperativeHandle(
    ref,
    (): PlayerHandle => ({
      play: () => {
        const video = videoRef.current;
        if (video) safePlay(video);
      },
      pause: () => videoRef.current?.pause(),
      seek: (timeSec: number) => {
        const video = videoRef.current;
        if (video) video.currentTime = clampToWindow(timeSec, winRef.current);
      },
      scrub: (timeSec: number) => {
        const video = videoRef.current;
        if (video) video.currentTime = clampToWindow(timeSec, winRef.current);
      },
      // the `?? 0` only fires if the ref is null, which the imperative handle can
      // never observe (it is callable only while the component is mounted).
      /* v8 ignore next */
      currentTime: () => videoRef.current?.currentTime ?? 0,
      isPlaying: () => {
        const video = videoRef.current;
        return Boolean(video && !video.paused && !video.ended);
      },
      element: () => videoRef.current,
    }),
    [],
  );

  return (
    <video
      ref={videoRef}
      className={className ?? 'player__video'}
      src={resolvedSrc || undefined}
      controls={controls}
      muted={muted}
      // Window mode must not autoplay from t=0 — playback starts after the
      // initial seek (handled in the window effect above).
      autoPlay={autoPlay && !win}
      preload="metadata"
      playsInline
    />
  );
});

export default Player;
