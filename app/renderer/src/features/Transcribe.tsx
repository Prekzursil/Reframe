// Transcribe feature panel.
//
// Calls the sidecar `transcribe.start` method (CONTRACTS.md §2) and shows
// streaming progress (`job.progress` / `job.done`). Consumes the frozen
// `window.api` surface via the shared local types in `./_api`.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './panels.css';
import {
  DEFAULT_JOB_TIMEOUT_MS,
  JobAbortedError,
  type Transcript,
  getApi,
  pickField,
  waitForJobDone,
} from './_api';
import { LanguageSelect } from '../components/LanguageSelect';
import { AUTO_DETECT, toWireLanguage } from '../lib/languages';

export interface TranscribeProps {
  videoId: string;
  /**
   * Optional callback fired with the transcript produced by a RUN in this panel.
   *
   * W11 SCOPED DECISION: the mount-time re-hydrate below deliberately does NOT
   * fire this. The persisted transcript comes from `project.open`, which the
   * Workspace parent already calls for itself (Workspace.tsx:197-209), so
   * echoing it back would hand a parent its own data as if this panel had just
   * produced it. Same reasoning as Subtitles.tsx:126-128 (hydrate with
   * `setTrack`, never `applyTrack`). Consumers that need "does a transcript
   * exist" read `video.hasTranscript` / `project.transcript`, not this callback.
   */
  onTranscript?: (transcript: Transcript) => void;
}

type Phase = 'idle' | 'running' | 'done' | 'error';

/**
 * W11 mount-time read of the PERSISTED transcript:
 *   'loading' — `project.open` is in flight; we do not yet know either way;
 *   'ready'   — the read landed (with or without a transcript);
 *   'error'   — the read failed; the panel still works, it just cannot show a
 *               previously-saved transcript.
 */
type LoadState = 'loading' | 'ready' | 'error';

/** The `project.open` reply shape this panel reads (CONTRACTS.md §2/§3). */
interface ProjectOpenResult {
  project?: { transcript?: Transcript };
}

export function Transcribe({ videoId, onTranscript }: TranscribeProps): React.ReactElement {
  const [language, setLanguage] = useState<string>(AUTO_DETECT);
  const [phase, setPhase] = useState<Phase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [loadState, setLoadState] = useState<LoadState>(videoId ? 'loading' : 'ready');
  const [loadError, setLoadError] = useState<string>('');

  // W11: RE-HYDRATE the persisted transcript at mount (and on a videoId change).
  //
  // `transcribe.start` persists its result onto the video's project manifest and
  // flips the library `hasTranscript` flag (sidecar
  // handlers/media_ops.py:480-488 `_transcribe_and_persist`), and
  // `project.open({id})` hands it back as `{project:{transcript}}`
  // (handlers/library_ops.py:328-337). Before this effect the ONLY writer of
  // `transcript` was the run below, so re-entering the tab after a finished run
  // showed the blank state and offered an accent primary action to re-run a
  // multi-minute GPU job — while the Library card next to it said "Transcript".
  // Same mount-time-read shape as Tracks.tsx:51-53 (`tracks.list`).
  useEffect(() => {
    if (!videoId) {
      setLoadState('ready');
      setLoadError('');
      setTranscript(null);
      return;
    }
    // Guards the STALE reply: switching video mid-read must not let the previous
    // video's transcript land on the new one (it would look re-hydrated and let
    // the user skip a transcription that never happened for this video).
    //
    // It MUST be a per-effect-run closure flag, not a component-lifetime ref:
    // `main.tsx:19` runs the app under <React.StrictMode>, whose setup -> cleanup
    // -> setup would leave a surviving flag latched `true` and discard BOTH reads,
    // stranding the panel on "Loading saved transcript…" forever in dev.
    let stale = false;
    setLoadState('loading');
    setLoadError('');
    setTranscript(null);
    void (async () => {
      try {
        const res = await getApi().rpc<ProjectOpenResult | null>('project.open', { id: videoId });
        if (stale) return;
        setTranscript(res?.project?.transcript ?? null);
        setLoadState('ready');
      } catch (err) {
        if (stale) return;
        setLoadError(err instanceof Error ? err.message : String(err));
        setLoadState('error');
      }
    })();
    return () => {
      stale = true;
    };
  }, [videoId]);

  // F2: aborts the in-flight job.done wait on cancel/unmount so the wait rejects
  // (JobAbortedError) and its subscription/timer tear down instead of leaking —
  // and a user cancel never waits out the 15-min timeout into a bogus error.
  const abortRef = useRef<AbortController | null>(null);

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
    // Clear any prior run's jobId immediately so a mid-flight Cancel (or the
    // gate below) can never target a previous, already-finished job.
    setJobId(null);
    setError('');
    setPct(0);
    setMessage('Starting…');
    setTranscript(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const params: Record<string, unknown> = { videoId };
      // CONTRACT-NOTE: the BCP-47 language hint is optional in `transcribe.start`
      // ({videoId, language?}) and AUTO-DETECT IS THE ABSENCE OF THE FIELD. The
      // sidecar validates `language` only as "a string when given" and hands it
      // straight to faster-whisper, so sending the literal "auto" would have it
      // read as a language id. `toWireLanguage` is that translation.
      const wireLanguage = toWireLanguage(language);
      if (wireLanguage !== undefined) params.language = wireLanguage;
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
        // F2: the wait carries the DEFAULT timeout + the cancel/unmount signal so
        // a dead sidecar can't hang the panel and a cancel tears it down at once.
        transcript = await waitForJobDone(
          getApi(),
          id,
          (r) => pickField<Transcript>(r, 'transcript'),
          DEFAULT_JOB_TIMEOUT_MS,
          ctrl.signal,
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
      // F2: an aborted wait is a clean cancel — cancel() already reset to idle,
      // so surface no error/phase change (the finally leaves the idle state).
      if (err instanceof JobAbortedError) return;
      setError(err instanceof Error ? err.message : String(err));
      setPhase('error');
    } finally {
      // F1/F2: a job that finished with neither a transcript nor an error (or a
      // timed-out wait) must NOT stick on 'running' forever — drop back to idle.
      setPhase((p) => (p === 'running' ? 'idle' : p));
      // Leave no stale jobId behind and release the run's abort controller.
      setJobId(null);
      abortRef.current = null;
    }
  }, [videoId, language, onTranscript]);

  // F2: abort any in-flight job.done wait (cancel/unmount) so the wait rejects
  // with JobAbortedError and its subscription/timer tear down instead of leaking.
  const tearDownWait = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const cancel = useCallback(async () => {
    // Tear the in-flight wait down FIRST so it rejects immediately, even if the
    // job.cancel rpc throws. The Cancel button renders only while running with a
    // known jobId (see the gate below), so jobId is always present here.
    tearDownWait();
    try {
      await getApi().rpc('job.cancel', { jobId });
    } catch {
      // Cancellation is best-effort; the job may already have finished.
    }
    setPhase('idle');
    setMessage('Cancelled');
  }, [jobId, tearDownWait]);

  // F2: tear down any in-flight job wait when the panel unmounts (no leak).
  useEffect(() => tearDownWait, [tearDownWait]);

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
        {/* The shared picker, NOT a second hardcoded list. This panel used to
            declare its own 9-language array with a different auto sentinel ('' vs
            'auto') and never import lib/languages at all (audit §1.1). */}
        <LanguageSelect
          id="transcribe-language"
          value={language}
          onChange={setLanguage}
          disabled={running}
        />
      </div>

      <div className="actions">
        {/* W11: with a transcript already on disk, re-running is a MULTI-MINUTE
            GPU job the user has already paid for — so the action drops out of
            the accent primary slot and says what it actually does. It stays
            enabled (a re-run is legitimate: a different language, a fixed
            audio track, a new ASR engine), just no longer invited. */}
        <button
          type="button"
          onClick={start}
          className={transcript ? 'secondary' : undefined}
          disabled={running || !videoId || loadState === 'loading'}
        >
          {running ? 'Transcribing…' : transcript ? 'Re-run transcription' : 'Start transcription'}
        </button>
        {running && jobId && (
          <button type="button" onClick={cancel} className="secondary">
            Cancel
          </button>
        )}
      </div>

      {loadState === 'loading' && (
        <p className="status" data-state="loading" aria-live="polite">
          Loading saved transcript…
        </p>
      )}

      {/* A failed READ is not a failed RUN: it is shown in the error voice (the
          saved transcript is genuinely unavailable) but carries no role="alert"
          — it is present at first paint, not a response to a user action — and
          it never disables Start. */}
      {loadState === 'error' && (
        <p className="error" data-state="load-error">
          Could not load the saved transcript: {loadError}
        </p>
      )}

      {loadState === 'ready' && !transcript && !running && (
        <p className="empty" data-state="empty">
          No transcript yet — run a transcription to create one.
        </p>
      )}

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
