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
  type ChooseInstallProfileResult,
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
    expect(cleanLine('[bootstrap] assets  12.3%  downloading x')).toBe(
      'assets 12.3% downloading x',
    );
  });

  it('leaves an unprefixed line intact (just trimmed)', () => {
    expect(cleanLine('  env ready  ')).toBe('env ready');
  });
});

describe('reduceProgress', () => {
  it("maps a 'done' event to the finishing phase at 100% with no detail", () => {
    expect(
      reduceProgress(INITIAL_PROGRESS, { state: 'done', line: 'bootstrap exited (code 0)' }),
    ).toEqual({ phase: 'finishing', pct: 100, line: '' });
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
    awaitingProfile: false,
    showChooser: false,
    choosingRouting: false,
    choiceError: null,
    phase: 'building',
    pct: 0,
    line: '',
    error: null,
    retrying: false,
    online: true,
    onRetry: () => {},
    onChooseProfile: () => {},
    onChooseRouting: () => {},
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

  // ---- WU-1c: the profile picker slot -----------------------------------------

  it('renders the ProfilePicker (not progress) while awaiting the profile choice', () => {
    const onChooseProfile = vi.fn();
    renderView(baseView({ awaitingProfile: true, onChooseProfile }));
    expect(container.querySelector('.profile-picker')).not.toBeNull();
    // the picker replaces the progress + error bodies
    expect(container.querySelector('.first-run-setup__progress')).toBeNull();
    expect(container.querySelector('.first-run-setup__error')).toBeNull();
    // the picker heading + subtitle swap to the setup-choice copy
    expect(container.querySelector('.first-run-setup__title')!.textContent).toBe('Set up Reframe');
    // committing a choice bubbles through onChooseProfile
    act(() =>
      container.querySelector<HTMLButtonElement>('[data-action="confirm-profile"]')!.click(),
    );
    expect(onChooseProfile).toHaveBeenCalledTimes(1);
  });

  it('an error takes precedence over the picker (busy folder after launch)', () => {
    renderView(baseView({ awaitingProfile: true, error: 'FAILED:bootstrap folder busy' }));
    expect(container.querySelector('.profile-picker')).toBeNull();
    expect(container.querySelector('.first-run-setup__error')).not.toBeNull();
  });

  it('a retry-in-flight takes precedence over the picker', () => {
    renderView(baseView({ awaitingProfile: true, retrying: true }));
    expect(container.querySelector('.profile-picker')).toBeNull();
    expect(container.querySelector('.first-run-setup__progress')).not.toBeNull();
  });

  // ---- WU-1d: the local-vs-cloud routing chooser step -------------------------

  it('renders the routing chooser (not progress) as the final step, after the picker', () => {
    const onChooseRouting = vi.fn();
    renderView(baseView({ showChooser: true, onChooseRouting }));
    // the shared FirstRunChooser is shown, replacing progress/picker/error
    expect(container.querySelector('.first-run-chooser')).not.toBeNull();
    expect(container.querySelector('.first-run-setup__progress')).toBeNull();
    expect(container.querySelector('.profile-picker')).toBeNull();
    // the header swaps to the setup-choice copy with an AI-routing subtitle
    expect(container.querySelector('.first-run-setup__title')!.textContent).toBe('Set up Reframe');
    expect(container.querySelector('.first-run-setup__subtitle')!.textContent).toContain(
      'how Reframe runs AI',
    );
    // picking cloud (the opt-in path) bubbles through onChooseRouting
    act(() => container.querySelector<HTMLButtonElement>('[data-choice="bestFreeCloud"]')!.click());
    expect(onChooseRouting).toHaveBeenCalledWith('bestFreeCloud');
  });

  it('disables the chooser while the choice is being applied (busy)', () => {
    renderView(baseView({ showChooser: true, choosingRouting: true }));
    const cloud = container.querySelector<HTMLButtonElement>('[data-choice="bestFreeCloud"]')!;
    expect(cloud.disabled).toBe(true);
  });

  it('renders a LOUD inline error when applying the routing choice failed', () => {
    renderView(baseView({ showChooser: true, choiceError: 'Could not save your choice.' }));
    const err = container.querySelector('.first-run-setup__choice-error')!;
    expect(err.getAttribute('role')).toBe('alert');
    expect(err.textContent).toContain('Could not save your choice.');
    // the chooser stays up alongside the error (retry, not a silent hand-off)
    expect(container.querySelector('.first-run-chooser')).not.toBeNull();
  });

  it('omits the inline choice error when there is none', () => {
    renderView(baseView({ showChooser: true, choiceError: null }));
    expect(container.querySelector('.first-run-setup__choice-error')).toBeNull();
  });
});

// ---- useFirstRunSetup hook (through a Probe) --------------------------------

let provisioningCb: ((state: ProvisioningState | null) => void) | null = null;
let progressCb: ((event: BootstrapProgressEvent) => void) | null = null;
let errorCb: ((message: string) => void) | null = null;
const repairSetup = vi.fn<() => Promise<RepairSetupResult>>();
const chooseInstallProfile = vi.fn<() => Promise<ChooseInstallProfileResult>>();
const getProvisioningState = vi.fn<() => Promise<ProvisioningState>>();
// WU-1d: the SAME `rpc('providers.firstRun', …)` transport the Settings chooser
// uses — the gate applies the local-vs-cloud AI-routing choice through it.
const providersRpc =
  vi.fn<(method: string, params?: Record<string, unknown>) => Promise<unknown>>();

interface BridgeOpts {
  omitProvisioning?: boolean;
  omitProgress?: boolean;
  omitError?: boolean;
  omitRepair?: boolean;
  omitChoose?: boolean;
  /** WU-1d: omit the `rpc` transport used to apply the routing choice. */
  omitRpc?: boolean;
  /** Include the mount-time `getProvisioningState` query on the bridge. */
  withQuery?: boolean;
}

function installBridge(opts: BridgeOpts = {}): void {
  (window as unknown as { api?: unknown }).api = {
    ...(opts.withQuery ? { getProvisioningState } : {}),
    ...(opts.omitRpc ? {} : { rpc: providersRpc }),
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
    ...(opts.omitChoose ? {} : { chooseInstallProfile }),
  };
}

function Probe(): React.ReactElement {
  const view = useFirstRunSetup();
  return (
    <div
      data-testid="probe"
      data-ready={String(view.ready)}
      data-visible={String(view.visible)}
      data-awaiting={String(view.awaitingProfile)}
      data-phase={view.phase}
      data-pct={String(view.pct)}
      data-line={view.line}
      data-error={view.error ?? ''}
      data-retrying={String(view.retrying)}
      data-online={String(view.online)}
      data-showchooser={String(view.showChooser)}
      data-choosing-routing={String(view.choosingRouting)}
      data-choice-error={view.choiceError ?? ''}
    >
      {view.visible ? <FirstRunSetup view={view} /> : <div data-testid="shell" />}
      <button type="button" data-testid="probe-retry" onClick={view.onRetry}>
        retry
      </button>
      <button
        type="button"
        data-testid="probe-choose"
        onClick={() => view.onChooseProfile('custom', ['ai-director'])}
      >
        choose
      </button>
      <button
        type="button"
        data-testid="probe-route-cloud"
        onClick={() => view.onChooseRouting('bestFreeCloud')}
      >
        route cloud
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

function clickChoose(): void {
  act(() => {
    container.querySelector<HTMLButtonElement>('[data-testid="probe-choose"]')!.click();
  });
}

function clickRouteCloud(): void {
  act(() => {
    container.querySelector<HTMLButtonElement>('[data-testid="probe-route-cloud"]')!.click();
  });
}

/** Drive a first-ever run to the point where the routing chooser step is shown:
 *  the profile picker latches sawProfile, bootstrap spawns, then provisioning
 *  finishes (the sidecar reached 'running') — exactly when providers.firstRun is
 *  reachable. */
function reachRoutingStep(): void {
  pushProvisioning({ active: true, awaitingProfile: true });
  pushProvisioning({ active: true, awaitingProfile: false });
  pushProvisioning({ active: false });
}

describe('useFirstRunSetup', () => {
  beforeEach(() => {
    provisioningCb = null;
    progressCb = null;
    errorCb = null;
    repairSetup.mockReset();
    repairSetup.mockResolvedValue({ ok: true });
    chooseInstallProfile.mockReset();
    chooseInstallProfile.mockResolvedValue({ ok: true });
    getProvisioningState.mockReset();
    getProvisioningState.mockResolvedValue({ active: false });
    providersRpc.mockReset();
    providersRpc.mockResolvedValue({ firstRunChoiceMade: true });
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
      omitChoose: true,
    });
    mountProbe();
    expect(probe().getAttribute('data-visible')).toBe('false');
    clickRetry();
    clickChoose();
    expect(repairSetup).not.toHaveBeenCalled();
    expect(chooseInstallProfile).not.toHaveBeenCalled();
  });

  // ---- WU-1c: awaiting-profile state + choose wiring ------------------------

  it('shows the picker when provisioning arrives awaitingProfile, and hides it once bootstrap spawns', () => {
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    expect(probe().getAttribute('data-awaiting')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('true');
    expect(container.querySelector('.profile-picker')).not.toBeNull();
    // The choose -> spawn transition arrives as active:true, awaitingProfile:false.
    pushProvisioning({ active: true, awaitingProfile: false });
    expect(probe().getAttribute('data-awaiting')).toBe('false');
    expect(container.querySelector('.profile-picker')).toBeNull();
    expect(container.querySelector('.first-run-setup__progress')).not.toBeNull();
  });

  it('reads awaitingProfile from the mount-time query (first frame of a first-ever run)', async () => {
    getProvisioningState.mockResolvedValueOnce({ active: true, awaitingProfile: true });
    installBridge({ withQuery: true });
    mountProbe();
    await act(async () => {
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-awaiting')).toBe('true');
    expect(container.querySelector('.profile-picker')).not.toBeNull();
  });

  it('choosing a profile invokes chooseInstallProfile with the profile + bundles', () => {
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    clickChoose();
    expect(chooseInstallProfile).toHaveBeenCalledTimes(1);
    expect(chooseInstallProfile).toHaveBeenCalledWith('custom', ['ai-director']);
  });

  it('surfaces a LOUD reason when the chosen profile is rejected (no silent stall)', async () => {
    chooseInstallProfile.mockResolvedValueOnce({ ok: false, reason: 'Invalid install profile: x' });
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="probe-choose"]')!.click();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-error')).toBe('Invalid install profile: x');
    expect(container.querySelector('.first-run-setup__error')).not.toBeNull();
  });

  it('does not set an error when the choice is accepted (ok:true)', async () => {
    chooseInstallProfile.mockResolvedValueOnce({ ok: true });
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="probe-choose"]')!.click();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-error')).toBe('');
  });

  it('does not set an error when a rejected choice carries no reason', async () => {
    chooseInstallProfile.mockResolvedValueOnce({ ok: false });
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="probe-choose"]')!.click();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-error')).toBe('');
  });

  it('surfaces a generic error when chooseInstallProfile rejects (never swallowed)', async () => {
    chooseInstallProfile.mockRejectedValueOnce(new Error('ipc down'));
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="probe-choose"]')!.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-error')).toContain('Could not start setup');
  });

  it('choose no-ops when the bridge lacks chooseInstallProfile', () => {
    installBridge({ omitChoose: true });
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    clickChoose();
    expect(chooseInstallProfile).not.toHaveBeenCalled();
  });

  it('choose no-ops when the bridge disappears before the click', () => {
    mountProbe();
    pushProvisioning({ active: true, awaitingProfile: true });
    delete (window as unknown as { api?: unknown }).api;
    clickChoose();
    expect(chooseInstallProfile).not.toHaveBeenCalled();
  });

  // ---- WU-1d: the local-vs-cloud routing chooser step -----------------------

  it('shows the routing chooser as the FINAL step once provisioning finishes on a first-ever run', () => {
    mountProbe();
    // During the picker + the download the chooser is NOT shown.
    pushProvisioning({ active: true, awaitingProfile: true });
    expect(probe().getAttribute('data-showchooser')).toBe('false');
    expect(container.querySelector('.first-run-chooser')).toBeNull();
    pushProvisioning({ active: true, awaitingProfile: false });
    expect(probe().getAttribute('data-showchooser')).toBe('false');
    // The sidecar reached 'running' → provisioning drops → the routing step shows
    // (the sidecar is now up, so providers.firstRun is reachable).
    pushProvisioning({ active: false });
    expect(probe().getAttribute('data-showchooser')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('true');
    expect(container.querySelector('.first-run-chooser')).not.toBeNull();
    expect(container.querySelector('[data-testid="shell"]')).toBeNull();
  });

  it('latches the first-ever run from the mount-time query too (chooser after provisioning)', async () => {
    getProvisioningState.mockResolvedValueOnce({ active: true, awaitingProfile: true });
    installBridge({ withQuery: true });
    mountProbe();
    await act(async () => {
      await Promise.resolve();
    });
    // First frame: the picker. Then provisioning runs and finishes.
    expect(container.querySelector('.profile-picker')).not.toBeNull();
    pushProvisioning({ active: true, awaitingProfile: false });
    pushProvisioning({ active: false });
    expect(probe().getAttribute('data-showchooser')).toBe('true');
  });

  it('a returning user / silent re-bootstrap is NEVER shown the routing chooser', () => {
    mountProbe();
    // A WU-S2 re-bootstrap never sets awaitingProfile, so sawProfile never latches.
    pushProvisioning({ active: true });
    pushProvisioning({ active: false });
    expect(probe().getAttribute('data-showchooser')).toBe('false');
    // It hands straight off to the shell — no double-prompt.
    expect(container.querySelector('.first-run-chooser')).toBeNull();
    expect(container.querySelector('[data-testid="shell"]')).not.toBeNull();
  });

  it('applies the LOCAL (privacy) choice via the SAME providers.firstRun path, then hands off', async () => {
    mountProbe();
    reachRoutingStep();
    // Picking the recommended local option applies it via providers.firstRun.
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-choice="privacy"]')!.click();
      await Promise.resolve();
    });
    expect(providersRpc).toHaveBeenCalledWith('providers.firstRun', { choice: 'privacy' });
    // On success the step drops and the gate hands off to the shell.
    expect(probe().getAttribute('data-showchooser')).toBe('false');
    expect(probe().getAttribute('data-visible')).toBe('false');
    expect(container.querySelector('[data-testid="shell"]')).not.toBeNull();
  });

  it('applies the opt-in CLOUD choice via providers.firstRun', async () => {
    mountProbe();
    reachRoutingStep();
    await act(async () => {
      clickRouteCloud();
      await Promise.resolve();
    });
    expect(providersRpc).toHaveBeenCalledWith('providers.firstRun', { choice: 'bestFreeCloud' });
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('shows a busy in-flight state while the routing choice is applied', async () => {
    let resolveRpc: (v: unknown) => void = () => {};
    providersRpc.mockReturnValueOnce(
      new Promise((res) => {
        resolveRpc = res;
      }),
    );
    mountProbe();
    reachRoutingStep();
    clickRouteCloud();
    // In-flight: busy true, the chooser stays up (buttons disabled).
    expect(probe().getAttribute('data-choosing-routing')).toBe('true');
    expect(container.querySelector<HTMLButtonElement>('[data-choice="privacy"]')!.disabled).toBe(
      true,
    );
    await act(async () => {
      resolveRpc({ firstRunChoiceMade: true });
      await Promise.resolve();
    });
    expect(probe().getAttribute('data-choosing-routing')).toBe('false');
    expect(probe().getAttribute('data-visible')).toBe('false');
  });

  it('surfaces a LOUD inline error and keeps the chooser up when the apply rejects (no silent fallback)', async () => {
    providersRpc.mockRejectedValueOnce(new Error('sidecar rpc failed'));
    mountProbe();
    reachRoutingStep();
    await act(async () => {
      clickRouteCloud();
      await Promise.resolve();
      await Promise.resolve();
    });
    // The choice was NOT recorded — the step stays up with a loud error for retry.
    expect(probe().getAttribute('data-choosing-routing')).toBe('false');
    expect(probe().getAttribute('data-choice-error')).toContain('Could not save your choice');
    expect(probe().getAttribute('data-showchooser')).toBe('true');
    expect(probe().getAttribute('data-visible')).toBe('true');
    expect(container.querySelector('.first-run-setup__choice-error')).not.toBeNull();
  });

  it('routing choice no-ops when the bridge lacks the rpc transport', () => {
    installBridge({ omitRpc: true });
    mountProbe();
    reachRoutingStep();
    clickRouteCloud();
    expect(providersRpc).not.toHaveBeenCalled();
    // Still on the chooser (no crash, no silent hand-off).
    expect(probe().getAttribute('data-showchooser')).toBe('true');
  });

  it('routing choice no-ops when the bridge disappears before the click', () => {
    mountProbe();
    reachRoutingStep();
    delete (window as unknown as { api?: unknown }).api;
    clickRouteCloud();
    expect(providersRpc).not.toHaveBeenCalled();
  });

  it('a bootstrap error takes precedence over the routing chooser (error owns the gate)', () => {
    mountProbe();
    reachRoutingStep();
    expect(probe().getAttribute('data-showchooser')).toBe('true');
    // A late bootstrap error must win: the chooser yields to the actionable body.
    pushError('FAILED:bootstrap late failure | fix: retry');
    expect(probe().getAttribute('data-showchooser')).toBe('false');
    expect(container.querySelector('.first-run-chooser')).toBeNull();
    expect(container.querySelector('.first-run-setup__error')).not.toBeNull();
  });
});
