// Settings.test.tsx — the Settings sub-navigated view: it mounts the three
// sub-sections (Models & System / Providers & Keys / System Health), switches
// between them via the sub-tab strip, honours `initialSection`, and routes the
// Providers empty-state action to the Models section. The heavy child panels are
// stubbed (they own their own tests).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Stub the three section bodies so the test exercises ONLY Settings' sub-nav.
vi.mock('../panels/ModelsSystemPanel', () => ({
  default: ({ onOpenProviders }: { onOpenProviders?: () => void }) => (
    <div data-testid="models">
      <button type="button" data-testid="open-providers" onClick={() => onOpenProviders?.()}>
        add a key
      </button>
    </div>
  ),
}));
vi.mock('../features/SystemHealth', () => ({
  SystemHealth: () => <div data-testid="health" />,
}));
vi.mock('../features/ProvidersKeys', () => ({
  ProvidersKeys: ({ onOpenModels }: { onOpenModels?: () => void }) => (
    <div data-testid="providers">
      <button type="button" data-testid="open-models" onClick={() => onOpenModels?.()}>
        review
      </button>
    </div>
  ),
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

import { Settings, SETTINGS_SECTIONS } from './Settings';

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

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function mount(initialSection?: string): Promise<void> {
  await act(async () => {
    root.render(<Settings initialSection={initialSection} />);
  });
  await flush();
}

function subtab(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.tab'));
  const found = btns.find((b) => b.textContent === label);
  if (!found) throw new Error(`sub-tab "${label}" not found`);
  return found;
}

describe('Settings sub-nav', () => {
  it('exposes the sub-sections as the extension array', () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual([
      'models',
      'setup',
      'providers',
      'storage',
      'preferences',
      'health',
      'licenses',
      'presets',
    ]);
    expect(SETTINGS_SECTIONS.map((s) => s.label)).toEqual([
      'Models & System',
      'Setup',
      'Providers & Keys',
      'Storage',
      'Caption defaults',
      'System Health',
      'Licenses',
      'Export presets',
    ]);
  });

  it('opens the Caption defaults (Preferences) section via the sub-tab', async () => {
    await mount();
    await act(async () => {
      subtab('Caption defaults').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="preferences"]')).not.toBeNull();
    expect(subtab('Caption defaults').classList.contains('tab--active')).toBe(true);
  });

  it('opens the Setup section (self-diagnostic) via the sub-tab', async () => {
    await mount();
    await act(async () => {
      subtab('Setup').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="setup"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="models"]')).toBeNull();
    expect(subtab('Setup').classList.contains('tab--active')).toBe(true);
  });

  it('opens the Storage section (PathsPanel) via the sub-tab', async () => {
    await mount();
    await act(async () => {
      subtab('Storage').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="storage"]')).not.toBeNull();
    // WU-3b2: the Storage section now also renders the managed-copy store meter.
    expect(container.querySelector('[data-testid="managed-meter"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="models"]')).toBeNull();
    expect(subtab('Storage').classList.contains('tab--active')).toBe(true);
  });

  it('opens the Licenses section (third-party notices) via the sub-tab', async () => {
    await mount();
    await act(async () => {
      subtab('Licenses').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="licenses"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="models"]')).toBeNull();
    expect(subtab('Licenses').classList.contains('tab--active')).toBe(true);
  });

  it('defaults to the first section (Models & System) and marks its sub-tab active', async () => {
    await mount();
    expect(container.querySelector('[data-testid="models"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="providers"]')).toBeNull();
    expect(subtab('Models & System').classList.contains('tab--active')).toBe(true);
    expect(subtab('Models & System').getAttribute('aria-selected')).toBe('true');
  });

  it('switches to Providers & Keys via the sub-tab', async () => {
    await mount();
    await act(async () => {
      subtab('Providers & Keys').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="providers"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="models"]')).toBeNull();
    expect(subtab('Providers & Keys').classList.contains('tab--active')).toBe(true);
  });

  it('switches to System Health via the sub-tab', async () => {
    await mount();
    await act(async () => {
      subtab('System Health').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="health"]')).not.toBeNull();
    expect(subtab('System Health').classList.contains('tab--active')).toBe(true);
  });

  it('honours initialSection by opening that section on mount', async () => {
    await mount('health');
    expect(container.querySelector('[data-testid="health"]')).not.toBeNull();
    expect(subtab('System Health').classList.contains('tab--active')).toBe(true);
  });

  it('falls back to the first section when initialSection is unknown', async () => {
    await mount('does-not-exist');
    expect(container.querySelector('[data-testid="models"]')).not.toBeNull();
    expect(subtab('Models & System').classList.contains('tab--active')).toBe(true);
  });

  it('falls back to the first section when initialSection is omitted', async () => {
    await mount(undefined);
    expect(container.querySelector('[data-testid="models"]')).not.toBeNull();
  });

  it('routes the Providers secondary action to the Models section', async () => {
    await mount('providers');
    expect(container.querySelector('[data-testid="providers"]')).not.toBeNull();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="open-models"]')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="models"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="providers"]')).toBeNull();
  });

  it('routes a Models readiness key/consent action to the Providers section', async () => {
    await mount('models');
    expect(container.querySelector('[data-testid="models"]')).not.toBeNull();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="open-providers"]')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="providers"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="models"]')).toBeNull();
  });
});
