// ShortMaker.test.tsx — tests for the short-maker review loop (unit: ui-shortmaker).
//
// Strategy: the bulk of the logic is exported as pure functions/reducers and
// tested with NO React render and NO heavy-ML imports — the RPC/provider seam is
// mocked (a fake `api`). A handful of component tests render with React 18's
// react-dom/client + act (already in deps; no @testing-library needed) under the
// jsdom env (vitest + jsdom devDeps).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import ShortMaker, {
  Candidate,
  Api,
  JobDone,
  JobProgress,
  MIN_CLIP_SEC,
  MAX_CLIP_SEC,
  DEFAULT_CONTROLS,
  CAPTION_STYLES,
  CAPTION_LIBASS_PRESETS,
  ALL_CAPTION_STYLES,
  CAPTION_STYLE_OPTIONS,
  DEFAULT_CAPTION_STYLE,
  REFRAME_ENGINE_OPTIONS,
  DEFAULT_REFRAME_ENGINE,
  clamp,
  sanitizeControls,
  candidateId,
  toReviewItems,
  nudgeCandidate,
  resetItem,
  approvedIds,
  approvedCandidates,
  displayPct,
  fmtTime,
  reviewReducer,
  ReviewItem,
  ReviewAction,
  extractCandidates,
  extractClips,
  isJobHandle,
  waitForJobDone,
  resolveJobResult,
  EXPORT_JOB_TIMEOUT_MS,
  FACTOR_KEYS,
  FACTOR_LABELS,
  factorEntries,
  displayVirality,
  recordFeedback,
  tasteProfileLine,
  CALIBRATION_LABELS,
  // P4 §7/§8c/§8d (re-exported through ShortMaker from ./shortMakerPresets).
  sortReviewItems,
  PLATFORM_PRESETS,
  PLATFORM_PRESET_IDS,
  applyPreset,
  topByVirality,
  buildExportParams,
  readBrandSettings,
  brandSettingsPatch,
  EMPTY_BRAND_SETTINGS,
} from './ShortMaker';

// ---------------------------------------------------------------------------
// jsdom does not implement HTMLMediaElement playback; back the properties the
// preview Player touches (play/pause/currentTime/paused/ended) with
// deterministic per-element stores so the keyboard tests can drive them
// (same pattern as components/Player.test.tsx).
// ---------------------------------------------------------------------------
const playMock = vi.fn(() => Promise.resolve());
const pauseMock = vi.fn();
const currentTimes = new WeakMap<HTMLMediaElement, number>();
const pausedStates = new WeakMap<HTMLMediaElement, boolean>();

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    writable: true,
    value: playMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    writable: true,
    value: pauseMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return currentTimes.get(this) ?? 0;
    },
    set(this: HTMLMediaElement, v: number) {
      currentTimes.set(this, v);
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'paused', {
    configurable: true,
    get(this: HTMLMediaElement) {
      return pausedStates.get(this) ?? true;
    },
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'ended', {
    configurable: true,
    get() {
      return false;
    },
  });
});

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function cand(over: Partial<Candidate> = {}): Candidate {
  return {
    rank: 1,
    start: 97,
    end: 131,
    durationSec: 34,
    hook: 'As it turns out, there is a pattern',
    why: 'Introduces the core concept',
    score: 95,
    sourceStart: 97,
    ...over,
  };
}

const THREE: Candidate[] = [
  cand({ rank: 2, start: 199, end: 248, durationSec: 49, hook: 'B', score: 92, sourceStart: 199 }),
  cand({ rank: 1, start: 97, end: 131, durationSec: 34, hook: 'A', score: 95, sourceStart: 97 }),
  cand({ rank: 3, start: 494, end: 554, durationSec: 60, hook: 'C', score: 93, sourceStart: 494 }),
];

// ---------------------------------------------------------------------------
// clamp / sanitizeControls
// ---------------------------------------------------------------------------

describe('clamp', () => {
  it('keeps values inside the range', () => {
    expect(clamp(5, 0, 10)).toBe(5);
  });
  it('clamps below and above', () => {
    expect(clamp(-1, 0, 10)).toBe(0);
    expect(clamp(11, 0, 10)).toBe(10);
  });
  it('returns lo when the range is inverted', () => {
    expect(clamp(5, 10, 0)).toBe(10);
  });
});

describe('sanitizeControls', () => {
  it('fills defaults from an empty object', () => {
    expect(sanitizeControls({})).toEqual(DEFAULT_CONTROLS);
  });

  it('forces count >= 1 and integer', () => {
    expect(sanitizeControls({ count: 0 }).count).toBe(1);
    expect(sanitizeControls({ count: -4 }).count).toBe(1);
    expect(sanitizeControls({ count: 3.7 }).count).toBe(4);
  });

  it('clamps minSec/maxSec into the 20-60 hard window', () => {
    const c = sanitizeControls({ minSec: 5, maxSec: 999 });
    expect(c.minSec).toBe(MIN_CLIP_SEC);
    expect(c.maxSec).toBe(MAX_CLIP_SEC);
  });

  it('repairs an inverted min>max by raising max to min', () => {
    const c = sanitizeControls({ minSec: 50, maxSec: 30 });
    expect(c.minSec).toBe(50);
    expect(c.maxSec).toBe(50);
    expect(c.minSec).toBeLessThanOrEqual(c.maxSec);
  });

  it('falls back to defaults for blank string fields', () => {
    const c = sanitizeControls({ aspect: '   ', language: '', captionStyle: '' });
    expect(c.aspect).toBe(DEFAULT_CONTROLS.aspect);
    expect(c.language).toBe(DEFAULT_CONTROLS.language);
    expect(c.captionStyle).toBe(DEFAULT_CONTROLS.captionStyle);
  });

  it('keeps provided non-blank string fields', () => {
    const c = sanitizeControls({ aspect: '1:1', language: 'es', captionStyle: 'bold' });
    expect(c.aspect).toBe('1:1');
    expect(c.language).toBe('es');
    expect(c.captionStyle).toBe('bold');
  });

  it('produces controls matching the §2 control field names exactly (+ T4b reframeEngine + P3 toggles + P4 §8a/§8b + audio-stabilize)', () => {
    // T4b extends the frozen §2 controls with the reframe engine override
    // (auto/verthor/claudeshorts); the P3 mini-contract adds the hookTitle and
    // removeFillers booleans; P4 §8a/§8b add the emphasis tri-state + autoZoom
    // bool; the audio-stabilize group adds the silenceTrim + stabilize bools —
    // see the CONTRACT-NOTE on ShortMakerControls.
    const c = sanitizeControls({});
    expect(Object.keys(c).sort()).toEqual(
      [
        'aspect',
        'autoZoom',
        'captionStyle',
        'count',
        'emphasis',
        'hookTitle',
        'language',
        'maxSec',
        'minSec',
        'reframeEngine',
        'removeFillers',
        'silenceTrim',
        'stabilize',
      ].sort(),
    );
  });

  // ---- P3: hookTitle / removeFillers toggles --------------------------------

  it('defaults hookTitle ON and removeFillers ON (V1 quality-defaults-ON, G-4)', () => {
    const c = sanitizeControls({});
    expect(c.hookTitle).toBe(true);
    expect(c.removeFillers).toBe(true);
    expect(DEFAULT_CONTROLS.hookTitle).toBe(true);
    expect(DEFAULT_CONTROLS.removeFillers).toBe(true);
  });

  it('keeps explicit boolean toggle values', () => {
    expect(sanitizeControls({ hookTitle: false }).hookTitle).toBe(false);
    expect(sanitizeControls({ removeFillers: false }).removeFillers).toBe(false);
  });

  it('rejects non-boolean toggle values back to the defaults', () => {
    expect(sanitizeControls({ hookTitle: 'yes' as unknown as boolean }).hookTitle).toBe(true);
    expect(sanitizeControls({ hookTitle: 0 as unknown as boolean }).hookTitle).toBe(true);
    expect(sanitizeControls({ removeFillers: 1 as unknown as boolean }).removeFillers).toBe(true);
    expect(sanitizeControls({ removeFillers: 'true' as unknown as boolean }).removeFillers).toBe(
      true,
    );
  });

  // ---- P4 §8a emphasis tri-state / §8b autoZoom -----------------------------

  it("defaults emphasis to 'default' (per-style) and autoZoom ON (V1 quality-defaults-ON, G-4)", () => {
    const c = sanitizeControls({});
    expect(c.emphasis).toBe('default');
    expect(c.autoZoom).toBe(true);
    expect(DEFAULT_CONTROLS.emphasis).toBe('default');
    expect(DEFAULT_CONTROLS.autoZoom).toBe(true);
  });

  it('keeps explicit emphasis choices and normalizes case', () => {
    expect(sanitizeControls({ emphasis: 'on' }).emphasis).toBe('on');
    expect(sanitizeControls({ emphasis: 'off' }).emphasis).toBe('off');
    expect(sanitizeControls({ emphasis: 'ON' as unknown as 'on' }).emphasis).toBe('on');
  });

  it("rejects an unknown emphasis value back to 'default'", () => {
    expect(sanitizeControls({ emphasis: 'maybe' as unknown as 'on' }).emphasis).toBe('default');
    expect(sanitizeControls({ emphasis: '' as unknown as 'on' }).emphasis).toBe('default');
  });

  it('keeps an explicit autoZoom boolean; junk falls back to the default ON', () => {
    expect(sanitizeControls({ autoZoom: false }).autoZoom).toBe(false);
    expect(sanitizeControls({ autoZoom: 1 as unknown as boolean }).autoZoom).toBe(true);
    expect(sanitizeControls({ autoZoom: 'true' as unknown as boolean }).autoZoom).toBe(true);
  });

  // ---- T4b: caption style + reframe engine sanitation ----------------------

  it('rejects an unknown captionStyle back to the libass default', () => {
    expect(sanitizeControls({ captionStyle: 'comic-sans-3d' }).captionStyle).toBe(
      DEFAULT_CAPTION_STYLE,
    );
  });

  it('accepts every catalogued caption style id', () => {
    for (const id of CAPTION_STYLE_OPTIONS) {
      expect(sanitizeControls({ captionStyle: id }).captionStyle).toBe(id);
    }
  });

  it('preserves the opusclip-karaoke libass preset (V1.1 WU SP1 BLOCKER fix)', () => {
    // The controls sanitizer must keep the preset so the export wire carries it
    // to the sidecar (which routes karaoke=True). Before the fix it reset to libass.
    expect(sanitizeControls({ captionStyle: 'opusclip-karaoke' }).captionStyle).toBe(
      'opusclip-karaoke',
    );
  });

  it('defaults reframeEngine to auto and normalizes case', () => {
    expect(sanitizeControls({}).reframeEngine).toBe('auto');
    expect(sanitizeControls({ reframeEngine: 'CLAUDESHORTS' }).reframeEngine).toBe('claudeshorts');
    expect(sanitizeControls({ reframeEngine: 'verthor' }).reframeEngine).toBe('verthor');
  });

  it('rejects an unknown reframeEngine back to auto', () => {
    expect(sanitizeControls({ reframeEngine: 'imovie' }).reframeEngine).toBe('auto');
    expect(sanitizeControls({ reframeEngine: '' }).reframeEngine).toBe('auto');
  });
});

// ---------------------------------------------------------------------------
// T4b style catalog + engine option invariants
// ---------------------------------------------------------------------------

describe('CAPTION_STYLES / REFRAME_ENGINE_OPTIONS (T4b)', () => {
  it('has unique ids and the libass default is a libass-engine style', () => {
    const ids = CAPTION_STYLES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    const def = CAPTION_STYLES.find((s) => s.id === DEFAULT_CAPTION_STYLE);
    expect(def).toBeTruthy();
    expect(def!.engine).toBe('libass');
    expect(DEFAULT_CONTROLS.captionStyle).toBe(DEFAULT_CAPTION_STYLE);
  });

  it('lists the >=12 OpusClip remotion templates (incl. the originals) (P4 §4)', () => {
    // The exhaustive id-set equality with vendor TEMPLATES + sidecar STYLES is
    // enforced by lib/captionTemplates.conformance.test.ts (reads the real
    // files). Here we sanity-check the picker carries the expected ids.
    const remotionIds = CAPTION_STYLES.filter((s) => s.engine === 'remotion').map((s) => s.id);
    expect(remotionIds.length).toBeGreaterThanOrEqual(12);
    expect(new Set(remotionIds)).toEqual(
      new Set([
        'bold',
        'bounce',
        'clean',
        'karaoke',
        'hormozi',
        'neon',
        'tiktok',
        'gradient',
        'impact',
        'mrbeast',
        'pop',
        'serif',
        'subtitle',
        'fire',
      ]),
    );
  });

  it('offers exactly the A4 engines plus the auto selector', () => {
    expect([...REFRAME_ENGINE_OPTIONS]).toEqual(['auto', 'verthor', 'claudeshorts']);
    expect(DEFAULT_REFRAME_ENGINE).toBe('auto');
    expect(DEFAULT_CONTROLS.reframeEngine).toBe('auto');
  });

  it('carries the libass-only presets OUTSIDE the conformance mirror (V1.1 WU SP1)', () => {
    // The opusclip-karaoke preset is a libass-engine preset that must NOT widen
    // CAPTION_STYLES (the conformance-pinned three-way mirror) but MUST be in the
    // full catalog + the sanitizer allowlist so it is selectable end-to-end.
    expect(CAPTION_LIBASS_PRESETS.map((s) => s.id)).toEqual(['opusclip-karaoke']);
    expect(CAPTION_LIBASS_PRESETS.every((s) => s.engine === 'libass')).toBe(true);
    // Kept out of the frozen mirror...
    expect(CAPTION_STYLES.map((s) => s.id)).not.toContain('opusclip-karaoke');
    // ...but present in the full catalog + the allowlist.
    expect(ALL_CAPTION_STYLES).toEqual([...CAPTION_STYLES, ...CAPTION_LIBASS_PRESETS]);
    expect(CAPTION_STYLE_OPTIONS).toContain('opusclip-karaoke');
    // No duplicate ids across the full catalog.
    const ids = ALL_CAPTION_STYLES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// ---------------------------------------------------------------------------
// candidate schema helpers
// ---------------------------------------------------------------------------

describe('candidateId', () => {
  it('is stable and distinguishes by rank + sourceStart', () => {
    expect(candidateId(cand({ rank: 1, sourceStart: 97 }))).toBe('1@97');
    expect(candidateId(cand({ rank: 2, sourceStart: 199 }))).toBe('2@199');
    expect(candidateId(cand({ rank: 1, sourceStart: 97 }))).toBe(
      candidateId(cand({ rank: 1, sourceStart: 97, hook: 'different' })),
    );
  });
});

describe('toReviewItems', () => {
  it('sorts by rank ascending and marks all pending', () => {
    const items = toReviewItems(THREE);
    expect(items.map((i) => i.current.rank)).toEqual([1, 2, 3]);
    expect(items.every((i) => i.status === 'pending')).toBe(true);
  });

  it('preserves original and current identically on load (non-destructive baseline)', () => {
    const items = toReviewItems([cand()]);
    expect(items[0].original).toEqual(items[0].current);
  });

  it('does not mutate the input array order', () => {
    const input = [...THREE];
    toReviewItems(input);
    expect(input[0].rank).toBe(2); // unchanged
  });
});

// ---------------------------------------------------------------------------
// nudgeCandidate — must stay in the 20-60 hard window (LC2 acceptance)
// ---------------------------------------------------------------------------

describe('nudgeCandidate', () => {
  it('shifts start later and recomputes duration', () => {
    const c = nudgeCandidate(cand({ start: 100, end: 140, durationSec: 40 }), 5, 0);
    expect(c.start).toBe(105);
    expect(c.end).toBe(140);
    expect(c.durationSec).toBe(35);
  });

  it('shifts end later and recomputes duration', () => {
    const c = nudgeCandidate(cand({ start: 100, end: 140, durationSec: 40 }), 0, 5);
    expect(c.end).toBe(145);
    expect(c.durationSec).toBe(45);
  });

  it('never lets start go below 0', () => {
    const c = nudgeCandidate(cand({ start: 3, end: 40, durationSec: 37 }), -10, 0);
    expect(c.start).toBe(0);
    expect(c.start).toBeGreaterThanOrEqual(0);
  });

  it('clamps a shrink below the minimum back up to MIN_CLIP_SEC', () => {
    // start 100, end 120 (dur 20). Move end -10 -> would be 10s -> clamp to 20.
    const c = nudgeCandidate(cand({ start: 100, end: 120, durationSec: 20 }), 0, -10);
    expect(c.durationSec).toBeGreaterThanOrEqual(MIN_CLIP_SEC);
    expect(c.durationSec).toBe(MIN_CLIP_SEC);
  });

  it('clamps a grow above the maximum back down to MAX_CLIP_SEC', () => {
    // start 100, end 155 (dur 55). Move end +20 -> 75s -> clamp to 60.
    const c = nudgeCandidate(cand({ start: 100, end: 155, durationSec: 55 }), 0, 20);
    expect(c.durationSec).toBeLessThanOrEqual(MAX_CLIP_SEC);
    expect(c.durationSec).toBe(MAX_CLIP_SEC);
  });

  it('handles an inverted result (end <= start) by enforcing a valid window', () => {
    const c = nudgeCandidate(cand({ start: 100, end: 110, durationSec: 10 }), 50, 0);
    expect(c.end).toBeGreaterThan(c.start);
    expect(c.durationSec).toBeGreaterThanOrEqual(MIN_CLIP_SEC);
    expect(c.durationSec).toBeLessThanOrEqual(MAX_CLIP_SEC);
  });

  it('always stays within [MIN, MAX] for a range of deltas (property-ish)', () => {
    for (const ds of [-30, -5, 0, 5, 30]) {
      for (const de of [-30, -5, 0, 5, 30]) {
        const c = nudgeCandidate(cand({ start: 100, end: 140, durationSec: 40 }), ds, de);
        expect(c.durationSec).toBeGreaterThanOrEqual(MIN_CLIP_SEC);
        expect(c.durationSec).toBeLessThanOrEqual(MAX_CLIP_SEC);
        expect(c.start).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it('does not change rank/hook/why/score/sourceStart (only boundaries)', () => {
    const base = cand();
    const c = nudgeCandidate(base, 5, 5);
    expect(c.rank).toBe(base.rank);
    expect(c.hook).toBe(base.hook);
    expect(c.why).toBe(base.why);
    expect(c.score).toBe(base.score);
    expect(c.sourceStart).toBe(base.sourceStart);
  });
});

describe('resetItem', () => {
  it('restores current back to the original (non-destructive)', () => {
    const item: ReviewItem = {
      id: '1@97',
      original: cand({ start: 97, end: 131 }),
      current: cand({ start: 110, end: 150 }),
      status: 'pending',
    };
    const reset = resetItem(item);
    expect(reset.current).toEqual(item.original);
    // The original is still intact and recoverable.
    expect(reset.original).toEqual(item.original);
  });
});

// ---------------------------------------------------------------------------
// approved selectors
// ---------------------------------------------------------------------------

describe('approvedIds / approvedCandidates', () => {
  it('returns only approved ids', () => {
    let items = toReviewItems(THREE);
    items = reviewReducer(items, { type: 'approve', id: '1@97' });
    items = reviewReducer(items, { type: 'discard', id: '2@199' });
    expect(approvedIds(items)).toEqual(['1@97']);
  });

  it('returns the CURRENT (nudged) candidate for approved items', () => {
    let items = toReviewItems([cand({ start: 100, end: 140, durationSec: 40 })]);
    items = reviewReducer(items, { type: 'nudge', id: '1@97', deltaStart: 0, deltaEnd: 5 });
    items = reviewReducer(items, { type: 'approve', id: '1@97' });
    const ac = approvedCandidates(items);
    expect(ac).toHaveLength(1);
    expect(ac[0].end).toBe(145);
    expect(ac[0].durationSec).toBe(45);
  });

  it('is empty when nothing is approved', () => {
    expect(approvedIds(toReviewItems(THREE))).toEqual([]);
    expect(approvedCandidates(toReviewItems(THREE))).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// reviewReducer
// ---------------------------------------------------------------------------

describe('reviewReducer', () => {
  it('load builds items', () => {
    expect(reviewReducer([], { type: 'load', candidates: THREE })).toHaveLength(3);
  });

  it('clear empties the list', () => {
    expect(reviewReducer(toReviewItems(THREE), { type: 'clear' })).toEqual([]);
  });

  it('approve / discard / pending transition only the targeted item', () => {
    let items = toReviewItems(THREE);
    items = reviewReducer(items, { type: 'approve', id: '1@97' });
    expect(items.find((i) => i.id === '1@97')!.status).toBe('approved');
    expect(items.find((i) => i.id === '2@199')!.status).toBe('pending');

    items = reviewReducer(items, { type: 'discard', id: '1@97' });
    expect(items.find((i) => i.id === '1@97')!.status).toBe('discarded');

    items = reviewReducer(items, { type: 'pending', id: '1@97' });
    expect(items.find((i) => i.id === '1@97')!.status).toBe('pending');
  });

  it('discard is non-destructive — the candidate stays in the list and can be reinstated', () => {
    let items = toReviewItems(THREE);
    items = reviewReducer(items, { type: 'discard', id: '3@494' });
    expect(items).toHaveLength(3); // not removed
    items = reviewReducer(items, { type: 'pending', id: '3@494' });
    expect(items.find((i) => i.id === '3@494')!.status).toBe('pending');
  });

  it('nudge updates current but leaves original intact (recoverable)', () => {
    let items = toReviewItems([cand({ start: 100, end: 140, durationSec: 40 })]);
    items = reviewReducer(items, { type: 'nudge', id: '1@97', deltaStart: 5, deltaEnd: 0 });
    const it = items[0];
    expect(it.current.start).toBe(105);
    expect(it.original.start).toBe(100); // original preserved
  });

  it('reset reverts a nudge', () => {
    let items = toReviewItems([cand({ start: 100, end: 140, durationSec: 40 })]);
    items = reviewReducer(items, { type: 'nudge', id: '1@97', deltaStart: 5, deltaEnd: 5 });
    items = reviewReducer(items, { type: 'reset', id: '1@97' });
    expect(items[0].current).toEqual(items[0].original);
  });

  it('ignores an unknown action type', () => {
    const items = toReviewItems(THREE);
    // @ts-expect-error intentional unknown action
    expect(reviewReducer(items, { type: 'bogus' } as ReviewAction)).toBe(items);
  });
});

// ---------------------------------------------------------------------------
// display helpers
// ---------------------------------------------------------------------------

describe('displayPct', () => {
  it('clamps to 0..100 and rounds', () => {
    expect(displayPct(50.6)).toBe(51);
    expect(displayPct(-5)).toBe(0);
    expect(displayPct(150)).toBe(100);
  });
  it('returns 0 for undefined/NaN', () => {
    expect(displayPct(undefined)).toBe(0);
    expect(displayPct(NaN)).toBe(0);
  });
});

describe('fmtTime', () => {
  it('formats seconds as M:SS', () => {
    expect(fmtTime(0)).toBe('0:00');
    expect(fmtTime(7)).toBe('0:07');
    expect(fmtTime(97)).toBe('1:37');
    expect(fmtTime(131)).toBe('2:11');
  });
  it('never goes negative', () => {
    expect(fmtTime(-10)).toBe('0:00');
  });
});

// ---------------------------------------------------------------------------
// P3-C: factor breakdown + virality display helpers
// ---------------------------------------------------------------------------

/** A candidate carrying the full P3-C payload. */
function factored(over: Partial<Candidate> = {}): Candidate {
  return cand({
    factors: { hookStrength: 88, emotionalFlow: 64, perceivedValue: 71, shareability: 90 },
    factorNotes: {
      hookStrength: 'Opens mid-claim',
      emotionalFlow: 'Steady build to the punchline',
      perceivedValue: 'Concrete takeaway',
      shareability: 'Quotable one-liner',
    },
    viralityPct: 87,
    ...over,
  });
}

describe('factorEntries / displayVirality (P3-C)', () => {
  it('returns the four FROZEN factors in display order with labels + notes', () => {
    const entries = factorEntries(factored());
    expect(entries.map((e) => e.key)).toEqual([...FACTOR_KEYS]);
    expect(entries.map((e) => e.key)).toEqual([
      'hookStrength',
      'emotionalFlow',
      'perceivedValue',
      'shareability',
    ]);
    expect(entries.map((e) => e.value)).toEqual([88, 64, 71, 90]);
    expect(entries[0].label).toBe(FACTOR_LABELS.hookStrength);
    expect(entries[0].note).toBe('Opens mid-claim');
  });

  it('returns [] when the candidate has no factors (pre-P3 payload)', () => {
    expect(factorEntries(cand())).toEqual([]);
  });

  it('clamps factor values into 0-100 and zeroes non-finite junk', () => {
    const entries = factorEntries(
      factored({
        factors: {
          hookStrength: 130,
          emotionalFlow: -7,
          perceivedValue: Number.NaN,
          shareability: 49.6,
        },
      }),
    );
    expect(entries.map((e) => e.value)).toEqual([100, 0, 0, 50]);
  });

  it('uses empty-string notes when factorNotes are absent', () => {
    const entries = factorEntries(factored({ factorNotes: undefined }));
    expect(entries.every((e) => e.note === '')).toBe(true);
  });

  it('displayVirality clamps to 0-100 and rejects non-numbers', () => {
    expect(displayVirality(87)).toBe(87);
    expect(displayVirality(87.6)).toBe(88);
    expect(displayVirality(150)).toBe(100);
    expect(displayVirality(-3)).toBe(0);
    expect(displayVirality(undefined)).toBeNull();
    expect(displayVirality(NaN)).toBeNull();
    expect(displayVirality('87')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// P4 §7: candidate sort (rank ↔ virality)
// ---------------------------------------------------------------------------

describe('sortReviewItems (P4 §7)', () => {
  const items = toReviewItems([
    cand({ rank: 1, sourceStart: 1, viralityPct: 40 }),
    cand({ rank: 2, sourceStart: 2, viralityPct: 90 }),
    cand({ rank: 3, sourceStart: 3, viralityPct: 70 }),
  ]);

  it('keeps the rank order under "rank" mode', () => {
    expect(sortReviewItems(items, 'rank').map((i) => i.current.rank)).toEqual([1, 2, 3]);
  });

  it('orders by viralityPct descending under "virality" mode', () => {
    expect(sortReviewItems(items, 'virality').map((i) => i.current.rank)).toEqual([2, 3, 1]);
  });

  it('sinks candidates with no virality below scored ones, tie-broken by rank', () => {
    const mixed = toReviewItems([
      cand({ rank: 1, sourceStart: 1 }), // no viralityPct
      cand({ rank: 2, sourceStart: 2, viralityPct: 55 }),
      cand({ rank: 3, sourceStart: 3 }), // no viralityPct
    ]);
    expect(sortReviewItems(mixed, 'virality').map((i) => i.current.rank)).toEqual([2, 1, 3]);
  });

  it('does not mutate the input array', () => {
    const before = items.map((i) => i.current.rank);
    sortReviewItems(items, 'virality');
    expect(items.map((i) => i.current.rank)).toEqual(before);
  });
});

// ---------------------------------------------------------------------------
// P4 §8c: platform presets + batch helpers
// ---------------------------------------------------------------------------

describe('PLATFORM_PRESETS / applyPreset (P4 §8c)', () => {
  it('exposes exactly tiktok/reels/shorts at 9:16 with the documented maxSec', () => {
    expect([...PLATFORM_PRESET_IDS]).toEqual(['tiktok', 'reels', 'shorts']);
    // The map records each platform's documented sweet-spot maxSec (60/90/60);
    // the EFFECTIVE value is clamped to the §5 hard window by applyPreset.
    expect(PLATFORM_PRESETS.tiktok).toMatchObject({ aspect: '9:16', maxSec: 60 });
    expect(PLATFORM_PRESETS.reels).toMatchObject({ aspect: '9:16', maxSec: 90 });
    expect(PLATFORM_PRESETS.shorts).toMatchObject({ aspect: '9:16', maxSec: 60 });
    for (const id of PLATFORM_PRESET_IDS) {
      expect(PLATFORM_PRESETS[id].count).toBeGreaterThanOrEqual(1);
    }
  });

  it('applies aspect/count + the §5-clamped maxSec, keeping the other controls', () => {
    const base = sanitizeControls({
      captionStyle: 'hormozi',
      reframeEngine: 'verthor',
      minSec: 25,
    });
    const out = applyPreset(base, 'reels');
    expect(out.aspect).toBe('9:16');
    // Reels asks for 90 but the §5 hard window (renderer + sidecar) clamps to 60.
    expect(out.maxSec).toBe(MAX_CLIP_SEC);
    expect(out.count).toBe(PLATFORM_PRESETS.reels.count);
    // unrelated controls survive
    expect(out.captionStyle).toBe('hormozi');
    expect(out.reframeEngine).toBe('verthor');
    expect(out.minSec).toBe(25);
  });

  it('presets stay distinct on the enforceable count axis', () => {
    const base = sanitizeControls({});
    expect(applyPreset(base, 'tiktok').count).toBe(5);
    expect(applyPreset(base, 'reels').count).toBe(3);
    expect(applyPreset(base, 'shorts').count).toBe(8);
  });

  it('lowers minSec when it would exceed a shorter preset maxSec (stays valid)', () => {
    const base = sanitizeControls({ minSec: 60, maxSec: 60 });
    const out = applyPreset(base, 'tiktok'); // maxSec 60 -> minSec ok at 60
    expect(out.minSec).toBeLessThanOrEqual(out.maxSec);
    // a deliberately-too-high minSec is clamped under the preset max
    const tight = applyPreset(sanitizeControls({ minSec: 60 }), 'tiktok');
    expect(tight.minSec).toBeLessThanOrEqual(60);
  });

  it('returns the controls unchanged for an unknown preset id', () => {
    const base = sanitizeControls({});
    expect(applyPreset(base, 'instagram-story-3000')).toBe(base);
  });

  it('produces sanitized controls (immutable; never the same object)', () => {
    const base = sanitizeControls({});
    const out = applyPreset(base, 'tiktok');
    expect(out).not.toBe(base);
    expect(Object.keys(out).sort()).toEqual(Object.keys(base).sort());
  });
});

describe('topByVirality (P4 §8c)', () => {
  const cs = [
    cand({ rank: 1, sourceStart: 1, viralityPct: 40 }),
    cand({ rank: 2, sourceStart: 2, viralityPct: 95 }),
    cand({ rank: 3, sourceStart: 3, viralityPct: 70 }),
    cand({ rank: 4, sourceStart: 4, viralityPct: 88 }),
  ];

  it('returns the top N by viralityPct descending', () => {
    expect(topByVirality(cs, 2).map((c) => c.rank)).toEqual([2, 4]);
    expect(topByVirality(cs, 3).map((c) => c.rank)).toEqual([2, 4, 3]);
  });

  it('clamps to the available count and never mutates the input', () => {
    const snapshot = cs.map((c) => c.rank);
    expect(topByVirality(cs, 99)).toHaveLength(4);
    expect(cs.map((c) => c.rank)).toEqual(snapshot);
  });

  it('returns [] for n <= 0', () => {
    expect(topByVirality(cs, 0)).toEqual([]);
    expect(topByVirality(cs, -1)).toEqual([]);
  });

  it('breaks virality ties by rank and sinks missing scores last', () => {
    const tied = [
      cand({ rank: 5, sourceStart: 5 }), // no score
      cand({ rank: 3, sourceStart: 3, viralityPct: 50 }),
      cand({ rank: 1, sourceStart: 1, viralityPct: 50 }),
    ];
    expect(topByVirality(tied, 3).map((c) => c.rank)).toEqual([1, 3, 5]);
  });
});

describe('buildExportParams (P4 §8c / §2 export contract)', () => {
  it('carries candidateIds + inline candidates + the controls', () => {
    const top = [cand({ rank: 2, sourceStart: 2 }), cand({ rank: 1, sourceStart: 1 })];
    const ctrl = sanitizeControls({
      captionStyle: 'bold',
      reframeEngine: 'verthor',
      hookTitle: false,
    });
    const params = buildExportParams('v1', top, ctrl, '');
    expect(params).toMatchObject({
      videoId: 'v1',
      candidateIds: ['2@2', '1@1'],
      captionStyle: 'bold',
      reframeEngine: 'verthor',
      hookTitle: false,
      removeFillers: true,
      autoZoom: true,
    });
    expect((params.candidates as Candidate[]).map((c) => c.rank)).toEqual([2, 1]);
  });

  it('includes audioTrackId only when a non-empty track is chosen', () => {
    const top = [cand()];
    const ctrl = sanitizeControls({});
    expect('audioTrackId' in buildExportParams('v1', top, ctrl, '')).toBe(false);
    expect(buildExportParams('v1', top, ctrl, 'dub-es')).toMatchObject({ audioTrackId: 'dub-es' });
  });

  it('always sends autoZoom (P4 §8b) and reflects an explicit OFF', () => {
    const top = [cand()];
    expect(buildExportParams('v1', top, sanitizeControls({}), '').autoZoom).toBe(true);
    expect(buildExportParams('v1', top, sanitizeControls({ autoZoom: false }), '').autoZoom).toBe(
      false,
    );
  });

  it("omits emphasis on 'default' but sends a bool on an explicit choice (P4 §8a)", () => {
    const top = [cand()];
    // 'default' -> the key is OMITTED so the sidecar's per-style default applies.
    expect('emphasis' in buildExportParams('v1', top, sanitizeControls({}), '')).toBe(false);
    // explicit 'on'/'off' -> sent as a real bool.
    expect(buildExportParams('v1', top, sanitizeControls({ emphasis: 'on' }), '')).toMatchObject({
      emphasis: true,
    });
    expect(buildExportParams('v1', top, sanitizeControls({ emphasis: 'off' }), '')).toMatchObject({
      emphasis: false,
    });
  });

  it('always sends the audio-stabilize toggles (silenceTrim/stabilize, default ON)', () => {
    const top = [cand()];
    const on = buildExportParams('v1', top, sanitizeControls({}), '');
    expect(on).toMatchObject({ silenceTrim: true, stabilize: true });
    const off = buildExportParams(
      'v1',
      top,
      sanitizeControls({ silenceTrim: false, stabilize: false }),
      '',
    );
    expect(off).toMatchObject({ silenceTrim: false, stabilize: false });
  });
});

// ---------------------------------------------------------------------------
// P4 §8d: brand kit settings helpers
// ---------------------------------------------------------------------------

describe('readBrandSettings / brandSettingsPatch (P4 §8d)', () => {
  it('reads the three FROZEN keys, trimming strings', () => {
    expect(
      readBrandSettings({
        brandLogoPath: '  /logos/brand.png ',
        brandCaptionTemplate: 'hormozi',
        brandFontFamily: ' Inter ',
        useCloud: true, // unrelated keys ignored
      }),
    ).toEqual({
      brandLogoPath: '/logos/brand.png',
      brandCaptionTemplate: 'hormozi',
      brandFontFamily: 'Inter',
    });
  });

  it('tolerates absent keys -> the empty brand kit (C12)', () => {
    expect(readBrandSettings({})).toEqual(EMPTY_BRAND_SETTINGS);
    expect(readBrandSettings({ ffmpegPath: '/x' })).toEqual(EMPTY_BRAND_SETTINGS);
  });

  it('tolerates a non-object settings result', () => {
    expect(readBrandSettings(null)).toEqual(EMPTY_BRAND_SETTINGS);
    expect(readBrandSettings(undefined)).toEqual(EMPTY_BRAND_SETTINGS);
    expect(readBrandSettings('nope')).toEqual(EMPTY_BRAND_SETTINGS);
  });

  it('drops an unknown caption template id (never shows a stale default)', () => {
    expect(readBrandSettings({ brandCaptionTemplate: 'comic-sans-3d' }).brandCaptionTemplate).toBe(
      '',
    );
    // a real id (including libass/none which the picker offers) is kept
    expect(readBrandSettings({ brandCaptionTemplate: 'libass' }).brandCaptionTemplate).toBe(
      'libass',
    );
  });

  it('non-string values coerce to empty strings', () => {
    expect(
      readBrandSettings({ brandLogoPath: 123, brandCaptionTemplate: {}, brandFontFamily: null }),
    ).toEqual(EMPTY_BRAND_SETTINGS);
  });

  it('brandSettingsPatch emits exactly the three FROZEN keys', () => {
    const patch = brandSettingsPatch({
      brandLogoPath: '/l.png',
      brandCaptionTemplate: 'neon',
      brandFontFamily: 'Roboto',
    });
    expect(Object.keys(patch).sort()).toEqual(
      ['brandCaptionTemplate', 'brandFontFamily', 'brandLogoPath'].sort(),
    );
    expect(patch).toEqual({
      brandLogoPath: '/l.png',
      brandCaptionTemplate: 'neon',
      brandFontFamily: 'Roboto',
    });
  });
});

// ---------------------------------------------------------------------------
// P3-D: feedback flywheel helpers
// ---------------------------------------------------------------------------

describe('recordFeedback / tasteProfileLine (P3-D)', () => {
  it('fires feedback.record with the FROZEN param names', () => {
    const rpc = vi.fn().mockResolvedValue({ ok: true });
    const api: Api = { rpc, onProgress: () => () => {} };
    recordFeedback(api, 'v1', cand(), 'approved');
    expect(rpc).toHaveBeenCalledWith('feedback.record', {
      videoId: 'v1',
      candidate: expect.objectContaining({ rank: 1, sourceStart: 97 }),
      action: 'approved',
    });
  });

  it('is fire-and-forget: a rejecting rpc is silent-logged, never thrown', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const api: Api = {
      rpc: vi.fn().mockRejectedValue(new Error('feedback store down')),
      onProgress: () => () => {},
    };
    expect(() => recordFeedback(api, 'v1', cand(), 'discarded')).not.toThrow();
    // Promise.resolve(rejected) adopts over several microtask ticks — flush a
    // full macrotask so the silent .catch has definitely run.
    await new Promise((r) => setTimeout(r, 0));
    expect(warn).toHaveBeenCalled();
  });

  it('tolerates a synchronously-throwing rpc and a missing api', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const api = {
      rpc: () => {
        throw new Error('boom');
      },
      onProgress: () => () => {},
    } as unknown as Api;
    expect(() => recordFeedback(api, 'v1', cand(), 'nudged')).not.toThrow();
    expect(warn).toHaveBeenCalled();
    expect(() => recordFeedback(undefined, 'v1', cand(), 'exported')).not.toThrow();
  });

  it('formats the taste-profile footer line', () => {
    expect(tasteProfileLine({ labels: 37, calibrated: false })).toBe(
      `Taste profile: 37 labels · calibration at ${CALIBRATION_LABELS}`,
    );
    expect(tasteProfileLine({ labels: 64, calibrated: true })).toBe(
      'Taste profile: 64 labels · calibrated',
    );
  });
});

// ---------------------------------------------------------------------------
// rpc payload extractors
// ---------------------------------------------------------------------------

describe('extractCandidates / extractClips / isJobHandle', () => {
  it('extracts candidates from a select result', () => {
    expect(extractCandidates({ candidates: THREE })).toHaveLength(3);
  });
  it('extracts clips from an export result', () => {
    expect(extractClips({ clips: [{ path: '/a.mp4' }] })).toEqual([{ path: '/a.mp4' }]);
  });
  it('returns null for non-matching payloads', () => {
    expect(extractCandidates({ jobId: 'j1' })).toBeNull();
    expect(extractClips({ jobId: 'j1' })).toBeNull();
    expect(extractCandidates(null)).toBeNull();
    expect(extractClips(undefined)).toBeNull();
  });
  it('recognizes a bare job handle', () => {
    expect(isJobHandle({ jobId: 'j1' })).toBe(true);
    expect(isJobHandle({ candidates: [] })).toBe(false);
    expect(isJobHandle({ clips: [] })).toBe(false);
    expect(isJobHandle({})).toBe(false);
    expect(isJobHandle(null)).toBe(false);
  });
});

describe('waitForJobDone', () => {
  it('resolves null when the api has no onJobDone hook', async () => {
    const api: Api = { rpc: vi.fn(), onProgress: () => () => {} };
    await expect(waitForJobDone(api, 'j1', extractCandidates)).resolves.toBeNull();
  });

  it('resolves with the matching job result', async () => {
    let cb: ((d: JobDone) => void) | null = null;
    const api: Api = {
      rpc: vi.fn(),
      onProgress: () => () => {},
      onJobDone: (fn) => {
        cb = fn;
        return () => {
          cb = null;
        };
      },
    };
    const p = waitForJobDone(api, 'j1', extractCandidates);
    cb!({ jobId: 'other', result: { candidates: [] } }); // ignored
    cb!({ jobId: 'j1', result: { candidates: THREE } }); // matched
    await expect(p).resolves.toHaveLength(3);
  });

  // ---- HIGH #5: timeout guard so a dead sidecar can't hang the UI -----------

  it('rejects with a user-facing error when the timeout elapses (fake timers)', async () => {
    vi.useFakeTimers();
    try {
      let off = false;
      const api: Api = {
        rpc: vi.fn(),
        onProgress: () => () => {},
        // job.done NEVER fires (dead sidecar); the unsubscribe must still run.
        onJobDone: () => () => {
          off = true;
        },
      };
      const p = waitForJobDone(api, 'j1', extractClips, EXPORT_JOB_TIMEOUT_MS);
      // Attach the rejection handler BEFORE advancing time (no unhandled reject).
      const assertion = expect(p).rejects.toThrow(/Timed out waiting for the job/);
      await vi.advanceTimersByTimeAsync(EXPORT_JOB_TIMEOUT_MS);
      await assertion;
      expect(off).toBe(true); // the subscription was cleaned up on timeout
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears the timeout when the job resolves first (no late rejection)', async () => {
    vi.useFakeTimers();
    try {
      let cb: ((d: JobDone) => void) | null = null;
      const api: Api = {
        rpc: vi.fn(),
        onProgress: () => () => {},
        onJobDone: (fn) => {
          cb = fn;
          return () => {
            cb = null;
          };
        },
      };
      const p = waitForJobDone(api, 'j1', extractClips, EXPORT_JOB_TIMEOUT_MS);
      cb!({ jobId: 'j1', result: { clips: [{ path: '/a.mp4' }] } });
      await expect(p).resolves.toEqual([{ path: '/a.mp4' }]);
      // Advancing past the deadline must NOT produce a late rejection.
      await vi.advanceTimersByTimeAsync(EXPORT_JOB_TIMEOUT_MS);
    } finally {
      vi.useRealTimers();
    }
  });

  it('applies the shared default timeout when no timeoutMs is given', async () => {
    // F2: the consolidated helper ALWAYS races a timeout (the shared default) so
    // the 9 panels that omit one still cannot hang the UI. (timeoutMs=0 to
    // disable is covered centrally in _api.test.ts.)
    vi.useFakeTimers();
    try {
      const api: Api = {
        rpc: vi.fn(),
        onProgress: () => () => {},
        onJobDone: () => () => {},
      };
      const p = waitForJobDone(api, 'j1', extractClips); // no timeout arg -> default
      const assertion = expect(p).rejects.toThrow(/Timed out waiting for the job/);
      await vi.advanceTimersByTimeAsync(EXPORT_JOB_TIMEOUT_MS);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('resolveJobResult (P4 §8c batch helper)', () => {
  const api: Api = { rpc: vi.fn(), onProgress: () => () => {} };

  it('returns the immediate payload without touching the job ref', async () => {
    const ref = { current: null as string | null };
    const out = await resolveJobResult(api, { candidates: THREE }, extractCandidates, ref);
    expect(out?.map((c) => c.rank)).toEqual([2, 1, 3]);
    expect(ref.current).toBeNull(); // no deferred job
  });

  it('records the jobId and waits for job.done on a deferred handle', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    const jobApi: Api = {
      rpc: vi.fn(),
      onProgress: () => () => {},
      onJobDone: (fn) => {
        doneCb = fn;
        return () => {
          doneCb = null;
        };
      },
    };
    const ref = { current: null as string | null };
    const p = resolveJobResult(jobApi, { jobId: 'job-9' }, extractClips, ref);
    expect(ref.current).toBe('job-9'); // recorded for progress/cancel
    doneCb!({ jobId: 'job-9', result: { clips: [{ path: '/out/x.mp4' }] } });
    const out = await p;
    expect(out).toEqual([{ path: '/out/x.mp4' }]);
  });

  it('resolves null for a non-result, non-handle payload', async () => {
    const ref = { current: null as string | null };
    expect(await resolveJobResult(api, { ok: true }, extractCandidates, ref)).toBeNull();
    expect(ref.current).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Component tests (React 18 createRoot + act, jsdom). API seam mocked.
// ---------------------------------------------------------------------------

function makeApi(over: Partial<Api> = {}): Api {
  return {
    rpc: vi.fn(),
    onProgress: vi.fn(() => () => {}),
    ...over,
  };
}

describe('<ShortMaker /> component', () => {
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
    vi.restoreAllMocks();
  });

  function render(el: React.ReactElement) {
    act(() => {
      root.render(el);
    });
  }

  function flush() {
    return act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  function byLabel(label: string): HTMLElement | null {
    return container.querySelector(`[aria-label="${label}"]`);
  }

  it('renders the prompt + all structured controls', () => {
    render(<ShortMaker videoId="v1" api={makeApi()} />);
    expect(byLabel('Prompt')).toBeTruthy();
    expect(byLabel('Count')).toBeTruthy();
    expect(byLabel('Min seconds')).toBeTruthy();
    expect(byLabel('Max seconds')).toBeTruthy();
    expect(byLabel('Aspect')).toBeTruthy();
    expect(byLabel('Language')).toBeTruthy();
    expect(byLabel('Caption style')).toBeTruthy();
  });

  it('calls shortmaker.select with videoId, prompt and sanitized controls', async () => {
    const api = makeApi({ rpc: vi.fn().mockResolvedValue({ candidates: THREE }) });
    render(<ShortMaker videoId="v1" api={api} initialControls={{ count: 3, aspect: '9:16' }} />);

    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();

    expect(api.rpc).toHaveBeenCalledWith(
      'shortmaker.select',
      expect.objectContaining({
        videoId: 'v1',
        prompt: '',
        controls: expect.objectContaining({
          count: 3,
          aspect: '9:16',
          minSec: expect.any(Number),
          maxSec: expect.any(Number),
          language: expect.any(String),
          captionStyle: expect.any(String),
        }),
      }),
    );
  });

  it('renders ranked candidates after select resolves', async () => {
    const api = makeApi({ rpc: vi.fn().mockResolvedValue({ candidates: THREE }) });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();

    const rows = container.querySelectorAll('.sm-candidate');
    expect(rows.length).toBe(3);
    // ranked ascending
    expect(rows[0].getAttribute('data-id')).toBe('1@97');
  });

  it('export is blocked until a candidate is approved (nothing auto-exports)', async () => {
    const rpc = vi.fn().mockResolvedValue({ candidates: THREE });
    const api = makeApi({ rpc });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();

    // The export button exists but is disabled with 0 approved.
    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    expect(exportBtn).toBeTruthy();
    expect(exportBtn.disabled).toBe(true);

    // shortmaker.export was never called.
    expect(rpc.mock.calls.find((c) => c[0] === 'shortmaker.export')).toBeUndefined();
  });

  it('exports ONLY approved candidate ids on explicit approve+export', async () => {
    // Method-aware fake: the mount-time tracks.audio.list call (the A2 audio
    // picker) must not consume an order-based mock meant for select/export.
    const rpc = vi.fn(async (method: string) => {
      if (method === 'tracks.audio.list') return { audioTracks: [] };
      if (method === 'shortmaker.select') return { candidates: THREE };
      if (method === 'shortmaker.export') return { clips: [{ path: '/out/1.mp4' }] };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({ rpc });
    render(<ShortMaker videoId="v1" api={api} />);

    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();

    // Approve rank 1 only.
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    const approveBtn = row.querySelector('[aria-label="Approve"]') as HTMLButtonElement;
    act(() => approveBtn.click());

    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    expect(exportBtn.disabled).toBe(false);

    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await flush();

    // Export sends the approved ids (and, as a restart-safe fallback, the
    // approved candidate objects). The key guarantee: ONLY the approved id.
    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.export',
      expect.objectContaining({ videoId: 'v1', candidateIds: ['1@97'] }),
    );
  });

  it('nudge updates the displayed boundaries, reset restores them (non-destructive)', async () => {
    const api = makeApi({
      rpc: vi
        .fn()
        .mockResolvedValue({ candidates: [cand({ start: 100, end: 140, durationSec: 40 })] }),
    });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();

    const row = container.querySelector('.sm-candidate')!;
    const laterEnd = row.querySelector('[aria-label="Later end"]') as HTMLButtonElement;
    act(() => laterEnd.click());
    expect(row.querySelector('.sm-nudged')).toBeTruthy();

    const resetBtn = row.querySelector('[aria-label="Reset boundaries"]') as HTMLButtonElement;
    expect(resetBtn).toBeTruthy();
    act(() => resetBtn.click());
    expect(container.querySelector('.sm-nudged')).toBeNull();
  });

  it('shows an empty-state message when select returns no candidates', async () => {
    const api = makeApi({ rpc: vi.fn().mockResolvedValue({ candidates: [] }) });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-empty')).toBeTruthy();
  });

  it('surfaces an error when select rejects', async () => {
    const api = makeApi({ rpc: vi.fn().mockRejectedValue(new Error('sidecar down')) });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('sidecar down');
  });

  it('subscribes to onProgress on mount', () => {
    const onProgress = vi.fn(() => () => {});
    render(<ShortMaker videoId="v1" api={makeApi({ onProgress })} />);
    expect(onProgress).toHaveBeenCalled();
  });

  it('button label switches to Regenerate once candidates exist', async () => {
    const api = makeApi({ rpc: vi.fn().mockResolvedValue({ candidates: THREE }) });
    render(<ShortMaker videoId="v1" api={api} />);
    let submit = container.querySelector('button[type="submit"]')!;
    expect(submit.textContent).toBe('Find clips');

    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();
    submit = container.querySelector('button[type="submit"]')!;
    expect(submit.textContent).toBe('Regenerate');
  });

  it('resolves a deferred select job via job.done', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    const api = makeApi({
      rpc: vi.fn().mockResolvedValue({ jobId: 'job-1' }),
      onJobDone: (fn) => {
        doneCb = fn;
        return () => {
          doneCb = null;
        };
      },
    });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    // The promise is now awaiting job.done; fire it.
    await act(async () => {
      doneCb!({ jobId: 'job-1', result: { candidates: THREE } });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelectorAll('.sm-candidate').length).toBe(3);
  });

  // ---- T4b: caption style picker + reframe engine override -----------------

  it('renders the caption style picker with the full catalog, libass default selected', () => {
    render(<ShortMaker videoId="v1" api={makeApi()} />);
    const select = byLabel('Caption style') as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect([...select.options].map((o) => o.value)).toEqual(CAPTION_STYLES.map((s) => s.id));
    expect(select.value).toBe(DEFAULT_CAPTION_STYLE);
  });

  it('renders the reframe engine override with auto/verthor/claudeshorts, auto selected', () => {
    render(<ShortMaker videoId="v1" api={makeApi()} />);
    const select = byLabel('Reframe engine') as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect([...select.options].map((o) => o.value)).toEqual(['auto', 'verthor', 'claudeshorts']);
    expect(select.value).toBe('auto');
  });

  it('flows a picked style + engine override into shortmaker.select controls', async () => {
    const api = makeApi({ rpc: vi.fn().mockResolvedValue({ candidates: THREE }) });
    render(<ShortMaker videoId="v1" api={api} />);

    const style = byLabel('Caption style') as HTMLSelectElement;
    act(() => {
      style.value = 'bounce';
      style.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const engine = byLabel('Reframe engine') as HTMLSelectElement;
    act(() => {
      engine.value = 'claudeshorts';
      engine.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();

    expect(api.rpc).toHaveBeenCalledWith(
      'shortmaker.select',
      expect.objectContaining({
        controls: expect.objectContaining({
          captionStyle: 'bounce',
          reframeEngine: 'claudeshorts',
        }),
      }),
    );
  });

  it('carries captionStyle + reframeEngine into the shortmaker.export params', async () => {
    // Method-aware fake (see the approve+export test above).
    const rpc = vi.fn(async (method: string) => {
      if (method === 'tracks.audio.list') return { audioTracks: [] };
      if (method === 'shortmaker.select') return { candidates: THREE };
      if (method === 'shortmaker.export') return { clips: [{ path: '/out/1.mp4' }] };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({ rpc });
    render(
      <ShortMaker
        videoId="v1"
        api={api}
        initialControls={{ captionStyle: 'bold', reframeEngine: 'verthor' }}
      />,
    );

    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();

    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());

    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await flush();

    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.export',
      expect.objectContaining({
        videoId: 'v1',
        candidateIds: ['1@97'],
        captionStyle: 'bold',
        reframeEngine: 'verthor',
      }),
    );
  });

  it('select sends the sanitized defaults for style/engine when untouched', async () => {
    const api = makeApi({ rpc: vi.fn().mockResolvedValue({ candidates: [] }) });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();
    expect(api.rpc).toHaveBeenCalledWith(
      'shortmaker.select',
      expect.objectContaining({
        controls: expect.objectContaining({
          captionStyle: DEFAULT_CAPTION_STYLE,
          reframeEngine: 'auto',
        }),
      }),
    );
  });

  // -------------------------------------------------------------------------
  // P3 wave — toggles, virality cards, feedback flywheel, stats footer.
  // -------------------------------------------------------------------------

  /** Method-aware rpc fake: mount calls tracks.audio.list + feedback.stats,
   *  so order-based mocks would misfire — route by method name instead. */
  function rpcFake(handlers: Record<string, unknown>): Api['rpc'] & ReturnType<typeof vi.fn> {
    return vi.fn(async (method: string) => {
      const h = handlers[method];
      if (h instanceof Error) throw h;
      return h ?? {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
  }

  async function submitForm() {
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await flush();
  }

  it('renders the two P3 toggles with their V1 defaults (hook title ON, fillers ON + experimental tag)', () => {
    render(<ShortMaker videoId="v1" api={makeApi()} />);
    const hook = byLabel('Hook title') as HTMLInputElement;
    const fillers = byLabel('Remove fillers') as HTMLInputElement;
    expect(hook).toBeTruthy();
    expect(hook.type).toBe('checkbox');
    expect(hook.checked).toBe(true);
    expect(fillers).toBeTruthy();
    expect(fillers.type).toBe('checkbox');
    expect(fillers.checked).toBe(true);
    const tag = container.querySelector('.sm-tag-exp');
    expect(tag?.textContent).toBe('experimental');
  });

  it('flows toggled hookTitle/removeFillers into shortmaker.select controls', async () => {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: [] } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);

    act(() => (byLabel('Hook title') as HTMLInputElement).click()); // ON -> OFF
    act(() => (byLabel('Remove fillers') as HTMLInputElement).click()); // ON -> OFF (V1 default ON)
    await submitForm();

    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.select',
      expect.objectContaining({
        controls: expect.objectContaining({ hookTitle: false, removeFillers: false }),
      }),
    );
  });

  it('carries hookTitle + removeFillers into the shortmaker.export params (like captionStyle)', async () => {
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }] },
    });
    render(
      <ShortMaker videoId="v1" api={makeApi({ rpc })} initialControls={{ removeFillers: true }} />,
    );
    await submitForm();

    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await flush();

    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.export',
      expect.objectContaining({
        videoId: 'v1',
        candidateIds: ['1@97'],
        hookTitle: true,
        removeFillers: true,
      }),
    );
  });

  it('carries autoZoom (§8b) + emphasis (§8a) from the UI controls into export params', async () => {
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }] },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    // Flip the two new controls in the UI (proving the call site exists).
    act(() => (byLabel('Auto zoom') as HTMLInputElement).click()); // ON -> OFF (V1 default ON)
    const emphasisSel = byLabel('Emphasis') as HTMLSelectElement;
    act(() => {
      emphasisSel.value = 'on';
      emphasisSel.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await flush();

    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.export',
      expect.objectContaining({ videoId: 'v1', autoZoom: false, emphasis: true }),
    );
  });

  it('seeds the emphasis control from the per-style default when the caption style changes (P4 §8a)', async () => {
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }] },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    const styleSel = byLabel('Caption style') as HTMLSelectElement;
    const emphasisSel = byLabel('Emphasis') as HTMLSelectElement;

    // Pick a CLEAN template -> emphasis seeds OFF (mirrors the sidecar default).
    act(() => {
      styleSel.value = 'clean';
      styleSel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(emphasisSel.value).toBe('off');

    // Pick an OpusClip-style template -> emphasis seeds ON.
    act(() => {
      styleSel.value = 'bold';
      styleSel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(emphasisSel.value).toBe('on');

    // The seeded ON choice flows as an explicit bool into the export params.
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await flush();

    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.export',
      expect.objectContaining({ videoId: 'v1', captionStyle: 'bold', emphasis: true }),
    );
  });

  it('headlines viralityPct, demotes the legacy score to a tooltip, and expands the four factor bars', async () => {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: [factored()] } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    const row = container.querySelector('.sm-candidate')!;
    const virality = row.querySelector('.sm-virality') as HTMLElement;
    expect(virality).toBeTruthy();
    expect(virality.textContent).toBe('87%');
    expect(virality.getAttribute('title')).toContain('95'); // legacy score tooltip
    expect(row.querySelector('.sm-score')).toBeNull(); // score chip replaced

    // Expand the factor breakdown.
    const toggle = row.querySelector('[aria-label="Factor breakdown"]') as HTMLButtonElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(row.querySelector('.sm-factors')).toBeNull();
    act(() => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');

    const factors = [...row.querySelectorAll('.sm-factor')];
    expect(factors.map((f) => f.getAttribute('data-factor'))).toEqual([
      'hookStrength',
      'emotionalFlow',
      'perceivedValue',
      'shareability',
    ]);
    expect(factors.map((f) => f.getAttribute('data-value'))).toEqual(['88', '64', '71', '90']);
    const fills = [...row.querySelectorAll('.sm-factor-fill')] as HTMLElement[];
    expect(fills).toHaveLength(4);
    expect(fills.map((f) => f.style.width)).toEqual(['88%', '64%', '71%', '90%']);
    expect(factors[0].querySelector('.sm-factor-note')?.textContent).toBe('Opens mid-claim');
    expect(factors[0].querySelector('.sm-factor-label')?.textContent).toBe('Hook strength');

    // Collapses again.
    act(() => toggle.click());
    expect(row.querySelector('.sm-factors')).toBeNull();
  });

  it('keeps the legacy score chip (and no factor toggle) for pre-P3 candidates', async () => {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: [cand()] } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    const row = container.querySelector('.sm-candidate')!;
    expect(row.querySelector('.sm-score')?.textContent).toBe('95');
    expect(row.querySelector('.sm-virality')).toBeNull();
    expect(row.querySelector('[aria-label="Factor breakdown"]')).toBeNull();
  });

  it('fires feedback.record for approve / discard / nudge (fire-and-forget)', async () => {
    const rpc = rpcFake({
      'shortmaker.select': { candidates: [cand({ start: 100, end: 140, durationSec: 40 })] },
      'feedback.record': { ok: true },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    const row = container.querySelector('.sm-candidate')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    act(() => (row.querySelector('[aria-label="Discard"]') as HTMLButtonElement).click());
    act(() => (row.querySelector('[aria-label="Later end"]') as HTMLButtonElement).click());
    await flush();

    const fb = rpc.mock.calls.filter((c) => c[0] === 'feedback.record');
    expect(fb.map((c) => (c[1] as { action: string }).action)).toEqual([
      'approved',
      'discarded',
      'nudged',
    ]);
    expect(fb[0][1]).toMatchObject({
      videoId: 'v1',
      action: 'approved',
      candidate: expect.objectContaining({ rank: 1, start: 100, end: 140 }),
    });
    // The nudge label carries the POST-nudge boundaries (end 140 -> 141).
    expect(fb[2][1]).toMatchObject({
      candidate: expect.objectContaining({ end: 141 }),
      action: 'nudged',
    });
  });

  it('records one exported feedback action per exported candidate', async () => {
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }, { path: '/out/2.mp4' }] },
      'feedback.record': { ok: true },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    for (const id of ['1@97', '2@199']) {
      const row = container.querySelector(`.sm-candidate[data-id="${id}"]`)!;
      act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    }
    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await flush();

    const exported = rpc.mock.calls.filter(
      (c) => c[0] === 'feedback.record' && (c[1] as { action: string }).action === 'exported',
    );
    expect(exported).toHaveLength(2);
    expect(exported.map((c) => (c[1] as { candidate: Candidate }).candidate.rank).sort()).toEqual([
      1, 2,
    ]);
  });

  it('a failing feedback.record never blocks the review action (silent-logged)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const rpc = rpcFake({
      'shortmaker.select': { candidates: [cand()] },
      'feedback.record': new Error('feedback store down'),
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    const row = container.querySelector('.sm-candidate')!;
    await act(async () => {
      (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();

    // The approve landed; no error surfaced; the failure went to the log.
    expect(row.querySelector('.sm-status-approved')).toBeTruthy();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(warn).toHaveBeenCalled();
  });

  it('renders the taste-profile footer from feedback.stats', async () => {
    const rpc = rpcFake({ 'feedback.stats': { labels: 37, calibrated: false } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();

    expect(rpc).toHaveBeenCalledWith('feedback.stats');
    const footer = container.querySelector('.sm-feedback-stats');
    expect(footer?.textContent).toContain('Taste profile: 37 labels');
    expect(footer?.textContent).toContain(`calibration at ${CALIBRATION_LABELS}`);
  });

  it('shows "calibrated" once feedback.stats reports calibration', async () => {
    const rpc = rpcFake({ 'feedback.stats': { labels: 64, calibrated: true } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect(container.querySelector('.sm-feedback-stats')?.textContent).toContain('calibrated');
  });

  it('hides the footer when feedback.stats fails or returns junk', async () => {
    const rpc = rpcFake({ 'feedback.stats': new Error('no store') });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect(container.querySelector('.sm-feedback-stats')).toBeNull();
  });

  it('shows per-clip filler-removal stats on the exported list when present', async () => {
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': {
        clips: [
          { path: '/out/1.mp4', fillersRemoved: 4, fillerSeconds: 2.5 },
          { path: '/out/2.mp4' }, // pass skipped -> no annotation
        ],
      },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await flush();

    const lis = [...container.querySelectorAll('.sm-exported li')];
    expect(lis).toHaveLength(2);
    expect(lis[0].querySelector('.sm-fillers')?.textContent).toContain('removed 4 fillers (2.5s)');
    expect(lis[1].querySelector('.sm-fillers')).toBeNull();
  });

  // -------------------------------------------------------------------------
  // P4 §5 — live caption overlay + preview-remount fix.
  // -------------------------------------------------------------------------

  it('fetches captions.cues for the videoId on mount', async () => {
    const rpc = rpcFake({ 'captions.cues': { cues: [] } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect(rpc).toHaveBeenCalledWith('captions.cues', { videoId: 'v1' });
  });

  it('overlays the live caption (word run + hook title) inside .sm-phone over the Player', async () => {
    const rpc = rpcFake({
      // a candidate cut at source 100..130; cues are source-absolute.
      'shortmaker.select': {
        candidates: [
          cand({
            rank: 1,
            start: 100,
            end: 130,
            durationSec: 30,
            sourceStart: 100,
            hook: 'Big idea',
          }),
        ],
      },
      'captions.cues': {
        cues: [
          { index: 1, start: 101.0, end: 101.5, text: 'Hello' },
          { index: 2, start: 101.5, end: 102.0, text: 'world' },
        ],
      },
    });
    render(
      <ShortMaker videoId="v1" api={makeApi({ rpc })} initialControls={{ captionStyle: 'bold' }} />,
    );
    await submitForm();

    const phone = container.querySelector('.sm-phone')!;
    const overlay = phone.querySelector('.caption-overlay');
    expect(overlay).toBeTruthy();
    // The overlay sits over the <Player> video, inside the phone frame.
    expect(phone.querySelector('video')).toBeTruthy();

    // Drive the playhead to mid-"Hello" via the Player's onTimeUpdate.
    const video = phone.querySelector('video') as HTMLVideoElement;
    await act(async () => {
      (video as unknown as { currentTime: number }).currentTime = 101.2;
      video.dispatchEvent(new Event('timeupdate'));
      await Promise.resolve();
    });
    await flush();

    expect(phone.querySelector('.caption-overlay__word.is-active')?.textContent).toBe('Hello');
    // The hook title shows in its slot (hookTitle default ON).
    expect(phone.querySelector('[data-hook-title="true"]')?.textContent).toBe('Big idea');
  });

  it('updates the overlay live when the caption-style select changes (none -> rendered)', async () => {
    const rpc = rpcFake({
      'shortmaker.select': {
        candidates: [cand({ rank: 1, start: 100, end: 130, durationSec: 30, sourceStart: 100 })],
      },
      'captions.cues': { cues: [{ index: 1, start: 101.0, end: 101.5, text: 'Hi' }] },
    });
    // Start with "none" -> overlay no-ops.
    render(
      <ShortMaker videoId="v1" api={makeApi({ rpc })} initialControls={{ captionStyle: 'none' }} />,
    );
    await submitForm();

    const phone = container.querySelector('.sm-phone')!;
    const video = phone.querySelector('video') as HTMLVideoElement;
    await act(async () => {
      (video as unknown as { currentTime: number }).currentTime = 101.2;
      video.dispatchEvent(new Event('timeupdate'));
      await Promise.resolve();
    });
    await flush();
    expect(phone.querySelector('.caption-overlay')).toBeNull();

    // Switch to a real template -> overlay appears live (no re-select needed).
    const style = byLabel('Caption style') as HTMLSelectElement;
    await act(async () => {
      style.value = 'hormozi';
      style.dispatchEvent(new Event('change', { bubbles: true }));
      await Promise.resolve();
    });
    await flush();
    const phone2 = container.querySelector('.sm-phone')!;
    expect(phone2.querySelector('.caption-overlay')?.getAttribute('data-template')).toBe('hormozi');
  });

  it('checks media.playable for the preview and does NOT start a second proxy build', async () => {
    const rpc = rpcFake({
      'media.playable': { playable: false, reason: 'building…' },
      'shortmaker.select': { candidates: [cand()] },
      'captions.cues': { cues: [] },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect(rpc).toHaveBeenCalledWith('media.playable', { videoId: 'v1' });
    // §5: ShortMaker must NOT kick its own proxy build (Workspace owns it).
    expect(rpc.mock.calls.find((c) => c[0] === 'media.proxy.start')).toBeUndefined();
  });

  it('remounts the preview Player once the proxy makes the source playable (job.done re-poll)', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    let playable = false;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'media.playable') return { playable };
      if (method === 'shortmaker.select') {
        return {
          candidates: [cand({ rank: 1, start: 100, end: 130, durationSec: 30, sourceStart: 100 })],
        };
      }
      if (method === 'captions.cues') return { cues: [] };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onJobDone: (fn) => {
        doneCb = fn;
        return () => {
          doneCb = null;
        };
      },
    });
    render(<ShortMaker videoId="v1" api={api} />);
    await submitForm();

    const keyBefore = (container.querySelector('.sm-phone video') as HTMLElement | null) !== null;
    expect(keyBefore).toBe(true);

    // The Workspace proxy job finishes; the source becomes playable.
    playable = true;
    await act(async () => {
      doneCb!({ jobId: 'proxy-1', result: { path: '/proxy/v1.mp4' } });
      await Promise.resolve();
    });
    await flush();

    // media.playable was re-polled after the job.done (more than the initial call).
    const playableCalls = rpc.mock.calls.filter((c) => c[0] === 'media.playable');
    expect(playableCalls.length).toBeGreaterThanOrEqual(2);
    // The preview player is still present (it remounted, re-fetching the proxy).
    expect(container.querySelector('.sm-phone video')).toBeTruthy();
  });

  // -------------------------------------------------------------------------
  // P4 §7 — scoring surfacing: sort-by-virality toggle on the candidate list.
  // -------------------------------------------------------------------------

  it('renders a Rank/Virality sort toggle (Rank active by default) once candidates load', async () => {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: THREE } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    const group = container.querySelector('[aria-label="Sort candidates"]')!;
    expect(group).toBeTruthy();
    const [rankBtn, viralityBtn] = [...group.querySelectorAll('button')] as HTMLButtonElement[];
    expect(rankBtn.textContent).toBe('Rank');
    expect(viralityBtn.textContent).toBe('Virality');
    expect(rankBtn.getAttribute('aria-pressed')).toBe('true');
    expect(viralityBtn.getAttribute('aria-pressed')).toBe('false');
  });

  it('reorders the candidate rows by viralityPct when the Virality sort is picked', async () => {
    const rpc = rpcFake({
      'shortmaker.select': {
        candidates: [
          cand({ rank: 1, sourceStart: 1, viralityPct: 40 }),
          cand({ rank: 2, sourceStart: 2, viralityPct: 90 }),
          cand({ rank: 3, sourceStart: 3, viralityPct: 70 }),
        ],
      },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();

    // Default rank order: 1,2,3.
    const idsRank = [...container.querySelectorAll('.sm-candidate')].map((r) =>
      r.getAttribute('data-id'),
    );
    expect(idsRank).toEqual(['1@1', '2@2', '3@3']);

    // Switch to Virality -> 90,70,40 => ranks 2,3,1.
    const viralityBtn = [
      ...container.querySelectorAll('[aria-label="Sort candidates"] button'),
    ].find((b) => b.textContent === 'Virality') as HTMLButtonElement;
    act(() => viralityBtn.click());

    const idsVir = [...container.querySelectorAll('.sm-candidate')].map((r) =>
      r.getAttribute('data-id'),
    );
    expect(idsVir).toEqual(['2@2', '3@3', '1@1']);
    expect(viralityBtn.getAttribute('aria-pressed')).toBe('true');
  });

  // -------------------------------------------------------------------------
  // P4 §8c — platform presets + batch "Make N".
  // -------------------------------------------------------------------------

  it('renders TikTok/Reels/Shorts preset buttons that set aspect/maxSec/count', async () => {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: [] } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);

    const presets = container.querySelector('[aria-label="Platform presets"]')!;
    expect(presets).toBeTruthy();
    const reels = presets.querySelector('[data-preset="reels"]') as HTMLButtonElement;
    expect(reels).toBeTruthy();
    act(() => reels.click());

    // The change flows into the next select's controls. Reels asks for 90 but the
    // §5 hard window clamps it to 60 (renderer + sidecar both enforce this).
    await submitForm();
    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.select',
      expect.objectContaining({
        controls: expect.objectContaining({ aspect: '9:16', maxSec: 60, count: 3 }),
      }),
    );
    // The Max seconds input reflects the (clamped) preset live.
    expect((byLabel('Max seconds') as HTMLInputElement).value).toBe('60');
  });

  it('"Make N shorts" runs select -> auto-approve top N by virality -> export unattended', async () => {
    const candidates = [
      cand({ rank: 1, sourceStart: 1, viralityPct: 30 }),
      cand({ rank: 2, sourceStart: 2, viralityPct: 95 }),
      cand({ rank: 3, sourceStart: 3, viralityPct: 80 }),
      cand({ rank: 4, sourceStart: 4, viralityPct: 60 }),
    ];
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates },
      'shortmaker.export': { clips: [{ path: '/out/a.mp4' }, { path: '/out/b.mp4' }] },
      'shorts.list': { shorts: [] },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} initialControls={{ count: 2 }} />);

    const batchBtn = byLabel('Make N shorts') as HTMLButtonElement;
    expect(batchBtn.textContent).toBe('Make 2 shorts');
    await act(async () => {
      batchBtn.click();
      await Promise.resolve();
    });
    await flush();

    // select ran with count 2.
    expect(rpc).toHaveBeenCalledWith(
      'shortmaker.select',
      expect.objectContaining({ videoId: 'v1', controls: expect.objectContaining({ count: 2 }) }),
    );
    // export auto-approved the TOP 2 by viralityPct: ranks 2 (95) + 3 (80).
    const exportCall = rpc.mock.calls.find((c) => c[0] === 'shortmaker.export')!;
    expect(exportCall).toBeTruthy();
    const params = exportCall[1] as { candidateIds: string[]; candidates: Candidate[] };
    expect(params.candidateIds).toEqual(['2@2', '3@3']);
    expect(params.candidates.map((c) => c.rank)).toEqual([2, 3]);
    // the exported summary shows the produced clips.
    expect(container.querySelector('.sm-exported')?.textContent).toContain('Exported 2 clip(s)');
  });

  it('batch shows the empty state (not an error) and does NOT export when no candidates are proposed', async () => {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: [] } });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} initialControls={{ count: 3 }} />);
    await act(async () => {
      (byLabel('Make N shorts') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(rpc.mock.calls.find((c) => c[0] === 'shortmaker.export')).toBeUndefined();
    // F1: a confirmed zero-result is the EMPTY state, not an error alert/Retry.
    expect(container.querySelector('.sm-empty')?.textContent).toContain('No candidates');
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  // -------------------------------------------------------------------------
  // P4 §8d — brand kit settings (load via settings.get, save via settings.set).
  // -------------------------------------------------------------------------

  it('hydrates the brand kit from settings.get and shows the persisted values', async () => {
    const rpc = rpcFake({
      'settings.get': {
        brandLogoPath: '/logos/me.png',
        brandCaptionTemplate: 'hormozi',
        brandFontFamily: 'Inter',
      },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    expect(rpc).toHaveBeenCalledWith('settings.get');

    // Open the Brand kit section.
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());

    expect((byLabel('Default caption template') as HTMLSelectElement).value).toBe('hormozi');
    expect((byLabel('Default font family') as HTMLInputElement).value).toBe('Inter');
    expect(container.querySelector('.sm-brand-logo-path')?.textContent).toBe('/logos/me.png');
  });

  it('tolerates absent brand keys on load (empty kit, no crash)', async () => {
    const rpc = rpcFake({ 'settings.get': { useCloud: true } }); // no brand keys
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());
    expect((byLabel('Default caption template') as HTMLSelectElement).value).toBe('');
    expect((byLabel('Default font family') as HTMLInputElement).value).toBe('');
    expect(container.querySelector('.sm-brand-logo-empty')).toBeTruthy();
  });

  it('persists a brand edit via settings.set with the three FROZEN keys', async () => {
    const rpc = rpcFake({ 'settings.get': {} });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());

    const font = byLabel('Default font family') as HTMLInputElement;
    act(() => {
      // Use the native value setter so React's controlled-input tracking sees it.
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
      setter.call(font, 'Montserrat');
      font.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await flush();

    const setCall = rpc.mock.calls.find((c) => c[0] === 'settings.set');
    expect(setCall).toBeTruthy();
    expect(setCall![1]).toEqual({
      brandLogoPath: '',
      brandCaptionTemplate: '',
      brandFontFamily: 'Montserrat',
    });
  });

  it('picks a logo via the pickLogoFile bridge and persists it', async () => {
    const rpc = rpcFake({ 'settings.get': {} });
    const pickLogoFile = vi.fn().mockResolvedValue('/picked/logo.png');
    render(<ShortMaker videoId="v1" api={makeApi({ rpc, pickLogoFile })} />);
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());

    await act(async () => {
      (byLabel('Pick logo file') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();

    expect(pickLogoFile).toHaveBeenCalled();
    const setCall = rpc.mock.calls.find(
      (c) =>
        c[0] === 'settings.set' &&
        (c[1] as { brandLogoPath?: string }).brandLogoPath === '/picked/logo.png',
    );
    expect(setCall).toBeTruthy();
    expect(container.querySelector('.sm-brand-logo-path')?.textContent).toBe('/picked/logo.png');
  });

  it('surfaces an error when the logo picker bridge is absent', async () => {
    const rpc = rpcFake({ 'settings.get': {} });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />); // no pickLogoFile
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());
    await act(async () => {
      (byLabel('Pick logo file') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'Logo picker is unavailable',
    );
  });

  // -------------------------------------------------------------------------
  // Keyboard review (T6) — the handleReviewKeys handler.
  // -------------------------------------------------------------------------

  function key(init: KeyboardEventInit): void {
    const group = container.querySelector('.sm-review') as HTMLElement;
    act(() => {
      group.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, ...init }));
    });
  }

  async function loadThree(
    rpcOver?: Record<string, unknown>,
  ): Promise<Api['rpc'] & ReturnType<typeof vi.fn>> {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: THREE }, ...rpcOver });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();
    return rpc;
  }

  it('J/K move the review selection (with sort order), wrapping at the ends', async () => {
    await loadThree();
    const selectedId = () =>
      container.querySelector('.sm-candidate.sm-selected')?.getAttribute('data-id');
    // Initial selection is the first row.
    expect(selectedId()).toBe('1@97');
    key({ key: 'j' });
    expect(selectedId()).toBe('2@199');
    key({ key: 'J' });
    expect(selectedId()).toBe('3@494');
    key({ key: 'j' }); // clamp at the bottom
    expect(selectedId()).toBe('3@494');
    key({ key: 'k' });
    expect(selectedId()).toBe('2@199');
    key({ key: 'K' });
    expect(selectedId()).toBe('1@97');
  });

  it('Space toggles the preview player play/pause', async () => {
    await loadThree();
    playMock.mockClear();
    pauseMock.mockClear();
    // The Player starts paused -> Space plays.
    key({ key: ' ' });
    expect(playMock).toHaveBeenCalled();
  });

  it('Space pauses when the preview player is already playing', async () => {
    await loadThree();
    playMock.mockClear();
    pauseMock.mockClear();
    const video = container.querySelector('.sm-phone video') as HTMLVideoElement;
    // Mark the element as playing so isPlaying() returns true -> Space pauses.
    pausedStates.set(video, false);
    key({ key: ' ' });
    expect(pauseMock).toHaveBeenCalled();
    pausedStates.delete(video);
  });

  it('A approves and X discards the selected candidate', async () => {
    await loadThree();
    key({ key: 'a' });
    expect(
      container.querySelector('.sm-candidate.sm-selected')?.querySelector('.sm-status-approved'),
    ).toBeTruthy();
    key({ key: 'x' });
    expect(
      container.querySelector('.sm-candidate.sm-selected')?.querySelector('.sm-status-discarded'),
    ).toBeTruthy();
  });

  it('ArrowLeft/ArrowRight nudge the selected window (shift = fine step)', async () => {
    const rpc = rpcFake({
      'shortmaker.select': {
        candidates: [cand({ rank: 1, start: 100, end: 140, durationSec: 40, sourceStart: 100 })],
      },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();
    key({ key: 'ArrowRight' });
    expect(container.querySelector('.sm-nudged')).toBeTruthy();
    key({ key: 'ArrowLeft', shiftKey: true });
    // Still nudged (coarse +1 then fine -0.2 => +0.8 window shift).
    expect(container.querySelector('.sm-nudged')).toBeTruthy();
  });

  it('ignores review keys with a modifier or from a text-entry target', async () => {
    await loadThree();
    const selectedId = () =>
      container.querySelector('.sm-candidate.sm-selected')?.getAttribute('data-id');
    expect(selectedId()).toBe('1@97');
    // Ctrl/meta/alt chords are left alone.
    key({ key: 'j', ctrlKey: true });
    expect(selectedId()).toBe('1@97');
    key({ key: 'j', metaKey: true });
    expect(selectedId()).toBe('1@97');
    key({ key: 'j', altKey: true });
    expect(selectedId()).toBe('1@97');
    // A keydown whose target is an INPUT/SELECT/TEXTAREA is ignored.
    const group = container.querySelector('.sm-review') as HTMLElement;
    const input = document.createElement('input');
    group.appendChild(input);
    act(() => {
      input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'j' }));
    });
    expect(selectedId()).toBe('1@97');
    // An unhandled key is a no-op (default branch).
    key({ key: 'z' });
    expect(selectedId()).toBe('1@97');
  });

  // -------------------------------------------------------------------------
  // DATA ROOT — changeDataFolder + the getDataFolder hydration effect.
  // -------------------------------------------------------------------------

  function openBrandKit(): void {
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());
  }

  it('hydrates the data folder from the getDataFolder bridge', async () => {
    const getDataFolder = vi.fn().mockResolvedValue('D:/data-root');
    render(<ShortMaker videoId="v1" api={makeApi({ rpc: rpcFake({}), getDataFolder })} />);
    await flush();
    openBrandKit();
    expect(container.querySelector('.sm-data-folder-path')?.textContent).toBe('D:/data-root');
  });

  it('shows Unavailable when getDataFolder rejects', async () => {
    const getDataFolder = vi.fn().mockRejectedValue(new Error('no bridge'));
    render(<ShortMaker videoId="v1" api={makeApi({ rpc: rpcFake({}), getDataFolder })} />);
    await flush();
    openBrandKit();
    expect(container.querySelector('.sm-data-folder-empty')).toBeTruthy();
  });

  it('changeDataFolder errors when the picker bridge is unavailable', async () => {
    render(<ShortMaker videoId="v1" api={makeApi({ rpc: rpcFake({}) })} />);
    await flush();
    openBrandKit();
    await act(async () => {
      (byLabel('Change data folder') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'Data-folder picker is unavailable',
    );
  });

  it('changeDataFolder picks a folder, persists it and flags a restart', async () => {
    const pickDataFolder = vi.fn().mockResolvedValue('E:/new-root');
    const setDataFolder = vi.fn().mockResolvedValue({ ok: true });
    const getDataFolder = vi.fn().mockResolvedValue('D:/old');
    render(
      <ShortMaker
        videoId="v1"
        api={makeApi({ rpc: rpcFake({}), pickDataFolder, setDataFolder, getDataFolder })}
      />,
    );
    await flush();
    openBrandKit();
    await act(async () => {
      (byLabel('Change data folder') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(setDataFolder).toHaveBeenCalledWith('E:/new-root');
    expect(container.querySelector('.sm-data-folder-path')?.textContent).toBe('E:/new-root');
    expect(container.querySelector('.sm-data-folder-restart')).toBeTruthy();
  });

  it('changeDataFolder is a no-op when the user cancels the picker', async () => {
    const pickDataFolder = vi.fn().mockResolvedValue(null); // cancelled
    const setDataFolder = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ShortMaker
        videoId="v1"
        api={makeApi({ rpc: rpcFake({}), pickDataFolder, setDataFolder })}
      />,
    );
    await flush();
    openBrandKit();
    await act(async () => {
      (byLabel('Change data folder') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(setDataFolder).not.toHaveBeenCalled();
    expect(container.querySelector('.sm-data-folder-restart')).toBeNull();
  });

  it('changeDataFolder surfaces a read-only setDataFolder result', async () => {
    const pickDataFolder = vi.fn().mockResolvedValue('E:/new-root');
    const setDataFolder = vi.fn().mockResolvedValue({ ok: false });
    render(
      <ShortMaker
        videoId="v1"
        api={makeApi({ rpc: rpcFake({}), pickDataFolder, setDataFolder })}
      />,
    );
    await flush();
    openBrandKit();
    await act(async () => {
      (byLabel('Change data folder') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('Could not save');
  });

  it('changeDataFolder surfaces a picker exception', async () => {
    const pickDataFolder = vi.fn().mockRejectedValue(new Error('picker crashed'));
    const setDataFolder = vi.fn().mockResolvedValue({ ok: true });
    render(
      <ShortMaker
        videoId="v1"
        api={makeApi({ rpc: rpcFake({}), pickDataFolder, setDataFolder })}
      />,
    );
    await flush();
    openBrandKit();
    await act(async () => {
      (byLabel('Change data folder') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('picker crashed');
  });

  // -------------------------------------------------------------------------
  // Export / batch deferred-job + error paths.
  // -------------------------------------------------------------------------

  it('resolves a deferred export job via job.done and shows the clips', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') return { candidates: THREE };
      if (method === 'shortmaker.export') return { jobId: 'exp-1' };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onJobDone: (fn) => {
        doneCb = fn;
        return () => {
          doneCb = null;
        };
      },
    });
    render(<ShortMaker videoId="v1" api={api} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    const exportBtn = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Export approved',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    await act(async () => {
      doneCb!({ jobId: 'exp-1', result: { clips: [{ path: '/out/deferred.mp4' }] } });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-exported')?.textContent).toContain('/out/deferred.mp4');
  });

  it('surfaces an export error', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') return { candidates: THREE };
      if (method === 'shortmaker.export') throw new Error('export blew up');
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('export blew up');
  });

  it('surfaces a batch error', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') throw new Error('batch select blew up');
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} initialControls={{ count: 2 }} />);
    await act(async () => {
      (byLabel('Make N shorts') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'batch select blew up',
    );
  });

  // ---- F1: distinct error state + Retry (re-runs the failed op) ------------

  it('a select failure shows a DISTINCT error + Retry that re-runs select', async () => {
    let n = 0;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') {
        n += 1;
        if (n === 1) throw new Error('select blew up');
        return { candidates: THREE };
      }
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('select blew up');
    const retryBtn = container.querySelector('.sm-retry') as HTMLButtonElement;
    expect(retryBtn).toBeTruthy();
    await act(async () => {
      retryBtn.click();
      await Promise.resolve();
    });
    await flush();
    // Retry re-ran select -> candidates loaded, error cleared.
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelectorAll('.sm-candidate').length).toBe(3);
  });

  it('a batch failure shows a Retry that re-runs the batch', async () => {
    let n = 0;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') {
        n += 1;
        if (n === 1) throw new Error('batch blew up');
        return { candidates: THREE };
      }
      if (method === 'shortmaker.export') return { clips: [{ path: '/out/b.mp4' }] };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} initialControls={{ count: 3 }} />);
    await act(async () => {
      (byLabel('Make N shorts') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('batch blew up');
    await act(async () => {
      (container.querySelector('.sm-retry') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-exported')?.textContent).toContain('/out/b.mp4');
  });

  it('an export failure shows a Retry that re-runs the export', async () => {
    let n = 0;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') return { candidates: THREE };
      if (method === 'shortmaker.export') {
        n += 1;
        if (n === 1) throw new Error('export blew up');
        return { clips: [{ path: '/out/e.mp4' }] };
      }
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('export blew up');
    await act(async () => {
      (container.querySelector('.sm-retry') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-exported')?.textContent).toContain('/out/e.mp4');
  });

  // ---- F2: Cancel always resets to idle (aborts the wait, no error) --------

  it('Cancel during export aborts the wait and resets to idle (no error)', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') return { candidates: THREE };
      if (method === 'shortmaker.export') return { jobId: 'exp-1' };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    // job.done NEVER fires (a cancelled export emits none) -> only the abort
    // can unwedge the wait.
    const api = makeApi({ rpc, onJobDone: () => () => undefined });
    render(<ShortMaker videoId="v1" api={api} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Cancel',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    // Idle again: no Cancel button left (escape to idle, no hang).
    expect(
      [...container.querySelectorAll('button')].find((b) => b.textContent === 'Cancel'),
    ).toBeUndefined();
  });

  it('Cancel during a batch aborts the wait and resets to idle (no hang)', async () => {
    const calls: string[] = [];
    const rpc = vi.fn(async (method: string) => {
      calls.push(method);
      if (method === 'shortmaker.select') return { jobId: 'bsel-1' };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({ rpc, onJobDone: () => () => undefined });
    render(<ShortMaker videoId="v1" api={api} initialControls={{ count: 2 }} />);
    await act(async () => {
      (byLabel('Make N shorts') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Cancel',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(calls).toContain('job.cancel');
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(
      [...container.querySelectorAll('button')].find((b) => b.textContent === 'Cancel'),
    ).toBeUndefined();
  });

  it('shows a clip with fillersRemoved but no fillerSeconds (defaults the seconds)', async () => {
    const rpc = rpcFake({
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4', fillersRemoved: 3 }] },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-fillers')?.textContent).toContain(
      'removed 3 fillers (0.0s)',
    );
  });

  it('renders progress with an empty message when the notification omits one', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    let progressCb: ((p: JobProgress) => void) | null = null;
    const rpc = vi.fn(async () => ({ jobId: 'sel-1' })) as unknown as Api['rpc'] &
      ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onProgress: (fn) => {
        progressCb = fn;
        return () => undefined;
      },
      onJobDone: (fn) => {
        doneCb = fn;
        return () => undefined;
      },
    });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await act(async () => {
      progressCb!({ jobId: 'sel-1', pct: 50, message: '' as unknown as string });
    });
    expect(container.querySelector('.sm-progress')?.textContent).toContain('50%');
    await act(async () => {
      doneCb!({ jobId: 'sel-1', result: { candidates: [] } });
      await Promise.resolve();
    });
    await flush();
  });

  // -------------------------------------------------------------------------
  // Produced-shorts gallery actions (wired via useShortsGallery).
  // -------------------------------------------------------------------------

  async function loadGallery(
    shorts: unknown[],
    over: Partial<Api> = {},
  ): Promise<{
    rpc: Api['rpc'] & ReturnType<typeof vi.fn>;
  }> {
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }] },
      'shorts.list': { shorts },
      'shorts.reexport': {
        videoId: 'v1',
        candidate: { hook: 'h', template: 't', viralityPct: 50, durationSec: 30 },
      },
      'shorts.delete': { ok: true },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc, ...over })} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    return { rpc };
  }

  const SHORT = {
    id: 'sid-1',
    path: '/out/clip.mp4',
    videoId: 'v1',
    sourceTitle: 'Talk',
    template: '',
    viralityPct: null,
    durationSec: 30,
    width: 1080,
    height: 1920,
    createdAt: 0,
    thumbnailPath: '',
    hook: '',
  };

  it('open-folder uses the openInFolder bridge', async () => {
    const openInFolder = vi.fn().mockResolvedValue(true);
    await loadGallery([SHORT], { openInFolder });
    await act(async () => {
      (byLabel('Open folder for Talk') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(openInFolder).toHaveBeenCalledWith('/out/clip.mp4');
  });

  it('re-export forwards the hint to onReexport', async () => {
    const onReexport = vi.fn();
    const rpc = rpcFake({
      'tracks.audio.list': { audioTracks: [] },
      'shortmaker.select': { candidates: THREE },
      'shortmaker.export': { clips: [{ path: '/out/1.mp4' }] },
      'shorts.list': { shorts: [SHORT] },
      'shorts.reexport': {
        videoId: 'v1',
        candidate: { hook: 'h', template: 't', viralityPct: 50, durationSec: 30 },
      },
    });
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} onReexport={onReexport} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    await act(async () => {
      (byLabel('Re-export Talk') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(onReexport).toHaveBeenCalledWith(expect.objectContaining({ videoId: 'v1' }));
  });

  it('delete confirms then removes the short and reloads the gallery', async () => {
    const confirmSpy = vi.spyOn(globalThis, 'confirm').mockReturnValue(true);
    const { rpc } = await loadGallery([SHORT]);
    await act(async () => {
      (byLabel('Delete Talk') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(rpc).toHaveBeenCalledWith('shorts.delete', { path: '/out/clip.mp4' });
    confirmSpy.mockRestore();
  });

  it('play toggles inline playback of a produced short', async () => {
    await loadGallery([SHORT]);
    const playBtn = byLabel('Play Talk') as HTMLButtonElement;
    act(() => playBtn.click());
    // The inline <video> Player appears for the playing clip.
    expect(container.querySelector('.shorts__player')).toBeTruthy();
  });

  // -------------------------------------------------------------------------
  // Misc: getApi fallback, pickLogo throw, cancel, progress targeting.
  // -------------------------------------------------------------------------

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const rpc = rpcFake({ 'shortmaker.select': { candidates: [] } });
    (globalThis as { api?: unknown }).api = makeApi({ rpc });
    try {
      render(<ShortMaker videoId="v1" />);
      await flush();
      expect(rpc).toHaveBeenCalledWith('feedback.stats');
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });

  it('surfaces a pickLogo exception from the bridge', async () => {
    const rpc = rpcFake({ 'settings.get': {} });
    const pickLogoFile = vi.fn().mockRejectedValue(new Error('picker exploded'));
    render(<ShortMaker videoId="v1" api={makeApi({ rpc, pickLogoFile })} />);
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());
    await act(async () => {
      (byLabel('Pick logo file') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('picker exploded');
  });

  it('Cancel calls job.cancel for the active (deferred) select job', async () => {
    // select resolves with a {jobId} handle, then the panel awaits job.done — so
    // activeJobRef stays set and busy, and the Cancel button is live.
    const calls: Array<{ method: string; params?: unknown }> = [];
    const rpc = vi.fn(async (method: string, params?: unknown) => {
      calls.push({ method, params });
      if (method === 'shortmaker.select') return { jobId: 'sel-1' };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      // Never fire job.done -> the wait hangs, keeping the job active.
      onJobDone: () => () => undefined,
    });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    const cancel = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    expect(cancel).toBeTruthy();
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    expect(calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'sel-1' });
  });

  it('Cancel surfaces a job.cancel rejection', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') return { jobId: 'sel-1' };
      if (method === 'job.cancel') throw new Error('cancel failed');
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({ rpc, onJobDone: () => () => undefined });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Cancel',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('cancel failed');
  });

  it('pickLogo is a no-op when the picker returns no path (user cancelled)', async () => {
    const rpc = rpcFake({ 'settings.get': {} });
    const pickLogoFile = vi.fn().mockResolvedValue(null);
    render(<ShortMaker videoId="v1" api={makeApi({ rpc, pickLogoFile })} />);
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());
    await act(async () => {
      (byLabel('Pick logo file') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(pickLogoFile).toHaveBeenCalled();
    // No settings.set for the logo path (cancelled -> nothing persisted).
    expect(
      rpc.mock.calls.find(
        (c) =>
          c[0] === 'settings.set' &&
          (c[1] as { brandLogoPath?: string }).brandLogoPath !== undefined &&
          (c[1] as { brandLogoPath?: string }).brandLogoPath !== '',
      ),
    ).toBeUndefined();
  });

  it('skips the per-video effects (audio/cues/playable) when there is no videoId', async () => {
    const rpc = rpcFake({});
    render(<ShortMaker videoId="" api={makeApi({ rpc })} />);
    await flush();
    expect(rpc.mock.calls.find((c) => c[0] === 'tracks.audio.list')).toBeUndefined();
    expect(rpc.mock.calls.find((c) => c[0] === 'captions.cues')).toBeUndefined();
    expect(rpc.mock.calls.find((c) => c[0] === 'media.playable')).toBeUndefined();
    // The feedback.stats + settings.get effects (no videoId dep) still run.
    expect(rpc.mock.calls.find((c) => c[0] === 'feedback.stats')).toBeTruthy();
  });

  it('treats a null deferred select payload as an empty candidate list', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') return { jobId: 'sel-1' };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onJobDone: (fn) => {
        doneCb = fn;
        return () => undefined;
      },
    });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    // job.done with no candidates -> extract returns null -> [] (empty state).
    await act(async () => {
      doneCb!({ jobId: 'sel-1', result: {} });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-empty')).toBeTruthy();
  });

  it('a deferred export job.done with no clips yields an empty exported list', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') return { candidates: THREE };
      if (method === 'shortmaker.export') return { jobId: 'exp-1' };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onJobDone: (fn) => {
        doneCb = fn;
        return () => undefined;
      },
    });
    render(<ShortMaker videoId="v1" api={api} />);
    await submitForm();
    const row = container.querySelector('.sm-candidate[data-id="1@97"]')!;
    act(() => (row.querySelector('[aria-label="Approve"]') as HTMLButtonElement).click());
    await act(async () => {
      (
        [...container.querySelectorAll('button')].find(
          (b) => b.textContent === 'Export approved',
        ) as HTMLButtonElement
      ).click();
      await Promise.resolve();
    });
    await act(async () => {
      doneCb!({ jobId: 'exp-1', result: {} }); // no clips
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-exported')?.textContent).toContain('Exported 0 clip(s)');
  });

  it('a batch whose export job.done carries no clips reports zero exported', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'tracks.audio.list') return { audioTracks: [] };
      if (method === 'shortmaker.select') {
        return { candidates: [cand({ rank: 1, sourceStart: 1, viralityPct: 90 })] };
      }
      if (method === 'shortmaker.export') return { jobId: 'bexp-1' };
      if (method === 'shorts.list') return { shorts: [] };
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onJobDone: (fn) => {
        doneCb = fn;
        return () => undefined;
      },
    });
    render(<ShortMaker videoId="v1" api={api} initialControls={{ count: 1 }} />);
    await act(async () => {
      (byLabel('Make N shorts') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await act(async () => {
      doneCb!({ jobId: 'bexp-1', result: {} }); // no clips
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.sm-exported')?.textContent).toContain('Exported 0 clip(s)');
  });

  it('ignores progress notifications that do not match the active job', async () => {
    let progressCb: ((p: JobProgress) => void) | null = null;
    let resolveSelect: (v: unknown) => void = () => undefined;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'shortmaker.select') {
        return new Promise((res) => {
          resolveSelect = res as (v: unknown) => void;
        });
      }
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onProgress: (fn) => {
        progressCb = fn;
        return () => undefined;
      },
      onJobDone: () => () => undefined,
    });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await act(async () => {
      resolveSelect({ jobId: 'sel-1' }); // sets activeJobRef
      await Promise.resolve();
    });
    // A progress event for a DIFFERENT job is ignored (no bar update).
    await act(async () => {
      progressCb!({ jobId: 'someone-else', pct: 77, message: 'not mine' });
    });
    expect(container.querySelector('.sm-progress')?.textContent ?? '').not.toContain('77%');
  });

  it('surfaces an error when persisting a brand edit fails', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'settings.get') return {};
      if (method === 'settings.set') throw new Error('settings store down');
      if (method === 'feedback.stats') return {};
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    render(<ShortMaker videoId="v1" api={makeApi({ rpc })} />);
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());
    const font = byLabel('Default font family') as HTMLInputElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
      setter.call(font, 'Montserrat');
      font.dispatchEvent(new Event('input', { bubbles: true }));
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('settings store down');
  });

  it('a batch whose deferred select resolves to nothing reports no candidates', async () => {
    let doneCb: ((d: JobDone) => void) | null = null;
    const rpc = vi.fn(async (method: string) => {
      if (method === 'tracks.audio.list') return { audioTracks: [] };
      if (method === 'shortmaker.select') return { jobId: 'bsel-1' }; // deferred
      return {};
    }) as unknown as Api['rpc'] & ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onJobDone: (fn) => {
        doneCb = fn;
        return () => undefined;
      },
    });
    render(<ShortMaker videoId="v1" api={api} initialControls={{ count: 2 }} />);
    await act(async () => {
      (byLabel('Make N shorts') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    // The deferred select finishes with no candidates -> found is null -> [].
    await act(async () => {
      doneCb!({ jobId: 'bsel-1', result: {} });
      await Promise.resolve();
    });
    await flush();
    // F1: a confirmed zero-result is the EMPTY state, not an error alert.
    expect(container.querySelector('.sm-empty')?.textContent).toContain('No candidates');
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('treats an empty data-folder string from the bridge as no folder', async () => {
    const getDataFolder = vi.fn().mockResolvedValue('');
    render(<ShortMaker videoId="v1" api={makeApi({ rpc: rpcFake({}), getDataFolder })} />);
    await flush();
    const toggle = [...container.querySelectorAll('.sm-brand-toggle')][0] as HTMLButtonElement;
    act(() => toggle.click());
    expect(container.querySelector('.sm-data-folder-empty')).toBeTruthy();
  });

  it('renders progress with a missing message field (?? "" fallback)', async () => {
    let progressCb: ((p: JobProgress) => void) | null = null;
    const rpc = vi.fn(async () => new Promise(() => {})) as unknown as Api['rpc'] &
      ReturnType<typeof vi.fn>;
    const api = makeApi({
      rpc,
      onProgress: (fn) => {
        progressCb = fn;
        return () => undefined;
      },
    });
    render(<ShortMaker videoId="v1" api={api} />);
    const form = container.querySelector('form')!;
    await act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await act(async () => {
      // Omit `message` entirely so the `progress.message ?? ''` fallback runs.
      progressCb!({ jobId: '', pct: 30 } as unknown as JobProgress);
    });
    expect(container.querySelector('.sm-progress')?.textContent).toContain('30%');
  });
});
