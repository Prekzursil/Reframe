// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  Player,
  WINDOW_END_EPSILON,
  clampToWindow,
  mediaUrl,
  resolveSrc,
  shortMediaUrl,
  thumbMediaUrl,
  windowEndReached,
  type PlayerHandle,
  type PlayerProps,
} from './Player';

// React 18's act() wants this flag in a bare jsdom environment.
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// jsdom does not implement HTMLMediaElement playback; back the properties the
// Player touches (play/pause/currentTime/readyState/paused/ended) with
// deterministic per-element stores so tests can drive them.
// ---------------------------------------------------------------------------
const playMock = vi.fn(() => Promise.resolve());
const pauseMock = vi.fn();
const loadMock = vi.fn();
const currentTimes = new WeakMap<HTMLMediaElement, number>();
const durations = new WeakMap<HTMLMediaElement, number>();
const playbackRates = new WeakMap<HTMLMediaElement, number>();
const readyStates = new WeakMap<HTMLMediaElement, number>();
const pausedStates = new WeakMap<HTMLMediaElement, boolean>();
const errorStates = new WeakMap<HTMLMediaElement, { code: number } | null>();
let defaultReadyState = 0;

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    writable: true,
    value: playMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    writable: true,
    value: pauseMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'load', {
    configurable: true,
    writable: true,
    value: loadMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'error', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return errorStates.get(this) ?? null;
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return currentTimes.get(this) ?? 0;
    },
    set(this: HTMLMediaElement, v: number) {
      currentTimes.set(this, v);
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'readyState', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return readyStates.get(this) ?? defaultReadyState;
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'paused', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return pausedStates.get(this) ?? true;
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'ended', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return false;
    },
  });
  // jsdom reports no duration at all; back it per-element so the transport can
  // be driven with a real one (and with the NaN a not-yet-loaded media reports).
  Object.defineProperty(HTMLMediaElement.prototype, 'duration', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return durations.get(this) ?? Number.NaN;
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'playbackRate', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return playbackRates.get(this) ?? 1;
    },
    set(this: HTMLMediaElement, v: number) {
      playbackRates.set(this, v);
    },
  });
});

// ---------------------------------------------------------------------------
// pure helpers
// ---------------------------------------------------------------------------
describe('mediaUrl / resolveSrc', () => {
  it('builds the canonical mstream URL with the id percent-encoded', () => {
    expect(mediaUrl('abc123def456')).toBe('mstream://media/abc123def456');
    expect(mediaUrl('id with spaces')).toBe('mstream://media/id%20with%20spaces');
  });

  it('resolveSrc prefers an explicit src over the videoId', () => {
    expect(resolveSrc('vid1', 'C:/proxies/vid1.mp4')).toBe('C:/proxies/vid1.mp4');
    expect(resolveSrc('vid1', undefined)).toBe('mstream://media/vid1');
    expect(resolveSrc(undefined, undefined)).toBe('');
  });
});

describe('shortMediaUrl (P4 §6 / C10)', () => {
  it('encodes the short: prefixed path as a single path segment', () => {
    const url = shortMediaUrl('C:\\exports\\shorts-vid1\\clip.mp4');
    expect(url).toBe(
      `mstream://media/${encodeURIComponent('short:C:\\exports\\shorts-vid1\\clip.mp4')}`,
    );
    // The colon after `short` is encoded (%3A) so it cannot be mistaken for a
    // URL scheme/host boundary — proves it is one path segment, not media/short/.
    expect(url.startsWith('mstream://media/short%3A')).toBe(true);
  });
});

describe('thumbMediaUrl (UX/QoL WU-4)', () => {
  it('encodes the thumb: prefixed path as a single path segment', () => {
    const url = thumbMediaUrl('C:\\data\\thumbnails\\v1.jpg');
    expect(url).toBe(`mstream://media/${encodeURIComponent('thumb:C:\\data\\thumbnails\\v1.jpg')}`);
    // The colon after `thumb` is encoded (%3A) so it cannot be mistaken for a
    // URL scheme/host boundary — proves it is one path segment, not media/thumb/.
    expect(url.startsWith('mstream://media/thumb%3A')).toBe(true);
  });
});

describe('clampToWindow', () => {
  const win = { start: 10, end: 20 };

  it('clamps below/above into the window', () => {
    expect(clampToWindow(5, win)).toBe(10);
    expect(clampToWindow(25, win)).toBe(20);
  });

  it('passes through values inside the window', () => {
    expect(clampToWindow(10, win)).toBe(10);
    expect(clampToWindow(15.5, win)).toBe(15.5);
    expect(clampToWindow(20, win)).toBe(20);
  });

  it('is the identity without a window', () => {
    expect(clampToWindow(123.4, null)).toBe(123.4);
    expect(clampToWindow(-5, undefined)).toBe(-5);
  });
});

describe('windowEndReached', () => {
  const win = { start: 12.5, end: 30 };

  it('is false strictly inside the window', () => {
    expect(windowEndReached(12.5, win)).toBe(false);
    expect(windowEndReached(29.9, win)).toBe(false);
  });

  it('is true within EPSILON of the end and beyond it', () => {
    expect(windowEndReached(30 - WINDOW_END_EPSILON, win)).toBe(true);
    expect(windowEndReached(30, win)).toBe(true);
    expect(windowEndReached(31.2, win)).toBe(true);
  });

  it('is false without a window', () => {
    expect(windowEndReached(9999, null)).toBe(false);
    expect(windowEndReached(9999, undefined)).toBe(false);
  });

  it('honors a custom epsilon', () => {
    expect(windowEndReached(29.5, win, 0.6)).toBe(true);
    expect(windowEndReached(29.5, win, 0.1)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// component
// ---------------------------------------------------------------------------
let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  playMock.mockClear();
  pauseMock.mockClear();
  loadMock.mockClear();
  defaultReadyState = 0;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(props: PlayerProps, ref?: React.Ref<PlayerHandle>): HTMLVideoElement {
  act(() => {
    root.render(<Player {...props} ref={ref} />);
  });
  const video = container.querySelector('video');
  expect(video).not.toBeNull();
  return video as HTMLVideoElement;
}

describe('Player rendering', () => {
  it('renders a <video> pointed at the mstream URL for a videoId', () => {
    const video = render({ videoId: 'vid-1' });
    expect(video.getAttribute('src')).toBe('mstream://media/vid-1');
    expect(video.hasAttribute('controls')).toBe(true);
  });

  it('prefers a direct converted/proxy src prop over the videoId', () => {
    const video = render({ videoId: 'vid-1', src: 'converted/vid-1.mp4' });
    expect(video.getAttribute('src')).toBe('converted/vid-1.mp4');
  });

  it('omits controls when controls=false and sets muted', () => {
    const video = render({ videoId: 'vid-1', controls: false, muted: true });
    expect(video.hasAttribute('controls')).toBe(false);
    expect(video.muted).toBe(true);
  });

  it('omits the src attribute entirely when neither videoId nor src is given', () => {
    // resolveSrc returns '' -> `src={resolvedSrc || undefined}` (Player.tsx:236)
    // drops the attribute rather than setting src="".
    const video = render({});
    expect(video.hasAttribute('src')).toBe(false);
  });

  it('does not set the autoplay attribute in window mode (plays after the seek)', () => {
    const video = render({
      videoId: 'vid-1',
      autoPlay: true,
      window: { start: 1, end: 2 },
    });
    expect(video.hasAttribute('autoplay')).toBe(false);
  });
});

describe('Player window mode', () => {
  const win = { start: 12.5, end: 30 };

  it('seeks to the window start on loadedmetadata', () => {
    const video = render({ videoId: 'vid-1', window: win });
    expect(video.currentTime).toBe(0);
    act(() => {
      video.dispatchEvent(new Event('loadedmetadata'));
    });
    expect(video.currentTime).toBe(12.5);
  });

  it('seeks to the window start only once even if loadedmetadata fires twice', () => {
    // The `done` guard (Player.tsx:164) means a second loadedmetadata is a no-op:
    // a user seek between the two events must not be clobbered by a re-seek.
    const video = render({ videoId: 'vid-1', window: win });
    act(() => {
      video.dispatchEvent(new Event('loadedmetadata'));
    });
    expect(video.currentTime).toBe(12.5);

    // Simulate the user scrubbing away, then a duplicate metadata event.
    act(() => {
      video.currentTime = 18;
      video.dispatchEvent(new Event('loadedmetadata'));
    });
    expect(video.currentTime).toBe(18); // not re-snapped to the window start
  });

  it('seeks immediately when metadata is already available', () => {
    defaultReadyState = 1; // HAVE_METADATA
    const video = render({ videoId: 'vid-1', window: win });
    expect(video.currentTime).toBe(12.5);
  });

  it('starts playback after the initial seek when autoPlay is set', () => {
    defaultReadyState = 1;
    render({ videoId: 'vid-1', window: win, autoPlay: true });
    expect(playMock).toHaveBeenCalledTimes(1);
  });

  it('stops at the window end: pause + snap + onEnded', () => {
    const onEnded = vi.fn();
    const video = render({ videoId: 'vid-1', window: win, onEnded });
    act(() => {
      video.currentTime = 30.2; // timeupdate overshoots the out point
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(pauseMock).toHaveBeenCalledTimes(1);
    expect(video.currentTime).toBe(30); // snapped exactly onto the out point
    expect(onEnded).toHaveBeenCalledTimes(1);
  });

  it('loops back to the window start instead of stopping when loop is set', () => {
    const onEnded = vi.fn();
    const video = render({ videoId: 'vid-1', window: win, loop: true, onEnded });
    act(() => {
      video.currentTime = 30.2;
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(video.currentTime).toBe(12.5);
    expect(playMock).toHaveBeenCalledTimes(1);
    expect(pauseMock).not.toHaveBeenCalled();
    expect(onEnded).not.toHaveBeenCalled();
  });

  it('does not pause inside the window and reports time via onTimeUpdate', () => {
    const onTimeUpdate = vi.fn();
    const video = render({ videoId: 'vid-1', window: win, onTimeUpdate });
    act(() => {
      video.currentTime = 20;
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(onTimeUpdate).toHaveBeenCalledWith(20);
    expect(pauseMock).not.toHaveBeenCalled();
  });

  it('fires the window-end stop only ONCE even when the snap re-triggers timeupdate', () => {
    // Real Chromium: `currentTime = w.end` queues another timeupdate (even while
    // paused) that still satisfies windowEndReached; the guard blocks a duplicate
    // onEnded + a redundant same-value seek (Player.tsx re-entry guard).
    const onEnded = vi.fn();
    const video = render({ videoId: 'vid-1', window: win, onEnded });
    act(() => {
      video.currentTime = 30.2; // timeupdate overshoots the out point
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(pauseMock).toHaveBeenCalledTimes(1);
    expect(onEnded).toHaveBeenCalledTimes(1);
    // The snap left currentTime at w.end (30); a second timeupdate at the snapped
    // out point must be a no-op.
    act(() => {
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(pauseMock).toHaveBeenCalledTimes(1);
    expect(onEnded).toHaveBeenCalledTimes(1);
  });

  it('re-arms and re-fires the stop after the head returns inside the window', () => {
    const onEnded = vi.fn();
    const video = render({ videoId: 'vid-1', window: win, onEnded });
    act(() => {
      video.currentTime = 30.2;
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(onEnded).toHaveBeenCalledTimes(1);
    // The user scrubs back inside the window (or replays) — this re-arms the guard.
    act(() => {
      video.currentTime = 20;
      video.dispatchEvent(new Event('timeupdate'));
    });
    // Reaching the out point again fires the stop a second time.
    act(() => {
      video.currentTime = 30.2;
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(onEnded).toHaveBeenCalledTimes(2);
    expect(pauseMock).toHaveBeenCalledTimes(2);
  });

  it('re-arms the end guard on a windowless timeupdate', () => {
    // No window: handleTimeUpdate takes the `!w` short-circuit, clearing the guard
    // and never stopping (covers the windowless re-arm branch).
    const onTimeUpdate = vi.fn();
    const onEnded = vi.fn();
    const video = render({ videoId: 'vid-1', onTimeUpdate, onEnded });
    act(() => {
      video.currentTime = 5;
      video.dispatchEvent(new Event('timeupdate'));
    });
    expect(onTimeUpdate).toHaveBeenCalledWith(5);
    expect(onEnded).not.toHaveBeenCalled();
    expect(pauseMock).not.toHaveBeenCalled();
  });

  it('re-seeks when the window prop changes (next candidate preview)', () => {
    const video = render({ videoId: 'vid-1', window: win });
    act(() => {
      video.dispatchEvent(new Event('loadedmetadata'));
    });
    expect(video.currentTime).toBe(12.5);

    act(() => {
      root.render(<Player videoId="vid-1" window={{ start: 40, end: 55 }} />);
    });
    act(() => {
      video.dispatchEvent(new Event('loadedmetadata'));
    });
    expect(video.currentTime).toBe(40);
  });

  it('forwards the native ended event to onEnded', () => {
    const onEnded = vi.fn();
    const video = render({ videoId: 'vid-1', onEnded });
    act(() => {
      video.dispatchEvent(new Event('ended'));
    });
    expect(onEnded).toHaveBeenCalledTimes(1);
  });
});

describe('Player reloadToken (shake-free proxy swap)', () => {
  it('does NOT reload on first mount even when a reloadToken is provided', () => {
    render({ videoId: 'vid-1', reloadToken: 0 });
    expect(loadMock).not.toHaveBeenCalled();
  });

  it('re-fetches the same src via video.load() WITHOUT remounting when the token changes', () => {
    const video = render({ videoId: 'vid-1', reloadToken: 0 });
    expect(loadMock).not.toHaveBeenCalled();
    act(() => {
      root.render(<Player videoId="vid-1" reloadToken={1} />);
    });
    // same element (no key remount) AND a load() was issued to pick up the proxy.
    expect(container.querySelector('video')).toBe(video);
    expect(loadMock).toHaveBeenCalledTimes(1);
  });

  it('does not reload when the token is unchanged across re-renders', () => {
    render({ videoId: 'vid-1', reloadToken: 3 });
    act(() => {
      root.render(<Player videoId="vid-1" reloadToken={3} muted />);
    });
    expect(loadMock).not.toHaveBeenCalled();
  });

  it('re-seeks the window start after a reload (window mode proxy swap)', () => {
    const win = { start: 12.5, end: 30 };
    const video = render({ videoId: 'vid-1', window: win, reloadToken: 0 });
    act(() => video.dispatchEvent(new Event('loadedmetadata')));
    expect(video.currentTime).toBe(12.5);
    // user scrubs away, then a proxy swap reloads -> re-seek to the window start.
    act(() => {
      video.currentTime = 20;
    });
    // Re-render with the bumped token (its effects flush at this act's end,
    // re-binding a fresh loadedmetadata listener whose `done` guard is reset).
    act(() => {
      root.render(<Player videoId="vid-1" window={win} reloadToken={1} />);
    });
    expect(loadMock).toHaveBeenCalledTimes(1);
    // The reload's loadedmetadata now re-seeks to the window start.
    act(() => video.dispatchEvent(new Event('loadedmetadata')));
    expect(video.currentTime).toBe(12.5);
  });

  it('re-seeks the window start after a reload even when metadata was ALREADY loaded', () => {
    // readyState>=1 proxy swap: the window effect used to seek immediately and
    // return WITHOUT attaching a listener, so the reload's re-fired loadedmetadata
    // left the playhead at t=0. The listener must stay armed and re-seek.
    defaultReadyState = 1; // HAVE_METADATA before any reload
    const win = { start: 12.5, end: 30 };
    const video = render({ videoId: 'vid-1', window: win, reloadToken: 0 });
    expect(video.currentTime).toBe(12.5); // immediate seek — metadata already ready
    act(() => {
      video.currentTime = 20; // user scrubs away
    });
    // Proxy swap bumps the token -> video.load() re-fetches the now-ready proxy.
    act(() => {
      root.render(<Player videoId="vid-1" window={win} reloadToken={1} />);
    });
    expect(loadMock).toHaveBeenCalledTimes(1);
    // Real Chromium: load() resets the playhead; the re-fired loadedmetadata must
    // re-seek to the window start rather than leaving it at t=0.
    act(() => {
      video.currentTime = 0;
      video.dispatchEvent(new Event('loadedmetadata'));
    });
    expect(video.currentTime).toBe(12.5);
  });
});

describe('Player onError', () => {
  it('reports a coded media error to onError', () => {
    const onError = vi.fn();
    const video = render({ videoId: 'vid-1', onError });
    errorStates.set(video, { code: 4 });
    act(() => video.dispatchEvent(new Event('error')));
    expect(onError).toHaveBeenCalledWith('media error (code 4)');
  });

  it('reports a generic message when video.error is null (jsdom dispatch)', () => {
    const onError = vi.fn();
    const video = render({ videoId: 'vid-1', onError });
    errorStates.set(video, null);
    act(() => video.dispatchEvent(new Event('error')));
    expect(onError).toHaveBeenCalledWith('media failed to load');
  });

  it('does not throw when an error fires with no onError handler', () => {
    const video = render({ videoId: 'vid-1' });
    errorStates.set(video, { code: 2 });
    expect(() => act(() => video.dispatchEvent(new Event('error')))).not.toThrow();
  });
});

describe('Player imperative handle', () => {
  const win = { start: 10, end: 20 };

  it('exposes play/pause/element/currentTime', () => {
    const ref = React.createRef<PlayerHandle>();
    const video = render({ videoId: 'vid-1' }, ref);

    ref.current!.play();
    expect(playMock).toHaveBeenCalledTimes(1);
    ref.current!.pause();
    expect(pauseMock).toHaveBeenCalledTimes(1);
    expect(ref.current!.element()).toBe(video);

    act(() => {
      video.currentTime = 7.25;
    });
    expect(ref.current!.currentTime()).toBe(7.25);
  });

  it('seek and scrub clamp into the active window', () => {
    const ref = React.createRef<PlayerHandle>();
    const video = render({ videoId: 'vid-1', window: win }, ref);

    act(() => ref.current!.seek(2));
    expect(video.currentTime).toBe(10);
    act(() => ref.current!.seek(99));
    expect(video.currentTime).toBe(20);
    act(() => ref.current!.scrub(15));
    expect(video.currentTime).toBe(15);
  });

  it('seek is unclamped without a window', () => {
    const ref = React.createRef<PlayerHandle>();
    const video = render({ videoId: 'vid-1' }, ref);
    act(() => ref.current!.seek(123.4));
    expect(video.currentTime).toBe(123.4);
  });

  it('isPlaying reflects the paused state', () => {
    const ref = React.createRef<PlayerHandle>();
    const video = render({ videoId: 'vid-1' }, ref);
    expect(ref.current!.isPlaying()).toBe(false);
    pausedStates.set(video, false);
    expect(ref.current!.isPlaying()).toBe(true);
  });

  it('swallows a synchronous play() throw (detached/jsdom element)', () => {
    // safePlay()'s try/catch (Player.tsx:124-128) guards the rare case where
    // video.play() throws synchronously rather than returning a promise — the UI
    // must not crash. Make play() throw for this single call.
    const ref = React.createRef<PlayerHandle>();
    render({ videoId: 'vid-1' }, ref);
    playMock.mockImplementationOnce(() => {
      throw new Error('synchronous play boom');
    });
    expect(() => ref.current!.play()).not.toThrow();
    expect(playMock).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// L8 — the custom transport (Transport.tsx) mounted INSTEAD of Chromium's
// default control bar. The seven production mounts are NOT migrated here, so
// the default must stay exactly as it was: native controls, no transport.
// ---------------------------------------------------------------------------
describe('Player custom transport (L8)', () => {
  function group(): HTMLElement {
    const el = container.querySelector('[role="group"][aria-label="Video transport"]');
    expect(el).not.toBeNull();
    return el as HTMLElement;
  }

  function button(name: string): HTMLButtonElement {
    const el = group().querySelector(`button[aria-label="${name}"]`);
    expect(el).not.toBeNull();
    return el as HTMLButtonElement;
  }

  function scrubber(): HTMLInputElement {
    return group().querySelector('input[type="range"]') as HTMLInputElement;
  }

  function click(el: HTMLElement): void {
    act(() => {
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
  }

  function press(key: string): void {
    act(() => {
      group().dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
    });
  }

  function fire(video: HTMLVideoElement, type: string): void {
    act(() => {
      video.dispatchEvent(new Event(type));
    });
  }

  it('keeps the native bar by default so no existing mount silently loses it', () => {
    const video = render({ videoId: 'vid-1' });
    expect(video.hasAttribute('controls')).toBe(true);
    expect(container.querySelector('[role="group"][aria-label="Video transport"]')).toBeNull();
  });

  it('replaces the native bar with the custom transport when transport is on', () => {
    const video = render({ videoId: 'vid-1', transport: true });
    expect(video.hasAttribute('controls')).toBe(false);
    expect(button('Play')).toBeTruthy();
  });

  it('keeps the native bar reachable behind the explicit controls prop', () => {
    // Nothing is silently taken away: an opt-in caller can still ask for both.
    const video = render({ videoId: 'vid-1', transport: true, controls: true });
    expect(video.hasAttribute('controls')).toBe(true);
    expect(button('Play')).toBeTruthy();
  });

  it('mirrors the media duration and playhead into the transport', () => {
    const video = render({ videoId: 'vid-1', transport: true });
    durations.set(video, 90);
    fire(video, 'loadedmetadata');
    video.currentTime = 12;
    fire(video, 'timeupdate');
    expect(scrubber().max).toBe('90');
    expect(scrubber().value).toBe('12');
  });

  it('reports a zero duration while the media reports a non-finite one', () => {
    const video = render({ videoId: 'vid-1', transport: true });
    fire(video, 'durationchange'); // duration is NaN until metadata lands
    expect(scrubber().max).toBe('0');
  });

  it('drives play and pause from the transport toggle', () => {
    render({ videoId: 'vid-1', transport: true });
    click(button('Play'));
    expect(playMock).toHaveBeenCalledTimes(1);
    click(button('Pause'));
    expect(pauseMock).toHaveBeenCalledTimes(1);
    expect(button('Play')).toBeTruthy();
  });

  it('tracks the media element own play / pause / ended events', () => {
    const video = render({ videoId: 'vid-1', transport: true });
    fire(video, 'play');
    expect(button('Pause')).toBeTruthy();
    fire(video, 'pause');
    expect(button('Play')).toBeTruthy();
    fire(video, 'play');
    fire(video, 'ended');
    expect(button('Play')).toBeTruthy();
  });

  it('seeks from the transport through the window clamp', () => {
    const video = render({ videoId: 'vid-1', transport: true, window: { start: 10, end: 20 } });
    click(button('Previous frame'));
    expect(video.currentTime).toBe(10);
  });

  it('frame-steps by exactly one frame at the caller-supplied fps', () => {
    const video = render({ videoId: 'vid-1', transport: true, fps: 25 });
    durations.set(video, 60);
    fire(video, 'loadedmetadata');
    click(button('Next frame'));
    expect(video.currentTime).toBeCloseTo(1 / 25, 10);
    expect(scrubber().value).toBe(String(1 / 25));
  });

  it('L accelerates the forward rate and K returns to 1x and pauses', () => {
    const video = render({ videoId: 'vid-1', transport: true });
    press('l');
    expect(playMock).toHaveBeenCalled();
    expect(video.playbackRate).toBe(1);
    press('l');
    expect(video.playbackRate).toBe(2);
    press('k');
    expect(video.playbackRate).toBe(1);
    expect(pauseMock).toHaveBeenCalled();
    expect(button('Play')).toBeTruthy();
  });

  it('J shuttles in reverse by walking the playhead back a frame at a time', () => {
    vi.useFakeTimers();
    try {
      const video = render({ videoId: 'vid-1', transport: true });
      durations.set(video, 60);
      fire(video, 'loadedmetadata');
      video.currentTime = 5;
      press('j');
      // Reverse cannot ride play() — HTMLMediaElement has no negative rate.
      expect(pauseMock).toHaveBeenCalled();
      act(() => {
        vi.advanceTimersByTime(100); // 3 frames at the default 30fps
      });
      expect(video.currentTime).toBeCloseTo(5 - 3 / 30, 6);
      expect(button('Pause')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it('ignores the pause event the reverse shuttle itself raises', () => {
    // The reverse driver pauses the element; if that pause read as "the user
    // stopped playback" the shuttle would immediately kill itself.
    vi.useFakeTimers();
    try {
      const video = render({ videoId: 'vid-1', transport: true });
      video.currentTime = 5;
      press('j');
      fire(video, 'pause');
      expect(button('Pause')).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(100);
      });
      expect(video.currentTime).toBeLessThan(5);
    } finally {
      vi.useRealTimers();
    }
  });

  it('drops the reverse shuttle when the element reports ended', () => {
    // `ended` is the ONE stop signal the shuttle honours besides an explicit
    // pause: the element is paused while shuttling, so a queued end event can
    // still land after J. Without this the timer would keep walking the head.
    vi.useFakeTimers();
    try {
      const video = render({ videoId: 'vid-1', transport: true });
      video.currentTime = 5;
      press('j');
      fire(video, 'ended');
      const parked = video.currentTime;
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(video.currentTime).toBe(parked);
      expect(button('Play')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it('stops the reverse shuttle at the window start and resets to 1x', () => {
    vi.useFakeTimers();
    try {
      const video = render({ videoId: 'vid-1', transport: true, window: { start: 2, end: 20 } });
      fire(video, 'loadedmetadata');
      video.currentTime = 2.05;
      press('j');
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(video.currentTime).toBe(2);
      expect(video.playbackRate).toBe(1);
      expect(button('Play')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it('stops the reverse shuttle the tick the head LANDS on the window start', () => {
    // The floor test is `next <= floorSec`, NOT `< floorSec`. A head that lands
    // EXACTLY on the in-point must stop THERE: under a strict `<` the shuttle
    // survives that tick still flagged as playing (the toggle keeps reading
    // "Pause" while the head is parked on the in-point) and only gives up one
    // frame later. The test above straddles the floor (2.05 is not a whole
    // number of frames above 2), so it cannot see the difference — this one
    // lands on it exactly. fps 32 is deliberate: 1/32 = 0.03125 is exactly
    // representable in binary, so `2.03125 - 1/32` is EXACTLY 2 and the
    // boundary is hit rather than approached.
    vi.useFakeTimers();
    try {
      const video = render({
        videoId: 'vid-1',
        transport: true,
        fps: 32,
        window: { start: 2, end: 20 },
      });
      fire(video, 'loadedmetadata');
      video.currentTime = 2.03125; // exactly one frame above the in-point
      press('j');
      act(() => {
        vi.advanceTimersByTime(32); // exactly ONE 31.25ms frame interval
      });
      expect(video.currentTime).toBe(2);
      expect(button('Play')).toBeTruthy(); // stopped on arrival, not a tick later
      expect(video.playbackRate).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  // -------------------------------------------------------------------------
  // GRIND 1 — the transport must be scoped to the WINDOW.
  //
  // Four production mounts (CaptionDesigner, CaptionStage, ExportStage,
  // CandidateReview) preview a few-second candidate inside a long source. The
  // reverse shuttle already floors at `win.start` (see the two tests above), so
  // the window was honoured in ONE place and missed in the two the user looks
  // at: the scrubber's range and the total-time readout.
  // -------------------------------------------------------------------------
  it('scopes the transport scrubber to the window, not to the whole source', () => {
    const video = render({ videoId: 'vid-1', transport: true, window: { start: 40, end: 44 } });
    durations.set(video, 600); // a 10-minute source holding a 4-second candidate
    fire(video, 'loadedmetadata');
    video.currentTime = 42;
    fire(video, 'timeupdate');
    expect(scrubber().min).toBe('40');
    expect(scrubber().max).toBe('44');
    expect(scrubber().value).toBe('42');
  });

  it('reads out the CLIP length in window mode, not the source length', () => {
    const video = render({ videoId: 'vid-1', transport: true, window: { start: 40, end: 44 } });
    durations.set(video, 600);
    fire(video, 'loadedmetadata');
    video.currentTime = 42;
    fire(video, 'timeupdate');
    expect(group().querySelector('.transport__time')?.textContent).toBe('0:02 / 0:04');
  });

  it('spans the whole source when there is no window', () => {
    // The other side of the same branch: without a window nothing narrows.
    const video = render({ videoId: 'vid-1', transport: true });
    durations.set(video, 600);
    fire(video, 'loadedmetadata');
    expect(scrubber().min).toBe('0');
    expect(scrubber().max).toBe('600');
  });

  // -------------------------------------------------------------------------
  // GRIND 1 — stop-path symmetry.
  //
  // The window floor (`setPlaying(false); setRate(1)`) and an explicit pause
  // (same pair) both clear the shuttle; `ended` cleared only `playing` and left
  // a NEGATIVE rate armed, so the next Play re-entered the reverse driver and
  // walked the head BACKWARD. jsdom has no decoder, so "plays forward" is not
  // observable — the falsifiable half is that the head must not move backward,
  // which is precisely the defect.
  //
  // NOT the whole enumeration: there is a FOURTH stop path (the window-END
  // stop), covered by the GRIND 2 test below. Closing `ended` here left that one
  // open, which is exactly what three reviewers caught.
  // -------------------------------------------------------------------------
  it('clears the shuttle rate when the media ends so the next Play is not a reverse walk', () => {
    vi.useFakeTimers();
    try {
      const video = render({ videoId: 'vid-1', transport: true });
      durations.set(video, 60);
      fire(video, 'loadedmetadata');
      video.currentTime = 5;
      press('j'); // reverse shuttle armed
      fire(video, 'ended'); // the element reports the end while rate is negative
      click(button('Play')); // ...and the user starts playback again
      const resumed = video.currentTime;
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(video.currentTime).toBe(resumed);
      expect(button('Pause')).toBeTruthy(); // playing forward, not parked
    } finally {
      vi.useRealTimers();
    }
  });

  // -------------------------------------------------------------------------
  // GRIND 2 — the FOURTH stop path.
  //
  // Three independent reviewers measured the same overclaim: the comment above
  // the shuttle driver enumerated THREE stop paths when the file has FOUR. The
  // window-END stop (Player.tsx, inside handleTimeUpdate) calls `video.pause()`
  // and the `onEnded` PROP — never the DOM `ended` event — so `syncEnded`, the
  // only listener that resets the rate, does not run there. A forward L-shuttle
  // therefore SURVIVED the out point: `playbackRate` stayed 2x/4x on the
  // element and the `role="status"` region kept announcing "2x" while playback
  // was stopped, so the next Play resumed at that rate. That is precisely the
  // defect the DOM-`ended` fix closed, one stop path over — and it lives in
  // window mode, the mode four of the seven production mounts use.
  // -------------------------------------------------------------------------
  it('clears the shuttle rate at the WINDOW-END stop (the fourth stop path)', () => {
    const video = render({ videoId: 'vid-1', transport: true, window: { start: 40, end: 44 } });
    durations.set(video, 600);
    fire(video, 'loadedmetadata');
    video.currentTime = 42;
    fire(video, 'timeupdate');
    press('l'); // 1x forward, playing
    press('l'); // -> 2x
    expect(video.playbackRate).toBe(2);
    expect(group().querySelector('.transport__rate')?.textContent).toBe('2x');

    // ...and playback rolls on to the out point.
    video.currentTime = 43.99;
    fire(video, 'timeupdate'); // the window-end stop: pause + snap + onEnded PROP
    fire(video, 'pause'); // the DOM event a real element raises for that pause

    expect(video.currentTime).toBe(44); // snapped onto the out point
    expect(video.playbackRate).toBe(1); // the shuttle is OVER, on the element too
    expect(group().querySelector('.transport__rate')?.textContent).toBe('');
    expect(button('Play')).toBeTruthy();
  });

  it('ends a REVERSE shuttle stopped at the out point, where NO pause event fires', () => {
    // The reachable state where the window-end stop must clear `playing` ITSELF:
    // a reverse shuttle keeps the element PAUSED while `playing` stays true, and
    // a real element raises NO `pause` event for a pause() on an already-paused
    // element — so `syncPaused` cannot be the one to clear it there. Seeking the
    // head onto the out point mid-shuttle gets there: neither the scrubber's
    // `handleSeek` nor the ref handle's `seek()` (keyboard review) touches the
    // rate, so the stop path runs with a NEGATIVE rate armed. This is also the
    // one case where the retired `!playing` guard's premise is exercised rather
    // than argued: the rate must come back to 1 or the driver keeps walking.
    vi.useFakeTimers();
    try {
      const video = render({ videoId: 'vid-1', transport: true, window: { start: 40, end: 44 } });
      durations.set(video, 600);
      fire(video, 'loadedmetadata');
      video.currentTime = 42;
      fire(video, 'timeupdate');
      press('j'); // reverse shuttle: element paused, `playing` true, rate -1
      expect(group().querySelector('.transport__rate')?.textContent).toBe('1x rev');

      video.currentTime = 43.99; // seeked onto the out point mid-shuttle
      fire(video, 'timeupdate'); // the seek's own timeupdate — and NO pause event

      expect(video.currentTime).toBe(44);
      expect(group().querySelector('.transport__rate')?.textContent).toBe('');
      expect(button('Play')).toBeTruthy(); // not still claiming to play
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(video.currentTime).toBe(44); // the reverse driver is torn down
    } finally {
      vi.useRealTimers();
    }
  });

  it('seeds duration and playhead from the ELEMENT when the transport mounts late', () => {
    // `loadedmetadata` and `durationchange` fire once per load, so a call site
    // that turns `transport` ON after metadata already landed never sees either
    // event again. Syncing from events ALONE left such a mount with a dead
    // scrubber at min === max === 0; the effect must seed off the element too.
    const video = render({ videoId: 'vid-1' }); // native bar first
    durations.set(video, 120);
    video.currentTime = 30;
    render({ videoId: 'vid-1', transport: true }); // ...transport toggled on later
    expect(scrubber().max).toBe('120');
    expect(scrubber().value).toBe('30');
  });
});
