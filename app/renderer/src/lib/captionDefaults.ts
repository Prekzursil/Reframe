// captionDefaults.ts — the novice-first Netflix readability defaults + per-language
// reading-speed resolution (V1.1 Lane 1, WU S4).
//
// V1.1 lets a prosumer tune reading speed (CPS) and line count via a CaptionOverride
// (WU S1). The 80% novice never touches them, so they need a SAFE default — and the
// safe default is per-language (Netflix Timed Text Style Guide, §1.5): children's
// content reads slowest, English adult may relax, everything else takes the
// conservative cross-language value.
//
// This module is the renderer-side MIRROR of the sidecar `resolve_caption_limits`
// (caption_polish.py): same numbers, same precedence (explicit override wins,
// clamped 10..30; else the per-content/per-language default; line count toggles
// 1/2 else 2). Mirroring it here means the T2 customizer + the live preview show
// EXACTLY the reading speed / line count the burn will apply — preview parity with
// the post-conversion resolved style, not a second, drifting guess.
//
// Everything here is PURE (no React, no DOM). Unit-tested in captionDefaults.test.ts.

import {
  MAX_CPS_MAX,
  MAX_CPS_MIN,
  type CaptionMaxLines,
  type CaptionOverride,
} from './captionOverride';

/** Conservative cross-language adult reading speed (chars/sec) — the default. */
export const MAX_CPS = 17;
/** English adult may relax to the Netflix English-template reading speed. */
export const MAX_CPS_ENGLISH = 20;
/** Children's content reads slowest (Netflix children's reading speed). */
export const MAX_CPS_CHILDREN = 13;
/** Max characters per line (Latin scripts). */
export const MAX_CPL = 42;
/** Max lines per cue (prefer 1 line unless the cue exceeds the CPL limit). */
export const MAX_LINES = 2;

/**
 * The content context the per-language default is resolved from. Both fields are
 * OPTIONAL: an absent context yields the conservative cross-language default (so an
 * un-wired caller behaves exactly like V1's fixed 17).
 */
export interface CaptionContentContext {
  /** Project / caption language as an ISO / BCP-47 code (e.g. `en`, `en-US`, `ro`). */
  language?: string;
  /** True when the content is for children (the slowest reading speed wins). */
  children?: boolean;
}

/** True when `language` is an English code (`en`, `en-US`, …); case/space tolerant. */
export function isEnglishLanguage(language: string | undefined): boolean {
  return typeof language === 'string' && language.trim().toLowerCase().startsWith('en');
}

/**
 * The per-content / per-language reading-speed default (§1.5): children's content
 * => 13; else English => 20; else the conservative cross-language 17. Mirrors the
 * sidecar `resolve_caption_limits` default branch (children flag wins over language).
 */
export function defaultMaxCps(content?: CaptionContentContext): number {
  if (content?.children) return MAX_CPS_CHILDREN;
  return isEnglishLanguage(content?.language) ? MAX_CPS_ENGLISH : MAX_CPS;
}

/** Clamp a reading speed into the [MAX_CPS_MIN, MAX_CPS_MAX] (10..30) window. */
function clampCps(value: number): number {
  if (value < MAX_CPS_MIN) return MAX_CPS_MIN;
  if (value > MAX_CPS_MAX) return MAX_CPS_MAX;
  return value;
}

/**
 * Resolve the EFFECTIVE reading-speed cap: an explicit, finite `override.maxCps`
 * is the user's choice and wins, clamped into 10..30; otherwise the per-language
 * default applies. Mirrors the sidecar precedence exactly.
 */
export function resolveMaxCps(
  override: CaptionOverride | undefined,
  content?: CaptionContentContext,
): number {
  const raw = override?.maxCps;
  if (typeof raw === 'number' && Number.isFinite(raw)) return clampCps(raw);
  return defaultMaxCps(content);
}

/** Resolve the EFFECTIVE line count: an explicit 1/2 override wins, else MAX_LINES. */
export function resolveMaxLines(override: CaptionOverride | undefined): CaptionMaxLines {
  return override?.maxLines === 1 || override?.maxLines === 2 ? override.maxLines : MAX_LINES;
}

/** The fully-resolved novice readability bundle the burn will apply. */
export interface ResolvedReadability {
  /** Effective reading-speed cap (chars/sec). */
  maxCps: number;
  /** Effective line count (1 or 2). */
  maxLines: CaptionMaxLines;
  /** The fixed per-line character ceiling (Latin scripts). */
  maxCpl: number;
}

/**
 * Resolve the full readability bundle (`maxCps` + `maxLines` + `maxCpl`) the way
 * the sidecar does, so the preview can show exactly what will burn (§1.5 preview
 * parity). `maxCpl` is fixed at the Netflix Latin-script ceiling; the line count
 * scales the per-cue capacity in the sidecar gate.
 */
export function resolveReadability(
  override: CaptionOverride | undefined,
  content?: CaptionContentContext,
): ResolvedReadability {
  return {
    maxCps: resolveMaxCps(override, content),
    maxLines: resolveMaxLines(override),
    maxCpl: MAX_CPL,
  };
}
