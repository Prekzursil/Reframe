// TemplateEditor.tsx — curated-preset-first template authoring (DESIGN §7 panel 1).
//
// A creator builds a template by picking a human-labeled STARTER (never a raw
// `protocol.METHODS` id), choosing the export-target presets to fan out to, and
// setting a couple of default controls. The underlying method ids are an
// implementation detail mapped by `repurposeTemplates` — they never reach the DOM
// (F-template-catalog, §7). Save via `client.templates.save`; existing templates
// are listed + deletable.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { client, type ExportPreset, type Template } from '../lib/rpc';
import {
  STARTER_TEMPLATES,
  buildTemplateFromStarter,
  starterById,
  type StarterTemplate,
} from './repurposeTemplates';
import './panels.css';

export interface TemplateEditorProps {
  onChanged?: () => void;
}

/** The Template editor: curated starters + export-target picker + CRUD. */
export function TemplateEditor({ onChanged }: TemplateEditorProps): React.ReactElement {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [presets, setPresets] = useState<ExportPreset[]>([]);
  const [starterId, setStarterId] = useState<string>(STARTER_TEMPLATES[0].id);
  const [name, setName] = useState('My template');
  const [count, setCount] = useState(5);
  const [targets, setTargets] = useState<string[]>([]);
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    try {
      const [{ templates: tmpl }, { presets: ps }] = await Promise.all([
        client.templates.list(),
        client.exportPresets.list(),
      ]);
      setTemplates(tmpl);
      setPresets(ps);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load templates');
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const starter: StarterTemplate = useMemo(() => starterById(starterId), [starterId]);

  const toggleTarget = useCallback((id: string) => {
    setTargets((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  }, []);

  const handleSave = useCallback(async () => {
    try {
      const payload = buildTemplateFromStarter(starter, name, { count }, targets);
      await client.templates.save(payload);
      await reload();
      onChanged?.();
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    }
  }, [starter, name, count, targets, reload, onChanged]);

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await client.templates.delete(id);
        await reload();
        onChanged?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Delete failed');
      }
    },
    [reload, onChanged],
  );

  return (
    <section className="template-editor" aria-label="Edit templates">
      {error !== '' ? (
        <p role="alert" className="template-editor__error">
          {error}
        </p>
      ) : null}

      <div className="template-editor__form">
        <label className="template-editor__field">
          <span>Template name</span>
          <input
            aria-label="Template name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <label className="template-editor__field">
          <span>Starter</span>
          <select
            aria-label="Starter template"
            value={starterId}
            onChange={(e) => setStarterId(e.target.value)}
          >
            {STARTER_TEMPLATES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <p className="template-editor__describe">{starter.describe}</p>

        <label className="template-editor__field">
          <span>Shorts per source</span>
          <input
            type="number"
            aria-label="Shorts per source"
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.floor(Number(e.target.value)) || 1))}
          />
        </label>

        <fieldset className="template-editor__targets">
          <legend>Export targets (platforms)</legend>
          {presets.map((preset) => (
            <label key={preset.id} className="template-editor__target">
              <input
                type="checkbox"
                checked={targets.includes(preset.id)}
                onChange={() => toggleTarget(preset.id)}
              />
              {preset.label}
            </label>
          ))}
        </fieldset>

        <button type="button" className="template-editor__save" onClick={() => void handleSave()}>
          Save template
        </button>
      </div>

      <div className="template-editor__saved">
        <h4>Saved templates</h4>
        <ul>
          {templates.map((tmpl) => (
            <li key={tmpl.id} className="template-editor__saved-row">
              <span>{tmpl.name}</span>
              <button type="button" onClick={() => void handleDelete(tmpl.id)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export default TemplateEditor;
