// outputOptions.ts — pure model for the Output Tray's delivery options (P4 §h).
//
// Consolidates the "how do I get my subtitles + which files do I keep" choices
// the Output Tray exposes after any primary action (Make Shorts / Edit /
// Director). Kept pure (no React) so the permutations are exhaustively unit
// tested and the same resolver feeds the export payload + the human summary.
//
// Subtitle DELIVERY is a single mode (you can't both burn AND soft-mux the same
// pass); the three SAVE intents are independent booleans, so every combination
// of {clip, short, srt} is expressible. The sidecar mirrors `resolveBurn` /
// `writesSubtitleFile` server-side when it runs the export.

/** How subtitles are delivered with the exported video. */
export type SubtitleMode = 'burn' | 'softmux' | 'sidecar' | 'none';

/** Delivery modes in display order. */
export const SUBTITLE_MODES: readonly SubtitleMode[] = ['burn', 'softmux', 'sidecar', 'none'];

/** Friendly label + one-line help for each delivery mode (UI copy). */
export const SUBTITLE_MODE_META: Record<SubtitleMode, { label: string; help: string }> = {
  burn: { label: 'Burn in', help: 'Captions are baked into the video pixels (always visible).' },
  softmux: {
    label: 'Soft track',
    help: 'Captions are a selectable subtitle track inside the video file.',
  },
  sidecar: {
    label: 'Separate file',
    help: 'Captions are written as a separate subtitle file next to the video.',
  },
  none: { label: 'No captions', help: 'Export the video with no captions at all.' },
};

/** The Output Tray's delivery + save selection. */
export interface OutputOptions {
  /** How subtitles ride the exported video. */
  subtitleMode: SubtitleMode;
  /** Keep the edited/source clip (the cut). */
  saveClip: boolean;
  /** Keep the produced short. */
  saveShort: boolean;
  /** Write the .srt subtitle file separately. */
  saveSrt: boolean;
}

/** Quality-ON default (G-4): burn captions, keep the short. */
export const DEFAULT_OUTPUT_OPTIONS: OutputOptions = {
  subtitleMode: 'burn',
  saveClip: false,
  saveShort: true,
  saveSrt: false,
};

/** True when subtitles are hard-burned into the pixels. */
export function resolveBurn(mode: SubtitleMode): boolean {
  return mode === 'burn';
}

/** True when subtitles appear IN the exported video (burned or soft track). */
export function embedsSubtitles(mode: SubtitleMode): boolean {
  return mode === 'burn' || mode === 'softmux';
}

/**
 * True when a standalone subtitle FILE must be produced: explicitly as the
 * sidecar delivery, OR because the user asked to save the SRT separately. (Burn
 * + soft-mux still need an intermediate subtitle build, but only this set keeps
 * the file as a deliverable.)
 */
export function writesSubtitleFile(options: OutputOptions): boolean {
  return options.subtitleMode === 'sidecar' || options.saveSrt;
}

/** A known subtitle mode, or the default for anything else. */
export function coerceSubtitleMode(raw: unknown): SubtitleMode {
  const v = typeof raw === 'string' ? raw.trim().toLowerCase() : '';
  return (SUBTITLE_MODES as readonly string[]).includes(v)
    ? (v as SubtitleMode)
    : DEFAULT_OUTPUT_OPTIONS.subtitleMode;
}

/** A real boolean, or `fallback` (for persisted/untrusted values). */
function boolOr(v: unknown, fallback: boolean): boolean {
  return typeof v === 'boolean' ? v : fallback;
}

/** Validate raw (persisted/untrusted) options into a clean OutputOptions. */
export function sanitizeOutputOptions(
  raw: Partial<OutputOptions> | null | undefined,
): OutputOptions {
  const r = raw ?? {};
  return {
    subtitleMode: coerceSubtitleMode(r.subtitleMode),
    saveClip: boolOr(r.saveClip, DEFAULT_OUTPUT_OPTIONS.saveClip),
    saveShort: boolOr(r.saveShort, DEFAULT_OUTPUT_OPTIONS.saveShort),
    saveSrt: boolOr(r.saveSrt, DEFAULT_OUTPUT_OPTIONS.saveSrt),
  };
}

/** The set of artifacts a given selection produces (stable order). */
export function outputArtifacts(options: OutputOptions): string[] {
  const out: string[] = [];
  if (options.saveClip) out.push('clip');
  if (options.saveShort) out.push('short');
  if (writesSubtitleFile(options)) out.push('srt');
  return out;
}

/** True when at least one deliverable will be produced (gates the Save action). */
export function hasOutput(options: OutputOptions): boolean {
  return outputArtifacts(options).length > 0;
}

/** A short human summary of the selection (UI acknowledgement + a11y). */
export function describeOutputs(options: OutputOptions): string {
  const artifacts = outputArtifacts(options);
  if (artifacts.length === 0) return 'Nothing selected to save.';
  const names: Record<string, string> = { clip: 'cut', short: 'short', srt: 'SRT' };
  const list = artifacts.map((a) => names[a]).join(', ');
  const sub = SUBTITLE_MODE_META[options.subtitleMode].label.toLowerCase();
  return `Save ${list} (captions: ${sub}).`;
}
