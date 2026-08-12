// Settings.loading.test.tsx — what Settings shows while its lazy panel loads.
//
// Library.tsx's own comment states the app's rule: "never a bare LOADING...".
// The Models & System section broke it — Settings.tsx rendered the literal string
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

/**
 * Elements whose ENTIRE text is the bare fallback the app's own rule forbids.
 * The rule is "never a bare LOADING…", NOT "never the word Loading" — the status
 * region legitimately carries the wait as text, so a substring match would ban
 * the fix along with the defect.
 */
const bareLoadingNodes = (root_: ParentNode): HTMLElement[] =>
  Array.from(root_.querySelectorAll<HTMLElement>('*')).filter(
    (el) => el.textContent?.trim() === 'Loading…',
  );

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
    expect(bareLoadingNodes(container)).toHaveLength(0);

    // DETECTOR CONTROL: the matcher must FIRE on the state this test forbids, or
    // its silence above measures nothing. (It is exactly the old markup: a node
    // whose whole content is the bare string.)
    const decoy = document.createElement('div');
    decoy.textContent = 'Loading…';
    container.appendChild(decoy);
    expect(bareLoadingNodes(container)).toHaveLength(1);
    decoy.remove();
    expect(bareLoadingNodes(container)).toHaveLength(0);
  });

  it('labels the wait as a busy status region that carries real text', async () => {
    const models = SETTINGS_SECTIONS.find((s) => s.id === 'models');

    await act(async () => {
      root.render(models?.render({ goTo: vi.fn() }));
    });

    // What this DOES assert: the markup contract. What it does NOT assert — and
    // jsdom cannot — is that a screen reader speaks it. See the Skeleton.tsx
    // header for the honest scope of that claim.
    const group = container.querySelector('.skeleton-group--panel');
    expect(group?.getAttribute('role')).toBe('status');
    expect(group?.getAttribute('aria-busy')).toBe('true');
    expect(group?.textContent).toContain('Models & System');
  });
});
