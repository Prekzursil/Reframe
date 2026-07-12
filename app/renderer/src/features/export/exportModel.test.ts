import { describe, expect, it } from 'vitest';
import type { EditorState } from '../../lib/editorState';
import { DEFAULT_CAPTION_DESIGN } from '../../lib/captionDesign';
import type { Cue } from '../../lib/rpc';
import {
  PLATFORM_PRESETS,
  type PlatformPreset,
  buildPreflight,
  captionSummary,
  estimateRenderSec,
  exportConvertOptions,
  firstAvailablePresetId,
  framingSummary,
  presetAvailability,
  presetById,
  rovingIndex,
  windowDurationSec,
} from './exportModel';

function stateWith(overrides: Partial<EditorState> = {}): EditorState {
  return {
    video: { videoId: 'v1', window: { start: 0, end: 30 }, durationSec: 30 },
    cues: [],
    cropPlan: null,
    design: DEFAULT_CAPTION_DESIGN,
    playhead: 0,
    selection: null,
    ...overrides,
  };
}

const cue = (index: number): Cue => ({ index, start: index, end: index + 1, text: `w${index}` });

describe('PLATFORM_PRESETS catalog', () => {
  it('spans the four target aspects with recognizable destinations only', () => {
    const aspects = new Set(PLATFORM_PRESETS.map((p) => p.aspect));
    expect(aspects).toEqual(new Set(['9:16', '4:5', '1:1', '16:9']));
    // No codec/bitrate jargon leaks into any user-visible field.
    for (const preset of PLATFORM_PRESETS) {
      expect(`${preset.name} ${preset.blurb} ${preset.lengthHint}`).not.toMatch(
        /codec|bitrate|h\.?264|crf|kbps|mp4/i,
      );
    }
    // At least one destination is uncapped (guarantees an always-available pick).
    expect(PLATFORM_PRESETS.some((p) => p.maxSec === null)).toBe(true);
  });
});

describe('presetById', () => {
  it('resolves a known id', () => {
    expect(presetById('shorts').name).toBe('YouTube Shorts');
  });
  it('falls back to the first preset for an unknown id', () => {
    expect(presetById('nope')).toBe(PLATFORM_PRESETS[0]);
  });
});

describe('presetAvailability', () => {
  it('is available when the clip fits the cap', () => {
    const shorts = presetById('shorts'); // maxSec 60
    expect(presetAvailability(shorts, 45)).toEqual({ status: 'available', reason: '' });
  });
  it('is available exactly at the cap (boundary)', () => {
    expect(presetAvailability(presetById('shorts'), 60).status).toBe('available');
  });
  it('is available for an uncapped destination regardless of length', () => {
    expect(presetAvailability(presetById('widescreen'), 99999).status).toBe('available');
  });
  it('is unavailable — with a plain reason — when the clip exceeds the cap', () => {
    const result = presetAvailability(presetById('shorts'), 75);
    expect(result.status).toBe('unavailable');
    expect(result.reason).toBe(
      'This clip runs longer than the 1:00 limit for YouTube Shorts — trim it first.',
    );
  });
});

describe('firstAvailablePresetId', () => {
  it('returns the first destination that fits the clip', () => {
    // 80s clip: tiktok (600) fits first.
    expect(firstAvailablePresetId(80)).toBe('tiktok');
  });
  it('falls back to the first entry when none fit (synthetic all-capped catalog)', () => {
    const capped: PlatformPreset[] = [
      { id: 'a', name: 'A', blurb: '', aspect: '9:16', maxSec: 10, lengthHint: '' },
      { id: 'b', name: 'B', blurb: '', aspect: '1:1', maxSec: 20, lengthHint: '' },
    ];
    expect(firstAvailablePresetId(999, capped)).toBe('a');
  });
});

describe('estimateRenderSec', () => {
  it('floors a tiny clip at the minimum', () => {
    expect(estimateRenderSec(2)).toBe(3);
  });
  it('scales with duration for a longer clip', () => {
    expect(estimateRenderSec(40)).toBe(20);
  });
});

describe('windowDurationSec', () => {
  it('measures a normal window', () => {
    expect(windowDurationSec(stateWith({ video: { window: { start: 5, end: 20 } } }))).toBe(15);
  });
  it('clamps a reversed window to zero', () => {
    expect(windowDurationSec(stateWith({ video: { window: { start: 20, end: 5 } } }))).toBe(0);
  });
  it('treats a non-finite window as zero', () => {
    expect(windowDurationSec(stateWith({ video: { window: { start: 0, end: Number.NaN } } }))).toBe(
      0,
    );
  });
});

describe('buildPreflight', () => {
  it('summarizes one local clip at the destination aspect', () => {
    const pre = buildPreflight(
      stateWith({ video: { window: { start: 5, end: 65 } } }),
      presetById('shorts'),
    );
    expect(pre).toEqual({
      clipCount: 1,
      aspect: '9:16',
      durationSec: 60,
      durationLabel: '1:00',
      estRenderLabel: '~0:30',
      estSpendLabel: '$0.00',
    });
  });
  it('clamps a reversed window to zero', () => {
    const pre = buildPreflight(
      stateWith({ video: { window: { start: 10, end: 4 } } }),
      presetById('feed'),
    );
    expect(pre.durationSec).toBe(0);
    expect(pre.durationLabel).toBe('0:00');
  });
  it('treats a non-finite window as zero', () => {
    const pre = buildPreflight(
      stateWith({ video: { window: { start: 0, end: Number.NaN } } }),
      presetById('feed'),
    );
    expect(pre.durationSec).toBe(0);
  });
});

describe('captionSummary', () => {
  it('reports no captions', () => {
    expect(captionSummary(stateWith({ cues: [] }))).toBe('No captions');
  });
  it('reports one caption (singular)', () => {
    expect(captionSummary(stateWith({ cues: [cue(1)] }))).toBe('1 caption');
  });
  it('reports many captions (plural)', () => {
    expect(captionSummary(stateWith({ cues: [cue(1), cue(2)] }))).toBe('2 captions');
  });
});

describe('framingSummary', () => {
  it('reads Original framing with no crop plan', () => {
    expect(framingSummary(stateWith({ cropPlan: null }))).toBe('Original framing');
  });
  it('reads Reframed when a crop plan is present — never leaking the engine id', () => {
    expect(framingSummary(stateWith({ cropPlan: { engine: 'verthor' } }))).toBe('Reframed');
  });
});

describe('exportConvertOptions', () => {
  it('is a universal share-ready mp4 profile', () => {
    expect(exportConvertOptions()).toEqual({
      container: 'mp4',
      vcodec: 'libx264',
      acodec: 'aac',
      scale: '',
      fps: '',
      crf: '20',
      audioOnly: false,
      audioFormat: 'mp3',
    });
  });
});

describe('rovingIndex', () => {
  const all = [true, true, true];
  it('moves next on ArrowRight / ArrowDown (wrapping)', () => {
    expect(rovingIndex('ArrowRight', 0, all)).toBe(1);
    expect(rovingIndex('ArrowDown', 0, all)).toBe(1);
    expect(rovingIndex('ArrowRight', 2, all)).toBe(0);
  });
  it('moves previous on ArrowLeft / ArrowUp (wrapping)', () => {
    expect(rovingIndex('ArrowLeft', 0, all)).toBe(2);
    expect(rovingIndex('ArrowUp', 1, all)).toBe(0);
  });
  it('jumps to first/last selectable on Home/End', () => {
    expect(rovingIndex('Home', 2, all)).toBe(0);
    expect(rovingIndex('End', 0, all)).toBe(2);
  });
  it('skips unavailable destinations when moving', () => {
    const gap = [true, false, true];
    expect(rovingIndex('ArrowRight', 0, gap)).toBe(2);
    expect(rovingIndex('ArrowLeft', 0, gap)).toBe(2);
    expect(rovingIndex('Home', 1, [false, true, true])).toBe(1);
    expect(rovingIndex('End', 1, [true, true, false])).toBe(1);
  });
  it('stays put when nothing is selectable', () => {
    expect(rovingIndex('ArrowRight', 1, [false, false])).toBe(1);
  });
  it('stays put for an empty group', () => {
    expect(rovingIndex('ArrowRight', 0, [])).toBe(0);
  });
  it('ignores other keys', () => {
    expect(rovingIndex('Tab', 1, all)).toBe(1);
  });
});
