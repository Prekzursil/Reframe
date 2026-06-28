// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CaptionCustomizer } from './CaptionCustomizer';
import type { CaptionOverride } from '../lib/captionOverride';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe('<CaptionCustomizer />', () => {
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
  });

  function render(
    value: CaptionOverride | undefined = undefined,
  ): { onChange: ReturnType<typeof vi.fn> } {
    const onChange = vi.fn();
    act(() => root.render(<CaptionCustomizer value={value} onChange={onChange} />));
    return { onChange };
  }

  const toggleBtn = (): HTMLButtonElement =>
    container.querySelector('.caption-customizer__toggle') as HTMLButtonElement;
  const open = (): void => act(() => toggleBtn().click());
  const q = <T extends Element>(sel: string): T => container.querySelector(sel) as T;
  // Drive controlled inputs the way React's synthetic onChange expects: write via
  // the native prototype setter (so React's value tracker sees the change), then
  // dispatch the event React actually listens to (input for value inputs, change
  // for <select>, click for checkboxes — mirrors AddKeyRow/ConsentToggle tests).
  const fireInput = (el: HTMLInputElement, value: string): void => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set?.call(el, value);
    act(() => el.dispatchEvent(new Event('input', { bubbles: true })));
  };
  const fireSelect = (el: HTMLSelectElement, value: string): void => {
    // React does not value-track <select>, so a plain assignment fires onChange
    // (jsdom rejects a prototype-setter .call on selects). Mirrors PresetPicker.
    el.value = value;
    act(() => el.dispatchEvent(new Event('change', { bubbles: true })));
  };
  const fireCheck = (el: HTMLInputElement, checked: boolean): void => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set?.call(el, checked);
    act(() => el.dispatchEvent(new Event('click', { bubbles: true })));
  };

  it('is collapsed by default — only the disclosure toggle is shown', () => {
    render();
    expect(toggleBtn()).toBeTruthy();
    expect(toggleBtn().getAttribute('aria-expanded')).toBe('false');
    expect(toggleBtn().textContent).toBe('Customize…');
    expect(container.querySelector('.caption-customizer__panel')).toBeNull();
  });

  it('uses a custom label when provided', () => {
    const onChange = vi.fn();
    act(() => root.render(<CaptionCustomizer value={undefined} onChange={onChange} label="Tune" />));
    expect(toggleBtn().textContent).toBe('Tune');
  });

  it('reveals the controls panel when the toggle is tapped, and hides it again', () => {
    render();
    open();
    expect(toggleBtn().getAttribute('aria-expanded')).toBe('true');
    const panel = container.querySelector('.caption-customizer__panel') as HTMLElement;
    expect(panel).toBeTruthy();
    expect(toggleBtn().getAttribute('aria-controls')).toBe(panel.id);
    act(() => toggleBtn().click());
    expect(container.querySelector('.caption-customizer__panel')).toBeNull();
  });

  it('does NOT expose a hex text field on the primary path (only swatches + color inputs)', () => {
    render();
    open();
    const textInputs = [...container.querySelectorAll('input')].filter(
      (i) => i.getAttribute('type') === 'text',
    );
    expect(textInputs).toHaveLength(0);
    expect(container.querySelectorAll('input[type="color"]').length).toBeGreaterThan(0);
  });

  it('selects a curated font and clears it back to the template default', () => {
    const { onChange } = render();
    open();
    const select = q<HTMLSelectElement>('.caption-customizer__font select');
    fireSelect(select, 'Anton');
    expect(onChange).toHaveBeenLastCalledWith({ fontFamily: 'Anton' });
    onChange.mockClear();
    // Re-render reflecting the new value so "Default" can clear it (the panel
    // stays open — `open` is component state preserved across the re-render).
    act(() => root.render(<CaptionCustomizer value={{ fontFamily: 'Anton' }} onChange={onChange} />));
    fireSelect(q<HTMLSelectElement>('.caption-customizer__font select'), '');
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it('moves the size slider and emits a clamped sizeScale', () => {
    const { onChange } = render();
    open();
    fireInput(q<HTMLInputElement>('.caption-customizer__size input'), '1.5');
    expect(onChange).toHaveBeenLastCalledWith({ sizeScale: 1.5 });
  });

  it('reflects an existing sizeScale on the slider value', () => {
    render({ sizeScale: 1.3 });
    open();
    expect(q<HTMLInputElement>('.caption-customizer__size input').value).toBe('1.3');
  });

  it('picks a text colour from the swatch grid and marks it active', () => {
    const { onChange } = render();
    open();
    const swatch = q<HTMLButtonElement>(
      '.caption-customizer__color[aria-label="Text colour"] .caption-customizer__swatch',
    );
    act(() => swatch.click());
    expect(onChange).toHaveBeenCalledTimes(1);
    const arg = onChange.mock.calls[0][0] as CaptionOverride;
    expect(arg.textColor).toBe(swatch.getAttribute('data-color')?.toUpperCase());
  });

  it('marks the matching swatch active when a colour is already set', () => {
    render({ activeColor: '#FFD700' });
    open();
    const active = container.querySelector(
      '.caption-customizer__color[aria-label="Active word colour"] .caption-customizer__swatch.is-active',
    );
    expect(active?.getAttribute('data-color')?.toUpperCase()).toBe('#FFD700');
  });

  it('picks a custom colour via the native color input', () => {
    const { onChange } = render();
    open();
    const colorInput = q<HTMLInputElement>(
      '.caption-customizer__color[aria-label="Spoken word colour"] input[type="color"]',
    );
    fireInput(colorInput, '#1a2b3c');
    expect(onChange).toHaveBeenLastCalledWith({ spokenColor: '#1A2B3C' });
  });

  it('defaults the native color input to white when no colour is set', () => {
    render();
    open();
    const colorInput = q<HTMLInputElement>(
      '.caption-customizer__color[aria-label="Text colour"] input[type="color"]',
    );
    expect(colorInput.value.toUpperCase()).toBe('#FFFFFF');
  });

  it('toggles outline, card, and uppercase booleans (including a forced-off false)', () => {
    const { onChange } = render({ outline: true });
    open();
    const outline = q<HTMLInputElement>('.caption-customizer__bool-outline input');
    expect(outline.checked).toBe(true);
    fireCheck(outline, false);
    expect(onChange).toHaveBeenLastCalledWith({ outline: false });

    onChange.mockClear();
    act(() => root.render(<CaptionCustomizer value={undefined} onChange={onChange} />));
    fireCheck(q<HTMLInputElement>('.caption-customizer__bool-card input'), true);
    expect(onChange).toHaveBeenLastCalledWith({ box: true });

    onChange.mockClear();
    fireCheck(q<HTMLInputElement>('.caption-customizer__bool-uppercase input'), true);
    expect(onChange).toHaveBeenLastCalledWith({ uppercase: true });
  });

  it('selects a position band and clears it', () => {
    const { onChange } = render();
    open();
    const band = q<HTMLSelectElement>('.caption-customizer__band select');
    fireSelect(band, 'center');
    expect(onChange).toHaveBeenLastCalledWith({ positionBand: 'center' });
    onChange.mockClear();
    act(() =>
      root.render(<CaptionCustomizer value={{ positionBand: 'center' }} onChange={onChange} />),
    );
    fireSelect(q<HTMLSelectElement>('.caption-customizer__band select'), '');
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it('selects a max-lines value and clears it', () => {
    const { onChange } = render();
    open();
    fireSelect(q<HTMLSelectElement>('.caption-customizer__lines select'), '1');
    expect(onChange).toHaveBeenLastCalledWith({ maxLines: 1 });
    onChange.mockClear();
    act(() => root.render(<CaptionCustomizer value={{ maxLines: 1 }} onChange={onChange} />));
    fireSelect(q<HTMLSelectElement>('.caption-customizer__lines select'), '');
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it('reflects an existing max-lines value on the select', () => {
    render({ maxLines: 2 });
    open();
    expect(q<HTMLSelectElement>('.caption-customizer__lines select').value).toBe('2');
  });

  it('moves the reading-speed slider and emits a clamped maxCps', () => {
    const { onChange } = render();
    open();
    fireInput(q<HTMLInputElement>('.caption-customizer__cps input'), '22');
    expect(onChange).toHaveBeenLastCalledWith({ maxCps: 22 });
  });

  it('resets every customization back to the template default', () => {
    const { onChange } = render({ sizeScale: 1.5, uppercase: true });
    open();
    act(() => (q<HTMLButtonElement>('.caption-customizer__reset')).click());
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });
});
