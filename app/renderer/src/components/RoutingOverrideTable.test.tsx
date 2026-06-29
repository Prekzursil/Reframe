// RoutingOverrideTable.test.tsx — M5 per-function routing override table.
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { RoutingOverrideTable, type RoutingOverrideTableProps } from './RoutingOverrideTable';
import { AI_FUNCTIONS } from './routingFunctions';
import type { RoutingPolicy } from '../lib/rpc';

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

function mount(props: RoutingOverrideTableProps): void {
  act(() => {
    root.render(<RoutingOverrideTable {...props} />);
  });
}

function sel(fn: string): HTMLSelectElement {
  return container.querySelector(`select[data-action="route-${fn}"]`) as HTMLSelectElement;
}

function setValue(el: HTMLSelectElement, value: string): void {
  act(() => {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

const POLICY: RoutingPolicy = { global: 'local', overrides: {} };

describe('RoutingOverrideTable', () => {
  it('renders a row per canonical AI function', () => {
    mount({ policy: POLICY, onApply: () => {} });
    for (const fn of AI_FUNCTIONS) expect(sel(fn)).not.toBeNull();
    expect(container.querySelectorAll('.routing-overrides__row').length).toBe(AI_FUNCTIONS.length);
  });

  it('shows inherit by default and the stored override otherwise', () => {
    mount({ policy: { global: 'local', overrides: { select: 'cloud' } }, onApply: () => {} });
    expect(sel('asr').value).toBe('inherit');
    expect(sel('select').value).toBe('cloud');
  });

  it('persists a concrete override with the current global preserved', () => {
    const onApply = vi.fn();
    mount({ policy: { global: 'auto', overrides: {} }, onApply });
    setValue(sel('select'), 'cloud');
    expect(onApply).toHaveBeenCalledWith({ global: 'auto', overrides: { select: 'cloud' } });
  });

  it('inherit removes the override (sends the trimmed map)', () => {
    const onApply = vi.fn();
    mount({ policy: { global: 'local', overrides: { select: 'cloud' } }, onApply });
    setValue(sel('select'), 'inherit');
    expect(onApply).toHaveBeenCalledWith({ global: 'local', overrides: {} });
  });

  it('shows an egress badge only for cloud/auto rows', () => {
    mount({ policy: { global: 'local', overrides: { select: 'cloud', asr: 'auto' } }, onApply: () => {} });
    expect(container.querySelector('[data-testid="egress-select"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="egress-asr"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="egress-caption"]')).toBeNull();
  });

  it('disables every select while busy', () => {
    mount({ policy: POLICY, onApply: () => {}, busy: true });
    for (const fn of AI_FUNCTIONS) expect(sel(fn).disabled).toBe(true);
  });

  it('is enabled by default (busy omitted)', () => {
    mount({ policy: POLICY, onApply: () => {} });
    expect(sel('select').disabled).toBe(false);
  });

  it('tolerates a policy with no overrides field', () => {
    mount({ policy: { global: 'cloud' } as RoutingPolicy, onApply: () => {} });
    expect(sel('select').value).toBe('inherit');
  });
});
