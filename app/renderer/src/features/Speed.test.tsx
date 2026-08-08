// Speed.test.tsx — tests for the Speed / slow-motion panel.
//
// The panel drives the one RPC this lane added:
//   speed.retime({videoId, factor}) -> {jobId} -> job.done {path, factor,
//                                                sourceDurationSec, durationSec}
// A job, so the terminal payload arrives via the job.done notification; a fake
// `api` bridge is injected through the `api?` prop, and the click/await idiom is
// Refine.test.tsx's (await act + a microtask turn, then fire job.done in a
// second act) — the pattern already proven against this bridge shape.
//
// The panel exists because the re-time ENGINE was reachable only through an
// LLM-planned Director op. These tests pin that a user can now pick a speed and
// press a button instead.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Speed, { DEFAULT_SPEED_FACTOR, speedResultPath } from './Speed';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';
import { SPEED_MAX, SPEED_MIN, SPEED_PRESETS } from '../lib/speedPresets';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(retimeResult: unknown = { jobId: 'job-s' }): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'speed.retime') return retimeResult as T;
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb) => {
      progressCbs.push(cb);
      return () => {
        progressCbs = progressCbs.filter((c) => c !== cb);
      };
    },
    onJobDone: (cb) => {
      doneCbs.push(cb);
      return () => {
        doneCbs = doneCbs.filter((c) => c !== cb);
      };
    },
  };
  return {
    api,
    calls,
    fireProgress: (ev) => progressCbs.slice().forEach((cb) => cb(ev)),
    fireDone: (ev) => doneCbs.slice().forEach((cb) => cb(ev)),
  };
}

describe('speedResultPath', () => {
  it('pulls the output path from a job.done result', () => {
    expect(speedResultPath({ path: '/x/clip.speed-2p00x.mp4' })).toBe('/x/clip.speed-2p00x.mp4');
  });
  it('null when absent or the wrong shape', () => {
    expect(speedResultPath({})).toBeNull();
    expect(speedResultPath(null)).toBeNull();
    expect(speedResultPath({ path: 7 })).toBeNull();
  });
});

describe('Speed panel', () => {
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
    delete (globalThis as { api?: unknown }).api;
    vi.restoreAllMocks();
  });

  async function mount(props: Record<string, unknown>): Promise<void> {
    await act(async () => {
      root.render(<Speed videoId="v1" {...props} />);
    });
  }

  const q = (sel: string): HTMLElement | null => container.querySelector(sel);

  async function clickAction(action: string): Promise<void> {
    await act(async () => {
      (container.querySelector(`button[data-action="${action}"]`) as HTMLButtonElement).click();
      await Promise.resolve();
    });
  }

  async function clickPreset(id: string): Promise<void> {
    await act(async () => {
      (container.querySelector(`button[data-preset="${id}"]`) as HTMLButtonElement).click();
      await Promise.resolve();
    });
  }

  async function setCustom(value: string): Promise<void> {
    const input = q('[data-tune="factor"]') as HTMLInputElement;
    await act(async () => {
      // React tracks the last value on the DOM node, so the NATIVE setter + an
      // input event is what makes a controlled <input> see a real change in jsdom.
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set;
      setter?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await Promise.resolve();
    });
  }

  it('offers one button per preset, including slow motion and 1.5x', async () => {
    await mount({ api: makeFakeApi().api });
    const buttons = [...container.querySelectorAll('[data-preset]')];
    expect(buttons).toHaveLength(SPEED_PRESETS.length);
    const labels = buttons.map((b) => b.textContent);
    expect(labels).toContain('0.5x slow motion');
    expect(labels).toContain('1.5x faster');
  });

  it('marks the active preset pressed, and moves it on click', async () => {
    await mount({ api: makeFakeApi().api });
    expect(q('[data-preset="faster-2"]')?.getAttribute('aria-pressed')).toBe('true');
    await clickPreset('slowmo-half');
    expect(q('[data-preset="slowmo-half"]')?.getAttribute('aria-pressed')).toBe('true');
    expect(q('[data-preset="faster-2"]')?.getAttribute('aria-pressed')).toBe('false');
  });

  it('predicts the new duration before anything is rendered', async () => {
    await mount({ api: makeFakeApi().api, sourceDurationSec: 120 });
    // Default 2x on a 2:00 source -> 1:00.
    expect(q('[data-field="sourceDuration"]')?.textContent).toBe('2:00');
    expect(q('[data-field="newDuration"]')?.textContent).toBe('1:00');
    await clickPreset('slowmo-half');
    expect(q('[data-field="newDuration"]')?.textContent).toBe('4:00');
  });

  it('shows a dash for both durations when the source length is unknown', async () => {
    await mount({ api: makeFakeApi().api });
    expect(q('[data-field="sourceDuration"]')?.textContent).toBe('—');
    expect(q('[data-field="newDuration"]')?.textContent).toBe('—');
  });

  it('sends speed.retime with the chosen factor', async () => {
    const fake = makeFakeApi();
    await mount({ api: fake.api, sourceDurationSec: 12 });
    await clickPreset('slowmo-half');
    await clickAction('apply');
    expect(fake.calls.find((c) => c.method === 'speed.retime')?.params).toEqual({
      videoId: 'v1',
      factor: 0.5,
    });
  });

  it('streams progress for its own job only, then shows the produced file', async () => {
    const fake = makeFakeApi();
    await mount({ api: fake.api, sourceDurationSec: 12 });
    await clickAction('apply');
    await act(async () => {
      fake.fireProgress({ jobId: 'someone-else', pct: 99, message: 'not mine' });
    });
    expect(q('.progress-pct')?.textContent).toBe('0%');
    await act(async () => {
      fake.fireProgress({ jobId: 'job-s', pct: 40, message: 'retiming' });
    });
    expect(q('.progress-pct')?.textContent).toBe('40%');
    expect(q('.progress-message')?.textContent).toContain('retiming');
    await act(async () => {
      fake.fireDone({ jobId: 'job-s', result: { path: '/out/in.speed-2p00x.mp4' } });
    });
    expect(q('[data-section="result"]')?.textContent).toContain('/out/in.speed-2p00x.mp4');
  });

  it('cancels the running job', async () => {
    const fake = makeFakeApi();
    await mount({ api: fake.api });
    await clickAction('apply');
    await clickAction('cancel');
    expect(fake.calls.some((c) => c.method === 'job.cancel')).toBe(true);
    expect(q('.progress-message')?.textContent).toContain('Cancelling');
    await act(async () => {
      fake.fireDone({ jobId: 'job-s', result: { path: '/out/a.mp4' } });
    });
  });

  it('a cancel that throws is swallowed (best-effort, no alert)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      async (method: string, params?: Record<string, unknown>) => {
        fake.calls.push({ method, params });
        if (method === 'job.cancel') throw new Error('gone');
        return { jobId: 'job-s' };
      },
    );
    await mount({ api: fake.api });
    await clickAction('apply');
    await clickAction('cancel');
    expect(q('[role="alert"]')).toBeNull();
    await act(async () => {
      fake.fireDone({ jobId: 'job-s', result: { path: '/out/a.mp4' } });
    });
  });

  it('surfaces an rpc rejection as an alert', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('ffmpeg is missing'));
    await mount({ api: fake.api });
    await clickAction('apply');
    expect(q('[role="alert"]')?.textContent).toContain('ffmpeg is missing');
  });

  it('surfaces a non-Error rejection via String(err)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('plain speed error');
    await mount({ api: fake.api });
    await clickAction('apply');
    expect(q('[role="alert"]')?.textContent).toContain('plain speed error');
  });

  it('surfaces a job.done error payload', async () => {
    const fake = makeFakeApi();
    await mount({ api: fake.api });
    await clickAction('apply');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-s',
        result: { error: { message: 're-time failed (ffmpeg exit 3)', type: 'InternalError' } },
      });
    });
    expect(q('[role="alert"]')?.textContent).toContain('re-time failed (ffmpeg exit 3)');
  });

  it('a response with no jobId settles without a result and without an error', async () => {
    const fake = makeFakeApi({});
    await mount({ api: fake.api });
    await clickAction('apply');
    expect(q('[data-section="result"]')).toBeNull();
    expect(q('[role="alert"]')).toBeNull();
  });

  it('a job.done carrying no path leaves the panel result-free', async () => {
    const fake = makeFakeApi();
    await mount({ api: fake.api });
    await clickAction('apply');
    await act(async () => {
      fake.fireDone({ jobId: 'job-s', result: undefined });
    });
    expect(q('[data-section="result"]')).toBeNull();
  });

  it('the custom factor input clamps to the accepted window', async () => {
    await mount({ api: makeFakeApi().api });
    await setCustom('999');
    expect((q('[data-tune="factor"]') as HTMLInputElement).value).toBe(String(SPEED_MAX));
    await setCustom('0.0001');
    expect((q('[data-tune="factor"]') as HTMLInputElement).value).toBe(String(SPEED_MIN));
  });

  it('a blank custom factor falls back to 1x and disables Apply (the no-op guard)', async () => {
    await mount({ api: makeFakeApi().api });
    await setCustom('');
    expect((q('[data-action="apply"]') as HTMLButtonElement).disabled).toBe(true);
    expect(q('[data-field="noop"]')).not.toBeNull();
  });

  it('Apply is enabled at a sendable factor', async () => {
    await mount({ api: makeFakeApi().api });
    expect((q('[data-action="apply"]') as HTMLButtonElement).disabled).toBe(false);
    expect(q('[data-field="noop"]')).toBeNull();
  });

  it('defaults to a real speed-up, not a no-op', () => {
    expect(DEFAULT_SPEED_FACTOR).not.toBe(1);
    expect(SPEED_PRESETS.some((p) => p.factor === DEFAULT_SPEED_FACTOR)).toBe(true);
  });

  it('falls back to the global bridge when no api prop is given', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;
    await mount({});
    await clickAction('apply');
    expect(fake.calls[0]?.method).toBe('speed.retime');
  });

  it('says plainly that the speed is CONSTANT, so no one reads it as a ramp', async () => {
    await mount({ api: makeFakeApi().api });
    expect(container.textContent?.toLowerCase()).toContain('constant');
  });
});
