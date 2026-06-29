// RoutingToggle.test.tsx — the M3 header global Local/Cloud/Auto routing toggle.
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { RoutingToggle, type RoutingToggleProps } from './RoutingToggle';

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

function mount(props: RoutingToggleProps): void {
  act(() => {
    root.render(<RoutingToggle {...props} />);
  });
}

function btn(mode: string): HTMLButtonElement {
  return container.querySelector(`button[data-mode="${mode}"]`) as HTMLButtonElement;
}

describe('RoutingToggle', () => {
  it('renders the three routing modes with the current one pressed', () => {
    mount({ value: 'local', onChange: () => {} });
    expect(btn('local').getAttribute('aria-pressed')).toBe('true');
    expect(btn('cloud').getAttribute('aria-pressed')).toBe('false');
    expect(btn('auto').getAttribute('aria-pressed')).toBe('false');
    expect(btn('local').textContent).toBe('Local');
    expect(btn('cloud').textContent).toBe('Cloud');
    expect(btn('auto').textContent).toBe('Auto');
  });

  it('reflects a cloud value as the pressed button', () => {
    mount({ value: 'cloud', onChange: () => {} });
    expect(btn('cloud').getAttribute('aria-pressed')).toBe('true');
    expect(btn('local').getAttribute('aria-pressed')).toBe('false');
  });

  it('reflects an auto value as the pressed button', () => {
    mount({ value: 'auto', onChange: () => {} });
    expect(btn('auto').getAttribute('aria-pressed')).toBe('true');
  });

  it('calls onChange with the clicked mode', () => {
    const onChange = vi.fn();
    mount({ value: 'local', onChange });
    act(() => btn('cloud').click());
    expect(onChange).toHaveBeenCalledWith('cloud');
    act(() => btn('auto').click());
    expect(onChange).toHaveBeenCalledWith('auto');
  });

  it('does NOT call onChange when the active mode is re-clicked (no churn)', () => {
    const onChange = vi.fn();
    mount({ value: 'local', onChange });
    act(() => btn('local').click());
    expect(onChange).not.toHaveBeenCalled();
  });

  it('disables every button while busy', () => {
    mount({ value: 'local', onChange: () => {}, busy: true });
    expect(btn('local').disabled).toBe(true);
    expect(btn('cloud').disabled).toBe(true);
    expect(btn('auto').disabled).toBe(true);
  });

  it('is enabled by default (busy omitted)', () => {
    mount({ value: 'local', onChange: () => {} });
    expect(btn('cloud').disabled).toBe(false);
  });

  it('exposes a labelled group and an egress hint on cloud/auto only', () => {
    mount({ value: 'local', onChange: () => {} });
    expect(container.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe(
      'AI routing',
    );
    expect(container.querySelector('[data-testid="routing-egress-hint"]')).toBeNull();
    mount({ value: 'cloud', onChange: () => {} });
    expect(container.querySelector('[data-testid="routing-egress-hint"]')).not.toBeNull();
    mount({ value: 'auto', onChange: () => {} });
    expect(container.querySelector('[data-testid="routing-egress-hint"]')).not.toBeNull();
  });
});
