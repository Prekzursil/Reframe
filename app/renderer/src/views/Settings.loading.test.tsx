// Settings.loading.test.tsx — what Settings shows while its lazy panel loads.
//
// Library.tsx:616-618 states the app's own rule: "never a bare LOADING...". The
// Models & System section broke it — Settings.tsx:157 rendered the literal string
// "Loading…" as its Suspense fallback, so the heaviest panel in the app was also
// the one with the cheapest loading state. This pins the shaped skeleton instead,
// and pins that the bare string does not come back.
//
// The panel is stubbed with a component that SUSPENDS FOREVER, which is the only
// way to hold the fallback on screen long enough to assert against it.
//
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const NEVER: Promise<never> = new Promise<never>(() => {});
vi.mock('../panels/ModelsSystemPanel', () => ({
  default: () => {
    throw NEVER;
  },
}));

import { SETTINGS_SECTIONS } from './Settings';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

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

describe('Settings — the Models & System loading state', () => {
  it('shows a shaped skeleton, never the bare "Loading" string', async () => {
    const models = SETTINGS_SECTIONS.find((s) => s.id === 'models');
    expect(models).toBeDefined();

    await act(async () => {
      root.render(models?.render({ goTo: vi.fn() }));
    });

    const group = container.querySelector('.skeleton-group--panel');
    expect(group).not.toBeNull();
    // A heading bar over three body lines — the shape of the panel that lands.
    expect(container.querySelectorAll('.skeleton')).toHaveLength(4);
    expect(container.textContent).not.toContain('Loading');
  });

  it('announces the wait to assistive tech instead of leaving dead air', async () => {
    const models = SETTINGS_SECTIONS.find((s) => s.id === 'models');

    await act(async () => {
      root.render(models?.render({ goTo: vi.fn() }));
    });

    const group = container.querySelector('.skeleton-group--panel');
    expect(group?.getAttribute('role')).toBe('status');
    expect(group?.getAttribute('aria-label')).toContain('Models');
  });
});
