// ReframeOverridePanel.test.tsx — the manual per-shot speaker/layout/crop
// correction panel (WU R2): override state (flip speaker / switch layout / nudge
// + zoom crop), the per-shot "changed" marking, and the affected-shot re-render
// handoff (Re-render passes EXACTLY the changed shot indices to the parent).

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { ReframeOverridePanel } from './ReframeOverridePanel';
import type { ShotPlan } from '../lib/reframeOverride';

function planFixture(): ShotPlan {
  return {
    sourceWidth: 1920,
    sourceHeight: 1080,
    fps: 30,
    shots: [
      {
        index: 0,
        startFrame: 0,
        endFrame: 3,
        speaker: 'a',
        layout: 'single',
        crop: [100, 0, 600, 1080],
        speakers: ['a', 'b'],
      },
      {
        index: 1,
        startFrame: 3,
        endFrame: 6,
        speaker: '',
        layout: 'split',
        crop: [200, 0, 600, 1080],
        speakers: [''],
      },
    ],
  };
}

let container: HTMLDivElement;
let root: Root;
let onRerender: ReturnType<typeof vi.fn>;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  onRerender = vi.fn();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function mount(plan: ShotPlan = planFixture()): Promise<void> {
  await act(async () => {
    root.render(<ReframeOverridePanel plan={plan} onRerender={onRerender} />);
  });
}

function $(sel: string): HTMLElement {
  const el = container.querySelector(sel);
  if (!el) throw new Error(`no element for ${sel}`);
  return el as HTMLElement;
}

async function click(sel: string): Promise<void> {
  await act(async () => {
    $(sel).click();
  });
}

async function selectLayout(shot: number, value: string): Promise<void> {
  const select = $(`select[id="layout-${shot}"]`) as HTMLSelectElement;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')?.set;
  await act(async () => {
    setter?.call(select, value);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

describe('ReframeOverridePanel', () => {
  it('renders each shot with its speaker, layout, and crop', async () => {
    await mount();
    expect($('[data-testid="speaker-0"]').textContent).toContain('a');
    // "" speaker renders as the friendly "Auto / none".
    expect($('[data-testid="speaker-1"]').textContent).toContain('Auto / none');
    expect($('[data-testid="crop-0"]').textContent).toBe('[100, 0, 600, 1080]');
    expect(($(`select[id="layout-1"]`) as HTMLSelectElement).value).toBe('split');
  });

  it('disables Flip when a shot has a single candidate, enables it otherwise', async () => {
    await mount();
    expect(($('[data-shot="0"] [data-action="flip-speaker"]') as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect(($('[data-shot="1"] [data-action="flip-speaker"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('starts with nothing to re-render and Reset disabled', async () => {
    await mount();
    const rerender = $('[data-action="rerender"]') as HTMLButtonElement;
    expect(rerender.disabled).toBe(true);
    expect(rerender.textContent).toBe('No changes to re-render');
    expect(($('[data-shot="0"] [data-action="reset"]') as HTMLButtonElement).disabled).toBe(true);
    expect($('[data-shot="0"]').getAttribute('data-changed')).toBe('no');
  });

  it('flips the speaker, marks the shot changed, and re-renders just that shot', async () => {
    await mount();
    await click('[data-shot="0"] [data-action="flip-speaker"]');
    expect($('[data-testid="speaker-0"]').textContent).toContain('b');
    expect($('[data-shot="0"]').getAttribute('data-changed')).toBe('yes');
    const rerender = $('[data-action="rerender"]') as HTMLButtonElement;
    expect(rerender.disabled).toBe(false);
    expect(rerender.textContent).toBe('Re-render 1 shot');
    await click('[data-action="rerender"]');
    expect(onRerender).toHaveBeenCalledWith([0]);
  });

  it('switches the layout via the select', async () => {
    await mount();
    await selectLayout(0, 'composite');
    expect(($(`select[id="layout-0"]`) as HTMLSelectElement).value).toBe('composite');
    expect($('[data-shot="0"]').getAttribute('data-changed')).toBe('yes');
  });

  it('nudges the crop in all four directions and zooms in/out', async () => {
    await mount();
    await click('[data-shot="0"] [data-action="nudge-left"]');
    expect($('[data-testid="crop-0"]').textContent).toBe('[84, 0, 600, 1080]');
    await click('[data-shot="0"] [data-action="nudge-right"]');
    expect($('[data-testid="crop-0"]').textContent).toBe('[100, 0, 600, 1080]');
    await click('[data-shot="0"] [data-action="nudge-down"]');
    expect($('[data-testid="crop-0"]').textContent).toBe('[100, 0, 600, 1080]'); // already at bottom (h===frame)
    await click('[data-shot="0"] [data-action="nudge-up"]');
    expect($('[data-testid="crop-0"]').textContent).toBe('[100, 0, 600, 1080]');
    await click('[data-shot="0"] [data-action="zoom-in"]');
    expect($('[data-testid="crop-0"]').textContent).toBe('[130, 54, 540, 972]');
    await click('[data-shot="0"] [data-action="zoom-out"]');
    expect($('[data-shot="0"]').getAttribute('data-changed')).toBe('yes');
  });

  it('resets a changed shot back to its original decision', async () => {
    await mount();
    await click('[data-shot="0"] [data-action="flip-speaker"]');
    expect($('[data-shot="0"]').getAttribute('data-changed')).toBe('yes');
    await click('[data-shot="0"] [data-action="reset"]');
    expect($('[data-testid="speaker-0"]').textContent).toContain('a');
    expect($('[data-shot="0"]').getAttribute('data-changed')).toBe('no');
    expect(($('[data-action="rerender"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('re-renders multiple changed shots (pluralised) with every affected index', async () => {
    await mount();
    await click('[data-shot="0"] [data-action="flip-speaker"]');
    await selectLayout(1, 'composite');
    const rerender = $('[data-action="rerender"]') as HTMLButtonElement;
    expect(rerender.textContent).toBe('Re-render 2 shots');
    await click('[data-action="rerender"]');
    expect(onRerender).toHaveBeenCalledWith([0, 1]);
  });
});
