// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { LanguageSelect } from './LanguageSelect';
import { AUTO_DETECT, LANGUAGES, languageLabel } from '../lib/languages';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

describe('languages lib', () => {
  it('exposes a non-empty curated list that excludes the auto sentinel', () => {
    expect(LANGUAGES.length).toBeGreaterThan(5);
    expect(LANGUAGES.some((l) => l.code === AUTO_DETECT)).toBe(false);
    // English is always offered as the canonical default.
    expect(LANGUAGES.some((l) => l.code === 'en')).toBe(true);
  });

  it('languageLabel returns the label for a known code and the raw code otherwise', () => {
    expect(languageLabel('en')).toBe('English');
    expect(languageLabel(AUTO_DETECT)).toBe('Auto-detect');
    expect(languageLabel('zz')).toBe('zz');
  });
});

describe('<LanguageSelect />', () => {
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

  function sel(): HTMLSelectElement {
    return container.querySelector('select') as HTMLSelectElement;
  }

  function pick(value: string): void {
    const el = sel();
    act(() => {
      el.value = value;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  it('renders an Auto-detect option plus every curated language and forwards changes', () => {
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value="en" onChange={onChange} />));
    const codes = [...sel().options].map((o) => o.value);
    expect(codes[0]).toBe(AUTO_DETECT);
    expect(codes).toContain('es');
    pick('es');
    expect(onChange).toHaveBeenCalledWith('es');
  });

  it('shows a quality-advice note ONLY when Auto-detect is selected', () => {
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value={AUTO_DETECT} onChange={onChange} />));
    expect(container.querySelector('.lang-select__advice')).toBeTruthy();
    act(() => root.render(<LanguageSelect value="en" onChange={onChange} />));
    expect(container.querySelector('.lang-select__advice')).toBeNull();
  });

  it('omits the Auto-detect option (and its advice) when includeAuto is false', () => {
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value="en" onChange={onChange} includeAuto={false} />));
    const codes = [...sel().options].map((o) => o.value);
    expect(codes).not.toContain(AUTO_DETECT);
    // Even if value were auto, no advice renders without the auto option.
    act(() =>
      root.render(<LanguageSelect value={AUTO_DETECT} onChange={onChange} includeAuto={false} />),
    );
    expect(container.querySelector('.lang-select__advice')).toBeNull();
  });

  it('keeps an unknown current value selectable via a fallback option', () => {
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value="zz" onChange={onChange} />));
    const codes = [...sel().options].map((o) => o.value);
    expect(codes).toContain('zz');
    expect(sel().value).toBe('zz');
  });

  it('accepts a custom label + id and wires them to the control', () => {
    const onChange = vi.fn();
    act(() =>
      root.render(
        <LanguageSelect value="en" onChange={onChange} id="cap-lang" label="Caption language" />,
      ),
    );
    expect(sel().id).toBe('cap-lang');
    expect(sel().getAttribute('aria-label')).toBe('Caption language');
  });
});
