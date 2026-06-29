// CaptionOverlay.tsx — the LIVE HTML/CSS caption overlay (P4 §5).
//
// A fast approximation of the exported caption look so the ShortMaker preview
// can show "how they'd look" as the candidate plays. This is NOT a Remotion
// render — the export still goes through Remotion/libass; the overlay just
// mirrors the selected template's palette/font/position so the reviewer can
// pick a style live.
//
// Contract (P4 §5 / C3):
//   * cues are WORD-level, SOURCE-absolute seconds (captions.cues output); the
//     overlay re-bases them to the preview window by subtracting `window.start`.
//   * `currentTime` is the Player's SOURCE-absolute playhead (its onTimeUpdate).
//   * styling comes from `lib/captionTemplates.ts[templateId]` (palette / font /
//     position / uppercase / box / outline + word-highlight via cue timing).
//   * the overlay NO-OPS on templateId 'none' (and renders nothing when there is
//     no active caption text).
//   * `hookTitle` renders in a dedicated slot (when provided).
//
// Pure render given props (no rpc, no effects). The cue-selection + re-basing +
// word-highlight math is exported as pure functions, unit-tested in
// CaptionOverlay.test.tsx.

import React from 'react';
import './captionOverlay.css';
import { captionVisualFor, isNoCaption, type CaptionTemplateVisual } from '../lib/captionTemplates';
import { isKaraokeStyle, karaokeActiveColor } from '../lib/captionKaraokePreset';
import type { Cue } from '../lib/rpc';
import type { PlayerWindow } from './Player';

/**
 * Tolerance (seconds) when grouping words into the active line: word cues from
 * the same spoken phrase are usually back-to-back, so a small gap still keeps
 * them on one line. Mirrors the Player's coarse timeupdate cadence.
 */
export const LINE_GAP_SEC = 0.8;

/** A word on the active caption line, with its highlight state at `t`. */
export interface OverlayWord {
  text: string;
  /** Window-relative start (source start minus window.start). */
  start: number;
  /** Window-relative end. */
  end: number;
  /** True for the word being spoken at the current time. */
  active: boolean;
  /** True for words already spoken (karaoke fill). */
  spoken: boolean;
}

/**
 * Re-base a source-absolute cue onto the preview window: subtract `window.start`
 * so t=0 is the window's in-point (P4 §5). Returns null for cues that fall
 * entirely OUTSIDE the window (they could never display in this preview).
 */
export function rebaseCue(cue: Cue, window: PlayerWindow): { start: number; end: number } | null {
  const start = cue.start - window.start;
  const end = cue.end - window.start;
  const span = window.end - window.start;
  if (end <= 0 || start >= span) return null;
  return { start, end };
}

/**
 * The active word cue at window-relative time `t`: the cue whose [start, end)
 * contains `t`. When between words, the most recently-ended cue is "active" so
 * the line stays visible through the natural micro-gaps in word timing. Returns
 * -1 when no cue has started yet.
 */
export function activeCueIndex(rebased: { start: number; end: number }[], t: number): number {
  let candidate = -1;
  for (let i = 0; i < rebased.length; i += 1) {
    const c = rebased[i];
    if (t >= c.start && t < c.end) return i;
    if (t >= c.end) candidate = i; // most recent ended word — keep the line up
  }
  return candidate;
}

/**
 * Build the active caption LINE at window-relative time `t`: the run of word
 * cues around the active word that are within `LINE_GAP_SEC` of each other (a
 * spoken phrase). Empty array when nothing is active (overlay shows no line).
 */
export function activeLine(
  cues: Cue[],
  window: PlayerWindow,
  t: number,
  gap: number = LINE_GAP_SEC,
): OverlayWord[] {
  const kept: { cue: Cue; start: number; end: number }[] = [];
  for (const cue of cues) {
    const r = rebaseCue(cue, window);
    if (r) kept.push({ cue, start: r.start, end: r.end });
  }
  if (kept.length === 0) return [];
  const idx = activeCueIndex(
    kept.map((k) => ({ start: k.start, end: k.end })),
    t,
  );
  if (idx === -1) return [];

  // Grow a window of words around `idx` while consecutive words stay within gap.
  let lo = idx;
  let hi = idx;
  while (lo > 0 && kept[lo].start - kept[lo - 1].end <= gap) lo -= 1;
  while (hi < kept.length - 1 && kept[hi + 1].start - kept[hi].end <= gap) hi += 1;

  const line: OverlayWord[] = [];
  for (let i = lo; i <= hi; i += 1) {
    const k = kept[i];
    line.push({
      text: k.cue.text,
      start: k.start,
      end: k.end,
      active: t >= k.start && t < k.end,
      spoken: t >= k.end,
    });
  }
  return line;
}

/** Map a template position to CSS placement for the absolutely-positioned line. */
function positionStyle(position: CaptionTemplateVisual['position']): React.CSSProperties {
  switch (position) {
    case 'top':
      return { top: '8%', bottom: 'auto' };
    case 'center':
      return { top: '50%', bottom: 'auto', transform: 'translateY(-50%)' };
    case 'bottom':
    default:
      return { bottom: '14%', top: 'auto' };
  }
}

/**
 * Per-word colour given its highlight state + the template palette.
 *
 * `activeColorOverride` (V1.1 WU SP1) lets the karaoke preset paint the ACTIVE
 * word with its alternating yellow/green accent instead of the static
 * `visual.activeColor`; absent, the template's own active colour is used.
 */
export function wordColor(
  word: OverlayWord,
  visual: CaptionTemplateVisual,
  activeColorOverride?: string,
): string {
  if (word.active) return activeColorOverride ?? visual.activeColor;
  if (word.spoken) return visual.spokenColor || visual.textColor;
  return visual.textColor;
}

export interface CaptionOverlayProps {
  cues: Cue[];
  templateId: string;
  /** Player playhead in SOURCE-absolute seconds (its onTimeUpdate). */
  currentTime: number;
  /** Optional hook/title text shown in its own slot. */
  hookTitle?: string;
  /** The preview window (source-absolute) the cues re-base against. */
  window: PlayerWindow;
}

/**
 * The live caption overlay. Renders nothing for the `none` template; otherwise
 * the active caption line (word-highlighted) styled per the selected template,
 * plus the hook-title slot when provided.
 */
export function CaptionOverlay({
  cues,
  templateId,
  currentTime,
  hookTitle,
  window: win,
}: CaptionOverlayProps): React.JSX.Element | null {
  if (isNoCaption(templateId)) return null;

  const visual = captionVisualFor(templateId);
  // V1.1 WU SP1: the karaoke preset alternates the ACTIVE word's accent
  // (yellow/green) per word, mirroring the libass burn's alternation.
  const karaoke = isKaraokeStyle(templateId);
  const t = currentTime - win.start;
  const words = activeLine(cues, win, t);
  const title = (hookTitle ?? '').trim();

  // Nothing to show (no active line + no hook) — render nothing so the overlay
  // does not paint an empty card.
  if (words.length === 0 && !title) return null;

  const lineStyle: React.CSSProperties = {
    ...positionStyle(visual.position),
    fontFamily: visual.fontFamily,
    textTransform: visual.uppercase ? 'uppercase' : 'none',
    backgroundColor: visual.box ? visual.backgroundColor : 'transparent',
    textShadow: visual.outline
      ? `0 0 2px ${visual.shadowColor}, 0 0 4px ${visual.shadowColor}, 2px 2px 0 ${visual.shadowColor}`
      : `0 2px 6px ${visual.shadowColor}`,
    WebkitTextStroke: visual.outline ? `1.5px ${visual.shadowColor}` : undefined,
  };

  return (
    <div
      className="caption-overlay"
      aria-hidden="true"
      data-template={templateId}
      data-position={visual.position}
    >
      {title && (
        <div
          className="caption-overlay__hook"
          data-hook-title="true"
          style={{ fontFamily: visual.fontFamily, color: visual.textColor }}
        >
          {title}
        </div>
      )}
      {words.length > 0 && (
        <div className="caption-overlay__line" data-template={templateId} style={lineStyle}>
          {words.map((w, i) => (
            <span
              key={`${w.text}-${w.start}-${i}`}
              className={
                'caption-overlay__word' +
                (w.active ? ' is-active' : '') +
                (w.spoken ? ' is-spoken' : '')
              }
              style={{
                color: wordColor(w, visual, karaoke ? karaokeActiveColor(i) : undefined),
                backgroundColor: w.active ? visual.activeBackground : 'transparent',
              }}
            >
              {w.text}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default CaptionOverlay;
