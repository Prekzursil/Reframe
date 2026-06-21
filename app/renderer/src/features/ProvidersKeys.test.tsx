// ProvidersKeys.test.tsx — the Providers & Keys empty-state scaffold: it shows a
// helpful message, renders the action only when an onOpenModels handler is wired,
// and invokes that handler on click.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ProvidersKeys } from './ProvidersKeys';

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
  vi.restoreAllMocks();
});

describe('ProvidersKeys empty-state', () => {
  it('renders a titled, helpful empty-state (not blank)', () => {
    act(() => {
      root.render(<ProvidersKeys />);
    });
    const title = container.querySelector('#providers-keys-title');
    expect(title?.textContent).toBe('No provider keys yet');
    expect(container.textContent).toContain('Add API keys for cloud providers');
    // The labelled region wires its title for SR users.
    expect(
      container.querySelector('section')?.getAttribute('aria-labelledby'),
    ).toBe('providers-keys-title');
  });

  it('hides the action when no onOpenModels handler is provided', () => {
    act(() => {
      root.render(<ProvidersKeys />);
    });
    expect(container.querySelector('.providers-keys__action')).toBeNull();
  });

  it('renders the action and calls onOpenModels on click', () => {
    const onOpenModels = vi.fn();
    act(() => {
      root.render(<ProvidersKeys onOpenModels={onOpenModels} />);
    });
    const action = container.querySelector<HTMLButtonElement>('.providers-keys__action');
    expect(action).not.toBeNull();
    expect(action!.textContent).toBe('Review model routing');
    act(() => {
      action!.click();
    });
    expect(onOpenModels).toHaveBeenCalledTimes(1);
  });
});
