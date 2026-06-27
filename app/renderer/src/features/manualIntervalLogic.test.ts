import { describe, expect, it } from 'vitest';
import {
  buildManualCandidates,
  formatTimecode,
  intervalToCandidate,
  parseTimecode,
} from './manualIntervalLogic';

describe('parseTimecode', () => {
  it('parses plain seconds', () => {
    expect(parseTimecode('90')).toBe(90);
    expect(parseTimecode('0')).toBe(0);
    expect(parseTimecode(' 12 ')).toBe(12);
  });

  it('parses mm:ss', () => {
    expect(parseTimecode('1:23')).toBe(83);
    expect(parseTimecode('0:00')).toBe(0);
    expect(parseTimecode('10:05')).toBe(605);
  });

  it('parses h:mm:ss', () => {
    expect(parseTimecode('1:02:03')).toBe(3723);
  });

  it('rejects empty / non-numeric / malformed input', () => {
    expect(parseTimecode('')).toBeNull();
    expect(parseTimecode('   ')).toBeNull();
    expect(parseTimecode('abc')).toBeNull();
    expect(parseTimecode('1:2:3:4')).toBeNull();
  });

  it('rejects out-of-range minutes/seconds fields and negatives', () => {
    expect(parseTimecode('1:99')).toBeNull(); // ss >= 60
    expect(parseTimecode('1:60:00')).toBeNull(); // mm >= 60
    expect(parseTimecode('-5')).toBeNull();
    expect(parseTimecode('1:-2')).toBeNull();
  });
});

describe('formatTimecode', () => {
  it('formats mm:ss and h:mm:ss', () => {
    expect(formatTimecode(83)).toBe('1:23');
    expect(formatTimecode(0)).toBe('0:00');
    expect(formatTimecode(3723)).toBe('1:02:03');
  });

  it('clamps invalid input to 0:00', () => {
    expect(formatTimecode(-5)).toBe('0:00');
    expect(formatTimecode(Number.NaN)).toBe('0:00');
  });
});

describe('intervalToCandidate', () => {
  it('builds a source-anchored candidate for a range', () => {
    const c = intervalToCandidate(83, 250, 2);
    expect(c.rank).toBe(2);
    expect(c.start).toBe(83);
    expect(c.sourceStart).toBe(83);
    expect(c.end).toBe(250);
    expect(c.durationSec).toBe(167);
  });
});

describe('buildManualCandidates', () => {
  it('ranks ranges 1..n in order', () => {
    const cands = buildManualCandidates([
      { start: 10, end: 40 },
      { start: 83, end: 250 },
    ]);
    expect(cands.map((c) => c.rank)).toEqual([1, 2]);
    expect(cands.map((c) => c.sourceStart)).toEqual([10, 83]);
  });

  it('returns an empty list for no ranges', () => {
    expect(buildManualCandidates([])).toEqual([]);
  });
});
