// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const rpcMock = vi.fn();
let progressCb: ((e: { jobId: string; pct: number; message: string }) => void) | null = null;

vi.mock('./api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: (cb: (e: { jobId: string; pct: number; message: string }) => void) => {
    progressCb = cb;
    return () => {
      progressCb = null;
    };
  },
  hasApi: () => true,
}));

import {
  useJob,
  featureLabel,
  extractJobError,
  registerJobRetry,
  resolveJobRetry,
  type UseJobOptions,
} from './useJob';
import { ToastProvider } from './toast/ToastProvider';
import { ToastHost } from './toast/ToastHost';

// The job.done relay is read straight off the window.api bridge (the frozen
// §1 surface + the preload's onJobDone) — install a capturing fake.
type DoneCb = (e: { jobId: string; result?: unknown }) => void;
let doneCb: DoneCb | null = null;

function installBridge(): void {
  (window as unknown as { api?: unknown }).api = {
    onJobDone: (cb: DoneCb) => {
      doneCb = cb;
      return () => {
        doneCb = null;
      };
    },
  };
}

// A tiny harness component that exposes the hook's API to the test.
let api: ReturnType<typeof useJob> | null = null;
function Harness(): React.ReactElement {
  api = useJob();
  return React.createElement(
    'div',
    null,
    `${api.state.running}|${api.state.jobId ?? ''}|${api.state.pct}|${api.state.message}|${api.state.error ?? ''}`,
  );
}

// Harness variant that takes UseJobOptions (for the error-surface tests).
function OptionsHarness({ options }: { options?: UseJobOptions }): React.ReactElement {
  api = useJob(options);
  return React.createElement(
    'div',
    null,
    `${api.state.running}|${api.state.jobId ?? ''}|${api.state.pct}|${api.state.message}|${api.state.error ?? ''}`,
  );
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  progressCb = null;
  doneCb = null;
  api = null;
  installBridge();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  registerJobRetry(null);
  delete (window as unknown as { api?: unknown }).api;
  doneCb = null;
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

/** Mount the options-harness wrapped in the real toast provider + host. */
async function renderWithToasts(options?: UseJobOptions): Promise<void> {
  await act(async () => {
    root.render(
      React.createElement(
        ToastProvider,
        null,
        React.createElement(OptionsHarness, { options }),
        React.createElement(ToastHost, null),
      ),
    );
  });
}

function bodyToasts(): Element[] {
  return Array.from(document.body.querySelectorAll('.toast'));
}

describe('useJob', () => {
  it('starts a job and tracks its progress notifications', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'j1' });
    await act(async () => {
      root.render(React.createElement(Harness));
    });

    await act(async () => {
      await api!.start('transcribe.start', { videoId: 'v1' });
    });
    await flush();

    expect(rpcMock).toHaveBeenCalledWith('transcribe.start', { videoId: 'v1' });
    expect(api!.state.jobId).toBe('j1');
    expect(api!.state.running).toBe(true);

    // A progress notification for the active job updates state.
    await act(async () => {
      progressCb!({ jobId: 'j1', pct: 40, message: 'working' });
    });
    expect(api!.state.pct).toBe(40);
    expect(api!.state.message).toBe('working');

    // A notification for a different job is ignored.
    await act(async () => {
      progressCb!({ jobId: 'other', pct: 99, message: 'noise' });
    });
    expect(api!.state.pct).toBe(40);
  });

  it('cancel calls job.cancel and stops running', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'j2' });
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });

    rpcMock.mockResolvedValueOnce({ ok: true });
    await act(async () => {
      await api!.cancel();
    });
    expect(rpcMock).toHaveBeenLastCalledWith('job.cancel', { jobId: 'j2' });
    expect(api!.state.running).toBe(false);
  });

  it('start tolerates a result without a jobId (useJob.ts:265)', async () => {
    rpcMock.mockResolvedValueOnce({ ok: true }); // no jobId field
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await flush();
    // The `?? null` fallback keeps jobId null while still marking it running.
    expect(api!.state.jobId).toBeNull();
    expect(api!.state.running).toBe(true);
  });

  it('start stringifies a non-Error rejection (useJob.ts:270-273 else)', async () => {
    rpcMock.mockRejectedValueOnce('string-only failure');
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' }).catch(() => {});
    });
    expect(api!.state.error).toBe('string-only failure');
    expect(api!.state.running).toBe(false);
  });

  it('cancel is a no-op when there is no active job (useJob.ts:288)', async () => {
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    // No start() yet -> activeJobId is null -> cancel returns before any rpc.
    await act(async () => {
      await api!.cancel();
    });
    expect(rpcMock).not.toHaveBeenCalled();
  });

  it('works without the onJobDone bridge (useJob.ts:67 no-op subscription)', async () => {
    // Replace the bridge with one that has NO onJobDone -> onJobDoneBridge takes
    // its early no-op return; the hook still starts/tracks jobs via job.progress.
    (window as unknown as { api?: unknown }).api = {};
    rpcMock.mockResolvedValueOnce({ jobId: 'no-bridge' });
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await flush();
    expect(api!.state.jobId).toBe('no-bridge');
    await act(async () => {
      progressCb!({ jobId: 'no-bridge', pct: 30, message: 'go' });
    });
    expect(api!.state.pct).toBe(30);
  });

  it('finish marks the job complete at 100%', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'j3' });
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await act(async () => {
      await api!.start('shortmaker.select', { videoId: 'v1' });
    });
    act(() => api!.finish());
    expect(api!.state.running).toBe(false);
    expect(api!.state.pct).toBe(100);
  });

  it('records an error when start rejects', async () => {
    rpcMock.mockRejectedValueOnce(new Error('boom'));
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await act(async () => {
      await api!.start('transcribe.start', { videoId: 'v1' }).catch(() => {});
    });
    expect(api!.state.error).toBe('boom');
    expect(api!.state.running).toBe(false);
  });
});

describe('useJob × job.done error surface (P2 U3)', () => {
  it('surfaces a job.done error payload as an error toast with the feature label and fires onError', async () => {
    const onError = vi.fn();
    rpcMock.mockResolvedValueOnce({ jobId: 'j9' });
    await renderWithToasts({ onError });

    await act(async () => {
      await api!.start('transcribe.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({
        jobId: 'j9',
        result: { error: { message: 'whisper exploded', type: 'RuntimeError' } },
      });
    });

    expect(api!.state.error).toBe('whisper exploded');
    expect(api!.state.running).toBe(false);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: 'j9',
        method: 'transcribe.start',
        feature: 'transcribe',
        label: 'Transcribe',
        message: 'whisper exploded',
        type: 'RuntimeError',
      }),
    );

    const toastEl = document.body.querySelector('.toast--error');
    expect(toastEl).not.toBeNull();
    expect(toastEl!.getAttribute('role')).toBe('alert');
    expect(toastEl!.textContent).toContain('Transcribe failed: whisper exploded');
    // No retry callable registered/detected -> no Retry action button.
    expect(document.body.querySelector('.toast__action')).toBeNull();
  });

  it('a job.done success payload finishes the active job (no toast)', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'j5' });
    await renderWithToasts();
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({ jobId: 'j5', result: { path: 'out.mp4' } });
    });
    expect(api!.state.running).toBe(false);
    expect(api!.state.pct).toBe(100);
    expect(api!.state.error).toBeNull();
    expect(bodyToasts()).toHaveLength(0);
  });

  it('ignores job.done notifications for other jobs', async () => {
    const onError = vi.fn();
    rpcMock.mockResolvedValueOnce({ jobId: 'j6' });
    await renderWithToasts({ onError });
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({ jobId: 'other', result: { error: { message: 'nope', type: 'X' } } });
    });
    expect(api!.state.running).toBe(true);
    expect(api!.state.error).toBeNull();
    expect(onError).not.toHaveBeenCalled();
    expect(bodyToasts()).toHaveLength(0);
  });

  it('treats a JobCancelled payload as a quiet finish, not a failure', async () => {
    const onError = vi.fn();
    rpcMock.mockResolvedValueOnce({ jobId: 'j7' });
    await renderWithToasts({ onError });
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({
        jobId: 'j7',
        result: { error: { message: 'j7', type: 'JobCancelled' } },
      });
    });
    expect(api!.state.running).toBe(false);
    expect(api!.state.error).toBeNull();
    expect(onError).not.toHaveBeenCalled();
    expect(bodyToasts()).toHaveLength(0);
  });

  it('an explicit label option overrides the derived feature label', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'j8' });
    await renderWithToasts({ label: 'Proxy build' });
    await act(async () => {
      await api!.start('media.proxy.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({ jobId: 'j8', result: { error: { message: 'no codec', type: 'ValueError' } } });
    });
    const toastEl = document.body.querySelector('.toast--error');
    expect(toastEl).not.toBeNull();
    expect(toastEl!.textContent).toContain('Proxy build failed: no codec');
  });

  it('offers Retry only when a job.retry callable is registered, and re-arms tracking', async () => {
    const retry = vi.fn().mockResolvedValue({ jobId: 'j2' });
    registerJobRetry(retry);
    rpcMock.mockResolvedValueOnce({ jobId: 'j1' });
    await renderWithToasts();
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({
        jobId: 'j1',
        result: { error: { message: 'ffmpeg exited 1', type: 'CalledProcessError' } },
      });
    });

    const btn = document.body.querySelector('.toast__action') as HTMLButtonElement | null;
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toBe('Retry');

    await act(async () => {
      btn!.click();
    });
    await flush();

    expect(retry).toHaveBeenCalledWith('j1');
    // The action consumed (dismissed) the toast and re-armed job tracking.
    expect(bodyToasts()).toHaveLength(0);
    expect(api!.state.running).toBe(true);
    expect(api!.state.jobId).toBe('j2');

    await act(async () => {
      progressCb!({ jobId: 'j2', pct: 25, message: 'retrying' });
    });
    expect(api!.state.pct).toBe(25);
  });

  it('a Retry that resolves without a jobId leaves jobId null (useJob.ts:216)', async () => {
    const retry = vi.fn().mockResolvedValue({ ok: true }); // no jobId field
    registerJobRetry(retry);
    rpcMock.mockResolvedValueOnce({ jobId: 'j1' });
    await renderWithToasts();
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({ jobId: 'j1', result: { error: { message: 'boom', type: 'X' } } });
    });
    const btn = document.body.querySelector('.toast__action') as HTMLButtonElement | null;
    await act(async () => {
      btn!.click();
    });
    await flush();
    expect(retry).toHaveBeenCalledWith('j1');
    expect(api!.state.running).toBe(true);
    expect(api!.state.jobId).toBeNull(); // `?? null` fallback path
  });

  it('a rejected Retry surfaces the error on state (useJob.ts:220-222)', async () => {
    const retry = vi.fn().mockRejectedValue(new Error('retry sidecar gone'));
    registerJobRetry(retry);
    rpcMock.mockResolvedValueOnce({ jobId: 'j1' });
    await renderWithToasts();
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({
        jobId: 'j1',
        result: { error: { message: 'ffmpeg exited 1', type: 'CalledProcessError' } },
      });
    });

    const btn = document.body.querySelector('.toast__action') as HTMLButtonElement | null;
    expect(btn).not.toBeNull();
    await act(async () => {
      btn!.click();
    });
    await flush();

    expect(retry).toHaveBeenCalledWith('j1');
    // The .catch() records the failure and stops running.
    expect(api!.state.running).toBe(false);
    expect(api!.state.error).toBe('retry sidecar gone');
  });

  it('a rejected Retry stringifies a non-Error rejection (useJob.ts:221 else)', async () => {
    const retry = vi.fn().mockRejectedValue('plain string boom');
    registerJobRetry(retry);
    rpcMock.mockResolvedValueOnce({ jobId: 'j1' });
    await renderWithToasts();
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await act(async () => {
      doneCb!({ jobId: 'j1', result: { error: { message: 'x', type: 'Y' } } });
    });

    const btn = document.body.querySelector('.toast__action') as HTMLButtonElement | null;
    await act(async () => {
      btn!.click();
    });
    await flush();
    expect(api!.state.error).toBe('plain string boom');
  });

  it('reset() clears state back to idle and stops tracking (useJob.ts:297-299)', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'j-reset' });
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await act(async () => {
      await api!.start('convert.start', { videoId: 'v1' });
    });
    await flush();
    expect(api!.state.running).toBe(true);
    expect(api!.state.jobId).toBe('j-reset');

    act(() => api!.reset());
    expect(api!.state.running).toBe(false);
    expect(api!.state.jobId).toBeNull();
    expect(api!.state.pct).toBe(0);
    expect(api!.state.error).toBeNull();

    // After reset, a progress event for the old job is ignored (tracking cleared).
    await act(async () => {
      progressCb!({ jobId: 'j-reset', pct: 80, message: 'stale' });
    });
    expect(api!.state.pct).toBe(0);
  });

  it('a start() rejection also flows through onError (with the feature label)', async () => {
    const onError = vi.fn();
    rpcMock.mockRejectedValueOnce(new Error('sidecar down'));
    await renderWithToasts({ onError });
    await act(async () => {
      await api!.start('shortmaker.select', { videoId: 'v1' }).catch(() => {});
    });
    expect(api!.state.error).toBe('sidecar down');
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        jobId: null,
        feature: 'shortmaker',
        label: 'Short-maker',
        message: 'sidecar down',
      }),
    );
    // No jobId to retry -> never offers a Retry action, even if one is registered.
    const toastEl = document.body.querySelector('.toast--error');
    expect(toastEl).not.toBeNull();
    expect(toastEl!.textContent).toContain('Short-maker failed: sidecar down');
    expect(document.body.querySelector('.toast__action')).toBeNull();
  });
});

describe('useJob helpers (pure)', () => {
  it('featureLabel derives the feature + label from the rpc method', () => {
    expect(featureLabel('transcribe.start')).toEqual({
      feature: 'transcribe',
      label: 'Transcribe',
    });
    expect(featureLabel('shortmaker.export')).toEqual({
      feature: 'shortmaker',
      label: 'Short-maker',
    });
    expect(featureLabel('tts.dub.start')).toEqual({ feature: 'tts', label: 'Dub' });
    expect(featureLabel(null)).toEqual({ feature: 'job', label: 'Job' });
    expect(featureLabel('')).toEqual({ feature: 'job', label: 'Job' });
    // Unknown features fall back to capitalization (forward-compatible).
    expect(featureLabel('frobnicate.run')).toEqual({
      feature: 'frobnicate',
      label: 'Frobnicate',
    });
  });

  it('extractJobError pulls the A3 payload and rejects malformed shapes', () => {
    expect(extractJobError({ error: { message: 'x', type: 'RuntimeError' } })).toEqual({
      message: 'x',
      type: 'RuntimeError',
    });
    expect(extractJobError({ error: { message: 'x' } })).toEqual({
      message: 'x',
      type: undefined,
    });
    expect(extractJobError({ transcript: {} })).toBeNull();
    expect(extractJobError(null)).toBeNull();
    expect(extractJobError(undefined)).toBeNull();
    expect(extractJobError('error')).toBeNull();
    expect(extractJobError({ error: 'nope' })).toBeNull();
    expect(extractJobError({ error: { message: 42 } })).toBeNull();
  });

  it('resolveJobRetry returns null when nothing is registered or on the bridge', () => {
    expect(resolveJobRetry()).toBeNull();
  });

  it('resolveJobRetry prefers the registered callable, then a bridge-level one', async () => {
    const fn = vi.fn().mockResolvedValue({ jobId: 'r1' });
    registerJobRetry(fn);
    expect(resolveJobRetry()).toBe(fn);

    registerJobRetry(null);
    (window as unknown as { api?: unknown }).api = { jobRetry: fn };
    const resolved = resolveJobRetry();
    expect(resolved).not.toBeNull();
    await resolved!('j1');
    expect(fn).toHaveBeenCalledWith('j1');
  });
});
