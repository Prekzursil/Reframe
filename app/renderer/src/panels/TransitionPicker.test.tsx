// TransitionPicker.test.tsx — the UI that lets a user CHOOSE a transition
// (v1.5 transitions lane). Before this, every join in the product was a hard cut
// and there was no control anywhere to say otherwise.
//
// The three behaviours worth guarding are the honest ones: the running total
// must show the timeline getting SHORTER than a hard cut, the re-encode cost must
// be visible before the user commits, and a selection the engine would reject
// must be blocked HERE with the offending clip named — not after a wasted render.

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { type Root, createRoot } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { DirectorOp } from '../lib/rpc';
import { type TransitionClip, TransitionPicker } from './TransitionPicker';

const SOURCE: TransitionClip = { path: '/a.mp4', label: 'Opening', durationMs: 10_000 };
const CLIPS: readonly TransitionClip[] = [
  { path: '/b.mp4', label: 'Middle', durationMs: 20_000 },
  { path: '/c.mp4', label: 'Closer', durationMs: 30_000 },
  { path: '/tiny.mp4', label: 'Sting', durationMs: 400 },
];

let container: HTMLDivElement;
let root: Root;
let onAdd: ReturnType<typeof vi.fn>;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  onAdd = vi.fn();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function mount(over: { available?: readonly TransitionClip[]; disabled?: boolean } = {}) {
  await act(async () => {
    root.render(
      <TransitionPicker
        opId="t1"
        source={SOURCE}
        available={over.available ?? CLIPS}
        onAdd={onAdd}
        disabled={over.disabled}
      />,
    );
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

async function setInput(sel: string, value: string): Promise<void> {
  const input = $(sel) as HTMLInputElement;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function selectStyle(value: string): Promise<void> {
  const select = $('[data-action="style"]') as HTMLSelectElement;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')?.set;
  await act(async () => {
    setter?.call(select, value);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

describe('TransitionPicker', () => {
  it('offers every sidecar-supported style, defaulting to the cross dissolve', async () => {
    await mount();
    const select = $('[data-action="style"]') as HTMLSelectElement;
    expect(select.value).toBe('dissolve');
    expect(select.options.length).toBe(11);
    expect(select.options[2].textContent).toBe('Cross dissolve');
    // The blurb explains what the viewer will SEE, not the ffmpeg filter name.
    expect($('[data-testid="style-blurb"]').textContent).toContain('blend through each other');
  });

  it('starts with nothing selected, so Add is blocked with the reason shown', async () => {
    await mount();
    expect(($('[data-action="add"]') as HTMLButtonElement).disabled).toBe(true);
    expect($('[data-testid="blocker"]').textContent).toContain('at least two clips');
    // No boundary yet -> no cost to disclose.
    expect(container.querySelector('[data-testid="reencode"]')).toBeNull();
  });

  it('shows the OVERLAP-SUBTRACTED total once a clip is picked', async () => {
    await mount();
    await click('[data-clip="/b.mp4"]');
    // 10s + 20s with the default 500ms dissolve = 29.5s, not 30s.
    expect($('[data-testid="total"]').textContent).toContain('29.5s');
    expect($('[data-testid="total"]').textContent).toContain('0.5s shorter than a hard cut');
  });

  it('discloses the re-encode cost as soon as there is a boundary', async () => {
    await mount();
    await click('[data-clip="/b.mp4"]');
    expect($('[data-testid="reencode"]').textContent).toContain('re-encode');
    expect($('[data-testid="reencode"]').textContent).toContain('1 transition boundary');
    await click('[data-clip="/c.mp4"]');
    expect($('[data-testid="reencode"]').textContent).toContain('2 transition boundaries');
  });

  it('blocks a clip that cannot outlast the transition, naming it', async () => {
    await mount();
    await click('[data-clip="/tiny.mp4"]');
    expect($('[data-testid="blocker"]').textContent).toContain('Clip 2');
    expect($('[data-testid="blocker"]').textContent).toContain('shorter than');
    expect(($('[data-action="add"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('un-blocks when the transition is shortened below the shortest clip', async () => {
    await mount();
    await click('[data-clip="/tiny.mp4"]');
    expect(($('[data-action="add"]') as HTMLButtonElement).disabled).toBe(true);
    await setInput('[data-action="duration"]', '300');
    expect(container.querySelector('[data-testid="blocker"]')).toBeNull();
    expect(($('[data-action="add"]') as HTMLButtonElement).disabled).toBe(false);
  });

  it('deselects a clip on a second click', async () => {
    await mount();
    await click('[data-clip="/b.mp4"]');
    await click('[data-clip="/c.mp4"]');
    expect($('[data-testid="total"]').textContent).toContain('59.0s');
    await click('[data-clip="/b.mp4"]');
    expect($('[data-testid="total"]').textContent).toContain('39.5s');
  });

  it('reflects the chosen style in the label, blurb and duration readout', async () => {
    await mount();
    await selectStyle('fadeBlack');
    expect($('[data-testid="style-blurb"]').textContent).toContain('Dips to black');
    await setInput('[data-action="duration"]', '1200');
    expect($('[data-testid="duration-readout"]').textContent).toBe('1.2s');
  });

  it('emits a wire-valid transition op carrying the selection, in pick order', async () => {
    await mount();
    await selectStyle('wipeLeft');
    await setInput('[data-action="duration"]', '1500');
    await click('[data-clip="/c.mp4"]');
    await click('[data-clip="/b.mp4"]');
    await click('[data-action="add"]');

    expect(onAdd).toHaveBeenCalledTimes(1);
    const op = onAdd.mock.calls[0][0] as DirectorOp;
    expect(op.kind).toBe('transition');
    expect(op.id).toBe('t1');
    expect(op.span).toBeNull();
    expect(op.params).toEqual({
      clips: ['/c.mp4', '/b.mp4'],
      style: 'wipeLeft',
      durationMs: 1500,
    });
  });

  it('clears the selection after a successful add', async () => {
    await mount();
    await click('[data-clip="/b.mp4"]');
    await click('[data-action="add"]');
    expect($('[data-testid="blocker"]').textContent).toContain('at least two clips');
    expect(($('[data-action="add"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('disables every control while the parent is busy', async () => {
    await mount({ disabled: true });
    expect(($('[data-action="style"]') as HTMLSelectElement).disabled).toBe(true);
    expect(($('[data-action="duration"]') as HTMLInputElement).disabled).toBe(true);
    expect(($('[data-clip="/b.mp4"]') as HTMLButtonElement).disabled).toBe(true);
    expect(($('[data-action="add"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('says so plainly when there is nothing to join to', async () => {
    await mount({ available: [] });
    expect($('[data-testid="empty"]').textContent).toContain('No other clips');
    expect(container.querySelector('[data-clip]')).toBeNull();
  });

  it('marks a picked clip as pressed for assistive tech', async () => {
    await mount();
    expect($('[data-clip="/b.mp4"]').getAttribute('aria-pressed')).toBe('false');
    await click('[data-clip="/b.mp4"]');
    expect($('[data-clip="/b.mp4"]').getAttribute('aria-pressed')).toBe('true');
  });
});
