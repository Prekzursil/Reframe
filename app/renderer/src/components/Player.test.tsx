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
