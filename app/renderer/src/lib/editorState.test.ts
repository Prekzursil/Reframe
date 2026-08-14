import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import {
  type CropFraming,
  type EditorAction,
  type EditorState,
  clampSelection,
  cropFraming,
  cropViewport,
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

// The crop rect the REFRAME phase computes, expressed in the SAME shape the
// per-shot override layer and the sidecar already use (`Crop = [x, y, w, h]` in
// source pixels, reframeOverride.ts). These tests pin the two doors into state
// (seed + `setCropPlan`) and the one read a preview needs (`cropViewport`), so a
// removed normalisation or a removed selector goes red here.
const FRAMING: CropFraming = { crop: [100, 0, 600, 1080], sourceWidth: 1920, sourceHeight: 1080 };

describe('cropFraming', () => {
  it('rejects a source frame that is not a positive finite size', () => {
    expect(cropFraming([0, 0, 10, 10], 0, 100)).toBeNull();
    expect(cropFraming([0, 0, 10, 10], 100, 0)).toBeNull();
    expect(cropFraming([0, 0, 10, 10], Number.NaN, 100)).toBeNull();
    expect(cropFraming([0, 0, 10, 10], 100, Number.POSITIVE_INFINITY)).toBeNull();
  });

  it('rejects a rect that is degenerate or not finite', () => {
    expect(cropFraming([Number.NaN, 0, 10, 10], 100, 100)).toBeNull();
    expect(cropFraming([0, Number.NaN, 10, 10], 100, 100)).toBeNull();
    expect(cropFraming([0, 0, 0, 10], 100, 100)).toBeNull();
    expect(cropFraming([0, 0, 10, 0], 100, 100)).toBeNull();
  });

  it('keeps an in-frame rect and records the frame it is measured against', () => {
    expect(cropFraming([100, 0, 600, 1080], 1920, 1080)).toEqual(FRAMING);
  });

  it('pulls an off-frame rect fully inside the source frame', () => {
    expect(cropFraming([-50, -50, 4000, 4000], 1920, 1080)?.crop).toEqual([0, 0, 1920, 1080]);
  });
});

describe('crop framing carried by the editor state', () => {
  it('seeds a usable framing through initialEditorState', () => {
    const state = initialEditorState({
      video: { videoId: 'v1', window: WINDOW },
      cropPlan: { engine: 'reframe_multispeaker', framing: FRAMING },
    });
    expect(state.cropPlan?.framing).toEqual(FRAMING);
    expect(cropViewport(state)).toEqual({ x: 100 / 1920, y: 0, width: 600 / 1920, height: 1 });
  });

  it('seeds a plan whose framing is unusable WITHOUT the framing', () => {
    const state = initialEditorState({
      video: { videoId: 'v1', window: WINDOW },
      cropPlan: { engine: 'verthor', framing: { ...FRAMING, sourceWidth: 0 } },
    });
    expect(state.cropPlan?.engine).toBe('verthor');
    expect(state.cropPlan?.framing).toBeUndefined();
    expect(cropViewport(state)).toBeNull();
  });

  it('setCropPlan stores a framing a preview can read back as fractions', () => {
    const next = editorReducer(base(), {
      type: 'setCropPlan',
      cropPlan: { engine: 'reframe_multispeaker', framing: FRAMING },
    });
    expect(cropViewport(next)).toEqual({ x: 100 / 1920, y: 0, width: 600 / 1920, height: 1 });
  });

  it('setCropPlan clamps an off-frame rect instead of storing it raw', () => {
    const next = editorReducer(base(), {
      type: 'setCropPlan',
      cropPlan: {
        framing: { crop: [-400, -400, 600, 1080], sourceWidth: 1920, sourceHeight: 1080 },
      },
    });
    expect(next.cropPlan?.framing?.crop).toEqual([0, 0, 600, 1080]);
  });

  it('setCropPlan drops an unusable framing rather than storing a NaN preview', () => {
    const next = editorReducer(base(), {
      type: 'setCropPlan',
      cropPlan: { engine: 'verthor', framing: { ...FRAMING, crop: [0, 0, 0, 1080] } },
    });
    expect(next.cropPlan?.engine).toBe('verthor');
    expect(next.cropPlan?.framing).toBeUndefined();
    expect(cropViewport(next)).toBeNull();
  });

  it('setCropPlan keeps the very same plan object when nothing needs normalising', () => {
    const plan = { engine: 'verthor', framing: FRAMING };
    expect(editorReducer(base(), { type: 'setCropPlan', cropPlan: plan }).cropPlan).toBe(plan);
  });

  it('setCropPlan clears the plan back to null', () => {
    const seeded = base({ cropPlan: { engine: 'verthor', framing: FRAMING } });
    expect(editorReducer(seeded, { type: 'setCropPlan', cropPlan: null }).cropPlan).toBeNull();
  });

  it('cropViewport is null with no plan at all and with a plan that has no rect', () => {
    expect(cropViewport(base())).toBeNull();
    expect(cropViewport(base({ cropPlan: { engine: 'verthor' } }))).toBeNull();
  });
});

// The THIRD door. `initialEditorState` and the `setCropPlan` reducer case both
// normalise, but an `EditorState` assembled directly does not pass through
// either — and that is not a hypothetical shape: it is the shape `base()` uses
// on every line above. `cropViewport` therefore validates the numbers it is
// about to divide by instead of trusting an invariant it cannot enforce, so a
// state built outside this module can never push Infinity or NaN into a preview.
describe('cropViewport on a hand-built state', () => {
  it('returns null for a framing whose source frame is not positive and finite', () => {
    expect(
      cropViewport(base({ cropPlan: { framing: { ...FRAMING, sourceWidth: 0 } } })),
    ).toBeNull();
    expect(
      cropViewport(base({ cropPlan: { framing: { ...FRAMING, sourceHeight: Number.NaN } } })),
    ).toBeNull();
  });

  it('returns null for a framing whose rect is degenerate or not finite', () => {
    expect(
      cropViewport(base({ cropPlan: { framing: { ...FRAMING, crop: [0, 0, 0, 1080] } } })),
    ).toBeNull();
    expect(
      cropViewport(
        base({ cropPlan: { framing: { ...FRAMING, crop: [0, Number.NaN, 600, 1080] } } }),
      ),
    ).toBeNull();
  });

  it('pulls an off-frame hand-built rect inside the frame instead of reporting it out of bounds', () => {
    const framing: CropFraming = {
      crop: [-400, -400, 600, 1080],
      sourceWidth: 1920,
      sourceHeight: 1080,
    };
    expect(cropViewport(base({ cropPlan: { framing } }))).toEqual({
      x: 0,
      y: 0,
      width: 600 / 1920,
      height: 1,
    });
  });
});

// ANCHOR-ROT GUARD. This module's docstrings are its actual deliverable: the
// crop container is dead in production, so what ships is the map telling the
// next author where the adoption blockers live. A cross-file `path:line` pin is
// the one citation form this repo has watched rot repeatedly, and NOTHING
// validates these: `C13-code-anchor` in `docs/validation/tools/`
// only matches citations whose TARGET is a `docs/**.md` file, and its own
// comment says the scan covers "docs->docs only" while citations from
// application source into other source are "covered by nothing". Six of the
// files this module cites are surfaces concurrent lanes are editing right now,
// so a line pin here is stale on someone else's next commit and no gate says so.
// Symbols move with their code; line numbers do not. This test is that gate.
describe('editorState docstrings (anchor-rot guard)', () => {
  it('cites symbols, never a bare cross-file source line number', () => {
    const source = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), 'editorState.ts'),
      'utf8',
    );
    // e.g. `views/Caption.tsx:110` or `lib/directorHandoff.ts:109` — a pin that
    // silently retargets the moment the cited file gains or loses a line above.
    const linePins = source.match(/[A-Za-z0-9_/.-]+\.tsx?:\d+/g) ?? [];
    expect(linePins).toEqual([]);
  });
});
