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
import { SidecarBanner, type SidecarStatus } from './SidecarBanner';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- bridge fake ------------------------------------------------------------

let statusCb: ((status: SidecarStatus) => void) | null = null;
const restartSidecar = vi.fn<() => Promise<{ ok: boolean }>>();

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

/** Drive a supervisor status push into the mounted banner. */
function pushStatus(status: SidecarStatus): void {
  act(() => {
    statusCb?.(status);
  });
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  statusCb = null;
  restartSidecar.mockReset();
  restartSidecar.mockResolvedValue({ ok: true });
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

  it('degrades to inert when no bridge is present', () => {
    delete (window as unknown as { api?: unknown }).api;
    mount();
    // No status pushes possible; renders nothing and does not throw.
    expect(banner()).toBeNull();
  });
});
