// SavePresetsControls.tsx — list / apply / save / remove named save-presets
// (UX/QoL WU-11).
//
// A save-preset is a named `{autosave, exportDefaults}` bundle persisted by the
// `savePresets.*` RPCs (WU-10). This control set:
//   * lists the saved bundles (one row each) with the last-applied one marked
//     `aria-current` (text "Active", not color alone — WCAG 1.4.1);
//   * APPLIES a bundle — marks it active server-side AND calls `onApply` so the
//     parent can pre-fill export dialogs from the bundle's `exportDefaults`;
//   * SAVES the live `autosave` + `exportDefaults` under a typed name (upsert) —
//     Save is disabled until the trimmed name is non-empty, and Enter in the name
//     field submits (the repo convention, AddKeyRow.tsx:38-48);
//   * REMOVES a bundle.
//
// Any mutation locks the WHOLE surface (all three sidecar handlers read-modify-write
// the entire `savePresets` block, so concurrent mutations would lose an update) and
// says so: `aria-busy` on every control, the verb on the button that owns it, and one
// action-neutral "Working…" live region.
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

/**
 * Which mutation is in flight, or `null` when idle.
 *
 * This replaces a bare `busy` boolean ONLY so the busy COPY can be truthful: one
 * flag shared by three mutations would relabel Save to "Saving…" (and announce it)
 * while a remove or an apply is what is actually running. The disable SCOPE is
 * unchanged — every control still locks on the derived `busy`, because all three
 * sidecar handlers read-modify-write the WHOLE `savePresets` block
 * (`providers_ops.py:388-396`; `settings.set` is a shallow top-level replace), so
 * per-row unlocking would let two concurrent mutations lose an update.
 */
type PendingAction = 'apply' | 'remove' | 'save' | null;

export function SavePresetsControls({
  rpc,
  autosave,
  exportDefaults,
  onApply,
}: SavePresetsControlsProps): React.ReactElement {
  const [block, setBlock] = useState<SavePresetsBlock>({ presets: {}, active: '' });
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState<string>('');
  const [pending, setPending] = useState<PendingAction>(null);

  // The whole surface locks for ANY mutation (see PendingAction above).
  const busy = pending !== null;

  // Save is disabled while the trimmed name is empty (the repo-wide convention —
  // AddKeyRow.tsx:20-21, ProviderKeyRow, DirectorPanel, Dub). Derived, not state.
  const trimmed = name.trim();
  const canSave = trimmed.length > 0;

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
      setPending('apply');
      try {
        const result = await rpc.apply(presetName);
        setBlock((prev) => ({ ...prev, active: result.active }));
        setError(null);
        if (onApply) onApply(result.savePreset);
      } catch (err) {
        setError(errText(err));
      } finally {
        setPending(null);
      }
    },
    [rpc, onApply],
  );

  const handleSave = useCallback(async () => {
    if (!canSave) return;
    setPending('save');
    try {
      await rpc.upsert(trimmed, { autosave, exportDefaults });
      setName('');
      setError(null);
      await refresh();
    } catch (err) {
      setError(errText(err));
    } finally {
      setPending(null);
    }
  }, [canSave, trimmed, rpc, autosave, exportDefaults, refresh]);

  const handleRemove = useCallback(
    async (presetName: string) => {
      setPending('remove');
      try {
        const result = await rpc.remove(presetName);
        setBlock({ presets: result.presets, active: result.active });
        setError(null);
      } catch (err) {
        setError(errText(err));
      } finally {
        setPending(null);
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

      {/* ONE live region for all three mutations, so it must stay action-NEUTRAL:
       * the specific verb belongs on the control that owns it (Save, below).
       * Precedent for the markup shape: CaptionPreferences.tsx:173-177. */}
      {busy ? (
        <p className="save-presets__status" role="status">
          Working…
        </p>
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
                    aria-busy={busy}
                    title={busy ? 'Working…' : undefined}
                    onClick={() => void handleApply(presetName)}
                  >
                    Apply
                  </button>
                  <button
                    type="button"
                    className="save-presets__remove"
                    aria-label={`Remove ${presetName}`}
                    disabled={busy}
                    aria-busy={busy}
                    title={busy ? 'Working…' : undefined}
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
          onKeyDown={(e) => {
            // Enter submits (and exercises the canSave guard for a blank field —
            // the Save button is disabled when blank, but Enter is not gated by it).
            if (e.key === 'Enter') void handleSave();
          }}
        />
        <button
          type="button"
          className="save-presets__save"
          disabled={busy || !canSave}
          aria-busy={busy}
          onClick={() => void handleSave()}
        >
          {/* The verb is only truthful while the SAVE is the in-flight action —
           * `busy` alone is also true for apply/remove (see PendingAction). */}
          {pending === 'save' ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  );
}

export default SavePresetsControls;
