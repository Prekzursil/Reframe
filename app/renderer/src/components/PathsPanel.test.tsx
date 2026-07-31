// PathsPanel.test.tsx — show the on-disk data layout + change-root flow + per-row
// "Open folder" (UX/QoL WU-12).
//
// Fake `paths.describe` payload + a fake bridge (no preload). Pins the falsifiable
// acceptance:
//   * each OPENABLE row exposes a real <button> named "Open <label> folder" (no
//     icon-only control) and renders its path as selectable TEXT (queryable, not
//     a button); a `subDirs` value that is a PATTERN gets text but no button;
//   * "Change data folder" calls bridge.pickDataFolder THEN bridge.setDataFolder
//     in order, then shows the chosen path + a restart hint;
//   * loading / unavailable-bridge / error branches all render.
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PathsPanel, type PathsRpc, type PathsBridge, type PathsDescribe } from './PathsPanel';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function layout(): PathsDescribe {
  return {
    dataDir: 'C:/data',
    projectsDir: 'C:/data/projects',
    exportsDir: 'C:/data/exports',
    settingsPath: 'C:/data/settings.json',
    // Mirrors the WIRE, not the old label: `paths.describe` reports the SQLite
    // store (`library.db`), never the legacy `library.json` index.
    libraryPath: 'C:/data/library.db',
    subDirs: {
      dubs: 'C:/data/dubs',
      shorts: 'C:/data/exports/shorts-*',
      stabilized: 'C:/data/exports/stabilized',
      audiomix: 'C:/data/exports/audiomix',
      trimmed: 'C:/data/exports/trimmed',
      'managed-copies': 'C:/data/managed-copies',
    },
  };
}

function makeRpc(overrides: Partial<PathsRpc> = {}): PathsRpc {
  return {
    describe: vi.fn().mockResolvedValue(layout()),
    ...overrides,
  };
}

function makeBridge(overrides: Partial<PathsBridge> = {}): PathsBridge {
  return {
    getDataFolder: vi.fn().mockResolvedValue('C:/data'),
    pickDataFolder: vi.fn().mockResolvedValue('D:/new-root'),
    setDataFolder: vi.fn().mockResolvedValue({ ok: true }),
    openInFolder: vi.fn().mockResolvedValue(true),
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

async function mount(props: Parameters<typeof PathsPanel>[0]): Promise<void> {
  await act(async () => {
    root.render(<PathsPanel {...props} />);
  });
  await flush();
}

function flush(): Promise<void> {
  return act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function openButtons(): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('.paths-panel__open'));
}

describe('<PathsPanel />', () => {
  it('renders a row per dir with a path-as-text and an "Open <label> folder" button', async () => {
    const rpc = makeRpc();
    await mount({ rpc, bridge: makeBridge() });
    expect(rpc.describe).toHaveBeenCalledTimes(1);
    // One row per layout entry (5 top-level + 6 subDirs = 11).
    const rows = container.querySelectorAll('.paths-panel__row');
    expect(rows.length).toBe(11);
    // The path string is rendered as TEXT, not a button.
    const dataRow = container.querySelector('[data-path-key="dataDir"]') as HTMLElement;
    const pathEl = dataRow.querySelector('.paths-panel__path') as HTMLElement;
    expect(pathEl.tagName).not.toBe('BUTTON');
    expect(pathEl.textContent).toBe('C:/data');
    // Each OPENABLE row's control is a real <button> with a row-specific
    // accessible name (8 = 3 top-level dirs + 5 concrete subDirs; the 2 file rows
    // and the `shorts-*` PATTERN row have none).
    const buttons = openButtons();
    expect(buttons.length).toBe(8);
    for (const btn of buttons) {
      expect(btn.tagName).toBe('BUTTON');
      expect(btn.getAttribute('aria-label')).toMatch(/^Open .+ folder$/);
    }
  });

  it("opens a dir via bridge.openInFolder with that row's path", async () => {
    const bridge = makeBridge();
    await mount({ rpc: makeRpc(), bridge });
    const row = container.querySelector('[data-path-key="exportsDir"]') as HTMLElement;
    const btn = row.querySelector('.paths-panel__open') as HTMLButtonElement;
    await act(async () => btn.click());
    await flush();
    expect(bridge.openInFolder).toHaveBeenCalledWith('C:/data/exports');
  });

  it('surfaces an open-folder failure', async () => {
    const bridge = makeBridge({ openInFolder: vi.fn().mockRejectedValue(new Error('open boom')) });
    await mount({ rpc: makeRpc(), bridge });
    const row = container.querySelector('[data-path-key="dataDir"]') as HTMLElement;
    await act(async () => (row.querySelector('.paths-panel__open') as HTMLButtonElement).click());
    await flush();
    expect(container.querySelector('.paths-panel__error')?.textContent).toBe('open boom');
  });

  it('shows the file-path rows as text but does NOT render an Open button for files', async () => {
    await mount({ rpc: makeRpc(), bridge: makeBridge() });
    const settingsRow = container.querySelector('[data-path-key="settingsPath"]') as HTMLElement;
    expect((settingsRow.querySelector('.paths-panel__path') as HTMLElement).textContent).toBe(
      'C:/data/settings.json',
    );
    // Files have no own-folder Open button (they are not directories).
    expect(settingsRow.querySelector('.paths-panel__open')).toBeNull();
  });

  it('renders no Open button for a glob-pattern subDir (shorts-* names no directory)', async () => {
    // `paths.describe` deliberately reports shorts as the PATTERN
    // `exports/shorts-*` because output is per-video `exports/shorts-<videoId>`.
    // MEASURED on this machine (Electron 43.2.0, Windows 11), two independent
    // detectors (Shell.Application LocationURL + Win32 EnumWindows/CabinetWClass),
    // both orders: `shell.showItemInFolder('…\\exports\\shorts-abc123')` opens
    // `…\\exports` (detector FIRED) while `shell.showItemInFolder('…\\exports\\shorts-*')`
    // opens NOTHING (detector SILENT). So the control is a silent no-op, not a
    // reveal-the-parent affordance — remove it rather than retarget it.
    await mount({ rpc: makeRpc(), bridge: makeBridge() });
    const shortsRow = container.querySelector('[data-path-key="subDir:shorts"]') as HTMLElement;
    expect(shortsRow).not.toBeNull();
    // The pattern is still SHOWN — the panel is a layout view, not an opener.
    expect((shortsRow.querySelector('.paths-panel__path') as HTMLElement).textContent).toBe(
      'C:/data/exports/shorts-*',
    );
    expect(shortsRow.querySelector('.paths-panel__open')).toBeNull();
  });

  it('names the managed-copies store as its own row, with an Open control', async () => {
    // `paths.describe` now reports `managed-copies` (the opt-in byte-copy store
    // beside the library DB), which ManagedStoreMeter renders in this same
    // sub-tab while naming its path nowhere. The subDirs KEY is the visible
    // label verbatim, so the hyphenated form is deliberate.
    // ACCEPTED trade-off: keepcopy creates that folder LAZILY on the first
    // kept copy, so on a fresh install this button reveals a not-yet-existing
    // path — the same shape the concrete dubs/stabilized/audiomix/trimmed rows
    // already have. It is a real directory (no wildcard), so it is openable in
    // principle; suppressing it would need an existence probe the layout
    // handler is contractually forbidden to do (it is a pure path-join).
    await mount({ rpc: makeRpc(), bridge: makeBridge() });
    const row = container.querySelector('[data-path-key="subDir:managed-copies"]') as HTMLElement;
    expect(row).not.toBeNull();
    expect((row.querySelector('.paths-panel__row-label') as HTMLElement).textContent).toBe(
      'managed-copies',
    );
    expect((row.querySelector('.paths-panel__path') as HTMLElement).textContent).toBe(
      'C:/data/managed-copies',
    );
    expect(row.querySelector('.paths-panel__open')).not.toBeNull();
  });

  it('hydrates and shows the current data folder from the bridge', async () => {
    const bridge = makeBridge();
    await mount({ rpc: makeRpc(), bridge });
    expect(bridge.getDataFolder).toHaveBeenCalledTimes(1);
    expect((container.querySelector('.paths-panel__root-value') as HTMLElement).textContent).toBe(
      'C:/data',
    );
  });

  it('falls back to "Unknown" when getDataFolder resolves an empty string', async () => {
    const bridge = makeBridge({ getDataFolder: vi.fn().mockResolvedValue('') });
    await mount({ rpc: makeRpc(), bridge });
    expect((container.querySelector('.paths-panel__root-value') as HTMLElement).textContent).toBe(
      'Unknown',
    );
  });

  it('changes the data folder: pickDataFolder THEN setDataFolder, then shows the choice + restart hint', async () => {
    const order: string[] = [];
    const bridge = makeBridge({
      pickDataFolder: vi.fn(async () => {
        order.push('pick');
        return 'D:/new-root';
      }),
      setDataFolder: vi.fn(async () => {
        order.push('set');
        return { ok: true };
      }),
    });
    await mount({ rpc: makeRpc(), bridge });
    const change = container.querySelector('.paths-panel__change-root') as HTMLButtonElement;
    await act(async () => change.click());
    await flush();
    expect(order).toEqual(['pick', 'set']);
    expect(bridge.setDataFolder).toHaveBeenCalledWith('D:/new-root');
    expect((container.querySelector('.paths-panel__root-value') as HTMLElement).textContent).toBe(
      'D:/new-root',
    );
    expect(container.querySelector('.paths-panel__restart-hint')).not.toBeNull();
  });

  it('no-ops the change when the picker is cancelled (null) — no setDataFolder, no restart hint', async () => {
    const bridge = makeBridge({ pickDataFolder: vi.fn().mockResolvedValue(null) });
    await mount({ rpc: makeRpc(), bridge });
    await act(async () =>
      (container.querySelector('.paths-panel__change-root') as HTMLButtonElement).click(),
    );
    await flush();
    expect(bridge.setDataFolder).not.toHaveBeenCalled();
    expect(container.querySelector('.paths-panel__restart-hint')).toBeNull();
  });

  it('surfaces a save failure (setDataFolder ok:false) without flagging a restart', async () => {
    const bridge = makeBridge({ setDataFolder: vi.fn().mockResolvedValue({ ok: false }) });
    await mount({ rpc: makeRpc(), bridge });
    await act(async () =>
      (container.querySelector('.paths-panel__change-root') as HTMLButtonElement).click(),
    );
    await flush();
    expect(container.querySelector('.paths-panel__error')?.textContent).toMatch(/read-only/i);
    expect(container.querySelector('.paths-panel__restart-hint')).toBeNull();
  });

  it('surfaces a change-root exception', async () => {
    const bridge = makeBridge({
      pickDataFolder: vi.fn().mockRejectedValue(new Error('pick boom')),
    });
    await mount({ rpc: makeRpc(), bridge });
    await act(async () =>
      (container.querySelector('.paths-panel__change-root') as HTMLButtonElement).click(),
    );
    await flush();
    expect(container.querySelector('.paths-panel__error')?.textContent).toBe('pick boom');
  });

  it('renders the loading state before the layout resolves', async () => {
    let resolve: (v: PathsDescribe) => void = () => undefined;
    const rpc = makeRpc({
      describe: vi.fn(
        () =>
          new Promise<PathsDescribe>((r) => {
            resolve = r;
          }),
      ),
    });
    await act(async () => {
      root.render(<PathsPanel rpc={rpc} bridge={makeBridge()} />);
    });
    expect(container.querySelector('.paths-panel__loading')).not.toBeNull();
    expect(container.querySelector('.paths-panel__row')).toBeNull();
    await act(async () => {
      resolve(layout());
    });
    await flush();
    expect(container.querySelector('.paths-panel__loading')).toBeNull();
    expect(container.querySelectorAll('.paths-panel__row').length).toBe(11);
  });

  it('surfaces a describe error and stops loading', async () => {
    const rpc = makeRpc({ describe: vi.fn().mockRejectedValue(new Error('describe boom')) });
    await mount({ rpc, bridge: makeBridge() });
    expect(container.querySelector('.paths-panel__error')?.textContent).toBe('describe boom');
    expect(container.querySelector('.paths-panel__loading')).toBeNull();
  });

  it('stringifies a non-Error describe rejection', async () => {
    const rpc = makeRpc({ describe: vi.fn().mockRejectedValue('describe-bad') });
    await mount({ rpc, bridge: makeBridge() });
    expect(container.querySelector('.paths-panel__error')?.textContent).toBe('describe-bad');
  });

  it('shows the change-root control as unavailable when the bridge lacks the picker', async () => {
    // Bridge with no pick/set/get — the data-root section degrades, never crashes.
    const bridge: PathsBridge = { openInFolder: vi.fn().mockResolvedValue(true) };
    await mount({ rpc: makeRpc(), bridge });
    expect(container.querySelector('.paths-panel__change-root')).toBeNull();
    expect(container.querySelector('.paths-panel__root-unavailable')).not.toBeNull();
    // The layout rows still render (the describe RPC is independent of the bridge).
    expect(container.querySelectorAll('.paths-panel__row').length).toBe(11);
  });

  it('keeps the Open button inert when the bridge lacks openInFolder', async () => {
    const bridge: PathsBridge = {
      getDataFolder: vi.fn().mockResolvedValue('C:/data'),
      pickDataFolder: vi.fn(),
      setDataFolder: vi.fn(),
    };
    await mount({ rpc: makeRpc(), bridge });
    // No Open buttons are rendered without an openInFolder bridge (no dead control).
    expect(openButtons().length).toBe(0);
  });

  it('tolerates a describe payload missing subDirs (defensive default)', async () => {
    const partial = { ...layout(), subDirs: undefined } as unknown as PathsDescribe;
    const rpc = makeRpc({ describe: vi.fn().mockResolvedValue(partial) });
    await mount({ rpc, bridge: makeBridge() });
    // Only the 5 top-level rows render; no crash on the absent subDirs map.
    expect(container.querySelectorAll('.paths-panel__row').length).toBe(5);
  });

  it('tolerates a getDataFolder failure (root stays unknown, panel still renders)', async () => {
    const bridge = makeBridge({ getDataFolder: vi.fn().mockRejectedValue(new Error('no root')) });
    await mount({ rpc: makeRpc(), bridge });
    // The root value falls back to the unknown placeholder; rows still render.
    expect((container.querySelector('.paths-panel__root-value') as HTMLElement).textContent).toBe(
      'Unknown',
    );
    expect(container.querySelectorAll('.paths-panel__row').length).toBe(11);
  });
});
