import { describe, expect, it } from 'vitest';
import {
  type Crop,
  type ShotDecision,
  type ShotPlan,
  affectedShotIndices,
  applyShotOverride,
  applyShotOverrides,
  clampCrop,
  cycleSpeaker,
  nudgeCrop,
  zoomCrop,
} from './reframeOverride';

function shot(overrides: Partial<ShotDecision> = {}): ShotDecision {
  return {
    index: 0,
    startFrame: 0,
    endFrame: 3,
    speaker: 'a',
    layout: 'single',
    crop: [100, 0, 600, 1080],
    speakers: ['a', 'b'],
    ...overrides,
  };
}

function plan(): ShotPlan {
  return {
    sourceWidth: 1920,
    sourceHeight: 1080,
    fps: 30,
    shots: [shot({ index: 0 }), shot({ index: 1, speaker: 'b', layout: 'split', startFrame: 3, endFrame: 6 })],
  };
}

describe('clampCrop', () => {
  it('pulls an oversized off-frame crop fully inside', () => {
    expect(clampCrop([-20, 200, 400, 50], 100, 100)).toEqual([0, 50, 100, 50]);
  });

  it('leaves an already-inside crop unchanged', () => {
    expect(clampCrop([10, 10, 20, 20], 100, 100)).toEqual([10, 10, 20, 20]);
  });

  it('throws loud on a degenerate width or height', () => {
    expect(() => clampCrop([0, 0, 0, 10], 100, 100)).toThrow('width and height must be positive');
    expect(() => clampCrop([0, 0, 10, -1], 100, 100)).toThrow('width and height must be positive');
  });
});

describe('nudgeCrop', () => {
  it('moves and re-clamps', () => {
    expect(nudgeCrop([10, 10, 20, 20], 5, -100, 100, 100)).toEqual([15, 0, 20, 20]);
  });
});

describe('zoomCrop', () => {
  it('tightens when factor < 1', () => {
    expect(zoomCrop([10, 10, 40, 40], 0.5, 100, 100)).toEqual([20, 20, 20, 20]);
  });

  it('widens and clamps when factor > 1', () => {
    expect(zoomCrop([40, 40, 20, 20], 5, 100, 100)).toEqual([0, 0, 100, 100]);
  });

  it('throws loud on a non-positive factor', () => {
    expect(() => zoomCrop([0, 0, 10, 10], 0, 100, 100)).toThrow('zoom factor must be positive');
  });
});

describe('cycleSpeaker', () => {
  it('returns current when fewer than two candidates', () => {
    expect(cycleSpeaker('a', ['a'])).toBe('a');
    expect(cycleSpeaker('a', [])).toBe('a');
  });

  it('advances to the next candidate and wraps', () => {
    expect(cycleSpeaker('a', ['a', 'b', 'c'])).toBe('b');
    expect(cycleSpeaker('c', ['a', 'b', 'c'])).toBe('a');
  });

  it('starts at the first candidate for an unknown current', () => {
    expect(cycleSpeaker('z', ['a', 'b'])).toBe('a');
  });
});

describe('applyShotOverride', () => {
  it('flips speaker, switches layout, and clamps crop', () => {
    const out = applyShotOverride(shot(), { index: 0, speaker: 'b', layout: 'composite', crop: [-5, 0, 9999, 9999] }, 1920, 1080);
    expect(out.speaker).toBe('b');
    expect(out.layout).toBe('composite');
    expect(out.crop).toEqual([0, 0, 1920, 1080]);
  });

  it('is a no-op copy for an empty override', () => {
    const base = shot();
    const out = applyShotOverride(base, { index: 0 }, 1920, 1080);
    expect(out).toEqual(base);
    expect(out).not.toBe(base);
  });

  it('throws loud on a speaker that is not a candidate', () => {
    expect(() => applyShotOverride(shot(), { index: 0, speaker: 'z' }, 1920, 1080)).toThrow('is not a candidate');
  });
});

describe('applyShotOverrides', () => {
  it('resolves overrides immutably, leaving untouched shots alone', () => {
    const base = plan();
    const out = applyShotOverrides(base, [{ index: 1, speaker: 'a' }]);
    expect(out.shots[1].speaker).toBe('a');
    expect(out.shots[0]).toBe(base.shots[0]);
    expect(base.shots[1].speaker).toBe('b');
  });

  it('throws loud on an override for an unknown shot index', () => {
    expect(() => applyShotOverrides(plan(), [{ index: 9 }])).toThrow('unknown shot index 9');
  });
});

describe('affectedShotIndices', () => {
  it('returns only the changed shots', () => {
    const base = plan();
    const resolved = applyShotOverrides(base, [{ index: 1, layout: 'composite', crop: [0, 0, 200, 200] }]);
    expect(affectedShotIndices(base, resolved)).toEqual([1]);
    expect(affectedShotIndices(base, base)).toEqual([]);
  });

  it('detects a speaker-only and a crop-only change', () => {
    const base = plan();
    const speakerOnly = applyShotOverrides(base, [{ index: 0, speaker: 'b' }]);
    expect(affectedShotIndices(base, speakerOnly)).toEqual([0]);
    const cropOnly = applyShotOverrides(base, [{ index: 0, crop: [1, 1, 50, 50] as Crop }]);
    expect(affectedShotIndices(base, cropOnly)).toEqual([0]);
  });

  it('throws loud on a different shot count', () => {
    const base = plan();
    const shorter: ShotPlan = { ...base, shots: base.shots.slice(0, 1) };
    expect(() => affectedShotIndices(base, shorter)).toThrow('different number of shots');
  });

  it('throws loud when the plans describe different shots', () => {
    const base = plan();
    const swapped: ShotPlan = { ...base, shots: [...base.shots].reverse() };
    expect(() => affectedShotIndices(base, swapped)).toThrow('describe different shots');
  });
});
