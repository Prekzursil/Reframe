// @vitest-environment jsdom
//
// nasty_captions.dom.test.tsx — GUI NASTY-INPUT regression (WU-A part 3, GUI leg).
//
// Feeds the REAL CaptionOverlay component (the one the app mounts over the
// preview <video>) deliberately hostile caption data and asserts it degrades
// gracefully: it renders valid DOM, or renders nothing — but NEVER throws,
// loops, or paints corrupted markup. This is the deterministic DOM-level
// complement to the sidecar nasty-input E2E (sidecar/tests/e2e/test_nasty_inputs.py).
//
// Hostile inputs: unicode/RTL/emoji caption text, zero-length cue list, cues
// entirely outside the window, zero-duration + overlapping cues, and a HUGE
// (10k-word) timeline rendered at an arbitrary playhead.

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CaptionOverlay } from '../renderer/src/components/CaptionOverlay';
import type { Cue } from '../renderer/src/lib/rpc';
import type { PlayerWindow } from '../renderer/src/components/Player';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const WINDOW: PlayerWindow = { start: 0, end: 60 };

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
});

function render(cues: Cue[], currentTime: number, win: PlayerWindow = WINDOW): void {
  act(() =>
    root.render(
      <CaptionOverlay cues={cues} templateId="bold" currentTime={currentTime} window={win} />,
    ),
  );
}

describe('CaptionOverlay nasty-input robustness', () => {
  it('renders unicode / RTL / emoji caption text verbatim in the DOM', () => {
    const cues: Cue[] = [
      { index: 1, start: 0.0, end: 0.5, text: 'مرحبا' }, // Arabic (RTL)
      { index: 2, start: 0.5, end: 1.0, text: '世界' }, // CJK
      { index: 3, start: 1.0, end: 1.5, text: '🎬🚀' }, // emoji
      { index: 4, start: 1.5, end: 2.0, text: 'café' }, // combining/accents
    ];
    render(cues, 0.6);
    const words = [...container.querySelectorAll('.caption-overlay__word')].map(
      (w) => w.textContent,
    );
    // The active line groups nearby words; the active word at t=0.6 ('世界') is
    // present and the RTL/emoji/accented neighbours render uncorrupted.
    expect(words).toContain('世界');
    expect(words.some((w) => w === '🎬🚀')).toBe(true);
    expect(container.querySelector('.caption-overlay__word.is-active')?.textContent).toBe('世界');
  });

  it('renders nothing (no crash) for an empty cue list', () => {
    render([], 1.0);
    expect(container.querySelector('.caption-overlay')).toBeNull();
  });

  it('renders nothing when every cue is outside the preview window', () => {
    const cues: Cue[] = [
      { index: 1, start: 120.0, end: 121.0, text: 'way past the window' },
      { index: 2, start: 200.0, end: 201.0, text: 'also out' },
    ];
    render(cues, 1.0);
    expect(container.querySelector('.caption-overlay')).toBeNull();
  });

  it('tolerates zero-duration and overlapping cues without throwing', () => {
    const cues: Cue[] = [
      { index: 1, start: 1.0, end: 1.0, text: 'zero-dur' }, // start === end
      { index: 2, start: 0.9, end: 1.4, text: 'overlap-a' },
      { index: 3, start: 1.0, end: 1.2, text: 'overlap-b' },
    ];
    // The render itself is the assertion: a degenerate cue must not blow up the
    // active-line grouping. It produces either a valid overlay or nothing.
    expect(() => render(cues, 1.0)).not.toThrow();
    const overlay = container.querySelector('.caption-overlay');
    if (overlay) {
      expect(container.querySelectorAll('.caption-overlay__word').length).toBeGreaterThan(0);
    }
  });

  it('handles a huge (10k-word) timeline at an arbitrary playhead', () => {
    // 10k words grouped into 10-word phrases. Within a phrase words are
    // back-to-back (< LINE_GAP_SEC=0.8); between phrases there is a >0.8s gap so
    // the active-line grouping breaks (realistic caption cadence). The overlay
    // must paint ONLY the active phrase, never the whole 10k timeline.
    const PHRASE = 10;
    const cues: Cue[] = Array.from({ length: 10_000 }, (_, i) => {
      const phrase = Math.floor(i / PHRASE);
      const within = i % PHRASE;
      const start = phrase * 6.0 + within * 0.3; // 0.3s words; 6s phrase stride => >0.8s gap
      return { index: i + 1, start, end: start + 0.25, text: `w${i}` };
    });
    // Playhead deep inside the timeline (~phrase 50). Rendering must stay bounded.
    expect(() => render(cues, 300.0)).not.toThrow();
    const painted = container.querySelectorAll('.caption-overlay__word').length;
    // A single active phrase is a small bounded run, never the whole 10k list.
    expect(painted).toBeGreaterThan(0);
    expect(painted).toBeLessThanOrEqual(PHRASE);
  });
});
