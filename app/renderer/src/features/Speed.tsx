// Speed feature panel — "Change the speed" (slow motion / speed up).
//
// WHY THIS EXISTS. The re-time engine has been sound for a long time
// (`director_op_engines.build_retime_argv`: `setpts=(1/factor)*PTS` plus a legal
// `atempo` chain so picture and sound stay in sync, with `retime` in
// WIRED_KINDS) — but nothing could reach it. There was no speed RPC and no speed
// control in ANY renderer panel, so the only path to a slow-motion clip was to
// phrase a prompt at the AI Director and hope the planner emitted a `retime` op.
// This panel plus `speed.retime` is the direct route.
//
// Drives ONE RPC over the FROZEN window.api bridge:
//   speed.retime({videoId, factor}) -> {jobId}
//     -> job.done {path, factor, sourceDurationSec, durationSec}
// A long job, so the terminal payload arrives on the `job.done` notification and
// is read through the shared `waitForJobDone` (same shape as Refine/Diarize).
//
// SCOPE, and it is on screen as well as in this comment: the speed is CONSTANT
// over the whole clip. A keyframed speed RAMP (piecewise `setpts` with
// segment-wise audio resampling) is a different engine that does not exist in
// this tree, so the UI must not imply one — `speedPresets.test.ts` asserts no
// preset advertises a ramp, and the panel copy says "constant" out loud.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { fmtSeconds, getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';
import {
  SPEED_MAX,
  SPEED_MIN,
  SPEED_PRESETS,
  clampFactor,
  isRetimeFactor,
  retimedDuration,
  speedLabel,
} from '../lib/speedPresets';

/**
 * The speed the panel opens on. A SPEED-UP, because "this drags, tighten it" is
 * the common ask, and it must never be 1.0 — that is the one value the sidecar
 * rejects, so opening on it would present a dead Apply button.
 */
export const DEFAULT_SPEED_FACTOR = 2;

/** Shown when there is no duration to show — an unknown length is not "0:00". */
const NO_DURATION = '—';

/** The output path from a `speed.retime` job.done result (null when missing). */
export function speedResultPath(result: unknown): string | null {
  const path = pickField<string>(result, 'path');
  return typeof path === 'string' ? path : null;
}

export interface SpeedProps {
  videoId: string;
  /**
   * Source length, used ONLY for the before/after prediction. Optional: when the
   * caller does not know it the panel shows a dash rather than inventing a
   * number, and the re-time still works (the sidecar probes for itself).
   */
  sourceDurationSec?: number;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function Speed({ videoId, sourceDurationSec, api }: SpeedProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [factor, setFactor] = useState<number>(DEFAULT_SPEED_FACTOR);
  const [applying, setApplying] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [resultPath, setResultPath] = useState<string>('');

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const source = sourceDurationSec ?? 0;
  const predicted = retimedDuration(source, factor);
  // The sidecar's `resolve_factor` is the authority and REJECTS a bad factor;
  // gating Apply on the same rule means a doomed request never leaves the UI.
  const sendable = isRetimeFactor(factor);

  const onCustomFactor = useCallback((raw: string): void => {
    // A cleared field is not "0.1x" — Number('') is 0, which would clamp to the
    // floor and silently arm an extreme slow-motion. Blank means "no choice yet",
    // so it lands on the neutral 1x (which then disables Apply).
    setFactor(clampFactor(raw === '' ? Number.NaN : Number(raw)));
  }, []);

  const apply = useCallback(async (): Promise<void> => {
    // defensive: Apply is disabled while a job runs and at an unsendable factor.
    /* v8 ignore next */
    if (applying || !sendable) return;
    setApplying(true);
    setError('');
    setResultPath('');
    setPct(0);
    setMessage('Starting…');
    try {
      const res = await bridge.rpc<{ jobId: string }>('speed.retime', { videoId, factor });
      const id = res?.jobId ?? null;
      setJobId(id);
      // waitForJobDone REJECTS on an {error} job.done payload, so a failed
      // re-time surfaces in the catch below instead of looking like a silent no-op.
      const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const path = speedResultPath(result);
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
  }, [bridge, videoId, factor, applying, sendable]);

  const cancel = useCallback(async (): Promise<void> => {
    // defensive: Cancel renders only while `applying && jobId`.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort: the job may already have finished.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  return (
    <section className="feature-panel speed-panel" aria-label="Speed">
      <h2>Change the Speed</h2>
      <p className="assets-intro">
        Re-time the whole clip at one constant speed — picture and sound stay in sync. The original
        is never touched; the result is written to a new file.
      </p>

      <div className="field" role="group" aria-label="Speed presets">
        {SPEED_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            data-preset={preset.id}
            aria-pressed={factor === preset.factor}
            onClick={() => setFactor(preset.factor)}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="field">
        <label>
          Custom speed ({SPEED_MIN}x – {SPEED_MAX}x)
          <input
            type="number"
            step="0.05"
            min={SPEED_MIN}
            max={SPEED_MAX}
            data-tune="factor"
            value={factor}
            onChange={(e) => onCustomFactor(e.target.value)}
          />
        </label>
        <span className="speed-readout" data-field="factorLabel">
          {speedLabel(factor)}
        </span>
      </div>

      <dl className="speed-preview" data-section="preview">
        <div>
          <dt>Now</dt>
          <dd data-field="sourceDuration">{source > 0 ? fmtSeconds(source) : NO_DURATION}</dd>
        </div>
        <div>
          <dt>After</dt>
          <dd data-field="newDuration">{predicted > 0 ? fmtSeconds(predicted) : NO_DURATION}</dd>
        </div>
      </dl>

      {!sendable && (
        <p className="hint" data-field="noop">
          1x is no change — pick a slower or faster speed to enable Apply.
        </p>
      )}

      <div className="actions">
        <button
          type="button"
          data-action="apply"
          onClick={() => void apply()}
          disabled={applying || !sendable}
        >
          {applying ? 'Re-timing…' : 'Apply speed'}
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

      {resultPath && (
        <div className="output-done" data-section="result">
          <span className="output-done-label">Re-timed file</span>
          <code>{resultPath}</code>
        </div>
      )}
    </section>
  );
}

export default Speed;
