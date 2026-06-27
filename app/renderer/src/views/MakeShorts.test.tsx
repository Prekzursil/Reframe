// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Candidate, ShortReexportHint, Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const libraryListMock = vi.fn();
const exportMock = vi.fn();
let hasApiValue = true;

vi.mock('../lib/rpc', () => ({
  hasApi: () => hasApiValue,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
    shortmaker: { export: (...a: unknown[]) => exportMock(...a) },
  },
}));

vi.mock('./Shorts', () => ({
  Shorts: ({ onReexport }: { onReexport?: (h: ShortReexportHint) => void }) => (
    <div data-testid="shorts">
      <button
        type="button"
        onClick={() =>
          onReexport?.({
            videoId: 'v2',
            candidate: { hook: 'h', template: 't', viralityPct: 50, durationSec: 30 },
          })
        }
      >
        reexport
      </button>
    </div>
  ),
}));

vi.mock('./Repurpose', () => ({
  Repurpose: ({ resumeId }: { resumeId?: string }) => (
    <div data-testid="repurpose" data-resume={resumeId ?? ''} />
  ),
}));

vi.mock('../features/ShortMaker', () => ({
  ShortMaker: ({ videoId }: { videoId: string }) => (
    <div data-testid="shortmaker" data-video-id={videoId} />
  ),
}));

vi.mock('../features/ManualInterval', () => {
  const cands = [
    { rank: 1, start: 10, end: 40, durationSec: 30, sourceStart: 10, hook: '', why: '', score: 0 },
  ];
  return {
    ManualInterval: ({
      onSubmit,
      busy,
    }: {
      onSubmit: (c: Candidate[]) => void;
      busy?: boolean;
    }) => (
      <div data-testid="manual" data-busy={String(busy)}>
        <button type="button" onClick={() => onSubmit(cands)}>
          manual-submit
        </button>
      </div>
    ),
  };
});

// Mirror of the candidate the ManualInterval mock submits (for assertions).
const MANUAL_CANDS: Candidate[] = [
  { rank: 1, start: 10, end: 40, durationSec: 30, sourceStart: 10, hook: '', why: '', score: 0 },
];

vi.mock('../components/OutputTray', () => {
  // Self-contained (vi.mock is hoisted — no top-level refs allowed).
  const seed = { caption: true, translate: false, reframe: true, burnSubs: true, language: 'en' };
  return {
    DEFAULT_OUTPUT_TRAY: seed,
    OutputTray: ({
      onChange,
      onSaveShort,
      onSaveSrt,
    }: {
      onChange: (s: typeof seed) => void;
      onSaveShort?: () => void;
      onSaveSrt?: () => void;
    }) => (
      <div data-testid="output-tray">
        <button type="button" onClick={() => onChange({ ...seed, translate: true })}>
          tray-change
        </button>
        <button type="button" onClick={() => onSaveShort?.()}>
          tray-save-short
        </button>
        <button type="button" onClick={() => onSaveSrt?.()}>
          tray-save-srt
        </button>
      </div>
    ),
  };
});

import { MakeShorts } from './MakeShorts';

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    id: 'v1',
    path: '/m/a.mp4',
    title: 'Alpha',
    addedAt: '2026-06-27T00:00:00Z',
    durationSec: 100,
    hasTranscript: false,
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  hasApiValue = true;
  libraryListMock.mockReset();
  libraryListMock.mockResolvedValue({ videos: [makeVideo()] });
  exportMock.mockReset();
  exportMock.mockResolvedValue({ clips: [{ path: '/out/1.mp4' }] });
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

async function mount(resumeId?: string): Promise<void> {
  await act(async () => {
    root.render(<MakeShorts resumeId={resumeId} />);
  });
  await flush();
}

function sectionBtn(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
  const found = btns.find((b) => b.textContent === label);
  if (!found) throw new Error(`section "${label}" not found`);
  return found;
}

function picker(): HTMLSelectElement {
  return container.querySelector('select[aria-label="Source video"]') as HTMLSelectElement;
}

async function selectVideo(id: string): Promise<void> {
  const sel = picker();
  await act(async () => {
    sel.value = id;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await flush();
}

describe('<MakeShorts />', () => {
  it('lands on the Make front door with a video picker + hint (no video yet)', async () => {
    await mount();
    expect(picker()).toBeTruthy();
    expect(container.querySelector('.make-shorts__hint')).toBeTruthy();
    expect(container.querySelector('[data-testid="shortmaker"]')).toBeNull();
    // The picker is populated from library.list.
    expect([...picker().options].map((o) => o.value)).toContain('v1');
  });

  it('defaults to the Batch section when a resume id is given', async () => {
    await mount('b9');
    const rep = container.querySelector('[data-testid="repurpose"]');
    expect(rep).toBeTruthy();
    expect(rep!.getAttribute('data-resume')).toBe('b9');
  });

  it('switches to the produced-shorts gallery and the batch section', async () => {
    await mount();
    await act(async () => sectionBtn('Produced shorts').click());
    await flush();
    expect(container.querySelector('[data-testid="shorts"]')).toBeTruthy();
    await act(async () => sectionBtn('Batch & Templates').click());
    await flush();
    expect(container.querySelector('[data-testid="repurpose"]')).toBeTruthy();
  });

  it('reveals AI moment-pick + manual intervals once a video is selected', async () => {
    await mount();
    await selectVideo('v1');
    expect(
      container.querySelector('[data-testid="shortmaker"]')!.getAttribute('data-video-id'),
    ).toBe('v1');
    expect(container.querySelector('[data-testid="manual"]')).toBeTruthy();
  });

  it('re-export from the gallery jumps to Make primed with the source video', async () => {
    libraryListMock.mockResolvedValue({
      videos: [makeVideo(), makeVideo({ id: 'v2', title: 'Beta' })],
    });
    await mount();
    await act(async () => sectionBtn('Produced shorts').click());
    await flush();
    await act(async () => {
      (container.querySelector('[data-testid="shorts"] button') as HTMLButtonElement).click();
    });
    await flush();
    // Back on Make, with v2 selected -> ShortMaker mounted for v2.
    expect(
      container.querySelector('[data-testid="shortmaker"]')!.getAttribute('data-video-id'),
    ).toBe('v2');
  });

  it('exports manual ranges, shows a note + the Output Tray on success', async () => {
    await mount();
    await selectVideo('v1');
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'manual-submit',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(exportMock).toHaveBeenCalledTimes(1);
    const [vid, ids, opts] = exportMock.mock.calls[0];
    expect(vid).toBe('v1');
    expect(ids).toEqual(['1@10']);
    expect(opts).toMatchObject({ candidates: MANUAL_CANDS });
    expect(container.querySelector('.make-shorts__note')?.textContent).toContain('Exported 1 clip');
    expect(container.querySelector('[data-testid="output-tray"]')).toBeTruthy();
  });

  it('surfaces a manual-export error and shows no tray', async () => {
    exportMock.mockRejectedValue(new Error('export blew up'));
    await mount();
    await selectVideo('v1');
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'manual-submit',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.make-shorts__error')?.textContent).toContain('export blew up');
    expect(container.querySelector('[data-testid="output-tray"]')).toBeNull();
  });

  it('stringifies a non-Error manual-export rejection', async () => {
    exportMock.mockRejectedValue('plain string failure');
    await mount();
    await selectVideo('v1');
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'manual-submit',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.make-shorts__error')?.textContent).toContain(
      'plain string failure',
    );
  });

  it('drives the Output Tray change + save seams after a manual export', async () => {
    await mount();
    await selectVideo('v1');
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'manual-submit',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    const click = (label: string) =>
      act(() => {
        (
          [...container.querySelectorAll('button')].find(
            (b) => b.textContent === label,
          ) as HTMLButtonElement
        ).click();
      });
    click('tray-change'); // exercises onChange={setTray}
    click('tray-save-short');
    expect(container.querySelector('.make-shorts__note')?.textContent).toContain('Saved the short');
    click('tray-save-srt');
    expect(container.querySelector('.make-shorts__note')?.textContent).toContain(
      'Saved the SRT sidecar',
    );
  });

  it('swallows a library.list rejection (best-effort) and stays usable', async () => {
    libraryListMock.mockRejectedValue(new Error('list failed'));
    await mount();
    // The picker still renders with just the placeholder; no crash.
    expect([...picker().options].map((o) => o.value)).toEqual(['']);
  });

  it('does not query the library when the preload bridge is absent', async () => {
    hasApiValue = false;
    await mount();
    expect(libraryListMock).not.toHaveBeenCalled();
    // Only the placeholder option exists with no bridge.
    expect([...picker().options].map((o) => o.value)).toEqual(['']);
  });

  it('ignores a late library.list result after unmount (cancelled guard)', async () => {
    let resolveList: (v: { videos: Video[] }) => void = () => {};
    libraryListMock.mockReturnValue(
      new Promise((res) => {
        resolveList = res;
      }),
    );
    await act(async () => {
      root.render(<MakeShorts />);
    });
    await flush();
    act(() => root.unmount());
    await act(async () => {
      resolveList({ videos: [makeVideo()] });
      await Promise.resolve();
    });
    root = createRoot(container);
  });
});
