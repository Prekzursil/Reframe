// useFocusTrap.ts — a shared modal focus-trap hook (Lane 0 F4 / R-M10).
//
// Modal dialogs (ModelsOnboarding, FirstRunChooser) set role="dialog" +
// aria-modal but, before this, did nothing to keep keyboard focus inside: Tab
// walked straight out into the page behind them, Escape did nothing, and focus
// was never restored to whatever opened the dialog. This hook fixes all three
// the WAI-ARIA way:
//
//   * on mount it moves focus to the RECOMMENDED control (initialFocus selector)
//     or, failing that, the first focusable element, or the container itself;
//   * it traps Tab / Shift+Tab so focus cycles within the container;
//   * Escape calls the optional onEscape handler (dialogs wire this to dismiss);
//   * on unmount it restores focus to whatever was focused before the dialog
//     opened.
//
// Attach the returned ref to the dialog container. The hook is intended for
// modal dialogs that are conditionally mounted (so mounting == "becomes active").
import { useEffect, useRef, type RefObject } from 'react';

/** Selector for the elements considered keyboard-focusable inside the trap. */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/** The focusable descendants of `container`, in document order. */
export function getFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

export interface FocusTrapOptions {
  /**
   * Called when Escape is pressed inside the trap. Dialogs wire this to their
   * dismiss action. Omit it for a trap that should ignore Escape.
   */
  onEscape?: () => void;
  /**
   * CSS selector (relative to the container) for the control to focus on mount —
   * the "recommended" default. Falls back to the first focusable element, then
   * the container itself.
   */
  initialFocus?: string;
}

/**
 * Trap keyboard focus inside the element the returned ref is attached to.
 * See the file header for the full behaviour.
 */
export function useFocusTrap<T extends HTMLElement = HTMLElement>(
  options: FocusTrapOptions,
): RefObject<T> {
  const { onEscape, initialFocus } = options;
  // useRef<T>(null) resolves to RefObject<T> (a read-only ref whose `current`
  // is T | null) — exactly what a JSX `ref` prop expects.
  const ref = useRef<T>(null);
  // Keep the latest onEscape without re-running the effect when it changes.
  const onEscapeRef = useRef(onEscape);
  onEscapeRef.current = onEscape;

  useEffect(() => {
    const current = ref.current;
    if (!current) return undefined;
    // Bind the narrowed (non-null) node so the type survives into the nested
    // keydown closure below (control-flow narrowing is not carried into closures).
    const node: T = current;

    const previouslyFocused = document.activeElement as HTMLElement | null;

    // Move focus to the recommended control, else the first focusable, else the
    // container itself (so focus never sits behind the dialog).
    const preferred = initialFocus ? node.querySelector<HTMLElement>(initialFocus) : null;
    const target = preferred ?? getFocusable(node)[0] ?? node;
    target.focus();

    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.preventDefault();
        onEscapeRef.current?.();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = getFocusable(node);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    node.addEventListener('keydown', onKeyDown);
    return () => {
      node.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus();
    };
  }, [initialFocus]);

  return ref;
}

export default useFocusTrap;
