// ProviderUsageAvailability.test.tsx — WU-D4 honest per-provider usage-API notes.
// Proves the component renders the honest message per provider (available vs not),
// never a fabricated number, and renders nothing when there is nothing to say.

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ProviderUsageAvailability } from './ProviderUsageAvailability';
import type { ProviderUsageAvailability as UsageAvailabilityRow } from '../lib/rpc';

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

function render(rows: UsageAvailabilityRow[]): void {
  act(() => root.render(<ProviderUsageAvailability rows={rows} />));
}

describe('ProviderUsageAvailability', () => {
  it('renders nothing when there are no rows', () => {
    render([]);
    expect(container.querySelector('[data-usage-availability]')).toBeNull();
    expect(container.textContent).toBe('');
  });

  it('shows the honest "not available" message for a provider without a usage API', () => {
    render([
      { provider: 'Groq', hasUsageApi: false, message: 'Usage API not available for Groq.' },
    ]);
    const row = container.querySelector('[data-provider="Groq"]');
    expect(row).not.toBeNull();
    expect(row?.getAttribute('data-available')).toBe('false');
    expect(row?.classList.contains('is-unavailable')).toBe(true);
    expect(container.textContent).toContain('Usage API not available for Groq.');
  });

  it('marks a provider WITH a usage API as available', () => {
    render([
      {
        provider: 'OpenRouter',
        hasUsageApi: true,
        message: 'Live per-key credit usage is available from OpenRouter.',
      },
    ]);
    const row = container.querySelector('[data-provider="OpenRouter"]');
    expect(row?.getAttribute('data-available')).toBe('true');
    expect(row?.classList.contains('is-available')).toBe(true);
    expect(container.textContent).toContain('available from OpenRouter');
  });

  it('renders one row per provider with the count', () => {
    render([
      { provider: 'Groq', hasUsageApi: false, message: 'Usage API not available for Groq.' },
      {
        provider: 'OpenRouter',
        hasUsageApi: true,
        message: 'Live per-key credit usage is available from OpenRouter.',
      },
    ]);
    const list = container.querySelector('[data-usage-availability="rows"]');
    expect(list?.getAttribute('data-row-count')).toBe('2');
    expect(container.querySelectorAll('.usage-availability__row').length).toBe(2);
  });
});
