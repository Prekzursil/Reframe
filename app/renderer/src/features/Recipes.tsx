// Recipes feature panel (system-advanced group, feature 3).
//
// Saved PIPELINE RECIPES — a lightweight, reusable multi-step pipeline (e.g.
// transcribe -> diarize -> make shorts) the user runs in ONE shot with per-step
// progress. Drives:
//   recipes.list()           -> {recipes:[Recipe]}      (direct)
//   recipes.save({recipe})   -> {recipe}                (direct, upsert)
//   recipes.delete({id})     -> {ok}                    (direct)
//   recipes.run({id})        -> {jobId} -> job.done {results}   (long job)
//
// Recipes are video-scoped via the active videoId, which is stamped into each
// step's params when saving a preset. Consumes the FROZEN window.api bridge via
// the shared `./_api` helpers, the same pattern as the sibling panels.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

// --- wire shapes (field names FROZEN, identical to the Python side) ---------
export interface RecipeStep {
  method: string;
  params: Record<string, unknown>;
  label: string;
}
export interface Recipe {
  id: string;
  name: string;
  steps: RecipeStep[];
}
export interface RunDoneResult {
  results: unknown[];
}

// --- preset templates -------------------------------------------------------
// Each preset is a (name, steps) builder taking the active videoId so the steps
// target the current video. Steps use the "$N.key" reference form the runner
// resolves (see recipes.py). These mirror real wired §2 methods.
export interface RecipePreset {
  id: string;
  name: string;
  describe: string;
  build: (videoId: string) => RecipeStep[];
}

export const RECIPE_PRESETS: RecipePreset[] = [
  {
    id: 'transcribe-diarize',
    name: 'Transcribe + label speakers',
    describe: 'Transcribe the video, then run token-free diarization.',
    build: (videoId) => [
      { method: 'transcribe.start', params: { videoId }, label: 'Transcribe' },
      { method: 'diarize.start', params: { videoId }, label: 'Label speakers' },
    ],
  },
  {
    id: 'transcribe-subtitles',
    name: 'Transcribe + subtitles',
    describe: 'Transcribe, then generate a soft subtitle track.',
    build: (videoId) => [
      { method: 'transcribe.start', params: { videoId }, label: 'Transcribe' },
      { method: 'subtitles.generate', params: { videoId }, label: 'Generate subtitles' },
    ],
  },
  {
    id: 'transcribe-subtitles-translate',
    name: 'Transcribe + subtitles + translate (ES)',
    describe: 'Transcribe, generate subtitles, then translate them to Spanish.',
    build: (videoId) => [
      { method: 'transcribe.start', params: { videoId }, label: 'Transcribe' },
      { method: 'subtitles.generate', params: { videoId }, label: 'Generate subtitles' },
      {
        method: 'subtitles.translate',
        params: { trackId: '$1.track.id', targetLang: 'es' },
        label: 'Translate to Spanish',
      },
    ],
  },
];

// --- pure helpers (exported for tests) -------------------------------------
/** Build a save-ready recipe payload from a preset + the active videoId. */
export function buildRecipeFromPreset(preset: RecipePreset, videoId: string): Omit<Recipe, 'id'> {
  return { name: preset.name, steps: preset.build(videoId) };
}

/** Pull the §A3 job.done error payload message ({error:{message,type}}). */
export function doneErrorMessage(result: unknown): string | null {
  const err = pickField<{ message?: unknown }>(result, 'error');
  if (err && typeof err === 'object' && typeof err.message === 'string') {
    return err.message;
  }
  return null;
}

export interface RecipesProps {
  /** Stamp recipe steps with this video so a preset targets the current video. */
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function Recipes({ videoId, api }: RecipesProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [listError, setListError] = useState<string>('');
  const [runError, setRunError] = useState<string>('');
  const [runningId, setRunningId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');

  const refresh = useCallback(async (): Promise<void> => {
    setListError('');
    try {
      const res = await bridge.rpc<{ recipes: Recipe[] }>('recipes.list');
      setRecipes(Array.isArray(res?.recipes) ? res.recipes : []);
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    }
  }, [bridge]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Relay job.progress for the active run only.
  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const savePreset = useCallback(
    async (preset: RecipePreset): Promise<void> => {
      setListError('');
      try {
        await bridge.rpc('recipes.save', { recipe: buildRecipeFromPreset(preset, videoId) });
        await refresh();
      } catch (err) {
        setListError(err instanceof Error ? err.message : String(err));
      }
    },
    [bridge, videoId, refresh],
  );

  const remove = useCallback(
    async (id: string): Promise<void> => {
      try {
        await bridge.rpc('recipes.delete', { id });
        await refresh();
      } catch (err) {
        setListError(err instanceof Error ? err.message : String(err));
      }
    },
    [bridge, refresh],
  );

  const run = useCallback(
    async (id: string): Promise<void> => {
      if (runningId) return;
      setRunningId(id);
      setRunError('');
      setPct(0);
      setMessage('Starting…');
      try {
        const res = await bridge.rpc<{ jobId: string }>('recipes.run', { id });
        const job = res?.jobId ?? null;
        setJobId(job);
        const result = job ? await waitForJobDone<unknown>(bridge, job, (r) => r ?? null) : null;
        const errMessage = doneErrorMessage(result);
        if (errMessage) {
          setRunError(errMessage);
        } else {
          setPct(100);
          setMessage('Done');
        }
      } catch (err) {
        setRunError(err instanceof Error ? err.message : String(err));
      } finally {
        setRunningId(null);
        setJobId(null);
      }
    },
    [bridge, runningId],
  );

  const cancel = useCallback(async (): Promise<void> => {
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort; the job may already be finishing.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  return (
    <section className="feature-panel recipes-panel" aria-label="Recipes">
      <h2>Pipeline Recipes</h2>
      <p className="assets-intro">
        Save a multi-step pipeline and run it in one shot, with per-step progress.
      </p>

      <h3>Add from a preset</h3>
      <ul className="recipe-presets" data-section="presets">
        {RECIPE_PRESETS.map((preset) => (
          <li key={preset.id} className="recipe-preset" data-preset={preset.id}>
            <span className="recipe-preset-name">{preset.name}</span>
            <span className="recipe-preset-desc">{preset.describe}</span>
            <button type="button" data-action="add-preset" onClick={() => void savePreset(preset)}>
              Save recipe
            </button>
          </li>
        ))}
      </ul>

      {listError && (
        <p className="error" role="alert">
          {listError}
        </p>
      )}
      {runError && (
        <p className="error" role="alert">
          {runError}
        </p>
      )}

      {runningId && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
          {jobId && (
            <button
              type="button"
              data-action="cancel"
              className="secondary"
              onClick={() => void cancel()}
            >
              Cancel
            </button>
          )}
        </div>
      )}

      <h3>Saved recipes</h3>
      <ul className="recipe-list" data-section="saved">
        {recipes.map((recipe) => (
          <li key={recipe.id} className="recipe-row" data-recipe={recipe.id}>
            <span className="recipe-name">{recipe.name}</span>
            <span className="recipe-steps">{recipe.steps.length} step(s)</span>
            <button
              type="button"
              data-action="run"
              data-recipe={recipe.id}
              onClick={() => void run(recipe.id)}
              disabled={Boolean(runningId)}
            >
              {runningId === recipe.id ? 'Running…' : 'Run'}
            </button>
            <button
              type="button"
              data-action="delete"
              data-recipe={recipe.id}
              className="secondary"
              onClick={() => void remove(recipe.id)}
              disabled={Boolean(runningId)}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
      {recipes.length === 0 && !listError && (
        <p className="asset-empty">No recipes yet — add one from a preset above.</p>
      )}
    </section>
  );
}

export default Recipes;
