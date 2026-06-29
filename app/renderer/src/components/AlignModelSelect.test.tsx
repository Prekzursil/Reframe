// AlignModelSelect.test.tsx — M5 word-timing alignment model opt-in (incl. RO).
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  AlignModelSelect,
  ALIGN_MODEL_CHOICES,
  type AlignModelSelectProps,
} from './AlignModelSelect';

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

function mount(props: AlignModelSelectProps): void {
  act(() => {
    root.render(<AlignModelSelect {...props} />);
  });
}

function select(): HTMLSelectElement {
  return container.querySelector('select[data-action="align-model"]') as HTMLSelectElement;
}

function setValue(el: HTMLSelectElement, value: string): void {
  act(() => {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

describe('AlignModelSelect', () => {
  it('exposes the MMS default + the Romanian and MIT opt-ins', () => {
    const ids = ALIGN_MODEL_CHOICES.map((c) => c.id);
    expect(ids).toContain('');
    expect(ids).toContain('romanian-wav2vec2');
    expect(ids).toContain('wav2vec2-960h-lv60');
  });

  it('shows the default (MMS) when value is blank', () => {
    mount({ value: '', onChange: () => {} });
    expect(select().value).toBe('');
  });

  it('reflects the Romanian opt-in selection', () => {
    mount({ value: 'romanian-wav2vec2', onChange: () => {} });
    expect(select().value).toBe('romanian-wav2vec2');
  });

  it('persists the Romanian choice', () => {
    const onChange = vi.fn();
    mount({ value: '', onChange });
    setValue(select(), 'romanian-wav2vec2');
    expect(onChange).toHaveBeenCalledWith('romanian-wav2vec2');
  });

  it('persists an empty id when reverting to the default', () => {
    const onChange = vi.fn();
    mount({ value: 'romanian-wav2vec2', onChange });
    setValue(select(), '');
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('keeps an unknown custom id without losing it (shows default row + a badge)', () => {
    mount({ value: 'gigant/romanian-wav2vec2', onChange: () => {} });
    expect(select().value).toBe('');
    expect(container.querySelector('[data-testid="align-model-custom"]')?.textContent).toContain(
      'gigant/romanian-wav2vec2',
    );
  });

  it('shows no custom badge for a blank value', () => {
    mount({ value: '', onChange: () => {} });
    expect(container.querySelector('[data-testid="align-model-custom"]')).toBeNull();
  });

  it('disables the control while busy', () => {
    mount({ value: '', onChange: () => {}, busy: true });
    expect(select().disabled).toBe(true);
  });

  it('is enabled by default', () => {
    mount({ value: '', onChange: () => {} });
    expect(select().disabled).toBe(false);
  });
});
