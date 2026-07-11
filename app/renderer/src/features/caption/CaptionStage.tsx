// CaptionStage.tsx — the SHARED editor stage (v1.5 Caption pilot).
//
// The one video surface every panel talks about. It reads the shared editor
// state (`useEditor`) and renders the live caption exactly as it will export —
// via the pure `captionOverridePreview` mirror (previewVisual/previewSizeScale/
// captionSampleStyle) + the CaptionOverlay word math (activeLine/wordColor) — so
// the Inspector's style/override edits and the Timeline's playhead all reflect
// here immediately, without the Stage owning any of those controls. Direct
// manipulation of the caption REGION lives here (the keyboard-operable
// CaptionBox), while style/text controls live in the Inspector — the
// inspector-over-shared-stage split the pilot proves.
//
// Motion: the karaoke word "pop" preview is gated behind prefers-reduced-motion
// (via the shared `prefersReducedMotion` helper) with a STATIC fallback — the CSS
// animation only arms when `data-karaoke-pop` is set.

import React from 'react';
import { Player } from '../../components/Player';
import { CaptionBox } from '../../components/CaptionBox';
import { activeLine, wordColor } from '../../components/CaptionOverlay';
import { prefersReducedMotion } from '../../components/UsageBar';
import { isNoCaption } from '../../lib/captionTemplates';
import { isKaraokeStyle, karaokeActiveColor } from '../../lib/captionKaraokePreset';
import {
  captionSampleStyle,
  previewSizeScale,
  previewVisual,
} from '../../lib/captionOverridePreview';
import { useEditor } from '../EditorContext';
import './captionStage.css';

/** The shared caption stage: live preview + on-canvas caption-region editing. */
export function CaptionStage(): React.ReactElement {
  const { state, dispatch } = useEditor();
  const { video, cues, design, playhead } = state;
  const win = video.window;

  const visual = previewVisual(design.style, design.override);
  const scale = previewSizeScale(design.override);
  const lineStyle = captionSampleStyle(visual, scale);
  const none = isNoCaption(design.style);
  const karaoke = isKaraokeStyle(design.style);
  const words = none ? [] : activeLine(cues, win, playhead - win.start);
  // The word "pop" animation arms only for the karaoke look AND when the user
  // has NOT asked for reduced motion; otherwise the active word stays static.
  const pop = karaoke && !prefersReducedMotion();

  return (
    <div className="caption-stage" aria-label="Caption stage">
      <div className="caption-stage__frame">
        <Player
          videoId={video.videoId}
          src={video.src}
          window={win}
          controls
          onTimeUpdate={(t) => dispatch({ type: 'setPlayhead', playhead: t })}
        />
        <CaptionBox box={design.box} onChange={(box) => dispatch({ type: 'setBox', box })}>
          <div
            className="caption-stage__sample"
            data-style={design.style}
            data-karaoke-pop={pop || undefined}
          >
            {none ? (
              <span className="caption-stage__hint">No captions</span>
            ) : words.length > 0 ? (
              <span className="caption-stage__line" style={lineStyle}>
                {words.map((w, i) => (
                  <span
                    key={`${w.text}-${w.start}-${i}`}
                    className={`caption-stage__word${w.active ? ' is-active' : ''}`}
                    style={{
                      color: wordColor(
                        w,
                        visual,
                        karaoke ? karaokeActiveColor(w.index) : undefined,
                      ),
                      backgroundColor: w.active ? visual.activeBackground : 'transparent',
                    }}
                  >
                    {w.text}
                  </span>
                ))}
              </span>
            ) : (
              <span
                className="caption-stage__hint"
                style={{ fontFamily: visual.fontFamily, fontSize: `${scale}em` }}
              >
                Caption preview
              </span>
            )}
          </div>
        </CaptionBox>
      </div>
    </div>
  );
}

export default CaptionStage;
