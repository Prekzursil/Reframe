// ProviderKeyRow.test.tsx — renders a redacted key + a Remove button (WU-keys).
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ProviderKeyRow } from './ProviderKeyRow';

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

describe('ProviderKeyRow', () => {
  it('shows the redacted key only (never a full key) and fires onRemove', () => {
    const onRemove = vi.fn();
    act(() => {
      root.render(
        <ProviderKeyRow providerId="groq" redactedKey="…WXYZ" index={2} onRemove={onRemove} />,
      );
    });

    const code = container.querySelector('.provider-key-row__value');
    expect(code?.textContent).toBe('…WXYZ');
    // The row carries the provider + index data attributes.
    const row = container.querySelector('.provider-key-row');
    expect(row?.getAttribute('data-provider')).toBe('groq');
    expect(row?.getAttribute('data-key-index')).toBe('2');

    const btn = container.querySelector('.provider-key-row__remove') as HTMLButtonElement;
    act(() => btn.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(onRemove).toHaveBeenCalledWith('groq', 2);
  });
});
