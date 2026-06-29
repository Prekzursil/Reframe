// AdvancedModels.tsx — M3 Advanced disclosure: model SORT + manual runner POINT.
//
// A progressive-disclosure (`<details>`) block in Settings › Models & System that
// exposes the two power-user affordances the WU calls for:
//   * SORT — re-order the metadata-driven eligibility list by VRAM fit / size /
//     name (pure `sortModelMetas`), so a user can see exactly which models fit.
//   * POINT — type a non-default Ollama / LM Studio base URL + port; on submit it
//     persists via the parent (settings `ollamaBaseUrl` / `lmStudioBaseUrl`),
//     which `local_detect.detect_local_servers` already honours, so a runner on a
//     custom host/port is detected on the next analyse. Advise-only (G-11 §e): we
//     point the detector at it, we do not provision it.
import React, { useState } from 'react';
import type { ModelMeta } from '../lib/rpc';
import {
  sortModelMetas,
  MODEL_SORT_MODES,
  MODEL_SORT_LABELS,
  type ModelSortMode,
} from './routingSort';

export interface AdvancedModelsProps {
  /** The metadata-driven eligible models (`models.overview` -> eligibility.models). */
  models: ModelMeta[];
  /** Current persisted Ollama base URL (blank = the default port). */
  ollamaBaseUrl: string;
  /** Current persisted LM Studio base URL (blank = the default port). */
  lmStudioBaseUrl: string;
  /** Persist the edited runner URLs (the parent writes them to settings). */
  onApplyRunnerUrls: (patch: { ollamaBaseUrl: string; lmStudioBaseUrl: string }) => void;
}

/** Human GB string for a VRAM estimate (or an em dash when unknown). */
function vramText(gb: number | null): string {
  return gb === null ? '—' : `${gb} GB`;
}

export function AdvancedModels({
  models,
  ollamaBaseUrl,
  lmStudioBaseUrl,
  onApplyRunnerUrls,
}: AdvancedModelsProps): React.ReactElement {
  const [sort, setSort] = useState<ModelSortMode>('fit');
  const [ollama, setOllama] = useState<string>(ollamaBaseUrl);
  const [lmStudio, setLmStudio] = useState<string>(lmStudioBaseUrl);

  const sorted = sortModelMetas(models, sort);

  const submit = (e: React.FormEvent): void => {
    e.preventDefault();
    onApplyRunnerUrls({ ollamaBaseUrl: ollama, lmStudioBaseUrl: lmStudio });
  };

  return (
    <details className="advanced-models">
      <summary>Advanced</summary>

      <div className="advanced-models__sort">
        <label htmlFor="model-sort">Sort models by</label>
        <select
          id="model-sort"
          data-action="model-sort"
          value={sort}
          onChange={(e) => setSort(e.target.value as ModelSortMode)}
        >
          {MODEL_SORT_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {MODEL_SORT_LABELS[mode]}
            </option>
          ))}
        </select>
      </div>

      {sorted.length === 0 ? (
        <p className="advanced-models__empty" data-section="advanced-models-empty">
          No detected-runner model metadata yet — analyse with a local runner (Ollama / LM Studio)
          running to populate this list.
        </p>
      ) : (
        <ul className="advanced-models__list" data-section="advanced-models">
          {sorted.map((m) => (
            <li key={m.digest} className="advanced-models__row" data-model={m.model}>
              <span className="advanced-models__name">{m.model}</span>
              <span className={`advanced-models__fit${m.fits ? ' is-fit' : ''}`}>
                {m.fits ? 'fits' : 'too big'}
              </span>
              <span className="advanced-models__vram">{vramText(m.vramEstimateGb)}</span>
            </li>
          ))}
        </ul>
      )}

      <form className="advanced-models__point" onSubmit={submit}>
        <p className="advanced-models__point-intro">
          Point at a runner on a non-default host/port (we detect it, we do not install it):
        </p>
        <div className="field">
          <label htmlFor="ollama-url">Ollama base URL</label>
          <input
            id="ollama-url"
            data-action="ollama-url"
            type="text"
            placeholder="http://127.0.0.1:11434/v1"
            value={ollama}
            onChange={(e) => setOllama(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="lmstudio-url">LM Studio base URL</label>
          <input
            id="lmstudio-url"
            data-action="lmstudio-url"
            type="text"
            placeholder="http://127.0.0.1:1234/v1"
            value={lmStudio}
            onChange={(e) => setLmStudio(e.target.value)}
          />
        </div>
        <button type="submit" data-action="apply-runner-urls">
          Apply runner URLs
        </button>
      </form>
    </details>
  );
}

export default AdvancedModels;
