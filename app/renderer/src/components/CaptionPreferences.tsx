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

  useEffect(() => {
    let alive = true;
    rpc
      .get()
      .then((raw) => {
        if (alive) setPrefs(readPreferences(raw));
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

  const visual = captionVisualFor(prefs.design.style);

  return (
    <section className="caption-prefs panel" aria-label="Caption defaults">
      <h2 className="caption-prefs__title">Caption &amp; output defaults</h2>
      <p className="caption-prefs__hint">
        These defaults seed every new short — you can still tweak each clip in Make Shorts.
      </p>

      <div className="caption-prefs__group">
        <h3>Default position</h3>
        <div className="caption-prefs__frame">
          <CaptionBox
            box={prefs.design.box}
            onChange={(box) => setPrefs((p) => ({ ...p, design: { ...p.design, box } }))}
          >
            <span
              className="caption-prefs__sample"
              style={{ color: visual.activeColor, fontFamily: visual.fontFamily }}
            >
              {isNoCaption(prefs.design.style) ? 'No captions' : 'Aa'}
            </span>
          </CaptionBox>
        </div>
      </div>

      <div className="caption-prefs__group">
        <h3>Default style</h3>
        <CaptionStylePicker
          value={prefs.design.style}
          onChange={(style) => setPrefs((p) => ({ ...p, design: { ...p.design, style } }))}
        />
      </div>

      <div className="caption-prefs__group caption-prefs__row">
        <label htmlFor="prefs-subtitle-mode">Subtitles</label>
        <select
          id="prefs-subtitle-mode"
          aria-label="Default subtitle delivery"
          value={prefs.subtitleMode}
          onChange={(e) =>
            setPrefs((p) => ({ ...p, subtitleMode: e.target.value as SubtitleMode }))
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
        <LanguageSelect
          value={prefs.language}
          includeAuto={false}
          label="Default language"
          onChange={(code) => setPrefs((p) => ({ ...p, language: code }))}
        />
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
