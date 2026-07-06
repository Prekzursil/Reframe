// @vitest-environment jsdom
// UpdateBanner.test.tsx — WU-U: the non-intrusive in-place auto-update surface.
// The banner reads the preload bridge structurally (window.api.{onUpdateStatus,
// downloadUpdate,quitAndInstall}); a capturing fake drives status pushes and
// asserts each UI state (available/progress/downloaded/error/none/checking), the
// Download + Restart actions (success + failure re-offer), the dismiss control,
// the engaged-gated error suppression (quiet offline launch), and inert
// degradation with no bridge.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  UpdateBanner,
  availableLabel,
  readyLabel,
  type UpdateActionResult,
  type UpdateStatus,
} from './UpdateBanner';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- bridge fake ------------------------------------------------------------

let statusCb: ((status: UpdateStatus) => void) | null = null;
const downloadUpdate = vi.fn<() => Promise<UpdateActionResult>>();
const quitAndInstall = vi.fn<() => Promise<UpdateActionResult>>();

/** Install a bridge; pass `false` to omit an action to test the inert path. */
function installBridge(opts: { withDownload?: boolean; withInstall?: boolean } = {}): void {
  const { withDownload = true, withInstall = true } = opts;
  (window as unknown as { api?: unknown }).api = {
    onUpdateStatus: (cb: (status: UpdateStatus) => void) => {
      statusCb = cb;
      return () => {
        statusCb = null;
      };
    },
    ...(withDownload ? { downloadUpdate } : {}),
    ...(withInstall ? { quitAndInstall } : {}),
  };
}

/** Drive an update-status push into the mounted banner. */
function pushStatus(status: UpdateStatus): void {
  act(() => {
    statusCb?.(status);
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  statusCb = null;
  downloadUpdate.mockReset();
  downloadUpdate.mockResolvedValue({ ok: true });
  quitAndInstall.mockReset();
  quitAndInstall.mockResolvedValue({ ok: true });
  installBridge();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (window as unknown as { api?: unknown }).api;
});

function mount(): void {
  act(() => {
    root.render(React.createElement(UpdateBanner, null));
  });
}

function banner(): Element | null {
  return container.querySelector('.update-banner');
}

function btn(action: string): HTMLButtonElement | null {
  return container.querySelector(`[data-action="${action}"]`);
}

describe('label helpers', () => {
  it('availableLabel guards an empty version', () => {
    expect(availableLabel('1.4.0')).toBe('Update v1.4.0 available');
    expect(availableLabel('')).toBe('An update is available');
  });

  it('readyLabel guards an empty version', () => {
    expect(readyLabel('1.4.0')).toBe('Update v1.4.0 is ready to install');
    expect(readyLabel('')).toBe('The update is ready to install');
  });
});

describe('UpdateBanner — silent / idle states', () => {
  it('renders nothing before any status arrives', () => {
    mount();
    expect(banner()).toBeNull();
  });

  it("renders nothing on 'checking' (the auto-check is silent)", () => {
    mount();
    pushStatus({ state: 'checking' });
    expect(banner()).toBeNull();
  });

  it("renders nothing on 'none' (no update available)", () => {
    mount();
    pushStatus({ state: 'none' });
    expect(banner()).toBeNull();
  });

  it('degrades to inert when no bridge is present', () => {
    delete (window as unknown as { api?: unknown }).api;
    mount();
    expect(banner()).toBeNull();
  });

  it('degrades to inert when the bridge lacks onUpdateStatus', () => {
    (window as unknown as { api?: unknown }).api = {};
    mount();
    expect(banner()).toBeNull();
  });
});

describe('UpdateBanner — available -> download', () => {
  it("shows 'Update vX available' + a Download button on 'available'", () => {
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    const el = banner();
    expect(el).not.toBeNull();
    expect(el!.getAttribute('role')).toBe('status');
    expect(el!.textContent).toContain('Update v1.4.0 available');
    expect(btn('download')).not.toBeNull();
  });

  it("shows the fallback label when 'available' carries an empty version", () => {
    mount();
    pushStatus({ state: 'available', version: '' });
    expect(banner()!.textContent).toContain('An update is available');
  });

  it('clicking Download invokes downloadUpdate() and shows "Starting download…"', () => {
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    act(() => {
      btn('download')!.click();
    });
    expect(downloadUpdate).toHaveBeenCalledTimes(1);
    expect(btn('download')).toBeNull();
    expect(banner()!.textContent).toContain('Starting download…');
  });

  it('re-offers Download when downloadUpdate resolves {ok:false}', async () => {
    downloadUpdate.mockResolvedValueOnce({ ok: false, reason: 'offline' });
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    await act(async () => {
      btn('download')!.click();
      await Promise.resolve();
    });
    expect(btn('download')).not.toBeNull();
  });

  it('re-offers Download when downloadUpdate rejects (failure not swallowed)', async () => {
    downloadUpdate.mockRejectedValueOnce(new Error('network'));
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    await act(async () => {
      btn('download')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(btn('download')).not.toBeNull();
  });

  it('Download no-ops when the bridge lacks downloadUpdate', () => {
    installBridge({ withDownload: false });
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    act(() => {
      btn('download')!.click();
    });
    // No callable -> stays on the offered button (never flipped to "Starting…").
    expect(btn('download')).not.toBeNull();
    expect(banner()!.textContent).not.toContain('Starting download');
  });

  it('Download no-ops when the bridge disappears before the click', () => {
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    delete (window as unknown as { api?: unknown }).api;
    act(() => {
      btn('download')!.click();
    });
    expect(downloadUpdate).not.toHaveBeenCalled();
    expect(btn('download')).not.toBeNull();
  });
});

describe('UpdateBanner — progress', () => {
  it("shows 'Downloading N%' with no button on 'progress'", () => {
    mount();
    pushStatus({ state: 'progress', percent: 42 });
    expect(banner()!.textContent).toContain('Downloading 42%');
    expect(btn('download')).toBeNull();
    expect(btn('install')).toBeNull();
  });

  it('a progress push clears the optimistic "Starting download…" note', () => {
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    act(() => {
      btn('download')!.click();
    });
    expect(banner()!.textContent).toContain('Starting download…');
    pushStatus({ state: 'progress', percent: 10 });
    expect(banner()!.textContent).toContain('Downloading 10%');
  });
});

describe('UpdateBanner — downloaded -> restart', () => {
  it("shows 'ready' + a Restart button on 'downloaded'", () => {
    mount();
    pushStatus({ state: 'downloaded', version: '1.4.0' });
    const el = banner();
    expect(el!.className).toContain('update-banner--ready');
    expect(el!.textContent).toContain('Update v1.4.0 is ready to install');
    expect(btn('install')).not.toBeNull();
    expect(btn('install')!.textContent).toBe('Restart to update');
  });

  it("shows the fallback label when 'downloaded' carries an empty version", () => {
    mount();
    pushStatus({ state: 'downloaded', version: '' });
    expect(banner()!.textContent).toContain('The update is ready to install');
  });

  it('clicking Restart invokes quitAndInstall() and shows "Restarting…"', () => {
    mount();
    pushStatus({ state: 'downloaded', version: '1.4.0' });
    act(() => {
      btn('install')!.click();
    });
    expect(quitAndInstall).toHaveBeenCalledTimes(1);
    expect(btn('install')).toBeNull();
    expect(banner()!.textContent).toContain('Restarting…');
  });

  it('re-offers Restart when quitAndInstall resolves {ok:false}', async () => {
    quitAndInstall.mockResolvedValueOnce({ ok: false });
    mount();
    pushStatus({ state: 'downloaded', version: '1.4.0' });
    await act(async () => {
      btn('install')!.click();
      await Promise.resolve();
    });
    expect(btn('install')).not.toBeNull();
  });

  it('re-offers Restart when quitAndInstall rejects', async () => {
    quitAndInstall.mockRejectedValueOnce(new Error('boom'));
    mount();
    pushStatus({ state: 'downloaded', version: '1.4.0' });
    await act(async () => {
      btn('install')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(btn('install')).not.toBeNull();
  });

  it('Restart no-ops when the bridge lacks quitAndInstall', () => {
    installBridge({ withInstall: false });
    mount();
    pushStatus({ state: 'downloaded', version: '1.4.0' });
    act(() => {
      btn('install')!.click();
    });
    expect(btn('install')).not.toBeNull();
    expect(banner()!.textContent).not.toContain('Restarting');
  });
});

describe('UpdateBanner — error (engaged-gated)', () => {
  it("suppresses an 'error' from the silent launch check (user never engaged)", () => {
    mount();
    pushStatus({ state: 'error', message: 'ENOTFOUND' });
    // Quiet degradation: no banner for a launch-time offline/no-release failure.
    expect(banner()).toBeNull();
  });

  it("surfaces an 'error' after the user engaged (clicked Download)", async () => {
    downloadUpdate.mockRejectedValueOnce(new Error('network'));
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    await act(async () => {
      btn('download')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    // Now engaged: a subsequent error IS shown (loud, role=alert).
    pushStatus({ state: 'error', message: 'disk full' });
    const el = banner();
    expect(el).not.toBeNull();
    expect(el!.getAttribute('role')).toBe('alert');
    expect(el!.className).toContain('update-banner--error');
    expect(el!.textContent).toContain('Update failed: disk full');
  });
});

describe('UpdateBanner — dismiss', () => {
  it('dismiss hides the current state, but a new state re-shows', () => {
    mount();
    pushStatus({ state: 'available', version: '1.4.0' });
    expect(banner()).not.toBeNull();
    act(() => {
      btn('dismiss')!.click();
    });
    // The dismissed 'available' state is hidden…
    expect(banner()).toBeNull();
    // …but a DIFFERENT lifecycle state re-shows the banner.
    pushStatus({ state: 'downloaded', version: '1.4.0' });
    expect(banner()).not.toBeNull();
    expect(btn('install')).not.toBeNull();
  });

  it('a repeated same-state push stays hidden after dismiss', () => {
    mount();
    pushStatus({ state: 'progress', percent: 20 });
    act(() => {
      btn('dismiss')!.click();
    });
    expect(banner()).toBeNull();
    // Further progress ticks (same state) stay dismissed.
    pushStatus({ state: 'progress', percent: 55 });
    expect(banner()).toBeNull();
  });
});
