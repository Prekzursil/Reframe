// ExportPresetsPanel.tsx — edit the server-persisted platform export presets
// (DESIGN §7 panel 2). A table of presets with an inline editor whose
// `captionStyle` is a CLOSED select of valid ids (so an invalid id is
// unselectable — the sidecar save-time validation is a defense-in-depth backstop,
// §7/§10.5) and whose duration fields are clamped into the hard 20-60 s window
// (so the user cannot author a preset the pipeline would silently correct).
//
// Driven through the canonical client (`client.exportPresets.*`). Reset restores
// the seeds. CRUD is direct-return (no jobs).
import React, { useCallback, useEffect, useState } from 'react';
import { client, type ExportPreset } from '../lib/rpc';
import {
  CAPTION_STYLE_OPTIONS,
  REFRAME_ENGINE_OPTIONS,
  blankPreset,
  clampWindowSec,
} from './repurposeLogic';
import './panels.css';

interface RowProps {
  preset: ExportPreset;
  onSave: (preset: ExportPreset) => void;
  onDelete: (id: string) => void;
}

function PresetRow({ preset, onSave, onDelete }: RowProps): React.ReactElement {
  const [draft, setDraft] = useState<ExportPreset>(preset);

  // Keep the row in sync if the parent reloads the list (e.g. after reset).
  useEffect(() => {
    setDraft(preset);
  }, [preset]);

  const setField = useCallback(<K extends keyof ExportPreset>(key: K, value: ExportPreset[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }, []);

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
          value={draft.minSec}
          onChange={(e) => setField('minSec', clampWindowSec(Number(e.target.value)))}
        />
      </td>
      <td>
        <input
          type="number"
          aria-label="Maximum seconds"
          value={draft.maxSec}
          onChange={(e) => setField('maxSec', clampWindowSec(Number(e.target.value)))}
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
        <button type="button" onClick={() => onSave(draft)}>
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
        await client.exportPresets.save(preset);
        await reload();
        onChanged?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Save failed');
      }
    },
    [reload, onChanged],
  );

  const handleDelete = useCallback(
    async (id: string) => {
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
    try {
      const { presets: list } = await client.exportPresets.reset();
      setPresets(list);
      setError('');
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed');
    }
  }, [onChanged]);

  return (
    <section className="export-presets" aria-label="Export presets">
      <div className="export-presets__toolbar">
        <button type="button" onClick={() => void handleAdd()}>
          New preset
        </button>
        <button type="button" onClick={() => void handleReset()}>
          Reset to defaults
        </button>
        <span className="export-presets__hint">Durations are clamped to 20-60 s.</span>
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
