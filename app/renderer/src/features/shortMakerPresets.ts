// shortMakerPresets.ts — pure logic for the P4 §7/§8c/§8d ShortMaker surfaces
// (candidate sort, platform presets + batch, brand kit settings, export params).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget and
// to isolate the pure, render-free logic the unit tests exercise directly. These
// helpers never touch React or window.api — they take plain data and return new
// data (immutability). The component wires them to state + RPC.
//
// CONTRACT-NOTE: the shared candidate/control types + the base sanitizers live in
// shortMakerLogic.ts (the pure-logic module extracted from ShortMaker.tsx). This
// module imports them from there rather than from the component, so the wire
// field names stay single-sourced AND there is no import cycle with the React
// component (ShortMaker.tsx imports THIS module).

import {
  type Candidate,
  type ReviewItem,
  type ShortMakerControls,
  candidateId,
  sanitizeControls,
  displayVirality,
  CAPTION_STYLE_OPTIONS,
} from './shortMakerLogic';
import type { CaptionBox } from '../lib/captionPosition';
import type { SubtitleMode } from '../lib/outputOptions';

// ---------------------------------------------------------------------------
// P4 §7 — candidate sort (rank ↔ virality).
// ---------------------------------------------------------------------------

/** How the candidate review list is ordered. */
export type CandidateSort = 'rank' | 'virality';

/**
 * A candidate's virality for SORTING (not display): absent/invalid scores sink
 * to -1 so they sort last under the "virality" order, never above real numbers.
 */
function sortVirality(c: Candidate): number {
  const v = displayVirality(c.viralityPct);
  return v === null ? -1 : v;
}

/**
 * Sort review items by `mode`, NON-DESTRUCTIVELY (returns a new array):
 * - 'rank': ascending rank (the sidecar's own ranking — the default).
 * - 'virality': viralityPct descending; ties + missing scores fall back to rank.
 * The list identity/ids are untouched; only the display order changes.
 */
export function sortReviewItems(items: readonly ReviewItem[], mode: CandidateSort): ReviewItem[] {
  const copy = [...items];
  if (mode === 'virality') {
    copy.sort((a, b) => {
      const d = sortVirality(b.current) - sortVirality(a.current);
      return d !== 0 ? d : a.current.rank - b.current.rank;
    });
  } else {
    copy.sort((a, b) => a.current.rank - b.current.rank);
  }
  return copy;
}

// ---------------------------------------------------------------------------
// P4 §8c — platform presets + batch "make N".
// ---------------------------------------------------------------------------

/** A platform preset partially overrides the controls (aspect/maxSec/count). */
export interface PlatformPreset {
  id: string;
  label: string;
  aspect: string;
  maxSec: number;
  count: number;
}

/**
 * The vertical-platform presets (P4 §8c). All are 9:16. `maxSec` records each
 * platform's documented clip sweet-spot (TikTok 60 / Reels 90 / Shorts 60), but
 * see the CONTRACT-NOTE on `applyPreset`: the §5 hard clip window is 20-60 s,
 * enforced in BOTH the renderer (sanitizeControls) AND the sidecar
 * (select._resolve_window clamps max_sec to MAX_CLIP_SEC=60). So the EFFECTIVE
 * maxSec is min(preset.maxSec, 60). The presets stay distinct on `count` (an
 * enforceable axis): TikTok 5 / Reels 3 (longer clips → fewer) / Shorts 8 (short
 * & frequent). FROZEN ids: tiktok/reels/shorts.
 */
export const PLATFORM_PRESETS: Record<string, PlatformPreset> = {
  tiktok: { id: 'tiktok', label: 'TikTok', aspect: '9:16', maxSec: 60, count: 5 },
  reels: { id: 'reels', label: 'Reels', aspect: '9:16', maxSec: 90, count: 3 },
  shorts: { id: 'shorts', label: 'Shorts', aspect: '9:16', maxSec: 60, count: 8 },
} as const;

/** Stable display order of the preset buttons. */
export const PLATFORM_PRESET_IDS = ['tiktok', 'reels', 'shorts'] as const;
export type PlatformPresetId = (typeof PLATFORM_PRESET_IDS)[number];

/**
 * Apply a preset onto the current controls (immutably). Only aspect/maxSec/count
 * are overridden; the rest (caption style, engine, toggles, language, minSec)
 * survive. An unknown preset id returns the controls unchanged.
 *
 * CONTRACT-NOTE (§5 hard window): the result is passed through `sanitizeControls`,
 * which clamps maxSec into the hard 20-60 s window — so a preset asking for >60
 * (Reels 90) lands at the enforceable 60. This is deliberate: the sidecar clamps
 * identically (select._resolve_window), so promising 90 in the UI would be a lie
 * the pipeline silently corrects. minSec is lowered under the (clamped) maxSec so
 * the window never inverts.
 */
export function applyPreset(controls: ShortMakerControls, presetId: string): ShortMakerControls {
  const preset = PLATFORM_PRESETS[presetId];
  if (!preset) return controls;
  const minSec = Math.min(controls.minSec, preset.maxSec);
  return sanitizeControls({
    ...controls,
    aspect: preset.aspect,
    maxSec: preset.maxSec,
    minSec,
    count: preset.count,
  });
}

/**
 * The top `n` candidates by viralityPct (descending), tie-broken by rank — the
 * unattended-batch auto-approval set (§8c). Missing scores sort last. Returns a
 * NEW array; never mutates the input. `n <= 0` yields [].
 */
export function topByVirality(candidates: readonly Candidate[], n: number): Candidate[] {
  if (n <= 0) return [];
  return [...candidates]
    .sort((a, b) => {
      const d = sortVirality(b) - sortVirality(a);
      return d !== 0 ? d : a.rank - b.rank;
    })
    .slice(0, n);
}

/**
 * Build the `shortmaker.export` params from a set of candidates + controls (P4
 * §8c batch reuses this; runExport reuses it too). Mirrors the frozen §2 export
 * contract: candidateIds (resolved against the sidecar cache) + the inline
 * candidates fallback + the optional T4b/P3 controls + the optional A2
 * audioTrackId (sent ONLY when a non-empty track id is chosen).
 *
 * P4 §8b autoZoom (bool) ALWAYS flows (default OFF). §8a emphasis is tri-state:
 * 'on'/'off' send an explicit `emphasis` bool; 'default' OMITS the key so the
 * sidecar's `resolve_emphasis` per-style default applies (ON for OpusClip-style
 * templates, OFF for clean/minimal) — sending nothing is the contract default.
 *
 * P4 §4 caption editor: the optional `output` slice carries the caption POSITION
 * box + the subtitle DELIVERY mode (burn / soft track / sidecar / none). Each is
 * sent only when provided so the existing AI/batch callers (no editor) are
 * byte-identical; the sidecar honours `subtitleMode` (burn vs not, skip for
 * none/sidecar) + `captionPosition` (ASS alignment/margins).
 */
export interface ExportOutputOptions {
  captionPosition?: CaptionBox;
  subtitleMode?: SubtitleMode;
}

export function buildExportParams(
  videoId: string,
  candidates: readonly Candidate[],
  controls: ShortMakerControls,
  audioTrackId: string,
  output: ExportOutputOptions = {},
): Record<string, unknown> {
  return {
    videoId,
    candidateIds: candidates.map(candidateId),
    candidates: [...candidates],
    captionStyle: controls.captionStyle,
    reframeEngine: controls.reframeEngine,
    hookTitle: controls.hookTitle,
    // WU SP2: the hook-card toggle + top-N gate flow to the sidecar (which also
    // owns the first-~5 s window + the rank-ordered NN- output filename prefix).
    hookCard: controls.hookCard,
    hookCardTopN: controls.hookCardTopN,
    removeFillers: controls.removeFillers,
    autoZoom: controls.autoZoom,
    // audio-stabilize group: dead-air removal + camera-shake stabilization
    // pre-steps (both default OFF). They ALWAYS flow as bools — the sidecar
    // gates each on its own toggle (silence-trim wins over removeFillers; a
    // missing libvidstab reports the stabilize skip via job.progress).
    silenceTrim: controls.silenceTrim,
    stabilize: controls.stabilize,
    ...(controls.emphasis === 'default' ? {} : { emphasis: controls.emphasis === 'on' }),
    ...(audioTrackId ? { audioTrackId } : {}),
    ...(output.subtitleMode ? { subtitleMode: output.subtitleMode } : {}),
    ...(output.captionPosition ? { captionPosition: output.captionPosition } : {}),
  };
}

// ---------------------------------------------------------------------------
// P4 §8d — brand kit settings (persisted via settings.get/set).
// ---------------------------------------------------------------------------

/** The three FROZEN brand-kit settings keys (C12: free-form settings store). */
export interface BrandSettings {
  /** Absolute path to a watermark logo ('' = none). */
  brandLogoPath: string;
  /** Default caption template id ('' = no default; user picks per-short). */
  brandCaptionTemplate: string;
  /** Default caption font family ('' = template default). */
  brandFontFamily: string;
}

/** Empty brand kit (the safe default when no keys are persisted yet). */
export const EMPTY_BRAND_SETTINGS: BrandSettings = {
  brandLogoPath: '',
  brandCaptionTemplate: '',
  brandFontFamily: '',
};

/** Coerce one persisted value to a trimmed string ('' for anything non-string). */
function brandStr(v: unknown): string {
  return typeof v === 'string' ? v.trim() : '';
}

/**
 * Read the brand kit out of a raw `settings.get` result, TOLERATING absent keys
 * (C12: settings are free-form; the keys may not be in DEFAULT_SETTINGS yet).
 * A non-object input yields the empty kit; unknown caption templates are dropped
 * so the picker never shows a stale/invalid default.
 */
export function readBrandSettings(raw: unknown): BrandSettings {
  if (!raw || typeof raw !== 'object') return EMPTY_BRAND_SETTINGS;
  const r = raw as Record<string, unknown>;
  const template = brandStr(r.brandCaptionTemplate);
  return {
    brandLogoPath: brandStr(r.brandLogoPath),
    brandCaptionTemplate: CAPTION_STYLE_OPTIONS.includes(template) ? template : '',
    brandFontFamily: brandStr(r.brandFontFamily),
  };
}

/** The settings.set patch for a brand kit (only the three FROZEN keys). */
export function brandSettingsPatch(brand: BrandSettings): Record<string, string> {
  return {
    brandLogoPath: brand.brandLogoPath,
    brandCaptionTemplate: brand.brandCaptionTemplate,
    brandFontFamily: brand.brandFontFamily,
  };
}
