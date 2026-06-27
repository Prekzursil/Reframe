// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { CaptionPreferences, type SettingsBridge } from './CaptionPreferences';
import { PREFERENCE_KEYS } from '../lib/captionPreferences';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (v: T) => void;
  reject: (e: unknown) => void;
}
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const flush = async (): Promise<void> => {
  await act(async () => {
    await Promise.resolve();
  });
};

describe('<CaptionPreferences />', () => {
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

  function mountWith(rpc: SettingsBridge): void {
    act(() => root.render(<CaptionPreferences rpc={rpc} />));
  }

  const swatch = (id: string): HTMLButtonElement =>
    container.querySelector(`[data-style="${id}"]`) as HTMLButtonElement;
  const subSelect = (): HTMLSelectElement =>
    container.querySelector('select[aria-label="Default subtitle delivery"]') as HTMLSelectElement;
  const saveBtn = (): HTMLButtonElement =>
    [...container.querySelectorAll('button')].find((b) =>
      (b.textContent ?? '').startsWith('Sav'),
    ) as HTMLButtonElement;

  it('loads + reflects persisted preferences', async () => {
    const rpc: SettingsBridge = {
      get: vi.fn().mockResolvedValue({
        [PREFERENCE_KEYS.style]: 'hormozi',
        [PREFERENCE_KEYS.subtitleMode]: 'sidecar',
        [PREFERENCE_KEYS.language]: 'pt',
      }),
      set: vi.fn(),
    };
    mountWith(rpc);
    await flush();
    expect(swatch('hormozi').getAttribute('aria-pressed')).toBe('true');
    expect(subSelect().value).toBe('sidecar');
  });

  it('shows an error when loading fails', async () => {
    const rpc: SettingsBridge = {
      get: vi.fn().mockRejectedValue(new Error('boom')),
      set: vi.fn(),
    };
    mountWith(rpc);
    await flush();
    expect(container.querySelector('.caption-prefs__error')?.textContent).toContain('boom');
  });

  it('saves the current preferences (and shows the in-flight state)', async () => {
    const d = deferred<Record<string, unknown>>();
    const set = vi.fn().mockReturnValue(d.promise);
    const rpc: SettingsBridge = { get: vi.fn().mockResolvedValue({}), set };
    mountWith(rpc);
    await flush();
    // Change the style first so the save carries it.
    act(() => swatch('neon').click());
    act(() => saveBtn().click());
    // While the set promise is pending the button is busy.
    expect(saveBtn().textContent).toBe('Saving…');
    expect(saveBtn().disabled).toBe(true);
    await act(async () => {
      d.resolve({});
      await Promise.resolve();
    });
    expect(set).toHaveBeenCalledWith(expect.objectContaining({ [PREFERENCE_KEYS.style]: 'neon' }));
    expect(container.querySelector('.caption-prefs__status')?.textContent).toBe(
      'Preferences saved.',
    );
  });

  it('shows an error when saving fails (non-Error rejection)', async () => {
    const rpc: SettingsBridge = {
      get: vi.fn().mockResolvedValue({}),
      // A plain-string rejection exercises the non-Error errText path.
      set: vi.fn().mockRejectedValue('nope-string'),
    };
    mountWith(rpc);
    await flush();
    await act(async () => {
      saveBtn().click();
      await Promise.resolve();
    });
    expect(container.querySelector('.caption-prefs__error')?.textContent).toContain('nope-string');
  });

  it('changes subtitle mode + language', async () => {
    const rpc: SettingsBridge = { get: vi.fn().mockResolvedValue({}), set: vi.fn() };
    mountWith(rpc);
    await flush();
    act(() => {
      subSelect().value = 'softmux';
      subSelect().dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(subSelect().value).toBe('softmux');
    const lang = container.querySelector(
      'select[aria-label="Default language"]',
    ) as HTMLSelectElement;
    act(() => {
      lang.value = 'fr';
      lang.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(lang.value).toBe('fr');
  });

  it('shows a "No captions" sample for the none style', async () => {
    const rpc: SettingsBridge = {
      get: vi.fn().mockResolvedValue({ [PREFERENCE_KEYS.style]: 'none' }),
      set: vi.fn(),
    };
    mountWith(rpc);
    await flush();
    expect(container.querySelector('.caption-prefs__sample')?.textContent).toBe('No captions');
  });

  it('moves the default position box by dragging it', async () => {
    const set = vi.fn().mockResolvedValue({});
    const rpc: SettingsBridge = { get: vi.fn().mockResolvedValue({}), set };
    mountWith(rpc);
    await flush();
    const frame = container.querySelector('.caption-box-frame') as HTMLElement;
    frame.getBoundingClientRect = () =>
      ({
        width: 100,
        height: 100,
        top: 0,
        left: 0,
        right: 100,
        bottom: 100,
        x: 0,
        y: 0,
      }) as DOMRect;
    const boxEl = container.querySelector('[data-testid="caption-box"]') as HTMLElement;
    const fire = (type: string, x: number, y: number): void => {
      const ev = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y });
      Object.defineProperty(ev, 'pointerId', { value: 1 });
      act(() => boxEl.dispatchEvent(ev));
    };
    fire('pointerdown', 0, 0);
    fire('pointermove', 0, 10); // move down 0.1
    await act(async () => {
      saveBtn().click();
      await Promise.resolve();
    });
    const savedBox = set.mock.calls[0][0][PREFERENCE_KEYS.box] as { y: number };
    expect(savedBox.y).toBeGreaterThan(0.76);
  });

  it('ignores a late load resolve after unmount', async () => {
    const d = deferred<Record<string, unknown>>();
    const rpc: SettingsBridge = { get: () => d.promise, set: vi.fn() };
    mountWith(rpc);
    act(() => root.unmount());
    await act(async () => {
      d.resolve({ [PREFERENCE_KEYS.style]: 'neon' });
      await Promise.resolve();
    });
    // No throw / no swatch (unmounted) — the alive guard skipped setState.
    expect(container.querySelector('[data-style="neon"]')).toBeNull();
  });

  it('ignores a late load error after unmount', async () => {
    const d = deferred<Record<string, unknown>>();
    const rpc: SettingsBridge = { get: () => d.promise, set: vi.fn() };
    mountWith(rpc);
    act(() => root.unmount());
    await act(async () => {
      d.reject(new Error('late'));
      await Promise.resolve();
    });
    expect(container.querySelector('.caption-prefs__error')).toBeNull();
  });

  it('defaults to the live client settings rpc when none injected', async () => {
    // Render WITHOUT an rpc prop -> uses client.settings, which reads window.api.
    const win = globalThis as unknown as { window?: { api?: unknown } };
    const prev = win.window?.api;
    win.window = win.window ?? {};
    (win.window as { api?: unknown }).api = {
      rpc: vi.fn().mockResolvedValue({ [PREFERENCE_KEYS.style]: 'bold' }),
    };
    act(() => root.render(<CaptionPreferences />));
    await flush();
    expect(swatch('bold').getAttribute('aria-pressed')).toBe('true');
    (win.window as { api?: unknown }).api = prev;
  });
});
