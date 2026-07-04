// @vitest-environment jsdom
// SidecarBanner.test.tsx — self-healing recovery surface. The banner reads the
// preload bridge structurally (window.api.{onSidecarStatus,restartSidecar}); we
// install a capturing fake so the test can drive status pushes and assert the
// Restart action. Pins: nothing while 'running', the banner on 'down', the
// Restart click invoking restartSidecar() + flipping to "Restarting…", and the
// banner clearing once 'running' is pushed again.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SidecarBanner, type RepairSetupResult, type SidecarStatus } from './SidecarBanner';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- bridge fake ------------------------------------------------------------

let statusCb: ((status: SidecarStatus) => void) | null = null;
let bootstrapErrorCb: ((message: string) => void) | null = null;
const restartSidecar = vi.fn<() => Promise<{ ok: boolean }>>();
const repairSetup = vi.fn<() => Promise<RepairSetupResult>>();

function installBridge(): void {
  (window as unknown as { api?: unknown }).api = {
    onSidecarStatus: (cb: (status: SidecarStatus) => void) => {
      statusCb = cb;
      return () => {
        statusCb = null;
      };
    },
    restartSidecar,
  };
}

/**
 * Bridge that ALSO relays first-run bootstrap errors (WU-1 FAIL-LOUD) and, when
 * `withRepair` (default), exposes the on-demand `repairSetup()` action (WU A5).
 */
function installBridgeWithBootstrap(withRepair = true): void {
  (window as unknown as { api?: unknown }).api = {
    onSidecarStatus: (cb: (status: SidecarStatus) => void) => {
      statusCb = cb;
      return () => {
        statusCb = null;
      };
    },
    restartSidecar,
    onBootstrapError: (cb: (message: string) => void) => {
      bootstrapErrorCb = cb;
      return () => {
        bootstrapErrorCb = null;
      };
    },
    ...(withRepair ? { repairSetup } : {}),
  };
}

/** Drive a supervisor status push into the mounted banner. */
function pushStatus(status: SidecarStatus): void {
  act(() => {
    statusCb?.(status);
  });
}

/** Drive a first-run bootstrap-error push into the mounted banner. */
function pushBootstrapError(message: string): void {
  act(() => {
    bootstrapErrorCb?.(message);
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  statusCb = null;
  bootstrapErrorCb = null;
  restartSidecar.mockReset();
  restartSidecar.mockResolvedValue({ ok: true });
  repairSetup.mockReset();
  repairSetup.mockResolvedValue({ ok: true });
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
    root.render(React.createElement(SidecarBanner, null));
  });
}

function banner(): Element | null {
  return container.querySelector('.sidecar-banner');
}

function restartBtn(): HTMLButtonElement | null {
  return container.querySelector('.sidecar-banner__action');
}

function repairBtn(): HTMLButtonElement | null {
  return container.querySelector('[data-action="repair"]');
}

describe('SidecarBanner', () => {
  it('renders nothing while the sidecar is running (default + explicit)', () => {
    mount();
    expect(banner()).toBeNull();
    pushStatus('running');
    expect(banner()).toBeNull();
  });

  it("shows the recovery banner with a Restart button on status 'down'", () => {
    mount();
    pushStatus('down');
    const el = banner();
    expect(el).not.toBeNull();
    expect(el!.getAttribute('role')).toBe('alert');
    expect(el!.textContent).toContain('Sidecar stopped');
    expect(restartBtn()).not.toBeNull();
    expect(restartBtn()!.textContent).toBe('Restart');
  });

  it('clicking Restart fires window.api.restartSidecar() and shows "Restarting…"', () => {
    mount();
    pushStatus('down');
    act(() => {
      restartBtn()!.click();
    });
    expect(restartSidecar).toHaveBeenCalledTimes(1);
    // Optimistic in-flight state: button gone, message switches to restarting.
    expect(restartBtn()).toBeNull();
    expect(banner()!.textContent).toContain('Restarting');
  });

  it('clears the banner once the supervisor reports running again', () => {
    mount();
    pushStatus('down');
    expect(banner()).not.toBeNull();
    pushStatus('running');
    expect(banner()).toBeNull();
  });

  it("shows 'Restarting…' (no button) when the supervisor reports 'restarting'", () => {
    mount();
    pushStatus('restarting');
    expect(banner()).not.toBeNull();
    expect(banner()!.textContent).toContain('Restarting');
    expect(restartBtn()).toBeNull();
  });

  it('re-offers Restart when restartSidecar resolves {ok:false}', async () => {
    restartSidecar.mockResolvedValueOnce({ ok: false });
    mount();
    pushStatus('down');
    await act(async () => {
      restartBtn()!.click();
      // let the resolved promise settle
      await Promise.resolve();
    });
    // ok:false -> busy cleared, button offered again (still 'down').
    expect(restartBtn()).not.toBeNull();
  });

  it('re-offers Restart when restartSidecar rejects (SidecarBanner.tsx:62-63)', async () => {
    restartSidecar.mockRejectedValueOnce(new Error('respawn failed'));
    mount();
    pushStatus('down');
    await act(async () => {
      restartBtn()!.click();
      // let the rejected promise settle through the .catch()
      await Promise.resolve();
      await Promise.resolve();
    });
    // The .catch() re-enables the button (failure not swallowed) — still 'down'.
    expect(restartBtn()).not.toBeNull();
    expect(banner()!.textContent).toContain('Sidecar stopped');
  });

  it('Restart no-ops when the bridge lacks restartSidecar (SidecarBanner.tsx:52)', () => {
    // Bridge can push status (so the banner + button render on 'down') but has no
    // restartSidecar callable -> onRestart returns early without flipping to busy.
    (window as unknown as { api?: unknown }).api = {
      onSidecarStatus: (cb: (status: SidecarStatus) => void) => {
        statusCb = cb;
        return () => {
          statusCb = null;
        };
      },
      // restartSidecar intentionally omitted
    };
    mount();
    pushStatus('down');
    expect(restartBtn()).not.toBeNull();
    act(() => {
      restartBtn()!.click();
    });
    // No restart fn -> the button stays offered (never went into "Restarting…").
    expect(restartBtn()).not.toBeNull();
    expect(banner()!.textContent).toContain('Sidecar stopped');
  });

  it('degrades to inert when no bridge is present', () => {
    delete (window as unknown as { api?: unknown }).api;
    mount();
    // No status pushes possible; renders nothing and does not throw.
    expect(banner()).toBeNull();
  });

  // ---- WU-1: first-run setup FAIL-LOUD surfacing -----------------------------

  it('surfaces an actionable first-run bootstrap error (role=alert, no Restart)', () => {
    installBridgeWithBootstrap();
    mount();
    expect(banner()).toBeNull();
    pushBootstrapError(
      'FAILED:bootstrap permission denied | data root=C:\\Users\\me | fix: pick a writable folder',
    );
    const el = banner();
    expect(el).not.toBeNull();
    expect(el!.getAttribute('role')).toBe('alert');
    expect(el!.textContent).toContain('permission denied');
    expect(el!.textContent).toContain('fix:');
    // The bootstrap-error banner offers no Restart (the fix is in the message).
    expect(restartBtn()).toBeNull();
  });

  it('ignores an empty bootstrap-error message (stays clear)', () => {
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('');
    expect(banner()).toBeNull();
  });

  it('the bootstrap error takes precedence over a sidecar status banner', () => {
    installBridgeWithBootstrap();
    mount();
    pushStatus('down');
    expect(banner()!.textContent).toContain('Sidecar stopped');
    pushBootstrapError('FAILED:bootstrap I/O error | fix: free disk space');
    // The actionable first-run failure replaces the generic status banner.
    expect(banner()!.textContent).toContain('I/O error');
    expect(restartBtn()).toBeNull();
  });

  // ---- WU A5: on-demand "Retry setup / Repair" control -----------------------

  it('offers a "Retry setup" button on a first-run bootstrap error', () => {
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    const btn = repairBtn();
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toBe('Retry setup');
    // Distinct from the sidecar Restart action (fix is a re-run, not a respawn).
    expect(restartBtn()).toBeNull();
  });

  it('clicking Retry setup invokes repairSetup() and shows an in-flight state', async () => {
    let resolveRepair: (r: RepairSetupResult) => void = () => {};
    repairSetup.mockReturnValueOnce(
      new Promise<RepairSetupResult>((res) => {
        resolveRepair = res;
      }),
    );
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    act(() => {
      repairBtn()!.click();
    });
    expect(repairSetup).toHaveBeenCalledTimes(1);
    // Optimistic in-flight: the button is replaced by a progress note.
    expect(repairBtn()).toBeNull();
    expect(banner()!.textContent).toContain('Retrying setup');
    // Let the pending promise settle so React has no unflushed act() work.
    await act(async () => {
      resolveRepair({ ok: true });
      await Promise.resolve();
    });
  });

  it('clears the banner when repair succeeds ({ok:true})', async () => {
    repairSetup.mockResolvedValueOnce({ ok: true });
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    await act(async () => {
      repairBtn()!.click();
      await Promise.resolve();
    });
    // Success clears the actionable error → the banner falls back to the
    // (now-healthy) sidecar status stream, which is 'running' by default.
    expect(banner()).toBeNull();
  });

  it('re-offers Retry setup and surfaces the reason when repair fails with one', async () => {
    repairSetup.mockResolvedValueOnce({ ok: false, reason: 'Setup failed: disk full' });
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    await act(async () => {
      repairBtn()!.click();
      await Promise.resolve();
    });
    // Loud failure: the button returns AND the fresh reason replaces the message.
    expect(repairBtn()).not.toBeNull();
    expect(banner()!.textContent).toContain('disk full');
  });

  it('re-offers Retry setup keeping the prior message when repair fails without a reason', async () => {
    repairSetup.mockResolvedValueOnce({ ok: false });
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    await act(async () => {
      repairBtn()!.click();
      await Promise.resolve();
    });
    // No reason → keep the existing actionable message (the error channel may
    // push a fresh one), re-offer the button.
    expect(repairBtn()).not.toBeNull();
    expect(banner()!.textContent).toContain('missing weights');
  });

  it('re-offers Retry setup when repairSetup rejects (failure not swallowed)', async () => {
    repairSetup.mockRejectedValueOnce(new Error('spawn failed'));
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    await act(async () => {
      repairBtn()!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(repairBtn()).not.toBeNull();
    expect(banner()!.textContent).toContain('missing weights');
  });

  it('Retry setup no-ops when the bridge lacks repairSetup', () => {
    installBridgeWithBootstrap(false);
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    // The button renders, but with no repairSetup callable the click is inert.
    expect(repairBtn()).not.toBeNull();
    act(() => {
      repairBtn()!.click();
    });
    expect(repairBtn()).not.toBeNull();
    expect(banner()!.textContent).toContain('missing weights');
  });

  it('Retry setup no-ops when the bridge disappears before the click', () => {
    installBridgeWithBootstrap();
    mount();
    pushBootstrapError('FAILED:bootstrap missing weights | fix: retry');
    // The bridge vanishes (e.g. teardown race) after the button rendered.
    delete (window as unknown as { api?: unknown }).api;
    act(() => {
      repairBtn()!.click();
    });
    expect(repairSetup).not.toHaveBeenCalled();
    expect(repairBtn()).not.toBeNull();
  });
});
