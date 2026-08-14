// Player.tsx — the real HTML5 video player (P2 U1).
//
// Plays library media over the privileged `mstream://` protocol (served with
// HTTP Range support by app/main/mediaProtocol.ts), or any direct `src` the
// caller already has (e.g. a converted file or an explicit proxy URL).
//
// Two modes:
//   * full playback — a <video> with either Chromium's native control bar
//     (the default, unchanged) or the custom Transport (`transport`, L8);
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
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { TRANSPORT_DEFAULT_FPS, Transport, frameDuration } from './Transport';
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
  /**
   * Show Chromium's NATIVE control bar. Defaults to `true` without `transport`
   * (every existing mount keeps exactly what it had) and to `false` with it.
   * Pass it explicitly to override either way — including `transport` + native
   * bar together, so enabling the custom transport never silently REMOVES a
   * control surface a caller was relying on.
   */
  controls?: boolean;
  /**
   * Render the custom {@link Transport} (play/pause, scrubbable position,
   * current/total time, frame-step, J/K/L shuttle) instead of the native bar.
   * Opt-in: the default is unchanged so no existing call site shifts under it.
   */
  transport?: boolean;
  /**
   * Frame rate used for frame-stepping and the reverse shuttle cadence
   * (default {@link TRANSPORT_DEFAULT_FPS}). Pass the probed rate when known —
   * the fallback steps by 1/30s, which is not one frame on a 24/25/50fps source.
   */
  fps?: number;
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
    controls,
    transport = false,
    fps = TRANSPORT_DEFAULT_FPS,
    muted = false,
    className,
    reloadToken,
    onTimeUpdate,
    onEnded,
    onError,
  } = props;

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const resolvedSrc = resolveSrc(videoId, src);
  // The native bar is the default ONLY while the custom transport is off; an
  // explicit `controls` always wins so nothing is silently taken away.
  //
  // MIGRATION TRAP — read before adding `transport` to a call site. Because an
  // explicit `controls` wins, `<Player controls transport />` renders BOTH bars
  // and leaves the L8 defect unfixed at that surface, silently. Five of the
  // seven production mounts pass a bare `controls` today (CaptionDesigner,
  // ProducedShorts, CaptionStage, ExportStage, Shorts), so migrating one means
  // DELETING its `controls` as well as adding `transport` — keep `controls`
  // only where the native bar is deliberately wanted alongside.
  const nativeControls = controls ?? !transport;

  // Transport-facing playback state. Kept here (not in Transport) so the
  // transport stays a pure controlled view and the same state can later feed
  // the multi-lane timeline playhead.
  const [playhead, setPlayhead] = useState(0);
  const [mediaDuration, setMediaDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  // The reverse shuttle PAUSES the element on purpose; the `pause` listener has
  // to tell that apart from the user stopping playback, and it is bound once,
  // so it reads the rate off a ref instead of a stale closure.
  const rateRef = useRef(rate);
  rateRef.current = rate;
  const frameSec = frameDuration(fps);
  const floorSec = win ? win.start : 0;

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
  //
  // RESIDUAL R11 — PRE-EXISTING on origin/main (this block is byte-identical
  // there), disclosed here because the transport makes it HARDER to see, not
  // because this lane caused it: the flag re-arms ONLY when the head comes back
  // INSIDE the window, so pressing Play while parked exactly ON `w.end` never
  // re-arms, every later `timeupdate` takes the early-return below, and playback
  // runs past the out point unbounded. The native bar at least showed that — it
  // reads the element's real time. The transport's span clamp
  // (Transport.clampToSpan) pins the thumb AND the readout at the out point, so
  // it would show a frozen `0:04 / 0:04` while playback continued. Not reachable
  // by a user today (no production mount passes `transport`), and deliberately
  // NOT fixed in this lane: the repair is a UX decision — replay from
  // `w.start`, refuse the Play, or render an explicit out-of-span state — on a
  // surface no call site uses yet, and it would change behaviour four live
  // window mounts share today. It MUST be settled before the first mount
  // migrates, and it is the reason `transport` is still opt-in.
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
      // A stop ENDS A SHUTTLE — and this path is the one that could forget. It
      // fires the `onEnded` PROP, not the DOM `ended` event, so `syncEnded`
      // (the listener that resets the rate) never runs for it: without these two
      // lines an L-shuttle survived the out point with `playbackRate` still 2x/4x
      // on the element and "2x" still announced in the transport's live region,
      // and the next Play resumed at that rate. Inert without the transport —
      // both values are already at these defaults, so React bails out.
      setPlaying(false);
      setRate(1);
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

  // L8: mirror the element's own state into React so the custom transport can
  // render it. Bound ONLY when the transport is mounted — a caller on the
  // native bar pays nothing (no extra listeners, no re-render per timeupdate).
  useEffect(() => {
    if (!transport) return undefined;
    const video = videoRef.current;
    /* v8 ignore next -- React attaches refs before effects run; unreachable */
    if (!video) return undefined;
    const syncTime = (): void => setPlayhead(video.currentTime);
    const syncDuration = (): void =>
      setMediaDuration(Number.isFinite(video.duration) ? video.duration : 0);
    const syncPlaying = (): void => setPlaying(true);
    const syncPaused = (): void => {
      // A reverse shuttle drives playback by pausing + stepping; its own pause
      // event must not read as "stopped".
      if (rateRef.current >= 0) setPlaying(false);
    };
    // `ended` is a STOP, so it must clear the shuttle exactly like the other
    // three stop paths (the window floor below, an explicit pause, and the
    // window-END stop in the listener effect above) already do. Clearing only
    // `playing` left a NEGATIVE rate armed, so the next Play re-entered the
    // reverse driver and walked the head BACKWARD.
    const syncEnded = (): void => {
      setPlaying(false);
      setRate(1);
    };
    // Seed from the ELEMENT, not from future events alone: `loadedmetadata` and
    // `durationchange` fire once per LOAD, so a call site that turns `transport`
    // on AFTER metadata landed would never see either again and would sit at
    // duration 0 forever — a dead scrubber with min === max. Seeding here makes
    // the effect order-independent instead of mount-order-dependent.
    syncTime();
    syncDuration();
    video.addEventListener('timeupdate', syncTime);
    video.addEventListener('seeked', syncTime);
    video.addEventListener('loadedmetadata', syncDuration);
    video.addEventListener('durationchange', syncDuration);
    video.addEventListener('play', syncPlaying);
    video.addEventListener('pause', syncPaused);
    video.addEventListener('ended', syncEnded);
    return () => {
      video.removeEventListener('timeupdate', syncTime);
      video.removeEventListener('seeked', syncTime);
      video.removeEventListener('loadedmetadata', syncDuration);
      video.removeEventListener('durationchange', syncDuration);
      video.removeEventListener('play', syncPlaying);
      video.removeEventListener('pause', syncPaused);
      video.removeEventListener('ended', syncEnded);
    };
  }, [transport]);

  // L8 shuttle driver. Forward rates ride the element's own playbackRate;
  // REVERSE cannot — HTMLMediaElement rejects a negative rate — so the head is
  // walked back one frame per frame-interval while the element stays paused.
  useEffect(() => {
    if (!transport) return undefined;
    const video = videoRef.current;
    /* v8 ignore next -- React attaches refs before effects run; unreachable */
    if (!video) return undefined;
    if (rate > 0) {
      video.playbackRate = rate;
      return undefined;
    }
    // A NEGATIVE rate now IS an active reverse shuttle, so no separate `playing`
    // test is needed. This file has FOUR paths that stop playback, and all four
    // clear the rate back to 1:
    //   1. an explicit pause          — handlePlayPause(false) below;
    //   2. the reverse-shuttle floor  — the interval below, at `floorSec`;
    //   3. the DOM `ended` event      — syncEnded in the sync effect above;
    //   4. the window-END stop        — in the listener effect above.
    // (4) was the one that did not, and an earlier revision of this comment
    // claimed only THREE existed — three reviewers measured that independently.
    // It fires the `onEnded` PROP rather than the DOM `ended` event, so
    // `syncEnded` never runs for it and a forward 2x/4x shuttle used to survive
    // the out point. It could never strand a NEGATIVE rate (the reverse driver
    // walks AWAY from `w.end` and `stoppedAtEndRef` latches), so retiring the
    // `!playing` guard was safe even then — but the enumeration was not true,
    // and a migrating call site would have read it as a total invariant.
    // The only producer of a negative rate — Transport's `shuttle()` — sets the
    // rate and starts playback in the same batch. A `!playing` guard used to sit
    // here; once every stop path cleared the rate it became unreachable, and
    // parking a BEHAVIOURAL branch behind a coverage ignore would be a dodge
    // rather than a safeguard. The rule is "no ignore on a behavioural branch",
    // NOT "no ignores": this file carries seven `v8 ignore` pragmas (three
    // inherited from main, four added with the transport) and every one is an
    // `if (!video)` / `?? 0` null-narrowing guard that React's ref timing makes
    // structurally unreachable — a different animal from a branch encoding a
    // playback rule. The FOUR stop-path tests in Player.test.tsx — including
    // 'clears the shuttle rate at the WINDOW-END stop' and 'ends a REVERSE
    // shuttle stopped at the out point' — are what hold the invariant up.
    video.pause();
    const stepSec = Math.abs(rate) * frameSec;
    const timer = setInterval(() => {
      const next = video.currentTime - stepSec;
      if (next <= floorSec) {
        video.currentTime = floorSec;
        setPlayhead(floorSec);
        setPlaying(false);
        setRate(1);
        return;
      }
      video.currentTime = next;
      setPlayhead(next);
    }, frameSec * 1000);
    return () => clearInterval(timer);
    // `playing` is deliberately NOT a dep: the effect no longer reads it, and a
    // rate change is what starts and stops the reverse arm.
  }, [transport, rate, frameSec, floorSec]);

  /** Transport intent: play or pause. Stopping always ends a shuttle. */
  const handlePlayPause = (play: boolean): void => {
    const video = videoRef.current;
    /* v8 ignore next -- the transport only renders while the element is mounted */
    if (!video) return;
    if (play) {
      safePlay(video);
      setPlaying(true);
      return;
    }
    video.pause();
    setPlaying(false);
    setRate(1);
  };

  /** Transport intent: seek (through the same window clamp as the ref handle). */
  const handleSeek = (timeSec: number): void => {
    const video = videoRef.current;
    /* v8 ignore next -- the transport only renders while the element is mounted */
    if (!video) return;
    const target = clampToWindow(timeSec, winRef.current);
    video.currentTime = target;
    // Chromium raises `seeked` for this, but updating now keeps the scrubber
    // pinned to the pointer instead of trailing the event.
    setPlayhead(target);
  };

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
    // A fragment, not a wrapper: without `transport` the rendered DOM is byte
    // for byte what it was, so no existing mount's layout or CSS shifts.
    <>
      <video
        ref={videoRef}
        className={className ?? 'player__video'}
        src={resolvedSrc || undefined}
        controls={nativeControls}
        muted={muted}
        // Window mode must not autoplay from t=0 — playback starts after the
        // initial seek (handled in the window effect above).
        autoPlay={autoPlay && !win}
        preload="metadata"
        playsInline
      />
      {transport ? (
        <Transport
          currentTime={playhead}
          duration={mediaDuration}
          // Window mode narrows the transport to the CANDIDATE, not the source:
          // the reverse shuttle already floors at `win.start` (floorSec), and
          // handleSeek already clamps every seek into the window, so leaving the
          // scrubber spanning the whole source was the one place the window was
          // dropped — and the one the user actually looks at.
          startTime={floorSec}
          endTime={win?.end}
          isPlaying={playing}
          rate={rate}
          fps={fps}
          onPlayPause={handlePlayPause}
          onSeek={handleSeek}
          onRateChange={setRate}
        />
      ) : null}
    </>
  );
});

export default Player;
