// routingSort.ts — the M3 Advanced model-SORT pure helper.
//
// The Advanced disclosure (Settings › Models & System) lets the user re-order the
// metadata-driven eligibility list by the axis they care about: VRAM-fit (which
// models actually fit this device, cheapest first), download size, or name. Pure
// + immutable so it is trivially unit-tested to 100% with no RPC/DOM.
import type { ModelMeta } from '../lib/rpc';

/** The model-sort axes offered in the Advanced disclosure (wire-stable order). */
export const MODEL_SORT_MODES = ['fit', 'size', 'name'] as const;
export type ModelSortMode = (typeof MODEL_SORT_MODES)[number];

/** Human label for a sort mode (the `<select>` option text). */
export const MODEL_SORT_LABELS: Record<ModelSortMode, string> = {
  fit: 'VRAM fit',
  size: 'Download size',
  name: 'Name',
};

/** Case-insensitive name compare (the stable tie-breaker for every mode). */
function byName(a: ModelMeta, b: ModelMeta): number {
  return a.model.localeCompare(b.model, undefined, { sensitivity: 'base' });
}

/**
 * Ascending numeric compare where `null` (unknown) always sorts LAST, then falls
 * back to name so the order is fully deterministic.
 */
function byNumberNullsLast(
  a: ModelMeta,
  b: ModelMeta,
  pick: (m: ModelMeta) => number | null,
): number {
  const av = pick(a);
  const bv = pick(b);
  if (av === null && bv === null) return byName(a, b);
  if (av === null) return 1;
  if (bv === null) return -1;
  if (av !== bv) return av - bv;
  return byName(a, b);
}

/**
 * Return a NEW array of `models` sorted by `mode`:
 *   * `fit`  — models that fit the device first, then ascending VRAM estimate
 *     (cheapest-fitting first; unknown estimate last), then name.
 *   * `size` — ascending download size (unknown size last), then name.
 *   * `name` — case-insensitive alphabetical (also the fallback for any
 *     unrecognised mode, so the UI never crashes on a stale value).
 * The input array is never mutated.
 */
export function sortModelMetas(models: ModelMeta[], mode: ModelSortMode): ModelMeta[] {
  const copy = [...models];
  if (mode === 'size') {
    return copy.sort((a, b) => byNumberNullsLast(a, b, (m) => m.sizeBytes));
  }
  if (mode === 'fit') {
    return copy.sort((a, b) => {
      if (a.fits !== b.fits) return a.fits ? -1 : 1;
      return byNumberNullsLast(a, b, (m) => m.vramEstimateGb);
    });
  }
  return copy.sort(byName);
}
