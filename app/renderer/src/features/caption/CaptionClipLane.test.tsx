// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorProvider, useEditor } from '../EditorContext';
import { CaptionClipLane } from './CaptionClipLane';
import type { EditorSeed } from '../../lib/editorState';
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
const CUES: Cue[] = [cue(1, 2, 3, 'Alpha'), cue(2, 6, 7, 'Beta'), cue(3, 10, 11, 'Gamma')];
const SEED: EditorSeed = { video: { videoId: 'v1', window: { start: 0, end: 20 } }, cues: CUES };

function Probe(): React.ReactElement {
  const { state } = useEditor();
  return (
    <div>
      <span data-testid="playhead">{state.playhead}</span>
      <span data-testid="sel">{String(state.selection)}</span>
      <span data-testid="c0start">{state.cues[0]?.start}</span>
      <span data-testid="c0end">{state.cues[0]?.end}</span>
      <span data-testid="c1start">{state.cues[1]?.start}</span>
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
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);
const num = (testid: string): number => Number(q(`[data-testid="${testid}"]`)?.textContent);

function render(seed: EditorSeed = SEED): void {
  act(() => {
    root.render(
      <EditorProvider seed={seed}>
        <CaptionClipLane />
        <Probe />
      </EditorProvider>,
    );
  });
}

function keyClip(pos: number, key: string, shiftKey = false): void {
  const clip = q(`[data-clip="${pos}"]`);
  if (!clip) throw new Error(`no clip ${pos}`);
  act(() => {
    clip.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true }));
  });
}

describe('CaptionClipLane', () => {
  it('shows an empty prompt when there are no cues', () => {
    render({ video: { videoId: 'v1', window: { start: 0, end: 20 } }, cues: [] });
    expect(q('.caption-clip-lane__empty')).not.toBeNull();
    expect(q('.caption-clip')).toBeNull();
  });

  it('renders one focusable clip per cue plus the playhead', () => {
    render();
    expect(container.querySelectorAll('.caption-clip')).toHaveLength(3);
    expect(q('[data-testid="clip-playhead"]')).not.toBeNull();
    expect(q('[data-clip="0"]')?.getAttribute('aria-label')).toBe('Caption 1: Alpha');
  });

  it('selects a clip on click', () => {
    render();
    act(() => q<HTMLButtonElement>('[data-clip="1"]')?.click());
    expect(num('sel')).toBe(1);
    expect(q('[data-clip="1"]')?.classList.contains('is-selected')).toBe(true);
  });

  it('seeks the playhead to the clip start on Enter', () => {
    render();
    keyClip(0, 'Enter');
    expect(num('playhead')).toBe(2);
    expect(num('sel')).toBe(0);
  });

  it('seeks on Space as well', () => {
    render();
    keyClip(1, ' ');
    expect(num('playhead')).toBe(6);
  });

  it('moves a clip later with ArrowRight (neighbor-clamped)', () => {
    render();
    keyClip(0, 'ArrowRight');
    expect(num('c0start')).toBeGreaterThan(2);
    expect(num('c0end')).toBeGreaterThan(3);
  });

  it('moves a clip earlier with ArrowLeft', () => {
    render();
    keyClip(1, 'ArrowLeft');
    expect(num('c1start')).toBeLessThan(6);
  });

  it('resizes the clip out-point with Shift+ArrowRight (start unchanged)', () => {
    render();
    keyClip(0, 'ArrowRight', true);
    expect(num('c0end')).toBeGreaterThan(3);
    expect(num('c0start')).toBe(2);
  });

  it('ignores non-arrow, non-seek keys', () => {
    render();
    keyClip(0, 'Home');
    expect(num('c0start')).toBe(2);
    expect(num('playhead')).toBe(0);
  });
});
