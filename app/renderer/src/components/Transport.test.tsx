// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  TRANSPORT_DEFAULT_FPS,
  TRANSPORT_MAX_SHUTTLE_RATE,
  Transport,
  clampTime,
  clampToSpan,
  formatTimecode,
  frameDuration,
  nextShuttleRate,
  rateLabel,
  type TransportProps,
} from './Transport';

// React 18's act() wants this flag in a bare jsdom environment.
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// pure helpers
// ---------------------------------------------------------------------------
describe('formatTimecode', () => {
  it('renders M:SS below one hour', () => {
    expect(formatTimecode(0)).toBe('0:00');
    expect(formatTimecode(7)).toBe('0:07');
    expect(formatTimecode(65)).toBe('1:05');
    expect(formatTimecode(599.9)).toBe('9:59');
  });

  it('renders H:MM:SS at or above one hour', () => {
    expect(formatTimecode(3600)).toBe('1:00:00');
    expect(formatTimecode(3661)).toBe('1:01:01');
  });

  it('floors non-finite and negative input to 0:00', () => {
    expect(formatTimecode(Number.NaN)).toBe('0:00');
    expect(formatTimecode(Number.POSITIVE_INFINITY)).toBe('0:00');
    expect(formatTimecode(-12)).toBe('0:00');
  });
});

describe('clampTime', () => {
  it('passes through in-range values', () => {
    expect(clampTime(0, 10)).toBe(0);
    expect(clampTime(4.25, 10)).toBe(4.25);
    expect(clampTime(10, 10)).toBe(10);
  });

  it('clamps below zero and past the duration', () => {
    expect(clampTime(-3, 10)).toBe(0);
    expect(clampTime(99, 10)).toBe(10);
  });

  it('treats a non-finite or non-positive duration as an empty range', () => {
    expect(clampTime(5, Number.NaN)).toBe(0);
    expect(clampTime(5, 0)).toBe(0);
  });

  it('treats a non-finite time as 0', () => {
    expect(clampTime(Number.NaN, 10)).toBe(0);
  });
});

describe('frameDuration', () => {
  it('is the reciprocal of a positive frame rate', () => {
    expect(frameDuration(30)).toBeCloseTo(1 / 30, 10);
    expect(frameDuration(60)).toBeCloseTo(1 / 60, 10);
  });

  it('falls back to the default rate for a non-positive rate', () => {
    expect(frameDuration(0)).toBeCloseTo(1 / TRANSPORT_DEFAULT_FPS, 10);
    expect(frameDuration(-5)).toBeCloseTo(1 / TRANSPORT_DEFAULT_FPS, 10);
  });
});

describe('nextShuttleRate', () => {
  it('starts a shuttle at 1x in the requested direction', () => {
    expect(nextShuttleRate(0, 1)).toBe(1);
    expect(nextShuttleRate(0, -1)).toBe(-1);
  });

  it('doubles when already shuttling the same way, capped at the maximum', () => {
    expect(nextShuttleRate(1, 1)).toBe(2);
    expect(nextShuttleRate(2, 1)).toBe(4);
    expect(nextShuttleRate(TRANSPORT_MAX_SHUTTLE_RATE, 1)).toBe(TRANSPORT_MAX_SHUTTLE_RATE);
    expect(nextShuttleRate(-1, -1)).toBe(-2);
    expect(nextShuttleRate(-TRANSPORT_MAX_SHUTTLE_RATE, -1)).toBe(-TRANSPORT_MAX_SHUTTLE_RATE);
  });

  it('resets to 1x when the direction reverses', () => {
    expect(nextShuttleRate(-2, 1)).toBe(1);
    expect(nextShuttleRate(4, -1)).toBe(-1);
  });
});

describe('rateLabel', () => {
  it('labels a forward rate', () => {
    expect(rateLabel(1)).toBe('1x');
    expect(rateLabel(2)).toBe('2x');
  });

  it('labels a reverse rate without a minus sign', () => {
    expect(rateLabel(-2)).toBe('2x rev');
  });
});

// ---------------------------------------------------------------------------
// component
// ---------------------------------------------------------------------------
let container: HTMLDivElement;
let root: Root;
const onPlayPause = vi.fn();
const onSeek = vi.fn();
const onRateChange = vi.fn();

const baseProps: TransportProps = {
  currentTime: 0,
  duration: 100,
  isPlaying: false,
  onPlayPause,
  onSeek,
  onRateChange,
};

beforeEach(() => {
  onPlayPause.mockClear();
  onSeek.mockClear();
  onRateChange.mockClear();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(overrides: Partial<TransportProps> = {}): HTMLElement {
  act(() => {
    root.render(<Transport {...baseProps} {...overrides} />);
  });
  const group = container.querySelector('[role="group"]');
  expect(group).not.toBeNull();
  return group as HTMLElement;
}

function button(group: HTMLElement, name: string): HTMLButtonElement {
  const el = group.querySelector(`button[aria-label="${name}"]`);
  expect(el).not.toBeNull();
  return el as HTMLButtonElement;
}

function scrubber(group: HTMLElement): HTMLInputElement {
  const el = group.querySelector('input[type="range"]');
  expect(el).not.toBeNull();
  return el as HTMLInputElement;
}

function click(el: HTMLElement): void {
  act(() => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

function press(el: HTMLElement, key: string): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  act(() => {
    el.dispatchEvent(event);
  });
  return event;
}

/** Drive a controlled range input past React's value tracker. */
function setRangeValue(el: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
  setter?.call(el, value);
  act(() => {
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('Transport rendering', () => {
  it('renders a named group with named controls (no icon-only mystery buttons)', () => {
    const group = render();
    expect(group.getAttribute('aria-label')).toBe('Video transport');
    expect(button(group, 'Previous frame')).toBeTruthy();
    expect(button(group, 'Play')).toBeTruthy();
    expect(button(group, 'Next frame')).toBeTruthy();
    // Every control is a real <button type="button"> so Enter/Space work natively.
    for (const el of group.querySelectorAll('button')) {
      expect(el.getAttribute('type')).toBe('button');
    }
    // The icons are decorative — the accessible name lives on the button.
    for (const svg of group.querySelectorAll('svg')) {
      expect(svg.getAttribute('aria-hidden')).toBe('true');
    }
  });

  it('names the toggle Pause while playing', () => {
    const group = render({ isPlaying: true });
    expect(button(group, 'Pause')).toBeTruthy();
    expect(group.querySelector('button[aria-label="Play"]')).toBeNull();
  });

  it('shows current / total time', () => {
    const group = render({ currentTime: 65, duration: 3661 });
    const time = group.querySelector('.transport__time');
    expect(time?.textContent).toBe('1:05 / 1:01:01');
  });

  it('renders the scrubber as a frame-stepping range with an accessible name', () => {
    const group = render({ currentTime: 12, duration: 100 });
    const range = scrubber(group);
    expect(range.getAttribute('aria-label')).toBe('Seek');
    expect(range.getAttribute('min')).toBe('0');
    expect(range.getAttribute('max')).toBe('100');
    expect(Number(range.getAttribute('step'))).toBeCloseTo(1 / TRANSPORT_DEFAULT_FPS, 10);
    expect(range.value).toBe('12');
    expect(range.getAttribute('aria-valuetext')).toBe('0:12 of 1:40');
  });

  it('clamps the scrubber position into the media range', () => {
    expect(scrubber(render({ currentTime: 500, duration: 100 })).value).toBe('100');
  });

  it('keeps the rate status region mounted and empty at 1x', () => {
    const group = render();
    const status = group.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent).toBe('');
  });

  it('announces a shuttle rate', () => {
    expect(render({ rate: 2 }).querySelector('[role="status"]')?.textContent).toBe('2x');
    expect(render({ rate: -2 }).querySelector('[role="status"]')?.textContent).toBe('2x rev');
  });

  it('honours a className override', () => {
    expect(render({ className: 'custom-transport' }).className).toBe('custom-transport');
  });
});

describe('Transport pointer controls', () => {
  it('requests play from the toggle while paused, and pause while playing', () => {
    click(button(render(), 'Play'));
    expect(onPlayPause).toHaveBeenCalledWith(true);

    onPlayPause.mockClear();
    click(button(render({ isPlaying: true }), 'Pause'));
    expect(onPlayPause).toHaveBeenCalledWith(false);
  });

  it('steps one frame forward and back, pausing first', () => {
    const group = render({ currentTime: 10, isPlaying: true });
    click(button(group, 'Next frame'));
    expect(onPlayPause).toHaveBeenCalledWith(false);
    expect(onSeek).toHaveBeenLastCalledWith(10 + 1 / TRANSPORT_DEFAULT_FPS);

    click(button(group, 'Previous frame'));
    expect(onSeek).toHaveBeenLastCalledWith(10 - 1 / TRANSPORT_DEFAULT_FPS);
  });

  it('steps at the caller-supplied frame rate', () => {
    click(button(render({ currentTime: 10, fps: 60 }), 'Next frame'));
    expect(onSeek).toHaveBeenLastCalledWith(10 + 1 / 60);
  });

  it('falls back to the default frame rate when fps is not positive', () => {
    click(button(render({ currentTime: 10, fps: 0 }), 'Next frame'));
    expect(onSeek).toHaveBeenLastCalledWith(10 + 1 / TRANSPORT_DEFAULT_FPS);
  });

  it('never steps outside the media range', () => {
    click(button(render({ currentTime: 0 }), 'Previous frame'));
    expect(onSeek).toHaveBeenLastCalledWith(0);
  });

  it('seeks from a scrubber drag', () => {
    setRangeValue(scrubber(render({ duration: 100 })), '42.5');
    expect(onSeek).toHaveBeenLastCalledWith(42.5);
  });
});

describe('Transport keyboard', () => {
  it('toggles playback on space', () => {
    const event = press(render(), ' ');
    expect(onPlayPause).toHaveBeenCalledWith(true);
    expect(event.defaultPrevented).toBe(true);
  });

  it('leaves space to the browser when a button has focus (no double toggle)', () => {
    const group = render();
    press(button(group, 'Play'), ' ');
    expect(onPlayPause).not.toHaveBeenCalled();
  });

  it('frame-steps with the arrow keys', () => {
    const group = render({ currentTime: 10 });
    press(group, 'ArrowRight');
    expect(onSeek).toHaveBeenLastCalledWith(10 + 1 / TRANSPORT_DEFAULT_FPS);
    press(group, 'ArrowLeft');
    expect(onSeek).toHaveBeenLastCalledWith(10 - 1 / TRANSPORT_DEFAULT_FPS);
  });

  it('leaves the arrow keys to the scrubber when it has focus', () => {
    const group = render({ currentTime: 10 });
    const event = press(scrubber(group), 'ArrowLeft');
    expect(onSeek).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it('K pauses at 1x', () => {
    press(render({ isPlaying: true, rate: 4 }), 'k');
    expect(onRateChange).toHaveBeenCalledWith(1);
    expect(onPlayPause).toHaveBeenCalledWith(false);
  });

  it('L shuttles forward, doubling on each press while playing', () => {
    press(render(), 'l');
    expect(onRateChange).toHaveBeenLastCalledWith(1);
    expect(onPlayPause).toHaveBeenLastCalledWith(true);

    press(render({ isPlaying: true, rate: 1 }), 'L');
    expect(onRateChange).toHaveBeenLastCalledWith(2);
  });

  it('J shuttles in reverse, doubling on each press while playing', () => {
    press(render(), 'j');
    expect(onRateChange).toHaveBeenLastCalledWith(-1);
    expect(onPlayPause).toHaveBeenLastCalledWith(true);

    press(render({ isPlaying: true, rate: -1 }), 'J');
    expect(onRateChange).toHaveBeenLastCalledWith(-2);
  });

  it('shuttles without an onRateChange listener', () => {
    const group = render({ onRateChange: undefined });
    press(group, 'l');
    expect(onPlayPause).toHaveBeenLastCalledWith(true);
    press(group, 'k');
    expect(onPlayPause).toHaveBeenLastCalledWith(false);
  });

  it('ignores unrelated keys', () => {
    const event = press(render(), 'x');
    expect(onPlayPause).not.toHaveBeenCalled();
    expect(onSeek).not.toHaveBeenCalled();
    expect(onRateChange).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// GRIND 1 — the playable SPAN.
//
// `duration` alone can only ever describe a transport that spans the WHOLE
// source. FOUR of the seven production mounts run the Player in window mode
// (CaptionDesigner, CaptionStage, ExportStage, CandidateReview) where the
// playable range is a few seconds inside a multi-minute source — exactly the
// candidate-preview surfaces L8 exists for. Scoping the scrubber to the source
// there produces a track whose thumb only crosses a sliver before the owner's
// window clamp snaps it back, and a total-time readout of the SOURCE length
// instead of the clip length.
//
// The fix keeps every emitted time SOURCE-ABSOLUTE (so `onSeek` still lines up
// with the owner's window clamp and with a future timeline playhead) and moves
// only the BOUNDS and the human-facing readout into the span.
// ---------------------------------------------------------------------------
describe('clampToSpan', () => {
  it('passes through a time inside the span, endpoints included', () => {
    expect(clampToSpan(42, 40, 44)).toBe(42);
    expect(clampToSpan(40, 40, 44)).toBe(40);
    expect(clampToSpan(44, 40, 44)).toBe(44);
  });

  it('clamps below the in-point and past the out-point', () => {
    expect(clampToSpan(0, 40, 44)).toBe(40);
    expect(clampToSpan(600, 40, 44)).toBe(44);
  });

  it('collapses a non-finite time onto the in-point', () => {
    expect(clampToSpan(Number.NaN, 40, 44)).toBe(40);
  });

  it('collapses an inverted span onto its in-point', () => {
    // A malformed window must not widen the range it is supposed to narrow.
    expect(clampToSpan(42, 44, 40)).toBe(44);
  });
});

describe('Transport playable span', () => {
  const windowed: Partial<TransportProps> = {
    currentTime: 42,
    duration: 600,
    startTime: 40,
    endTime: 44,
  };

  it('bounds the scrubber to the window, not to the whole source', () => {
    const range = scrubber(render(windowed));
    expect(range.min).toBe('40');
    expect(range.max).toBe('44');
    expect(range.value).toBe('42');
  });

  it('reads out time relative to the window, not to the source', () => {
    const group = render(windowed);
    expect(group.querySelector('.transport__time')?.textContent).toBe('0:02 / 0:04');
    expect(scrubber(group).getAttribute('aria-valuetext')).toBe('0:02 of 0:04');
  });

  it('holds the thumb inside the window when the owner reports a time outside it', () => {
    const range = scrubber(render({ ...windowed, currentTime: 0 }));
    expect(range.value).toBe('40');
  });

  it('frame-steps inside the window and stops at the in-point', () => {
    const group = render({ ...windowed, currentTime: 40, fps: 25 });
    click(button(group, 'Previous frame'));
    expect(onSeek).toHaveBeenLastCalledWith(40); // already parked on the in-point
    click(button(group, 'Next frame'));
    expect(onSeek.mock.lastCall?.[0]).toBeCloseTo(40 + 1 / 25, 10);
  });

  it('clamps a scrub to the out-point instead of the source duration', () => {
    setRangeValue(scrubber(render(windowed)), '600');
    expect(onSeek).toHaveBeenLastCalledWith(44);
  });
});
