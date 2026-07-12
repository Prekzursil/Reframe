// directorHandoff.test.ts — the pure per-phase hand-off model (v1.5 Director).

import { describe, expect, it } from 'vitest';
import type { DirectorOpKind } from './directorTypes';
import { egressWarning } from './directorTypes';
import type { CropPlan } from './editorState';
import { type EditorState, initialEditorState } from './editorState';
import {
  HANDOFF_ROUTES,
  type HandoffPhase,
  TRUST_REVERSIBLE,
  TRUST_TEXT_EGRESS,
  handoffRows,
  landingZones,
  phaseForOpKind,
} from './directorHandoff';

const WINDOW = { start: 0, end: 10 };

function stateWith(over: { cues?: EditorState['cues']; cropPlan?: CropPlan | null }): EditorState {
  return initialEditorState({
    video: { videoId: 'v1', window: WINDOW, durationSec: 10 },
    cues: over.cues,
    cropPlan: over.cropPlan,
  });
}

const CUE = (index: number) => ({ index, start: index, end: index + 1, text: `w${index}` });

describe('phaseForOpKind', () => {
  it('routes cut/pacing kinds to the Edit phase', () => {
    const editKinds: DirectorOpKind[] = [
      'trim',
      'cut',
      'join',
      'removeSilence',
      'removeFillers',
      'reorder',
      'retime',
    ];
    for (const kind of editKinds) {
      expect(phaseForOpKind(kind)).toBe('edit');
    }
  });

  it('routes caption/text kinds to the Caption phase', () => {
    const captionKinds: DirectorOpKind[] = [
      'caption',
      'translateCaption',
      'overlayText',
      'lowerThird',
    ];
    for (const kind of captionKinds) {
      expect(phaseForOpKind(kind)).toBe('caption');
    }
  });

  it('routes crop/framing kinds to the Reframe phase', () => {
    const reframeKinds: DirectorOpKind[] = ['reframe', 'zoomPan', 'stitchPanorama', 'regenScroll'];
    for (const kind of reframeKinds) {
      expect(phaseForOpKind(kind)).toBe('reframe');
    }
  });

  it('leaves terminal/analysis kinds unrouted (not a reviewable phase diff)', () => {
    expect(phaseForOpKind('export')).toBeNull();
    expect(phaseForOpKind('ocrExtractList')).toBeNull();
  });
});

describe('HANDOFF_ROUTES', () => {
  it('names exactly the three review phases in the directed order', () => {
    expect(HANDOFF_ROUTES.map((r) => r.phase)).toEqual(['edit', 'caption', 'reframe']);
    expect(HANDOFF_ROUTES.map((r) => r.destination)).toEqual(['Edit', 'Caption', 'Reframe']);
  });

  it('describes each route in plain language (no op jargon, no model codenames)', () => {
    for (const route of HANDOFF_ROUTES) {
      expect(route.change.length).toBeGreaterThan(0);
      expect(route.blurb.length).toBeGreaterThan(0);
      // No engineer op-kind identifiers leak into the copy.
      expect(route.change).not.toMatch(/removeSilence|zoomPan|ocrExtractList/);
    }
  });
});

describe('landingZones', () => {
  it('marks Edit ready always (there is always a source timeline)', () => {
    const zones = landingZones(stateWith({}));
    const edit = zones.find((z) => z.phase === 'edit')!;
    expect(edit.ready).toBe(true);
    expect(edit.status).toContain('Timeline ready');
  });

  it('gates Caption on a transcript and reports the (plural) word count', () => {
    const zones = landingZones(stateWith({ cues: [CUE(1), CUE(2)] }));
    const caption = zones.find((z) => z.phase === 'caption')!;
    expect(caption.ready).toBe(true);
    expect(caption.status).toBe('Transcript ready — 2 words to re-time.');
  });

  it('uses the singular for a one-word transcript', () => {
    const zones = landingZones(stateWith({ cues: [CUE(1)] }));
    expect(zones.find((z) => z.phase === 'caption')!.status).toBe(
      'Transcript ready — 1 word to re-time.',
    );
  });

  it('reports Caption not-ready with no transcript', () => {
    const caption = landingZones(stateWith({ cues: [] })).find((z) => z.phase === 'caption')!;
    expect(caption.ready).toBe(false);
    expect(caption.status).toBe('No transcript yet — the Director reads the speech first.');
  });

  it('gates Reframe on a crop plan', () => {
    const withCrop = landingZones(stateWith({ cropPlan: { engine: 'x' } })).find(
      (z) => z.phase === 'reframe',
    )!;
    expect(withCrop.ready).toBe(true);
    expect(withCrop.status).toBe('Crop plan in place — framing nudges land on it.');

    const noCrop = landingZones(stateWith({ cropPlan: null })).find((z) => z.phase === 'reframe')!;
    expect(noCrop.ready).toBe(false);
    expect(noCrop.status).toBe('No crop plan yet — framing starts from center.');
  });

  it('returns exactly one zone per review phase', () => {
    const phases = landingZones(stateWith({})).map((z) => z.phase);
    expect([...phases].sort()).toEqual(['caption', 'edit', 'reframe']);
  });
});

describe('handoffRows', () => {
  it('merges each route with its live landing zone, aligned by phase', () => {
    const rows = handoffRows(stateWith({ cues: [CUE(1)], cropPlan: { engine: 'x' } }));
    expect(rows.map((r) => r.phase)).toEqual(['edit', 'caption', 'reframe']);
    // Row carries BOTH the route copy and the live zone status.
    const caption = rows.find((r) => r.phase === 'caption')!;
    expect(caption.destination).toBe('Caption');
    expect(caption.ready).toBe(true);
    expect(caption.status).toBe('Transcript ready — 1 word to re-time.');
  });

  it('keeps the route order and the zone order aligned', () => {
    const rows = handoffRows(stateWith({}));
    const zones = landingZones(stateWith({}));
    rows.forEach((row, i) => {
      expect(row.phase).toBe(zones[i].phase);
    });
  });
});

describe('trust microcopy (verbatim, single-sourced)', () => {
  it('pins the reviewable/reversible signature line', () => {
    expect(TRUST_REVERSIBLE).toBe(
      'The Director plans a reviewable, reversible edit — nothing is applied until you confirm.',
    );
  });

  it('pins the text-egress beat and keeps it identical to the cost-banner warning', () => {
    expect(TRUST_TEXT_EGRESS).toBe('Text will leave your machine.');
    // The same verbatim string directorTypes surfaces for a text-egressing op.
    expect(
      egressWarning({
        function: 'editPlan',
        route: 'cloud',
        costEst: 0,
        willEgress: true,
        cacheHit: false,
        cacheKey: 'k',
      }),
    ).toBe(TRUST_TEXT_EGRESS);
  });

  it('exposes the phase union type through a usable value', () => {
    const phase: HandoffPhase = 'edit';
    expect(HANDOFF_ROUTES.some((r) => r.phase === phase)).toBe(true);
  });
});
