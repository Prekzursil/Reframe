// NleExport.test.tsx — tests for the NLE timeline-export panel (captions-export).
//
// Mocks the typed client (lib/rpc) so `nle.export` is deterministic; renders with
// React 18 createRoot + act under jsdom and drives the format/fps selects + the
// export button. Mirrors the Shorts/Library test strategy.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// The panel now resolves promises inside effects, so the multi-generation
// `settle()` below needs a real act environment (house pattern — see
// panels/ModelsSystemPanel.test.tsx, panels/DirectorPanel.test.tsx).
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const exportMock = vi.fn();
const settingsGetMock = vi.fn();
const settingsSetMock = vi.fn();
let apiAvailable = true;

vi.mock('../lib/rpc', () => ({
  client: {
    nle: { export: (...a: unknown[]) => exportMock(...a) },
    settings: {
      get: (...a: unknown[]) => settingsGetMock(...a),
      set: (...a: unknown[]) => settingsSetMock(...a),
    },
  },
  hasApi: () => apiAvailable,
}));

import { NleExport } from './NleExport';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  exportMock.mockReset();
  settingsGetMock.mockReset();
  settingsSetMock.mockReset();
  // Default: a persisted store with no `exportDefaults` slice at all, so the
  // panel keeps its built-in edl/30 and the pre-existing tests are unaffected.
  settingsGetMock.mockResolvedValue({});
  settingsSetMock.mockResolvedValue({});
  apiAvailable = true;
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

/**
 * Drain a multi-await chain (mount seed -> export -> re-read -> persist). One
 * `flush()` only advances a single microtask generation.
 */
async function settle(): Promise<void> {
  await flush();
  await flush();
  await flush();
}

function selects(): { fmt: HTMLSelectElement; fps: HTMLSelectElement } {
  return {
    fmt: container.querySelector('#nle-format') as HTMLSelectElement,
    fps: container.querySelector('#nle-fps') as HTMLSelectElement,
  };
}

function pick(format: string, fps: string): void {
  const { fmt, fps: fpsEl } = selects();
  act(() => {
    fmt.value = format;
    fmt.dispatchEvent(new Event('change', { bubbles: true }));
    fpsEl.value = fps;
    fpsEl.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

function render(): void {
  act(() => {
    root.render(<NleExport videoId="v1" />);
  });
}

function click(label: string): void {
  const btn = Array.from(container.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(label),
  );
  if (!btn) throw new Error(`button not found: ${label}`);
  act(() => btn.dispatchEvent(new MouseEvent('click', { bubbles: true })));
}

describe('NleExport', () => {
  it('renders the format + fps selects and the export button', () => {
    render();
    expect(container.querySelector('#nle-format')).toBeTruthy();
    expect(container.querySelector('#nle-fps')).toBeTruthy();
    expect(container.textContent).toContain('Export timeline');
  });

  it('offers all four frame rates', () => {
    render();
    const fps = container.querySelector('#nle-fps') as HTMLSelectElement;
    const values = Array.from(fps.options).map((o) => o.value);
    expect(values).toEqual(['24', '25', '30', '60']);
  });

  it('exports with the selected format + fps and shows the saved path', async () => {
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 3 });
    render();
    // Change format -> csv, fps -> 25.
    const fmt = container.querySelector('#nle-format') as HTMLSelectElement;
    const fps = container.querySelector('#nle-fps') as HTMLSelectElement;
    act(() => {
      fmt.value = 'csv';
      fmt.dispatchEvent(new Event('change', { bubbles: true }));
      fps.value = '25';
      fps.dispatchEvent(new Event('change', { bubbles: true }));
    });
    click('Export timeline');
    await flush();
    expect(exportMock).toHaveBeenCalledWith('v1', { format: 'csv', fps: 25 });
    expect(container.textContent).toContain('Exported 3 clips');
    expect(container.textContent).toContain('/exports/v1-timeline.edl');
  });

  it('reports an empty-timeline export distinctly', async () => {
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 0 });
    render();
    click('Export timeline');
    await flush();
    expect(container.textContent).toContain('no approved clips');
  });

  it('surfaces an export error', async () => {
    exportMock.mockRejectedValue(new Error('disk full'));
    render();
    click('Export timeline');
    await flush();
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('disk full');
  });

  it('surfaces a non-Error rejection via String(err)', async () => {
    exportMock.mockRejectedValue('plain export error');
    render();
    click('Export timeline');
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain export error');
  });

  it('uses the singular "clip" wording for a single exported clip', async () => {
    exportMock.mockResolvedValue({ path: '/exports/v1.edl', clipCount: 1 });
    render();
    click('Export timeline');
    await flush();
    expect(container.querySelector('.status')?.textContent).toContain('Exported 1 clip');
    expect(container.querySelector('.status')?.textContent).not.toContain('clips');
    // The saved-path line also uses the singular form.
    expect(container.querySelector('.export-path')?.textContent).toContain('Saved 1 clip to');
  });

  // Q6 caveat, stated inline: this is a `!hasApi()` branch a working PACKAGED
  // install never reaches (the preload always installs `window.api`), so it is
  // the lowest-value of the five copy sites — fixed for consistency, not because
  // a shipped user was seeing it. UNVERIFIED that any user has ever hit it;
  // settling experiment: instrument this branch in a packaged build and see
  // whether it ever fires.
  it('names "the engine", not "sidecar", when there is no api', async () => {
    apiAvailable = false;
    render();
    click('Export timeline');
    await flush();
    const alert = container.querySelector('[role="alert"]')?.textContent ?? '';
    expect(alert).toContain('The engine is not available.');
    expect(alert).not.toMatch(/sidecar/i);
    expect(exportMock).not.toHaveBeenCalled();
  });

  // ---- F28: the persisted `exportDefaults` slice is read at mount + written ----

  it('seeds the format + fps selects from the persisted exportDefaults', async () => {
    settingsGetMock.mockResolvedValue({
      exportDefaults: { subtitleFormat: 'srt', nleFormat: 'csv', nleFps: 24 },
    });
    render();
    await settle();
    const { fmt, fps } = selects();
    expect(fmt.value).toBe('csv');
    expect(fps.value).toBe('24');
  });

  it('persists the picked format + fps after a successful export, re-reading first', async () => {
    // Mount reads `subtitleFormat: 'vtt'`; ANOTHER surface then writes 'ass'
    // before the export lands. The persisted payload must carry 'ass' — a
    // mount-time snapshot would clobber it, because the sidecar `settings.set`
    // is a SHALLOW top-level merge (settings_store.py:508-528).
    settingsGetMock
      .mockResolvedValueOnce({
        exportDefaults: { subtitleFormat: 'vtt', nleFormat: 'edl', nleFps: 30 },
      })
      .mockResolvedValueOnce({
        exportDefaults: { subtitleFormat: 'ass', nleFormat: 'edl', nleFps: 30 },
      });
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.csv', clipCount: 2 });
    render();
    await settle();
    pick('csv', '25');
    click('Export timeline');
    await settle();
    expect(settingsSetMock).toHaveBeenCalledWith({
      exportDefaults: { subtitleFormat: 'ass', nleFormat: 'csv', nleFps: 25 },
    });
  });

  it('falls back to edl/30 for a persisted format + fps the panel does not offer', async () => {
    // `nleFormat` is a bare `string` on the wire and the sidecar documents
    // `fcpxml` as legal; an unmatched <select> value would render BLANK.
    settingsGetMock.mockResolvedValue({
      exportDefaults: { subtitleFormat: 'srt', nleFormat: 'fcpxml', nleFps: 99 },
    });
    render();
    await settle();
    const { fmt, fps } = selects();
    expect(fmt.value).toBe('edl');
    expect(fps.value).toBe('30');
  });

  it('treats a non-object exportDefaults as absent, on both the read and the write', async () => {
    // A corrupt scalar must not be spread into the persisted payload — spreading
    // a string would write index keys ({0:'c',1:'o',…}) into the slice.
    settingsGetMock.mockResolvedValue({ exportDefaults: 'corrupt' });
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 1 });
    render();
    await settle();
    const { fmt, fps } = selects();
    expect(fmt.value).toBe('edl');
    expect(fps.value).toBe('30');
    click('Export timeline');
    await settle();
    expect(settingsSetMock).toHaveBeenCalledWith({
      exportDefaults: { nleFormat: 'edl', nleFps: 30 },
    });
  });

  it('keeps the built-in defaults when the settings read rejects', async () => {
    settingsGetMock.mockRejectedValue(new Error('settings unreadable'));
    render();
    await settle();
    const { fmt, fps } = selects();
    expect(fmt.value).toBe('edl');
    expect(fps.value).toBe('30');
    // A failed preference read is not an error the user is shown.
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('never touches client.settings when there is no bridge', async () => {
    // `client.settings.get` throws SYNCHRONOUSLY without a preload, so the mount
    // effect must return on `hasApi()` BEFORE reaching the client.
    apiAvailable = false;
    render();
    await settle();
    expect(settingsGetMock).not.toHaveBeenCalled();
    expect(container.querySelector('#nle-format')).toBeTruthy();
  });

  it('does not let a late settings resolve clobber a pick the user already made', async () => {
    let resolveGet: (value: Record<string, unknown>) => void = () => undefined;
    settingsGetMock.mockReturnValue(
      new Promise<Record<string, unknown>>((res) => {
        resolveGet = res;
      }),
    );
    render();
    pick('csv', '30');
    await act(async () => {
      resolveGet({ exportDefaults: { subtitleFormat: 'srt', nleFormat: 'edl', nleFps: 60 } });
    });
    await settle();
    const { fmt, fps } = selects();
    expect(fmt.value).toBe('csv');
    expect(fps.value).toBe('30');
  });

  it('ignores a settings resolve that lands after unmount', async () => {
    let resolveGet: (value: Record<string, unknown>) => void = () => undefined;
    settingsGetMock.mockReturnValue(
      new Promise<Record<string, unknown>>((res) => {
        resolveGet = res;
      }),
    );
    render();
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    act(() => root.unmount());
    await act(async () => {
      resolveGet({ exportDefaults: { subtitleFormat: 'srt', nleFormat: 'csv', nleFps: 24 } });
    });
    // The cleanup flag suppressed the seed: no update on an unmounted tree.
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
    // Hand afterEach a fresh, never-rendered root (this one is already unmounted).
    root = createRoot(container);
  });

  it('does not surface a failed preference write as an export error', async () => {
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 4 });
    settingsSetMock.mockRejectedValue(new Error('settings read-only'));
    render();
    await settle();
    click('Export timeline');
    await settle();
    expect(settingsSetMock).toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('.status')?.textContent).toContain('Exported 4 clips');
  });

  // ---- F29: the success outcome + saved path are announced -------------------

  it('announces the export outcome and the saved path in a polite live region', async () => {
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 3 });
    render();
    await settle();
    // Mounted-while-empty (components/ToastHost.tsx): a region inserted together
    // with its text is not reliably announced, so it must exist BEFORE the action.
    const live = container.querySelector('[role="status"][aria-live="polite"]');
    expect(live).toBeTruthy();
    click('Export timeline');
    await settle();
    expect(live?.textContent).toContain('Exported 3 clips');
    expect(live?.textContent).toContain('/exports/v1-timeline.edl');
  });

  it('announces the empty-timeline outcome inside the live region', async () => {
    // clipCount>0 needs persisted approved clips, so this is the string real
    // users hear today — it must land in the region too, not just beside it.
    exportMock.mockResolvedValue({ path: '/exports/v1-timeline.edl', clipCount: 0 });
    render();
    await settle();
    const live = container.querySelector('[role="status"][aria-live="polite"]');
    click('Export timeline');
    await settle();
    expect(live?.textContent).toContain('no approved clips');
    expect(live?.textContent).toContain('/exports/v1-timeline.edl');
  });

  it('keeps the failure alert OUT of the polite region', async () => {
    exportMock.mockRejectedValue(new Error('disk full'));
    render();
    await settle();
    click('Export timeline');
    await settle();
    const live = container.querySelector('[role="status"][aria-live="polite"]');
    expect(live).toBeTruthy();
    expect(live?.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('disk full');
  });

  it('drops the previous saved path when a later export fails', async () => {
    exportMock.mockResolvedValueOnce({ path: '/exports/v1-timeline.edl', clipCount: 2 });
    render();
    await settle();
    click('Export timeline');
    await settle();
    expect(container.querySelector('.export-path')).toBeTruthy();
    // A stale success path must not sit in the live region beside the alert.
    exportMock.mockRejectedValueOnce(new Error('disk full'));
    click('Export timeline');
    await settle();
    expect(container.querySelector('.export-path')).toBeNull();
  });
});
