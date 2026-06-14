// CaptionOverlay.test.tsx — the live caption overlay (P4 §5).
//
// The cue-selection / re-basing / word-highlight math is exported pure and
// tested without React; a handful of render tests (React 18 createRoot + act,
// jsdom) assert which line shows at t, the palette is applied, the overlay
// no-ops on 'none', and the hook-title slot renders.

// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import CaptionOverlay, {
  rebaseCue,
  activeCueIndex,
  activeLine,
  wordColor,
  LINE_GAP_SEC,
  type OverlayWord,
} from './CaptionOverlay';
import { captionVisualFor, REMOTION_CAPTION_TEMPLATES } from '../lib/captionTemplates';
import type { Cue } from '../lib/rpc';
import type { PlayerWindow } from './Player';

// A candidate cut at source 100..130s; cues are SOURCE-absolute.
const WINDOW: PlayerWindow = { start: 100, end: 130 };

function cue(index: number, start: number, end: number, text: string): Cue {
  return { index, start, end, text };
}

// "Hello brave new world" spoken across source 101.0..103.0.
const CUES: Cue[] = [
  cue(1, 101.0, 101.4, 'Hello'),
  cue(2, 101.4, 101.9, 'brave'),
  cue(3, 101.9, 102.4, 'new'),
  cue(4, 102.4, 103.0, 'world'),
];

// ---------------------------------------------------------------------------
// pure: rebaseCue
// ---------------------------------------------------------------------------
describe('rebaseCue', () => {
  it('subtracts window.start so t=0 is the in-point', () => {
    const r = rebaseCue(cue(1, 101, 101.4, 'Hello'), WINDOW)!;
    expect(r.start).toBeCloseTo(1, 6);
    expect(r.end).toBeCloseTo(1.4, 6);
  });

  it('returns null for a cue entirely before the window', () => {
    expect(rebaseCue(cue(1, 90, 95, 'x'), WINDOW)).toBeNull();
  });

  it('returns null for a cue entirely after the window', () => {
    expect(rebaseCue(cue(1, 140, 145, 'x'), WINDOW)).toBeNull();
  });

  it('keeps a cue that overlaps the window edge', () => {
    const r = rebaseCue(cue(1, 99, 101, 'edge'), WINDOW)!;
    expect(r.start).toBeCloseTo(-1, 6);
    expect(r.end).toBeCloseTo(1, 6);
  });
});

// ---------------------------------------------------------------------------
// pure: activeCueIndex
// ---------------------------------------------------------------------------
describe('activeCueIndex', () => {
  const rebased = CUES.map((c) => ({ start: c.start - 100, end: c.end - 100 }));

  it('returns -1 before the first cue starts', () => {
    expect(activeCueIndex(rebased, 0.5)).toBe(-1);
  });

  it('returns the cue containing t', () => {
    expect(activeCueIndex(rebased, 1.5)).toBe(1); // 1.4..1.9 = "brave"
  });

  it('keeps the most recent ended cue between words (micro-gap)', () => {
    // no cue covers t=3.5 (past the last word's end 3.0); the last word stays.
    expect(activeCueIndex(rebased, 3.5)).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// pure: activeLine (which words show at t + highlight state)
// ---------------------------------------------------------------------------
describe('activeLine', () => {
  it('returns the whole spoken phrase as one line (gap <= LINE_GAP_SEC)', () => {
    const line = activeLine(CUES, WINDOW, 1.6); // mid "brave"
    expect(line.map((w) => w.text)).toEqual(['Hello', 'brave', 'new', 'world']);
  });

  it('marks the spoken word active and earlier words spoken', () => {
    const line = activeLine(CUES, WINDOW, 1.6); // "brave" active
    const active = line.find((w) => w.active);
    expect(active?.text).toBe('brave');
    expect(line.find((w) => w.text === 'Hello')?.spoken).toBe(true);
    expect(line.find((w) => w.text === 'new')?.spoken).toBe(false);
    expect(line.find((w) => w.text === 'new')?.active).toBe(false);
  });

  it('returns an empty line before any cue starts', () => {
    expect(activeLine(CUES, WINDOW, 0.2)).toEqual([]);
  });

  it('splits phrases separated by a gap larger than LINE_GAP_SEC', () => {
    const two: Cue[] = [
      cue(1, 101, 101.4, 'first'),
      // big gap (> LINE_GAP_SEC) then a second phrase
      cue(2, 105, 105.4, 'second'),
      cue(3, 105.4, 105.8, 'phrase'),
    ];
    const line = activeLine(two, WINDOW, 5.2); // mid "second"
    expect(line.map((w) => w.text)).toEqual(['second', 'phrase']);
    expect(line.some((w) => w.text === 'first')).toBe(false);
  });

  it('uses LINE_GAP_SEC as the phrase-grouping threshold', () => {
    expect(LINE_GAP_SEC).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// pure: wordColor (palette applied per highlight state)
// ---------------------------------------------------------------------------
describe('wordColor', () => {
  const visual = captionVisualFor('karaoke');
  const base = (over: Partial<OverlayWord>): OverlayWord => ({
    text: 'x',
    start: 0,
    end: 1,
    active: false,
    spoken: false,
    ...over,
  });

  it('uses activeColor for the active word', () => {
    expect(wordColor(base({ active: true }), visual)).toBe(visual.activeColor);
  });

  it('uses spokenColor for already-spoken words', () => {
    expect(wordColor(base({ spoken: true }), visual)).toBe(visual.spokenColor);
  });

  it('uses textColor for upcoming words', () => {
    expect(wordColor(base({}), visual)).toBe(visual.textColor);
  });
});

// ---------------------------------------------------------------------------
// React render (jsdom)
// ---------------------------------------------------------------------------
describe('<CaptionOverlay />', () => {
  let container: HTMLDivElement;
  let root: Root;

  afterEach(() => {
    if (root) act(() => root.unmount());
    if (container) container.remove();
  });

  function render(el: React.ReactElement): void {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => root.render(el));
  }

  it('renders the active line word-by-word at t', () => {
    render(
      <CaptionOverlay cues={CUES} templateId="bold" currentTime={101.6} window={WINDOW} />,
    );
    const words = [...container.querySelectorAll('.caption-overlay__word')].map(
      (w) => w.textContent,
    );
    expect(words).toEqual(['Hello', 'brave', 'new', 'world']);
    expect(container.querySelector('.caption-overlay__word.is-active')?.textContent).toBe('brave');
  });

  it('applies the template palette to the active word colour', () => {
    render(
      <CaptionOverlay cues={CUES} templateId="hormozi" currentTime={101.6} window={WINDOW} />,
    );
    const active = container.querySelector('.caption-overlay__word.is-active') as HTMLElement;
    // hormozi's active colour is the green pop (#22E84F) — palette is applied.
    expect(active.style.color.toLowerCase()).toContain('34, 232, 79');
    expect(active.style.color || REMOTION_CAPTION_TEMPLATES.hormozi.activeColor).toBeTruthy();
  });

  it('reflects the template position via data-position', () => {
    render(
      <CaptionOverlay cues={CUES} templateId="mrbeast" currentTime={101.6} window={WINDOW} />,
    );
    // mrbeast positions captions at the top.
    expect(container.querySelector('.caption-overlay')?.getAttribute('data-position')).toBe('top');
  });

  it('no-ops on the "none" template (renders nothing)', () => {
    render(<CaptionOverlay cues={CUES} templateId="none" currentTime={101.6} window={WINDOW} />);
    expect(container.querySelector('.caption-overlay')).toBeNull();
  });

  it('renders nothing when no caption line is active and there is no hook', () => {
    render(<CaptionOverlay cues={CUES} templateId="bold" currentTime={100.2} window={WINDOW} />);
    expect(container.querySelector('.caption-overlay')).toBeNull();
  });

  it('renders the hook-title slot when provided (even before captions start)', () => {
    render(
      <CaptionOverlay
        cues={CUES}
        templateId="bold"
        currentTime={100.2}
        hookTitle="The big idea"
        window={WINDOW}
      />,
    );
    const hook = container.querySelector('[data-hook-title="true"]');
    expect(hook?.textContent).toBe('The big idea');
  });

  it('updates the active word live as currentTime advances', () => {
    render(<CaptionOverlay cues={CUES} templateId="bold" currentTime={101.2} window={WINDOW} />);
    expect(container.querySelector('.is-active')?.textContent).toBe('Hello');
    act(() =>
      root.render(
        <CaptionOverlay cues={CUES} templateId="bold" currentTime={102.6} window={WINDOW} />,
      ),
    );
    expect(container.querySelector('.is-active')?.textContent).toBe('world');
  });
});
