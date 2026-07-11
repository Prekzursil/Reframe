// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CaptionDelivery, type CaptionDeliveryMode } from './CaptionDelivery';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onChange = vi.fn();

beforeEach(() => {
  onChange.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);
function render(value: CaptionDeliveryMode): void {
  act(() => {
    root.render(<CaptionDelivery value={value} onChange={onChange} />);
  });
}

describe('CaptionDelivery', () => {
  it('shows the reversible soft-track note by default (no alert)', () => {
    render('soft');
    const note = q('.caption-delivery__note');
    expect(note?.textContent).toMatch(/toggle captions on or off/);
    expect(note?.classList.contains('is-warning')).toBe(false);
    expect(note?.getAttribute('role')).toBeNull();
    expect(q('.caption-delivery__option.is-active')?.textContent).toBe('Soft track');
  });

  it('raises a guarded permanence alert for burn-in', () => {
    render('hard');
    const note = q('.caption-delivery__note');
    expect(note?.textContent).toMatch(/permanent/);
    expect(note?.classList.contains('is-warning')).toBe(true);
    expect(note?.getAttribute('role')).toBe('alert');
    const active = q('.caption-delivery__option.is-active');
    expect(active?.textContent).toBe('Burn in');
    expect(active?.getAttribute('aria-checked')).toBe('true');
  });

  it('emits the chosen mode', () => {
    render('soft');
    act(() => {
      const buttons = container.querySelectorAll<HTMLButtonElement>('.caption-delivery__option');
      buttons[1].click();
    });
    expect(onChange).toHaveBeenCalledWith('hard');
  });
});
