// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { CardProvenanceDisclosure } from './CardProvenanceDisclosure';
import type { ProvenanceHandlers } from '../features/LibraryProvenance';

function handlers(): ProvenanceHandlers & { reveal: ReturnType<typeof vi.fn> } {
  return {
    reveal: vi.fn(async () => ({
      id: 'v1',
      sources: [
        { id: 'v1', path: '/movies/talk.mp4', title: 'Talk', exists: true, relinkable: true },
      ],
      missing: [] as string[],
    })),
    pinHash: vi.fn(async () => ({})),
    relink: vi.fn(async () => {}),
    openInFolder: vi.fn(async () => true),
    pickRelinkTarget: vi.fn(async () => null),
  };
}

const video = { id: 'v1', path: '/movies/talk.mp4', title: 'Talk' };

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

async function flush(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  });
}

async function render(h: ProvenanceHandlers): Promise<void> {
  await act(async () => {
    root.render(<CardProvenanceDisclosure video={video} handlers={h} />);
  });
  await flush();
}

function toggle(): HTMLButtonElement {
  return container.querySelector('.card-provenance__toggle') as HTMLButtonElement;
}

async function click(el: HTMLElement): Promise<void> {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

describe('CardProvenanceDisclosure', () => {
  it('renders a collapsed toggle at rest — the provenance tail is demoted', async () => {
    const h = handlers();
    await render(h);
    const btn = toggle();
    expect(btn).not.toBeNull();
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    // The plumbing (path / on-disk / keep-a-copy) is NOT in the resting card…
    expect(container.querySelector('.library-provenance')).toBeNull();
    // …and it is not even fetched until the user asks for it (lazy).
    expect(h.reveal).not.toHaveBeenCalled();
    // The caret reads "collapsed".
    expect(container.querySelector('.card-provenance__caret')?.textContent).toBe('▾');
  });

  it('reveals the provenance panel on toggle and wires aria-controls to it', async () => {
    const h = handlers();
    await render(h);
    await click(toggle());

    expect(toggle().getAttribute('aria-expanded')).toBe('true');
    const panel = container.querySelector('.card-provenance__panel') as HTMLElement;
    expect(panel).not.toBeNull();
    expect(panel.querySelector('.library-provenance')).not.toBeNull();
    expect(toggle().getAttribute('aria-controls')).toBe(panel.id);
    expect(panel.id.length).toBeGreaterThan(0);
    // Opening the disclosure is what triggers the source lookup.
    expect((h as ReturnType<typeof handlers>).reveal).toHaveBeenCalledWith('v1');
    expect(container.querySelector('.card-provenance__caret')?.textContent).toBe('▴');
  });

  it('collapses again on a second toggle', async () => {
    const h = handlers();
    await render(h);
    await click(toggle());
    expect(container.querySelector('.library-provenance')).not.toBeNull();
    await click(toggle());
    expect(toggle().getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('.library-provenance')).toBeNull();
  });

  it('wraps the disclosure in a plain <div> — no duplicate "region" landmark per card', async () => {
    await render(handlers());
    const wrapper = container.querySelector('.card-provenance') as HTMLElement;
    expect(wrapper).not.toBeNull();
    // A per-card <section aria-label> minted N identical "Source & storage" region
    // landmarks across the Library; the toggle button already names the disclosure,
    // so the wrapper is a plain <div> carrying no landmark role or label.
    expect(wrapper.tagName).toBe('DIV');
    expect(wrapper.getAttribute('aria-label')).toBeNull();
    expect(container.querySelector('section')).toBeNull();
    expect(container.querySelector('[role="region"]')).toBeNull();
  });

  it('keeps aria-controls a valid IDREF at rest — panel is present but hidden + empty', async () => {
    await render(handlers());
    const btn = toggle();
    const controls = btn.getAttribute('aria-controls');
    expect(controls).toBeTruthy();
    // WAI-ARIA disclosure: the controlled panel is ALWAYS in the DOM (so the resting
    // card's aria-controls never dangles) and merely toggles `hidden`.
    const panel = document.getElementById(controls as string);
    expect(panel).not.toBeNull();
    expect(panel?.classList.contains('card-provenance__panel')).toBe(true);
    expect(panel?.hasAttribute('hidden')).toBe(true);
    // …while the heavy provenance body stays lazy — the hidden panel is empty at rest.
    expect(panel?.querySelector('.library-provenance')).toBeNull();
    // Opening un-hides the very same panel node (no dangling / swapped IDREF).
    await click(btn);
    expect(document.getElementById(controls as string)?.hasAttribute('hidden')).toBe(false);
  });
});
