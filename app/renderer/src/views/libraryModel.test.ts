// libraryModel.test.ts — full-branch coverage of the pure Library view-model.
import { describe, it, expect } from 'vitest';

import type { Video } from '../components/api';
import type { ShortInfo } from '../lib/rpc';
import {
  type LibraryVideo,
  LIBRARY_SORT_MODES,
  LIBRARY_SORT_LABELS,
  groupShortsByVideo,
  filterVideos,
  sortVideos,
  formatDuration,
  cardBadges,
  cardAriaLabel,
  formatAdded,
  shortsCountLabel,
  shortsOpenAriaLabel,
} from './libraryModel';

function makeVideo(over: Partial<LibraryVideo> = {}): LibraryVideo {
  return {
    id: 'v1',
    path: '/movies/talk.mp4',
    title: 'Talk',
    addedAt: '2026-06-11T00:00:00Z',
    durationSec: 605,
    hasTranscript: false,
    ...over,
  };
}

function makeShort(over: Partial<ShortInfo> = {}): ShortInfo {
  return {
    id: 's1',
    path: '/out/s1.mp4',
    videoId: 'v1',
    sourceTitle: 'Talk',
    template: '',
    viralityPct: null,
    durationSec: 30,
    width: 1080,
    height: 1920,
    createdAt: 1,
    thumbnailPath: '',
    hook: '',
    ...over,
  };
}

describe('sort model constants', () => {
  it('exposes every sort mode with a label', () => {
    for (const mode of LIBRARY_SORT_MODES) {
      expect(LIBRARY_SORT_LABELS[mode]).toBeTruthy();
    }
    expect(LIBRARY_SORT_MODES[0]).toBe('recent');
  });
});

describe('groupShortsByVideo', () => {
  it('groups shorts under their source video id and skips id-less shorts', () => {
    const grouped = groupShortsByVideo([
      makeShort({ id: 'a', videoId: 'v1' }),
      makeShort({ id: 'b', videoId: 'v2' }),
      makeShort({ id: 'c', videoId: 'v1' }),
      makeShort({ id: 'd', videoId: '' }), // no source — dropped
    ]);
    expect(grouped['v1'].map((s) => s.id)).toEqual(['a', 'c']);
    expect(grouped['v2'].map((s) => s.id)).toEqual(['b']);
    expect(Object.keys(grouped)).toEqual(['v1', 'v2']);
  });

  it('returns an empty map for no shorts', () => {
    expect(groupShortsByVideo([])).toEqual({});
  });
});

describe('filterVideos', () => {
  const list = [
    makeVideo({ id: 'a', title: 'Keynote' }),
    makeVideo({ id: 'b', title: 'Bloopers' }),
  ];

  it('returns a copy of all videos for an empty / whitespace query', () => {
    const out = filterVideos(list, '   ');
    expect(out.map((v) => v.id)).toEqual(['a', 'b']);
    expect(out).not.toBe(list);
  });

  it('matches the title case-insensitively', () => {
    expect(filterVideos(list, 'key').map((v) => v.id)).toEqual(['a']);
  });

  it('returns an empty list when nothing matches', () => {
    expect(filterVideos(list, 'zzz')).toEqual([]);
  });
});

describe('sortVideos', () => {
  const count = (id: string): number => ({ a: 2, b: 5, c: 5 })[id] ?? 0;
  const list = [
    makeVideo({ id: 'a', title: 'Bravo', addedAt: '2026-01-02', durationSec: 100 }),
    makeVideo({ id: 'b', title: 'Alpha', addedAt: '2026-01-03', durationSec: 100 }),
    makeVideo({ id: 'c', title: 'Charlie', addedAt: '2026-01-01', durationSec: 300 }),
  ];

  it('sorts by title A–Z', () => {
    expect(sortVideos(list, 'title', count).map((v) => v.id)).toEqual(['b', 'a', 'c']);
  });

  it('sorts by duration desc, tie → title', () => {
    // c(300) leads; a & b tie at 100 → title (Alpha 'b' before Bravo 'a').
    expect(sortVideos(list, 'duration', count).map((v) => v.id)).toEqual(['c', 'b', 'a']);
  });

  it('sorts by shorts count desc, tie → title', () => {
    // b & c tie at 5 → title (Alpha 'b' before Charlie 'c'); a has 2.
    expect(sortVideos(list, 'shorts', count).map((v) => v.id)).toEqual(['b', 'c', 'a']);
  });

  it('sorts by recency (addedAt desc), preserving input order on a tie (stable)', () => {
    const list = [
      makeVideo({ id: 'a', title: 'Bravo', addedAt: '2026-01-01' }),
      makeVideo({ id: 'b', title: 'Alpha', addedAt: '2026-01-03' }),
      makeVideo({ id: 'x', title: 'Yankee', addedAt: '2026-01-02' }),
      makeVideo({ id: 'y', title: 'Xray', addedAt: '2026-01-02' }),
    ];
    // b(03) leads; the 01-02 tie keeps its INPUT order (x before y); a(01) last.
    expect(sortVideos(list, 'recent', count).map((v) => v.id)).toEqual(['b', 'x', 'y', 'a']);
  });

  it('does not mutate the input array', () => {
    const input = [...list];
    sortVideos(input, 'title', count);
    expect(input.map((v) => v.id)).toEqual(['a', 'b', 'c']);
  });
});

describe('formatDuration', () => {
  it('formats mm:ss under an hour', () => {
    expect(formatDuration(605)).toBe('10:05');
  });
  it('formats h:mm:ss past an hour', () => {
    expect(formatDuration(3725)).toBe('1:02:05');
  });
  it('returns --:-- for zero / negative / non-finite', () => {
    expect(formatDuration(0)).toBe('--:--');
    expect(formatDuration(-5)).toBe('--:--');
    expect(formatDuration(Number.NaN)).toBe('--:--');
  });
});

describe('cardBadges', () => {
  it('is empty for a plain video', () => {
    expect(cardBadges(makeVideo())).toEqual([]);
  });
  it('shows only the Transcript chip when transcribed', () => {
    expect(cardBadges(makeVideo({ hasTranscript: true }))).toEqual([
      { kind: 'transcript', label: 'Transcript' },
    ]);
  });
  it('shows only the Failed badge for a failed video', () => {
    expect(cardBadges(makeVideo({ failed: true }))).toEqual([{ kind: 'failed', label: 'Failed' }]);
  });
  it('leads with Failed then Transcript when both apply', () => {
    expect(cardBadges(makeVideo({ failed: true, hasTranscript: true })).map((b) => b.kind)).toEqual(
      ['failed', 'transcript'],
    );
  });
});

describe('cardAriaLabel', () => {
  it('names open + duration + transcript status', () => {
    expect(cardAriaLabel(makeVideo({ hasTranscript: true }), false)).toBe(
      'Open Talk, 10:05, transcript ready',
    );
  });
  it('names the history verb + no-transcript status in lineage view', () => {
    expect(cardAriaLabel(makeVideo(), true)).toBe('Show history of Talk, 10:05, no transcript');
  });
  it('names the failed status', () => {
    expect(cardAriaLabel(makeVideo({ failed: true }), false)).toBe(
      'Open Talk, 10:05, processing failed',
    );
  });
  it('omits an unknown duration from the name', () => {
    expect(cardAriaLabel(makeVideo({ durationSec: 0 }), false)).toBe('Open Talk, no transcript');
  });
});

describe('shortsCountLabel', () => {
  it('uses the singular noun for exactly one short', () => {
    expect(shortsCountLabel(1)).toBe('1 short');
  });
  it('uses the plural noun for zero or many shorts', () => {
    expect(shortsCountLabel(0)).toBe('0 shorts');
    expect(shortsCountLabel(3)).toBe('3 shorts');
  });
});

describe('shortsOpenAriaLabel', () => {
  it('pluralizes the produced-shorts open name (singular)', () => {
    expect(shortsOpenAriaLabel(1, 'Talk')).toBe('View 1 produced short for Talk');
  });
  it('pluralizes the produced-shorts open name (plural)', () => {
    expect(shortsOpenAriaLabel(3, 'Talk')).toBe('View 3 produced shorts for Talk');
  });
});

describe('formatAdded', () => {
  it('extracts the date part of an ISO timestamp', () => {
    expect(formatAdded('2026-06-11T00:00:00Z')).toBe('2026-06-11');
  });
  it('returns empty string for an unparseable value', () => {
    expect(formatAdded('not-a-date')).toBe('');
  });
});

// A Video (no `failed`) is assignable to LibraryVideo — the forward-compatible seam.
it('accepts a plain Video as a LibraryVideo', () => {
  const v: Video = {
    id: 'z',
    path: '/z.mp4',
    title: 'Z',
    addedAt: '2026-01-01T00:00:00Z',
    durationSec: 10,
    hasTranscript: false,
  };
  const lv: LibraryVideo = v;
  expect(cardBadges(lv)).toEqual([]);
});
