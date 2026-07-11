// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PresetMatrix } from './PresetMatrix';

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
  vi.restoreAllMocks();
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);
const all = (sel: string): Element[] => Array.from(container.querySelectorAll(sel));

function render(props: { value?: string; durationSec?: number; disabled?: boolean }): void {
  act(() => {
    root.render(
      <PresetMatrix
        value={props.value ?? 'tiktok'}
        onChange={onChange}
        durationSec={props.durationSec ?? 30}
        disabled={props.disabled}
      />,
    );
  });
}

function keyOnGroup(key: string): void {
  const group = q<HTMLDivElement>('[role="radiogroup"]');
  act(() => {
    group?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });
}

const optionFor = (id: string): HTMLButtonElement | null =>
  q<HTMLButtonElement>(`[data-preset="${id}"]`);

describe('PresetMatrix', () => {
  it('renders a real fieldset/radiogroup of destination radios', () => {
    render({ value: 'tiktok' });
    expect(q('fieldset.preset-matrix')).not.toBeNull();
    expect(q('legend')?.textContent).toBe('Deliver to');
    const radios = all('[role="radio"]');
    expect(radios.length).toBe(6);
    // Named destinations, no codec jargon.
    expect(optionFor('shorts')?.textContent).toContain('YouTube Shorts');
    expect(optionFor('shorts')?.textContent).toContain('9:16');
  });

  it('reflects the selection through aria-checked + roving tabindex', () => {
    render({ value: 'reels' });
    expect(optionFor('reels')?.getAttribute('aria-checked')).toBe('true');
    expect(optionFor('reels')?.tabIndex).toBe(0);
    expect(optionFor('tiktok')?.getAttribute('aria-checked')).toBe('false');
    expect(optionFor('tiktok')?.tabIndex).toBe(-1);
  });

  it('selects an available destination on click', () => {
    render({ value: 'tiktok' });
    act(() => optionFor('square')?.click());
    expect(onChange).toHaveBeenCalledWith('square');
  });

  it('blocks a destination whose cap the clip exceeds (disabled + reason)', () => {
    render({ value: 'tiktok', durationSec: 120 });
    const shorts = optionFor('shorts');
    expect(shorts?.disabled).toBe(true);
    expect(shorts?.className).toContain('is-unavailable');
    expect(shorts?.textContent).toContain('trim it first');
    // A disabled option cannot be chosen.
    act(() => shorts?.click());
    expect(onChange).not.toHaveBeenCalled();
  });

  it('moves selection to the next SELECTABLE destination on ArrowRight (skipping blocked)', () => {
    // 120s clip blocks reels (90) + shorts (60); ArrowRight from tiktok lands on feed.
    render({ value: 'tiktok', durationSec: 120 });
    keyOnGroup('ArrowRight');
    expect(onChange).toHaveBeenCalledWith('feed');
    // Focus follows the roving selection.
    expect(document.activeElement).toBe(optionFor('feed'));
  });

  it('wraps to the last destination on ArrowLeft', () => {
    render({ value: 'tiktok', durationSec: 30 });
    keyOnGroup('ArrowLeft');
    expect(onChange).toHaveBeenCalledWith('widescreen');
  });

  it('jumps to the first / last destination on Home / End', () => {
    render({ value: 'square', durationSec: 30 });
    keyOnGroup('Home');
    expect(onChange).toHaveBeenLastCalledWith('tiktok');
    keyOnGroup('End');
    expect(onChange).toHaveBeenLastCalledWith('widescreen');
  });

  it('ignores non-navigation keys', () => {
    render({ value: 'tiktok' });
    keyOnGroup('Tab');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('locks the whole group (no click, no keyboard) while disabled', () => {
    render({ value: 'tiktok', disabled: true });
    expect(optionFor('reels')?.disabled).toBe(true);
    act(() => optionFor('reels')?.click());
    keyOnGroup('ArrowRight');
    expect(onChange).not.toHaveBeenCalled();
  });
});
