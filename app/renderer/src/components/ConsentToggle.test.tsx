// ConsentToggle.test.tsx — text vs frames consent are SEPARATE + the train-on-
// input disclosure shows before first use (WU-keys / SE1).
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ConsentToggle, disclosureText } from './ConsentToggle';

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

function checkbox(consent: 'text' | 'frames'): HTMLInputElement {
  return container.querySelector(
    `.consent-toggle__option[data-consent="${consent}"] input`,
  ) as HTMLInputElement;
}

/** Flip a controlled checkbox the way React's synthetic onChange expects. */
function toggle(el: HTMLInputElement, value: boolean): void {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    'checked',
  )?.set;
  setter?.call(el, value);
  act(() => el.dispatchEvent(new Event('click', { bubbles: true })));
}

describe('disclosureText', () => {
  it('warns for a trains=true provider', () => {
    expect(disclosureText(true)).toContain('trains on your input');
  });
  it('warns about the opt-out for a conditional provider', () => {
    expect(disclosureText('conditional')).toContain('opt-out');
  });
  it('reassures for a no-train provider', () => {
    expect(disclosureText(false)).toContain('does not train');
  });
});

describe('ConsentToggle', () => {
  it('reflects the current text/frames state independently', () => {
    act(() =>
      root.render(
        <ConsentToggle
          providerId="groq"
          text={true}
          frames={false}
          trainsOnInput={false}
          onChange={vi.fn()}
        />,
      ),
    );
    expect(checkbox('text').checked).toBe(true);
    expect(checkbox('frames').checked).toBe(false);
  });

  it('toggling frames calls onChange for frames only (text untouched)', () => {
    const onChange = vi.fn();
    act(() =>
      root.render(
        <ConsentToggle
          providerId="groq"
          text={true}
          frames={false}
          trainsOnInput="conditional"
          onChange={onChange}
        />,
      ),
    );
    toggle(checkbox('frames'), true);
    expect(onChange).toHaveBeenCalledWith('groq', 'frames', true);
    expect(onChange).not.toHaveBeenCalledWith('groq', 'text', expect.anything());
  });

  it('toggling text calls onChange for text only', () => {
    const onChange = vi.fn();
    act(() =>
      root.render(
        <ConsentToggle
          providerId="groq"
          text={false}
          frames={true}
          trainsOnInput={true}
          onChange={onChange}
        />,
      ),
    );
    toggle(checkbox('text'), true);
    expect(onChange).toHaveBeenCalledWith('groq', 'text', true);
  });

  it('renders the train-on-input disclosure with its data attribute', () => {
    act(() =>
      root.render(
        <ConsentToggle
          providerId="gemini"
          text={false}
          frames={false}
          trainsOnInput={true}
          onChange={vi.fn()}
        />,
      ),
    );
    const note = container.querySelector('.consent-toggle__disclosure');
    expect(note?.getAttribute('data-trains')).toBe('true');
    expect(note?.textContent).toContain('avoid sending private');
  });
});
