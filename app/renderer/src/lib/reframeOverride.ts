// reframeOverride.ts — the renderer's PURE per-shot override logic (V1.1 Lane R, WU R2).
//
// Mirrors the sidecar `media_studio.features.reframe_override` decision layer so the
// manual-correction panel can let a user FLIP the active speaker, SWITCH the layout,
// or NUDGE the crop on individual shots, and compute EXACTLY which shots changed so
// only those re-render (never the whole clip). The heavy per-shot re-render is the R1
// engine's job — this module only resolves the user's edits + the affected-shot set.
//
// Everything here is pure (no React, no DOM, no rpc). Wire field names (camelCase)
// mirror the sidecar contract; crop is `[x, y, w, h]` in source pixels, matching the
// R0 ReframeTrace. Unit-tested to 100% in reframeOverride.test.ts.

/** The three layout classes a shot may render with (mirrors sidecar `LAYOUTS`). */
export const SHOT_LAYOUTS = ['single', 'split', 'composite'] as const;
export type ShotLayout = (typeof SHOT_LAYOUTS)[number];

/** A crop rectangle `[x, y, w, h]` in source pixels (matches the R0 trace crop). */
export type Crop = readonly [number, number, number, number];

/** One shot's reframe decision: chosen speaker + layout + crop (+ candidates). */
export interface ShotDecision {
  index: number;
  startFrame: number;
  endFrame: number;
  /** The chosen active-speaker id ("" = none / saliency crop). */
  speaker: string;
  layout: ShotLayout;
  crop: Crop;
  /** The candidate speaker ids the detector found in this shot (flip targets). */
  speakers: readonly string[];
}

/** The full editable per-shot plan for one clip. */
export interface ShotPlan {
  sourceWidth: number;
  sourceHeight: number;
  fps: number;
  shots: readonly ShotDecision[];
}

/** A user's patch to one shot — every edit field optional (absent = keep current). */
export interface ShotOverride {
  index: number;
  speaker?: string;
  layout?: ShotLayout;
  crop?: Crop;
}

/** Crop nudge step (source px) for the directional controls. */
export const NUDGE_PX = 16;
/** Crop zoom step: <1 zooms in (tighter crop), >1 zooms out (wider crop). */
export const ZOOM_IN_FACTOR = 0.9;
export const ZOOM_OUT_FACTOR = 1.1;

/**
 * Clamp a crop fully inside the source frame; throws (loud) on a degenerate
 * (non-positive) width/height — there is no sensible frame to render from it
 * (no silent fixup). Position + size are pulled inside `[0,width] x [0,height]`.
 */
export function clampCrop(crop: Crop, width: number, height: number): Crop {
  const [cx, cy, cw, ch] = crop;
  if (cw <= 0 || ch <= 0) throw new Error('crop width and height must be positive');
  const w = Math.min(cw, width);
  const h = Math.min(ch, height);
  const x = Math.min(Math.max(cx, 0), width - w);
  const y = Math.min(Math.max(cy, 0), height - h);
  return [x, y, w, h];
}

/** Nudge a crop by `(dx, dy)` source px, re-clamped inside the frame. */
export function nudgeCrop(crop: Crop, dx: number, dy: number, width: number, height: number): Crop {
  const [x, y, w, h] = crop;
  return clampCrop([x + dx, y + dy, w, h], width, height);
}

/**
 * Scale a crop about its centre by `factor` (loud on a non-positive factor),
 * re-clamped inside the frame. `<1` tightens (zoom in), `>1` widens (zoom out).
 */
export function zoomCrop(crop: Crop, factor: number, width: number, height: number): Crop {
  if (factor <= 0) throw new Error('zoom factor must be positive');
  const [x, y, w, h] = crop;
  const nw = w * factor;
  const nh = h * factor;
  const nx = x + w / 2 - nw / 2;
  const ny = y + h / 2 - nh / 2;
  return clampCrop([nx, ny, nw, nh], width, height);
}

/**
 * The next candidate speaker after `current` (wraps to the first). Returns
 * `current` unchanged when there are fewer than two candidates (nothing to flip).
 * An unknown `current` starts the cycle at the first candidate.
 */
export function cycleSpeaker(current: string, speakers: readonly string[]): string {
  if (speakers.length < 2) return current;
  const idx = speakers.indexOf(current);
  return speakers[(idx + 1) % speakers.length];
}

/** True when two crops are element-wise equal. */
function cropsEqual(a: Crop, b: Crop): boolean {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2] && a[3] === b[3];
}

/**
 * Return `shot` patched by `override` (immutable). A `speaker` not among the
 * shot's candidates throws (loud — mirrors the sidecar guard); `layout` is type-
 * checked at compile time; `crop` is clamped into the frame.
 */
export function applyShotOverride(
  shot: ShotDecision,
  override: ShotOverride,
  width: number,
  height: number,
): ShotDecision {
  const next: ShotDecision = { ...shot };
  if (override.speaker !== undefined) {
    if (!shot.speakers.includes(override.speaker)) {
      throw new Error(`speaker "${override.speaker}" is not a candidate for shot ${shot.index}`);
    }
    next.speaker = override.speaker;
  }
  if (override.layout !== undefined) next.layout = override.layout;
  if (override.crop !== undefined) next.crop = clampCrop(override.crop, width, height);
  return next;
}

/**
 * Resolve `overrides` (keyed by shot index) onto `plan`, returning a NEW plan
 * (immutable). Shots with no override are unchanged; an override for an unknown
 * index throws (loud).
 */
export function applyShotOverrides(plan: ShotPlan, overrides: readonly ShotOverride[]): ShotPlan {
  const valid = new Set(plan.shots.map((s) => s.index));
  const byIndex = new Map<number, ShotOverride>();
  for (const ov of overrides) {
    if (!valid.has(ov.index)) throw new Error(`override targets unknown shot index ${ov.index}`);
    byIndex.set(ov.index, ov);
  }
  const shots = plan.shots.map((shot) => {
    const ov = byIndex.get(shot.index);
    return ov ? applyShotOverride(shot, ov, plan.sourceWidth, plan.sourceHeight) : shot;
  });
  return { ...plan, shots };
}

/**
 * The indices of shots whose speaker / layout / crop changed — the EXACT set a
 * caller must re-render. The two plans must describe the same shots (loud
 * otherwise).
 */
export function affectedShotIndices(base: ShotPlan, resolved: ShotPlan): number[] {
  if (base.shots.length !== resolved.shots.length) {
    throw new Error('plans have a different number of shots');
  }
  const affected: number[] = [];
  base.shots.forEach((before, i) => {
    const after = resolved.shots[i];
    if (before.index !== after.index) throw new Error('plans describe different shots');
    if (
      before.speaker !== after.speaker ||
      before.layout !== after.layout ||
      !cropsEqual(before.crop, after.crop)
    ) {
      affected.push(after.index);
    }
  });
  return affected;
}
