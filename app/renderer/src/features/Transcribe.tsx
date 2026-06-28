// Transcribe feature panel.
//
// Calls the sidecar `transcribe.start` method (CONTRACTS.md §2) and shows
// streaming progress (`job.progress` / `job.done`). Consumes the frozen
// `window.api` surface via the shared local types in `./_api`.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { type Transcript, getApi, pickField, waitForJobDone } from './_api';

export interface TranscribeProps {
  videoId: string;
  /** Optional callback fired with the finished transcript. */
  onTranscript?: (transcript: Transcript) => void;
}

type Phase = 'idle' | 'running' | 'done' | 'error';

// CONTRACT-NOTE: BCP-47 language hint is optional in `transcribe.start`
// ({videoId, language?}); empty = auto-detect (sent as undefined, not "").
const LANGUAGES: Array<{ code: string; label: string }> = [
  { code: '', label: 'Auto-detect' },
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Spanish' },
  { code: 'fr', label: 'French' },
  { code: 'de', label: 'German' },
  { code: 'it', label: 'Italian' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'ja', label: 'Japanese' },
  { code: 'ko', label: 'Korean' },
  { code: 'zh', label: 'Chinese' },
];

export function Transcribe({ videoId, onTranscript }: TranscribeProps): React.ReactElement {
  const [language, setLanguage] = useState<string>('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [transcript, setTranscript] = useState<Transcript | null>(null);

  // Relay sidecar progress notifications for THIS job only.
  useEffect(() => {
    if (!jobId) return;
    const off = getApi().onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [jobId]);

  const start = useCallback(async () => {
    setPhase('running');
    setError('');
    setPct(0);
    setMessage('Starting…');
    setTranscript(null);
    try {
      const params: Record<string, unknown> = { videoId };
      if (language) params.language = language;
      // §2 long job: rpc resolves IMMEDIATELY with {jobId} only; the terminal
      // {transcript} arrives later as a `job.done` notification. So we read the
      // jobId for progress/cancel, then await job.done for the transcript
      // (copying ShortMaker.tsx's working onJobDone pattern).
      const res = await getApi().rpc<{ jobId: string; transcript?: Transcript }>(
        'transcribe.start',
        params,
      );
      const id = res.jobId;
      setJobId(id);
      // Fast-path: if the sidecar ever inlines the result, honor it.
      let transcript = res.transcript ?? null;
      if (!transcript && id) {
        transcript = await waitForJobDone(getApi(), id, (r) =>
          pickField<Transcript>(r, 'transcript'),
        );
      }
      if (transcript) {
        setTranscript(transcript);
        setPct(100);
        setMessage('Done');
        setPhase('done');
        onTranscript?.(transcript);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase('error');
    } finally {
      // F1/F2: a job that finished with neither a transcript nor an error (or a
      // timed-out wait) must NOT stick on 'running' forever — drop back to idle.
      setPhase((p) => (p === 'running' ? 'idle' : p));
    }
  }, [videoId, language, onTranscript]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    try {
      await getApi().rpc('job.cancel', { jobId });
    } catch {
      // Cancellation is best-effort; the job may already have finished.
    }
    setPhase('idle');
    setMessage('Cancelled');
  }, [jobId]);

  const running = phase === 'running';
  const wordCount = useMemo(
    () => (transcript ? transcript.segments.reduce((n, s) => n + s.words.length, 0) : 0),
    [transcript],
  );

  return (
    <section className="feature-panel transcribe-panel" aria-label="Transcribe">
      <h2>Transcribe</h2>

      <div className="field">
        <label htmlFor="transcribe-language">Language</label>
        <select
          id="transcribe-language"
          value={language}
          disabled={running}
          onChange={(e) => setLanguage(e.target.value)}
        >
          {LANGUAGES.map((l) => (
            <option key={l.code || 'auto'} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </div>

      <div className="actions">
        <button type="button" onClick={start} disabled={running || !videoId}>
          {running ? 'Transcribing…' : 'Start transcription'}
        </button>
        {running && (
          <button type="button" onClick={cancel} className="secondary">
            Cancel
          </button>
        )}
      </div>

      {(running || phase === 'done') && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {phase === 'error' && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {transcript && (
        <div className="transcript-summary">
          <p>
            Language: <strong>{transcript.language}</strong> · Duration:{' '}
            <strong>{transcript.durationSec.toFixed(1)}s</strong> · Segments:{' '}
            <strong>{transcript.segments.length}</strong> · Words: <strong>{wordCount}</strong>
          </p>
          <ol className="transcript-segments">
            {transcript.segments.map((seg, i) => (
              <li key={`${seg.start}-${i}`}>
                <span className="seg-time">
                  {seg.start.toFixed(1)}–{seg.end.toFixed(1)}s
                </span>{' '}
                {seg.text}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

export default Transcribe;
