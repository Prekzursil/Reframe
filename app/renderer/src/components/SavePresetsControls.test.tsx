// SavePresetsControls.test.tsx — list / apply / save / remove save-presets
// (UX/QoL WU-11).
//
// Fake `savePresets.*` client slice (no preload bridge). Pins the falsifiable
// acceptance: list renders rows with the active one tagged; Apply calls
// `savePresets.apply` + `onApply(bundle)` + marks active; Save upserts the live
// autosave/exportDefaults under the typed name and refreshes; Remove drops a row;
// empty/error states render; whitespace name is a no-op.
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SavePresetsControls, type SavePresetsRpc } from './SavePresetsControls';
import type { AutosaveSettings, ExportDefaults, SavePreset, SavePresetsBlock } from '../lib/rpc';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const AUTOSAVE: AutosaveSettings = { enabled: true, debounceMs: 1500 };
const EXPORT_DEFAULTS: ExportDefaults = { subtitleFormat: 'srt', nleFormat: 'edl', nleFps: 30 };

function preset(): SavePreset {
  return { autosave: { enabled: false, debounceMs: 800 }, exportDefaults: { nleFps: 24 } };
}

function block(active = 'Fast'): SavePresetsBlock {
  return { presets: { Fast: preset(), Slow: preset() }, active };
}

function makeRpc(overrides: Partial<SavePresetsRpc> = {}): SavePresetsRpc {
  return {
    list: vi.fn().mockResolvedValue(block()),
    apply: vi.fn().mockResolvedValue({ active: 'Slow', savePreset: preset() }),
    upsert: vi.fn().mockResolvedValue({ presets: block().presets }),
    remove: vi.fn().mockResolvedValue({ presets: { Slow: preset() }, active: '' }),
    ...overrides,
  };
}

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
  vi.restoreAllMocks();
});

async function mount(props: Parameters<typeof SavePresetsControls>[0]): Promise<void> {
  await act(async () => {
    root.render(<SavePresetsControls {...props} />);
  });
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function flush(): Promise<void> {
  return act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

/**
 * Type into a controlled <input>. React tracks the value via a native setter, so
 * a bare `el.value = x` is reverted on the synthetic event; we must call the
 * prototype setter before dispatching `input` for React's onChange to see it.
 */
function typeInto(el: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
  setter?.call(el, value);
  act(() => el.dispatchEvent(new Event('input', { bubbles: true })));
}

describe('<SavePresetsControls />', () => {
  it('lists the saved presets on mount, tagging the active one', async () => {
    const rpc = makeRpc();
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    expect(rpc.list).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-preset="Fast"]')).not.toBeNull();
    expect(container.querySelector('[data-preset="Slow"]')).not.toBeNull();
    const fast = container.querySelector('[data-preset="Fast"]') as HTMLElement;
    expect(fast.getAttribute('aria-current')).toBe('true');
    expect(fast.querySelector('.save-presets__active-tag')?.textContent).toBe('Active');
    // The non-active row carries no aria-current and no tag.
    const slow = container.querySelector('[data-preset="Slow"]') as HTMLElement;
    expect(slow.getAttribute('aria-current')).toBeNull();
    expect(slow.querySelector('.save-presets__active-tag')).toBeNull();
  });

  it('renders the empty state when there are no presets', async () => {
    const rpc = makeRpc({ list: vi.fn().mockResolvedValue({ presets: {}, active: '' }) });
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    expect(container.querySelector('.save-presets__empty')).not.toBeNull();
    expect(container.querySelector('.save-presets__list')).toBeNull();
  });

  it('tolerates a list payload missing presets/active (defensive defaults)', async () => {
    const rpc = makeRpc({ list: vi.fn().mockResolvedValue(null) });
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    expect(container.querySelector('.save-presets__empty')).not.toBeNull();
  });

  it('applies a preset: calls savePresets.apply, marks active, and pre-fills via onApply', async () => {
    const rpc = makeRpc();
    const onApply = vi.fn();
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS, onApply });
    const applyBtn = container.querySelector(
      '[data-preset="Slow"] .save-presets__apply',
    ) as HTMLButtonElement;
    await act(async () => applyBtn.click());
    await flush();
    expect(rpc.apply).toHaveBeenCalledWith('Slow');
    expect(onApply).toHaveBeenCalledWith(preset());
    // The active marker moves to Slow without a re-list.
    expect(
      (container.querySelector('[data-preset="Slow"]') as HTMLElement).getAttribute('aria-current'),
    ).toBe('true');
    expect(rpc.list).toHaveBeenCalledTimes(1);
  });

  it('applies without an onApply callback (optional prop omitted)', async () => {
    const rpc = makeRpc();
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    const applyBtn = container.querySelector(
      '[data-preset="Fast"] .save-presets__apply',
    ) as HTMLButtonElement;
    await act(async () => applyBtn.click());
    await flush();
    expect(rpc.apply).toHaveBeenCalledWith('Fast');
  });

  it('saves the live settings under the typed name, then refreshes and clears it', async () => {
    const rpc = makeRpc();
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    const input = container.querySelector('#save-presets-name') as HTMLInputElement;
    typeInto(input, 'My preset');
    const saveBtn = container.querySelector('.save-presets__save') as HTMLButtonElement;
    await act(async () => saveBtn.click());
    await flush();
    expect(rpc.upsert).toHaveBeenCalledWith('My preset', {
      autosave: AUTOSAVE,
      exportDefaults: EXPORT_DEFAULTS,
    });
    // Refresh after save (list called twice: mount + post-save).
    expect(rpc.list).toHaveBeenCalledTimes(2);
    // Name field cleared.
    expect((container.querySelector('#save-presets-name') as HTMLInputElement).value).toBe('');
  });

  it('trims the name and ignores a whitespace-only save (no RPC)', async () => {
    const rpc = makeRpc();
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    const input = container.querySelector('#save-presets-name') as HTMLInputElement;
    typeInto(input, '   ');
    const saveBtn = container.querySelector('.save-presets__save') as HTMLButtonElement;
    // The handler trims and no-ops on a blank name — no RPC fires.
    await act(async () => saveBtn.click());
    await flush();
    expect(rpc.upsert).not.toHaveBeenCalled();
  });

  it('removes a preset: calls savePresets.remove and drops the row', async () => {
    const rpc = makeRpc();
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    const removeBtn = container.querySelector(
      '[data-preset="Fast"] .save-presets__remove',
    ) as HTMLButtonElement;
    await act(async () => removeBtn.click());
    await flush();
    expect(rpc.remove).toHaveBeenCalledWith('Fast');
    expect(container.querySelector('[data-preset="Fast"]')).toBeNull();
    expect(container.querySelector('[data-preset="Slow"]')).not.toBeNull();
  });

  it('surfaces a list error', async () => {
    const rpc = makeRpc({ list: vi.fn().mockRejectedValue(new Error('list boom')) });
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    expect(container.querySelector('.save-presets__error')?.textContent).toBe('list boom');
  });

  it('surfaces an apply error (non-Error rejection stringified)', async () => {
    const rpc = makeRpc({ apply: vi.fn().mockRejectedValue('apply-bad') });
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    const applyBtn = container.querySelector(
      '[data-preset="Fast"] .save-presets__apply',
    ) as HTMLButtonElement;
    await act(async () => applyBtn.click());
    await flush();
    expect(container.querySelector('.save-presets__error')?.textContent).toBe('apply-bad');
  });

  it('surfaces a save error', async () => {
    const rpc = makeRpc({ upsert: vi.fn().mockRejectedValue(new Error('save boom')) });
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    const input = container.querySelector('#save-presets-name') as HTMLInputElement;
    typeInto(input, 'X');
    await act(async () =>
      (container.querySelector('.save-presets__save') as HTMLButtonElement).click(),
    );
    await flush();
    expect(container.querySelector('.save-presets__error')?.textContent).toBe('save boom');
  });

  it('surfaces a remove error', async () => {
    const rpc = makeRpc({ remove: vi.fn().mockRejectedValue(new Error('remove boom')) });
    await mount({ rpc, autosave: AUTOSAVE, exportDefaults: EXPORT_DEFAULTS });
    await act(async () =>
      (
        container.querySelector('[data-preset="Fast"] .save-presets__remove') as HTMLButtonElement
      ).click(),
    );
    await flush();
    expect(container.querySelector('.save-presets__error')?.textContent).toBe('remove boom');
  });
});
