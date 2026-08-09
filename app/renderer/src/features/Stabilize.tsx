// Stabilize feature panel — "Steady the shot" (per-video camera-shake removal).
//
// WHY THIS PANEL EXISTS (measured, not assumed).
// `docs/plans/v1.5/competitor-matrix-2026-08.md:166,219` lists `stabilize.run`
// as built-and-registered but unreachable. That was MEASURED before wiring, with
// a detector proven against a known-present control:
//   probe  : Select-String -SimpleMatch over app/**/*.{ts,tsx,js,json,html}
//   control: "shortmaker.export" -> 4 hits (the detector fires)
//   target : "stabilize.run"     -> 0 hits (genuinely unreferenced)
// Corroborating signal: the sidecar already provisions a dedicated output
// directory for standalone runs (`handlers/library_ops.py:418` "stabilized") and
// registers the RPC (`features/stabilize.py:496`) — engine, RPC and output path
// are all paid for; only the surface was missing. Before this panel the ONLY way
// to stabilize was the all-or-nothing ShortMaker export pre-step
// (`ShortMakerControls.tsx:284-293` -> `shortMakerPresets.ts:185`), which cannot
// steady an arbitrary library clip.
//
// The two SIBLING items in the same audit row were measured as FALSE GAPS and
// are deliberately NOT wired here:
//   - `silence.trim`: the capability already ships twice — `Refine.tsx` (preview
//     + tunables, via refine.preview/apply) and the ShortMaker "Trim silence"
//     toggle. `docs/plans/_archive/editing-refine/DESIGN.md:133` states the
//     unreferenced literal is intentional back-compat, with `refine.*` as the
//     replacement surface. A second silence UI would rebuild a removed duplicate.
//   - hook-title generation: the matrix claim (`:148`, `:304`) is that the LLM
//     TEXT-GEN step is missing, not the UI. Refuted — `features/select.py:344-345`
//     pins "hook" in the JSON schema the model must return.
//
// TRANSPORT: `stabilize.run({videoId}) -> {jobId}`; the terminal payload
// `{path, stabilized[, notice]}` arrives on the LATER `job.done` notification,
// never on the rpc promise (see `_api.ts` CONTRACT-NOTE), so we subscribe via
// `waitForJobDone`. Same shape as `Refine.tsx` (getApi / bridge.rpc /
// waitForJobDone / onProgress / injectable `api?` prop for tests).
//
// The engine takes NO tunables over the wire — `stabilize.run` accepts only
// `{videoId|path}` (`features/stabilize.py:430`); shakiness/smoothing/accuracy
// come from settings. So this panel is deliberately a single action, not a
// knob-farm that would imply per-run control the RPC does not accept.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

/**
 * The typed skip notice the sidecar emits when the bundled ffmpeg has no
 * libvidstab (`stabilize.py` `make_unavailable_notice`). The sidecar REPORTS
 * that case rather than silently passing the clip through, so the UI must
 * surface it distinctly — never as a success.
 */
export interface StabilizeNotice {
  type: string;
  message: string;
}

/** The `job.done` payload of `stabilize.run` (`stabilize.py:433`). */
export interface StabilizeOutcome {
  /** The steadied clip, or the untouched source when `stabilized` is false. */
  path: string;
  stabilized: boolean;
  notice: StabilizeNotice | null;
}

// --- pure helpers (exported for tests) -------------------------------------
/**
 * Read a `stabilize.run` job.done result. Null when there is no usable `path`
 * (a shapeless or error payload) so the panel renders nothing rather than junk.
 * A non-`true` `stabilized` flag is treated as NOT stabilized (fail closed), and
 * a notice that is not an object with a string `message` is dropped.
 */
export function stabilizeOutcome(result: unknown): StabilizeOutcome | null {
  const path = pickField<string>(result, 'path');
  if (typeof path !== 'string' || !path) return null;
  const raw = pickField<unknown>(result, 'notice');
  const notice =
    raw !== null && typeof raw === 'object' && typeof (raw as StabilizeNotice).message === 'string'
      ? (raw as StabilizeNotice)
      : null;
  return {
    path,
    stabilized: pickField<boolean>(result, 'stabilized') === true,
    notice,
  };
}

export interface StabilizeProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function Stabilize({ videoId, api }: StabilizeProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [running, setRunning] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<StabilizeOutcome | null>(null);
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

  const run = useCallback(async (): Promise<void> => {
    // defensive: the button is disabled while a run is in flight, so the UI
    // cannot dispatch a second one.
    /* v8 ignore next */
    if (running) return;
    setRunning(true);
    setError('');
    setOutcome(null);
    setPct(0);
    setMessage('Starting…');
    try {
      const res = await bridge.rpc<{ jobId: string }>('stabilize.run', { videoId });
      const id = res?.jobId ?? null;
      setJobId(id);
      // waitForJobDone REJECTS on an {error} job.done payload (caught below) —
      // a failed stabilization is never laundered into a silent success.
      const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const next = stabilizeOutcome(result);
      if (next) {
        setOutcome(next);
        setPct(100);
        setMessage(next.stabilized ? 'Done' : 'Skipped');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
      setJobId(null);
    }
  }, [bridge, videoId, running]);

  const cancel = useCallback(async (): Promise<void> => {
    // defensive: Cancel renders only while `running && jobId`.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort — a failed cancel must not become a panel error.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  return (
    <section className="feature-panel stabilize-panel" aria-label="Stabilize">
      <h2>Steady the Shot</h2>
      <p className="assets-intro">
        Remove camera shake from this video with a two-pass vidstab analyse-then-warp — token-free
        and fully local. The original is never touched; the steadied clip is written to a new file.
      </p>

      <div className="actions">
        <button type="button" data-action="run" onClick={() => void run()} disabled={running}>
          {running ? 'Stabilizing…' : 'Stabilize'}
        </button>
        {running && jobId && (
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

      {running && (
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

      {/* The libvidstab-missing case is REPORTED, never silently skipped: the
          source path came back unchanged, so it is NOT shown as a result. */}
      {outcome?.notice && (
        <p className="stabilize-notice" data-section="notice" role="status">
          {outcome.notice.message}
        </p>
      )}

      {outcome?.stabilized && (
        <div className="output-done" data-section="result">
          <span className="output-done-label">Stabilized file</span>
          <code>{outcome.path}</code>
        </div>
      )}
    </section>
  );
}

export default Stabilize;
