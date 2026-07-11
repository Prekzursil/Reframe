// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Candidate, ShortReexportHint, Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const libraryListMock = vi.fn();
const exportMock = vi.fn();
const settingsGetMock = vi.fn();
let hasApiValue = true;

vi.mock('../lib/rpc', () => ({
  hasApi: () => hasApiValue,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
    shortmaker: { export: (...a: unknown[]) => exportMock(...a) },
    settings: { get: (...a: unknown[]) => settingsGetMock(...a) },
  },
}));

vi.mock('../components/CaptionDesigner', () => ({
  CaptionDesigner: ({
    design,
    onChange,
    videoId,
  }: {
    design: { style: string; override?: Record<string, unknown> };
    onChange: (d: { style: string; override?: Record<string, unknown> }) => void;
    videoId?: string;
  }) => (
    <div data-testid="caption-designer" data-style={design.style} data-video-id={videoId}>
      <button type="button" onClick={() => onChange({ ...design, style: 'karaoke' })}>
        designer-pick-karaoke
      </button>
      <button
        type="button"
        onClick={() => onChange({ ...design, override: { uppercase: true, positionBand: 'top' } })}
      >
        designer-set-override
      </button>
    </div>
  ),
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
  ShortMaker: ({
    videoId,
    initialControls,
    onReexport,
  }: {
    videoId: string;
    initialControls?: { captionStyle?: string; language?: string };
    onReexport?: (h: ShortReexportHint) => void;
  }) => (
    <div
      data-testid="shortmaker"
      data-video-id={videoId}
      data-init-caption-style={initialControls?.captionStyle ?? ''}
      data-init-language={initialControls?.language ?? ''}
      data-has-reexport={onReexport ? 'true' : 'false'}
    >
      <button
        type="button"
        onClick={() =>
          onReexport?.({
            videoId: 'v2',
            candidate: { hook: 'h', template: 't', viralityPct: 50, durationSec: 30 },
          })
        }
      >
        shortmaker-reexport
      </button>
    </div>
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
  const seed = {
    caption: true,
    translate: false,
    reframe: true,
    subtitleMode: 'burn',
    language: 'en',
  };
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
  jobDoneCb = null;
  delete (globalThis as { window: { api?: unknown } }).window.api;
});

// A driveable preload bridge for the DEFERRED shortmaker.export job wait:
// `waitForJobDone` reads window.api.onJobDone (via resolveWindowApi). Installing
// it lets a test emit the terminal job.done itself. `withJobDone=false` models an
// older bridge with no onJobDone (waitForJobDone then resolves null immediately).
let jobDoneCb: ((d: { jobId: string; result?: unknown }) => void) | null = null;

function installBridge(withJobDone = true): void {
  const api: Record<string, unknown> = {};
  if (withJobDone) {
    api.onJobDone = (cb: (d: { jobId: string; result?: unknown }) => void) => {
      jobDoneCb = cb;
      return () => {};
    };
  }
  (globalThis as { window: { api?: unknown } }).window.api = api;
}

async function clickManualSubmit(): Promise<void> {
  await act(async () => {
    (
      [...container.querySelectorAll('button')].find(
        (b) => b.textContent === 'manual-submit',
      ) as HTMLButtonElement
    ).click();
    await Promise.resolve();
  });
  await flush();
}

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
    // WU-D3: the "pick a video" state is now the shared ghost-poster empty, not a
    // lone hint line.
    expect(container.querySelector('.make-shorts__empty-poster')).toBeTruthy();
    expect(container.querySelector('.make-shorts__empty-glyph')).toBeTruthy();
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

  // WU-3a4: the Workspace "Short-maker" tab deep-links here pre-selected to the
  // video (single ShortMaker owner) via the `videoId` prop — the Make front door
  // lands with AI moment-pick already revealed, no manual picker step.
  it('pre-selects a deep-linked video (Short-maker tab redirect) and reveals AI moment-pick on mount', async () => {
    await act(async () => {
      root.render(<MakeShorts videoId="v1" />);
    });
    await flush();
    // The one ShortMaker owner is mounted for the deep-linked video on the Make tab.
    expect(
      container.querySelector('[data-testid="shortmaker"]')!.getAttribute('data-video-id'),
    ).toBe('v1');
    expect(container.querySelector('[data-testid="manual"]')).toBeTruthy();
    // The picker reflects the pre-selection once the library list resolves.
    expect(picker().value).toBe('v1');
  });

  // Finding@useShortsGallery:89 — the Make-tab ShortMaker now receives onReexport,
  // so its inline ProducedShorts Re-export button is functional (re-primes the
  // source video via the same handler the gallery uses).
  it('wires onReexport on the Make-tab ShortMaker (inline re-export re-primes the source)', async () => {
    libraryListMock.mockResolvedValue({
      videos: [makeVideo(), makeVideo({ id: 'v2', title: 'Beta' })],
    });
    await mount();
    await selectVideo('v1');
    const sm = container.querySelector('[data-testid="shortmaker"]');
    expect(sm?.getAttribute('data-has-reexport')).toBe('true');
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'shortmaker-reexport',
        ) as HTMLButtonElement
      ).click();
    });
    await flush();
    // handleReexport re-primes the picker to the hinted source video.
    expect(
      container.querySelector('[data-testid="shortmaker"]')!.getAttribute('data-video-id'),
    ).toBe('v2');
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
    // P4 §4: the caption design + subtitle delivery ride the export payload.
    expect(opts).toMatchObject({
      candidates: MANUAL_CANDS,
      captionStyle: 'libass',
      subtitleMode: 'burn',
    });
    expect(opts.captionPosition).toMatchObject({ w: expect.any(Number), h: expect.any(Number) });
    expect(container.querySelector('.make-shorts__note')?.textContent).toContain('Exported 1 clip');
    expect(container.querySelector('[data-testid="output-tray"]')).toBeTruthy();
  });

  it('seeds the caption design + subtitle delivery from persisted preferences', async () => {
    settingsGetMock.mockResolvedValue({
      defaultCaptionStyle: 'neon',
      defaultSubtitleMode: 'sidecar',
      defaultLanguage: 'pt',
    });
    await mount();
    await selectVideo('v1');
    // The designer reflects the persisted style.
    expect(
      container.querySelector('[data-testid="caption-designer"]')?.getAttribute('data-style'),
    ).toBe('neon');
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'manual-submit',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    const [, , opts] = exportMock.mock.calls[0];
    expect(opts).toMatchObject({ captionStyle: 'neon', subtitleMode: 'sidecar' });
  });

  it('swallows a settings.get rejection (keeps built-in defaults)', async () => {
    settingsGetMock.mockRejectedValue(new Error('settings down'));
    await mount();
    await selectVideo('v1');
    // Built-in default style survives.
    expect(
      container.querySelector('[data-testid="caption-designer"]')?.getAttribute('data-style'),
    ).toBe('libass');
  });

  it('updates the caption design from the editor', async () => {
    await mount();
    await selectVideo('v1');
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'designer-pick-karaoke',
        ) as HTMLButtonElement
      ).click();
    });
    expect(
      container.querySelector('[data-testid="caption-designer"]')?.getAttribute('data-style'),
    ).toBe('karaoke');
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

  it('ignores a late settings.get result after unmount (cancelled guard)', async () => {
    let resolveSettings: (v: Record<string, unknown>) => void = () => {};
    settingsGetMock.mockReturnValue(
      new Promise((res) => {
        resolveSettings = res;
      }),
    );
    await act(async () => {
      root.render(<MakeShorts />);
    });
    await flush();
    act(() => root.unmount());
    await act(async () => {
      resolveSettings({ defaultCaptionStyle: 'neon' });
      await Promise.resolve();
    });
    root = createRoot(container);
  });

  it('ignores a late settings.get REJECTION after unmount (no prefsLoaded write)', async () => {
    let rejectSettings: (e: unknown) => void = () => {};
    settingsGetMock.mockReturnValue(
      new Promise((_res, rej) => {
        rejectSettings = rej;
      }),
    );
    await act(async () => {
      root.render(<MakeShorts />);
    });
    await flush();
    act(() => root.unmount());
    await act(async () => {
      rejectSettings(new Error('late settings failure'));
      await Promise.resolve();
    });
    root = createRoot(container);
  });

  // ---- deferred shortmaker.export job (verified finding: success reported early) --

  it('waits for the deferred export job before reporting success (real clip count)', async () => {
    installBridge(true);
    exportMock.mockResolvedValue({ jobId: 'j1' });
    await mount();
    await selectVideo('v1');
    await clickManualSubmit();
    // The job is still running: no success note, no tray, and STILL busy.
    expect(container.querySelector('.make-shorts__note')).toBeNull();
    expect(container.querySelector('[data-testid="output-tray"]')).toBeNull();
    expect(container.querySelector('[data-testid="manual"]')?.getAttribute('data-busy')).toBe(
      'true',
    );
    // job.done delivers the real (two) clips.
    await act(async () => {
      jobDoneCb!({
        jobId: 'j1',
        result: { clips: [{ path: '/out/1.mp4' }, { path: '/out/2.mp4' }] },
      });
    });
    await flush();
    expect(container.querySelector('.make-shorts__note')?.textContent).toContain('Exported 2 clip');
    expect(container.querySelector('[data-testid="output-tray"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="manual"]')?.getAttribute('data-busy')).toBe(
      'false',
    );
  });

  it('surfaces a deferred export job.done error (never a silent success)', async () => {
    installBridge(true);
    exportMock.mockResolvedValue({ jobId: 'j2' });
    await mount();
    await selectVideo('v1');
    await clickManualSubmit();
    await act(async () => {
      jobDoneCb!({
        jobId: 'j2',
        result: { error: { message: 'ffmpeg exploded', type: 'ExportError' } },
      });
    });
    await flush();
    expect(container.querySelector('.make-shorts__error')?.textContent).toContain('ffmpeg exploded');
    expect(container.querySelector('[data-testid="output-tray"]')).toBeNull();
  });

  it('reports zero clips when the bridge cannot observe job.done (no onJobDone)', async () => {
    installBridge(false);
    exportMock.mockResolvedValue({ jobId: 'j3' });
    await mount();
    await selectVideo('v1');
    await clickManualSubmit();
    // waitForJobDone resolves null with no onJobDone channel → zero clips exported.
    expect(container.querySelector('.make-shorts__note')?.textContent).toContain('Exported 0 clip');
    expect(container.querySelector('[data-testid="output-tray"]')).toBeTruthy();
  });

  it('reports zero clips for a response that is neither clips nor a job handle', async () => {
    // Neither {clips} nor {jobId}: extractClips is null AND isJobHandle is false,
    // so the wait is skipped and the export settles at zero clips (no crash).
    exportMock.mockResolvedValue({});
    await mount();
    await selectVideo('v1');
    await clickManualSubmit();
    expect(container.querySelector('.make-shorts__note')?.textContent).toContain('Exported 0 clip');
  });

  // ---- V1.1 CaptionOverride threads through the manual export -------------------

  it('threads the caption override patch into the export payload when set', async () => {
    await mount();
    await selectVideo('v1');
    // Tune a within-template override via the caption editor, then export.
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'designer-set-override',
        ) as HTMLButtonElement
      ).click();
    });
    await flush();
    await clickManualSubmit();
    const [, , opts] = exportMock.mock.calls[0];
    expect(opts.captionOverride).toEqual({ uppercase: true, positionBand: 'top' });
  });

  it('omits captionOverride from the export payload when no override is set', async () => {
    await mount();
    await selectVideo('v1');
    await clickManualSubmit();
    const [, , opts] = exportMock.mock.calls[0];
    expect(opts.captionOverride).toBeUndefined();
  });

  // ---- persisted caption/language default seeds the AI ShortMaker flow ----------

  it('seeds the AI ShortMaker flow from the persisted caption/language default', async () => {
    settingsGetMock.mockResolvedValue({ defaultCaptionStyle: 'bold', defaultLanguage: 'pt' });
    await mount();
    await selectVideo('v1');
    const sm = container.querySelector('[data-testid="shortmaker"]');
    expect(sm?.getAttribute('data-init-caption-style')).toBe('bold');
    expect(sm?.getAttribute('data-init-language')).toBe('pt');
  });

  it('mounts the AI flow with built-in defaults when preferences fail to load (fail-open)', async () => {
    settingsGetMock.mockRejectedValue(new Error('settings down'));
    await mount();
    await selectVideo('v1');
    const sm = container.querySelector('[data-testid="shortmaker"]');
    expect(sm).toBeTruthy();
    expect(sm?.getAttribute('data-init-caption-style')).toBe('libass');
  });
});
