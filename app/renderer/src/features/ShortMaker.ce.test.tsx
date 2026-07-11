// ShortMaker.ce.test.tsx — cross-edit reconcile tests for ShortMaker.tsx.
//
// Isolated (uniquely-named `*.ce.test.tsx`) so it never collides with the
// primary ShortMaker.test.tsx while the shared tree is edited in parallel.
// Coverage is attributed by SOURCE file, so these count toward ShortMaker.tsx's
// 100% gate. Covers the two feature-completion cross-edits applied here:
//   * sidecar-features-2 (brandkit.py:172): a persisted brand caption template
//     seeds the Caption style control — but ONLY while it is still at the picker
//     default (the guard must never clobber an explicit user pick) — and flows
//     through buildExportParams into shortmaker.export.
//   * renderer-features-2 (useShortsGallery:89): the inline ProducedShorts
//     Re-export button is wired ONLY when the host provided cross-view nav
//     (onReexport); the Workspace mount (no nav) shows no dead button.
//
// Every new conditional in the source is exercised true AND false:
//   - `tpl && CAPTION_STYLE_OPTIONS.includes(tpl)`: truthy (brand template set)
//     via the seeding tests; short-circuit (settings.get has no brand template)
//     via the gallery tests below (their settings.get resolves to {}).
//   - `prev.captionStyle === DEFAULT_CAPTION_STYLE`: true (default -> seed) and
//     false (user already picked -> keep pick) via the guard test.
//   - `defaultEmphasisForStyle(tpl) ? 'on' : 'off'`: on (hormozi) and off (clean).
//   - `onReexport ? ... : undefined`: false (no nav -> no button) here; the true
//     branch is covered by ShortMaker.test.tsx's existing re-export test.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import ShortMaker, { type Api, type Candidate } from './ShortMaker';

// The candidate Player mounts during the export flow; jsdom lacks media methods.
beforeAll(() => {
  const paused = new WeakMap<HTMLMediaElement, boolean>();
  const times = new WeakMap<HTMLMediaElement, number>();
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    writable: true,
    value: vi.fn(function (this: HTMLMediaElement) {
      paused.set(this, false);
      return Promise.resolve();
    }),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    writable: true,
    value: vi.fn(function (this: HTMLMediaElement) {
      paused.set(this, true);
    }),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return times.get(this) ?? 0;
    },
    set(this: HTMLMediaElement, v: number) {
      times.set(this, v);
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'paused', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return paused.get(this) ?? true;
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'ended', {
    configurable: true,
    get() {
      return false;
    },
  });
});

function cand(over: Partial<Candidate> = {}): Candidate {
  return {
    rank: 1,
    start: 97,
    end: 131,
    durationSec: 34,
    hook: 'A',
    why: 'Introduces the core concept',
    score: 95,
    sourceStart: 97,
    ...over,
  };
}

const THREE: Candidate[] = [
  cand({ rank: 2, start: 199, end: 248, durationSec: 49, hook: 'B', score: 92, sourceStart: 199 }),
  cand({ rank: 1, start: 97, end: 131, durationSec: 34, hook: 'A', score: 95, sourceStart: 97 }),
  cand({ rank: 3, start: 494, end: 554, durationSec: 60, hook: 'C', score: 93, sourceStart: 494 }),
];

const SHORT = {
  id: 'sid-1',
  path: '/out/clip.mp4',
  videoId: 'v1',
  sourceTitle: 'Talk',
  template: '',
  viralityPct: null,
  durationSec: 30,
  width: 1080,
  height: 1920,
  createdAt: 0,
  thumbnailPath: '',
  hook: '',
};

function makeApi(over: Partial<Api> = {}): Api {
  return { rpc: vi.fn(), onProgress: vi.fn(() => () => {}), ...over };
}

describe('<ShortMaker /> cross-edit reconcile', () => {
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
    vi.restoreAllMocks();
  });

  function render(el: React.ReactElement) {
    act(() => {
      root.render(el);
    });
  }

  function flush() {
    return act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  function byLabel(label: string): HTMLElement | null {
    return container.querySelector(`[aria-label="${label}"]`);
  }

  function rpcFake(handlers: Record<string, unknown>): Api['rpc'] & ReturnType<typeof vi.fn> {
    return vi.fn(async (method: string) => {
      const h = handlers[method];
      if (h instanceof Error) throw h;
      return h ?? {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
  }

  async function submitForm() {
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();
  }

  // ---- sidecar-features-2: brand caption template seeds the Caption style ----

  it('seeds the Caption style control from a persisted brand template (default -> ON emphasis)', async () => {
    const rpc = rpcFake({ 'settings.get': { brandCaptionTemplate: 'hormozi' } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect((byLabel('Caption style') as HTMLSelectElement).value).toBe('hormozi');
    // hormozi is an OpusClip-style template -> emphasis seeds ON.
    expect((byLabel('Emphasis') as HTMLSelectElement).value).toBe('on');
  });

  it('a seeded brand template flows through to shortmaker.export params', async () => {
    const rpc = rpcFake({
      'settings.get': { brandCaptionTemplate: 'hormozi' },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }] },
      'shorts.list': { shorts: [] },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect((byLabel('Caption style') as HTMLSelectElement).value).toBe('hormozi');

    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();

    const exportCall = rpc.mock.calls.find((c) => c[0] === 'shortmaker.export');
    expect(exportCall).toBeTruthy();
    expect((exportCall![1] as { captionStyle?: string }).captionStyle).toBe('hormozi');
  });

  it('seeds a clean brand template with emphasis OFF (default_emphasis_for_style false)', async () => {
    const rpc = rpcFake({ 'settings.get': { brandCaptionTemplate: 'clean' } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect((byLabel('Caption style') as HTMLSelectElement).value).toBe('clean');
    // clean is a minimal template -> emphasis seeds OFF.
    expect((byLabel('Emphasis') as HTMLSelectElement).value).toBe('off');
  });

  it('does NOT override an explicit user pick made before settings.get resolves (guard)', async () => {
    // Deferred settings.get: the user changes the Caption style BEFORE it resolves.
    let resolveSettings: (v: unknown) => void = () => {};
    const settingsPromise = new Promise((r) => {
      resolveSettings = r;
    });
    const rpc = vi.fn(async (method: string) => {
      if (method === 'settings.get') return settingsPromise;
      return {};
    }) as unknown as Api['rpc'];
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);

    // User picks a non-default style while settings.get is still pending.
    const style = byLabel('Caption style') as HTMLSelectElement;
    act(() => {
      style.value = 'neon';
      style.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect((byLabel('Caption style') as HTMLSelectElement).value).toBe('neon');

    // settings.get now resolves with a brand template -> the guard must keep 'neon'.
    await act(async () => {
      resolveSettings({ brandCaptionTemplate: 'hormozi' });
      await Promise.resolve();
    });
    await flush();
    expect((byLabel('Caption style') as HTMLSelectElement).value).toBe('neon');
  });

  // ---- renderer-features-2: inline Re-export only when host wired nav --------

  async function loadGallery(shorts: unknown[]): Promise<void> {
    // NOTE: settings.get is intentionally unmocked (-> {}), which also exercises
    // the brand-seeding `tpl` short-circuit (no brand template -> no seeding).
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }] },
      'shorts.list': { shorts },
      'shorts.reexport': {
        videoId: 'v1',
        candidate: { hook: 'h', template: 't', viralityPct: 50, durationSec: 30 },
      },
    });
    // No onReexport prop -> the Workspace-style mount with no cross-view nav.
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
  }

  it('renders NO inline Re-export button when the host wired no onReexport nav', async () => {
    await loadGallery([SHORT]);
    // The produced short still renders (play/open/delete) but no dead Re-export.
    expect(byLabel('Play Talk')).toBeTruthy();
    expect(byLabel('Re-export Talk')).toBeNull();
  });
});
