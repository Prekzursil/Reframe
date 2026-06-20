// useAutosave.test.tsx — debounced, gated workspace autosave (UX/QoL WU-11).
//
// Fake timers + a fake `save` fn pin the falsifiable acceptance:
//   * enabled + N rapid schedule()s -> EXACTLY ONE save after `debounceMs`;
//   * disabled -> ZERO saves;
//   * a config flip / unmount drops a pending timer (no stale, wrongly-timed save);
//   * the trailing save runs the LATEST `save` closure (ref-tracked, not stale).
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { useAutosave, type AutosaveConfig, type AutosaveControls } from './useAutosave';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('useAutosave (hook)', () => {
  let container: HTMLDivElement;
  let root: Root;
  let controls: AutosaveControls;

  function Harness(props: { save: () => void; config: AutosaveConfig }): React.ReactElement {
    controls = useAutosave(props.save, props.config);
    return React.createElement('div', null, null);
  }

  function render(props: { save: () => void; config: AutosaveConfig }): void {
    act(() => {
      root.render(React.createElement(Harness, props));
    });
  }

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('coalesces N rapid edits into ONE save after the debounce window', () => {
    const save = vi.fn();
    render({ save, config: { enabled: true, debounceMs: 1500 } });

    act(() => {
      controls.schedule();
      controls.schedule();
      controls.schedule();
    });
    // Before the window closes: nothing has fired.
    act(() => vi.advanceTimersByTime(1499));
    expect(save).not.toHaveBeenCalled();
    // One tick past the window: exactly one coalesced save.
    act(() => vi.advanceTimersByTime(1));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('re-arms the timer on each edit (only the trailing edit fires)', () => {
    const save = vi.fn();
    render({ save, config: { enabled: true, debounceMs: 1000 } });

    act(() => controls.schedule());
    act(() => vi.advanceTimersByTime(800)); // not yet
    act(() => controls.schedule()); // re-arm: the 800ms of waiting is discarded
    act(() => vi.advanceTimersByTime(800));
    expect(save).not.toHaveBeenCalled(); // would have fired at 1000 without re-arm
    act(() => vi.advanceTimersByTime(200));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('never saves when autosave is disabled', () => {
    const save = vi.fn();
    render({ save, config: { enabled: false, debounceMs: 1500 } });

    act(() => {
      controls.schedule();
      controls.schedule();
    });
    act(() => vi.advanceTimersByTime(10000));
    expect(save).not.toHaveBeenCalled();
  });

  it('drops a pending save when autosave is turned off mid-window', () => {
    const save = vi.fn();
    render({ save, config: { enabled: true, debounceMs: 1500 } });
    act(() => controls.schedule());
    act(() => vi.advanceTimersByTime(500));
    // Flip enabled -> false: the config-change effect clears the pending timer.
    render({ save, config: { enabled: false, debounceMs: 1500 } });
    act(() => vi.advanceTimersByTime(5000));
    expect(save).not.toHaveBeenCalled();
  });

  it('clears a pending save on unmount', () => {
    const save = vi.fn();
    render({ save, config: { enabled: true, debounceMs: 1500 } });
    act(() => controls.schedule());
    act(() => vi.advanceTimersByTime(500));
    act(() => root.unmount());
    act(() => vi.advanceTimersByTime(5000));
    expect(save).not.toHaveBeenCalled();
  });

  it('runs the latest save closure, not the one captured at schedule time', () => {
    const first = vi.fn();
    const second = vi.fn();
    render({ save: first, config: { enabled: true, debounceMs: 1000 } });
    act(() => controls.schedule());
    // Re-render with a fresh save fn before the timer fires (e.g. a new project).
    render({ save: second, config: { enabled: true, debounceMs: 1000 } });
    act(() => vi.advanceTimersByTime(1000));
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
