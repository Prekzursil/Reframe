// CaptionDesigner.tsx — the caption EDITOR with live preview on a real frame (P4 §4).
//
// Brings the position editor (CaptionBox) and the style picker
// (CaptionStylePicker) together over a real video frame (Player), so the user
// designs exactly how captions look AND where they sit before processing:
//   * the Player plays the candidate's window (a real frame, not a mock);
//   * the CaptionBox draws a draggable/resizable caption region over it, with a
//     LIVE word-highlighted sample (the same activeLine/word-colour math the
//     export overlay uses) rendered INSIDE the box at the chosen style;
//   * quick band buttons (Top/Center/Bottom) re-seat the box to a template band;
//   * the CaptionStylePicker swaps the look, previewed both as swatches and on
//     the actual video.
//
// Controlled: the parent owns the CaptionDesign and gets onChange.
import React, { useState } from 'react';
import { Player, type PlayerWindow } from './Player';
import { CaptionBox } from './CaptionBox';
import { CaptionStylePicker } from './CaptionStylePicker';
import { CaptionCustomizer } from './CaptionCustomizer';
import { activeLine, wordColor } from './CaptionOverlay';
import { isNoCaption } from '../lib/captionTemplates';
import { isKaraokeStyle, karaokeActiveColor } from '../lib/captionKaraokePreset';
import { captionSampleStyle, previewSizeScale, previewVisual } from '../lib/captionOverridePreview';
import { type CaptionBand, bandBox, boxBand } from '../lib/captionPosition';
import type { CaptionContentContext } from '../lib/captionDefaults';
import type { CaptionDesign } from '../lib/captionDesign';
import type { CaptionStyleOption } from '../features/shortMakerLogic';
import type { Cue } from '../lib/rpc';
import './captionDesigner.css';

export interface CaptionDesignerProps {
  /** Library video id for the preview frame. */
  videoId?: string;
  /** Direct src override (wins over videoId). */
  src?: string;
  /** The candidate's source-absolute preview window. */
  window: PlayerWindow;
  /** Word-level caption cues (source-absolute seconds). */
  cues: Cue[];
  /** The current caption design (parent-owned). */
  design: CaptionDesign;
  /** Called with the next design on style/position change. */
  onChange: (design: CaptionDesign) => void;
  /** Optional hook headline shown above the caption sample. */
  hookTitle?: string;
  /** Override the style catalog (defaults to the full set). */
  styles?: readonly CaptionStyleOption[];
  /** Project content context for the per-language reading-speed default (WU S4). */
  content?: CaptionContentContext;
}

const BANDS: readonly { id: CaptionBand; label: string }[] = [
  { id: 'top', label: 'Top' },
  { id: 'center', label: 'Center' },
  { id: 'bottom', label: 'Bottom' },
];

export function CaptionDesigner({
  videoId,
  src,
  window: win,
  cues,
  design,
  onChange,
  hookTitle,
  styles,
  content,
}: CaptionDesignerProps): React.ReactElement {
  const [currentTime, setCurrentTime] = useState(win.start);

  const visual = previewVisual(design.style, design.override);
  const scale = previewSizeScale(design.override);
  const lineStyle = captionSampleStyle(visual, scale);
  const none = isNoCaption(design.style);
  // V1.1 WU SP1: the karaoke preset alternates the active word accent per word.
  const karaoke = isKaraokeStyle(design.style);
  const words = none ? [] : activeLine(cues, win, currentTime - win.start);
  const band = boxBand(design.box);
  const title = (hookTitle ?? '').trim();

  return (
    <div className="caption-designer" aria-label="Caption editor">
      <div className="caption-designer__phone">
        <Player videoId={videoId} src={src} window={win} controls onTimeUpdate={setCurrentTime} />
        <CaptionBox box={design.box} onChange={(box) => onChange({ ...design, box })}>
          <div className="caption-designer__sample" data-style={design.style}>
            {title && (
              <div
                className="caption-designer__hook"
                style={{ fontFamily: visual.fontFamily, color: visual.textColor }}
              >
                {title}
              </div>
            )}
            {none ? (
              <span className="caption-designer__hint">No captions</span>
            ) : words.length > 0 ? (
              <span className="caption-designer__line" style={lineStyle}>
                {words.map((w, i) => (
                  <span
                    key={`${w.text}-${w.start}-${i}`}
                    style={{
                      // Alternate the karaoke accent by the word's ABSOLUTE cue
                      // index (w.index), NOT its line-local position `i`, mirroring
                      // CaptionOverlay + the libass burn so the preview parity holds
                      // even when the on-screen phrase starts at an odd index.
                      color: wordColor(w, visual, karaoke ? karaokeActiveColor(w.index) : undefined),
                      backgroundColor: w.active ? visual.activeBackground : 'transparent',
                    }}
                  >
                    {w.text}
                  </span>
                ))}
              </span>
            ) : (
              <span
                className="caption-designer__hint"
                style={{ fontFamily: visual.fontFamily, fontSize: `${scale}em` }}
              >
                Caption preview
              </span>
            )}
          </div>
        </CaptionBox>
      </div>

      <div className="caption-designer__bands" role="group" aria-label="Caption band">
        {BANDS.map((b) => (
          <button
            key={b.id}
            type="button"
            className={`caption-designer__band${band === b.id ? ' is-active' : ''}`}
            aria-pressed={band === b.id}
            onClick={() => onChange({ ...design, box: bandBox(b.id) })}
          >
            {b.label}
          </button>
        ))}
      </div>

      <CaptionStylePicker
        value={design.style}
        styles={styles}
        onChange={(style) => onChange({ ...design, style })}
      />

      <CaptionCustomizer
        value={design.override}
        onChange={(override) => onChange({ ...design, override })}
        content={content}
        style={design.style}
      />
    </div>
  );
}

export default CaptionDesigner;
