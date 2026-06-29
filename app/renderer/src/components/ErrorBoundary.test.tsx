// ErrorBoundary.test.tsx — contains a child render throw to an inline fallback
// instead of letting it unmount the whole tree (the Library roll-up guard).
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ErrorBoundary } from './ErrorBoundary';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // React logs caught render errors to console.error; silence it for clean output.
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  consoleError.mockRestore();
});

function Boom({ message }: { message: string }): never {
  throw new Error(message);
}

describe('<ErrorBoundary />', () => {
  it('renders its children when nothing throws', async () => {
    await act(async () => {
      root.render(
        <ErrorBoundary>
          <p className="ok">all good</p>
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('.ok')?.textContent).toBe('all good');
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('contains a child render throw to the default inline alert', async () => {
    await act(async () => {
      root.render(
        <ErrorBoundary label="Panel failed">
          <Boom message="kaboom" />
        </ErrorBoundary>,
      );
    });
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain('kaboom');
    expect(alert?.getAttribute('aria-label')).toBe('Panel failed');
  });

  it('renders a custom fallback and reports via onError', async () => {
    const onError = vi.fn();
    await act(async () => {
      root.render(
        <ErrorBoundary fallback={(err) => <span className="fb">caught: {err.message}</span>} onError={onError}>
          <Boom message="nope" />
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('.fb')?.textContent).toBe('caught: nope');
    expect(onError).toHaveBeenCalledOnce();
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
  });

  it('coerces a non-Error throw into an Error message', async () => {
    function ThrowString(): never {
      // Throw via an `unknown`-typed binding (not a literal) so the non-Error
      // coercion branch is exercised without tripping throw-literal lints.
      const notAnError: unknown = 'plain string failure';
      throw notAnError;
    }
    await act(async () => {
      root.render(
        <ErrorBoundary>
          <ThrowString />
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain string failure');
  });
});
