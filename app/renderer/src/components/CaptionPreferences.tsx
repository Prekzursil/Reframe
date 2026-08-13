// CaptionPreferences.tsx — the Preferences/Settings area for caption + output
// DEFAULTS (P4 §4). Set the caption style + position, subtitle delivery, and
// language every new short starts from; persisted to the settings store so the
// Make Shorts flow + Output Tray seed from one place.
//
// The settings RPC is injected (defaults to the live client) so the panel is
// unit-testable without a backend. The position box edits over a static preview
// frame (no Player needed in Settings); the live video preview lives in the
// Make Shorts caption editor.
import React, { useCallback, useEffect, useState } from 'react';
import { CaptionStylePicker } from './CaptionStylePicker';
import { CaptionBox } from './CaptionBox';
import { LanguageSelect } from './LanguageSelect';
import { captionVisualFor, isNoCaption } from '../lib/captionTemplates';
import {
  type CaptionPreferences as Prefs,
  DEFAULT_PREFERENCES,
  preferencesPatch,
  readPreferences,
} from '../lib/captionPreferences';
import { SUBTITLE_MODES, SUBTITLE_MODE_META, type SubtitleMode } from '../lib/outputOptions';
import { client } from '../lib/rpc';
import './captionPreferences.css';

/** The settings store slice this panel needs (injectable for tests). */
export interface SettingsBridge {
  get: () => Promise<Record<string, unknown>>;
  set: (values: Record<string, unknown>) => Promise<Record<string, unknown>>;
}

export interface CaptionPreferencesProps {
  /** The settings RPC (defaults to the live client). */
  rpc?: SettingsBridge;
}

/**
 * DOM ids wiring the "Caption quality" group to its heading + scope note, so the
 * disclosure is programmatically associated (aria-labelledby/-describedby) and not
 * merely adjacent. Static string ids follow the panel idiom (LocalRunners.tsx,
 * RoutingToggle.tsx) — this panel renders once per Settings sub-tab.
 */
const QUALITY_LABEL_ID = 'prefs-caption-quality-label';
const QUALITY_SCOPE_ID = 'prefs-caption-quality-scope';

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function CaptionPreferences({
  rpc = client.settings,
}: CaptionPreferencesProps): React.ReactElement {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFERENCES);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  // The ASR engine is NOT a preference this panel owns or writes — Settings ▸
  // Models does that. It is read here only so the language picker can warn when
  // the chosen engine cannot transcribe the chosen default language, and it comes
  // out of the SAME settings payload, so it costs no extra rpc.
  const [asrEngine, setAsrEngine] = useState('');

  useEffect(() => {
    let alive = true;
    rpc
      .get()
      .then((raw) => {
        if (!alive) return;
        setPrefs(readPreferences(raw));
        setAsrEngine(typeof raw.asrEngine === 'string' ? raw.asrEngine : '');
      })
      .catch((err) => {
        if (alive) setError(`Could not load preferences: ${errText(err)}`);
      });
    return () => {
      alive = false;
    };
  }, [rpc]);

  const save = useCallback(async () => {
    setSaving(true);
    setStatus('');
    setError('');
    try {
      await rpc.set(preferencesPatch(prefs));
      setStatus('Preferences saved.');
    } catch (err) {
      setError(`Could not save preferences: ${errText(err)}`);
    } finally {
      setSaving(false);
    }
  }, [rpc, prefs]);

  /**
   * Apply a draft edit. ANY edit makes `prefs` diverge from what is on disk, so
   * the green "Preferences saved." live region must stop asserting a state that
   * no longer holds — it is otherwise cleared only by the NEXT save. Every edit
   * handler below routes through this, so the invariant lives in one place.
   *
   * `error` is deliberately NOT cleared: a save failure stays relevant until the
   * next save attempt. Nor is the Save button gated on dirtiness — an
   * unsaved-changes guard is a separate, unbuilt capability.
   */
  const editPrefs = useCallback((next: (p: Prefs) => Prefs): void => {
    setStatus('');
    setPrefs(next);
  }, []);

  const visual = captionVisualFor(prefs.design.style);
  // The "none" template's fill is the literal `transparent` (NONE_VISUAL in
  // captionTemplates.ts), so applying it would paint the preview's own
  // explanatory "No captions" label at zero alpha.
  const none = isNoCaption(prefs.design.style);

  return (
    <section className="caption-prefs panel" aria-label="Caption defaults">
      <h2 className="caption-prefs__title">Caption &amp; output defaults</h2>
      <p className="caption-prefs__hint">
        Caption style, position, subtitle delivery and language seed every new short — you can still
        tweak each clip in Make Shorts.
      </p>

      <div className="caption-prefs__group">
        <h3>Default position</h3>
        <div className="caption-prefs__frame">
          <CaptionBox
            box={prefs.design.box}
            onChange={(box) => editPrefs((p) => ({ ...p, design: { ...p.design, box } }))}
          >
            <span
              className={`caption-prefs__sample${none ? ' caption-prefs__sample--none' : ''}`}
              style={{
                color: none ? undefined : visual.activeColor,
                fontFamily: visual.fontFamily,
              }}
            >
              {none ? 'No captions' : 'Aa'}
            </span>
          </CaptionBox>
        </div>
      </div>

      <div className="caption-prefs__group">
        <h3>Default style</h3>
        <CaptionStylePicker
          value={prefs.design.style}
          onChange={(style) => editPrefs((p) => ({ ...p, design: { ...p.design, style } }))}
        />
      </div>

      <div className="caption-prefs__group caption-prefs__row">
        <label htmlFor="prefs-subtitle-mode">Subtitles</label>
        {/* Deliberately UNCLASSED. This panel's root is `caption-prefs panel` and `.panel`
            has no rule in the tree, so its <button> does need a class to reach the shared
            voice — but a <select> does not: styles/controls.css:34 already voices every
            <select> in the app, chevron included. Adding a class here put it under
            shell.css's shared INPUT rule, whose `background:`/`padding:` shorthands then
            reset the chevron and the padding reserved for it, so this control stopped
            matching the LanguageSelect directly below it. Measured in-engine and reverted;
            shell.buttonVoice.conformance.test.ts keeps the two dropdowns in parity. */}
        <select
          id="prefs-subtitle-mode"
          aria-label="Default subtitle delivery"
          value={prefs.subtitleMode}
          onChange={(e) =>
            editPrefs((p) => ({ ...p, subtitleMode: e.target.value as SubtitleMode }))
          }
        >
          {SUBTITLE_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {SUBTITLE_MODE_META[mode].label}
            </option>
          ))}
        </select>
      </div>

      <div className="caption-prefs__group caption-prefs__row">
        <span>Default language</span>
        {/* Auto-detect IS offered here: this is a transcription SOURCE hint, not a
            translation target, so "let the model detect it" is a real choice.
            `coerceLanguage` accepts the sentinel too — without that, saving it
            would silently rewrite it to English (audit §2.1). */}
        <LanguageSelect
          value={prefs.language}
          label="Default language"
          engine={asrEngine}
          onChange={(code) => editPrefs((p) => ({ ...p, language: code }))}
        />
      </div>

      <div
        className="caption-prefs__group"
        role="group"
        aria-labelledby={QUALITY_LABEL_ID}
        aria-describedby={QUALITY_SCOPE_ID}
      >
        <h3 id={QUALITY_LABEL_ID}>Caption quality</h3>
        <p className="caption-prefs__scope" id={QUALITY_SCOPE_ID}>
          Applies to captions generated on the Caption, Subtitles and Recipes screens — not to the
          Make Shorts export, where captions are tuned per clip in the caption editor.
        </p>
        <label className="caption-prefs__toggle" htmlFor="prefs-caption-polish">
          <input
            id="prefs-caption-polish"
            type="checkbox"
            checked={prefs.captionPolish}
            onChange={(e) => editPrefs((p) => ({ ...p, captionPolish: e.target.checked }))}
          />
          <span className="caption-prefs__toggle-text">
            Polish captions
            <small>Tidy punctuation, casing &amp; reading speed (Netflix CPS/CPL).</small>
          </span>
        </label>
        <label className="caption-prefs__toggle" htmlFor="prefs-caption-speakers">
          <input
            id="prefs-caption-speakers"
            type="checkbox"
            checked={prefs.captionSpeakerLabels}
            onChange={(e) => editPrefs((p) => ({ ...p, captionSpeakerLabels: e.target.checked }))}
          />
          <span className="caption-prefs__toggle-text">
            Speaker labels
            <small>Prefix each line with the detected speaker (needs diarization).</small>
          </span>
        </label>
      </div>

      <div className="caption-prefs__actions">
        <button type="button" onClick={() => void save()} disabled={saving}>
          {saving ? 'Saving…' : 'Save defaults'}
        </button>
      </div>

      {status ? (
        <p className="caption-prefs__status" role="status">
          {status}
        </p>
      ) : null}
      {error ? (
        <p className="caption-prefs__error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

export default CaptionPreferences;
