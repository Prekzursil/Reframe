// CaptionGallery.tsx — the template-preset gallery (v1.5 Caption pilot, §4).
//
// The redesign rejects the prototype's cramped 320px style column: Caption's
// density needs a preset gallery that EXPANDS over the timeline. This is that
// gallery — a browse affordance that opens a wide, grouped grid of live style
// previews. Every style is named by its LOOK (captionStyleNames), grouped by its
// layout/behaviour FAMILY, and previewed with the SAME `sampleStyle` the shipped
// picker/overlay use (composition, not a rewrite).
//
// One-accent GUARD: this is the surface most likely to sprout a decorative second
// hue. It does not. Styles are told apart by their family SECTIONS + their own
// caption palettes (that is the caption's look, i.e. content — not app chrome);
// the only app-chrome accent is the amber selection ring (`is-active`). No new
// chrome hue is introduced.
//
// Controlled + presentational: the parent owns `value` and gets `onChange(id)`.

import React, { useState } from 'react';
import { sampleStyle } from '../../components/CaptionStylePicker';
import { captionVisualFor, isNoCaption } from '../../lib/captionTemplates';
import {
  type LookStyleOption,
  groupByFamily,
  lookNamedCatalog,
  styleLook,
} from '../../lib/captionStyleNames';
import './captionGallery.css';

/** Sample text shown on each styled swatch. */
const SAMPLE_TEXT = 'Aa';

export interface CaptionGalleryProps {
  /** The selected style id (parent-owned). */
  value: string;
  /** Called with the chosen style id. */
  onChange: (id: string) => void;
  /** Override the look catalog (defaults to the full look-named catalog). */
  catalog?: readonly LookStyleOption[];
}

export function CaptionGallery({
  value,
  onChange,
  catalog = lookNamedCatalog(),
}: CaptionGalleryProps): React.ReactElement {
  const [expanded, setExpanded] = useState(false);
  const groups = groupByFamily(catalog);
  const active = styleLook(value);

  return (
    <section className="caption-gallery" aria-label="Caption style gallery">
      <div className="caption-gallery__bar">
        <span className="caption-gallery__label">Style</span>
        <span className="caption-gallery__current">{active.name}</span>
        <button
          type="button"
          className="caption-gallery__toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? 'Done' : 'Browse styles'}
        </button>
      </div>

      {expanded && (
        <div className="caption-gallery__grid" role="radiogroup" aria-label="Caption styles">
          {groups.map((group) => (
            <section key={group.family} className="caption-gallery__group" aria-label={group.label}>
              <h4 className="caption-gallery__group-title">{group.label}</h4>
              <div className="caption-gallery__swatches">
                {group.options.map((option) => {
                  const selected = option.id === value;
                  const visual = captionVisualFor(option.id);
                  return (
                    <button
                      key={option.id}
                      type="button"
                      className={`caption-gallery__swatch${selected ? ' is-active' : ''}`}
                      data-style={option.id}
                      role="radio"
                      aria-checked={selected}
                      onClick={() => onChange(option.id)}
                    >
                      <span className="caption-gallery__preview">
                        {isNoCaption(option.id) ? (
                          <span className="caption-gallery__off">Off</span>
                        ) : (
                          <span className="caption-gallery__sample" style={sampleStyle(visual)}>
                            {SAMPLE_TEXT}
                          </span>
                        )}
                      </span>
                      <span className="caption-gallery__name">{option.label}</span>
                      <span className="caption-gallery__blurb">{option.blurb}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

export default CaptionGallery;
