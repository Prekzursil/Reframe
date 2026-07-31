// ExportPresetsPanel.tsx — edit the server-persisted platform export presets
// (DESIGN §7 panel 2). A table of presets with an inline editor whose
// `captionStyle` is a CLOSED select of valid ids (so an invalid id is
// unselectable — the sidecar save-time validation is a defense-in-depth backstop,
// §7/§10.5) and whose duration fields are clamped into the hard 20-60 s window
// AND coupled so `minSec <= maxSec` (so the user cannot author a preset the
// pipeline would silently correct). Both run at the COMMIT points — blur and Save
// — never per keystroke, or an in-window value like 45 is untypeable.
//
// Driven through the canonical client (`client.exportPresets.*`). Reset restores
// the seeds. CRUD is direct-return (no jobs).
import React, { useCallback, useEffect, useState } from 'react';
import { client, type ExportPreset } from '../lib/rpc';
import {
  CAPTION_STYLE_OPTIONS,
  MAX_WINDOW_SEC,
  MIN_WINDOW_SEC,
  REFRAME_ENGINE_OPTIONS,
  type WindowEdge,
  blankPreset,
  clampWindowPair,
} from './repurposeLogic';
import './panels.css';

/**
 * VALUE fingerprint of a server row. Sorted keys make it order-independent and
 * `Object.keys` makes it complete, so a future `ExportPreset` field cannot
 * silently drop out of the comparison.
 */
function presetKey(preset: ExportPreset): string {
  return JSON.stringify(preset, Object.keys(preset).sort());
}

interface RowProps {
  preset: ExportPreset;
  /**
   * Bumped for THIS row only, when its own save (or a Reset) makes the server
   * copy authoritative again. Distinct from the value fingerprint because a
   * normalisation-only save leaves the fingerprint unchanged.
   */
  syncNonce: number;
  onSave: (preset: ExportPreset) => void;
  onDelete: (id: string) => void;
}

function PresetRow({ preset, syncNonce, onSave, onDelete }: RowProps): React.ReactElement {
  const [draft, setDraft] = useState<ExportPreset>(preset);
  // The two duration cells are string MIRRORS, so `onChange` only records what
  // was typed and never rewrites the field mid-entry. Clamping per keystroke made
  // an in-window value unreachable: the first digit of "45" clamped to 20, then
  // the second appended to *that* and overshot to 60.
  const [minText, setMinText] = useState(String(preset.minSec));
  const [maxText, setMaxText] = useState(String(preset.maxSec));
  // Which duration cell was touched last. Consulted ONLY when the pair inverts,
  // and a freshly loaded row cannot invert (the sidecar persists minSec <=
  // maxSec), so the seed value is inert until the user edits something.
  const [editedEdge, setEditedEdge] = useState<WindowEdge>('max');

  const serverKey = presetKey(preset);

  // Re-sync this row when the server row's VALUES change, or when its own save (or
  // a Reset) bumps its nonce.
  //
  // The dep used to be the `preset` OBJECT IDENTITY. Every `exportPresets.list()`
  // crosses `ipcRenderer.invoke` and is re-read from JSON in the sidecar, so each
  // reload handed EVERY row a brand-new identity and this effect overwrote sibling
  // rows' unsaved keystrokes with the server copy — silently, with no dirty marker.
  //
  // A value fingerprint ALONE is not enough either: when the sidecar normalises the
  // submitted draft back onto the values already on disk (whitespace strip,
  // `9x16` -> `9:16`, window de-inversion) the fingerprint is unchanged, the effect
  // never fires, and the row the user acted on keeps displaying a value the server
  // rejected. Hence fingerprint AND a PER-ROW nonce — a reload-wide nonce would
  // reinstate the sibling-wipe.
  useEffect(() => {
    setDraft(preset);
    setMinText(String(preset.minSec));
    setMaxText(String(preset.maxSec));
  }, [serverKey, syncNonce]);

  const setField = useCallback(<K extends keyof ExportPreset>(key: K, value: ExportPreset[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

  // The ONE commit value for the window: both ends clamped into [20, 60] and the
  // pair de-inverted, derived from the MIRRORS rather than from `draft`. Blur
  // shows the correction; Save reads the same value, so a field the user typed
  // into but never blurred commits what they typed instead of silently reverting.
  const windowPair = clampWindowPair(Number(minText), Number(maxText), editedEdge);

  const commitWindow = (): void => {
    setMinText(String(windowPair.minSec));
    setMaxText(String(windowPair.maxSec));
    setDraft((prev) => ({ ...prev, ...windowPair }));
  };

  return (
    <tr className="export-presets__row">
      <td>
        <input
          aria-label="Preset label"
          value={draft.label}
          onChange={(e) => setField('label', e.target.value)}
        />
      </td>
      <td>
        <input
          aria-label="Aspect ratio"
          value={draft.aspect}
          onChange={(e) => setField('aspect', e.target.value)}
        />
      </td>
      <td>
        <input
          type="number"
          aria-label="Minimum seconds"
          min={MIN_WINDOW_SEC}
          max={MAX_WINDOW_SEC}
          step={1}
          value={minText}
          onChange={(e) => {
            setMinText(e.target.value);
            setEditedEdge('min');
          }}
          onBlur={commitWindow}
        />
      </td>
      <td>
        <input
          type="number"
          aria-label="Maximum seconds"
          min={MIN_WINDOW_SEC}
          max={MAX_WINDOW_SEC}
          step={1}
          value={maxText}
          onChange={(e) => {
            setMaxText(e.target.value);
            setEditedEdge('max');
          }}
          onBlur={commitWindow}
        />
      </td>
      <td>
        <input
          type="number"
          aria-label="Clip count"
          value={draft.count}
          onChange={(e) => setField('count', Math.max(1, Math.floor(Number(e.target.value)) || 1))}
        />
      </td>
      <td>
        <select
          aria-label="Caption style"
          value={draft.captionStyle}
          onChange={(e) => setField('captionStyle', e.target.value)}
        >
          {CAPTION_STYLE_OPTIONS.map((style) => (
            <option key={style} value={style}>
              {style}
            </option>
          ))}
        </select>
      </td>
      <td>
        <select
          aria-label="Reframe engine"
          value={draft.reframeEngine}
          onChange={(e) => setField('reframeEngine', e.target.value)}
        >
          {REFRAME_ENGINE_OPTIONS.map((engine) => (
            <option key={engine} value={engine}>
              {engine}
            </option>
          ))}
        </select>
      </td>
      <td>
        <button type="button" onClick={() => onSave({ ...draft, ...windowPair })}>
          Save
        </button>
        <button type="button" onClick={() => onDelete(draft.id)}>
          Delete
        </button>
      </td>
    </tr>
  );
}

export interface ExportPresetsPanelProps {
  /** Notify the parent when presets change (so other panels can refresh). */
  onChanged?: () => void;
}

/** The Export Presets editor table (window-clamped, closed caption-style select). */
export function ExportPresetsPanel({ onChanged }: ExportPresetsPanelProps): React.ReactElement {
  const [presets, setPresets] = useState<ExportPreset[]>([]);
  const [error, setError] = useState('');
  /** Per-preset-id resync counter (see `RowProps.syncNonce`). */
  const [syncNonces, setSyncNonces] = useState<Record<string, number>>({});

  const bumpSync = useCallback((ids: readonly string[]) => {
    setSyncNonces((prev) => {
      const next = { ...prev };
      for (const id of ids) next[id] = (next[id] ?? 0) + 1;
      return next;
    });
  }, []);

  const reload = useCallback(async () => {
    try {
      const { presets: list } = await client.exportPresets.list();
      setPresets(list);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load presets');
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const handleSave = useCallback(
    async (preset: ExportPreset) => {
      try {
        // The save RPC returns the STORED record, so its id is the one row whose
        // draft must yield to the server copy (even if the values did not move).
        const { preset: saved } = await client.exportPresets.save(preset);
        await reload();
        bumpSync([saved.id]);
        onChanged?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Save failed');
      }
    },
    [reload, onChanged, bumpSync],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      // Confirm before any destructive call (the in-repo idiom — Library.tsx:461,
      // Shorts.tsx:147, useShortsGallery.ts:99 — and the standard this panel was
      // violating: "never a silent one-click destructive action").
      const ok = (globalThis as { confirm?: (m: string) => boolean }).confirm?.(
        `Delete preset "${id}"?\n\nThis removes the preset; templates targeting it will fail to expand.`,
      );
      if (!ok) return;
      try {
        await client.exportPresets.delete(id);
        await reload();
        onChanged?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Delete failed');
      }
    },
    [reload, onChanged],
  );

  const handleAdd = useCallback(async () => {
    await handleSave({ id: '', ...blankPreset() });
  }, [handleSave]);

  const handleReset = useCallback(async () => {
    // Reset re-seeds the WHOLE catalog and nothing retains the prior copy, so this
    // is irreversible — the loudest confirm in the panel.
    const ok = (globalThis as { confirm?: (m: string) => boolean }).confirm?.(
      'Reset export presets to defaults?\n\nThis replaces the whole catalog with TikTok / Reels / Shorts and discards every custom preset.',
    );
    if (!ok) return;
    try {
      const { presets: list } = await client.exportPresets.reset();
      setPresets(list);
      // Reset is catalog-wide: every surviving row must drop its draft, including
      // one whose persisted values happen to equal the seeds already.
      bumpSync(list.map((p) => p.id));
      setError('');
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed');
    }
  }, [onChanged, bumpSync]);

  return (
    <section className="export-presets" aria-label="Export presets">
      <div className="export-presets__toolbar">
        <button type="button" onClick={() => void handleAdd()}>
          New preset
        </button>
        <button type="button" onClick={() => void handleReset()}>
          Reset to defaults
        </button>
        <span className="export-presets__hint">
          Durations are clamped to 20-60 s, and Min is kept at or below Max.
        </span>
      </div>

      {error !== '' ? (
        <p role="alert" className="export-presets__error">
          {error}
        </p>
      ) : null}

      <table className="export-presets__table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Aspect</th>
            <th>Min s</th>
            <th>Max s</th>
            <th>Count</th>
            <th>Caption style</th>
            <th>Engine</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {presets.map((preset) => (
            <PresetRow
              key={preset.id}
              preset={preset}
              syncNonce={syncNonces[preset.id] ?? 0}
              onSave={(p) => void handleSave(p)}
              onDelete={(id) => void handleDelete(id)}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default ExportPresetsPanel;
