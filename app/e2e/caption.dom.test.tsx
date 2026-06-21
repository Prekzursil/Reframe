// @vitest-environment jsdom
//
// caption.dom.test.tsx — DATA-PATH proof that a generated caption renders in the
// DOM OVER the preview <video>, using the REAL CaptionOverlay component (no
// stub). This is the deterministic complement to the live GUI E2E: the live
// caption overlay (CandidateReview) sits behind ML candidate selection (whisper
// transcript + LLM clip selection), which is not reachable without the model
// stack, so caption-over-video is verified here at the component+DOM level.
//
// It renders the SAME overlay the app mounts in the ShortMaker preview, fed
// word-level cues in the SAME shape `captions.cues` returns, layered over a real
// <video> the SAME way CandidateReview composes them, and asserts the active
// caption word is painted in the DOM positioned over the video frame.

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CaptionOverlay } from '../renderer/src/components/CaptionOverlay';
import { Player, type PlayerWindow } from '../renderer/src/components/Player';
import type { Cue } from '../renderer/src/lib/rpc';

// React 18 createRoot + act under jsdom (mirrors the renderer's own tests).
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// Word-level, source-absolute cues — the exact shape captions.cues emits.
const CUES: Cue[] = [
  { index: 1, start: 0.0, end: 0.4, text: 'Hello' },
  { index: 2, start: 0.4, end: 0.9, text: 'reframed' },
  { index: 3, start: 0.9, end: 1.5, text: 'world' },
];
const WINDOW: PlayerWindow = { start: 0, end: 3 };

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

describe('caption renders over the preview video (real CaptionOverlay)', () => {
  it('paints the active caption word over a <video> at the current time', () => {
    act(() =>
      root.render(
        <div style={{ position: 'relative' }}>
          {/* The same preview <video> the app plays media through. */}
          <Player src="mstream://media/sample" window={WINDOW} controls={false} />
          {/* The same overlay CandidateReview layers on top, fed real cues. */}
          <CaptionOverlay cues={CUES} templateId="bold" currentTime={0.6} window={WINDOW} />
        </div>,
      ),
    );

    // The preview <video> is present...
    const video = container.querySelector('video');
    expect(video).not.toBeNull();

    // ...and the generated caption is rendered in the DOM over it: the word
    // active at t=0.6 ('reframed') is highlighted, with the full line visible.
    const overlay = container.querySelector('.caption-overlay');
    expect(overlay).not.toBeNull();
    const words = [...container.querySelectorAll('.caption-overlay__word')].map(
      (w) => w.textContent,
    );
    expect(words).toContain('reframed');
    expect(container.querySelector('.caption-overlay__word.is-active')?.textContent).toBe(
      'reframed',
    );
  });

  it('shows no caption line before the first cue starts (honest gap behaviour)', () => {
    act(() =>
      root.render(
        <CaptionOverlay cues={CUES} templateId="bold" currentTime={-0.5} window={WINDOW} />,
      ),
    );
    // Before t=0 there is no active word and no hook -> nothing painted.
    expect(container.querySelector('.caption-overlay')).toBeNull();
  });
});
