// @vitest-environment jsdom
//
// F05 regression at the REAL IPC boundary — the manual path must never send a
// fabricated hook.
//
// Why a SEPARATE file: `MakeShorts.test.tsx` mocks `../features/ManualInterval`
// module-wide and its mock hardcodes `hook: ''`, so that suite stays green even
// if the placeholder were reintroduced in `manualIntervalLogic.ts`. This file
// deliberately does NOT mock ManualInterval — it drives the real control (type a
// range, Add range, Make shorts from ranges) so the candidates that reach
// `client.shortmaker.export` are the ones `buildManualCandidates` actually built.
//
// A non-empty `hook` is BURNED into the exported pixels by the sidecar caption
// stage (`shortmaker.py` `hook_title = hook_text or None` -> `caption.py`
// HookCard for ranks 1-10 / plain HookTitle otherwise) and is persisted as the
// clip's gallery label in `<clip>.json`. The remaining five child mocks are
// re-declared here so the real CaptionDesigner/Player tree is not pulled into
// jsdom.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Candidate, Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const libraryListMock = vi.fn();
const exportMock = vi.fn();
const settingsGetMock = vi.fn();

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

vi.mock('./Shorts', () => ({
  Shorts: () => <div data-testid="shorts" />,
}));

vi.mock('./Repurpose', () => ({
  Repurpose: () => <div data-testid="repurpose" />,
}));

vi.mock('../features/ShortMaker', () => ({
  ShortMaker: ({ videoId }: { videoId: string }) => (
    <div data-testid="shortmaker" data-video-id={videoId} />
  ),
}));

vi.mock('../components/OutputTray', () => {
  // Self-contained (vi.mock is hoisted — no top-level refs allowed).
  const seed = {
    caption: true,
    translate: false,
    reframe: true,
    subtitleMode: 'burn',
    language: 'en',
  };
  return {
    DEFAULT_OUTPUT_TRAY: seed,
    OutputTray: () => <div data-testid="output-tray" />,
  };
});

// NOTE: `../features/ManualInterval` is deliberately NOT mocked.
import { MakeShorts } from './MakeShorts';

let container: HTMLDivElement;
let root: Root;

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
  exportMock.mockReset();
  exportMock.mockResolvedValue({ clips: [{ path: '/out/1.mp4' }] });
  settingsGetMock.mockReset();
  settingsGetMock.mockResolvedValue({});
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function button(text: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')].find((b) => b.textContent === text);
  if (!found) throw new Error(`button "${text}" not found`);
  return found;
}

function typeInto(label: string, value: string): void {
  const el = container.querySelector(`input[aria-label="${label}"]`) as HTMLInputElement;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function addRange(start: string, end: string): Promise<void> {
  typeInto('Range start', start);
  typeInto('Range end', end);
  await act(async () => {
    button('Add range').click();
  });
}

describe('<MakeShorts /> manual export — real ManualInterval (F05)', () => {
  async function driveTwoRanges(): Promise<void> {
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
    await addRange('0:10', '0:40');
    await addRange('1:00', '1:30');
    await act(async () => {
      button('Make shorts from ranges').click();
      await Promise.resolve();
    });
    await flush();
  }

  it('sends NO hook text for manual ranges (a non-empty hook is burned into the pixels)', async () => {
    await driveTwoRanges();

    // SETUP GUARD — proves the harness actually reached the export RPC with the
    // real control's candidates. This passes both before and after the fix, so a
    // failure below is the defect and not a broken fixture.
    expect(exportMock).toHaveBeenCalledTimes(1);
    const [videoId, ids, params] = exportMock.mock.calls[0] as [
      string,
      string[],
      { candidates: Candidate[] },
    ];
    expect(videoId).toBe('v1');
    expect(ids).toEqual(['1@10', '2@60']);
    expect(params.candidates).toHaveLength(2);

    // THE ASSERTION — no candidate may carry a fabricated headline.
    expect(params.candidates.map((c) => c.hook)).toEqual(['', '']);
  });

  it('keeps the manual ranges themselves intact (source-anchored, ranked)', async () => {
    await driveTwoRanges();
    const [, , params] = exportMock.mock.calls[0] as [
      string,
      string[],
      { candidates: Candidate[] },
    ];
    expect(params.candidates.map((c) => [c.rank, c.sourceStart, c.end])).toEqual([
      [1, 10, 40],
      [2, 60, 90],
    ]);
  });
});
