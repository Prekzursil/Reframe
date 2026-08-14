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
// The transport is scoped to the PLAYABLE SPAN, not to the whole source: in
// window mode (a candidate preview) the scrubber bounds and the time readout
// cover `[startTime, endTime]` only. Times crossing the props boundary stay
// SOURCE-ABSOLUTE so they line up with the owner's window clamp and with the
// shared timeline playhead.
//
// The pure helpers (`formatTimecode` / `clampTime` / `clampToSpan` /
// `frameDuration` / `nextShuttleRate` / `rateLabel`) are exported and
// unit-tested in Transport.test.tsx.
import React from 'react';

// The component's own skin. Imported HERE (not by a parent) so the styles cannot
// be separated from the markup by a call site that forgets them — the failure that
// left every class below unstyled when this component first shipped.
import './transport.css';

// THE timecode formatter (one definition, repo-wide). Used below and re-exported
// so this module's existing public surface is unchanged.
import { formatTimecode } from '../lib/timecode';

/**
 * Frame rate used for frame-stepping when the caller does not know the media's
 * real rate. 30 is a fallback, NOT a measurement — a 24/25/50/60fps source steps
 * by a fraction of a frame.
 *
 * NO PRODUCER EXISTS YET, so this is currently the rate for EVERY source. Measured
 * across all three layers rather than assumed:
 *   * sidecar — nothing reads `r_frame_rate` or `avg_frame_rate` anywhere under
 *     `sidecar/`, so the source rate is never probed;
 *   * wire — the only `fps` in `lib/rpc/schemas.ts` is a field of `ConvertOptions`,
 *     an OUTPUT encoding setting, not a property of the opened media;
 *   * renderer — no call site has a source rate to pass.
 *
 * An earlier version of this note told the caller to "pass `fps` from the probed
 * metadata whenever it is available". That was unactionable: there is no probed
 * metadata to pass. Closing the gap means adding a real source-rate field —
 * ffprobe `r_frame_rate` in the sidecar, a field on the media payload, then the
 * prop — which is a feature, not a rename. Until then frame-step is EXACT only on
 * 30fps sources; treat it as approximate elsewhere and do not claim otherwise.
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
  /** Seek intent, source-absolute seconds, already clamped into the playable span. */
  onSeek: (timeSec: number) => void;
  /** Shuttle-rate intent (negative = reverse). Optional: a simple player can ignore shuttle. */
  onRateChange?: (rate: number) => void;
  className?: string;
}

/**
 * Format seconds as `M:SS`, or `H:MM:SS` once past an hour.
 *
 * MOVED to `lib/timecode.ts` and re-exported here so existing importers (and this
 * file's own tests) are unaffected. It was defined here AND in
 * features/manualIntervalLogic.ts with divergent rounding — floor here, round there
 * — so the same seconds rendered as two different timecodes depending on the import.
 * There is now exactly one definition; see that module for why floor wins.
 */
export { formatTimecode };

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
  // RESIDUAL R11 (see Player.tsx `stoppedAtEndRef`): `position` is PINNED into
  // the span, so if the owner ever lets the head run PAST `spanEnd` — which its
  // pre-existing re-arm hole allows — the thumb and the readout both freeze on
  // the out point while playback continues, where the native bar showed the
  // truth. Honest for every in-span position; a known gap for an out-of-span
  // one, to be settled (here or in the owner) before any mount migrates.
  const position = clampToSpan(currentTime, spanStart, spanEnd);
  // Elapsed WITHIN the span: a 4s candidate reads `0:02 / 0:04`, never the
  // source's `0:42 / 10:00`.
  const elapsed = position - spanStart;

  /** Step `frames` frames, stopping playback first — stepping while rolling is never the intent. */
  const step = (frames: number): void => {
    onPlayPause(false);
    onSeek(clampToSpan(position + frames * frameSec, spanStart, spanEnd));
  };

  /**
   * Enter (or accelerate) a shuttle in `direction`.
   *
   * `onRateChange` is OPTIONAL ("a simple player can ignore shuttle"), and a player
   * that ignores it cannot play backwards at all. Forward degrades honestly — L
   * without a rate consumer is just "play", which is what L means. REVERSE does not:
   * calling `onPlayPause(true)` with no rate consumer starts FORWARD playback, the
   * opposite of what J asked for, which is worse than doing nothing. So a reverse
   * shuttle with no consumer is a no-op rather than a wrong-direction play.
   */
  const shuttle = (direction: 1 | -1): void => {
    if (direction === -1 && !onRateChange) return;
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
    //
    // SCOPE OF THE KEYBOARD CLAIM (rescoped after a reviewer measured the wider
    // wording): Space / J / K / L / arrows work only while focus is ALREADY
    // INSIDE this group. Keydown BUBBLES up from a focused child, this div has
    // no `tabIndex`, and nothing autofocuses — so on a freshly mounted player
    // with focus on <body> the shortcuts do nothing until the user Tabs to or
    // clicks a control. That is deliberate, not an oversight: `tabIndex={0}` on
    // a role="group" wrapper adds a tab stop that does nothing when reached, and
    // autofocusing on mount would steal focus from whatever the user was doing.
    // A global "press Space anywhere on the page" layer is the CALL SITE's to
    // own, and this is a migration decision, not a component one.
    //
    // NAMED OWNER + KNOWN COLLISION: ShortMaker already has such a layer, and
    // its Space branch calls `player.pause()` / `player.play()` through the
    // ref handle. On the CandidateReview mount both would be live at once, so
    // whoever migrates that surface must decide which owns Space rather than
    // letting a focused transport and a document-level handler both fire.
    // The tests here dispatch KeyboardEvents directly on this element, so they
    // pin the handler's behaviour and CANNOT observe the focus precondition —
    // settling experiment: drive it with userEvent (real Tab/click focus) or in
    // a real browser from a cold mount.
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
