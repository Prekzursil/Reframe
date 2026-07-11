import { describe, expect, it } from 'vitest';
import {
  CAPTION_FAMILY_LABEL,
  CAPTION_FAMILY_ORDER,
  CAPTION_STYLE_LOOKS,
  DEFAULT_STYLE_LOOK,
  type LookStyleOption,
  groupByFamily,
  lookNamedCatalog,
  styleLook,
} from './captionStyleNames';
import { ALL_CAPTION_STYLES } from '../features/shortMakerLogic';

describe('styleLook', () => {
  it('returns the look identity for a known style', () => {
    expect(styleLook('opusclip-karaoke')).toEqual({
      name: 'Word-by-word pop',
      family: 'word-by-word',
      blurb: 'Each word pops as it is spoken',
    });
  });

  it('falls back for an unknown style id', () => {
    expect(styleLook('totally-unknown')).toBe(DEFAULT_STYLE_LOOK);
  });
});

describe('look-name discipline', () => {
  it('gives every selectable catalog id an explicit look entry (no missing names)', () => {
    for (const option of ALL_CAPTION_STYLES) {
      expect(CAPTION_STYLE_LOOKS[option.id], `missing look for ${option.id}`).toBeDefined();
    }
  });

  it('never surfaces a font/codec/model/brand name in any look name', () => {
    const banned =
      /libass|remotion|hormozi|mrbeast|tiktok|opusclip|montserrat|anton|bangers|georgia|inter/i;
    for (const look of Object.values(CAPTION_STYLE_LOOKS)) {
      expect(banned.test(look.name), `jargon leaked in "${look.name}"`).toBe(false);
      expect(banned.test(look.blurb), `jargon leaked in "${look.blurb}"`).toBe(false);
    }
    expect(banned.test(DEFAULT_STYLE_LOOK.name)).toBe(false);
  });

  it('maps every family used to a heading in the display order', () => {
    for (const look of Object.values(CAPTION_STYLE_LOOKS)) {
      expect(CAPTION_FAMILY_ORDER).toContain(look.family);
      expect(CAPTION_FAMILY_LABEL[look.family]).toBeTruthy();
    }
  });
});

describe('lookNamedCatalog', () => {
  it('re-labels the full catalog by look, preserving id + engine', () => {
    const catalog = lookNamedCatalog();
    expect(catalog).toHaveLength(ALL_CAPTION_STYLES.length);
    const karaoke = catalog.find((o) => o.id === 'opusclip-karaoke');
    expect(karaoke).toMatchObject({
      id: 'opusclip-karaoke',
      label: 'Word-by-word pop',
      family: 'word-by-word',
      engine: 'libass',
    });
  });

  it('re-labels a supplied base catalog', () => {
    const catalog = lookNamedCatalog([
      { id: 'serif', engine: 'remotion', label: 'Serif (editorial)' },
    ]);
    expect(catalog).toEqual([
      {
        id: 'serif',
        label: 'Editorial serif',
        family: 'editorial',
        blurb: 'A quiet pull-quote voice',
        engine: 'remotion',
      },
    ]);
  });
});

describe('groupByFamily', () => {
  it('produces ordered, non-empty family sections', () => {
    const groups = groupByFamily(lookNamedCatalog());
    // headline behaviours first
    expect(groups[0].family).toBe('word-by-word');
    expect(groups.map((g) => g.family)).toEqual(
      CAPTION_FAMILY_ORDER.filter((f) => groups.some((g) => g.family === f)),
    );
    for (const group of groups) {
      expect(group.options.length).toBeGreaterThan(0);
      expect(group.label).toBe(CAPTION_FAMILY_LABEL[group.family]);
    }
  });

  it('omits families with no options', () => {
    const onlyEditorial: LookStyleOption[] = [
      {
        id: 'serif',
        label: 'Editorial serif',
        family: 'editorial',
        blurb: 'x',
        engine: 'remotion',
      },
    ];
    const groups = groupByFamily(onlyEditorial);
    expect(groups).toHaveLength(1);
    expect(groups[0].family).toBe('editorial');
  });
});
