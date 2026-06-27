// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { DEFAULT_OUTPUT_TRAY, OutputTray, type OutputTrayState } from './OutputTray';
import { AUTO_DETECT } from '../lib/languages';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe('DEFAULT_OUTPUT_TRAY', () => {
  it('ships quality features ON by default (G-4): caption + reframe + burn subtitles', () => {
    expect(DEFAULT_OUTPUT_TRAY.caption).toBe(true);
    expect(DEFAULT_OUTPUT_TRAY.reframe).toBe(true);
    expect(DEFAULT_OUTPUT_TRAY.subtitleMode).toBe('burn');
    // Translate is opt-in (off until a target language is wanted).
    expect(DEFAULT_OUTPUT_TRAY.translate).toBe(false);
    expect(DEFAULT_OUTPUT_TRAY.language).toBe('en');
  });
});

describe('<OutputTray />', () => {
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

  function render(props: Partial<React.ComponentProps<typeof OutputTray>> = {}): {
    onChange: ReturnType<typeof vi.fn>;
    state: OutputTrayState;
  } {
    const onChange = props.onChange ?? vi.fn();
    const state = props.state ?? DEFAULT_OUTPUT_TRAY;
    act(() => root.render(<OutputTray {...props} state={state} onChange={onChange} />));
    return { onChange: onChange as ReturnType<typeof vi.fn>, state };
  }

  function toggle(label: string): HTMLInputElement {
    return container.querySelector(`input[aria-label="${label}"]`) as HTMLInputElement;
  }
  function button(text: string): HTMLButtonElement | undefined {
    return [...container.querySelectorAll('button')].find((b) => b.textContent === text);
  }

  it('renders the consolidated post-action toggles', () => {
    render();
    expect(toggle('Caption')).toBeTruthy();
    expect(toggle('Translate')).toBeTruthy();
    expect(toggle('Reframe')).toBeTruthy();
  });

  it('emits an immutable next-state when a toggle flips', () => {
    const { onChange, state } = render();
    act(() => toggle('Caption').click()); // ON -> OFF
    expect(onChange).toHaveBeenCalledWith({ ...state, caption: false });
    // The input was not mutated in place.
    expect(state.caption).toBe(true);
  });

  it('shows the subtitle-delivery selector only while Caption is on and forwards it', () => {
    const onChange = vi.fn();
    // Caption OFF -> no subtitle delivery selector.
    render({ state: { ...DEFAULT_OUTPUT_TRAY, caption: false }, onChange });
    expect(container.querySelector('.output-tray__subs')).toBeNull();
    // Caption ON -> the four delivery modes are offered.
    render({ state: { ...DEFAULT_OUTPUT_TRAY, caption: true }, onChange });
    const select = container.querySelector(
      'select[aria-label="Subtitle delivery"]',
    ) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(['burn', 'softmux', 'sidecar', 'none']);
    act(() => {
      select.value = 'sidecar';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith({
      ...DEFAULT_OUTPUT_TRAY,
      caption: true,
      subtitleMode: 'sidecar',
    });
  });

  it('hides the translate-language picker until Translate is on, then forwards it', () => {
    const onChange = vi.fn();
    render({ state: { ...DEFAULT_OUTPUT_TRAY, translate: false }, onChange });
    expect(container.querySelector('.output-tray__lang')).toBeNull();
    // Turn translate ON.
    render({ state: { ...DEFAULT_OUTPUT_TRAY, translate: true }, onChange });
    const langWrap = container.querySelector('.output-tray__lang');
    expect(langWrap).toBeTruthy();
    const select = langWrap?.querySelector('select') as HTMLSelectElement;
    // Translate target must NOT offer auto-detect (you translate TO a language).
    expect([...select.options].some((o) => o.value === AUTO_DETECT)).toBe(false);
    act(() => {
      select.value = 'es';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith({
      ...DEFAULT_OUTPUT_TRAY,
      translate: true,
      language: 'es',
    });
  });

  it('renders ONLY the save actions whose handlers are provided', () => {
    const onSaveClip = vi.fn();
    const onSaveSrt = vi.fn();
    render({ onSaveClip, onSaveSrt });
    expect(button('Save clip')).toBeTruthy();
    expect(button('Save SRT separately')).toBeTruthy();
    expect(button('Save short')).toBeUndefined();
    act(() => button('Save clip')?.click());
    expect(onSaveClip).toHaveBeenCalled();
    act(() => button('Save SRT separately')?.click());
    expect(onSaveSrt).toHaveBeenCalled();
  });

  it('wires the Save short action when provided', () => {
    const onSaveShort = vi.fn();
    render({ onSaveShort });
    act(() => button('Save short')?.click());
    expect(onSaveShort).toHaveBeenCalled();
  });

  it('disables the save buttons while busy', () => {
    render({ onSaveClip: vi.fn(), busy: true });
    expect(button('Save clip')?.disabled).toBe(true);
  });

  it('uses a custom title when provided', () => {
    render({ title: 'Finish up' });
    expect(container.querySelector('.output-tray__title')?.textContent).toBe('Finish up');
  });
});
