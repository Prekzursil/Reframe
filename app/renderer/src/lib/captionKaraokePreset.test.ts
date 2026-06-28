// Tests for the renderer mirror of the OpusClip karaoke caption preset (WU SP1).
//
// Pure-logic assertions PLUS a DRIFT GUARD that reads the REAL sidecar source
// (`caption_karaoke.py`) and asserts the shared constants match — so the live
// preview palette/casing/grouping/safe-area can never silently diverge from the
// libass burn (the same defence the three-way template conformance test uses).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  OPUSCLIP_KARAOKE_STYLE,
  KARAOKE_FILL_HEX,
  KARAOKE_OUTLINE_HEX,
  KARAOKE_ACTIVE_HEX,
  KARAOKE_FONT,
  KARAOKE_OUTLINE_WIDTH,
  KARAOKE_POP_SCALE,
  KARAOKE_POP_MS,
  MAX_WORDS_PER_LINE,
  SAFE_AREA_TOP_FRACTION,
  SAFE_AREA_BOTTOM_FRACTION,
  isKaraokeStyle,
  karaokeActiveColor,
  safeAreaMarginV,
} from './captionKaraokePreset';

// app/renderer/src/lib -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');
const SIDECAR_KARAOKE = resolve(
  REPO_ROOT,
  'sidecar',
  'media_studio',
  'features',
  'caption_karaoke.py',
);

describe('captionKaraokePreset constants (WU SP1)', () => {
  it('pins the OpusClip palette, casing, pop, and grouping', () => {
    expect(OPUSCLIP_KARAOKE_STYLE).toBe('opusclip-karaoke');
    expect(KARAOKE_FILL_HEX).toBe('#FFFFFF');
    expect(KARAOKE_OUTLINE_HEX).toBe('#000000');
    expect(KARAOKE_ACTIVE_HEX).toEqual(['#FFFF00', '#00FF00']);
    expect(KARAOKE_FONT).toBe('Anton');
    expect(KARAOKE_OUTLINE_WIDTH).toBe(4);
    expect(KARAOKE_POP_SCALE).toBe(115);
    expect(KARAOKE_POP_MS).toBe(120);
    expect(MAX_WORDS_PER_LINE).toBe(4);
    expect(SAFE_AREA_TOP_FRACTION).toBe(0.1);
    expect(SAFE_AREA_BOTTOM_FRACTION).toBe(0.18);
  });
});

describe('isKaraokeStyle', () => {
  it('is true only for the preset id (case/space-insensitive)', () => {
    for (const s of ['opusclip-karaoke', ' OpusClip-Karaoke ', 'OPUSCLIP-KARAOKE']) {
      expect(isKaraokeStyle(s)).toBe(true);
    }
    for (const s of ['karaoke', 'bold', '', 'libass', null, undefined, 123]) {
      expect(isKaraokeStyle(s)).toBe(false);
    }
  });
});

describe('karaokeActiveColor', () => {
  it('alternates yellow/green by absolute word index', () => {
    expect(karaokeActiveColor(0)).toBe('#FFFF00');
    expect(karaokeActiveColor(1)).toBe('#00FF00');
    expect(karaokeActiveColor(2)).toBe('#FFFF00');
    expect(karaokeActiveColor(3)).toBe('#00FF00');
  });

  it('coerces a non-finite/negative index safely', () => {
    expect(karaokeActiveColor(Number.NaN)).toBe('#FFFF00');
    expect(karaokeActiveColor(-1)).toBe('#00FF00');
    expect(karaokeActiveColor(2.9)).toBe('#FFFF00');
  });
});

describe('safeAreaMarginV (mirrors sidecar safe_area_margin_v)', () => {
  it('clears the bottom ~18% by default (lower-mid for 9:16)', () => {
    expect(safeAreaMarginV(1920, 'bottom')).toBe(346);
    expect(safeAreaMarginV(1920, 'sideways')).toBe(346); // unknown -> bottom
  });
  it('clears the top ~10% for a top band', () => {
    expect(safeAreaMarginV(1920, 'top')).toBe(192);
  });
  it('is centred (0) for a center band', () => {
    expect(safeAreaMarginV(1920, 'center')).toBe(0);
  });
});

describe('drift guard — renderer mirror == sidecar caption_karaoke.py', () => {
  const src = readFileSync(SIDECAR_KARAOKE, 'utf8');

  const num = (name: string): number => {
    const m = src.match(new RegExp(`${name}\\s*=\\s*([0-9.]+)`));
    if (!m) throw new Error(`could not find ${name} in caption_karaoke.py`);
    return Number(m[1]);
  };
  const str = (name: string): string => {
    const m = src.match(new RegExp(`${name}\\s*=\\s*"([^"]+)"`));
    if (!m) throw new Error(`could not find ${name} in caption_karaoke.py`);
    return m[1];
  };

  it('style id, palette, font match the sidecar', () => {
    expect(str('OPUSCLIP_KARAOKE_STYLE')).toBe(OPUSCLIP_KARAOKE_STYLE);
    expect(str('KARAOKE_FILL_HEX')).toBe(KARAOKE_FILL_HEX);
    expect(str('KARAOKE_OUTLINE_HEX')).toBe(KARAOKE_OUTLINE_HEX);
    expect(str('KARAOKE_FONT')).toBe(KARAOKE_FONT);
  });

  it('alternating active hex tuple matches the sidecar', () => {
    const m = src.match(/KARAOKE_ACTIVE_HEX[^=]*=\s*\(([^)]*)\)/);
    if (!m) throw new Error('could not find KARAOKE_ACTIVE_HEX in caption_karaoke.py');
    const hexes = [...m[1].matchAll(/"(#[0-9A-Fa-f]{6})"/g)].map((x) => x[1]);
    expect(hexes).toEqual([...KARAOKE_ACTIVE_HEX]);
  });

  it('numeric knobs (pop, outline, words, safe-area) match the sidecar', () => {
    expect(num('KARAOKE_POP_SCALE')).toBe(KARAOKE_POP_SCALE);
    expect(num('KARAOKE_POP_MS')).toBe(KARAOKE_POP_MS);
    expect(num('KARAOKE_OUTLINE_WIDTH')).toBe(KARAOKE_OUTLINE_WIDTH);
    expect(num('MAX_WORDS_PER_LINE')).toBe(MAX_WORDS_PER_LINE);
    expect(num('SAFE_AREA_TOP_FRACTION')).toBe(SAFE_AREA_TOP_FRACTION);
    expect(num('SAFE_AREA_BOTTOM_FRACTION')).toBe(SAFE_AREA_BOTTOM_FRACTION);
  });
});
