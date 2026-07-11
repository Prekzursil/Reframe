// Settings.ce.test.tsx — cross-edit coverage for the WU-11 "Export presets"
// sub-section (SavePresetsSection wrapper) added to Settings.tsx: it self-fetches
// the live autosave/exportDefaults from client.settings, mounts the real
// SavePresetsControls, pushes an applied bundle back via settings.set, and FAILS
// LOUD on a settings read/write reject. Kept in a uniquely-named file so it never
// collides with the sibling agents editing Settings.test.tsx; coverage is by
// source file, so these still count toward Settings.tsx's 100% gate.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Mock every OTHER section body so mounting Settings only exercises the presets
// wrapper + the REAL SavePresetsControls (whose data-section we assert on).
vi.mock('../panels/ModelsSystemPanel', () => ({ default: () => <div data-testid="models" /> }));
vi.mock('../features/SystemHealth', () => ({ SystemHealth: () => <div data-testid="health" /> }));
vi.mock('../features/ProvidersKeys', () => ({
  ProvidersKeys: () => <div data-testid="providers" />,
}));
vi.mock('../components/PathsPanel', () => ({
  PathsPanel: () => <div data-testid="storage" />,
  default: () => <div data-testid="storage" />,
}));
vi.mock('../components/ManagedStoreMeter', () => ({
  ManagedStoreMeter: () => <div data-testid="managed-meter" />,
  default: () => <div data-testid="managed-meter" />,
}));
vi.mock('../components/SetupStatusPanel', () => ({
  SetupStatusPanel: () => <div data-testid="setup" />,
}));
vi.mock('../components/CaptionPreferences', () => ({
  CaptionPreferences: () => <div data-testid="preferences" />,
}));
vi.mock('../features/ThirdPartyNotices', () => ({
  ThirdPartyNotices: () => <div data-testid="licenses" />,
}));

// The mocked RPC client — Settings.tsx value-imports `client`. The real
// SavePresetsControls (unmocked) reads `rpc.list()` on mount.
vi.mock('../lib/rpc', () => ({
  client: {
    paths: {},
    library: {},
    savePresets: { list: vi.fn(), apply: vi.fn(), upsert: vi.fn(), remove: vi.fn() },
    settings: { get: vi.fn(), set: vi.fn() },
  },
}));

import { Settings } from './Settings';
import { client } from '../lib/rpc';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.mocked(client.savePresets.list).mockReset();
  vi.mocked(client.savePresets.apply).mockReset();
  vi.mocked(client.settings.get).mockReset();
  vi.mocked(client.settings.set).mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

async function mountPresets(): Promise<void> {
  await act(async () => {
    root.render(<Settings initialSection="presets" />);
  });
  await flush();
}

describe('Settings › Export presets section (SavePresetsSection)', () => {
  it('mounts the real SavePresetsControls with no error on a successful settings read', async () => {
    vi.mocked(client.settings.get).mockResolvedValue({});
    vi.mocked(client.savePresets.list).mockResolvedValue({ presets: {}, active: '' });

    await mountPresets();

    expect(container.querySelector('[data-section="save-presets"]')).not.toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(client.settings.get).toHaveBeenCalledTimes(1);
  });

  it('fails loud with an alert when the settings read rejects (Error branch)', async () => {
    vi.mocked(client.settings.get).mockRejectedValue(new Error('load boom'));
    vi.mocked(client.savePresets.list).mockResolvedValue({ presets: {}, active: '' });

    await mountPresets();

    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain('load boom');
    // The presets control still renders beneath the loud error.
    expect(container.querySelector('[data-section="save-presets"]')).not.toBeNull();
  });

  it('pushes the applied bundle (merged over live defaults) into settings.set', async () => {
    vi.mocked(client.settings.get).mockResolvedValue({});
    vi.mocked(client.savePresets.list).mockResolvedValue({
      presets: { Fast: { autosave: { enabled: false }, exportDefaults: { nleFps: 24 } } },
      active: '',
    });
    vi.mocked(client.savePresets.apply).mockResolvedValue({
      active: 'Fast',
      savePreset: { autosave: { enabled: false }, exportDefaults: { nleFps: 24 } },
    });
    vi.mocked(client.settings.set).mockResolvedValue({});

    await mountPresets();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[aria-label="Apply Fast"]')!.click();
    });
    await flush();

    expect(client.savePresets.apply).toHaveBeenCalledWith('Fast');
    // The partial preset merges over the live DEFAULT_AUTOSAVE / DEFAULT_EXPORT_DEFAULTS.
    expect(client.settings.set).toHaveBeenCalledWith({
      autosave: { enabled: false, debounceMs: 1500 },
      exportDefaults: { subtitleFormat: 'srt', nleFormat: 'edl', nleFps: 24 },
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('fails loud when settings.set rejects on apply (non-Error branch)', async () => {
    vi.mocked(client.settings.get).mockResolvedValue({});
    vi.mocked(client.savePresets.list).mockResolvedValue({
      presets: { Fast: { autosave: {}, exportDefaults: {} } },
      active: '',
    });
    vi.mocked(client.savePresets.apply).mockResolvedValue({
      active: 'Fast',
      savePreset: { autosave: {}, exportDefaults: {} },
    });
    // Reject with a non-Error value to exercise errText's String(err) else branch.
    vi.mocked(client.settings.set).mockRejectedValue('set nope');

    await mountPresets();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[aria-label="Apply Fast"]')!.click();
    });
    await flush();

    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain('set nope');
  });
});
