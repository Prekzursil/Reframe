// @vitest-environment jsdom
//
// F45 — the AI moment-pick export must carry the caption POSITION, the subtitle
// DELIVERY mode and the V1.1 caption OVERRIDE, exactly like the manual path.
//
// Why a SEPARATE file: `MakeShorts.test.tsx` mocks `../features/ShortMaker`
// module-wide, so it cannot see what the real AI flow actually puts on the wire.
// Here ShortMaker is REAL — only `../lib/rpc` and `../components/CaptionDesigner`
// are mocked — so the assertions are made at the `shortmaker.export` RPC boundary
// that the sidecar reads. MakeShorts passes no `api` prop, so ShortMaker resolves
// the bridge through `resolveWindowApi()`; the `window.api` stub below is that
// bridge.
//
// CONTRACT-NOTE (deliberate behaviour change, pinned by the third test):
// `captionDesignWire` ALWAYS emits `captionPosition`, so after the fix EVERY AI
// export sends a box — including the DEFAULT bottom band for a user who never
// opened the caption editor. Sidecar-side that moves the libass margins from the
// `position=None` defaults (alignment 2 / 40,40,115) to the default-box values
// via `caption_position_fields`, which narrows the usable text width and can
// change line wrapping. That is accepted deliberately: it converges the AI path
// onto the manual path (which already sends the default box). AI-flow caption
// visual baselines are expected to move.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Candidate, Video } from '../lib/rpc';
import { DEFAULT_CAPTION_BOX, boxToWire } from '../lib/captionPosition';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const libraryListMock = vi.fn();
const settingsGetMock = vi.fn();
const exportMock = vi.fn();

vi.mock('../lib/rpc', () => ({
  hasApi: () => true,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
    shortmaker: { export: (...a: unknown[]) => exportMock(...a) },
    settings: { get: (...a: unknown[]) => settingsGetMock(...a) },
  },
}));

vi.mock('../components/CaptionDesigner', () => ({
  CaptionDesigner: ({ design }: { design: { style: string } }) => (
    <div data-testid="caption-designer" data-style={design.style} />
  ),
}));

import { MakeShorts } from './MakeShorts';

/** A TOP band + a non-burn delivery — both DIFFERENT from the shipped defaults, so
 *  the assertions cannot pass by coincidence. */
const TOP_BAND = { x: 0.1, y: 0.06, w: 0.8, h: 0.16 };

const AI_CANDIDATES: Candidate[] = [
  {
    rank: 1,
    start: 10,
    end: 40,
    durationSec: 30,
    sourceStart: 10,
    hook: 'A real model-authored hook',
    why: 'strong opener',
    score: 0.9,
    viralityPct: 95,
  },
  {
    rank: 2,
    start: 60,
    end: 90,
    durationSec: 30,
    sourceStart: 60,
    hook: 'Another hook',
    why: 'punchline',
    score: 0.5,
    viralityPct: 40,
  },
];

let container: HTMLDivElement;
let root: Root;
let rpc: ReturnType<typeof vi.fn>;

beforeEach(() => {
  libraryListMock.mockReset();
  libraryListMock.mockResolvedValue({
    videos: [
      {
        id: 'v1',
        path: '/m/a.mp4',
        title: 'Alpha',
        addedAt: '2026-06-27T00:00:00Z',
        durationSec: 100,
        hasTranscript: false,
      } satisfies Video,
    ],
  });
  settingsGetMock.mockReset();
  settingsGetMock.mockResolvedValue({});
  exportMock.mockReset();
  exportMock.mockResolvedValue({ clips: [] });

  // Method-aware bridge fake: ShortMaker's mount fires tracks.audio.list,
  // feedback.stats, settings.get (brand kit) and shorts.list, so an order-based
  // mock would misfire — route by method name.
  rpc = vi.fn(async (method: string) => {
    if (method === 'tracks.audio.list') return { audioTracks: [] };
    if (method === 'shortmaker.select') return { candidates: AI_CANDIDATES };
    if (method === 'shortmaker.export') return { clips: [{ path: '/out/1.mp4' }] };
    return {};
  });
  (globalThis as { window: { api?: unknown } }).window.api = {
    rpc,
    onProgress: () => () => {},
  };

  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  delete (globalThis as { window: { api?: unknown } }).window.api;
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

/** Mount MakeShorts, pick the source video, and await the preferences read so
 *  the AI section (gated on `prefsLoaded`) is mounted with the seeded design. */
async function mountWithVideo(): Promise<void> {
  await act(async () => {
    root.render(<MakeShorts />);
  });
  await flush();
  const sel = container.querySelector('select[aria-label="Source video"]') as HTMLSelectElement;
  await act(async () => {
    sel.value = 'v1';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await flush();
}

function exportParams(): Record<string, unknown> {
  const call = rpc.mock.calls.find((c) => c[0] === 'shortmaker.export');
  if (!call) throw new Error('shortmaker.export was never called');
  return call[1] as Record<string, unknown>;
}

/** Find clips -> approve rank 1 -> Export approved (the review call site). */
async function driveApproveExport(): Promise<void> {
  const form = container.querySelector('form') as HTMLFormElement;
  await act(async () => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve();
  });
  await flush();
  const row = container.querySelector('.sm-candidate[data-id="1@10"]') as HTMLElement;
  act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
  const exportBtn = [...container.querySelectorAll('button')].find(
    (b) => b.textContent === 'Export approved',
  ) as HTMLButtonElement;
  await act(async () => {
    exportBtn.click();
    await Promise.resolve();
  });
  await flush();
}

/** "Make N shorts" — the unattended batch call site (a separate useCallback). */
async function driveBatch(): Promise<void> {
  const batchBtn = container.querySelector('[aria-label="Make N shorts"]') as HTMLButtonElement;
  await act(async () => {
    batchBtn.click();
    await Promise.resolve();
  });
  await flush();
}

describe('<MakeShorts /> AI export caption defaults (F45)', () => {
  it('threads the caption position + subtitle delivery into the review-path AI export', async () => {
    settingsGetMock.mockResolvedValue({
      defaultCaptionBox: TOP_BAND,
      defaultSubtitleMode: 'sidecar',
    });
    await mountWithVideo();
    await driveApproveExport();

    // SETUP GUARD — passes TODAY, proving the harness reached the right RPC with
    // the right video. A failure below is therefore the defect, not a fixture.
    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.export',
      expect.objectContaining({ videoId: 'v1', captionStyle: expect.any(String) }),
    );

    // THE RED ASSERTIONS — neither key is present before the fix.
    expect(exportParams()).toMatchObject({
      subtitleMode: 'sidecar',
      captionPosition: boxToWire(TOP_BAND),
    });
  });

  it('threads them into the unattended batch AI export too (the second call site)', async () => {
    settingsGetMock.mockResolvedValue({
      defaultCaptionBox: TOP_BAND,
      defaultSubtitleMode: 'sidecar',
    });
    await mountWithVideo();
    await driveBatch();

    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.export',
      expect.objectContaining({ videoId: 'v1', captionStyle: expect.any(String) }),
    );
    expect(exportParams()).toMatchObject({
      subtitleMode: 'sidecar',
      captionPosition: boxToWire(TOP_BAND),
    });
  });

  it('sends the DEFAULT caption box on an out-of-box AI export (an explicit layout change)', async () => {
    // Nothing persisted: the built-in defaults. This pins the deliberate
    // behaviour change described in the CONTRACT-NOTE above — the AI path now
    // sends the default bottom band instead of omitting the position entirely,
    // which converges it onto the manual path.
    settingsGetMock.mockResolvedValue({});
    await mountWithVideo();
    await driveApproveExport();

    expect(exportParams()).toMatchObject({
      subtitleMode: 'burn',
      captionPosition: boxToWire(DEFAULT_CAPTION_BOX),
    });
  });
});
