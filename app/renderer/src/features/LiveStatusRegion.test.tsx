// LiveStatusRegion.test.tsx — the BatchQueue a11y announcer (§7.1).

// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { LiveStatusRegion } from './LiveStatusRegion';

let container: HTMLElement;
let root: Root;

function render(ui: React.ReactElement): void {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(ui);
  });
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('LiveStatusRegion', () => {
  it('renders a polite aggregate region with the message', () => {
    render(<LiveStatusRegion aggregate="source 4/30 · Ep4" politeLog={[]} assertive="" />);
    const status = container.querySelector('[role="status"]');
    expect(status?.getAttribute('aria-live')).toBe('polite');
    expect(status?.textContent).toBe('source 4/30 · Ep4');
  });

  it('renders polite log lines (terminal done/skipped flips)', () => {
    render(
      <LiveStatusRegion
        aggregate=""
        politeLog={['Ep1 — done', 'Ep2 — skipped: would egress']}
        assertive=""
      />,
    );
    const log = container.querySelector('[role="log"]');
    expect(log?.getAttribute('aria-live')).toBe('polite');
    const lines = log?.querySelectorAll('.batch-livestatus__line');
    expect(lines?.length).toBe(2);
    expect(log?.textContent).toContain('Ep2 — skipped: would egress');
  });

  it('renders an assertive alert region for errors', () => {
    render(<LiveStatusRegion aggregate="" politeLog={[]} assertive="Ep3 — failed: boom" />);
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.getAttribute('aria-live')).toBe('assertive');
    expect(alert?.textContent).toBe('Ep3 — failed: boom');
  });
});
