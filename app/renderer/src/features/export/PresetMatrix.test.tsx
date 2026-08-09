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

function render(props: { values?: string[]; durationSec?: number; disabled?: boolean }): void {
  act(() => {
    root.render(
      <PresetMatrix
        values={props.values ?? ['tiktok']}
        onChange={onChange}
        durationSec={props.durationSec ?? 30}
        disabled={props.disabled}
      />,
    );
  });
}

function keyOnGroup(key: string): void {
  const group = q<HTMLDivElement>('[role="group"]');
  act(() => {
    group?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });
}

const optionFor = (id: string): HTMLButtonElement | null =>
  q<HTMLButtonElement>(`[data-preset="${id}"]`);

describe('PresetMatrix', () => {
  it('renders a real fieldset/group of destination CHECKBOXES (multi-select)', () => {
    render({ values: ['tiktok'] });
    expect(q('fieldset.preset-matrix')).not.toBeNull();
    expect(q('legend')?.textContent).toBe('Deliver to');
    // A checkbox group, not a radiogroup: several destinations at once is the
    // whole point of the aspect matrix.
    expect(q('[role="radiogroup"]')).toBeNull();
    const boxes = all('[role="checkbox"]');
    expect(boxes.length).toBe(6);
    // Named destinations, no codec jargon.
    expect(optionFor('shorts')?.textContent).toContain('YouTube Shorts');
    expect(optionFor('shorts')?.textContent).toContain('9:16');
  });

  it('offers WIDESCREEN 16:9 as a first-class destination', () => {
    render({ values: ['tiktok'] });
    const wide = optionFor('widescreen');
    expect(wide).not.toBeNull();
    expect(wide?.textContent).toContain('16:9');
    expect(wide?.disabled).toBe(false);
  });

  it('tells the user one file lands per DISTINCT aspect', () => {
    render({ values: ['tiktok'] });
    // Replaces the old "aspect is set upstream, Export keeps your framing" hint:
    // the matrix now drives the aspect, so the hint must state the fan-out rule.
    expect(q('.preset-matrix__hint')?.textContent).toBe(
      'Pick every destination you need — one file is rendered per distinct aspect.',
    );
  });

  it('reflects EVERY selected destination through aria-checked', () => {
    render({ values: ['reels', 'square'] });
    expect(optionFor('reels')?.getAttribute('aria-checked')).toBe('true');
    expect(optionFor('square')?.getAttribute('aria-checked')).toBe('true');
    expect(optionFor('tiktok')?.getAttribute('aria-checked')).toBe('false');
  });

  it('ADDS a destination on click instead of replacing the selection', () => {
    render({ values: ['tiktok'] });
    act(() => optionFor('square')?.click());
    expect(onChange).toHaveBeenCalledWith(['tiktok', 'square']);
  });

  it('removes an already-checked destination on click', () => {
    render({ values: ['tiktok', 'square'] });
    act(() => optionFor('tiktok')?.click());
    expect(onChange).toHaveBeenCalledWith(['square']);
  });

  it('refuses to uncheck the LAST destination (export needs one)', () => {
    render({ values: ['tiktok'] });
    act(() => optionFor('tiktok')?.click());
    expect(onChange).toHaveBeenCalledWith(['tiktok']);
  });

  it('blocks a destination whose cap the clip exceeds (disabled + reason)', () => {
    render({ values: ['tiktok'], durationSec: 120 });
    const shorts = optionFor('shorts');
    expect(shorts?.disabled).toBe(true);
    expect(shorts?.className).toContain('is-unavailable');
    expect(shorts?.textContent).toContain('trim it first');
    act(() => shorts?.click());
    expect(onChange).not.toHaveBeenCalled();
  });

  it('carries a roving tabindex anchored on the first selected destination', () => {
    render({ values: ['reels'] });
    expect(optionFor('reels')?.tabIndex).toBe(0);
    expect(optionFor('tiktok')?.tabIndex).toBe(-1);
  });

  it('moves FOCUS (not the selection) to the next selectable destination', () => {
    // ARIA checkbox-group pattern: arrows navigate, Space/Enter toggles. A 120s
    // clip blocks reels (90) + shorts (60), so ArrowRight from tiktok lands on feed.
    render({ values: ['tiktok'], durationSec: 120 });
    keyOnGroup('ArrowRight');
    expect(document.activeElement).toBe(optionFor('feed'));
    // Navigating must NOT check anything — that is the radiogroup behaviour we left.
    expect(onChange).not.toHaveBeenCalled();
  });

  it('wraps focus to the last destination on ArrowLeft', () => {
    render({ values: ['tiktok'], durationSec: 30 });
    keyOnGroup('ArrowLeft');
    expect(document.activeElement).toBe(optionFor('widescreen'));
  });

  it('jumps focus to the first / last destination on Home / End', () => {
    render({ values: ['square'], durationSec: 30 });
    keyOnGroup('Home');
    expect(document.activeElement).toBe(optionFor('tiktok'));
    keyOnGroup('End');
    expect(document.activeElement).toBe(optionFor('widescreen'));
  });

  it('ignores non-navigation keys', () => {
    render({ values: ['tiktok'] });
    keyOnGroup('Tab');
    expect(onChange).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.body);
  });

  it('locks the whole group (no click, no keyboard) while disabled', () => {
    render({ values: ['tiktok'], disabled: true });
    expect(optionFor('reels')?.disabled).toBe(true);
    act(() => optionFor('reels')?.click());
    keyOnGroup('ArrowRight');
    expect(onChange).not.toHaveBeenCalled();
  });
});
