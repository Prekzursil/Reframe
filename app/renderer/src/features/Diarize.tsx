// Diarize feature panel (system-advanced group, feature 4).
//
// Token-free speaker diarization: SpeechBrain VAD -> ECAPA -> greedy cosine
// clustering -> SPEAKER_NN labels on the transcript. Drives:
//   diarize.start({videoId, threshold?}) -> {jobId} -> job.done {transcript}
//
// The transcript must already exist (run Transcribe first); the result is the
// transcript with a `speaker` on each segment + a `speakers` roster, which this
// panel surfaces. The gated SpeechBrain models are on-demand assets (Assets
// tab); offline mode refuses the run when they are not yet installed. Consumes
// the FROZEN window.api bridge via the shared `./_api` helpers.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { getApi, pickField, waitForJobDone, type MediaStudioApi, type Segment } from './_api';

// The diarized transcript adds a per-segment `speaker` label + a `speakers`
// roster onto the §3 transcript shape. `Segment` already carries words/timings;
// `speaker` is the diarization addition.
export type DiarizedSegment = Segment & { speaker?: string };
export interface DiarizedTranscript {
  language: string;
  durationSec: number;
  segments: DiarizedSegment[];
  speakers?: string[];
}
export interface DiarizeDoneResult {
  transcript: DiarizedTranscript;
}

// --- pure helpers (exported for tests) -------------------------------------
/** The roster from a done transcript (empty when absent). */
export function extractSpeakers(result: unknown): string[] {
  const transcript = pickField<DiarizedTranscript>(result, 'transcript');
  return Array.isArray(transcript?.speakers) ? transcript!.speakers! : [];
}

/** Pull the §A3 job.done error payload message ({error:{message,type}}). */
export function doneErrorMessage(result: unknown): string | null {
  const err = pickField<{ message?: unknown }>(result, 'error');
  if (err && typeof err === 'object' && typeof err.message === 'string') {
    return err.message;
  }
  return null;
}

export interface DiarizeProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function Diarize({ videoId, api }: DiarizeProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [busy, setBusy] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [speakers, setSpeakers] = useState<string[]>([]);

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
    // defensive re-entrancy guard: the trigger button is `disabled={busy}`, so a
    // second run cannot be dispatched via UI while one is in flight.
    /* v8 ignore next */
    if (busy) return;
    setBusy(true);
    setError('');
    setSpeakers([]);
    setPct(0);
    setMessage('Starting…');
    try {
      const res = await bridge.rpc<{ jobId: string }>('diarize.start', { videoId });
      const id = res?.jobId ?? null;
      setJobId(id);
      const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const errMessage = doneErrorMessage(result);
      if (errMessage) {
        setError(errMessage);
      } else {
        setSpeakers(extractSpeakers(result));
        setPct(100);
        setMessage('Done');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      setJobId(null);
    }
  }, [bridge, videoId, busy]);

  const cancel = useCallback(async (): Promise<void> => {
    // defensive: the Cancel button renders only while `busy && jobId`, so cancel
    // is never invoked with a null jobId via UI.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  return (
    <section className="feature-panel diarize-panel" aria-label="Diarize">
      <h2>Speaker Diarization</h2>
      <p className="assets-intro">
        Label who speaks when — token-free, fully local. Needs a transcript first; the SpeechBrain
        models install on demand from the Assets tab.
      </p>

      <div className="actions">
        <button type="button" data-action="diarize" onClick={() => void run()} disabled={busy}>
          {busy ? 'Diarizing…' : 'Label speakers'}
        </button>
        {busy && jobId && (
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

      {busy && (
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

      {speakers.length > 0 && (
        <>
          <h3>Speakers found ({speakers.length})</h3>
          <ul className="speaker-list" data-section="speakers">
            {speakers.map((speaker) => (
              <li key={speaker} className="speaker-row" data-speaker={speaker}>
                {speaker}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export default Diarize;
