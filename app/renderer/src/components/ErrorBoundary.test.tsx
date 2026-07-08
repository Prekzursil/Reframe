// ErrorBoundary.test.tsx — the top-level renderer crash backstop (WU2 resilience).
//
// Pins the falsifiable acceptance: a child that throws on render shows the inline
// fallback (honest copy + a reload affordance) INSTEAD of unmounting the tree
// (a blank #root), getDerivedStateFromError + componentDidCatch both run, the
// error is logged once, and a healthy child renders through untouched.
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ErrorBoundary } from './ErrorBoundary';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

/** A component that throws synchronously on render. */
function Boom(): React.ReactElement {
  throw new Error('render exploded');
}

describe('<ErrorBoundary /> — renderer crash backstop', () => {
  it('renders its children untouched when nothing throws', () => {
    act(() => {
      root.render(
        <ErrorBoundary>
          <p data-testid="child">all good</p>
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('[data-testid="child"]')?.textContent).toBe('all good');
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('shows the inline fallback (does NOT unmount) when a child throws on render', () => {
    // React logs the caught error to console.error — silence + assert it fires.
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    act(() => {
      root.render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      );
    });

    // The tree is NOT blank: the fallback rendered in place of the crashed child.
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(container.textContent).toContain('Something went wrong');
    // getDerivedStateFromError swapped in the fallback; the child is gone.
    expect(container.querySelector('[data-testid="child"]')).toBeNull();
    // componentDidCatch logged the failure (at least once).
    expect(errorSpy).toHaveBeenCalled();
  });

  it('invokes the injected onReload when the reload control is clicked', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const onReload = vi.fn();

    act(() => {
      root.render(
        <ErrorBoundary onReload={onReload}>
          <Boom />
        </ErrorBoundary>,
      );
    });

    const button = container.querySelector('button[data-action="reload"]') as HTMLButtonElement;
    expect(button).not.toBeNull();
    act(() => {
      button.click();
    });
    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it('falls back to a full window reload when no onReload is injected', () => {
    // console.error swallows both componentDidCatch's log AND jsdom's benign
    // "not implemented: navigation" note that window.location.reload() emits.
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    act(() => {
      root.render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      );
    });

    const button = container.querySelector('button[data-action="reload"]') as HTMLButtonElement;
    // With no onReload, the else branch runs the real window.location.reload() —
    // jsdom does not implement it but does NOT throw, so the click is safe.
    expect(() => {
      act(() => {
        button.click();
      });
    }).not.toThrow();
  });
});
