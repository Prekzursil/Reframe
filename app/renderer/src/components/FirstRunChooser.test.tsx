// FirstRunChooser.test.tsx — the first-run local-vs-cloud chooser (WU-presets P1 #6).
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { FirstRunChooser } from './FirstRunChooser';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

function mount(props: Parameters<typeof FirstRunChooser>[0]): void {
  act(() => {
    root.render(<FirstRunChooser {...props} />);
  });
}

describe('<FirstRunChooser />', () => {
  it('renders both the local-safe and cloud options', () => {
    mount({ onChoose: vi.fn() });
    expect(container.querySelector('[data-choice="privacy"]')).not.toBeNull();
    expect(container.querySelector('[data-choice="bestFreeCloud"]')).not.toBeNull();
  });

  it('marks the local option as the safe default', () => {
    mount({ onChoose: vi.fn() });
    const local = container.querySelector('[data-choice="privacy"]') as HTMLElement;
    // The default is signalled both via a class and an always-present text label
    // (not color alone) so the local-safe default is unmistakable.
    expect(local.getAttribute('data-default')).toBe('true');
    expect(local.textContent).toContain('Recommended');
  });

  it('calls onChoose("privacy") when the local option is picked', () => {
    const onChoose = vi.fn();
    mount({ onChoose });
    const btn = container.querySelector('[data-choice="privacy"]') as HTMLButtonElement;
    act(() => btn.click());
    expect(onChoose).toHaveBeenCalledWith('privacy');
  });

  it('calls onChoose("bestFreeCloud") when the cloud option is picked', () => {
    const onChoose = vi.fn();
    mount({ onChoose });
    const btn = container.querySelector('[data-choice="bestFreeCloud"]') as HTMLButtonElement;
    act(() => btn.click());
    expect(onChoose).toHaveBeenCalledWith('bestFreeCloud');
  });

  it('disables the buttons while busy', () => {
    mount({ onChoose: vi.fn(), busy: true });
    const btns = container.querySelectorAll('button[data-choice]');
    for (const b of btns) expect((b as HTMLButtonElement).disabled).toBe(true);
  });

  it('exposes a modal dialog role + an accessible label', () => {
    mount({ onChoose: vi.fn() });
    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.getAttribute('aria-modal')).toBe('true');
    expect(dialog?.getAttribute('aria-label')).toBeTruthy();
  });

  it('moves focus to the recommended privacy option on mount (focus trap)', () => {
    mount({ onChoose: vi.fn() });
    const local = container.querySelector('[data-choice="privacy"]');
    expect(document.activeElement).toBe(local);
  });

  it('selects the privacy-safe default on Escape', () => {
    const onChoose = vi.fn();
    mount({ onChoose });
    act(() => {
      (document.activeElement ?? document.body).dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
      );
    });
    expect(onChoose).toHaveBeenCalledWith('privacy');
  });

  it('ignores Escape while busy (no choice is forced mid-apply)', () => {
    const onChoose = vi.fn();
    mount({ onChoose, busy: true });
    act(() => {
      container
        .querySelector('[role="dialog"]')
        ?.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
        );
    });
    expect(onChoose).not.toHaveBeenCalled();
  });
});
