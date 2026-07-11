// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorProvider, useEditor } from '../EditorContext';
import { CaptionStage } from './CaptionStage';
import type { EditorSeed } from '../../lib/editorState';
import { DEFAULT_CAPTION_DESIGN } from '../../lib/captionDesign';
import type { Cue } from '../../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const cue = (index: number, start: number, end: number, text: string): Cue => ({
  index,
  start,
  end,
  text,
});
const PHRASE: Cue[] = [cue(0, 2, 3, 'Hello'), cue(1, 3, 4, 'there'), cue(2, 4, 5, 'world')];

function setReducedMotion(reduce: boolean): void {
  (window as unknown as { matchMedia: (q: string) => MediaQueryList }).matchMedia = ((q: string) =>
    ({
      matches: reduce,
      media: q,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList) as unknown as (q: string) => MediaQueryList;
}

function Probe(): React.ReactElement {
  const { state } = useEditor();
  return (
    <div>
      <span data-testid="playhead">{state.playhead}</span>
      <span data-testid="box-y">{state.design.box.y}</span>
    </div>
  );
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (window as unknown as { matchMedia?: unknown }).matchMedia;
});

function render(seed: EditorSeed): void {
  act(() => {
    root.render(
      <EditorProvider seed={seed}>
        <CaptionStage />
        <Probe />
      </EditorProvider>,
    );
  });
}

/** Advance the shared playhead by firing the Player's native `timeupdate`. */
function seekTo(t: number): void {
  const video = container.querySelector('video');
  if (!video) throw new Error('no video');
  Object.defineProperty(video, 'currentTime', { configurable: true, get: () => t });
  act(() => {
    video.dispatchEvent(new Event('timeupdate'));
  });
}

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);

describe('CaptionStage', () => {
  it('shows the "No captions" hint for the none style', () => {
    setReducedMotion(false);
    render({
      video: { videoId: 'v1', window: { start: 0, end: 10 } },
      cues: [],
      design: { ...DEFAULT_CAPTION_DESIGN, style: 'none' },
    });
    expect(q('.caption-stage__hint')?.textContent).toBe('No captions');
    expect(q('.caption-stage__line')).toBeNull();
  });

  it('shows the pre-transcript preview hint before any word is active', () => {
    setReducedMotion(false);
    render({
      video: { videoId: 'v1', window: { start: 0, end: 10 } },
      cues: PHRASE,
      design: { ...DEFAULT_CAPTION_DESIGN, style: 'hormozi' },
    });
    // initial playhead = window.start = 0, before the first cue (starts at 2s)
    expect(q('.caption-stage__hint')?.textContent).toBe('Caption preview');
    expect(q('.caption-stage__line')).toBeNull();
  });

  it('renders the live word line with the karaoke pop armed (motion allowed)', () => {
    setReducedMotion(false);
    render({
      video: { videoId: 'v1', window: { start: 0, end: 10 } },
      cues: PHRASE,
      design: { ...DEFAULT_CAPTION_DESIGN, style: 'opusclip-karaoke' },
    });
    seekTo(3.5);
    expect(q('[data-testid="playhead"]')?.textContent).toBe('3.5');
    const words = container.querySelectorAll('.caption-stage__word');
    expect(words).toHaveLength(3);
    expect(container.querySelectorAll('.caption-stage__word.is-active')).toHaveLength(1);
    expect(q('.caption-stage__sample')?.getAttribute('data-karaoke-pop')).toBe('true');
  });

  it('leaves the karaoke pop OFF under prefers-reduced-motion', () => {
    setReducedMotion(true);
    render({
      video: { videoId: 'v1', window: { start: 0, end: 10 } },
      cues: PHRASE,
      design: { ...DEFAULT_CAPTION_DESIGN, style: 'opusclip-karaoke' },
    });
    seekTo(3.5);
    expect(q('.caption-stage__line')).not.toBeNull();
    expect(q('.caption-stage__sample')?.hasAttribute('data-karaoke-pop')).toBe(false);
  });

  it('renders a non-karaoke style with no pop attribute', () => {
    setReducedMotion(false);
    render({
      video: { videoId: 'v1', window: { start: 0, end: 10 } },
      cues: PHRASE,
      design: { ...DEFAULT_CAPTION_DESIGN, style: 'hormozi' },
    });
    seekTo(3.5);
    expect(container.querySelectorAll('.caption-stage__word')).toHaveLength(3);
    expect(q('.caption-stage__sample')?.hasAttribute('data-karaoke-pop')).toBe(false);
  });

  it('moves the caption region from the keyboard (on-canvas, WCAG 2.1.1)', () => {
    setReducedMotion(false);
    render({
      video: { videoId: 'v1', window: { start: 0, end: 10 } },
      cues: PHRASE,
      design: { ...DEFAULT_CAPTION_DESIGN, style: 'hormozi' },
    });
    const box = q('[data-testid="caption-box"]');
    if (!box) throw new Error('no caption box');
    act(() => {
      box.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    });
    const y = Number(q('[data-testid="box-y"]')?.textContent);
    expect(y).toBeGreaterThan(0.76);
  });
});
