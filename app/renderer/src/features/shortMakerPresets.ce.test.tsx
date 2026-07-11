// shortMakerPresets.ce.test.tsx — cross-edit coverage for the V1.1 caption
// TUNING override threading through buildExportParams (reconcile Finding #3).
//
// buildExportParams gained an optional `output.captionOverride` spread: it is
// forwarded to the sidecar ONLY when provided, so callers with no override stay
// byte-identical. Both branches of that conditional spread are exercised here to
// keep shortMakerPresets.ts at 100%. Isolated in a uniquely-named file so it
// never collides with the parallel ShortMaker suites; coverage is by source file.

import { describe, it, expect } from 'vitest';
import { buildExportParams } from './shortMakerPresets';
import { type Candidate, sanitizeControls } from './shortMakerLogic';
import type { CaptionOverride } from '../lib/captionOverride';

function cand(over: Partial<Candidate> = {}): Candidate {
  return {
    rank: 1,
    start: 97,
    end: 131,
    durationSec: 34,
    hook: 'As it turns out, there is a pattern',
    why: 'Introduces the core concept',
    score: 95,
    sourceStart: 97,
    ...over,
  };
}

describe('buildExportParams — captionOverride spread (reconcile Finding #3)', () => {
  it('includes captionOverride when output.captionOverride is provided', () => {
    const override: CaptionOverride = { uppercase: true, maxLines: 2, maxCps: 17 };
    const params = buildExportParams('v1', [cand()], sanitizeControls({}), '', {
      captionOverride: override,
    });
    expect(params.captionOverride).toEqual(override);
  });

  it('OMITS captionOverride when it is undefined (byte-identical for override-less callers)', () => {
    // Default output ({}) — no captionOverride key at all.
    expect('captionOverride' in buildExportParams('v1', [cand()], sanitizeControls({}), '')).toBe(
      false,
    );
    // Explicitly-undefined field — still omitted (falsy branch of the spread).
    expect(
      'captionOverride' in
        buildExportParams('v1', [cand()], sanitizeControls({}), '', { captionOverride: undefined }),
    ).toBe(false);
  });
});
