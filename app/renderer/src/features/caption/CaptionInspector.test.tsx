// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { EditorProvider, useEditor } from '../EditorContext';
import { CaptionInspector } from './CaptionInspector';
import type { EditorSeed } from '../../lib/editorState';
import { DEFAULT_CAPTION_DESIGN } from '../../lib/captionDesign';
import type { Cue } from '../../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const onGenerate = vi.fn();

const cue = (index: number, start: number, end: number, text: string): Cue => ({
  index,
  start,
  end,
  text,
});
const CUES: Cue[] = [cue(0, 2, 3, 'Hello'), cue(1, 3, 4, 'world')];

function Probe(): React.ReactElement {
  const { state } = useEditor();
  return (
    <div>
      <span data-testid="style">{state.design.style}</span>
      <span data-testid="has-override">{state.design.override ? 'yes' : 'no'}</span>
    </div>
  );
}

beforeEach(() => {
  onGenerate.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);

function render(seed: EditorSeed, props: Parameters<typeof CaptionInspector>[0] = {}): void {
  act(() => {
    root.render(
      <EditorProvider seed={seed}>
        <CaptionInspector {...props} />
        <Probe />
      </EditorProvider>,
    );
  });
}

const READY: EditorSeed = {
  video: { videoId: 'v1', window: { start: 0, end: 10 } },
  cues: CUES,
  design: { ...DEFAULT_CAPTION_DESIGN, style: 'hormozi' },
};
const EMPTY: EditorSeed = { video: { videoId: 'v1', window: { start: 0, end: 10 } }, cues: [] };

describe('CaptionInspector transcript gate', () => {
  it('shows the "generate captions first" state with no transcript', () => {
    render(EMPTY, { onGenerate });
    expect(q('.caption-inspector__empty-title')?.textContent).toBe('Generate captions first');
    const btn = q<HTMLButtonElement>('.caption-inspector__generate');
    expect(btn?.textContent).toBe('Generate captions');
    expect(btn?.disabled).toBe(false);
    expect(q('.caption-gallery')).toBeNull();
    act(() => btn?.click());
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it('disables the generate button while a request is in flight', () => {
    render(EMPTY, { onGenerate, generating: true });
    const btn = q<HTMLButtonElement>('.caption-inspector__generate');
    expect(btn?.textContent).toBe('Generating…');
    expect(btn?.disabled).toBe(true);
  });
});

describe('CaptionInspector editing surface (transcript ready)', () => {
  it('composes the gallery, customizer, and delivery choice', () => {
    render(READY);
    expect(q('.caption-gallery')).not.toBeNull();
    expect(q('.caption-customizer')).not.toBeNull();
    expect(q('.caption-delivery')).not.toBeNull();
    expect(q('.caption-inspector__empty')).toBeNull();
  });

  it('dispatches a style change from the gallery into the shared state', () => {
    render(READY);
    act(() => q<HTMLButtonElement>('.caption-gallery__toggle')?.click()); // expand
    act(() => q<HTMLButtonElement>('[data-style="serif"]')?.click());
    expect(q('[data-testid="style"]')?.textContent).toBe('serif');
  });

  it('dispatches a customizer override into the shared state', () => {
    render(READY);
    expect(q('[data-testid="has-override"]')?.textContent).toBe('no');
    act(() => q<HTMLButtonElement>('.caption-customizer__toggle')?.click()); // open disclosure
    act(() => q<HTMLButtonElement>('.caption-customizer__swatch[data-color="#FFD700"]')?.click());
    expect(q('[data-testid="has-override"]')?.textContent).toBe('yes');
  });

  it('drives the guarded burn/soft delivery choice locally', () => {
    render(READY);
    expect(q('.caption-delivery__note')?.classList.contains('is-warning')).toBe(false);
    act(() => {
      const opts = container.querySelectorAll<HTMLButtonElement>('.caption-delivery__option');
      opts[1].click(); // Burn in
    });
    expect(q('.caption-delivery__note')?.classList.contains('is-warning')).toBe(true);
  });
});
