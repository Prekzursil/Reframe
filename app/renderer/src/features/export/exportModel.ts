// exportModel.ts — the PURE core of the Phase-5 Export screen (v1.5 §4).
//
// Export is the ONE irreversible, spend/file-writing action, so it is designed as
// a GUARDED COMMIT. This module holds the framework-free decisions that guard it —
// the recognizable per-platform destinations (NEVER codec/bitrate jargon), their
// availability against the clip length, the pre-flight summary the confirm step
// restates, and the roving-radiogroup keyboard math — so the React panels stay thin
// and every branch is unit-testable to 100% without a DOM.
//
// Division of labour (the naming fix, §4): Phase-5 "Export" renders/finishes ONE
// video (this module); the rail "Deliver" owns cross-video/batch publish. The
// aspect is COMPOSED upstream in Reframe — a destination here governs the length +
// loudness EXPECTATION and tags the output, it does not re-crop the frame.

import type { EditorState } from '../../lib/editorState';
import type { ConvertOptions } from '../../lib/rpc';
import { fmtSeconds } from '../_api';
import { formatDollars } from '../spendCapLogic';

/**
 * One recognizable delivery DESTINATION. Named by where the clip is going
 * (TikTok / Reels / Shorts…), implying its aspect + length — never a codec or
 * bitrate. `maxSec` is the platform's hard length limit (null = no cap).
 */
export interface PlatformPreset {
  /** Stable id (routing/selection key), never shown to the user. */
  id: string;
  /** The destination name shown to the user (e.g. "TikTok"). */
  name: string;
  /** One-line "what it's for" blurb. */
  blurb: string;
  /** The aspect the destination implies (e.g. "9:16") — display only. */
  aspect: string;
  /** The platform's hard length cap in seconds, or null when it has none. */
  maxSec: number | null;
  /** Human length expectation (e.g. "Up to 60 sec") — never a bitrate. */
  lengthHint: string;
}

/**
 * The curated destination set. Vertical shorts destinations lead (this is a
 * shorts-first app), then the tall feed post, the square post, and widescreen.
 * Together they span the four target aspects (9:16 / 4:5 / 1:1 / 16:9); the
 * uncapped 1:1 + 16:9 destinations guarantee at least one is always available.
 */
export const PLATFORM_PRESETS: readonly PlatformPreset[] = [
  {
    id: 'tiktok',
    name: 'TikTok',
    blurb: 'Vertical, sound-on, hook first.',
    aspect: '9:16',
    maxSec: 600,
    lengthHint: 'Up to 10 min',
  },
  {
    id: 'reels',
    name: 'Instagram Reels',
    blurb: 'Vertical, tightly cut for the feed.',
    aspect: '9:16',
    maxSec: 90,
    lengthHint: 'Up to 90 sec',
  },
  {
    id: 'shorts',
    name: 'YouTube Shorts',
    blurb: 'Vertical, hook first, under a minute.',
    aspect: '9:16',
    maxSec: 60,
    lengthHint: 'Up to 60 sec',
  },
  {
    id: 'feed',
    name: 'Instagram feed',
    blurb: 'Tall feed post that fills more screen.',
    aspect: '4:5',
    maxSec: null,
    lengthHint: 'Any length',
  },
  {
    id: 'square',
    name: 'Square post',
    blurb: 'One-to-one for a grid post.',
    aspect: '1:1',
    maxSec: null,
    lengthHint: 'Any length',
  },
  {
    id: 'widescreen',
    name: 'Widescreen',
    blurb: 'Landscape for the big screen.',
    aspect: '16:9',
    maxSec: null,
    lengthHint: 'Any length',
  },
];

/**
 * Canonical output canvas per curated aspect — the renderer-side MIRROR of the
 * sidecar registry (`sidecar/media_studio/features/aspect.py::ASPECT_PRESETS`).
 * 16:9 joined the curated set in the v1.5 aspect-matrix lane; before that the
 * sidecar's `require_supported_aspect` REJECTED it, so a 16:9 export preset could
 * not be persisted at all even though this catalog already showed the badge.
 *
 * Kept as a literal (not fetched) because it is display + planning data on the
 * synchronous render path; `ASPECT_DIMENSIONS covers every catalog aspect` in
 * exportModel.test.ts is the drift guard against the destination list, and
 * test_aspect.py pins the same four pairs on the sidecar side.
 */
export const ASPECT_DIMENSIONS: Readonly<Record<string, readonly [number, number]>> = {
  '9:16': [1080, 1920],
  '1:1': [1080, 1080],
  '4:5': [1080, 1350],
  '16:9': [1920, 1080],
};

/** One rendered target of a fan-out: a curated aspect and the canvas it fills. */
export interface AspectTarget {
  /** The canonical `"W:H"` aspect id. */
  aspect: string;
  /** Output width in pixels. */
  width: number;
  /** Output height in pixels. */
  height: number;
}

/** Resolve a preset by id, falling back to the first when the id is unknown. */
export function presetById(id: string): PlatformPreset {
  return PLATFORM_PRESETS.find((preset) => preset.id === id) ?? PLATFORM_PRESETS[0];
}

/**
 * Resolve destination ids to presets in CATALOG order (never click order), so a
 * fan-out plan and every label built from it read top-to-bottom exactly as the
 * matrix does. Unknown ids are dropped rather than faked into the first preset —
 * `presetById`'s fallback is right for a single selection, wrong for a set.
 */
export function presetsByIds(
  ids: readonly string[],
  presets: readonly PlatformPreset[] = PLATFORM_PRESETS,
): PlatformPreset[] {
  return presets.filter((preset) => ids.includes(preset.id));
}

/** A preset is selectable (`available`) or blocked with a stated `reason`. */
export type AvailabilityStatus = 'available' | 'unavailable';

/** A destination's availability against the current clip, with a plain reason. */
export interface PresetAvailability {
  status: AvailabilityStatus;
  /** Why it is blocked (plain language); '' when available. */
  reason: string;
}

/**
 * Decide whether a destination can take this clip. The only hard block is a clip
 * that runs LONGER than the platform's length cap — a real, honest constraint the
 * user must resolve (trim first) before the guarded commit. Uncapped destinations
 * (`maxSec === null`) are always available.
 */
export function presetAvailability(
  preset: PlatformPreset,
  durationSec: number,
): PresetAvailability {
  if (preset.maxSec !== null && durationSec > preset.maxSec) {
    return {
      status: 'unavailable',
      reason: `This clip runs longer than the ${fmtSeconds(preset.maxSec)} limit for ${preset.name} — trim it first.`,
    };
  }
  return { status: 'available', reason: '' };
}

/**
 * The first available destination id for a clip of this length (the default
 * selection), falling back to the list's first entry when none fit — so the
 * matrix always has a selection. `presets` is injectable for testing.
 */
export function firstAvailablePresetId(
  durationSec: number,
  presets: readonly PlatformPreset[] = PLATFORM_PRESETS,
): string {
  const found = presets.find(
    (preset) => presetAvailability(preset, durationSec).status === 'available',
  );
  return found ? found.id : presets[0].id;
}

/**
 * Multi-select toggle for the destination matrix. Adds an unselected id at the
 * END (order-preserving) and removes a selected one — EXCEPT when it is the last
 * one standing: the guarded commit has no meaning without a destination, so
 * un-checking the final box is a deliberate no-op rather than a state the
 * inspector would have to defend against downstream.
 */
export function togglePresetId(selected: readonly string[], id: string): string[] {
  if (!selected.includes(id)) return [...selected, id];
  if (selected.length === 1) return [...selected];
  return selected.filter((current) => current !== id);
}

/**
 * Re-validate a selection against the current clip length. A destination the clip
 * has outgrown (the user trimmed longer, or opened a longer video) is dropped so
 * the commit can never target a blocked platform; if that empties the set we fall
 * back to the first destination that DOES fit, preserving the ≥1 invariant.
 */
export function sanitizeSelection(
  selected: readonly string[],
  durationSec: number,
  presets: readonly PlatformPreset[] = PLATFORM_PRESETS,
): string[] {
  const kept = presetsByIds(selected, presets)
    .filter((preset) => presetAvailability(preset, durationSec).status === 'available')
    .map((preset) => preset.id);
  return kept.length > 0 ? kept : [firstAvailablePresetId(durationSec, presets)];
}

/**
 * The ONE-source -> N-aspect render matrix: one {@link AspectTarget} per DISTINCT
 * aspect across the chosen destinations, in catalog order.
 *
 * The dedupe is what makes a fan-out honest at the destination level — TikTok,
 * Reels and Shorts are three destinations but a single 9:16 render, so the plan
 * holds one entry and the caller writes one file. Mirrors the sidecar's
 * `aspect.fanout_plan`. A destination whose aspect has no canonical canvas is
 * skipped rather than guessed at, so an unmapped badge can never invent a canvas.
 */
export function aspectFanoutPlan(presets: readonly PlatformPreset[]): AspectTarget[] {
  const seen = new Set<string>();
  const plan: AspectTarget[] = [];
  for (const preset of presets) {
    const dims = ASPECT_DIMENSIONS[preset.aspect];
    if (!dims || seen.has(preset.aspect)) continue;
    seen.add(preset.aspect);
    plan.push({ aspect: preset.aspect, width: dims[0], height: dims[1] });
  }
  return plan;
}

/** "TikTok" / "TikTok + 2 more" — the destination phrase for buttons + headings. */
export function fanoutDestinationLabel(presets: readonly PlatformPreset[]): string {
  if (presets.length === 0) return 'your destinations';
  if (presets.length === 1) return presets[0].name;
  return `${presets[0].name} + ${presets.length - 1} more`;
}

/**
 * The destination file for ONE fan-out target: `<stem>.<aspect>.<ext>` alongside
 * the source, which is the location the sidecar's `_confined_output` permits by
 * default (`sidecar/media_studio/features/convert.py`).
 *
 * The aspect is slugged with an "x" (`9x16`), never a colon: ':' is a reserved
 * character in a Windows filename and `talk.9:16.mp4` would be parsed as an
 * alternate data stream on `talk.9`, silently producing no visible file. The
 * stem is split on the LAST separator first so a dotted DIRECTORY (`/a.b/talk`)
 * cannot be mistaken for an extension.
 */
export function fanoutOutPath(sourcePath: string, target: AspectTarget, ext = 'mp4'): string {
  const cut = Math.max(sourcePath.lastIndexOf('/'), sourcePath.lastIndexOf('\\'));
  const dir = sourcePath.slice(0, cut + 1);
  const name = sourcePath.slice(cut + 1);
  const dot = name.lastIndexOf('.');
  const stem = dot > 0 ? name.slice(0, dot) : name;
  return `${dir}${stem}.${target.aspect.replace(':', 'x')}.${ext}`;
}

/**
 * A rough LOCAL render-time estimate (seconds). A local h264 finish runs at a
 * fraction of real time; floored to a few seconds so a tiny clip never estimates
 * "0". Surfaced with a "~" so it always reads as an estimate, never a promise.
 */
export function estimateRenderSec(durationSec: number): number {
  return Math.max(3, Math.ceil(durationSec * 0.5));
}

/** The editor window length in seconds — clamped non-negative + finite. */
export function windowDurationSec(state: EditorState): number {
  const raw = state.video.window.end - state.video.window.start;
  return Number.isFinite(raw) ? Math.max(0, raw) : 0;
}

/** The pre-flight summary the confirm step restates before the guarded commit. */
export interface Preflight {
  /** Clips produced by this per-video export (always 1). */
  clipCount: number;
  /** The chosen destination's aspect (e.g. "9:16"). */
  aspect: string;
  /** The clip length in seconds. */
  durationSec: number;
  /** The clip length as M:SS. */
  durationLabel: string;
  /** The estimated render time as ~M:SS. */
  estRenderLabel: string;
  /** The estimated spend ($0.00 — a local render never spends). */
  estSpendLabel: string;
}

/**
 * Build the pre-flight summary from the shared editor state + the chosen
 * destination. A per-video export is always ONE clip; the duration is the editor
 * window (clamped non-negative + finite); the spend is $0 because the render is
 * LOCAL (never egresses).
 */
export function buildPreflight(state: EditorState, preset: PlatformPreset): Preflight {
  const durationSec = windowDurationSec(state);
  return {
    clipCount: 1,
    aspect: preset.aspect,
    durationSec,
    durationLabel: fmtSeconds(durationSec),
    estRenderLabel: `~${fmtSeconds(estimateRenderSec(durationSec))}`,
    estSpendLabel: formatDollars(0),
  };
}

/** The pre-flight summary for a MULTI-aspect fan-out of one source. */
export interface FanoutPreflight {
  /** Files this commit produces — one per DISTINCT aspect, not per destination. */
  clipCount: number;
  /** The render matrix (aspect + canvas) this commit will execute. */
  targets: readonly AspectTarget[];
  /** The aspects as one line ("9:16 · 1:1"); '' when nothing is selected. */
  aspectLabel: string;
  /** The clip length in seconds. */
  durationSec: number;
  /** The clip length as M:SS. */
  durationLabel: string;
  /** The estimated render time for the WHOLE fan-out as ~M:SS. */
  estRenderLabel: string;
  /** The estimated spend ($0.00 — a local render never spends). */
  estSpendLabel: string;
}

/**
 * Build the fan-out pre-flight the confirm step restates before the guarded
 * commit. `clipCount` counts DISTINCT ASPECTS, so picking three vertical
 * destinations honestly says "1 file" rather than inflating to three, and the
 * render estimate is the per-file estimate multiplied by that same count. An
 * empty selection reports 0 — it does not round up to a comforting 1.
 */
export function buildFanoutPreflight(
  state: EditorState,
  presets: readonly PlatformPreset[],
): FanoutPreflight {
  const durationSec = windowDurationSec(state);
  const targets = aspectFanoutPlan(presets);
  return {
    clipCount: targets.length,
    targets,
    aspectLabel: targets.map((target) => target.aspect).join(' · '),
    durationSec,
    durationLabel: fmtSeconds(durationSec),
    estRenderLabel: `~${fmtSeconds(estimateRenderSec(durationSec) * targets.length)}`,
    estSpendLabel: formatDollars(0),
  };
}

/**
 * Plain-language caption summary for the bake preview (never color-only).
 *
 * Counts the transcript's WORD-level cues, NOT rendered caption lines:
 * `captions.cues` emits one cue PER SPOKEN WORD (`lib/rpc/client.ts:298-299`,
 * sidecar `cues.py::word_cues`), and many words group into one on-screen line
 * (`sidecar/tests/test_caption_karaoke_flatten.py`). Hence "148 words", matching
 * `lib/directorHandoff.ts:107,119`, which reads the identical `state.cues.length`
 * off the same EditorState and calls it `wordCount`.
 */
export function captionSummary(state: EditorState): string {
  const count = state.cues.length;
  // The zero case stays phrased in CAPTION terms on purpose: "no cues" really does
  // mean "no captions", and it reads better than "No words". Do NOT "tidy" this to
  // match the plural branch — it is a deliberate split, not an oversight.
  if (count === 0) return 'No captions';
  return `${count} word${count === 1 ? '' : 's'}`;
}

/**
 * Plain-language framing summary. The presence of a crop plan (Reframe-owned)
 * means the clip was reframed; the raw engine id is NEVER surfaced (it is a model
 * codename — the no-jargon rule), only the human "Reframed" vs "Original framing".
 */
export function framingSummary(state: EditorState): string {
  return state.cropPlan ? 'Reframed' : 'Original framing';
}

/** The single, universal share-ready render profile (mp4/h264 — never shown). */
export function exportConvertOptions(): ConvertOptions {
  return {
    container: 'mp4',
    vcodec: 'libx264',
    acodec: 'aac',
    scale: '',
    fps: '',
    crf: '20',
    audioOnly: false,
    audioFormat: 'mp3',
  };
}

/**
 * Roving-tabindex math for the destination RADIOGROUP (WAI-ARIA). Arrow keys move
 * the selection to the next/previous SELECTABLE destination (wrapping, skipping
 * unavailable ones); Home/End jump to the first/last selectable; any other key
 * leaves the selection where it is. Returns the next selected index.
 */
export function rovingIndex(key: string, current: number, selectable: readonly boolean[]): number {
  const n = selectable.length;
  if (n === 0) return current;
  const scan = (from: number, step: number): number => {
    for (let i = 0; i < n; i += 1) {
      const idx = (((from + i * step) % n) + n) % n;
      if (selectable[idx]) return idx;
    }
    return current;
  };
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return scan(current + 1, 1);
    case 'ArrowLeft':
    case 'ArrowUp':
      return scan(current - 1, -1);
    case 'Home':
      return scan(0, 1);
    case 'End':
      return scan(n - 1, -1);
    default:
      return current;
  }
}
