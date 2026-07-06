// @vitest-environment jsdom
// FirstRunSetup.test.tsx — the full-screen first-run provisioning gate (WU-1b).
//
// Three layers, each held to 100%:
//   * pure helpers: parseBootstrapLine / cleanLine / reduceProgress / phaseLabel,
//   * the presentational <FirstRunSetup> (progress + FAILURE/OFFLINE bodies),
//   * the useFirstRunSetup hook (the WU-1a signal subscriptions + visibility +
//     Retry wiring), driven through a Probe that also mounts the real component.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  FirstRunSetup,
  useFirstRunSetup,
  parseBootstrapLine,
  cleanLine,
  reduceProgress,
  phaseLabel,
  INITIAL_PROGRESS,
  SETUP_ESTIMATE_MIN,
  type BootstrapProgressEvent,
  type FirstRunSetupView,
  type ProvisioningState,
  type RepairSetupResult,
} from './FirstRunSetup';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---- pure helpers -----------------------------------------------------------

describe('parseBootstrapLine', () => {
  it('parses an asset-download percentage (with a [bootstrap] prefix + padding)', () => {
    expect(parseBootstrapLine('[bootstrap] assets  12.3%  downloading yunet')).toEqual({
      kind: 'assets',
      pct: 12.3,
    });
  });

  it('parses a whole-number asset percentage', () => {
    expect(parseBootstrapLine('assets 100%')).toEqual({ kind: 'assets', pct: 100 });
  });

  it('parses a pip build step k/N', () => {
    expect(parseBootstrapLine('[bootstrap] step 1/2: python -m pip install')).toEqual({
      kind: 'step',
      k: 1,
      n: 2,
    });
  });

  it('returns "other" for a line with neither signal', () => {
    expect(parseBootstrapLine('first-run setup starting')).toEqual({ kind: 'other' });
  });
});

describe('cleanLine', () => {
  it('strips the [bootstrap] prefix and collapses whitespace', () => {
    expect(cleanLine('[bootstrap] assets  12.3%  downloading x')).toBe('assets 12.3% downloading x');
  });

  it('leaves an unprefixed line intact (just trimmed)', () => {
    expect(cleanLine('  env ready  ')).toBe('env ready');
  });
});

describe('reduceProgress', () => {
  it("maps a 'done' event to the finishing phase at 100% with no detail", () => {
    expect(reduceProgress(INITIAL_PROGRESS, { state: 'done', line: 'bootstrap exited (code 0)' })).toEqual(
      { phase: 'finishing', pct: 100, line: '' },
    );
  });

  it("leaves state unchanged for an 'error' event (message arrives elsewhere)", () => {
    const prev = { phase: 'downloading' as const, pct: 40, line: 'x' };
    expect(reduceProgress(prev, { state: 'error', line: 'boom' })).toBe(prev);
  });

  it('maps an assets line to the downloading phase at that percent', () => {
    expect(reduceProgress(INITIAL_PROGRESS, { state: 'running', line: 'assets 55.5% x' })).toEqual({
      phase: 'downloading',
      pct: 55.5,
      line: 'assets 55.5% x',
    });
  });

  it('maps a step line to the building phase at k/N', () => {
    expect(reduceProgress(INITIAL_PROGRESS, { state: 'running', line: 'step 1/2: pip' })).toEqual({
      phase: 'building',
      pct: 50,
      line: 'step 1/2: pip',
    });
  });

  it('guards a degenerate step N=0 to 0% (no divide-by-zero)', () => {
    expect(reduceProgress(INITIAL_PROGRESS, { state: 'running', line: 'step 1/0: pip' })).toEqual({
      phase: 'building',
      pct: 0,
      line: 'step 1/0: pip',
    });
  });

  it('keeps the phase/percent and refreshes the detail for an unrecognised line', () => {
    const prev = { phase: 'downloading' as const, pct: 40, line: 'old' };
    expect(reduceProgress(prev, { state: 'running', line: '[bootstrap] env ready' })).toEqual({
      phase: 'downloading',
      pct: 40,
      line: 'env ready',
    });
  });
});

describe('phaseLabel', () => {
  it('labels every phase', () => {
    expect(phaseLabel('building')).toBe('Building environment');
    expect(phaseLabel('downloading')).toBe('Downloading core models');
    expect(phaseLabel('finishing')).toBe('Finishing');
  });
});

// ---- DOM harness ------------------------------------------------------------

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  setNavigatorOnline(true);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (window as unknown as { api?: unknown }).api;
});

function setNavigatorOnline(value: boolean): void {
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, get: () => value });
}

// ---- presentational <FirstRunSetup> ----------------------------------------

function baseView(over: Partial<FirstRunSetupView> = {}): FirstRunSetupView {
  return {
    ready: true,
    visible: true,
    phase: 'building',
    pct: 0,
    line: '',
    error: null,
    retrying: false,
    online: true,
    onRetry: () => {},
    ...over,
  };
}

function renderView(view: FirstRunSetupView): void {
  act(() => {
    root.render(React.createElement(FirstRunSetup, { view }));
  });
}

describe('FirstRunSetup (presentational)', () => {
  it('shows the brand, one-time subtitle, phase label and progress bar', () => {
    renderView(baseView({ phase: 'downloading', pct: 42, line: 'assets 42% x' }));
    expect(container.querySelector('.first-run-setup__brand')!.textContent).toBe('Reframe');
    expect(container.querySelector('.first-run-setup__subtitle')!.textContent).toContain(
      String(SETUP_ESTIMATE_MIN),
    );
    expect(container.querySelector('.first-run-setup__phase')!.textContent).toBe(
      'Downloading core models',
    );
    const bar = container.querySelector('[role="progressbar"]')!;
    expect(bar.getAttribute('aria-valuenow')).toBe('42');
    // A non-empty detail line renders.
    expect(container.querySelector('.first-run-setup__detail')!.textContent).toBe('assets 42% x');
    // Online + no error: no offline hint, no error body.
    expect(container.querySelector('.first-run-setup__offline')).toBeNull();
    expect(container.querySelector('.first-run-setup__error')).toBeNull();
  });

  it('omits the detail line when there is none', () => {
    renderView(baseView({ line: '' }));
    expect(container.querySelector('.first-run-setup__detail')).toBeNull();
  });

  it('shows "Retrying setup…" while a retry is in flight (progress body, not error)', () => {
    renderView(baseView({ retrying: true, error: 'FAILED:bootstrap boom' }));
    expect(container.querySelector('.first-run-setup__phase')!.textContent).toBe('Retrying setup…');
    // retrying wins over the error: the failure body is not shown.
    expect(container.querySelector('.first-run-setup__error')).toBeNull();
  });

  it('renders the OFFLINE hint inside the progress body when offline', () => {
    renderView(baseView({ online: false }));
    expect(container.querySelector('.first-run-setup__offline')).not.toBeNull();
  });

  it('renders the FAILURE body with an actionable message, generic hint and Retry', () => {
    const onRetry = vi.fn();
    renderView(baseView({ error: 'FAILED:bootstrap disk full | fix: free space', onRetry }));
    const err = container.querySelector('.first-run-setup__error')!;
    expect(err.getAttribute('role')).toBe('alert');
    expect(err.textContent).toContain('disk full');
    // Online failure → generic hint, not the offline hint.
    expect(container.querySelector('.first-run-setup__hint')).not.toBeNull();
    expect(container.querySelector('.first-run-setup__offline')).toBeNull();
    // The progress body is replaced by the failure body.
    expect(container.querySelector('.first-run-setup__progress')).toBeNull();
    const retry = container.querySelector<HTMLButtonElement>('[data-action="retry"]')!;
    expect(retry.textContent).toBe('Retry setup');
    act(() => retry.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('renders the OFFLINE hint (not the generic one) in the failure body when offline', () => {
    renderView(baseView({ error: 'FAILED:bootstrap network', online: false }));
    expect(container.querySelector('.first-run-setup__offline')).not.toBeNull();
    expect(container.querySelector('.first-run-setup__hint')).toBeNull();
  });
});

// ---- useFirstRunSetup hook (through a Probe) --------------------------------

let provisioningCb: ((state: ProvisioningState | null) => void) | null = null;
let progressCb: ((event: BootstrapProgressEvent) => void) | null = null;
let errorCb: ((message: string) => void) | null = null;
const repairSetup = vi.fn<() => Promise<RepairSetupResult>>();
const getProvisioningState = vi.fn<() => Promise<ProvisioningState>>();

interface BridgeOpts {
  omitProvisioning?: boolean;
  omitProgress?: boolean;
  omitError?: boolean;
  omitRepair?: boolean;
  /** Include the mount-time `getProvisioningState` query on the bridge. */
  withQuery?: boolean;
}

function installBridge(opts: BridgeOpts = {}): void {
  (window as unknown as { api?: unknown }).api = {
    ...(opts.withQuery ? { getProvisioningState } : {}),
    ...(opts.omitProvisioning
      ? {}
      : {
          onProvisioningState: (cb: (state: ProvisioningState | null) => void) => {
            provisioningCb = cb;
            return () => {
              provisioningCb = null;
            };
          },
        }),
    ...(opts.omitProgress
      ? {}
      : {
          onBootstrapProgress: (cb: (event: BootstrapProgressEvent) => void) => {
            progressCb = cb;
            return () => {
              progressCb = null;
            };
          },
        }),
    ...(opts.omitError
      ? {}
      : {
          onBootstrapError: (cb: (message: string) => void) => {
            errorCb = cb;
            return () => {
              errorCb = null;
            };
          },
        }),
    ...(opts.omitRepair ? {} : { repairSetup }),
  };
}

function Probe(): React.ReactElement {
  const view = useFirstRunSetup();
  return (
    <div
      data-testid="probe"
      data-ready={String(view.ready)}
      data-visible={String(view.visible)}
      data-phase={view.phase}
      data-pct={String(view.pct)}
      data-line={view.line}
      data-error={view.error ?? ''}
      data-retrying={String(view.retrying)}
      data-online={String(view.online)}
    >
      {view.visible ? <FirstRunSetup view={view} /> : <div data-testid="shell" />}
      <button type="button" data-testid="probe-retry" onClick={view.onRetry}>
        retry
      </button>
    </div>
  );
}

function mountProbe(): void {
  act(() => {
    root.render(React.createElement(Probe, null));
  });
}

function probe(): HTMLElement {
  return container.querySelector<HTMLElement>('[data-testid="probe"]')!;
}

function pushProvisioning(state: ProvisioningState | null): void {
  act(() => provisioningCb?.(state));
}

function pushProgress(event: BootstrapProgressEvent): void {
  act(() => progressCb?.(event));
}

function pushError(message: string): void {
  act(() => errorCb?.(message));
}

function clickRetry(): void {
  act(() => {
    container.querySelector<HTMLButtonElement>('[data-testid="probe-retry"]')!.click();
  });
}

describe('useFirstRunSetup', () => {
  beforeEach(() => {
    provisioningCb = null;
    progressCb = null;
    errorCb = null;
    repairSetup.mockReset();
    repairSetup.mockResolvedValue({ ok: true });
    getProvisioningState.mockReset();
    getProvisioningState.mockResolvedValue({ active: false });
    installBridge();
  });

  it('is hidden by default (no provisioning, no error) — the shell shows', () => {
    mountProbe();
    // No getProvisioningState on the bridge → ready resolves immediately.
    expect(probe().getAttribute('data-ready')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('false');
    expect(container.querySelector('[data-testid="shell"]')).not.toBeNull();
    expect(container.querySelector('.first-run-setup')).toBeNull();
  });

  // ---- mount-time initial query (WU-1b frame-0 gate) ------------------------

  it('is not ready until the mount-time query resolves; an active result shows the gate', async () => {
    let resolveQuery: (s: ProvisioningState) => void = () => {};
    getProvisioningState.mockReturnValueOnce(
      new Promise<ProvisioningState>((res) => {
        resolveQuery = res;
      }),
    );
    installBridge({ withQuery: true });
    mountProbe();
    // Query in flight: not ready yet, so App would withhold the shell.
    expect(probe().getAttribute('data-ready')).toBe('false');
    expect(probe().getAttribute('data-visible')).toBe('false');
    await act(async () => {
      resolveQuery({ active: true });
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-ready')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('true');
  });

  it('a query resolving inactive marks ready without showing the gate', async () => {
    getProvisioningState.mockResolvedValueOnce({ active: false });
    installBridge({ withQuery: true });
    mountProbe();
    await act(async () => {
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-ready')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('treats a null query payload as inactive', async () => {
    getProvisioningState.mockResolvedValueOnce(null as unknown as ProvisioningState);
    installBridge({ withQuery: true });
    mountProbe();
    await act(async () => {
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-ready')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('still marks ready when the query rejects (never strands the window blank)', async () => {
    getProvisioningState.mockRejectedValueOnce(new Error('ipc down'));
    installBridge({ withQuery: true });
    mountProbe();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-ready')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('ignores a query that resolves AFTER unmount (cancelled guard)', async () => {
    let resolveQuery: (s: ProvisioningState) => void = () => {};
    getProvisioningState.mockReturnValueOnce(
      new Promise<ProvisioningState>((res) => {
        resolveQuery = res;
      }),
    );
    installBridge({ withQuery: true });
    mountProbe();
    act(() => root.unmount());
    await act(async () => {
      resolveQuery({ active: true });
      await Promise.resolve();
    });
    root = createRoot(container);
  });

  it('ignores a query that rejects AFTER unmount (cancelled guard)', async () => {
    let rejectQuery: (e: Error) => void = () => {};
    getProvisioningState.mockReturnValueOnce(
      new Promise<ProvisioningState>((_res, rej) => {
        rejectQuery = rej;
      }),
    );
    installBridge({ withQuery: true });
    mountProbe();
    act(() => root.unmount());
    await act(async () => {
      rejectQuery(new Error('late'));
      await Promise.resolve();
      await Promise.resolve();
    });
    root = createRoot(container);
  });

  it('becomes visible when provisioning goes active and hides again when it clears', () => {
    mountProbe();
    pushProvisioning({ active: true });
    expect(probe().getAttribute('data-visible')).toBe('true');
    expect(container.querySelector('.first-run-setup')).not.toBeNull();
    expect(container.querySelector('[data-testid="shell"]')).toBeNull();
    // Sidecar reached running → provisioning drops, no error → hand off to shell.
    pushProvisioning({ active: false });
    expect(probe().getAttribute('data-visible')).toBe('false');
    expect(container.querySelector('[data-testid="shell"]')).not.toBeNull();
  });

  it('treats a null/absent provisioning payload as inactive', () => {
    mountProbe();
    pushProvisioning(null);
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('folds progress events into the phase/percent/detail', () => {
    mountProbe();
    pushProvisioning({ active: true });
    pushProgress({ state: 'running', line: '[bootstrap] step 1/2: pip' });
    expect(probe().getAttribute('data-phase')).toBe('building');
    expect(probe().getAttribute('data-pct')).toBe('50');
    pushProgress({ state: 'running', line: 'assets 80% qwen' });
    expect(probe().getAttribute('data-phase')).toBe('downloading');
    expect(probe().getAttribute('data-pct')).toBe('80');
    pushProgress({ state: 'done', line: 'bootstrap exited (code 0)' });
    expect(probe().getAttribute('data-phase')).toBe('finishing');
    expect(probe().getAttribute('data-pct')).toBe('100');
  });

  it('surfaces a bootstrap error (visible even after provisioning drops) and ignores empty', () => {
    mountProbe();
    pushProvisioning({ active: true });
    pushError('FAILED:bootstrap missing weights | fix: retry');
    // Failure clears provisioning in main; the gate must STAY up on the error.
    pushProvisioning({ active: false });
    expect(probe().getAttribute('data-visible')).toBe('true');
    expect(container.querySelector('.first-run-setup__error')).not.toBeNull();
    expect(container.querySelector('.first-run-setup__error')!.textContent).toContain(
      'missing weights',
    );
    // An empty message clears the error → hides (nothing else keeping it up).
    pushError('');
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('reflects offline connectivity via window online/offline events', () => {
    mountProbe();
    pushProvisioning({ active: true });
    expect(probe().getAttribute('data-online')).toBe('true');
    setNavigatorOnline(false);
    act(() => window.dispatchEvent(new Event('offline')));
    expect(probe().getAttribute('data-online')).toBe('false');
    expect(container.querySelector('.first-run-setup__offline')).not.toBeNull();
    setNavigatorOnline(true);
    act(() => window.dispatchEvent(new Event('online')));
    expect(probe().getAttribute('data-online')).toBe('true');
  });

  // ---- Retry wiring ---------------------------------------------------------

  it('Retry calls repairSetup, shows an in-flight state, and clears the error on success', async () => {
    let resolveRepair: (r: RepairSetupResult) => void = () => {};
    repairSetup.mockReturnValueOnce(
      new Promise<RepairSetupResult>((res) => {
        resolveRepair = res;
      }),
    );
    mountProbe();
    pushError('FAILED:bootstrap boom | fix: retry');
    expect(probe().getAttribute('data-visible')).toBe('true');
    clickRetry();
    expect(repairSetup).toHaveBeenCalledTimes(1);
    // Optimistic in-flight: retrying true, the progress body replaces the error.
    expect(probe().getAttribute('data-retrying')).toBe('true');
    expect(container.querySelector('.first-run-setup__phase')!.textContent).toBe('Retrying setup…');
    await act(async () => {
      resolveRepair({ ok: true });
      await Promise.resolve();
    });
    // Success cleared the error; nothing keeps the gate up → hidden.
    expect(probe().getAttribute('data-retrying')).toBe('false');
    expect(probe().getAttribute('data-error')).toBe('');
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('Retry surfaces a fresh reason and re-offers when repair fails with one', async () => {
    repairSetup.mockResolvedValueOnce({ ok: false, reason: 'Setup failed: disk full' });
    mountProbe();
    pushError('FAILED:bootstrap boom | fix: retry');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="probe-retry"]')!.click();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-retrying')).toBe('false');
    expect(probe().getAttribute('data-error')).toBe('Setup failed: disk full');
    expect(probe().getAttribute('data-visible')).toBe('true');
  });

  it('Retry keeps the prior message when repair fails without a reason', async () => {
    repairSetup.mockResolvedValueOnce({ ok: false });
    mountProbe();
    pushError('FAILED:bootstrap boom | fix: retry');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="probe-retry"]')!.click();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-error')).toBe('FAILED:bootstrap boom | fix: retry');
    expect(probe().getAttribute('data-visible')).toBe('true');
  });

  it('Retry drops the in-flight state when repairSetup rejects (failure not swallowed)', async () => {
    repairSetup.mockRejectedValueOnce(new Error('spawn failed'));
    mountProbe();
    pushError('FAILED:bootstrap boom | fix: retry');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="probe-retry"]')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-retrying')).toBe('false');
    // The prior actionable message is retained; the gate stays up.
    expect(probe().getAttribute('data-error')).toBe('FAILED:bootstrap boom | fix: retry');
    expect(probe().getAttribute('data-visible')).toBe('true');
  });

  it('Retry no-ops when the bridge lacks repairSetup', () => {
    installBridge({ omitRepair: true });
    mountProbe();
    pushError('FAILED:bootstrap boom | fix: retry');
    clickRetry();
    expect(repairSetup).not.toHaveBeenCalled();
    expect(probe().getAttribute('data-retrying')).toBe('false');
    expect(probe().getAttribute('data-visible')).toBe('true');
  });

  it('Retry no-ops when the bridge disappears before the click', () => {
    mountProbe();
    pushError('FAILED:bootstrap boom | fix: retry');
    delete (window as unknown as { api?: unknown }).api;
    clickRetry();
    expect(repairSetup).not.toHaveBeenCalled();
  });

  // ---- degraded bridges (early-return guards) -------------------------------

  it('degrades to inert with no bridge at all (never visible, no throw)', () => {
    delete (window as unknown as { api?: unknown }).api;
    mountProbe();
    expect(probe().getAttribute('data-visible')).toBe('false');
    expect(container.querySelector('[data-testid="shell"]')).not.toBeNull();
  });

  it('subscribes only to the signals the bridge actually exposes', () => {
    // A bridge missing every optional signal fn exercises each typeof-guard
    // early-return; the gate stays inert.
    installBridge({
      omitProvisioning: true,
      omitProgress: true,
      omitError: true,
      omitRepair: true,
    });
    mountProbe();
    expect(probe().getAttribute('data-visible')).toBe('false');
    clickRetry();
    expect(repairSetup).not.toHaveBeenCalled();
  });
});
