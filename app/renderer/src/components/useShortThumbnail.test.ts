// useShortThumbnail.test.ts — the pure poster-URL helper (P4 §6).
//
// The hook itself is exercised end-to-end by Shorts.test.tsx (generate-on-mount,
// serve-existing, error-fallback). Here we pin the pure `thumbnailSrc` mapping:
// a poster path becomes a `short:` mstream URL; an empty path stays "".
import { describe, it, expect } from 'vitest';
import { thumbnailSrc } from './useShortThumbnail';

describe('thumbnailSrc', () => {
  it('routes a poster path through the short: mstream resolver', () => {
    const url = thumbnailSrc('/exports/shorts-v1/a.thumb.jpg');
    expect(url).toContain('mstream://media/');
    expect(url).toContain('short%3A'); // encoded "short:"
    expect(url).toContain('a.thumb.jpg');
  });

  it('returns "" for an empty path (caller shows the glyph fallback)', () => {
    expect(thumbnailSrc('')).toBe('');
  });
});
