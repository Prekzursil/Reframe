// SavePresetsControls.tsx — list / apply / save / remove named save-presets
// (UX/QoL WU-11).
//
// A save-preset is a named `{autosave, exportDefaults}` bundle persisted by the
// `savePresets.*` RPCs (WU-10). This control set:
//   * lists the saved bundles (one row each) with the last-applied one marked
//     `aria-current` (text "Active", not color alone — WCAG 1.4.1);
//   * APPLIES a bundle — marks it active server-side AND calls `onApply` so the
//     parent can pre-fill export dialogs from the bundle's `exportDefaults`;
//   * SAVES the live `autosave` + `exportDefaults` under a typed name (upsert);
//   * REMOVES a bundle.
//
// Self-fetching (mirrors JobQueue's load-on-mount + error state) but with the RPC
// surface INJECTED (mirrors useVideoThumbnail) so it unit-tests against a fake
// client with no preload bridge. The parent owns the live settings (passed in)
// and the post-apply pre-fill (`onApply`); this component owns only the list +
// the three mutations.
import React, { useCallback, useEffect, useState } from 'react';
import type { AutosaveSettings, ExportDefaults, SavePreset, SavePresetsBlock } from '../lib/rpc';
import './savePresetsControls.css';

/** The thin `savePresets.*` slice this component needs (injectable for tests). */
export interface SavePresetsRpc {
  list(): Promise<SavePresetsBlock>;
  apply(name: string): Promise<{ active: string; savePreset: SavePreset }>;
  upsert(
    name: string,
    bundle: { autosave: AutosaveSettings; exportDefaults: ExportDefaults },
  ): Promise<{ presets: Record<string, SavePreset> }>;
  remove(name: string): Promise<{ presets: Record<string, SavePreset>; active: string }>;
}

export interface SavePresetsControlsProps {
  /** The injected `savePresets.*` client slice (`client.savePresets` in the app). */
  rpc: SavePresetsRpc;
  /** Live autosave settings — bundled into the preset on Save. */
  autosave: AutosaveSettings;
  /** Live export defaults — bundled into the preset on Save. */
  exportDefaults: ExportDefaults;
  /** Called after a successful apply with the applied bundle (parent pre-fills UI). */
  onApply?: (preset: SavePreset) => void;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function SavePresetsControls({
  rpc,
  autosave,
  exportDefaults,
  onApply,
}: SavePresetsControlsProps): React.ReactElement {
  const [block, setBlock] = useState<SavePresetsBlock>({ presets: {}, active: '' });
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState<string>('');
  const [busy, setBusy] = useState<boolean>(false);

  const refresh = useCallback(async () => {
    try {
      const result = await rpc.list();
      setBlock({ presets: result?.presets ?? {}, active: result?.active ?? '' });
      setError(null);
    } catch (err) {
      setError(errText(err));
    }
  }, [rpc]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleApply = useCallback(
    async (presetName: string) => {
      setBusy(true);
      try {
        const result = await rpc.apply(presetName);
        setBlock((prev) => ({ ...prev, active: result.active }));
        setError(null);
        if (onApply) onApply(result.savePreset);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [rpc, onApply],
  );

  const handleSave = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await rpc.upsert(trimmed, { autosave, exportDefaults });
      setName('');
      setError(null);
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }, [name, rpc, autosave, exportDefaults, refresh]);

  const handleRemove = useCallback(
    async (presetName: string) => {
      setBusy(true);
      try {
        const result = await rpc.remove(presetName);
        setBlock({ presets: result.presets, active: result.active });
        setError(null);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [rpc],
  );

  const names = Object.keys(block.presets);

  return (
    <div className="save-presets" data-section="save-presets">
      <h3>Saved export presets</h3>

      {error ? (
        <div className="save-presets__error" role="alert">
          {error}
        </div>
      ) : null}

      {names.length === 0 ? (
        <div className="save-presets__empty">No saved presets yet.</div>
      ) : (
        <ul className="save-presets__list">
          {names.map((presetName) => {
            const isActive = block.active === presetName;
            return (
              <li
                key={presetName}
                className="save-presets__item"
                data-preset={presetName}
                aria-current={isActive ? 'true' : undefined}
              >
                <span className="save-presets__name">{presetName}</span>
                {isActive ? <span className="save-presets__active-tag">Active</span> : null}
                <div className="save-presets__item-actions">
                  <button
                    type="button"
                    className="save-presets__apply"
                    aria-label={`Apply ${presetName}`}
                    disabled={busy}
                    onClick={() => void handleApply(presetName)}
                  >
                    Apply
                  </button>
                  <button
                    type="button"
                    className="save-presets__remove"
                    aria-label={`Remove ${presetName}`}
                    disabled={busy}
                    onClick={() => void handleRemove(presetName)}
                  >
                    Remove
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <div className="save-presets__save-row">
        <label htmlFor="save-presets-name">Save current settings as</label>
        <input
          id="save-presets-name"
          type="text"
          className="save-presets__name-input"
          placeholder="Preset name"
          value={name}
          disabled={busy}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          type="button"
          className="save-presets__save"
          disabled={busy}
          onClick={() => void handleSave()}
        >
          Save
        </button>
      </div>
    </div>
  );
}

export default SavePresetsControls;
