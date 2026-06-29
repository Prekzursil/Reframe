// routingSort.test.ts — the M3 Advanced model-SORT pure helper.
import { describe, it, expect } from 'vitest';
import { sortModelMetas, type ModelSortMode, MODEL_SORT_MODES } from './routingSort';
import type { ModelMeta } from '../lib/rpc';

function meta(over: Partial<ModelMeta>): ModelMeta {
  return {
    model: 'm',
    digest: 'd',
    sizeBytes: null,
    paramsB: null,
    quantBits: null,
    vramEstimateGb: null,
    capabilities: [],
    aliases: [],
    fits: false,
    ...over,
  };
}

describe('sortModelMetas', () => {
  it('exposes the three sort modes verbatim', () => {
    expect(MODEL_SORT_MODES).toEqual(['fit', 'size', 'name']);
  });

  it('does not mutate the input array (returns a new array)', () => {
    const input = [meta({ model: 'b' }), meta({ model: 'a' })];
    const out = sortModelMetas(input, 'name');
    expect(out).not.toBe(input);
    expect(input.map((m) => m.model)).toEqual(['b', 'a']);
  });

  it('sorts by name alphabetically (case-insensitive)', () => {
    const out = sortModelMetas([meta({ model: 'Zephyr' }), meta({ model: 'alpha' })], 'name');
    expect(out.map((m) => m.model)).toEqual(['alpha', 'Zephyr']);
  });

  it('sorts by size ascending with unknown sizes last', () => {
    const out = sortModelMetas(
      [
        meta({ model: 'big', sizeBytes: 9000 }),
        meta({ model: 'unknown', sizeBytes: null }),
        meta({ model: 'small', sizeBytes: 100 }),
      ],
      'size',
    );
    expect(out.map((m) => m.model)).toEqual(['small', 'big', 'unknown']);
  });

  it('sorts by VRAM-fit: fitting models first, then ascending VRAM estimate, unknowns last', () => {
    const out = sortModelMetas(
      [
        meta({ model: 'fits-big', fits: true, vramEstimateGb: 7 }),
        meta({ model: 'nofit', fits: false, vramEstimateGb: 2 }),
        meta({ model: 'fits-small', fits: true, vramEstimateGb: 3 }),
        meta({ model: 'fits-unknown', fits: true, vramEstimateGb: null }),
      ],
      'fit',
    );
    expect(out.map((m) => m.model)).toEqual(['fits-small', 'fits-big', 'fits-unknown', 'nofit']);
  });

  it('breaks ties by name within an equal sort key', () => {
    const out = sortModelMetas(
      [meta({ model: 'beta', sizeBytes: 500 }), meta({ model: 'alpha', sizeBytes: 500 })],
      'size',
    );
    expect(out.map((m) => m.model)).toEqual(['alpha', 'beta']);
  });

  it('falls back to name sort for an unknown mode (defensive)', () => {
    const out = sortModelMetas(
      [meta({ model: 'b' }), meta({ model: 'a' })],
      'bogus' as ModelSortMode,
    );
    expect(out.map((m) => m.model)).toEqual(['a', 'b']);
  });
});
