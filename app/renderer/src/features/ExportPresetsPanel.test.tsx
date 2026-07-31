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

/** The (single) input carrying `aria-label`, re-queried so a re-render is seen. */
function field(label: string): HTMLInputElement {
  return container.querySelector(`input[aria-label="${label}"]`) as HTMLInputElement;
}

/** Type into a controlled input the way a browser does (native setter + `input`). */
function type(label: string, value: string): void {
  const el = field(label);
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

/** Append one character to a field's CURRENT value (models a real keystroke). */
function typeMore(label: string, char: string): void {
  type(label, `${field(label).value}${char}`);
}

/** Commit a field — React's `onBlur` is the bubbling native `focusout`. */
function blur(label: string): void {
  const el = field(label);
  act(() => el.dispatchEvent(new FocusEvent('focusout', { bubbles: true })));
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

  // F12 — the clamp must NOT run on every keystroke. Typing digit-by-digit toward
  // an in-window value has to be possible; the clamp fires at the COMMIT points.
  it('does not clamp mid-typing: consecutive keystrokes land in the field', async () => {
    await render();
    type('Minimum seconds', '4');
    expect(field('Minimum seconds').value).toBe('4');
    typeMore('Minimum seconds', '5');
    expect(field('Minimum seconds').value).toBe('45');
  });

  // F12 — the §7/§10.5 invariant (no out-of-window preset is authorable) still
  // holds, just at blur + save instead of per keystroke.
  it('clamps an over-max duration at the commit points (blur, then save)', async () => {
    await render();
    type('Maximum seconds', '600');
    expect(field('Maximum seconds').value).toBe('600');
    blur('Maximum seconds');
    expect(field('Maximum seconds').value).toBe('60');
    await act(async () => {
      clickText('Save');
      await Promise.resolve();
    });
    expect(saveMock).toHaveBeenCalledWith(expect.objectContaining({ maxSec: 60 }));
  });

  // F27 — the two duration cells are independent today, so `{minSec:60,maxSec:20}`
  // is authorable and POSTed verbatim: a window NEITHER the renderer's nor the
  // sidecar's policy permits.
  it('never commits an inverted window (Max edited last wins)', async () => {
    await render();
    type('Minimum seconds', '60');
    type('Maximum seconds', '20');
    await act(async () => {
      clickText('Save');
      await Promise.resolve();
    });
    expect(saveMock).toHaveBeenCalledWith(expect.objectContaining({ minSec: 20, maxSec: 20 }));
  });

  // F27 — direction-aware coupling: the field just edited wins. A symmetric
  // `max := min` rule would make Max un-lowerable (40-60 could never narrow).
  it('lowering Max below Min pulls Min down, not Max back up', async () => {
    await render();
    type('Minimum seconds', '40');
    blur('Minimum seconds');
    type('Maximum seconds', '30');
    blur('Maximum seconds');
    expect(field('Maximum seconds').value).toBe('30');
    expect(field('Minimum seconds').value).toBe('30');
  });

  it('raising Min above Max pushes Max up, not Min back down', async () => {
    await render();
    type('Maximum seconds', '30');
    blur('Maximum seconds');
    type('Minimum seconds', '50');
    blur('Minimum seconds');
    expect(field('Minimum seconds').value).toBe('50');
    expect(field('Maximum seconds').value).toBe('50');
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

  // F26 — the draft-resync effect was keyed on the `preset` OBJECT IDENTITY, and
  // every reload crosses IPC + a JSON re-read in the sidecar, so each row got a
  // fresh identity and the effect wiped sibling rows' unsaved keystrokes.
  it("keeps a sibling row's unsaved edits when another row is saved", async () => {
    const TWO: ExportPreset[] = [SEED[0], { ...SEED[0], id: 'reels', label: 'Reels', count: 3 }];
    // Faithful to the wire: `list()` yields brand-new identities on EVERY call.
    // The shared-identity fixture used elsewhere in this file hides the defect.
    listMock.mockImplementation(() => Promise.resolve({ presets: TWO.map((p) => ({ ...p })) }));
    await render();
    const labels = (): HTMLInputElement[] =>
      [...container.querySelectorAll('input[aria-label="Preset label"]')] as HTMLInputElement[];
    expect(labels()).toHaveLength(2); // guard: both rows mounted
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!
      .set!;
    act(() => {
      setter.call(labels()[1], 'KEEP-ME');
      labels()[1].dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(labels()[1].value).toBe('KEEP-ME'); // guard: the keystroke reached row 2
    await act(async () => {
      clickText('Save'); // the FIRST Save button — row 1's
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve(); // drain save -> reload -> setPresets
    });
    // guard: the save that ran targeted the OTHER row
    expect(saveMock).toHaveBeenCalledWith(expect.objectContaining({ id: 'tiktok' }));
    expect(labels()[1].value).toBe('KEEP-ME');
  });

  // F26 companion — a value fingerprint ALONE breaks the acted-on row: the sidecar
  // strips whitespace (`_require_str`, export_presets.py:75-79), so this save stores
  // a row byte-identical to the one already on disk. The fingerprint never changes,
  // so only the per-row sync nonce can pull the rejected text back to the truth.
  it('re-displays the server value after a normalisation-only save', async () => {
    await render();
    type('Preset label', 'TikTok  ');
    expect(field('Preset label').value).toBe('TikTok  ');
    await act(async () => {
      clickText('Save');
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(saveMock).toHaveBeenCalledWith(expect.objectContaining({ label: 'TikTok  ' }));
    expect(field('Preset label').value).toBe('TikTok');
  });

  it('deletes a preset', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
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
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await render();
    await act(async () => {
      clickText('Reset to defaults');
      await Promise.resolve();
    });
    expect(resetMock).toHaveBeenCalledTimes(1);
  });

  // F13 — Reset overwrites the whole catalog (`PresetStore.reset` re-seeds and
  // `_write` keeps no prior copy, so there is no restore path) and per-row Delete
  // is equally final. Both were one-click, against the project's own standard
  // ("never a silent one-click destructive action", KeepCopyControl.tsx:21).
  it('does not reset when the confirm is declined', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await render();
    await act(async () => {
      clickText('Reset to defaults');
      await Promise.resolve();
    });
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(resetMock).not.toHaveBeenCalled();
  });

  it('does not delete when the confirm is declined', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await render();
    await act(async () => {
      clickText('Delete');
      await Promise.resolve();
    });
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(deleteMock).not.toHaveBeenCalled();
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
    vi.spyOn(window, 'confirm').mockReturnValue(true);
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
    vi.spyOn(window, 'confirm').mockReturnValue(true);
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
    vi.spyOn(window, 'confirm').mockReturnValue(true);
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
