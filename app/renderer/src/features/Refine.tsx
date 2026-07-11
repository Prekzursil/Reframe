// Refine feature panel (system-advanced group) — "Tighten the edit".
//
// Descript-style "see before you cut": preview the proposed filler + silence
// removal (a NON-destructive cut-list with saved-seconds + per-category stats),
// tune the knobs, then Apply to write a NEW *.refined.mp4 (the original is never
// touched). Drives the WU-5 RPCs over the FROZEN window.api bridge:
//   refine.preview({videoId, removeFillers, removeSilence, noiseDb,
//                   minSilenceSec, mergeGapMs}) -> {plan}              (DIRECT)
//   refine.apply({...same...}) -> {jobId} -> job.done {path, removedSec, stats}
// preview is a fast/direct RPC (the plan resolves on the rpc promise); apply is
// a long job whose terminal payload arrives via the job.done notification, so we
// subscribe through `waitForJobDone`. Same shape as Diarize.tsx (getApi /
// bridge.rpc / waitForJobDone / onProgress / injectable `api?` prop for tests).
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { fmtSeconds, getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

// The pure refine plan (CONTRACTS.md §3 / refine.py RefinePlan): a union keep-list
// over original-video seconds + de-duplicated per-category stats.
export interface RefineStats {
  fillersRemoved: number;
  fillerSeconds: number;
  silenceRemovedSec: number;
  keptSec: number;
}
export interface RefinePlan {
  keeps: number[][];
  stats: RefineStats;
}

// --- pure helpers (exported for tests) -------------------------------------
/** The plan from a `refine.preview` result (null when absent/shapeless). */
export function extractPlan(result: unknown): RefinePlan | null {
  const plan = pickField<RefinePlan>(result, 'plan');
  if (plan && Array.isArray(plan.keeps) && plan.stats && typeof plan.stats === 'object') {
    return plan;
  }
  return null;
}

/** The output path from a `refine.apply` job.done result (null when missing). */
export function applyResultPath(result: unknown): string | null {
  const path = pickField<string>(result, 'path');
  return typeof path === 'string' ? path : null;
}

export interface RefineProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function Refine({ videoId, api }: RefineProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [removeFillers, setRemoveFillers] = useState<boolean>(true);
  const [removeSilence, setRemoveSilence] = useState<boolean>(true);
  const [noiseDb, setNoiseDb] = useState<number>(-30);
  const [minSilenceSec, setMinSilenceSec] = useState<number>(0.6);
  const [mergeGapMs, setMergeGapMs] = useState<number>(200);

  const [previewing, setPreviewing] = useState<boolean>(false);
  const [applying, setApplying] = useState<boolean>(false);
  const [plan, setPlan] = useState<RefinePlan | null>(null);
  const [resultPath, setResultPath] = useState<string>('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const params = useMemo(
    () => ({ videoId, removeFillers, removeSilence, noiseDb, minSilenceSec, mergeGapMs }),
    [videoId, removeFillers, removeSilence, noiseDb, minSilenceSec, mergeGapMs],
  );

  // "See before you cut" contract: any knob change makes the on-screen plan/stats
  // stale, so invalidate the preview — Apply is gated by `!plan` (below), so
  // clearing it re-disables Apply until a fresh Preview is run. This prevents
  // Apply from silently writing a cut that differs from every displayed number.
  const invalidatePreview = useCallback((): void => {
    setPlan(null);
    setResultPath('');
  }, []);

  const preview = useCallback(async (): Promise<void> => {
    // defensive: the button is disabled while previewing, so the UI cannot
    // dispatch a second preview in flight.
    /* v8 ignore next */
    if (previewing) return;
    setPreviewing(true);
    setError('');
    setResultPath('');
    try {
      const res = await bridge.rpc<unknown>('refine.preview', { ...params });
      setPlan(extractPlan(res ?? null));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewing(false);
    }
  }, [bridge, params, previewing]);

  const apply = useCallback(async (): Promise<void> => {
    // defensive: Apply is disabled until a plan exists and while a job runs.
    /* v8 ignore next */
    if (applying || !plan) return;
    setApplying(true);
    setError('');
    setResultPath('');
    setPct(0);
    setMessage('Starting…');
    try {
      const res = await bridge.rpc<{ jobId: string }>('refine.apply', { ...params });
      const id = res?.jobId ?? null;
      setJobId(id);
      // F1: waitForJobDone REJECTS on an {error} job.done payload (surfaced by
      // the catch below) — no more silent doneErrorMessage swallow.
      const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const path = applyResultPath(result);
      if (path) {
        setResultPath(path);
        setPct(100);
        setMessage('Done');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(false);
      setJobId(null);
    }
  }, [bridge, params, applying, plan]);

  const cancel = useCallback(async (): Promise<void> => {
    // defensive: Cancel renders only while `applying && jobId`.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  const stats = plan?.stats;

  return (
    <section className="feature-panel refine-panel" aria-label="Refine">
      <h2>Tighten the Edit</h2>
      <p className="assets-intro">
        Preview the dead air and filler words this will cut — token-free and fully local. Nothing is
        changed until you Apply; the result is written to a new file.
      </p>

      <div className="field">
        <label className="checkbox-field">
          <input
            type="checkbox"
            data-toggle="removeFillers"
            checked={removeFillers}
            onChange={(e) => {
              setRemoveFillers(e.target.checked);
              invalidatePreview();
            }}
          />
          Remove fillers
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            data-toggle="removeSilence"
            checked={removeSilence}
            onChange={(e) => {
              setRemoveSilence(e.target.checked);
              invalidatePreview();
            }}
          />
          Remove silence
        </label>
      </div>

      <div className="field">
        <label>
          Noise floor (dB)
          <input
            type="number"
            data-tune="noiseDb"
            value={noiseDb}
            onChange={(e) => {
              setNoiseDb(Number(e.target.value));
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Min silence (s)
          <input
            type="number"
            step="0.1"
            data-tune="minSilenceSec"
            value={minSilenceSec}
            onChange={(e) => {
              setMinSilenceSec(Number(e.target.value));
              invalidatePreview();
            }}
          />
        </label>
        <label>
          Merge gap (ms)
          <input
            type="number"
            data-tune="mergeGapMs"
            value={mergeGapMs}
            onChange={(e) => {
              setMergeGapMs(Number(e.target.value));
              invalidatePreview();
            }}
          />
        </label>
      </div>

      <div className="actions">
        <button
          type="button"
          data-action="preview"
          onClick={() => void preview()}
          disabled={previewing}
        >
          {previewing ? 'Previewing…' : 'Preview cut'}
        </button>
        <button
          type="button"
          data-action="apply"
          onClick={() => void apply()}
          disabled={applying || !plan}
        >
          {applying ? 'Applying…' : 'Apply'}
        </button>
        {applying && jobId && (
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

      {applying && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {stats && (
        <>
          <dl className="refine-stats" data-section="stats">
            <div>
              <dt>Saved</dt>
              <dd data-stat="savedSec">
                {fmtSeconds(Math.max(0, stats.silenceRemovedSec + stats.fillerSeconds))}
              </dd>
            </div>
            <div>
              <dt>Fillers removed</dt>
              <dd data-stat="fillersRemoved">{stats.fillersRemoved}</dd>
            </div>
            <div>
              <dt>Silence removed (s)</dt>
              <dd data-stat="silenceRemovedSec">{stats.silenceRemovedSec}</dd>
            </div>
            <div>
              <dt>Kept (s)</dt>
              <dd data-stat="keptSec">{stats.keptSec}</dd>
            </div>
          </dl>

          <h3>Keep ({plan.keeps.length} segments)</h3>
          <ul className="keep-list" data-section="keeps">
            {plan.keeps.map(([start, end]) => (
              <li key={`${start}-${end}`} className="keep-row">
                {fmtSeconds(start)} → {fmtSeconds(end)}
              </li>
            ))}
          </ul>
        </>
      )}

      {resultPath && (
        <div className="output-done" data-section="result">
          <span className="output-done-label">Refined file</span>
          <code>{resultPath}</code>
        </div>
      )}
    </section>
  );
}

export default Refine;
