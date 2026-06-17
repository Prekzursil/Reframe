// PresetPicker.tsx — smart presets + per-function override (WU-presets PH3).
//
// Two parts in one Provider-Hub section:
//   * three smart preset buttons (Privacy/offline · Best free cloud · Balanced)
//     that resolve a whole `routing.perFunction` map server-side (the active one
//     is marked with aria-pressed, not color alone);
//   * a per-function override row: one dropdown per Reframe function (select /
//     subtitles / translation / vision / edit-plan) whose options are the catalog
//     models that can SERVE that function (a non-`na` per-task grade) plus the
//     always-available Local backstop. Each option shows the catalog grade and a
//     "trains on input" privacy warning (text, not color) for AVOID-tier models.
//
// Pure presentational: the parent owns the catalog + current routing and the
// apply/override RPC calls. Changing a dropdown calls `onSetFunction`; clicking a
// preset calls `onApplyPreset`.
import React from 'react';
import type { CatalogEntry, CatalogResponse, RoutingBlock } from '../lib/rpc';

/** The local backstop sentinel id (mirrors sidecar `presets.LOCAL`). */
export const LOCAL = 'local';

/** Reframe function -> friendly label (the override-row order). */
export const FUNCTION_LABELS: Record<string, string> = {
  select: 'Moment-find / Select',
  subtitles: 'Caption / Title / Hook',
  translation: 'Translation',
  vision: 'Vision / OCR',
  editPlan: 'Edit-plan generation',
};

/** Reframe function -> the catalog `perTaskTier` task-id key. */
const FUNCTION_TASK: Record<string, string> = {
  select: 'moment_find',
  subtitles: 'caption',
  translation: 'translation',
  vision: 'vision',
  editPlan: 'edit_plan',
};

/** The three smart presets, in display order. */
const PRESETS: { id: string; label: string; hint: string }[] = [
  {
    id: 'privacy',
    label: 'Privacy / offline',
    hint: 'Everything local — nothing leaves the machine.',
  },
  {
    id: 'bestFreeCloud',
    label: 'Best free cloud',
    hint: 'Fastest free models with a local backstop.',
  },
  { id: 'balanced', label: 'Balanced', hint: 'Cloud for text, local for private frames.' },
];

export interface PresetPickerProps {
  catalog: CatalogResponse;
  routing: RoutingBlock;
  activePreset: string;
  onApplyPreset: (name: string) => void;
  onSetFunction: (function_: string, provider: string) => void;
  busy?: boolean;
}

/** Whether `entry` can serve `function_` (a real, non-`na` per-task grade). */
function canServe(entry: CatalogEntry, function_: string): boolean {
  const grade = entry.perTaskTier[FUNCTION_TASK[function_]];
  return Boolean(grade) && grade !== 'na';
}

/** The option label for one catalog model serving `function_`. */
function optionLabel(entry: CatalogEntry, function_: string): string {
  const grade = entry.perTaskTier[FUNCTION_TASK[function_]];
  const warn = entry.privacyTier === 'AVOID' ? ' — trains on input' : '';
  return `${entry.provider} ${entry.model} (${grade})${warn}`;
}

export function PresetPicker({
  catalog,
  routing,
  activePreset,
  onApplyPreset,
  onSetFunction,
  busy = false,
}: PresetPickerProps): React.ReactElement {
  return (
    <div className="preset-picker" data-section="presets">
      <h3>AI presets</h3>
      <div className="preset-picker__presets" role="group" aria-label="Smart presets">
        {PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className="preset-picker__preset"
            data-preset={preset.id}
            aria-pressed={activePreset === preset.id}
            disabled={busy}
            title={preset.hint}
            onClick={() => onApplyPreset(preset.id)}
          >
            <span className="preset-picker__preset-name">{preset.label}</span>
            <span className="preset-picker__preset-hint">{preset.hint}</span>
          </button>
        ))}
      </div>

      <h3>Per-function model</h3>
      <p className="preset-picker__intro">
        Override the model each task uses. Only models that can do the task are listed; “Local”
        always works offline. Models that train on your input are flagged.
      </p>
      <div className="preset-picker__functions">
        {Object.entries(FUNCTION_LABELS).map(([function_, label]) => {
          const current = routing.perFunction[function_]?.provider ?? LOCAL;
          const models = catalog.providers.filter((e) => canServe(e, function_));
          return (
            <div className="preset-picker__function" key={function_}>
              <label htmlFor={`fn-${function_}`}>{label}</label>
              <select
                id={`fn-${function_}`}
                data-function={function_}
                value={current}
                disabled={busy}
                onChange={(e) => onSetFunction(function_, e.target.value)}
              >
                <option value={LOCAL}>Local (always available)</option>
                {models.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {optionLabel(entry, function_)}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default PresetPicker;
