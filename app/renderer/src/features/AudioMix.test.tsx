// AudioMix.test.tsx — tests for the audio-mixer panel (v1.5 audiomix-ui).
//
// Strategy mirrors Dub.test.tsx: pure helpers tested with no render; component
// tests use React 18's react-dom/client + act under jsdom with the RPC bridge
// mocked (a fake `MediaStudioApi`) — no real sidecar, no ffmpeg, no network.
//
// The LUFS/duck numbers this panel shows are mirrored from the sidecar engine;
// that mirror is gated separately by AudioMix.conformance.test.ts, which parses
// the real `sidecar/media_studio/features/audiomix.py`.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import AudioMix, {
  DEFAULT_BG_GAIN_DB,
  DEFAULT_DUCK_RATIO,
  DEFAULT_DUCK_THRESHOLD,
  DEFAULT_TARGET_ID,
  LOUDNESS_TARGETS,
  buildMergeParams,
  buildNormalizeParams,
  formatLufs,
  numOr,
  targetFor,
  targetOptionLabel,
} from './AudioMix';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

// ---------------------------------------------------------------------------
// pure helpers
// ---------------------------------------------------------------------------

describe('LOUDNESS_TARGETS', () => {
  it('offers the documented social / broadcast anchors', () => {
    const byId = Object.fromEntries(LOUDNESS_TARGETS.map((t) => [t.id, t.lufs]));
    expect(byId.tiktok).toBe(-14);
    expect(byId.reels).toBe(-14);
    expect(byId.shorts).toBe(-14);
    expect(byId.youtube).toBe(-14);
    expect(byId.ebu).toBe(-23);
    expect(byId.atsc).toBe(-24);
  });

  it('defaults to a target that exists in the list', () => {
    expect(LOUDNESS_TARGETS.some((t) => t.id === DEFAULT_TARGET_ID)).toBe(true);
  });
});

describe('targetFor', () => {
  it('resolves a known platform id', () => {
    expect(targetFor('ebu').lufs).toBe(-23);
  });

  it('falls back to the first row for an unknown id (the select can only hold known ids)', () => {
    expect(targetFor('not-a-platform')).toBe(LOUDNESS_TARGETS[0]);
  });
});

describe('formatLufs', () => {
  it('renders an integer target without a trailing zero', () => {
    expect(formatLufs(-14)).toBe('-14 LUFS');
    expect(formatLufs(-23)).toBe('-23 LUFS');
  });
});

describe('targetOptionLabel', () => {
  it('pairs the human label with the number that will be applied', () => {
    expect(targetOptionLabel({ id: 'atsc', label: 'US broadcast', lufs: -24 })).toBe(
      'US broadcast — -24 LUFS',
    );
  });
});

describe('numOr', () => {
  it('parses a real number, including a negative decimal', () => {
    expect(numOr('-12.5', -10)).toBe(-12.5);
  });

  it('keeps a legitimate zero (0 is a value, not "empty")', () => {
    expect(numOr('0', -10)).toBe(0);
  });

  it('falls back on a blank / whitespace field', () => {
    expect(numOr('', -10)).toBe(-10);
    expect(numOr('   ', -10)).toBe(-10);
  });

  it('falls back on a non-numeric entry rather than sending NaN', () => {
    expect(numOr('loud', -10)).toBe(-10);
  });
});

describe('buildMergeParams', () => {
  it('builds the frozen audiomix.merge wire object and trims the bed path', () => {
    expect(
      buildMergeParams({
        videoId: 'v1',
        bgPath: '  C:/music/bed.mp3  ',
        bgGainDb: -12,
        duckThreshold: 0.05,
        duckRatio: 6,
        platform: 'tiktok',
      }),
    ).toEqual({
      videoId: 'v1',
      bgPath: 'C:/music/bed.mp3',
      bgGainDb: -12,
      duckThreshold: 0.05,
      duckRatio: 6,
      platform: 'tiktok',
    });
  });
});

describe('buildNormalizeParams', () => {
  it('builds the frozen audiomix.normalize wire object (no bed)', () => {
    expect(buildNormalizeParams({ videoId: 'v1', platform: 'ebu' })).toEqual({
      videoId: 'v1',
      platform: 'ebu',
    });
  });
});

// ---------------------------------------------------------------------------
// component (jsdom + mocked bridge)
// ---------------------------------------------------------------------------

type ProgressCb = (ev: ProgressEvent) => void;
type DoneCb = (ev: DoneEvent) => void;

function makeBridge(overrides: Record<string, unknown> = {}) {
  const progressCbs: ProgressCb[] = [];
  const doneCbs: DoneCb[] = [];
  const calls: { method: string; params?: Record<string, unknown> }[] = [];
  const responses: Record<string, unknown> = {
    'audiomix.merge': { jobId: 'job-mix' },
    'audiomix.normalize': { jobId: 'job-norm' },
    'job.cancel': { ok: true },
    ...overrides,
  };
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (!(method in responses)) throw new Error(`unexpected rpc: ${method}`);
      const value = responses[method];
      if (value instanceof Error) throw value;
      if (typeof value === 'function') return (value as () => T)();
      return value as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb: ProgressCb) => {
      progressCbs.push(cb);
      return () => undefined;
    },
    onJobDone: (cb: DoneCb) => {
      doneCbs.push(cb);
      return () => undefined;
    },
  };
  return { api, calls, progressCbs, doneCbs };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('<AudioMix />', () => {
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
    delete (globalThis as { api?: unknown }).api;
  });

  function render(node: React.ReactElement): void {
    act(() => {
      root.render(node);
    });
  }

  function q<T extends Element>(selector: string): T {
    return container.querySelector(selector) as T;
  }

  /**
   * Set a controlled input through React's TRACKED native value setter. A bare
   * `el.value = x` updates the node behind React's value tracker, which then
   * sees no change and swallows the synthetic onChange — the field would look
   * typed but the state would never move (the repo idiom: Diarize.test.tsx:299).
   */
  async function type(selector: string, value: string): Promise<void> {
    const el = q<HTMLInputElement>(selector);
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => {
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('renders one option per loudness target and shows the active target', () => {
    render(<AudioMix videoId="v1" api={makeBridge().api} />);
    const picker = q<HTMLSelectElement>('[data-picker="platform"]');
    expect(picker.options).toHaveLength(LOUDNESS_TARGETS.length);
    expect(picker.value).toBe(DEFAULT_TARGET_ID);
    expect(container.textContent).toContain(formatLufs(targetFor(DEFAULT_TARGET_ID).lufs));
  });

  it('shows a REAL Windows path in the bed placeholder', () => {
    // A JSX string attribute is HTML-like: it does NOT process backslash
    // escapes, so `placeholder="C:\\path"` renders two visible backslashes and
    // shows the user a path shape that does not exist. (The sibling Dub panel
    // has this defect at Dub.tsx:342 — out of this lane's scope to change.)
    render(<AudioMix videoId="v1" api={makeBridge().api} />);
    const placeholder = q<HTMLInputElement>('[data-input="bg-path"]').placeholder;
    expect(placeholder).toBe('C:\\path\\to\\bed.mp3');
    expect(placeholder).not.toContain('\\\\');
  });

  it('mixes a bed under the speaker and renders the produced file on job.done', async () => {
    const { api, calls, doneCbs, progressCbs } = makeBridge();
    render(<AudioMix videoId="v1" api={api} />);

    expect(q<HTMLButtonElement>('[data-action="mix"]').disabled).toBe(true);
    await type('[data-input="bg-path"]', 'C:/music/bed.mp3');
    expect(q<HTMLButtonElement>('[data-action="mix"]').disabled).toBe(false);

    await act(async () => {
      q<HTMLButtonElement>('[data-action="mix"]').click();
    });
    await flush();

    expect(calls.find((c) => c.method === 'audiomix.merge')?.params).toEqual({
      videoId: 'v1',
      bgPath: 'C:/music/bed.mp3',
      bgGainDb: DEFAULT_BG_GAIN_DB,
      duckThreshold: DEFAULT_DUCK_THRESHOLD,
      duckRatio: DEFAULT_DUCK_RATIO,
      platform: DEFAULT_TARGET_ID,
    });

    // progress for THIS job updates the bar; a sibling job's is ignored.
    await act(async () => {
      progressCbs.forEach((cb) => cb({ jobId: 'job-mix', pct: 40, message: 'ducking' }));
      progressCbs.forEach((cb) => cb({ jobId: 'other', pct: 99, message: 'not mine' }));
    });
    expect(container.textContent).toContain('ducking');
    expect(container.textContent).not.toContain('not mine');

    await act(async () => {
      doneCbs.forEach((cb) =>
        cb({ jobId: 'job-mix', result: { path: 'C:/exports/audiomix/talk-mixed-1.mp4' } }),
      );
    });
    await flush();

    const result = q<HTMLElement>('[data-testid="audiomix-result"]');
    expect(result).not.toBeNull();
    expect(result.textContent).toContain('C:/exports/audiomix/talk-mixed-1.mp4');
    expect(result.textContent).toContain('Mixed');
    expect(q<HTMLButtonElement>('[data-action="mix"]').disabled).toBe(false);
  });

  it('threads the edited bed gain / duck tunables and the picked platform', async () => {
    const { api, calls } = makeBridge();
    render(<AudioMix videoId="v1" api={api} />);
    await type('[data-input="bg-path"]', 'C:/music/bed.mp3');
    await type('[data-input="bg-gain"]', '-18');
    await type('[data-input="duck-threshold"]', '0.08');
    await type('[data-input="duck-ratio"]', '12');
    const picker = q<HTMLSelectElement>('[data-picker="platform"]');
    await act(async () => {
      picker.value = 'ebu';
      picker.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(container.textContent).toContain('-23 LUFS');

    await act(async () => {
      q<HTMLButtonElement>('[data-action="mix"]').click();
    });
    await flush();

    expect(calls.find((c) => c.method === 'audiomix.merge')?.params).toEqual({
      videoId: 'v1',
      bgPath: 'C:/music/bed.mp3',
      bgGainDb: -18,
      duckThreshold: 0.08,
      duckRatio: 12,
      platform: 'ebu',
    });
  });

  it('falls back to the engine default when a tunable is cleared to blank', async () => {
    const { api, calls } = makeBridge();
    render(<AudioMix videoId="v1" api={api} />);
    await type('[data-input="bg-path"]', 'C:/music/bed.mp3');
    await type('[data-input="bg-gain"]', '');

    await act(async () => {
      q<HTMLButtonElement>('[data-action="mix"]').click();
    });
    await flush();

    expect(calls.find((c) => c.method === 'audiomix.merge')?.params).toMatchObject({
      bgGainDb: DEFAULT_BG_GAIN_DB,
    });
  });

  it('loudness-normalizes an export with no bed (audiomix.normalize)', async () => {
    const { api, calls, doneCbs } = makeBridge();
    render(<AudioMix videoId="v1" api={api} />);

    // no bed path needed for the normalize-only path
    expect(q<HTMLButtonElement>('[data-action="normalize"]').disabled).toBe(false);
    await act(async () => {
      q<HTMLButtonElement>('[data-action="normalize"]').click();
    });
    await flush();

    expect(calls.find((c) => c.method === 'audiomix.normalize')?.params).toEqual({
      videoId: 'v1',
      platform: DEFAULT_TARGET_ID,
    });

    await act(async () => {
      doneCbs.forEach((cb) =>
        cb({ jobId: 'job-norm', result: { path: 'C:/exports/audiomix/talk-loudnorm-1.mp4' } }),
      );
    });
    await flush();
    // the result card names WHICH job produced the file (the other branch of the
    // mode label is asserted as 'Mixed' by the merge test above)
    expect(q<HTMLElement>('[data-testid="audiomix-result"]').textContent).toContain('Normalised');
  });

  it('surfaces a rejected rpc as an error and returns to idle', async () => {
    const { api } = makeBridge({ 'audiomix.merge': new Error('background audio not found: bed') });
    render(<AudioMix videoId="v1" api={api} />);
    await type('[data-input="bg-path"]', 'C:/nope.mp3');
    await act(async () => {
      q<HTMLButtonElement>('[data-action="mix"]').click();
    });
    await flush();

    expect(q<HTMLElement>('[role="alert"]').textContent).toContain('background audio not found');
    expect(q<HTMLButtonElement>('[data-action="mix"]').disabled).toBe(false);
  });

  it('stringifies a non-Error rejection', async () => {
    const { api } = makeBridge({
      'audiomix.normalize': () => {
        // eslint-disable-next-line @typescript-eslint/only-throw-error
        throw 'sidecar exploded';
      },
    });
    render(<AudioMix videoId="v1" api={api} />);
    await act(async () => {
      q<HTMLButtonElement>('[data-action="normalize"]').click();
    });
    await flush();
    expect(q<HTMLElement>('[role="alert"]').textContent).toContain('sidecar exploded');
  });

  it('returns to idle when the sidecar answers without a jobId (no job to await)', async () => {
    const { api } = makeBridge({ 'audiomix.normalize': {} });
    render(<AudioMix videoId="v1" api={api} />);
    await act(async () => {
      q<HTMLButtonElement>('[data-action="normalize"]').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="audiomix-result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(q<HTMLButtonElement>('[data-action="normalize"]').disabled).toBe(false);
  });

  it('shows no result when job.done carries no path', async () => {
    const { api, doneCbs } = makeBridge();
    render(<AudioMix videoId="v1" api={api} />);
    await act(async () => {
      q<HTMLButtonElement>('[data-action="normalize"]').click();
    });
    await flush();
    await act(async () => {
      doneCbs.forEach((cb) => cb({ jobId: 'job-norm', result: {} }));
    });
    await flush();
    expect(container.querySelector('[data-testid="audiomix-result"]')).toBeNull();
    expect(q<HTMLButtonElement>('[data-action="normalize"]').disabled).toBe(false);
  });

  it('cancels a running job and returns to idle WITHOUT surfacing an error', async () => {
    const { api, calls } = makeBridge();
    render(<AudioMix videoId="v1" api={api} />);
    await act(async () => {
      q<HTMLButtonElement>('[data-action="normalize"]').click();
    });
    await flush();
    expect(q<HTMLButtonElement>('[data-action="cancel"]')).not.toBeNull();

    await act(async () => {
      q<HTMLButtonElement>('[data-action="cancel"]').click();
    });
    await flush();

    expect(calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-norm' });
    // A cancel is a clean escape: no error banner, no stuck spinner. (The sidecar
    // emits NO job.done for a cancelled job, so aborting the wait is what frees
    // the panel — see features/_api.ts waitForJobDone.)
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[data-action="cancel"]')).toBeNull();
    expect(q<HTMLButtonElement>('[data-action="normalize"]').disabled).toBe(false);
  });

  it('still frees the panel when job.cancel itself rejects (best-effort cancel)', async () => {
    const { api } = makeBridge({ 'job.cancel': new Error('already finished') });
    render(<AudioMix videoId="v1" api={api} />);
    await act(async () => {
      q<HTMLButtonElement>('[data-action="normalize"]').click();
    });
    await flush();
    await act(async () => {
      q<HTMLButtonElement>('[data-action="cancel"]').click();
    });
    await flush();
    expect(container.querySelector('[data-action="cancel"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('disables both actions when no video is open', () => {
    render(<AudioMix videoId="" api={makeBridge().api} />);
    expect(q<HTMLButtonElement>('[data-action="mix"]').disabled).toBe(true);
    expect(q<HTMLButtonElement>('[data-action="normalize"]').disabled).toBe(true);
  });

  it('falls back to the preload-exposed bridge when no api prop is given', async () => {
    const { api, calls } = makeBridge();
    (globalThis as { api?: unknown }).api = api;
    render(<AudioMix videoId="v1" />);
    await act(async () => {
      q<HTMLButtonElement>('[data-action="normalize"]').click();
    });
    await flush();
    expect(calls.map((c) => c.method)).toContain('audiomix.normalize');
  });
});
