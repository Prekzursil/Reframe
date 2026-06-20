// ExportPresetsPanel.test.tsx — preset table: closed caption-style select +
// inline window clamp + CRUD/reset wiring (§7 / §10.5).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { ExportPreset } from '../lib/rpc';

const listMock = vi.fn();
const saveMock = vi.fn();
const deleteMock = vi.fn();
const resetMock = vi.fn();

vi.mock('../lib/rpc', () => ({
  client: {
    exportPresets: {
      list: (...a: unknown[]) => listMock(...a),
      save: (...a: unknown[]) => saveMock(...a),
      delete: (...a: unknown[]) => deleteMock(...a),
      reset: (...a: unknown[]) => resetMock(...a),
    },
  },
}));

import { ExportPresetsPanel } from './ExportPresetsPanel';
import { CAPTION_STYLE_OPTIONS } from './repurposeLogic';

const SEED: ExportPreset[] = [
  {
    id: 'tiktok',
    label: 'TikTok',
    aspect: '9:16',
    minSec: 20,
    maxSec: 60,
    count: 5,
    captionStyle: 'tiktok',
    reframeEngine: 'auto',
  },
];

let container: HTMLElement;
let root: Root;

const onChangedSpy = vi.fn();

async function render(): Promise<void> {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<ExportPresetsPanel onChanged={onChangedSpy} />);
  });
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  listMock.mockResolvedValue({ presets: SEED });
  saveMock.mockResolvedValue({ preset: SEED[0] });
  deleteMock.mockResolvedValue({ ok: true });
  resetMock.mockResolvedValue({ presets: SEED });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  onChangedSpy.mockClear();
  vi.clearAllMocks();
});

function clickText(text: string): void {
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent === text);
  if (!btn) throw new Error(`button not found: ${text}`);
  act(() => btn.dispatchEvent(new MouseEvent('click', { bubbles: true })));
}

describe('ExportPresetsPanel', () => {
  it('loads and renders the preset rows', async () => {
    await render();
    expect(listMock).toHaveBeenCalledTimes(1);
    const label = container.querySelector('input[aria-label="Preset label"]') as HTMLInputElement;
    expect(label.value).toBe('TikTok');
  });

  it('caption-style control is a closed select of valid ids only', async () => {
    await render();
    const select = container.querySelector(
      'select[aria-label="Caption style"]',
    ) as HTMLSelectElement;
    const ids = [...select.options].map((o) => o.value);
    expect(ids).toEqual([...CAPTION_STYLE_OPTIONS]);
    // an out-of-set id is not an option (unselectable).
    expect(ids).not.toContain('__nope__');
  });

  it('clamps an over-max duration in the maxSec input', async () => {
    await render();
    const maxInput = container.querySelector(
      'input[aria-label="Maximum seconds"]',
    ) as HTMLInputElement;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!
        .set!;
      setter.call(maxInput, '600');
      maxInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(
      (container.querySelector('input[aria-label="Maximum seconds"]') as HTMLInputElement).value,
    ).toBe('60');
  });

  it('floors the count at 1 (and on non-numeric)', async () => {
    await render();
    const countInput = container.querySelector(
      'input[aria-label="Clip count"]',
    ) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!
      .set!;
    act(() => {
      setter.call(countInput, '0');
      countInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(
      (container.querySelector('input[aria-label="Clip count"]') as HTMLInputElement).value,
    ).toBe('1');
    act(() => {
      setter.call(countInput, 'abc');
      countInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(
      (container.querySelector('input[aria-label="Clip count"]') as HTMLInputElement).value,
    ).toBe('1');
  });

  it('edits label/aspect/minSec/style/engine and saves the draft', async () => {
    await render();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!
      .set!;
    const label = container.querySelector('input[aria-label="Preset label"]') as HTMLInputElement;
    const aspect = container.querySelector('input[aria-label="Aspect ratio"]') as HTMLInputElement;
    const minInput = container.querySelector(
      'input[aria-label="Minimum seconds"]',
    ) as HTMLInputElement;
    act(() => {
      setter.call(label, 'TT');
      label.dispatchEvent(new Event('input', { bubbles: true }));
      setter.call(aspect, '1:1');
      aspect.dispatchEvent(new Event('input', { bubbles: true }));
      setter.call(minInput, '25');
      minInput.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const style = container.querySelector(
      'select[aria-label="Caption style"]',
    ) as HTMLSelectElement;
    const engine = container.querySelector(
      'select[aria-label="Reframe engine"]',
    ) as HTMLSelectElement;
    const selSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')!
      .set!;
    act(() => {
      selSetter.call(style, 'hormozi');
      style.dispatchEvent(new Event('change', { bubbles: true }));
      selSetter.call(engine, 'verthor');
      engine.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      clickText('Save');
      await Promise.resolve();
    });
    expect(saveMock).toHaveBeenCalledWith(
      expect.objectContaining({
        label: 'TT',
        aspect: '1:1',
        minSec: 25,
        captionStyle: 'hormozi',
        reframeEngine: 'verthor',
      }),
    );
  });

  it('deletes a preset', async () => {
    await render();
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(deleteMock).toHaveBeenCalledWith('tiktok');
  });

  it('adds a new preset via save with an empty id', async () => {
    await render();
    await act(async () => {
      clickText('New preset');
      await Promise.resolve();
    });
    expect(saveMock).toHaveBeenCalledWith(expect.objectContaining({ id: '', label: 'New preset' }));
  });

  it('resets to defaults', async () => {
    await render();
    await act(async () => {
      clickText('Reset to defaults');
      await Promise.resolve();
    });
    expect(resetMock).toHaveBeenCalledTimes(1);
  });

  it('shows an error when load fails', async () => {
    listMock.mockRejectedValueOnce(new Error('nope'));
    await render();
    expect(container.querySelector('.export-presets__error')?.textContent).toBe('nope');
  });

  it('shows a generic error when load rejects a non-Error', async () => {
    listMock.mockRejectedValueOnce('boom');
    await render();
    expect(container.querySelector('.export-presets__error')?.textContent).toBe(
      'Failed to load presets',
    );
  });

  it('surfaces save / delete / reset failures', async () => {
    await render();
    saveMock.mockRejectedValueOnce('x');
    await act(async () => {
      clickText('Save');
      await Promise.resolve();
    });
    expect(container.querySelector('.export-presets__error')?.textContent).toBe('Save failed');

    deleteMock.mockRejectedValueOnce('x');
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(container.querySelector('.export-presets__error')?.textContent).toBe('Delete failed');

    resetMock.mockRejectedValueOnce('x');
    await act(async () => {
      clickText('Reset to defaults');
      await Promise.resolve();
    });
    expect(container.querySelector('.export-presets__error')?.textContent).toBe('Reset failed');
  });

  it('surfaces Error-typed save/delete/reset messages (instanceof arm)', async () => {
    await render();
    saveMock.mockRejectedValueOnce(new Error('save-e'));
    await act(async () => {
      clickText('Save');
      await Promise.resolve();
    });
    expect(container.querySelector('.export-presets__error')?.textContent).toBe('save-e');

    deleteMock.mockRejectedValueOnce(new Error('del-e'));
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(container.querySelector('.export-presets__error')?.textContent).toBe('del-e');

    resetMock.mockRejectedValueOnce(new Error('reset-e'));
    await act(async () => {
      clickText('Reset to defaults');
      await Promise.resolve();
    });
    expect(container.querySelector('.export-presets__error')?.textContent).toBe('reset-e');
  });

  it('notifies onChanged after a successful save / delete / reset', async () => {
    await render();
    await act(async () => {
      clickText('Save');
      await Promise.resolve();
    });
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    await act(async () => {
      clickText('Reset to defaults');
      await Promise.resolve();
    });
    expect(onChangedSpy).toHaveBeenCalledTimes(3);
  });
});
