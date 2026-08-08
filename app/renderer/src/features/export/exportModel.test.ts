import { describe, expect, it } from 'vitest';
import type { EditorState } from '../../lib/editorState';
import { DEFAULT_CAPTION_DESIGN } from '../../lib/captionDesign';
import type { Cue } from '../../lib/rpc';
import {
  ASPECT_DIMENSIONS,
  PLATFORM_PRESETS,
  type PlatformPreset,
  aspectFanoutPlan,
  buildFanoutPreflight,
  buildPreflight,
  captionSummary,
  estimateRenderSec,
  exportConvertOptions,
  fanoutDestinationLabel,
  fanoutOutPath,
  firstAvailablePresetId,
  framingSummary,
  presetAvailability,
  presetById,
  presetsByIds,
  rovingIndex,
  sanitizeSelection,
  togglePresetId,
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
  it('reports one word (singular)', () => {
    expect(captionSummary(stateWith({ cues: [cue(1)] }))).toBe('1 word');
  });
  it('reports many words (plural)', () => {
    expect(captionSummary(stateWith({ cues: [cue(1), cue(2)] }))).toBe('2 words');
  });
  it('labels WORD-level cues as words, not captions', () => {
    // `captions.cues` returns ONE cue PER WORD (lib/rpc/client.ts:298-299;
    // sidecar cues.py:59-94 `word_cues`). These six word cues are ONE rendered
    // caption line — proved by sidecar/tests/test_caption_karaoke_flatten.py:14-24.
    const cues = ['hello', 'there', 'how', 'are', 'you', 'today'].map((text, i) => ({
      index: i + 1,
      start: i,
      end: i + 0.5,
      text,
    }));
    expect(captionSummary(stateWith({ cues }))).toBe('6 words');
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

// --------------------------------------------------------------------------- //
// v1.5 aspect-matrix: multi-select + the ONE-source -> N-aspect fan-out plan
// --------------------------------------------------------------------------- //
describe('ASPECT_DIMENSIONS (renderer mirror of the sidecar aspect registry)', () => {
  it('carries every curated aspect INCLUDING the widescreen 16:9', () => {
    expect(ASPECT_DIMENSIONS).toEqual({
      '9:16': [1080, 1920],
      '1:1': [1080, 1080],
      '4:5': [1080, 1350],
      '16:9': [1920, 1080],
    });
  });

  it('covers every aspect the destination catalog can offer (no unmapped badge)', () => {
    for (const preset of PLATFORM_PRESETS) {
      expect(ASPECT_DIMENSIONS[preset.aspect]).toBeDefined();
    }
  });
});

describe('togglePresetId', () => {
  it('adds an unselected id, preserving order', () => {
    expect(togglePresetId(['tiktok'], 'square')).toEqual(['tiktok', 'square']);
  });

  it('removes an already-selected id', () => {
    expect(togglePresetId(['tiktok', 'square'], 'tiktok')).toEqual(['square']);
  });

  it('refuses to empty the selection (export always needs a destination)', () => {
    expect(togglePresetId(['tiktok'], 'tiktok')).toEqual(['tiktok']);
  });
});

describe('presetsByIds', () => {
  it('resolves ids to presets in CATALOG order, not click order', () => {
    // Clicking widescreen then tiktok must still read top-to-bottom in the UI.
    expect(presetsByIds(['widescreen', 'tiktok']).map((p) => p.id)).toEqual([
      'tiktok',
      'widescreen',
    ]);
  });

  it('drops ids that are not in the catalog', () => {
    expect(presetsByIds(['tiktok', '__nope__']).map((p) => p.id)).toEqual(['tiktok']);
  });
});

describe('sanitizeSelection', () => {
  it('keeps a selection whose destinations all still fit the clip', () => {
    expect(sanitizeSelection(['tiktok', 'square'], 30)).toEqual(['tiktok', 'square']);
  });

  it('drops destinations the clip has outgrown', () => {
    // 120s blocks shorts (60s cap) but not the uncapped square.
    expect(sanitizeSelection(['shorts', 'square'], 120)).toEqual(['square']);
  });

  it('falls back to the first AVAILABLE destination when everything is dropped', () => {
    expect(sanitizeSelection(['shorts'], 120)).toEqual([firstAvailablePresetId(120)]);
  });
});

describe('aspectFanoutPlan', () => {
  it('pairs each distinct aspect with its canonical canvas', () => {
    expect(aspectFanoutPlan(presetsByIds(['tiktok', 'square', 'widescreen']))).toEqual([
      { aspect: '9:16', width: 1080, height: 1920 },
      { aspect: '1:1', width: 1080, height: 1080 },
      { aspect: '16:9', width: 1920, height: 1080 },
    ]);
  });

  it('DEDUPES by aspect — three vertical destinations are ONE render target', () => {
    // Mirrors the sidecar's aspect.fanout_plan dedupe: TikTok + Reels + Shorts
    // are three destinations but a single 9:16 file.
    expect(aspectFanoutPlan(presetsByIds(['tiktok', 'reels', 'shorts']))).toEqual([
      { aspect: '9:16', width: 1080, height: 1920 },
    ]);
  });

  it('is empty for an empty destination list', () => {
    expect(aspectFanoutPlan([])).toEqual([]);
  });

  it('skips a destination whose aspect has no canonical canvas', () => {
    const rogue: PlatformPreset = {
      id: 'rogue',
      name: 'Rogue',
      blurb: '',
      aspect: '21:9',
      maxSec: null,
      lengthHint: '',
    };
    expect(aspectFanoutPlan([rogue])).toEqual([]);
  });
});

describe('fanoutDestinationLabel', () => {
  it('names a single destination outright', () => {
    expect(fanoutDestinationLabel(presetsByIds(['tiktok']))).toBe('TikTok');
  });

  it('names the first and counts the rest', () => {
    expect(fanoutDestinationLabel(presetsByIds(['tiktok', 'square']))).toBe('TikTok + 1 more');
    expect(fanoutDestinationLabel(presetsByIds(['tiktok', 'square', 'widescreen']))).toBe(
      'TikTok + 2 more',
    );
  });

  it('degrades to a neutral word when nothing is selected', () => {
    expect(fanoutDestinationLabel([])).toBe('your destinations');
  });
});

describe('fanoutOutPath', () => {
  const target = { aspect: '9:16', width: 1080, height: 1920 };

  it('writes NEXT TO the source, tagged with the aspect', () => {
    expect(fanoutOutPath('/videos/talk.mov', target)).toBe('/videos/talk.9x16.mp4');
  });

  it('uses an "x" separator so the name is legal on Windows', () => {
    // ':' is a reserved character in a Windows filename — a raw "9:16" would make
    // the path unopenable (and would read as an alternate data stream).
    expect(fanoutOutPath('C:\\clips\\talk.mp4', target)).toBe('C:\\clips\\talk.9x16.mp4');
    expect(fanoutOutPath('C:\\clips\\talk.mp4', target)).not.toContain(':16');
  });

  it('keeps a dotted directory out of the stem calculation', () => {
    expect(fanoutOutPath('/a.b/talk', target)).toBe('/a.b/talk.9x16.mp4');
  });

  it('honours a non-default container extension', () => {
    expect(fanoutOutPath('/videos/talk.mov', target, 'mkv')).toBe('/videos/talk.9x16.mkv');
  });
});

describe('buildFanoutPreflight', () => {
  it('reports ONE clip per distinct aspect and lists them', () => {
    const pre = buildFanoutPreflight(stateWith(), presetsByIds(['tiktok', 'square']));
    expect(pre.clipCount).toBe(2);
    expect(pre.aspectLabel).toBe('9:16 · 1:1');
    expect(pre.targets).toHaveLength(2);
  });

  it('collapses same-aspect destinations to a single clip', () => {
    const pre = buildFanoutPreflight(stateWith(), presetsByIds(['tiktok', 'reels']));
    expect(pre.clipCount).toBe(1);
    expect(pre.aspectLabel).toBe('9:16');
  });

  it('scales the render estimate by the number of files', () => {
    const one = buildFanoutPreflight(stateWith(), presetsByIds(['tiktok']));
    const two = buildFanoutPreflight(stateWith(), presetsByIds(['tiktok', 'square']));
    expect(one.estRenderLabel).toBe('~0:15');
    expect(two.estRenderLabel).toBe('~0:30');
  });

  it('still costs nothing — the render is LOCAL', () => {
    expect(buildFanoutPreflight(stateWith(), presetsByIds(['tiktok'])).estSpendLabel).toBe('$0.00');
  });

  it('carries the clip duration through unchanged', () => {
    const pre = buildFanoutPreflight(stateWith(), presetsByIds(['tiktok']));
    expect(pre.durationSec).toBe(30);
    expect(pre.durationLabel).toBe('0:30');
  });

  it('reports an empty plan honestly rather than pretending one file', () => {
    const pre = buildFanoutPreflight(stateWith(), []);
    expect(pre.clipCount).toBe(0);
    expect(pre.aspectLabel).toBe('');
  });
});
