// Conformance test for the P4 caption-template three-way mirror (§4 / C3).
//
// Asserts the SUPERSET relation across the five places the style list lives:
//   keys(vendor TEMPLATES) == sidecar STYLES == remotion-template keys here
//   AND renderer remotion-engine subset (ShortMaker CAPTION_STYLES) == TEMPLATES
//   AND renderer full picker list == keys(TEMPLATES) ∪ {libass, none}
//
// It reads the REAL source files (not a copy) so adding a style without
// updating all mirrors fails the build (a known bug class — P4 §1). Runs in the
// default node environment (filesystem access, no jsdom). Tests run with cwd =
// app/, so repo paths are resolved relative to this file via import.meta.url.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  REMOTION_CAPTION_TEMPLATES,
  REMOTION_TEMPLATE_IDS,
  CAPTION_TEMPLATE_VISUALS,
  CLEAN_CAPTION_STYLES,
  defaultEmphasisForStyle,
} from './captionTemplates';
import { CAPTION_STYLES } from '../features/ShortMaker';

// app/renderer/src/lib -> repo root is four levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..');

const VENDOR_TEMPLATES = resolve(
  REPO_ROOT,
  'vendor',
  'remotion-captions',
  'src',
  'templates.ts',
);
const SIDECAR_CAPTION_REMOTION = resolve(
  REPO_ROOT,
  'sidecar',
  'media_studio',
  'features',
  'caption_remotion.py',
);
const SIDECAR_EMPHASIS = resolve(
  REPO_ROOT,
  'sidecar',
  'media_studio',
  'features',
  'emphasis.py',
);

/** Parse the `CAPTION_STYLES = [ ... ] as const` tuple ids from templates.ts. */
function vendorTemplateKeys(): string[] {
  const src = readFileSync(VENDOR_TEMPLATES, 'utf8');
  const m = src.match(/export const CAPTION_STYLES = \[([\s\S]*?)\] as const;/);
  if (!m) throw new Error('could not find CAPTION_STYLES tuple in templates.ts');
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
}

/** Parse the `STYLES: List[str] = [ ... ]` ids from caption_remotion.py. */
function sidecarStyleIds(): string[] {
  const src = readFileSync(SIDECAR_CAPTION_REMOTION, 'utf8');
  const m = src.match(/STYLES: List\[str\] = \[([\s\S]*?)\]/);
  if (!m) throw new Error('could not find STYLES list in caption_remotion.py');
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
}

/** Parse the `CLEAN_STYLES ... frozenset({ ... })` ids from emphasis.py. */
function sidecarCleanStyles(): string[] {
  const src = readFileSync(SIDECAR_EMPHASIS, 'utf8');
  const m = src.match(/CLEAN_STYLES[^=]*=\s*frozenset\(\{([\s\S]*?)\}\)/);
  if (!m) throw new Error('could not find CLEAN_STYLES frozenset in emphasis.py');
  return [...m[1].matchAll(/"([^"]*)"/g)].map((x) => x[1]);
}

const asSet = (xs: readonly string[]): Set<string> => new Set(xs);

describe('caption template three-way mirror conformance (P4 §4 / C3)', () => {
  const vendorKeys = vendorTemplateKeys();
  const sidecarIds = sidecarStyleIds();
  const rendererRemotionIds = REMOTION_TEMPLATE_IDS;

  it('vendor TEMPLATES tuple has >= 12 templates incl. the originals', () => {
    expect(vendorKeys.length).toBeGreaterThanOrEqual(12);
    for (const id of ['bold', 'bounce', 'clean', 'karaoke']) {
      expect(vendorKeys).toContain(id);
    }
    // The OpusClip additions all present.
    for (const id of [
      'hormozi', 'neon', 'tiktok', 'gradient', 'impact',
      'mrbeast', 'pop', 'serif', 'subtitle', 'fire',
    ]) {
      expect(vendorKeys).toContain(id);
    }
  });

  it('keys(TEMPLATES) == sidecar STYLES == renderer remotion keys (as sets)', () => {
    expect(asSet(sidecarIds)).toEqual(asSet(vendorKeys));
    expect(asSet(rendererRemotionIds)).toEqual(asSet(vendorKeys));
    // No id duplicates in any mirror.
    expect(new Set(vendorKeys).size).toBe(vendorKeys.length);
    expect(new Set(sidecarIds).size).toBe(sidecarIds.length);
    expect(new Set(rendererRemotionIds).size).toBe(rendererRemotionIds.length);
  });

  it('renderer remotion-engine picker subset == keys(TEMPLATES)', () => {
    const pickerRemotion = CAPTION_STYLES.filter((s) => s.engine === 'remotion').map(
      (s) => s.id,
    );
    expect(asSet(pickerRemotion)).toEqual(asSet(vendorKeys));
  });

  it('renderer full picker list == keys(TEMPLATES) ∪ {libass, none} (C3 superset)', () => {
    const pickerIds = CAPTION_STYLES.map((s) => s.id);
    const expected = new Set<string>([...vendorKeys, 'libass', 'none']);
    expect(asSet(pickerIds)).toEqual(expected);
    // libass is the picker default and a libass-engine style.
    const libass = CAPTION_STYLES.find((s) => s.id === 'libass');
    expect(libass?.engine).toBe('libass');
  });

  it('overlay visual map covers TEMPLATES ∪ {libass, none} (C3 — overlay needs them)', () => {
    const visualIds = Object.keys(CAPTION_TEMPLATE_VISUALS);
    const expected = new Set<string>([...vendorKeys, 'libass', 'none']);
    expect(asSet(visualIds)).toEqual(expected);
    // Every remotion visual id is also a vendor template key.
    for (const id of Object.keys(REMOTION_CAPTION_TEMPLATES)) {
      expect(vendorKeys).toContain(id);
    }
    // none is a no-op look (transparent text); libass is a real fallback look.
    expect(CAPTION_TEMPLATE_VISUALS.none.textColor).toBe('transparent');
    expect(CAPTION_TEMPLATE_VISUALS.libass.textColor).not.toBe('transparent');
  });
});

describe('emphasis per-style default mirror (P4 §8a — renderer ↔ sidecar)', () => {
  const vendorKeys = vendorTemplateKeys();

  it('renderer CLEAN_CAPTION_STYLES equals the sidecar CLEAN_STYLES (no drift)', () => {
    const rendererClean = [...CLEAN_CAPTION_STYLES];
    const sidecarClean = sidecarCleanStyles();
    expect(asSet(rendererClean)).toEqual(asSet(sidecarClean));
  });

  it('defaultEmphasisForStyle is OFF for clean/minimal looks, ON for OpusClip templates', () => {
    // OFF for every "clean" id (clean/subtitle/none/libass/empty), matched
    // case-insensitively + trimmed (mirrors default_emphasis_for_style).
    for (const id of CLEAN_CAPTION_STYLES) {
      expect(defaultEmphasisForStyle(id)).toBe(false);
    }
    expect(defaultEmphasisForStyle(' CLEAN ')).toBe(false);
    expect(defaultEmphasisForStyle('')).toBe(false);
    // ON for every remotion template that is NOT in the clean set.
    for (const id of vendorKeys) {
      const expected = !CLEAN_CAPTION_STYLES.has(id);
      expect(defaultEmphasisForStyle(id)).toBe(expected);
    }
    // Spot-check a couple of bold OpusClip templates explicitly.
    expect(defaultEmphasisForStyle('bold')).toBe(true);
    expect(defaultEmphasisForStyle('hormozi')).toBe(true);
  });
});
