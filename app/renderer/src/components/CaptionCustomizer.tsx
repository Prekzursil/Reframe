// CaptionCustomizer.tsx — the T2 "Customize…" disclosure (V1.1 Lane 1, WU S3).
//
// A progressive-disclosure panel (collapsed by default; NN/g progressive
// disclosure) that lets a prosumer tune the chosen caption template WITHIN its
// bounds — without ever leaving the novice-first path. It edits a single
// CaptionOverride (WU S1) and emits it through `onChange`; the CaptionDesigner
// reuses the same override to update its LIVE preview on every change.
//
// "Mostly dropdowns, almost no typing" (V1-GRILL §e): font is a dropdown, size +
// reading-speed are sliders, the booleans are checkboxes, and — per the GATE
// requirement — COLOURS are a swatch grid + native <input type=color> presets,
// with NO hex text field on the primary path. Every edit is funnelled through
// `sanitizeCaptionOverride` so the emitted patch is always valid (and collapses
// to `undefined` when nothing non-default remains).
//
// Controlled + presentational: the parent owns `value` and gets `onChange`.
import React, { useId, useState } from 'react';
import {
  type CaptionMaxLines,
  type CaptionOverride,
  type CaptionPositionBand,
  CURATED_CAPTION_FONTS,
  MAX_CPS_MAX,
  MAX_CPS_MIN,
  SIZE_SCALE_MAX,
  SIZE_SCALE_MIN,
  sanitizeCaptionOverride,
} from '../lib/captionOverride';
import './captionCustomizer.css';

/** The colour presets shown in the swatch grid (text/active/spoken share them). */
const COLOR_PRESETS: readonly string[] = [
  '#FFFFFF',
  '#000000',
  '#FFD700',
  '#FE2C55',
  '#22E84F',
  '#00E5FF',
  '#FF00E5',
  '#9B5DE5',
];

/** The coarse vertical bands offered in the position dropdown. */
const BANDS: readonly { id: CaptionPositionBand; label: string }[] = [
  { id: 'top', label: 'Top' },
  { id: 'center', label: 'Center' },
  { id: 'bottom', label: 'Bottom' },
];

/** Slider neutral positions shown when the field is unset (identity / safe default). */
const NEUTRAL_SIZE = 1;
const NEUTRAL_CPS = 17;
const SIZE_STEP = 0.05;
const CPS_STEP = 1;

/** The three colour slots the override tunes, with their group labels. */
type ColorKey = 'textColor' | 'activeColor' | 'spokenColor';
const COLOR_SLOTS: readonly { key: ColorKey; label: string }[] = [
  { key: 'textColor', label: 'Text colour' },
  { key: 'activeColor', label: 'Active word colour' },
  { key: 'spokenColor', label: 'Spoken word colour' },
];

export interface CaptionCustomizerProps {
  /** The current override (parent-owned); `undefined` = pure template defaults. */
  value: CaptionOverride | undefined;
  /** Called with the next (validated) override, or `undefined` when cleared. */
  onChange: (next: CaptionOverride | undefined) => void;
  /** Disclosure label (default "Customize…"). */
  label?: string;
}

export function CaptionCustomizer({
  value,
  onChange,
  label = 'Customize…',
}: CaptionCustomizerProps): React.ReactElement {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const ov: CaptionOverride = value ?? {};

  /** Set (or clear, when `v === undefined`) one override field, then re-validate. */
  function set<K extends keyof CaptionOverride>(key: K, v: CaptionOverride[K] | undefined): void {
    const next: CaptionOverride = { ...ov };
    if (v === undefined) delete next[key];
    else next[key] = v;
    onChange(sanitizeCaptionOverride(next));
  }

  return (
    <div className="caption-customizer">
      <button
        type="button"
        className="caption-customizer__toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        {label}
      </button>

      {open && (
        <div id={panelId} className="caption-customizer__panel">
          <label className="caption-customizer__field caption-customizer__font">
            <span>Font</span>
            <select
              value={ov.fontFamily ?? ''}
              onChange={(e) => set('fontFamily', e.target.value === '' ? undefined : e.target.value)}
            >
              <option value="">Default</option>
              {CURATED_CAPTION_FONTS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>

          <label className="caption-customizer__field caption-customizer__size">
            <span>Size</span>
            <input
              type="range"
              min={SIZE_SCALE_MIN}
              max={SIZE_SCALE_MAX}
              step={SIZE_STEP}
              value={ov.sizeScale ?? NEUTRAL_SIZE}
              onChange={(e) => set('sizeScale', Number(e.target.value))}
            />
          </label>

          {COLOR_SLOTS.map(({ key, label: slotLabel }) => {
            const current = ov[key];
            return (
              <div
                key={key}
                className="caption-customizer__field caption-customizer__color"
                role="group"
                aria-label={slotLabel}
              >
                <span>{slotLabel}</span>
                <div className="caption-customizer__swatches">
                  {COLOR_PRESETS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className={`caption-customizer__swatch${current === c ? ' is-active' : ''}`}
                      data-color={c}
                      style={{ backgroundColor: c }}
                      aria-label={`${slotLabel} ${c}`}
                      aria-pressed={current === c}
                      onClick={() => set(key, c)}
                    />
                  ))}
                  <input
                    type="color"
                    aria-label={`${slotLabel} custom`}
                    value={current ?? '#FFFFFF'}
                    onChange={(e) => set(key, e.target.value.toUpperCase())}
                  />
                </div>
              </div>
            );
          })}

          <label className="caption-customizer__toggle-field caption-customizer__bool-outline">
            <input
              type="checkbox"
              checked={ov.outline ?? false}
              onChange={(e) => set('outline', e.target.checked)}
            />
            <span>Outline</span>
          </label>

          <label className="caption-customizer__toggle-field caption-customizer__bool-card">
            <input
              type="checkbox"
              checked={ov.box ?? false}
              onChange={(e) => set('box', e.target.checked)}
            />
            <span>Card</span>
          </label>

          <label className="caption-customizer__toggle-field caption-customizer__bool-uppercase">
            <input
              type="checkbox"
              checked={ov.uppercase ?? false}
              onChange={(e) => set('uppercase', e.target.checked)}
            />
            <span>UPPERCASE</span>
          </label>

          <label className="caption-customizer__field caption-customizer__band">
            <span>Position</span>
            <select
              value={ov.positionBand ?? ''}
              onChange={(e) =>
                set(
                  'positionBand',
                  e.target.value === '' ? undefined : (e.target.value as CaptionPositionBand),
                )
              }
            >
              <option value="">Default</option>
              {BANDS.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.label}
                </option>
              ))}
            </select>
          </label>

          <label className="caption-customizer__field caption-customizer__lines">
            <span>Max lines</span>
            <select
              value={ov.maxLines ?? ''}
              onChange={(e) =>
                set(
                  'maxLines',
                  e.target.value === '' ? undefined : (Number(e.target.value) as CaptionMaxLines),
                )
              }
            >
              <option value="">Default</option>
              <option value="1">1 line</option>
              <option value="2">2 lines</option>
            </select>
          </label>

          <label className="caption-customizer__field caption-customizer__cps">
            <span>Reading speed</span>
            <input
              type="range"
              min={MAX_CPS_MIN}
              max={MAX_CPS_MAX}
              step={CPS_STEP}
              value={ov.maxCps ?? NEUTRAL_CPS}
              onChange={(e) => set('maxCps', Number(e.target.value))}
            />
          </label>

          <button
            type="button"
            className="caption-customizer__reset"
            onClick={() => onChange(undefined)}
          >
            Reset
          </button>
        </div>
      )}
    </div>
  );
}

export default CaptionCustomizer;
