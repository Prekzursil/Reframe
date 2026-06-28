// CandidateReview.test.tsx — behavioral tests for the review panel wrapper.
// Mounts CandidateReview directly (real Player + CaptionOverlay under jsdom) and
// exercises: the null-render guard (empty list), the preview + markers, the
// hookTitle-off branch (overlay slot gets no title), and BOTH sort toggle
// handlers (Rank and Virality).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { CandidateReview } from './CandidateReview';
import {
  type Candidate,
  type ReviewItem,
  type ShortMakerControls,
  DEFAULT_CONTROLS,
  candidateId,
} from './shortMakerLogic';
import type { CandidateSort } from './shortMakerPresets';

// jsdom lacks HTMLMediaElement playback; the preview Player only touches these.
beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn(() => Promise.resolve()),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value: vi.fn(),
  });
});

function cand(over: Partial<Candidate> = {}): Candidate {
  return {
    rank: 1,
    start: 100,
    end: 130,
    durationSec: 30,
    hook: 'Big idea',
    why: 'why',
    score: 90,
    sourceStart: 100,
    ...over,
  };
}

function item(over: Partial<Candidate> = {}): ReviewItem {
  const c = cand(over);
  return { id: candidateId(c), original: c, current: c, status: 'pending' };
}

describe('<CandidateReview />', () => {
  let container: HTMLDivElement;
  let root: Root;
  let setSortMode: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    setSortMode = vi.fn();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function mount(opts: {
    items: ReviewItem[];
    selected: ReviewItem | null;
    sortMode?: CandidateSort;
    controls?: Partial<ShortMakerControls>;
  }) {
    const controls: ShortMakerControls = { ...DEFAULT_CONTROLS, ...opts.controls };
    act(() => {
      root.render(
        <CandidateReview
          items={opts.items}
          selectedId={opts.selected?.id ?? null}
          selected={opts.selected}
          controls={controls}
          videoId="v1"
          cues={[]}
          currentTime={0}
          playerEpoch={0}
          sortMode={opts.sortMode ?? 'rank'}
          playerRef={React.createRef()}
          onKeyDown={vi.fn()}
          onTimeUpdate={vi.fn()}
          setSortMode={setSortMode}
          setSelectedId={vi.fn()}
          onApprove={vi.fn()}
          onDiscard={vi.fn()}
          onReinstate={vi.fn()}
          onNudge={vi.fn()}
          onReset={vi.fn()}
        />,
      );
    });
  }

  it('renders nothing when there are no items', () => {
    mount({ items: [], selected: null });
    expect(container.querySelector('.sm-review')).toBeNull();
  });

  it('renders the preview window + in/out markers for the selected item', () => {
    const it = item({ sourceStart: 100, end: 130 });
    mount({ items: [it], selected: it });
    const preview = container.querySelector('.sm-preview') as HTMLElement;
    expect(preview).toBeTruthy();
    expect(preview.getAttribute('data-window-start')).toBe('100');
    expect(preview.getAttribute('data-window-end')).toBe('130');
    expect(container.querySelector('.sm-marker-in')?.textContent).toContain('1:40');
  });

  it('renders the live caption overlay with the hook title when hookTitle is ON', () => {
    const it = item();
    mount({ items: [it], selected: it, controls: { captionStyle: 'bold', hookTitle: true } });
    // The hook title slot renders even with no active word cue (hookTitle ON).
    expect(container.querySelector('[data-hook-title="true"]')?.textContent).toBe('Big idea');
  });

  it('omits the hook title slot when hookTitle is OFF (branch coverage)', () => {
    const it = item();
    mount({ items: [it], selected: it, controls: { captionStyle: 'bold', hookTitle: false } });
    // The CaptionOverlay JSX is still reached (the hookTitle ternary's false arm
    // is taken) but with no hook title there is no title element rendered.
    expect(container.querySelector('[data-hook-title="true"]')).toBeNull();
  });

  it('does not render the overlay for the "none" caption style', () => {
    const it = item();
    mount({ items: [it], selected: it, controls: { captionStyle: 'none' } });
    expect(container.querySelector('.caption-overlay')).toBeNull();
  });

  it('the Rank and Virality sort buttons each invoke setSortMode', () => {
    const it = item();
    mount({ items: [it], selected: it, sortMode: 'virality' });
    const group = container.querySelector('[aria-label="Sort candidates"]')!;
    const [rankBtn, viralityBtn] = [...group.querySelectorAll('button')] as HTMLButtonElement[];
    act(() => rankBtn.click());
    expect(setSortMode).toHaveBeenCalledWith('rank');
    act(() => viralityBtn.click());
    expect(setSortMode).toHaveBeenCalledWith('virality');
    // sortMode=virality => the virality button is the active/pressed one.
    expect(viralityBtn.getAttribute('aria-pressed')).toBe('true');
    expect(rankBtn.getAttribute('aria-pressed')).toBe('false');
  });

  it('advertises the single-letter shortcuts to AT and exposes the legend (F4)', () => {
    const it = item();
    mount({ items: [it], selected: it });
    const group = container.querySelector('.sm-review') as HTMLElement;
    // The keyboard shortcuts are discoverable via aria-keyshortcuts on the group.
    expect(group.getAttribute('aria-keyshortcuts')).toBe('J K Space A X ArrowLeft ArrowRight');
    // The visible legend is no longer hidden from assistive tech.
    const legend = container.querySelector('.sm-kbd-hints') as HTMLElement;
    expect(legend.getAttribute('aria-hidden')).toBeNull();
    expect(legend.getAttribute('aria-label')).toBe('Keyboard shortcuts');
  });
});
