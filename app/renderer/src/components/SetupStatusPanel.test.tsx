// SetupStatusPanel.test.tsx — the first-run self-diagnostic surface (WU-2).
//
// Consumes `system.selfTest` and renders a clear pass/fail setup-status panel:
// an overall banner (ready vs blocked), one row per check with its detail + fix
// hint, a re-run control, and loud, never-silent failure copy. Pins the §WU-2
// acceptance: an all-green report reads "ready"; a missing required dep surfaces
// a problem + fix hint; a load failure degrades to a visible alert (never crash).
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SetupStatusPanel } from './SetupStatusPanel';
import type { SelfTestCheck, SelfTestReport } from '../lib/rpc';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

/** A typed client stub exposing only `system.selfTest`. */
function makeClient(selfTest: () => Promise<SelfTestReport>) {
  return { system: { selfTest: vi.fn(selfTest) } } as unknown as Parameters<
    typeof SetupStatusPanel
  >[0]['rpcClient'];
}

async function flush(turns = 4): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) await Promise.resolve();
  });
}

function check(over: Partial<SelfTestCheck> = {}): SelfTestCheck {
  return {
    id: 'data',
    label: 'Writable data folder',
    ok: true,
    required: true,
    detail: 'Data folder is writable.',
    fixHint: '',
    ...over,
  };
}

const OK_REPORT: SelfTestReport = {
  ok: true,
  checks: [check(), check({ id: 'device', label: 'Device probe', required: false })],
  problems: [],
};

async function mount(
  report: () => Promise<SelfTestReport>,
): Promise<ReturnType<typeof makeClient>> {
  const rpcClient = makeClient(report);
  await act(async () => {
    root.render(<SetupStatusPanel rpcClient={rpcClient} />);
  });
  await flush();
  return rpcClient;
}

describe('<SetupStatusPanel /> — WU-2 first-run diagnostic', () => {
  it('shows the loading state while the diagnostic is in flight', async () => {
    let resolve: (v: SelfTestReport) => void = () => {};
    const rpcClient = makeClient(() => new Promise<SelfTestReport>((res) => (resolve = res)));
    await act(async () => {
      root.render(<SetupStatusPanel rpcClient={rpcClient} />);
    });
    expect(container.querySelector('.setup-status__loading')).not.toBeNull();
    // The re-run control is disabled while a check is in flight.
    expect(container.querySelector<HTMLButtonElement>('[data-action="rerun"]')!.disabled).toBe(
      true,
    );

    await act(async () => {
      resolve(OK_REPORT);
    });
    await flush();
    expect(container.querySelector('.setup-status__loading')).toBeNull();
  });

  it('renders the all-green ready banner when every check passes', async () => {
    await mount(() => Promise.resolve(OK_REPORT));
    const summary = container.querySelector('.setup-status__summary');
    expect(summary?.classList.contains('is-ok')).toBe(true);
    expect(summary?.getAttribute('role')).toBe('status');
    expect(summary?.textContent).toContain('ready');
    // Two check rows, both marked pass.
    const rows = container.querySelectorAll('.setup-status__check');
    expect(rows.length).toBe(2);
    expect(container.querySelectorAll('[data-state="ok"]').length).toBe(2);
    // No fix-hint lines on a clean report.
    expect(container.querySelectorAll('[data-role="fix-hint"]').length).toBe(0);
  });

  it('reports a missing required dependency with a fix hint, and a non-required warning', async () => {
    const report: SelfTestReport = {
      ok: false,
      checks: [
        check(),
        check({
          id: 'device',
          label: 'Device probe',
          required: false,
          ok: false,
          detail: 'probe failed',
          fixHint: 'update driver',
        }),
        check({
          id: 'cv2',
          label: 'Reframe engine (OpenCV + MediaPipe)',
          required: true,
          ok: false,
          detail: 'missing: cv2',
          fixHint: 'Reframe needs OpenCV — reinstall the app',
        }),
        // A required failure WITHOUT a fix hint exercises the no-hint branch.
        check({
          id: 'asr',
          label: 'Whisper',
          required: true,
          ok: false,
          detail: 'missing: faster_whisper',
          fixHint: '',
        }),
      ],
      problems: ['x'],
    };
    await mount(() => Promise.resolve(report));

    const summary = container.querySelector('.setup-status__summary');
    expect(summary?.classList.contains('is-blocked')).toBe(true);
    expect(summary?.getAttribute('role')).toBe('alert');

    const cv2Row = container.querySelector('[data-check-id="cv2"]')!;
    expect(cv2Row.classList.contains('is-failed')).toBe(true);
    expect(cv2Row.querySelector('[data-state="failed"]')?.textContent).toBe('Problem');
    expect(cv2Row.querySelector('[data-role="fix-hint"]')?.textContent).toContain('OpenCV');

    // Non-required device failure reads as a Warning, not a blocking Problem.
    expect(
      container.querySelector('[data-check-id="device"] [data-state="failed"]')?.textContent,
    ).toBe('Warning');

    // The required no-hint failure renders no fix line but still shows its detail.
    const asrRow = container.querySelector('[data-check-id="asr"]')!;
    expect(asrRow.querySelector('[data-role="fix-hint"]')).toBeNull();
    expect(asrRow.querySelector('.setup-status__check-detail')?.textContent).toContain(
      'faster_whisper',
    );
  });

  it('re-runs the diagnostic when the re-run button is clicked', async () => {
    const reports = [
      Promise.resolve<SelfTestReport>({
        ok: false,
        checks: [check({ ok: false, fixHint: 'fix it' })],
        problems: ['x'],
      }),
      Promise.resolve<SelfTestReport>(OK_REPORT),
    ];
    let call = 0;
    const rpcClient = makeClient(() => reports[call++]);
    await act(async () => {
      root.render(<SetupStatusPanel rpcClient={rpcClient} />);
    });
    await flush();
    expect(
      container.querySelector('.setup-status__summary')?.classList.contains('is-blocked'),
    ).toBe(true);

    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-action="rerun"]')!.click();
    });
    await flush();
    expect(rpcClient!.system.selfTest).toHaveBeenCalledTimes(2);
    expect(container.querySelector('.setup-status__summary')?.classList.contains('is-ok')).toBe(
      true,
    );
  });

  it('surfaces a load error (Error instance) without crashing', async () => {
    await mount(() => Promise.reject(new Error('sidecar down')));
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('sidecar down');
    expect(container.querySelector('.setup-status__summary')).toBeNull();
  });

  it('stringifies a non-Error load rejection', async () => {
    await mount(() => Promise.reject('plain failure'));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain failure');
  });

  it('shows a neutral empty state when the diagnostic resolves to nothing', async () => {
    await mount(() => Promise.resolve(undefined as unknown as SelfTestReport));
    expect(container.querySelector('.setup-status__empty')).not.toBeNull();
    expect(container.querySelector('.setup-status__summary')).toBeNull();
  });

  it('renders a custom title when provided', async () => {
    const rpcClient = makeClient(() => Promise.resolve(OK_REPORT));
    await act(async () => {
      root.render(<SetupStatusPanel rpcClient={rpcClient} title="First-run check" />);
    });
    await flush();
    expect(container.querySelector('.setup-status__title')?.textContent).toBe('First-run check');
  });

  it('ignores a late resolve after unmount (no state update warning)', async () => {
    let resolve: (v: SelfTestReport) => void = () => {};
    const rpcClient = makeClient(() => new Promise<SelfTestReport>((res) => (resolve = res)));
    await act(async () => {
      root.render(<SetupStatusPanel rpcClient={rpcClient} />);
    });
    await act(async () => {
      root.unmount();
    });
    await act(async () => {
      resolve(OK_REPORT);
    });
    expect(container.querySelector('.setup-status__summary')).toBeNull();
    root = createRoot(container);
  });
});
