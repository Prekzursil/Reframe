// AdvancedModels.test.tsx — M3 Advanced disclosure: model SORT + runner POINT.
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { AdvancedModels, type AdvancedModelsProps } from './AdvancedModels';
import type { ModelMeta } from '../lib/rpc';

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

function meta(over: Partial<ModelMeta>): ModelMeta {
  return {
    model: 'm',
    digest: 'd',
    sizeBytes: null,
    paramsB: null,
    quantBits: null,
    vramEstimateGb: null,
    capabilities: [],
    aliases: [],
    fits: false,
    ...over,
  };
}

function mount(over: Partial<AdvancedModelsProps> = {}): void {
  const props: AdvancedModelsProps = {
    models: [],
    ollamaBaseUrl: '',
    lmStudioBaseUrl: '',
    onApplyRunnerUrls: () => {},
    ...over,
  };
  act(() => {
    root.render(<AdvancedModels {...props} />);
  });
}

function typeInto(el: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  setter?.call(el, value);
  act(() => el.dispatchEvent(new Event('input', { bubbles: true })));
}

function rowNames(): string[] {
  return Array.from(
    container.querySelectorAll('[data-section="advanced-models"] [data-model]'),
  ).map((el) => el.getAttribute('data-model') ?? '');
}

describe('AdvancedModels', () => {
  it('renders inside a collapsed Advanced disclosure', () => {
    mount();
    const details = container.querySelector('details.advanced-models') as HTMLDetailsElement;
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);
  });

  it('defaults the sort to VRAM fit (fitting models first)', () => {
    mount({
      models: [
        meta({ model: 'nofit', fits: false, vramEstimateGb: 1 }),
        meta({ model: 'fits', fits: true, vramEstimateGb: 5 }),
      ],
    });
    expect(rowNames()).toEqual(['fits', 'nofit']);
  });

  it('re-sorts when the sort axis changes to name', () => {
    mount({ models: [meta({ model: 'zeta', fits: true }), meta({ model: 'alpha', fits: true })] });
    const select = container.querySelector('select[data-action="model-sort"]') as HTMLSelectElement;
    act(() => {
      select.value = 'name';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(rowNames()).toEqual(['alpha', 'zeta']);
  });

  it('re-sorts by size when chosen', () => {
    mount({
      models: [meta({ model: 'big', sizeBytes: 900 }), meta({ model: 'small', sizeBytes: 10 })],
    });
    const select = container.querySelector('select[data-action="model-sort"]') as HTMLSelectElement;
    act(() => {
      select.value = 'size';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(rowNames()).toEqual(['small', 'big']);
  });

  it('shows an empty hint when there are no metadata models', () => {
    mount({ models: [] });
    expect(container.querySelector('[data-section="advanced-models-empty"]')).not.toBeNull();
    expect(rowNames()).toEqual([]);
  });

  it('renders a fit badge + VRAM estimate per model row', () => {
    mount({
      models: [meta({ model: 'q', fits: true, vramEstimateGb: 4, sizeBytes: 4_000_000_000 })],
    });
    const row = container.querySelector('[data-model="q"]') as HTMLElement;
    expect(row.textContent).toContain('fits');
    expect(row.textContent).toContain('4');
  });

  it('seeds the runner URL inputs from props', () => {
    mount({ ollamaBaseUrl: 'http://host:9999/v1', lmStudioBaseUrl: 'http://lm:1234/v1' });
    expect(
      (container.querySelector('input[data-action="ollama-url"]') as HTMLInputElement).value,
    ).toBe('http://host:9999/v1');
    expect(
      (container.querySelector('input[data-action="lmstudio-url"]') as HTMLInputElement).value,
    ).toBe('http://lm:1234/v1');
  });

  it('applies edited runner URLs on submit (POINT)', () => {
    const onApply = vi.fn();
    mount({ onApplyRunnerUrls: onApply });
    const ollama = container.querySelector('input[data-action="ollama-url"]') as HTMLInputElement;
    typeInto(ollama, 'http://127.0.0.1:11434/v1');
    const form = container.querySelector('form.advanced-models__point') as HTMLFormElement;
    act(() => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(onApply).toHaveBeenCalledWith({
      ollamaBaseUrl: 'http://127.0.0.1:11434/v1',
      lmStudioBaseUrl: '',
    });
  });

  it('edits the LM Studio URL too', () => {
    const onApply = vi.fn();
    mount({ onApplyRunnerUrls: onApply });
    const lm = container.querySelector('input[data-action="lmstudio-url"]') as HTMLInputElement;
    typeInto(lm, 'http://lm.local:1234/v1');
    const form = container.querySelector('form.advanced-models__point') as HTMLFormElement;
    act(() => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(onApply).toHaveBeenCalledWith({
      ollamaBaseUrl: '',
      lmStudioBaseUrl: 'http://lm.local:1234/v1',
    });
  });
});
