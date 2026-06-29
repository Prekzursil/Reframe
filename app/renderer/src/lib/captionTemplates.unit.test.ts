// captionTemplates.unit.test.ts — unit tests for the pure overlay helpers in
// captionTemplates.ts (P4 §4 / §5 / C3). The conformance test
// (captionTemplates.conformance.test.ts) asserts the three-way mirror against
// the real source files; THIS file exercises the runtime lookup functions
// (`captionVisualFor`, `isNoCaption`) and the remaining branches of
// `defaultEmphasisForStyle` (the nullish-coalescing default) so the module is
// 100% line + branch covered.

import { describe, it, expect } from 'vitest';

import {
  CAPTION_TEMPLATE_VISUALS,
  KARAOKE_PRESET_VISUAL,
  REMOTION_CAPTION_TEMPLATES,
  captionVisualFor,
  isNoCaption,
  defaultEmphasisForStyle,
} from './captionTemplates';
import {
  KARAOKE_ACTIVE_HEX,
  KARAOKE_FILL_HEX,
  KARAOKE_OUTLINE_HEX,
  OPUSCLIP_KARAOKE_STYLE,
} from './captionKaraokePreset';

describe('captionVisualFor', () => {
  it('returns the exact visual for a known remotion template id', () => {
    const visual = captionVisualFor('bold');
    // Same object identity as the source registry entry (not a copy).
    expect(visual).toBe(REMOTION_CAPTION_TEMPLATES.bold);
    expect(visual.id).toBe('bold');
    expect(visual.engine).toBe('remotion');
  });

  it('returns the libass visual for the libass id', () => {
    const visual = captionVisualFor('libass');
    expect(visual).toBe(CAPTION_TEMPLATE_VISUALS.libass);
    expect(visual.id).toBe('libass');
    expect(visual.engine).toBe('libass');
  });

  it('returns the none (no-op) visual for the none id', () => {
    const visual = captionVisualFor('none');
    expect(visual.id).toBe('none');
    // none renders nothing — transparent text colour.
    expect(visual.textColor).toBe('transparent');
  });

  it('falls back to the libass default look for an unknown id (never throws)', () => {
    const visual = captionVisualFor('does-not-exist');
    // The fallback is the libass DEFAULT visual (same shape as the libass entry).
    expect(visual.id).toBe('libass');
    expect(visual.engine).toBe('libass');
    expect(visual).toEqual(CAPTION_TEMPLATE_VISUALS.libass);
  });

  it('falls back for the empty-string id too', () => {
    const visual = captionVisualFor('');
    expect(visual.id).toBe('libass');
  });

  it('returns the karaoke preset visual for the opusclip-karaoke id (V1.1 WU SP1)', () => {
    // The libass-only preset is NOT in CAPTION_TEMPLATE_VISUALS (conformance-pinned)
    // but captionVisualFor resolves it to KARAOKE_PRESET_VISUAL so the look renders live.
    const visual = captionVisualFor(OPUSCLIP_KARAOKE_STYLE);
    expect(visual).toBe(KARAOKE_PRESET_VISUAL);
    expect(visual.id).toBe(OPUSCLIP_KARAOKE_STYLE);
    expect(visual.engine).toBe('libass');
    // Built from the shared sidecar-mirrored constants (no silent drift).
    expect(visual.textColor).toBe(KARAOKE_FILL_HEX);
    expect(visual.activeColor).toBe(KARAOKE_ACTIVE_HEX[0]);
    expect(visual.shadowColor).toBe(KARAOKE_OUTLINE_HEX);
    expect(visual.uppercase).toBe(true);
    expect(visual.outline).toBe(true);
    // Resolves case/space-insensitively (mirrors isKaraokeStyle).
    expect(captionVisualFor(' OPUSCLIP-KARAOKE ')).toBe(KARAOKE_PRESET_VISUAL);
  });
});

describe('isNoCaption', () => {
  it('is true only for the exact "none" id', () => {
    expect(isNoCaption('none')).toBe(true);
  });

  it('is false for any other id (remotion, libass, empty, unknown)', () => {
    expect(isNoCaption('bold')).toBe(false);
    expect(isNoCaption('libass')).toBe(false);
    expect(isNoCaption('')).toBe(false);
    expect(isNoCaption('None')).toBe(false); // case-sensitive by contract
    expect(isNoCaption('nonexistent')).toBe(false);
  });
});

describe('defaultEmphasisForStyle nullish/whitespace branches', () => {
  it('treats null as the empty (clean) style — emphasis OFF', () => {
    // Exercises the `style ?? ''` nullish-coalescing branch (line 343).
    expect(defaultEmphasisForStyle(null as unknown as string)).toBe(false);
  });

  it('treats undefined as the empty (clean) style — emphasis OFF', () => {
    expect(defaultEmphasisForStyle(undefined as unknown as string)).toBe(false);
  });

  it('trims + lowercases before matching the clean set', () => {
    expect(defaultEmphasisForStyle('  Subtitle  ')).toBe(false);
    expect(defaultEmphasisForStyle('NONE')).toBe(false);
  });

  it('is ON for a non-clean OpusClip template id', () => {
    expect(defaultEmphasisForStyle('neon')).toBe(true);
  });
});
