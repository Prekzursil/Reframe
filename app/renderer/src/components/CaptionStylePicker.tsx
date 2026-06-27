// CaptionStylePicker.tsx — selectable + PREVIEWABLE subtitle style templates (P4 §4).
//
// A swatch grid of the caption style templates (karaoke + the OpusClip-style
// premium looks + the libass classic + "no captions"). Each swatch renders a
// LIVE sample styled with that template's real palette/font/box/outline (the
// same `lib/captionTemplates` visuals the on-video overlay uses), so the user
// sees how a style looks BEFORE processing — and the selected style also drives
// the live overlay on the actual video frame.
//
// Controlled + presentational: the parent owns `value` and gets `onChange(id)`.
import React from 'react';
import { type CaptionTemplateVisual, captionVisualFor, isNoCaption } from '../lib/captionTemplates';
import { CAPTION_STYLES, type CaptionStyleOption } from '../features/shortMakerLogic';
import './captionStylePicker.css';

/** The CSS for a swatch's sample line, from the template visual (mirrors overlay). */
export function sampleStyle(visual: CaptionTemplateVisual): React.CSSProperties {
  return {
    fontFamily: visual.fontFamily,
    color: visual.activeColor,
    textTransform: visual.uppercase ? 'uppercase' : 'none',
    backgroundColor: visual.box ? visual.backgroundColor : 'transparent',
    WebkitTextStroke: visual.outline ? `0.6px ${visual.shadowColor}` : undefined,
    textShadow: visual.outline ? 'none' : `0 1px 2px ${visual.shadowColor}`,
  };
}

export interface CaptionStylePickerProps {
  /** The selected style id (parent-owned). */
  value: string;
  /** Called with the chosen style id. */
  onChange: (id: string) => void;
  /** The styles to show (defaults to the full caption catalog). */
  styles?: readonly CaptionStyleOption[];
  /** Accessible label for the group. */
  label?: string;
}

/** Sample caption text shown on each styled swatch. */
const SAMPLE_TEXT = 'Aa';

export function CaptionStylePicker({
  value,
  onChange,
  styles = CAPTION_STYLES,
  label = 'Caption style',
}: CaptionStylePickerProps): React.ReactElement {
  return (
    <div className="caption-style-picker" role="group" aria-label={label}>
      {styles.map((style) => {
        const active = style.id === value;
        const visual = captionVisualFor(style.id);
        return (
          <button
            key={style.id}
            type="button"
            className={`caption-style-swatch${active ? ' is-active' : ''}`}
            data-style={style.id}
            aria-pressed={active}
            onClick={() => onChange(style.id)}
          >
            <span className="caption-style-swatch__preview">
              {isNoCaption(style.id) ? (
                <span className="caption-style-swatch__none">No captions</span>
              ) : (
                <span className="caption-style-swatch__sample" style={sampleStyle(visual)}>
                  {SAMPLE_TEXT}
                </span>
              )}
            </span>
            <span className="caption-style-swatch__label">{style.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export default CaptionStylePicker;
