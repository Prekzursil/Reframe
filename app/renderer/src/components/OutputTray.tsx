// OutputTray.tsx — the KEYSTONE post-action surface (V1 IA §h).
//
// Defined ONCE and rendered after ANY primary action (Make Shorts / Edit /
// Director), the Output Tray consolidates the choices that used to be duplicated
// across the old flat tabs (caption×6, translate×3, subtitle-edit×2, gallery×2,
// export×7). It offers, in one consistent place:
//   * Caption?  · Translate? (+ target language)  · Reframe?  · Burn subtitles
//   * Save clip · Save short · Save SRT separately  (only the ones the surface
//     supports — each gated on a provided handler)
//
// It is a CONTROLLED, presentational component: the parent owns the state and
// the save handlers, so the same tray serves every surface without embedding
// surface-specific logic. Quality features default ON (G-4) via
// DEFAULT_OUTPUT_TRAY. The caption-editor detail (position/style preview) lands
// in a later phase — this is the clean seam it plugs into.
import React from 'react';
import { LanguageSelect } from './LanguageSelect';
import { SUBTITLE_MODES, SUBTITLE_MODE_META, type SubtitleMode } from '../lib/outputOptions';
import './outputTray.css';

/** The consolidated post-action toggles + subtitle delivery + translate language. */
export interface OutputTrayState {
  caption: boolean;
  translate: boolean;
  reframe: boolean;
  /** How subtitles ride the export (burn / soft track / separate file / none). */
  subtitleMode: SubtitleMode;
  /** Target language for Translate (a code from lib/languages, never auto). */
  language: string;
}

/** Quality-defaults-ON seed (G-4): caption + reframe ON, burn subtitles; translate opt-in. */
export const DEFAULT_OUTPUT_TRAY: OutputTrayState = {
  caption: true,
  translate: false,
  reframe: true,
  subtitleMode: 'burn',
  language: 'en',
};

export interface OutputTrayProps {
  /** Current tray state (parent-owned). */
  state: OutputTrayState;
  /** Called with the next immutable state on any change. */
  onChange: (next: OutputTrayState) => void;
  /** Save the edited clip (Edit surface). Omit to hide the button. */
  onSaveClip?: () => void;
  /** Save the produced short (Make Shorts surface). Omit to hide the button. */
  onSaveShort?: () => void;
  /** Save the SRT sidecar separately. Omit to hide the button. */
  onSaveSrt?: () => void;
  /** Disable the save actions while an action is in flight. */
  busy?: boolean;
  /** Heading text (defaults to "Next steps"). */
  title?: string;
}

interface ToggleDef {
  key: 'caption' | 'translate' | 'reframe';
  label: string;
}

const TOGGLES: readonly ToggleDef[] = [
  { key: 'caption', label: 'Caption' },
  { key: 'translate', label: 'Translate' },
  { key: 'reframe', label: 'Reframe' },
];

/** The single, shared post-action tray. */
export function OutputTray({
  state,
  onChange,
  onSaveClip,
  onSaveShort,
  onSaveSrt,
  busy = false,
  title = 'Next steps',
}: OutputTrayProps): React.ReactElement {
  return (
    <section className="output-tray" aria-label="Output options">
      <h3 className="output-tray__title">{title}</h3>

      <div className="output-tray__toggles" role="group" aria-label="Post-action options">
        {TOGGLES.map(({ key, label }) => (
          <label key={key} className="output-tray__toggle">
            <input
              type="checkbox"
              aria-label={label}
              checked={state[key]}
              onChange={(e) => onChange({ ...state, [key]: e.target.checked })}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>

      {state.caption ? (
        <div className="output-tray__subs">
          <label className="output-tray__subs-label" htmlFor="output-tray-subtitle-mode">
            Subtitles
          </label>
          <select
            id="output-tray-subtitle-mode"
            aria-label="Subtitle delivery"
            value={state.subtitleMode}
            onChange={(e) => onChange({ ...state, subtitleMode: e.target.value as SubtitleMode })}
          >
            {SUBTITLE_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {SUBTITLE_MODE_META[mode].label}
              </option>
            ))}
          </select>
          <span className="output-tray__subs-help">
            {SUBTITLE_MODE_META[state.subtitleMode].help}
          </span>
        </div>
      ) : null}

      {state.translate ? (
        <div className="output-tray__lang">
          <span className="output-tray__lang-label">Translate to</span>
          {/* No auto-detect: you translate TO a chosen language. */}
          <LanguageSelect
            value={state.language}
            includeAuto={false}
            label="Translate to"
            onChange={(code) => onChange({ ...state, language: code })}
          />
        </div>
      ) : null}

      <div className="output-tray__saves" role="group" aria-label="Save">
        {onSaveClip ? (
          <button type="button" onClick={onSaveClip} disabled={busy}>
            Save clip
          </button>
        ) : null}
        {onSaveShort ? (
          <button type="button" onClick={onSaveShort} disabled={busy}>
            Save short
          </button>
        ) : null}
        {onSaveSrt ? (
          <button type="button" onClick={onSaveSrt} disabled={busy}>
            Save SRT separately
          </button>
        ) : null}
      </div>
    </section>
  );
}

export default OutputTray;
