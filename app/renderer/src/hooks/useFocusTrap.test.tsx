// useFocusTrap.test.tsx — behavioural tests for the shared modal focus-trap hook
// (Lane 0 F4 / R-M10). Mounts a small harness under jsdom (React 18 createRoot +
// act, the repo convention) and exercises: initial focus (recommended selector,
// first-focusable fallback, container fallback), Tab/Shift+Tab wrap-around, the
// empty-container guard, Escape (with and without a handler), the non-trap key
// path, focus restore on unmount (and the null-previous-focus branch), and the
// detached-ref guard.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { useFocusTrap, getFocusable, type FocusTrapOptions } from './useFocusTrap';

interface HarnessProps {
  options: FocusTrapOptions;
  attachRef?: boolean;
  containerTabIndex?: number;
  count?: number;
}

/** Renders a trapped container with `count` buttons (default 3). */
function Harness({
  options,
  attachRef = true,
  containerTabIndex,
  count = 3,
}: HarnessProps): React.JSX.Element {
  const ref = useFocusTrap<HTMLDivElement>(options);
  return (
    <div ref={attachRef ? ref : undefined} tabIndex={containerTabIndex} data-testid="trap">
      {Array.from({ length: count }, (_, i) => (
        <button key={i} type="button" data-idx={i}>
          btn{i}
        </button>
      ))}
    </div>
  );
}

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

function mount(props: HarnessProps): void {
  act(() => {
    root.render(<Harness {...props} />);
  });
}

function trapEl(): HTMLDivElement {
  return container.querySelector('[data-testid="trap"]') as HTMLDivElement;
}

function buttons(): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll('button'));
}

function press(target: Element, key: string, opts: KeyboardEventInit = {}): KeyboardEvent {
  const ev = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...opts });
  act(() => {
    target.dispatchEvent(ev);
  });
  return ev;
}

describe('useFocusTrap', () => {
  describe('initial focus', () => {
    it('focuses the recommended control matched by initialFocus', () => {
      mount({ options: { initialFocus: '[data-idx="1"]' } });
      expect(document.activeElement).toBe(buttons()[1]);
    });

    it('falls back to the first focusable when initialFocus matches nothing', () => {
      mount({ options: { initialFocus: '[data-idx="99"]' } });
      expect(document.activeElement).toBe(buttons()[0]);
    });

    it('focuses the first focusable when no initialFocus is given', () => {
      mount({ options: {} });
      expect(document.activeElement).toBe(buttons()[0]);
    });

    it('focuses the container itself when there are no focusables', () => {
      mount({ options: {}, count: 0, containerTabIndex: -1 });
      expect(document.activeElement).toBe(trapEl());
    });
  });

  describe('Tab trapping', () => {
    it('wraps from the last element to the first on Tab', () => {
      mount({ options: {} });
      const btns = buttons();
      act(() => btns[2].focus());
      const ev = press(btns[2], 'Tab');
      expect(document.activeElement).toBe(btns[0]);
      expect(ev.defaultPrevented).toBe(true);
    });

    it('does not wrap on Tab when not on the last element', () => {
      mount({ options: {} });
      const btns = buttons();
      act(() => btns[0].focus());
      const ev = press(btns[0], 'Tab');
      expect(document.activeElement).toBe(btns[0]);
      expect(ev.defaultPrevented).toBe(false);
    });

    it('wraps from the first element to the last on Shift+Tab', () => {
      mount({ options: {} });
      const btns = buttons();
      act(() => btns[0].focus());
      const ev = press(btns[0], 'Tab', { shiftKey: true });
      expect(document.activeElement).toBe(btns[2]);
      expect(ev.defaultPrevented).toBe(true);
    });

    it('does not wrap on Shift+Tab when not on the first element', () => {
      mount({ options: {} });
      const btns = buttons();
      act(() => btns[2].focus());
      const ev = press(btns[2], 'Tab', { shiftKey: true });
      expect(document.activeElement).toBe(btns[2]);
      expect(ev.defaultPrevented).toBe(false);
    });

    it('swallows Tab when the container has no focusables', () => {
      mount({ options: {}, count: 0, containerTabIndex: -1 });
      const ev = press(trapEl(), 'Tab');
      expect(ev.defaultPrevented).toBe(true);
    });
  });

  describe('Escape + other keys', () => {
    it('calls onEscape when Escape is pressed', () => {
      const onEscape = vi.fn();
      mount({ options: { onEscape } });
      const ev = press(buttons()[0], 'Escape');
      expect(onEscape).toHaveBeenCalledTimes(1);
      expect(ev.defaultPrevented).toBe(true);
    });

    it('does not throw on Escape when no onEscape handler is given', () => {
      mount({ options: {} });
      expect(() => press(buttons()[0], 'Escape')).not.toThrow();
    });

    it('ignores keys other than Tab and Escape', () => {
      mount({ options: {} });
      const ev = press(buttons()[0], 'a');
      expect(ev.defaultPrevented).toBe(false);
    });
  });

  describe('focus restore', () => {
    it('restores focus to the previously-focused element on unmount', () => {
      const outside = document.createElement('button');
      document.body.appendChild(outside);
      outside.focus();
      expect(document.activeElement).toBe(outside);

      mount({ options: {} });
      expect(document.activeElement).toBe(buttons()[0]);

      act(() => root.unmount());
      expect(document.activeElement).toBe(outside);
      outside.remove();
    });

    it('does not throw when there was no previously-focused element', () => {
      // Force document.activeElement to null at mount so the restore branch sees
      // no previous element. Restored in finally so it never leaks to other tests.
      Object.defineProperty(document, 'activeElement', {
        configurable: true,
        get: () => null,
      });
      try {
        mount({ options: {} });
        expect(() => act(() => root.unmount())).not.toThrow();
      } finally {
        Reflect.deleteProperty(document, 'activeElement');
      }
    });
  });

  describe('guards', () => {
    it('is a no-op when the ref is never attached', () => {
      const before = document.activeElement;
      expect(() => mount({ options: { onEscape: vi.fn() }, attachRef: false })).not.toThrow();
      expect(document.activeElement).toBe(before);
    });
  });

  describe('getFocusable', () => {
    it('returns the focusable descendants in document order', () => {
      mount({ options: {} });
      const found = getFocusable(trapEl());
      expect(found).toEqual(buttons());
    });
  });
});
