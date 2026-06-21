// App.quality.test.tsx — App's non-routing behaviour that App.test.tsx leaves
// uncovered: the Local/Cloud quality toggle (hydrate-from-settings +
// persist-on-change, with and without the preload bridge), the Settings
// readiness deep-link (Library → Settings/Models), the Jobs slide-over toggle,
// and the Re-export guard branches (no videoId / no bridge / library.list
// rejecting). hasApi is a CONTROLLABLE mock so both bridge-present and
// bridge-absent paths are exercised.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { Video, ShortReexportHint } from './lib/rpc';

// ---- mocks -----------------------------------------------------------------
const rpcMock = vi.fn();
const libraryListMock = vi.fn();
const batchListMock = vi.fn((..._a: unknown[]) => Promise.resolve({ batches: [] as never[] }));
let hasApiValue = true;

vi.mock('./lib/rpc', () => ({
  rpc: (...a: unknown[]) => rpcMock(...a),
  hasApi: () => hasApiValue,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
    batch: { list: (...a: unknown[]) => batchListMock(...a) },
  },
}));

vi.mock('./views/Repurpose', () => ({
  Repurpose: () => <div data-testid="repurpose" />,
}));

// The Library stub exposes BOTH onOpen and onReadinessAction so we can drive
// the readiness deep-link into Settings/Models.
vi.mock('./views/Library', () => ({
  Library: ({
    onOpen,
    onReadinessAction,
  }: {
    onOpen: (v: Video) => void;
    onReadinessAction?: (action: unknown) => void;
  }) => (
    <div data-testid="library">
      <button
        type="button"
        data-testid="open-video"
        onClick={() =>
          onOpen({
            id: 'v1',
            path: '/movies/talk.mp4',
            title: 'Talk',
            addedAt: '2026-06-11T00:00:00Z',
            durationSec: 600,
            hasTranscript: false,
          })
        }
      >
        open-video
      </button>
      <button
        type="button"
        data-testid="readiness-fix"
        onClick={() => onReadinessAction?.({ kind: 'assets.ensure', assets: ['x'] })}
      >
        fix
      </button>
      <button
        type="button"
        data-testid="readiness-fix-key"
        onClick={() => onReadinessAction?.({ kind: 'openProviders', provider: 'Groq' })}
      >
        fix-key
      </button>
    </div>
  ),
}));
vi.mock('./views/Workspace', () => ({
  Workspace: ({ video }: { video: Video }) => (
    <div data-testid="workspace" data-video-id={video.id} />
  ),
}));
vi.mock('./views/Shorts', () => ({
  Shorts: ({ onReexport }: { onReexport?: (h: ShortReexportHint) => void }) => (
    <div data-testid="shorts">
      <button
        type="button"
        data-testid="reexport-ok"
        onClick={() =>
          onReexport?.({
            videoId: 'v1',
            candidate: { hook: 'h', template: 'neon', viralityPct: 70, durationSec: 30 },
          })
        }
      >
        reexport-ok
      </button>
      <button
        type="button"
        data-testid="reexport-no-id"
        onClick={() =>
          onReexport?.({
            videoId: '',
            candidate: { hook: 'h', template: 'neon', viralityPct: 70, durationSec: 30 },
          })
        }
      >
        reexport-no-id
      </button>
    </div>
  ),
}));
// Settings stub surfaces the initialSection App wired (proves the deep-link).
vi.mock('./views/Settings', () => ({
  Settings: ({ initialSection }: { initialSection?: string }) => (
    <div data-testid="settings" data-section={initialSection ?? ''} />
  ),
}));
vi.mock('./components/JobQueue', () => ({
  JobQueue: ({ open, onClose }: { open: boolean; onClose: () => void }) => (
    <div data-testid="jobqueue" data-open={String(open)}>
      <button type="button" data-testid="jobqueue-close" onClick={onClose}>
        close
      </button>
    </div>
  ),
}));
vi.mock('./components/SidecarBanner', () => ({ SidecarBanner: () => <div /> }));

import { App } from './App';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  hasApiValue = true;
  rpcMock.mockReset();
  rpcMock.mockResolvedValue({});
  libraryListMock.mockReset();
  libraryListMock.mockResolvedValue({ videos: [] });
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

async function mount(): Promise<void> {
  await act(async () => {
    root.render(<App />);
  });
  await flush();
}

function qualityBtn(label: 'Local' | 'Cloud'): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.quality-toggle__btn'));
  const found = btns.find((b) => b.textContent === label);
  if (!found) throw new Error(`quality button "${label}" not found`);
  return found;
}

function tab(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.toptab'));
  const found = btns.find((b) => b.querySelector('.toptab__label')?.textContent === label);
  if (!found) throw new Error(`tab "${label}" not found`);
  return found;
}

describe('App quality toggle — hydrate from settings', () => {
  it('hydrates to Cloud when settings.useCloud is true', async () => {
    rpcMock.mockImplementation((method: string) =>
      method === 'settings.get' ? Promise.resolve({ useCloud: true }) : Promise.resolve({}),
    );
    await mount();
    expect(rpcMock).toHaveBeenCalledWith('settings.get');
    expect(qualityBtn('Cloud').getAttribute('aria-pressed')).toBe('true');
    expect(qualityBtn('Cloud').classList.contains('is-active')).toBe(true);
    expect(qualityBtn('Local').getAttribute('aria-pressed')).toBe('false');
  });

  it('hydrates to Local when settings.useCloud is false', async () => {
    rpcMock.mockImplementation((method: string) =>
      method === 'settings.get' ? Promise.resolve({ useCloud: false }) : Promise.resolve({}),
    );
    await mount();
    expect(qualityBtn('Local').getAttribute('aria-pressed')).toBe('true');
    expect(qualityBtn('Local').classList.contains('is-active')).toBe(true);
  });

  it('keeps the Local default when settings.useCloud is absent (non-boolean)', async () => {
    rpcMock.mockImplementation((method: string) =>
      method === 'settings.get' ? Promise.resolve({ somethingElse: 1 }) : Promise.resolve({}),
    );
    await mount();
    expect(qualityBtn('Local').getAttribute('aria-pressed')).toBe('true');
  });

  it('keeps the Local default when settings is null', async () => {
    rpcMock.mockImplementation((method: string) =>
      method === 'settings.get' ? Promise.resolve(null) : Promise.resolve({}),
    );
    await mount();
    expect(qualityBtn('Local').getAttribute('aria-pressed')).toBe('true');
  });

  it('swallows a settings.get rejection and keeps the Local default', async () => {
    rpcMock.mockImplementation((method: string) =>
      method === 'settings.get' ? Promise.reject(new Error('boom')) : Promise.resolve({}),
    );
    await mount();
    expect(qualityBtn('Local').getAttribute('aria-pressed')).toBe('true');
  });

  it('does NOT call settings.get when the preload bridge is absent', async () => {
    hasApiValue = false;
    await mount();
    expect(rpcMock).not.toHaveBeenCalledWith('settings.get');
    expect(qualityBtn('Local').getAttribute('aria-pressed')).toBe('true');
  });
});

describe('App quality toggle — persist on change', () => {
  it('persists useCloud=true via settings.set and flips the active button', async () => {
    await mount();
    await act(async () => {
      qualityBtn('Cloud').click();
    });
    await flush();
    expect(rpcMock).toHaveBeenCalledWith('settings.set', { useCloud: true });
    expect(qualityBtn('Cloud').classList.contains('is-active')).toBe(true);
    expect(qualityBtn('Local').classList.contains('is-active')).toBe(false);
  });

  it('persists useCloud=false when switching back to Local', async () => {
    await mount();
    await act(async () => {
      qualityBtn('Cloud').click();
    });
    await flush();
    await act(async () => {
      qualityBtn('Local').click();
    });
    await flush();
    expect(rpcMock).toHaveBeenCalledWith('settings.set', { useCloud: false });
    expect(qualityBtn('Local').classList.contains('is-active')).toBe(true);
  });

  it('still flips the in-memory toggle when no bridge is present (no settings.set)', async () => {
    hasApiValue = false;
    await mount();
    await act(async () => {
      qualityBtn('Cloud').click();
    });
    await flush();
    expect(rpcMock).not.toHaveBeenCalledWith('settings.set', { useCloud: true });
    expect(qualityBtn('Cloud').classList.contains('is-active')).toBe(true);
  });

  it('swallows a settings.set rejection but still reflects the choice', async () => {
    rpcMock.mockImplementation((method: string) =>
      method === 'settings.set' ? Promise.reject(new Error('nope')) : Promise.resolve({}),
    );
    await mount();
    await act(async () => {
      qualityBtn('Cloud').click();
    });
    await flush();
    expect(qualityBtn('Cloud').classList.contains('is-active')).toBe(true);
  });
});

describe('App readiness deep-link → Settings', () => {
  it('routes a download (assets.ensure) fix to the Models & System section', async () => {
    await mount();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="readiness-fix"]')!.click();
    });
    await flush();
    const settings = container.querySelector('[data-testid="settings"]');
    expect(settings).not.toBeNull();
    expect(settings!.getAttribute('data-section')).toBe('models');
    expect(tab('Settings').getAttribute('aria-selected')).toBe('true');
  });

  it('routes a key (openProviders) fix to the Providers & Keys section', async () => {
    await mount();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="readiness-fix-key"]')!.click();
    });
    await flush();
    const settings = container.querySelector('[data-testid="settings"]');
    expect(settings).not.toBeNull();
    expect(settings!.getAttribute('data-section')).toBe('providers');
    expect(tab('Settings').getAttribute('aria-selected')).toBe('true');
  });
});

describe('App jobs slide-over toggle', () => {
  it('opens and closes the JobQueue via the Jobs button', async () => {
    await mount();
    const jobsToggle = container.querySelector<HTMLButtonElement>('.app__jobs-toggle')!;
    expect(jobsToggle.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('[data-testid="jobqueue"]')!.getAttribute('data-open')).toBe(
      'false',
    );
    await act(async () => {
      jobsToggle.click();
    });
    await flush();
    expect(jobsToggle.getAttribute('aria-expanded')).toBe('true');
    expect(container.querySelector('[data-testid="jobqueue"]')!.getAttribute('data-open')).toBe(
      'true',
    );
    await act(async () => {
      jobsToggle.click();
    });
    await flush();
    expect(jobsToggle.getAttribute('aria-expanded')).toBe('false');
  });

  it('closes the JobQueue via its own onClose handler', async () => {
    await mount();
    const jobsToggle = container.querySelector<HTMLButtonElement>('.app__jobs-toggle')!;
    await act(async () => {
      jobsToggle.click();
    });
    await flush();
    expect(jobsToggle.getAttribute('aria-expanded')).toBe('true');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="jobqueue-close"]')!.click();
    });
    await flush();
    expect(jobsToggle.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('[data-testid="jobqueue"]')!.getAttribute('data-open')).toBe(
      'false',
    );
  });
});

describe('App handleReexport guard branches', () => {
  it('falls back to the Library when the hint has no videoId', async () => {
    await mount();
    await act(async () => {
      tab('Create').click();
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="reexport-no-id"]')!.click();
    });
    await flush();
    expect(libraryListMock).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
  });

  it('falls back to the Library when no preload bridge is present', async () => {
    hasApiValue = false;
    await mount();
    await act(async () => {
      tab('Create').click();
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="reexport-ok"]')!.click();
    });
    await flush();
    expect(libraryListMock).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
  });

  it('falls back to the Library when library.list rejects (catch branch)', async () => {
    libraryListMock.mockRejectedValue(new Error('list failed'));
    await mount();
    await act(async () => {
      tab('Create').click();
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="reexport-ok"]')!.click();
    });
    await flush();
    expect(libraryListMock).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="workspace"]')).toBeNull();
  });
});

describe('App lastOpenedVideoId — bridge-absent branches (WU-13)', () => {
  it('does NOT read settings.get on launch when no preload bridge is present', async () => {
    hasApiValue = false;
    await mount();
    expect(rpcMock).not.toHaveBeenCalledWith('settings.get');
    expect(libraryListMock).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
  });

  it('does NOT persist lastOpenedVideoId when no preload bridge is present', async () => {
    hasApiValue = false;
    await mount();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="open-video"]')!.click();
    });
    await flush();
    expect(rpcMock).not.toHaveBeenCalledWith('settings.set', { lastOpenedVideoId: 'v1' });
    expect(
      container.querySelector('[data-testid="workspace"]')!.getAttribute('data-video-id'),
    ).toBe('v1');
  });
});
