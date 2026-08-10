// ReframeCorrect.test.tsx — the W17 mount of the built-but-unreachable
// ReframeOverridePanel.
//
// The panel itself is already covered in isolation (panels/ReframeOverridePanel
// .test.tsx). What is untested — and what shipped WRONG, as "mounted nowhere" —
// is the surrounding container: where a real plan comes from, what happens when
// a clip has no per-shot decisions, and whether the UI tells the truth about
// what "Re-render" can actually do in this build.
//
// The honesty assertions are load-bearing, not decoration — and they were WRONG
// in the first version of this file, which pinned the sentence "this build
// registers no reframe.render method" as the reason corrections cannot be
// applied. That sentence named the wrong blocker: the re-render engine is built
// and lives in the export pipeline (`shortmaker.export {reframeOverrides}`,
// `shortmaker.py:257,1450-1455`; `docs/plans/v1.5/SCOPE.md:47-74`). The
// assertions below now pin the CORRECTED sentences, plus the two properties the
// old version got wrong:
//   * the UI must NOT offer "re-export the short" as a remedy — that path is
//     `shortmaker.export` without the map, so it re-cuts and DISCARDS the user's
//     corrections;
//   * the corrections must survive the press, as the exact `reframeOverrides`
//     entry the export takes.
// Both of those fail against the previous commit (it printed the re-export
// advice and rendered no payload at all), so neither is green in the known-bad
// state.

// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { ShotPlan } from '../lib/reframeOverride';

const listMock = vi.fn();
const shotPlanForMock = vi.fn();
vi.mock('../lib/rpc', () => ({
  client: {
    shorts: { list: (videoId?: string) => listMock(videoId) },
    reframe: { shotPlanFor: (clip: string) => shotPlanForMock(clip) },
  },
}));

import { ReframeCorrect } from './ReframeCorrect';

// A produced clip as `shorts.list` reports it (only the fields this panel reads
// are meaningful; the rest mirror the ShortInfo schema so the type is honest).
function short(path: string): Record<string, unknown> {
  return {
    id: path,
    path,
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
}

const CLIP_A = 'C:/shorts/talk-01.mp4';
const CLIP_B = 'C:/shorts/talk-02.mp4';

function planFixture(): ShotPlan {
  return {
    sourceWidth: 1920,
    sourceHeight: 1080,
    fps: 30,
    shots: [
      {
        index: 0,
        startFrame: 0,
        endFrame: 30,
        speaker: 'a',
        layout: 'single',
        crop: [100, 0, 600, 1080],
        speakers: ['a', 'b'],
      },
      {
        index: 1,
        startFrame: 30,
        endFrame: 60,
        speaker: 'b',
        layout: 'split',
        crop: [200, 0, 600, 1080],
        speakers: ['b'],
      },
    ],
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  listMock.mockReset();
  shotPlanForMock.mockReset();
  listMock.mockResolvedValue({ shorts: [short(CLIP_A), short(CLIP_B)] });
  shotPlanForMock.mockResolvedValue({
    plan: planFixture(),
    engine: 'multispeaker',
    aspect: '9:16',
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

async function mount(videoId = 'v1'): Promise<void> {
  await act(async () => {
    root.render(<ReframeCorrect videoId={videoId} />);
  });
}

const section = (name: string): HTMLElement | null =>
  container.querySelector(`[data-section="${name}"]`);
const sectionText = (name: string): string => section(name)?.textContent ?? '';

describe('ReframeCorrect — where the plan comes from', () => {
  it('lists this video produced clips and opens the FIRST one plan', async () => {
    await mount();
    expect(listMock).toHaveBeenCalledWith('v1');
    expect(shotPlanForMock).toHaveBeenCalledWith(CLIP_A);
    // the real correction panel is mounted, with a row per shot
    expect(container.querySelector('section.reframe-override')).not.toBeNull();
    expect(container.querySelectorAll('[data-shot]')).toHaveLength(2);
    // the clip picker offers every produced clip by file name
    const options = [...container.querySelectorAll('select[data-action="clip"] option')].map(
      (o) => o.textContent,
    );
    expect(options).toEqual(['talk-01.mp4', 'talk-02.mp4']);
  });

  it('loads the plan of whichever clip is picked', async () => {
    await mount();
    const select = container.querySelector('select[data-action="clip"]') as HTMLSelectElement;
    await act(async () => {
      select.value = CLIP_B;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(shotPlanForMock).toHaveBeenLastCalledWith(CLIP_B);
  });

  // ReframeOverridePanel keeps its override map in `useState`, seeded ONCE
  // (`panels/ReframeOverridePanel.tsx:96`). A new `plan` prop does not reset it,
  // so without a remount an edit made on clip A would be replayed onto clip B —
  // clip B would open already "edited", by shot INDEX, against decisions that
  // were never its own. The container must not let that happen.
  it('does not carry one clip edits over to the next clip', async () => {
    await mount();
    const flip = container.querySelector(
      '[data-shot="0"] button[data-action="flip-speaker"]',
    ) as HTMLButtonElement;
    await act(async () => {
      flip.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.querySelectorAll('[data-changed="yes"]')).toHaveLength(1);

    const select = container.querySelector('select[data-action="clip"]') as HTMLSelectElement;
    await act(async () => {
      select.value = CLIP_B;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // clip B opens CLEAN: no shot marked edited, nothing offered for re-render.
    expect(container.querySelectorAll('[data-changed="yes"]')).toHaveLength(0);
    const rerender = container.querySelector('button[data-action="rerender"]') as HTMLButtonElement;
    expect(rerender.disabled).toBe(true);
  });

  it('shows a loading note until shorts.list settles', async () => {
    let release: (v: unknown) => void = () => {};
    listMock.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    await mount();
    expect(sectionText('loading')).toContain('Looking for');
    expect(section('no-clips')).toBeNull();
    await act(async () => {
      release({ shorts: [] });
    });
    expect(section('loading')).toBeNull();
  });
});

describe('ReframeCorrect — honest empty states', () => {
  it('says the video has no produced clips instead of an empty picker', async () => {
    listMock.mockResolvedValue({ shorts: [] });
    await mount();
    expect(sectionText('no-clips')).toContain('no reframed clips');
    expect(container.querySelector('select[data-action="clip"]')).toBeNull();
    expect(shotPlanForMock).not.toHaveBeenCalled();
  });

  it('tolerates a payload with no shorts array', async () => {
    listMock.mockResolvedValue({});
    await mount();
    expect(sectionText('no-clips')).toContain('no reframed clips');
  });

  it('renders NO correction panel for a clip with no decision sidecar', async () => {
    shotPlanForMock.mockResolvedValue({ plan: null, engine: '', aspect: '' });
    await mount();
    expect(container.querySelector('section.reframe-override')).toBeNull();
    expect(sectionText('no-plan')).toContain('no per-shot');
  });

  it('surfaces a shorts.list failure', async () => {
    listMock.mockRejectedValue(new Error('library unreadable'));
    await mount();
    expect(sectionText('error')).toContain('library unreadable');
  });

  it('surfaces a shotPlanFor failure, including a non-Error rejection', async () => {
    shotPlanForMock.mockRejectedValue('sidecar exploded');
    await mount();
    expect(sectionText('error')).toContain('sidecar exploded');
    expect(container.querySelector('section.reframe-override')).toBeNull();
  });
});

describe('ReframeCorrect — telling the truth about Re-render', () => {
  async function editShotOneAndRerender(): Promise<void> {
    // edit shot 1 (index 0): flip its speaker a -> b
    const flip = container.querySelector(
      '[data-shot="0"] button[data-action="flip-speaker"]',
    ) as HTMLButtonElement;
    await act(async () => {
      flip.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    const rerender = container.querySelector('button[data-action="rerender"]') as HTMLButtonElement;
    expect(rerender.disabled).toBe(false);
    await act(async () => {
      rerender.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
  }

  // The disclosure must be present WHENEVER the panel is, and must name the REAL
  // blocker. A user who edits a shot and presses the panel's own "Re-render"
  // button gets nothing re-encoded; if the UI does not say that before they press
  // it, the mount is a lie.
  it('discloses that corrections are not applied, naming the built export path', async () => {
    await mount();
    const limits = section('limits');
    expect(limits).not.toBeNull();
    expect(limits?.textContent).toContain('not re-encode');
    // the REAL mechanism, so the next reader looks at the wiring, not at a
    // sidecar method that does not need building
    expect(limits?.textContent).toContain('shortmaker.export');
    expect(limits?.textContent).toContain('reframeOverrides');
  });

  // REGRESSION (fails on the previous commit, which printed exactly this advice).
  // `shortmaker.export` WITHOUT `reframeOverrides` re-cuts the clip from scratch,
  // so "re-export the short" is not a remedy — it is data loss dressed as one.
  it('never offers re-exporting the short as a remedy', async () => {
    await mount();
    await editShotOneAndRerender();
    const shown = `${sectionText('limits')} ${sectionText('rerender-note')}`;
    // The retracted sentence, verbatim from the previous commit:
    //   "Re-export the short to pick up a different framing."
    expect(shown).not.toMatch(/re-export the short to pick up/i);
    // …and re-exporting is only ever mentioned as a WARNING, in both places the
    // user reads. Absence alone would pass on a page that simply said nothing,
    // so pin the warning positively too.
    expect(sectionText('limits')).toMatch(/re-exporting the short is not a workaround/i);
    expect(sectionText('rerender-note')).toMatch(/discards these corrections/i);
  });

  it('reports the affected shots on Re-render and states nothing was re-encoded', async () => {
    await mount();
    await editShotOneAndRerender();
    const note = sectionText('rerender-note');
    expect(note).toContain('shot 1');
    expect(note).toContain('nothing has been re-encoded');
  });

  // REGRESSION (fails on the previous commit: the panel handed back indices only
  // and this container rendered no payload, so the corrections died on press).
  it('keeps the corrections as the exact reframeOverrides entry for the clip', async () => {
    await mount();
    expect(section('payload')).toBeNull();
    await editShotOneAndRerender();
    const box = container.querySelector('textarea[data-action="payload"]') as HTMLTextAreaElement;
    expect(JSON.parse(box.value)).toEqual({ [CLIP_A]: [{ index: 0, speaker: 'b' }] });
  });

  it('drops a stale payload when another clip is picked', async () => {
    await mount();
    await editShotOneAndRerender();
    expect(section('payload')).not.toBeNull();
    const select = container.querySelector('select[data-action="clip"]') as HTMLSelectElement;
    await act(async () => {
      select.value = CLIP_B;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(section('payload')).toBeNull();
  });
});
