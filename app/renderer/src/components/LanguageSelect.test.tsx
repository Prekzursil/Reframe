// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { LanguageSelect } from './LanguageSelect';
import { AUTO_DETECT, COMMON_CODES, LANGUAGES, languageLabel } from '../lib/languages';

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

  it('never DISPLAYS a different language than its value, even for auto with includeAuto=false', () => {
    // A <select> whose value matches no option silently shows the FIRST option
    // instead. On a translate-TARGET picker (includeAuto={false}) seeded with the
    // 'auto' sentinel that means the control reads "English" while its state — and
    // therefore the wire value — is 'auto'. A lying control is worse than an ugly
    // one, so the value always gets an option.
    const onChange = vi.fn();
    act(() =>
      root.render(<LanguageSelect value={AUTO_DETECT} onChange={onChange} includeAuto={false} />),
    );
    expect(sel().value).toBe(AUTO_DETECT);
    const opt = [...sel().options].find((o) => o.value === AUTO_DETECT);
    expect(opt?.textContent).toBe(languageLabel(AUTO_DETECT));
  });

  it('groups the common creator languages ahead of the full list', () => {
    // 102 flat options is a wall of text; the curated head goes in its own group
    // so the common choices stay one glance away (V1-GRILL §h intent preserved).
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value="en" onChange={onChange} />));
    const groups = [...container.querySelectorAll('optgroup')];
    expect(groups.length).toBe(2);
    const [common, all] = groups.map((g) => [...g.querySelectorAll('option')].map((o) => o.value));
    expect(common).toEqual([...COMMON_CODES]);
    // Romanian was unreachable before v1.5; it lives in the full-list group.
    expect(all).toContain('ro');
    expect(common).not.toContain('ro');
    expect(common.length + all.length).toBe(LANGUAGES.length);
  });

  it('surfaces the per-language capability caveat beside the picker', () => {
    const onChange = vi.fn();
    // nb has NO ASR coverage at all — offering it silently would be the defect.
    act(() => root.render(<LanguageSelect value="nb" onChange={onChange} />));
    const note = container.querySelector('.lang-select__capability');
    expect(note?.getAttribute('role')).toBe('note');
    expect(note?.textContent).toContain('cannot be transcribed');
  });

  it('warns when the CHOSEN engine cannot cover the picked language, and names the fix', () => {
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value="ja" onChange={onChange} engine="parakeet" />));
    const note = container.querySelector('.lang-select__capability')?.textContent ?? '';
    expect(note).toContain('Parakeet');
    expect(note).toContain('Japanese');
    expect(note).toContain('Whisper');
    // Same language, default engine -> nothing to warn about.
    act(() => root.render(<LanguageSelect value="ja" onChange={onChange} engine="whisper" />));
    expect(container.querySelector('.lang-select__capability')).toBeNull();
  });

  it('shows no capability caveat for a fully-covered language or for auto-detect', () => {
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value="ro" onChange={onChange} engine="parakeet" />));
    expect(container.querySelector('.lang-select__capability')).toBeNull();
    act(() => root.render(<LanguageSelect value={AUTO_DETECT} onChange={onChange} />));
    expect(container.querySelector('.lang-select__capability')).toBeNull();
    // ...and the auto advice is still the note that renders in that state.
    expect(container.querySelector('.lang-select__advice')).toBeTruthy();
  });

  it('can be disabled (callers lock the picker while a job runs)', () => {
    const onChange = vi.fn();
    act(() => root.render(<LanguageSelect value="en" onChange={onChange} />));
    expect(sel().disabled).toBe(false);
    act(() => root.render(<LanguageSelect value="en" onChange={onChange} disabled />));
    expect(sel().disabled).toBe(true);
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
