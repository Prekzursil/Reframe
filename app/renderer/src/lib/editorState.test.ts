import { describe, expect, it } from 'vitest';
import {
  type EditorAction,
  type EditorState,
  clampSelection,
  editorReducer,
  initialEditorState,
  transcriptReady,
} from './editorState';
import { DEFAULT_CAPTION_DESIGN } from './captionDesign';
import { bandBox } from './captionPosition';
import type { Cue } from './rpc';

const WINDOW = { start: 2, end: 8 };
const cue = (index: number, start: number, end: number, text: string): Cue => ({
  index,
  start,
  end,
  text,
});
const CUES: Cue[] = [cue(0, 2, 3, 'Hello'), cue(1, 3, 4, 'there'), cue(2, 4, 5, 'world')];

function base(overrides: Partial<EditorState> = {}): EditorState {
  return {
    video: { videoId: 'v1', window: WINDOW },
    cues: CUES,
    cropPlan: null,
    design: DEFAULT_CAPTION_DESIGN,
    playhead: 2,
    selection: null,
    ...overrides,
  };
}

describe('initialEditorState', () => {
  it('seeds playhead at the window in-point with empty defaults', () => {
    const state = initialEditorState({ video: { videoId: 'v1', window: WINDOW } });
    expect(state.playhead).toBe(2);
    expect(state.cues).toEqual([]);
    expect(state.cropPlan).toBeNull();
    expect(state.design).toBe(DEFAULT_CAPTION_DESIGN);
    expect(state.selection).toBeNull();
  });

  it('honours a full seed (cues, cropPlan, design)', () => {
    const design = { ...DEFAULT_CAPTION_DESIGN, style: 'serif' };
    const cropPlan = { engine: 'verthor', keyframes: [] };
    const state = initialEditorState({
      video: { src: 'file.mp4', window: WINDOW },
      cues: CUES,
      cropPlan,
      design,
    });
    expect(state.cues).toBe(CUES);
    expect(state.cropPlan).toBe(cropPlan);
    expect(state.design).toBe(design);
  });
});

describe('transcriptReady', () => {
  it('is false with no cues and true with cues', () => {
    expect(transcriptReady(base({ cues: [] }))).toBe(false);
    expect(transcriptReady(base({ cues: CUES }))).toBe(true);
  });
});

describe('clampSelection', () => {
  it('maps a null request to null', () => {
    expect(clampSelection(null, 3)).toBeNull();
  });
  it('rejects a non-integer index', () => {
    expect(clampSelection(1.5, 3)).toBeNull();
  });
  it('rejects a negative index', () => {
    expect(clampSelection(-1, 3)).toBeNull();
  });
  it('rejects an out-of-range index', () => {
    expect(clampSelection(5, 3)).toBeNull();
  });
  it('keeps a valid index', () => {
    expect(clampSelection(1, 3)).toBe(1);
  });
});

describe('editorReducer', () => {
  it('setPlayhead replaces the playhead immutably', () => {
    const prev = base();
    const next = editorReducer(prev, { type: 'setPlayhead', playhead: 5 });
    expect(next.playhead).toBe(5);
    expect(next).not.toBe(prev);
    expect(prev.playhead).toBe(2);
  });

  it('setCues replaces cues and keeps a still-valid selection', () => {
    const next = editorReducer(base({ selection: 1 }), { type: 'setCues', cues: CUES });
    expect(next.cues).toBe(CUES);
    expect(next.selection).toBe(1);
  });

  it('setCues drops a now-out-of-range selection', () => {
    const next = editorReducer(base({ selection: 2 }), {
      type: 'setCues',
      cues: [cue(0, 2, 3, 'only')],
    });
    expect(next.selection).toBeNull();
  });

  it('setVideo swaps the media and reseats the playhead to the new in-point', () => {
    const next = editorReducer(base(), {
      type: 'setVideo',
      video: { videoId: 'v2', window: { start: 10, end: 20 } },
    });
    expect(next.video.videoId).toBe('v2');
    expect(next.playhead).toBe(10);
  });

  it('setDesign replaces the whole design', () => {
    const design = { ...DEFAULT_CAPTION_DESIGN, style: 'hormozi' };
    const next = editorReducer(base(), { type: 'setDesign', design });
    expect(next.design).toBe(design);
  });

  it('setStyle updates only the style slice', () => {
    const next = editorReducer(base(), { type: 'setStyle', style: 'serif' });
    expect(next.design.style).toBe('serif');
    expect(next.design.box).toEqual(DEFAULT_CAPTION_DESIGN.box);
  });

  it('setOverride updates only the override slice (incl. clearing to undefined)', () => {
    const withOverride = editorReducer(base(), {
      type: 'setOverride',
      override: { uppercase: true },
    });
    expect(withOverride.design.override).toEqual({ uppercase: true });
    const cleared = editorReducer(withOverride, { type: 'setOverride', override: undefined });
    expect(cleared.design.override).toBeUndefined();
  });

  it('setBox updates only the box slice', () => {
    const box = bandBox('top');
    const next = editorReducer(base(), { type: 'setBox', box });
    expect(next.design.box).toBe(box);
    expect(next.design.style).toBe(DEFAULT_CAPTION_DESIGN.style);
  });

  it('selectCue clamps the requested index against the cue list', () => {
    expect(editorReducer(base(), { type: 'selectCue', index: 1 }).selection).toBe(1);
    expect(editorReducer(base(), { type: 'selectCue', index: 9 }).selection).toBeNull();
    expect(editorReducer(base(), { type: 'selectCue', index: null }).selection).toBeNull();
  });

  it('setCropPlan carries the cross-phase crop plan', () => {
    const cropPlan = { engine: 'reframe_multispeaker', keyframes: [{ t: 0 }] };
    const next = editorReducer(base(), { type: 'setCropPlan', cropPlan });
    expect(next.cropPlan).toBe(cropPlan);
  });

  it('is a no-op for an unknown action', () => {
    const prev = base();
    const next = editorReducer(prev, { type: 'bogus' } as unknown as EditorAction);
    expect(next).toBe(prev);
  });
});
