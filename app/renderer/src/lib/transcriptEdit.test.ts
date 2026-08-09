import { describe, expect, it } from 'vitest';

import {
  buildEditSpans,
  editedText,
  flattenWords,
  keepSpansFor,
  remapTime,
  removedSeconds,
  selectRange,
  toggleWord,
  wordAt,
} from './transcriptEdit';
import type { Transcript } from './transcriptEdit';

// The §3 transcript shape `transcript.get` returns (wordIds stamped sidecar-side
// by features/transcript_edit.address_transcript).
const TRANSCRIPT: Transcript = {
  language: 'en',
  durationSec: 10,
  segments: [
    {
      start: 0,
      end: 3.5,
      text: 'we um should ship',
      words: [
        { wordId: 'w0-0', segmentIndex: 0, wordIndex: 0, text: 'we', start: 0, end: 0.5 },
        { wordId: 'w0-1', segmentIndex: 0, wordIndex: 1, text: 'um', start: 1, end: 1.4 },
        { wordId: 'w0-2', segmentIndex: 0, wordIndex: 2, text: 'should', start: 2, end: 2.5 },
        { wordId: 'w0-3', segmentIndex: 0, wordIndex: 3, text: 'ship', start: 3, end: 3.5 },
      ],
    },
  ],
};

describe('flattenWords', () => {
  it('flattens every stamped word in transcript order', () => {
    expect(flattenWords(TRANSCRIPT).map((w) => w.wordId)).toEqual(['w0-0', 'w0-1', 'w0-2', 'w0-3']);
  });

  it('spans multiple segments', () => {
    const t: Transcript = {
      segments: [
        { words: [{ wordId: 'w0-0', text: 'a', start: 0, end: 0.2 }] },
        { words: [{ wordId: 'w1-0', text: 'b', start: 1, end: 1.2 }] },
      ],
    };
    expect(flattenWords(t).map((w) => w.wordId)).toEqual(['w0-0', 'w1-0']);
  });

  it('derives a wordId when the sidecar did not stamp one', () => {
    const t: Transcript = { segments: [{ words: [{ text: 'a', start: 0, end: 0.2 }] }] };
    expect(flattenWords(t)[0]).toEqual({
      wordId: 'w0-0',
      segmentIndex: 0,
      wordIndex: 0,
      text: 'a',
      start: 0,
      end: 0.2,
    });
  });

  it('returns [] for a null/undefined/empty transcript', () => {
    expect(flattenWords(null)).toEqual([]);
    expect(flattenWords(undefined)).toEqual([]);
    expect(flattenWords({})).toEqual([]);
    expect(flattenWords({ segments: [] })).toEqual([]);
  });

  it('skips malformed segments and words instead of throwing', () => {
    const t = {
      segments: [
        null,
        'nope',
        { words: null },
        { words: ['nope', 42, { text: 'ok', start: 1, end: 2 }] },
      ],
    } as unknown as Transcript;
    expect(flattenWords(t).map((w) => w.text)).toEqual(['ok']);
  });

  it('drops a word whose timings are not finite numbers', () => {
    const t = {
      segments: [
        {
          words: [
            { wordId: 'bad-1', text: 'x', start: 'a', end: 2 },
            { wordId: 'bad-2', text: 'y', start: 1, end: Number.NaN },
            { wordId: 'ok', text: 'z', start: 1, end: 2 },
          ],
        },
      ],
    } as unknown as Transcript;
    expect(flattenWords(t).map((w) => w.wordId)).toEqual(['ok']);
  });

  it('coerces a missing text to the empty string', () => {
    const t = { segments: [{ words: [{ start: 0, end: 1 }] }] } as unknown as Transcript;
    expect(flattenWords(t)[0]?.text).toBe('');
  });
});

describe('toggleWord', () => {
  it('adds an id and returns a NEW set (the input is untouched)', () => {
    const before = new Set<string>();
    const after = toggleWord(before, 'w0-3');
    expect([...after]).toEqual(['w0-3']);
    expect(before.size).toBe(0);
  });

  it('removes an id that was already deleted', () => {
    expect([...toggleWord(new Set(['w0-1', 'w0-3']), 'w0-3')]).toEqual(['w0-1']);
  });
});

describe('selectRange', () => {
  const words = flattenWords(TRANSCRIPT);

  it('returns the inclusive ids between two anchors', () => {
    expect(selectRange(words, 'w0-1', 'w0-3')).toEqual(['w0-1', 'w0-2', 'w0-3']);
  });

  it('is order-insensitive (drag backwards)', () => {
    expect(selectRange(words, 'w0-3', 'w0-1')).toEqual(['w0-1', 'w0-2', 'w0-3']);
  });

  it('a single-word range is that word', () => {
    expect(selectRange(words, 'w0-2', 'w0-2')).toEqual(['w0-2']);
  });

  it('returns [] when either anchor is unknown', () => {
    expect(selectRange(words, 'ghost', 'w0-2')).toEqual([]);
    expect(selectRange(words, 'w0-2', 'ghost')).toEqual([]);
  });
});

describe('buildEditSpans', () => {
  const words = flattenWords(TRANSCRIPT);

  it('emits one delete span per deleted word, in transcript order', () => {
    expect(buildEditSpans(words, new Set(['w0-3', 'w0-1']))).toEqual([
      { op: 'delete', wordId: 'w0-1' },
      { op: 'delete', wordId: 'w0-3' },
    ]);
  });

  it('ignores ids that are not in the transcript', () => {
    expect(buildEditSpans(words, new Set(['ghost']))).toEqual([]);
  });

  it('emits nothing when nothing is deleted', () => {
    expect(buildEditSpans(words, new Set())).toEqual([]);
  });
});

describe('removedSeconds', () => {
  const words = flattenWords(TRANSCRIPT);

  it('sums the deleted word durations', () => {
    expect(removedSeconds(words, new Set(['w0-1', 'w0-3']))).toBe(0.9);
  });

  it('is 0 with no deletions', () => {
    expect(removedSeconds(words, new Set())).toBe(0);
  });

  it('never counts a negative duration', () => {
    const inverted = [{ wordId: 'x', segmentIndex: 0, wordIndex: 0, text: 'x', start: 5, end: 4 }];
    expect(removedSeconds(inverted, new Set(['x']))).toBe(0);
  });
});

describe('editedText', () => {
  const words = flattenWords(TRANSCRIPT);

  it('renders the transcript without the deleted tokens', () => {
    expect(editedText(words, new Set(['w0-1']))).toBe('we should ship');
  });

  it('renders the full text when nothing is deleted', () => {
    expect(editedText(words, new Set())).toBe('we um should ship');
  });

  it('trims stray whitespace from each token', () => {
    const spaced = [
      { wordId: 'a', segmentIndex: 0, wordIndex: 0, text: '  hi  ', start: 0, end: 1 },
    ];
    expect(editedText(spaced, new Set())).toBe('hi');
  });
});

describe('keepSpansFor', () => {
  const words = flattenWords(TRANSCRIPT);

  it('inverts one deleted word into two keeps', () => {
    expect(keepSpansFor(words, new Set(['w0-3']), 10)).toEqual([
      [0, 3],
      [3.5, 10],
    ]);
  });

  it('merges adjacent/overlapping deletions into one gap', () => {
    const overlapping = [
      { wordId: 'a', segmentIndex: 0, wordIndex: 0, text: 'a', start: 1, end: 2.5 },
      { wordId: 'b', segmentIndex: 0, wordIndex: 1, text: 'b', start: 2, end: 3 },
    ];
    expect(keepSpansFor(overlapping, new Set(['a', 'b']), 10)).toEqual([
      [0, 1],
      [3, 10],
    ]);
  });

  it('keeps the whole clip when nothing is deleted', () => {
    expect(keepSpansFor(words, new Set(), 10)).toEqual([[0, 10]]);
  });

  it('drops a leading keep when the first word starts at 0', () => {
    expect(keepSpansFor(words, new Set(['w0-0']), 10)).toEqual([[0.5, 10]]);
  });

  it('drops the trailing keep when the deletion runs to the end', () => {
    const tail = [{ wordId: 'a', segmentIndex: 0, wordIndex: 0, text: 'a', start: 8, end: 10 }];
    expect(keepSpansFor(tail, new Set(['a']), 10)).toEqual([[0, 8]]);
  });

  it('clamps a deletion past the clip end', () => {
    const over = [{ wordId: 'a', segmentIndex: 0, wordIndex: 0, text: 'a', start: 9, end: 99 }];
    expect(keepSpansFor(over, new Set(['a']), 10)).toEqual([[0, 9]]);
  });

  it('returns [] for a non-positive duration', () => {
    expect(keepSpansFor(words, new Set(['w0-3']), 0)).toEqual([]);
  });

  it('degrades a delete-everything to the whole clip (an empty keep-list is unrenderable)', () => {
    const all = [{ wordId: 'a', segmentIndex: 0, wordIndex: 0, text: 'a', start: 0, end: 10 }];
    expect(keepSpansFor(all, new Set(['a']), 10)).toEqual([[0, 10]]);
  });
});

describe('remapTime', () => {
  const keeps: ReadonlyArray<readonly [number, number]> = [
    [0, 3],
    [3.5, 10],
  ];

  it('maps a time inside the first keep to itself', () => {
    expect(remapTime(1, keeps)).toBe(1);
  });

  it('slides a time after the cut earlier by the removed amount', () => {
    expect(remapTime(4, keeps)).toBe(3.5);
  });

  it('collapses a time inside the removed span onto the cut point', () => {
    expect(remapTime(3.2, keeps)).toBe(3);
  });

  it('clamps a time before the first keep to 0', () => {
    expect(remapTime(-1, [[2, 5]])).toBe(0);
  });

  it('clamps a time past the last keep to the total kept duration', () => {
    expect(remapTime(99, keeps)).toBe(9.5);
  });

  it('is 0 for an empty keep-list', () => {
    expect(remapTime(5, [])).toBe(0);
  });
});

describe('wordAt', () => {
  const words = flattenWords(TRANSCRIPT);

  it('finds the word containing the playhead', () => {
    expect(wordAt(words, 2.2)?.text).toBe('should');
  });

  it('is inclusive of the word start and end', () => {
    expect(wordAt(words, 2)?.wordId).toBe('w0-2');
    expect(wordAt(words, 2.5)?.wordId).toBe('w0-2');
  });

  it('is null between words and outside the transcript', () => {
    expect(wordAt(words, 1.7)).toBeNull();
    expect(wordAt(words, 99)).toBeNull();
  });
});
