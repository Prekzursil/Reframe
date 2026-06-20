// ReadinessBadge.test.tsx — render tests for the shared readiness status pill
// (WU-9). Mirrors advisorComponents' raw-DOM convention (createRoot + jsdom).
// Pins the WCAG-1.4.1 guard: status is asserted by visible TEXT + role, never by
// hue alone; every action control is a real <button> with a capability-tied name.

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ReadinessBadge } from './ReadinessBadge';
import { READINESS_LABEL, READINESS_CLASS } from './readinessMeta';
import type { ReadinessAction, ReadinessStatus } from '../lib/rpc';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

async function render(node: React.ReactElement): Promise<void> {
  await act(async () => {
    root.render(node);
  });
}

const STATUSES: ReadinessStatus[] = [
  'ready',
  'needsDownload',
  'needsKey',
  'needsConsent',
  'unavailable',
];

describe('<ReadinessBadge /> — status pill', () => {
  it.each(
    STATUSES,
  )('renders %s by visible text + role + data attr (not hue alone)', async (status) => {
    await render(<ReadinessBadge status={status} capabilityLabel="Captions" />);
    const badge = container.querySelector('[role="status"]') as HTMLElement;
    // Visible TEXT label — the use-of-color guard (query text, not class).
    expect(badge.textContent).toBe(READINESS_LABEL[status]);
    expect(badge.tagName).toBe('SPAN');
    expect(badge.getAttribute('data-readiness')).toBe(status);
    // Reuses verdict-badge pill geometry + a parallel readiness class.
    expect(badge.classList.contains('verdict-badge')).toBe(true);
    expect(badge.classList.contains('readiness-badge')).toBe(true);
    expect(badge.classList.contains(READINESS_CLASS[status])).toBe(true);
    // Title names blocker + fix (non-empty).
    expect(badge.title.length).toBeGreaterThan(0);
  });

  it('appends a blockedBy reason to the title when supplied', async () => {
    await render(
      <ReadinessBadge status="needsKey" capabilityLabel="Captions" blockedBy="No OpenAI key" />,
    );
    const badge = container.querySelector('[role="status"]') as HTMLElement;
    expect(badge.title).toContain('No OpenAI key');
  });
});

describe('<ReadinessBadge /> — action button', () => {
  it('renders an assets.ensure action as a button naming the capability', async () => {
    const action: ReadinessAction = { kind: 'assets.ensure', assets: ['saliency'] };
    await render(
      <ReadinessBadge status="needsDownload" capabilityLabel="Captions" action={action} />,
    );
    const button = container.querySelector('button') as HTMLButtonElement;
    expect(button.getAttribute('aria-label')).toBe('Download Captions model');
    expect(button.tagName).toBe('BUTTON');
  });

  it('renders an openProviders action as a button', async () => {
    const action: ReadinessAction = { kind: 'openProviders' };
    await render(<ReadinessBadge status="needsKey" capabilityLabel="Captions" action={action} />);
    const button = container.querySelector('button') as HTMLButtonElement;
    expect(button.getAttribute('aria-label')).toBe('Add a provider key');
  });

  it('renders a setConsent action as a button naming the provider', async () => {
    const action: ReadinessAction = { kind: 'setConsent', provider: 'openai' };
    await render(
      <ReadinessBadge status="needsConsent" capabilityLabel="Captions" action={action} />,
    );
    const button = container.querySelector('button') as HTMLButtonElement;
    expect(button.getAttribute('aria-label')).toBe('Grant consent for openai');
  });

  it('renders NO button when there is no action (ready / blocked-no-fix)', async () => {
    await render(<ReadinessBadge status="ready" capabilityLabel="Captions" />);
    expect(container.querySelector('button')).toBeNull();
  });

  it('invokes onAction with the action when the button is clicked', async () => {
    const action: ReadinessAction = { kind: 'openProviders' };
    let received: ReadinessAction | null = null;
    await render(
      <ReadinessBadge
        status="needsKey"
        capabilityLabel="Captions"
        action={action}
        onAction={(a) => {
          received = a;
        }}
      />,
    );
    const button = container.querySelector('button') as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    expect(received).toBe(action);
  });

  it('does not throw when the button is clicked with no onAction handler', async () => {
    const action: ReadinessAction = { kind: 'openProviders' };
    await render(<ReadinessBadge status="needsKey" capabilityLabel="Captions" action={action} />);
    const button = container.querySelector('button') as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    expect(button).toBeTruthy();
  });
});
