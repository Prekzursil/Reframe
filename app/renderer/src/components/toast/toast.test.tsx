// @vitest-environment jsdom
// toast.test.tsx — ToastProvider reducer/timers, useToast accessors, ToastHost
// portal rendering (P2 U3): enqueue / dismiss / auto-expire / kinds / action slot.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  ToastProvider,
  toastReducer,
  DEFAULT_DURATION_MS,
  type Toast,
  type ToastApi,
  type ToastReducerAction,
} from './ToastProvider';
import { ToastHost } from './ToastHost';
import { useToast, useToastOptional } from './useToast';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- reducer (pure) ---------------------------------------------------------

function makeToast(id: number, kind: Toast['kind'] = 'info'): Toast {
  return { id, kind, message: `m${id}`, durationMs: null };
}

describe('toastReducer', () => {
  it('push appends in enqueue order', () => {
    let state: readonly Toast[] = [];
    state = toastReducer(state, { type: 'push', toast: makeToast(1) });
    state = toastReducer(state, { type: 'push', toast: makeToast(2) });
    expect(state.map((t) => t.id)).toEqual([1, 2]);
  });

  it('dismiss removes exactly the matching id and ignores unknown ids', () => {
    let state: readonly Toast[] = [makeToast(1), makeToast(2)];
    const untouched = toastReducer(state, { type: 'dismiss', id: 99 });
    expect(untouched).toBe(state); // unknown id: same reference, no churn
    state = toastReducer(state, { type: 'dismiss', id: 1 });
    expect(state.map((t) => t.id)).toEqual([2]);
  });

  it('clear empties the queue', () => {
    const state: readonly Toast[] = [makeToast(1), makeToast(2)];
    expect(toastReducer(state, { type: 'clear' })).toEqual([]);
    const empty: readonly Toast[] = [];
    expect(toastReducer(empty, { type: 'clear' })).toBe(empty);
  });

  it('returns state unchanged for unknown actions', () => {
    const state: readonly Toast[] = [makeToast(1)];
    const bogus = { type: 'bogus' } as unknown as ToastReducerAction;
    expect(toastReducer(state, bogus)).toBe(state);
  });
});

// ---- provider + host (DOM) ---------------------------------------------------

let toast: ToastApi | null = null;

function Capture(): null {
  toast = useToast();
  return null;
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  toast = null;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

function mountHost(): void {
  act(() => {
    root.render(
      React.createElement(
        ToastProvider,
        null,
        React.createElement(Capture, null),
        React.createElement(ToastHost, null),
      ),
    );
  });
}

function bodyToasts(): Element[] {
  return Array.from(document.body.querySelectorAll('.toast'));
}

describe('ToastProvider + ToastHost', () => {
  it('enqueues toasts of every kind with matching classes and roles', () => {
    mountHost();
    act(() => {
      toast!.info('hello');
      toast!.success('saved');
      toast!.error('broke');
    });
    const els = bodyToasts();
    expect(els).toHaveLength(3);
    expect(els[0].className).toContain('toast--info');
    expect(els[0].getAttribute('role')).toBe('status');
    expect(els[0].textContent).toContain('hello');
    expect(els[1].className).toContain('toast--success');
    expect(els[1].getAttribute('role')).toBe('status');
    expect(els[2].className).toContain('toast--error');
    expect(els[2].getAttribute('role')).toBe('alert');
  });

  it('push honors an explicit kind option and returns usable ids', () => {
    mountHost();
    let a = 0;
    let b = 0;
    act(() => {
      a = toast!.push('first', { kind: 'success' });
      b = toast!.push('second');
    });
    expect(a).not.toBe(b);
    expect(bodyToasts()).toHaveLength(2);
    expect(bodyToasts()[0].className).toContain('toast--success');

    act(() => toast!.dismiss(a));
    const remaining = bodyToasts();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].textContent).toContain('second');
  });

  it('the close button dismisses its toast', () => {
    mountHost();
    act(() => {
      toast!.info('bye');
    });
    const close = document.body.querySelector('.toast__close') as HTMLButtonElement;
    expect(close).not.toBeNull();
    act(() => {
      close.click();
    });
    expect(bodyToasts()).toHaveLength(0);
  });

  it('clear removes all toasts at once', () => {
    mountHost();
    act(() => {
      toast!.info('one');
      toast!.error('two');
    });
    expect(bodyToasts()).toHaveLength(2);
    act(() => toast!.clear());
    expect(bodyToasts()).toHaveLength(0);
  });

  it('auto-expires info/success after the default duration; errors are sticky', () => {
    vi.useFakeTimers();
    mountHost();
    act(() => {
      toast!.info('temporary');
      toast!.success('also temporary');
      toast!.error('sticky failure');
    });
    expect(bodyToasts()).toHaveLength(3);

    act(() => {
      vi.advanceTimersByTime(DEFAULT_DURATION_MS);
    });
    const remaining = bodyToasts();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].className).toContain('toast--error');

    // Errors never auto-expire by default.
    act(() => {
      vi.advanceTimersByTime(10 * DEFAULT_DURATION_MS);
    });
    expect(bodyToasts()).toHaveLength(1);
  });

  it('explicit durationMs overrides the per-kind default (both directions)', () => {
    vi.useFakeTimers();
    mountHost();
    act(() => {
      toast!.error('quick error', { durationMs: 100 });
      toast!.info('sticky info', { durationMs: null });
    });
    expect(bodyToasts()).toHaveLength(2);

    act(() => {
      vi.advanceTimersByTime(100);
    });
    let remaining = bodyToasts();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].textContent).toContain('sticky info');

    act(() => {
      vi.advanceTimersByTime(10 * DEFAULT_DURATION_MS);
    });
    remaining = bodyToasts();
    expect(remaining).toHaveLength(1);
  });

  it('dismissing early cancels the pending auto-expire timer', () => {
    vi.useFakeTimers();
    mountHost();
    let id = 0;
    act(() => {
      id = toast!.info('going early');
    });
    act(() => toast!.dismiss(id));
    expect(bodyToasts()).toHaveLength(0);
    // Advancing past the would-be expiry must not dispatch anything odd.
    act(() => {
      vi.advanceTimersByTime(DEFAULT_DURATION_MS * 2);
    });
    expect(bodyToasts()).toHaveLength(0);
  });

  it('portals into an explicit container prop instead of document.body', () => {
    const target = document.createElement('section');
    target.id = 'custom-toast-target';
    document.body.appendChild(target);
    act(() => {
      root.render(
        <ToastProvider>
          <Capture />
          <ToastHost container={target} />
        </ToastProvider>,
      );
    });
    act(() => {
      toast!.info('in custom target');
    });
    // The toast renders inside the explicit container, not loose in the body.
    expect(target.querySelectorAll('.toast')).toHaveLength(1);
    target.remove();
  });

  it('renders nothing when there is no portal target available', () => {
    // Force the document.body fallback to null so the `if (!target)` guard
    // (ToastHost.tsx:63) returns null even with live toasts queued.
    const realBody = document.body;
    Object.defineProperty(document, 'body', {
      configurable: true,
      get: () => null,
    });
    try {
      act(() => {
        root.render(
          <ToastProvider>
            <Capture />
            <ToastHost container={null} />
          </ToastProvider>,
        );
      });
      act(() => {
        toast!.info('nowhere to go');
      });
      // No portal target -> nothing rendered anywhere (no throw).
      expect(realBody.querySelectorAll('.toast')).toHaveLength(0);
    } finally {
      Object.defineProperty(document, 'body', {
        configurable: true,
        value: realBody,
        writable: true,
      });
    }
  });

  it('renders the action button slot; clicking runs the action then dismisses', () => {
    mountHost();
    const onClick = vi.fn();
    act(() => {
      toast!.error('job failed', { action: { label: 'Retry', onClick } });
    });
    const btn = document.body.querySelector('.toast__action') as HTMLButtonElement;
    expect(btn).not.toBeNull();
    expect(btn.textContent).toBe('Retry');
    act(() => {
      btn.click();
    });
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(bodyToasts()).toHaveLength(0);
  });
});

describe('useToast accessors', () => {
  it('useToastOptional returns null outside a provider and ToastHost renders nothing', () => {
    let optional: ToastApi | null | 'unset' = 'unset';
    function CaptureOptional(): null {
      optional = useToastOptional();
      return null;
    }
    act(() => {
      root.render(
        React.createElement(
          React.Fragment,
          null,
          React.createElement(CaptureOptional, null),
          React.createElement(ToastHost, null),
        ),
      );
    });
    expect(optional).toBeNull();
    expect(bodyToasts()).toHaveLength(0);
  });

  it('useToast throws outside a provider', () => {
    class Boundary extends React.Component<
      { children?: React.ReactNode },
      { error: Error | null }
    > {
      state = { error: null as Error | null };
      static getDerivedStateFromError(error: Error): { error: Error } {
        return { error };
      }
      render(): React.ReactNode {
        return this.state.error
          ? React.createElement('div', { className: 'caught' }, this.state.error.message)
          : this.props.children;
      }
    }
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    act(() => {
      root.render(React.createElement(Boundary, null, React.createElement(Capture, null)));
    });
    expect(container.textContent).toContain('useToast must be used inside <ToastProvider>');
    errSpy.mockRestore();
  });
});
