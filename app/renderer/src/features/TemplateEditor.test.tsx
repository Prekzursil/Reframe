// TemplateEditor.test.tsx — curated-preset-first (no raw method ids) + CRUD.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { ExportPreset, Template } from '../lib/rpc';

const tmplListMock = vi.fn();
const tmplSaveMock = vi.fn();
const tmplDeleteMock = vi.fn();
const presetListMock = vi.fn();

vi.mock('../lib/rpc', () => ({
  client: {
    templates: {
      list: (...a: unknown[]) => tmplListMock(...a),
      save: (...a: unknown[]) => tmplSaveMock(...a),
      delete: (...a: unknown[]) => tmplDeleteMock(...a),
    },
    exportPresets: {
      list: (...a: unknown[]) => presetListMock(...a),
    },
  },
}));

import { TemplateEditor } from './TemplateEditor';

const PRESETS: ExportPreset[] = [
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
  {
    id: 'shorts',
    label: 'Shorts',
    aspect: '9:16',
    minSec: 20,
    maxSec: 60,
    count: 5,
    captionStyle: 'clean',
    reframeEngine: 'auto',
  },
];

const SAVED: Template[] = [
  { id: 't1', name: 'House style', steps: [], defaultControls: {}, exportTargets: ['tiktok'] },
];

let container: HTMLElement;
let root: Root;

const onChangedSpy = vi.fn();

async function render(): Promise<void> {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<TemplateEditor onChanged={onChangedSpy} />);
  });
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  tmplListMock.mockResolvedValue({ templates: SAVED });
  tmplSaveMock.mockResolvedValue({ template: SAVED[0] });
  tmplDeleteMock.mockResolvedValue({ ok: true });
  presetListMock.mockResolvedValue({ presets: PRESETS });
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

describe('TemplateEditor', () => {
  it('loads templates + presets', async () => {
    await render();
    expect(tmplListMock).toHaveBeenCalledTimes(1);
    expect(presetListMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain('House style');
  });

  it('exposes ZERO raw method ids in the DOM (curated labels only)', async () => {
    await render();
    const text = container.textContent ?? '';
    expect(text).not.toContain('shortmaker.select');
    expect(text).not.toContain('shortmaker.export');
    expect(text).not.toContain('phase8.select');
    expect(text).not.toContain('transcribe.start');
  });

  it('offers export targets from the preset labels (closed set)', async () => {
    await render();
    const targets = container.querySelector('.template-editor__targets');
    expect(targets?.textContent).toContain('TikTok');
    expect(targets?.textContent).toContain('Shorts');
  });

  it('saves a template built from the chosen starter + targets + controls', async () => {
    await render();
    // change the name + count
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!
      .set!;
    const name = container.querySelector('input[aria-label="Template name"]') as HTMLInputElement;
    const count = container.querySelector(
      'input[aria-label="Shorts per source"]',
    ) as HTMLInputElement;
    act(() => {
      setter.call(name, 'My pod');
      name.dispatchEvent(new Event('input', { bubbles: true }));
      setter.call(count, '3');
      count.dispatchEvent(new Event('input', { bubbles: true }));
    });
    // pick the second starter
    const starter = container.querySelector(
      'select[aria-label="Starter template"]',
    ) as HTMLSelectElement;
    const selSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')!
      .set!;
    act(() => {
      selSetter.call(starter, 'captioned-shorts');
      starter.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // toggle tiktok target on then off then on (covers both branches)
    const tiktok = container.querySelectorAll(
      '.template-editor__target input',
    )[0] as HTMLInputElement;
    act(() => tiktok.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    act(() => tiktok.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    act(() => tiktok.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await act(async () => {
      clickText('Save template');
      await Promise.resolve();
    });
    expect(tmplSaveMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'My pod',
        defaultControls: { count: 3 },
        exportTargets: ['tiktok'],
      }),
    );
  });

  it('floors count at 1 on non-numeric input', async () => {
    await render();
    const count = container.querySelector(
      'input[aria-label="Shorts per source"]',
    ) as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!
      .set!;
    act(() => {
      setter.call(count, 'x');
      count.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(
      (container.querySelector('input[aria-label="Shorts per source"]') as HTMLInputElement).value,
    ).toBe('1');
  });

  it('deletes a saved template', async () => {
    await render();
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(tmplDeleteMock).toHaveBeenCalledWith('t1');
  });

  it('shows a load error (Error and non-Error)', async () => {
    tmplListMock.mockRejectedValueOnce(new Error('list-bad'));
    await render();
    expect(container.querySelector('.template-editor__error')?.textContent).toBe('list-bad');
  });

  it('shows a generic load error on non-Error rejection', async () => {
    tmplListMock.mockRejectedValueOnce('x');
    await render();
    expect(container.querySelector('.template-editor__error')?.textContent).toBe(
      'Failed to load templates',
    );
  });

  it('surfaces save + delete failures', async () => {
    await render();
    tmplSaveMock.mockRejectedValueOnce('x');
    await act(async () => {
      clickText('Save template');
      await Promise.resolve();
    });
    expect(container.querySelector('.template-editor__error')?.textContent).toBe('Save failed');

    tmplDeleteMock.mockRejectedValueOnce('x');
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(container.querySelector('.template-editor__error')?.textContent).toBe('Delete failed');
  });

  it('surfaces Error-typed save + delete messages (instanceof arm)', async () => {
    await render();
    tmplSaveMock.mockRejectedValueOnce(new Error('save-e'));
    await act(async () => {
      clickText('Save template');
      await Promise.resolve();
    });
    expect(container.querySelector('.template-editor__error')?.textContent).toBe('save-e');

    tmplDeleteMock.mockRejectedValueOnce(new Error('del-e'));
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(container.querySelector('.template-editor__error')?.textContent).toBe('del-e');
  });

  it('notifies onChanged after a successful save + delete', async () => {
    await render();
    await act(async () => {
      clickText('Save template');
      await Promise.resolve();
    });
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(onChangedSpy).toHaveBeenCalledTimes(2);
  });
});
