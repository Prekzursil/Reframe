// speechKeywords.test.ts — the SETTLING EXPERIMENT for the speech-keyword
// threshold that `transcribe-journey.spec.ts` asserts on.
//
// ── WHY THIS FILE EXISTS ─────────────────────────────────────────────────────
// `fixtures.SPEECH_KEYWORD_MIN_HITS` used to justify itself with "the same
// assertion scores 0 hits on the speechless `sine` sample (measured)". That was
// REFUTED: on speechless audio the GUI spec dies EARLIER, at the zero-segments
// arm (`.transcript-segments li` `.not.toHaveCount(0)`), so the keyword arm is
// never evaluated in the broken state. The zero-segments arm is genuinely
// both-states verified; the THRESHOLD's failing direction was not observed at
// all — the both-states proof belonged to a different assertion than the one
// carrying the claim.
//
// This file closes that gap deterministically, with no audio, no model and no
// GUI: it pins the FAILING direction (a 1-hit transcript must be BELOW the
// floor) and the boundary (a 2-hit transcript must be AT it). Mutation-checked:
// setting SPEECH_KEYWORD_MIN_HITS to 1 turns the "1 hit is below the floor" case
// red, so this suite is actually protecting the constant rather than restating
// it.
//
// It rides `vitest.e2e.config.ts` (`include: ['e2e/**/*.test.{ts,tsx}']`, run by
// `npm run test:e2e:dom`), which every OS leg of e2e.yml already runs — so unlike
// the Windows-only GUI journey, this check is OS-independent and always exercised.

import { describe, expect, it } from 'vitest';

import { SPEECH_KEYWORDS, SPEECH_KEYWORD_MIN_HITS, SPEECH_PHRASE, matchedSpeechKeywords } from './fixtures';

describe('speech-keyword oracle', () => {
  it('DETECTOR CONTROL — the phrase the fixture speaks scores every keyword', () => {
    // If this ever fails, the keyword list and the phrase have drifted apart and
    // every conclusion below is meaningless.
    expect(matchedSpeechKeywords(SPEECH_PHRASE)).toEqual([...SPEECH_KEYWORDS]);
  });

  it('scores 0 on an EMPTY transcript — silence can never satisfy the floor', () => {
    expect(matchedSpeechKeywords('')).toEqual([]);
    // The load-bearing consequence: the floor is strictly positive, so a
    // transcript with no recognised speech cannot pass the keyword arm even if
    // the earlier zero-segments arm were ever removed.
    expect(SPEECH_KEYWORD_MIN_HITS).toBeGreaterThan(0);
  });

  it('FAILS CLOSED at one hit — the arm the speechless run never reaches', () => {
    const oneHit = 'the lazy dog sat still and nothing else was said';
    expect(matchedSpeechKeywords(oneHit)).toEqual(['dog']);
    // This is the assertion the sine fixture could NOT make: a transcript that
    // carries a single keyword must be rejected by the threshold.
    expect(matchedSpeechKeywords(oneHit).length).toBeLessThan(SPEECH_KEYWORD_MIN_HITS);
  });

  it('passes at two hits — the boundary is exactly where the constant says', () => {
    const twoHits = 'a fox and a dog';
    expect(matchedSpeechKeywords(twoHits)).toEqual(['fox', 'dog']);
    expect(matchedSpeechKeywords(twoHits).length).toBeGreaterThanOrEqual(SPEECH_KEYWORD_MIN_HITS);
  });

  it('tolerates a mangled product name but not a mangled keyword', () => {
    // MEASURED with the shipped stack (faster-whisper 1.2.1, `tiny`, cpu/int8) on
    // all 3 enabled en-* SAPI voices of this box: "Reframe" came back as
    // "Refrain" / "Refrain" / "Reframed" while all four keywords survived 4/4.
    // That is exactly why the oracle is keyword-based and excludes the product
    // name — this case pins the reason so a future edit cannot quietly re-add it.
    const asHeard = 'The quick brown fox jumps over the lazy dog. Refrain converts landscape video to vertical.';
    expect(matchedSpeechKeywords(asHeard).length).toBe(SPEECH_KEYWORDS.length);
    expect(SPEECH_KEYWORDS).not.toContain('reframe');
  });

  it('matches case-insensitively and on inflected forms (deliberate substring match)', () => {
    // The matcher is a lowercase `includes`, so "Dogs"/"vertically" count. That
    // looseness is intended: whisper output is not word-normalised, and an exact
    // word-boundary match would fail on plurals for no benefit.
    expect(matchedSpeechKeywords('TWO DOGS and one FOX')).toEqual(['fox', 'dog']);
    expect(matchedSpeechKeywords('rendered vertically')).toEqual(['vertical']);
  });
});
