// Transport.tsx — the custom playback transport (L8).
//
// Every professional NLE (Premiere, Resolve, CapCut, Descript) ships its own
// transport; Chromium's default `<video controls>` bar is the single most
// recognisable tell that a desktop app is a web page in a frame. It also cannot
// express the behaviours an editor needs: frame-step, J/K/L shuttle, and a
// playhead the timeline can share.
//
// This component is deliberately PRESENTATIONAL and fully controlled — it owns
// no playback state and holds no ref to a <video>. It renders the current
// position and emits intent (`onPlayPause` / `onSeek` / `onRateChange`); the
// owner (Player.tsx) applies that intent to the media element. That split is
// what makes the transport unit-testable without a real decoder, and what will
// let the multi-lane timeline drive the SAME playhead later.
//
// Accessibility contract (non-negotiable — it replaces a native control bar
// that was already accessible):
//   * every control is a real <button type="button"> with an accessible name,
//     so Enter/Space activate it natively and a screen reader announces it;
//   * the icons are decorative (`aria-hidden`), never the name;
//   * the scrubber is a native <input type="range"> — arrow keys step exactly
//     one frame because `step` IS the frame duration — with `aria-valuetext`
//     spoken as a timecode instead of a raw float;
//   * the shortcut layer never steals a key the focused control already owns
//     (Space on a button, arrows on the scrubber), so nothing double-fires.
//
// The pure helpers (`formatTimecode` / `clampTime` / `frameDuration` /
// `nextShuttleRate` / `rateLabel`) are exported and unit-tested in
// Transport.test.tsx.
import React from 'react';

/**
 * Frame rate used for frame-stepping when the caller does not know the media's
 * real rate. 30 is a fallback, NOT a measurement: pass `fps` from the probed
 * metadata whenever it is available or a 24/25/50/60fps source will step by a
 * fraction of a frame.
 */
export const TRANSPORT_DEFAULT_FPS = 30;

/** Fastest J/K/L shuttle multiplier (Premiere-style 1x -> 2x -> 4x). */
export const TRANSPORT_MAX_SHUTTLE_RATE = 4;

export interface TransportProps {
  /** Playhead position in seconds (source-absolute). */
  currentTime: number;
  /** Media duration in seconds; 0 while unknown. */
  duration: number;
  /**
   * Source-absolute IN point of the playable span (window mode). Default 0.
   *
   * The scrubber spans `[startTime, endTime]`, not `[0, duration]`: a candidate
   * preview is a few seconds inside a multi-minute source, and a track scaled to
   * the source would move its thumb across a sliver before the owner's window
   * clamp snapped it back. Times crossing this boundary stay SOURCE-ABSOLUTE so
   * `onSeek` still lines up with the owner's clamp and with a shared timeline
   * playhead; only the bounds and the human-facing readout live in the span.
   */
  startTime?: number;
  /** Source-absolute OUT point of the playable span. Default: the full duration. */
  endTime?: number;
  /** True while the media is actually advancing. */
  isPlaying: boolean;
  /** Frame rate used for single-frame steps (default {@link TRANSPORT_DEFAULT_FPS}). */
  fps?: number;
  /** Current shuttle rate: 1 = normal, >1 = fast forward, <0 = reverse. */
  rate?: number;
  /** Playback intent: `true` = play, `false` = pause. */
  onPlayPause: (play: boolean) => void;
  /** Seek intent, in seconds, already clamped into `[0, duration]`. */
  onSeek: (timeSec: number) => void;
  /** Shuttle-rate intent (negative = reverse). Optional: a simple player can ignore shuttle. */
  onRateChange?: (rate: number) => void;
  className?: string;
}

/** Format seconds as `M:SS`, or `H:MM:SS` once past an hour. Non-finite/negative -> `0:00`. */
export function formatTimecode(seconds: number): string {
  const total = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, '0');
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${secs}`;
  return `${minutes}:${secs}`;
}

/** Clamp a time into `[0, duration]`; a non-finite time or duration collapses to 0. */
export function clampTime(timeSec: number, duration: number): number {
  const max = Number.isFinite(duration) && duration > 0 ? duration : 0;
  if (!Number.isFinite(timeSec)) return 0;
  return Math.min(Math.max(timeSec, 0), max);
}

/**
 * Clamp a SOURCE-ABSOLUTE time into the playable span `[start, end]`; a
 * non-finite time (or an inverted span) collapses onto `start`.
 *
 * This is `clampTime` shifted off zero: the span is the window, so the floor is
 * the in-point rather than the start of the source.
 */
export function clampToSpan(timeSec: number, start: number, end: number): number {
  return start + clampTime(timeSec - start, Math.max(end - start, 0));
}

/** Seconds per frame at `fps`, falling back to the default rate for a non-positive rate. */
export function frameDuration(fps: number): number {
  return fps > 0 ? 1 / fps : 1 / TRANSPORT_DEFAULT_FPS;
}

/**
 * The shuttle rate after a J (direction -1) or L (direction +1) press.
 * Already shuttling that way -> double (capped); otherwise start at 1x that way.
 * Pass 0 as `current` when paused so the first press always starts at 1x.
 */
export function nextShuttleRate(current: number, direction: 1 | -1): number {
  const sameDirection = direction > 0 ? current >= 1 : current <= -1;
  if (!sameDirection) return direction;
  return Math.min(Math.abs(current) * 2, TRANSPORT_MAX_SHUTTLE_RATE) * direction;
}

/** Human label for a shuttle rate (`2x`, `2x rev`) — a bare `-2x` reads badly aloud. */
export function rateLabel(rate: number): string {
  return rate < 0 ? `${Math.abs(rate)}x rev` : `${rate}x`;
}

const ICON_PROPS = {
  viewBox: '0 0 16 16',
  width: 16,
  height: 16,
  fill: 'currentColor',
  'aria-hidden': true,
  focusable: 'false',
} as const;

/** A fully keyboard-operable playback transport (play/pause, scrub, frame-step, J/K/L). */
export function Transport({
  currentTime,
  duration,
  startTime = 0,
  endTime,
  isPlaying,
  fps = TRANSPORT_DEFAULT_FPS,
  rate = 1,
  onPlayPause,
  onSeek,
  onRateChange,
  className,
}: TransportProps): React.ReactElement {
  const frameSec = frameDuration(fps);
  // `clampTime(d, d)` IS the sanitized duration: non-finite/negative collapse to 0.
  const total = clampTime(duration, duration);
  // The playable span. Both ends are clamped into the media so a window that
  // outruns the source (or arrives before `loadedmetadata`, while `total` is
  // still 0) cannot bound the scrubber outside the material that exists.
  const spanStart = clampTime(startTime, total);
  const spanEnd = Math.max(clampTime(endTime ?? total, total), spanStart);
  const spanLength = spanEnd - spanStart;
  const position = clampToSpan(currentTime, spanStart, spanEnd);
  // Elapsed WITHIN the span: a 4s candidate reads `0:02 / 0:04`, never the
  // source's `0:42 / 10:00`.
  const elapsed = position - spanStart;

  /** Step `frames` frames, stopping playback first — stepping while rolling is never the intent. */
  const step = (frames: number): void => {
    onPlayPause(false);
    onSeek(clampToSpan(position + frames * frameSec, spanStart, spanEnd));
  };

  /** Enter (or accelerate) a shuttle in `direction`. */
  const shuttle = (direction: 1 | -1): void => {
    onRateChange?.(nextShuttleRate(isPlaying ? rate : 0, direction));
    onPlayPause(true);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    const target = event.target as HTMLElement;
    const key = event.key;
    if (key === ' ') {
      // A focused <button> already toggles on Space; handling it here too would
      // fire the toggle twice and land back where it started.
      if (target.tagName === 'BUTTON') return;
      event.preventDefault();
      onPlayPause(!isPlaying);
      return;
    }
    if (key === 'ArrowLeft' || key === 'ArrowRight') {
      // The scrubber's own `step` IS one frame, so let it handle its arrows.
      if (target.tagName === 'INPUT') return;
      event.preventDefault();
      step(key === 'ArrowRight' ? 1 : -1);
      return;
    }
    const lower = key.toLowerCase();
    if (lower === 'k') {
      event.preventDefault();
      onRateChange?.(1);
      onPlayPause(false);
      return;
    }
    if (lower === 'l') {
      event.preventDefault();
      shuttle(1);
      return;
    }
    if (lower === 'j') {
      event.preventDefault();
      shuttle(-1);
    }
  };

  return (
    // The keydown handler is a BUBBLE layer over real focusable controls
    // (buttons + range), not a fake widget: every action it exposes is also
    // reachable by activating a control, so no keyboard trap is introduced.
    <div
      className={className ?? 'transport'}
      role="group"
      aria-label="Video transport"
      onKeyDown={handleKeyDown}
    >
      <button
        type="button"
        className="transport__button"
        aria-label="Previous frame"
        onClick={() => step(-1)}
      >
        <svg {...ICON_PROPS}>
          <path d="M13 3v10L6 8z" />
          <path d="M3 3h2v10H3z" />
        </svg>
      </button>
      <button
        type="button"
        className="transport__button transport__button--play"
        aria-label={isPlaying ? 'Pause' : 'Play'}
        onClick={() => onPlayPause(!isPlaying)}
      >
        {isPlaying ? (
          <svg {...ICON_PROPS}>
            <path d="M4 3h3v10H4z" />
            <path d="M9 3h3v10H9z" />
          </svg>
        ) : (
          <svg {...ICON_PROPS}>
            <path d="M4 2.5v11l9-5.5z" />
          </svg>
        )}
      </button>
      <button
        type="button"
        className="transport__button"
        aria-label="Next frame"
        onClick={() => step(1)}
      >
        <svg {...ICON_PROPS}>
          <path d="M3 3v10l7-5z" />
          <path d="M11 3h2v10h-2z" />
        </svg>
      </button>
      <input
        type="range"
        className="transport__scrubber"
        aria-label="Seek"
        aria-valuetext={`${formatTimecode(elapsed)} of ${formatTimecode(spanLength)}`}
        min={spanStart}
        max={spanEnd}
        step={frameSec}
        value={position}
        onChange={(event) => onSeek(clampToSpan(Number(event.target.value), spanStart, spanEnd))}
      />
      {/* The scrubber's aria-valuetext already speaks the position; a second
          announcement of the same numbers is noise, so the readout is visual. */}
      <span className="transport__time" aria-hidden="true">
        {`${formatTimecode(elapsed)} / ${formatTimecode(spanLength)}`}
      </span>
      {/* Always mounted so a live region exists BEFORE the rate changes. */}
      <span className="transport__rate" role="status">
        {rate === 1 ? '' : rateLabel(rate)}
      </span>
    </div>
  );
}

export default Transport;
