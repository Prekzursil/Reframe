// Transcript-native editing pane (v1.5 flagship #2) — "delete a word, the video cuts".
//
// The Descript-class inspector: the transcript renders as clickable word tokens;
// striking a token marks it deleted, "Preview cut" asks the sidecar for the
// resulting keep-list WITHOUT encoding, "Apply" renders it ONCE to a NEW
// *.edited.mp4 (the source is never touched), and "Undo" pops that edit back off
// the project's reversible ledger.
//
// Drives the four RPCs over the FROZEN window.api bridge:
//   transcript.get({videoId})                -> {transcript}   (DIRECT)
//   transcript.previewEdit({videoId, edits}) -> {plan}          (DIRECT)
//   transcript.applyEdit({videoId, edits})   -> {jobId} -> job.done {path, editId, ...}
//   transcript.undoEdit({videoId, editId})   -> {editId, path}  (DIRECT)
//
// ALL selection/΄what-does-this-cut΄ math lives in the pure `lib/transcriptEdit`
// module (unit-tested standalone); this file is the thin view over it. Same
// bridge shape as Refine.tsx (getApi / bridge.rpc / waitForJobDone / onProgress
// / injectable `api?` prop for tests).
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import './transcriptEditor.css';
import {
  buildEditSpans,
  editedText,
  flattenWords,
  removedSeconds,
  toggleWord,
  type Transcript,
} from '../lib/transcriptEdit';
import { getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

/** The sidecar's TranscriptEditPlan (features/transcript_edit.py). */
export interface TranscriptEditPlan {
  keeps: number[][];
  stats: {
    wordsDeleted: number;
    deletedSec: number;
    fillersRemoved: number;
    fillerSeconds: number;
    silenceRemovedSec: number;
    keptSec: number;
    removedSec: number;
  };
  cues: unknown[];
  rejected: Array<{ index: number; op: string; reason: string }>;
}

/** The applied-edit receipt (`transcript.applyEdit` job.done). */
export interface ApplyReceipt {
  path: string;
  editId: string | null;
}

// --- pure helpers (exported for tests) -------------------------------------
/** The transcript from a `transcript.get` result (null when absent/shapeless). */
export function extractTranscript(result: unknown): Transcript | null {
  const transcript = pickField<Transcript>(result, 'transcript');
  if (transcript && Array.isArray(transcript.segments)) return transcript;
  return null;
}

/** The plan from a `transcript.previewEdit` result (null when shapeless). */
export function extractPlan(result: unknown): TranscriptEditPlan | null {
  const plan = pickField<TranscriptEditPlan>(result, 'plan');
  if (plan && Array.isArray(plan.keeps) && plan.stats && typeof plan.stats === 'object') {
    return plan;
  }
  return null;
}

/** The `{path, editId}` receipt from an applyEdit job.done (null without a path). */
export function extractApply(result: unknown): ApplyReceipt | null {
  const path = pickField<string>(result, 'path');
  if (typeof path !== 'string') return null;
  const editId = pickField<string>(result, 'editId');
  return { path, editId: typeof editId === 'string' ? editId : null };
}

/** A rejected RPC's human message — a non-Error throw still reads sensibly. */
export function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The path a `transcript.undoEdit` result restores to ('' when it names none). */
export function undoPath(result: unknown): string {
  const path = pickField<string>(result, 'path');
  return typeof path === 'string' ? path : '';
}

export interface TranscriptEditorProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function TranscriptEditor({ videoId, api }: TranscriptEditorProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [loading, setLoading] = useState<boolean>(true);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [deleted, setDeleted] = useState<ReadonlySet<string>>(() => new Set<string>());
  const [plan, setPlan] = useState<TranscriptEditPlan | null>(null);
  const [previewing, setPreviewing] = useState<boolean>(false);
  const [applying, setApplying] = useState<boolean>(false);
  const [resultPath, setResultPath] = useState<string>('');
  const [editId, setEditId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const res = await bridge.rpc<unknown>('transcript.get', { videoId });
        if (live) setTranscript(extractTranscript(res));
      } catch (err) {
        if (live) setError(errMessage(err));
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [bridge, videoId]);

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const words = useMemo(() => flattenWords(transcript), [transcript]);
  const edits = useMemo(() => buildEditSpans(words, deleted), [words, deleted]);

  // "See before you cut": changing the selection makes the on-screen plan stale,
  // so drop it — Apply is gated on `!plan`, which re-disables it until a fresh
  // Preview runs. Apply can therefore never write a cut that differs from the
  // numbers on screen.
  const strike = useCallback((wordId: string): void => {
    setDeleted((prev) => toggleWord(prev, wordId));
    setPlan(null);
  }, []);

  const preview = useCallback(async (): Promise<void> => {
    // defensive: the button is disabled while a preview is in flight.
    /* v8 ignore next */
    if (previewing) return;
    setPreviewing(true);
    setError('');
    try {
      const res = await bridge.rpc<unknown>('transcript.previewEdit', { videoId, edits });
      setPlan(extractPlan(res));
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setPreviewing(false);
    }
  }, [bridge, videoId, edits, previewing]);

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
      const res = await bridge.rpc<unknown>('transcript.applyEdit', { videoId, edits });
      const id = pickField<string>(res, 'jobId');
      setJobId(id);
      const done = id ? await waitForJobDone<unknown>(bridge, id, (r) => r) : null;
      const receipt = extractApply(done);
      if (receipt) {
        setResultPath(receipt.path);
        setEditId(receipt.editId);
        setPct(100);
        setMessage('Done');
      }
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setApplying(false);
      setJobId(null);
    }
  }, [bridge, videoId, edits, applying, plan]);

  const undo = useCallback(async (): Promise<void> => {
    // defensive: Undo renders disabled until an edit has been applied.
    /* v8 ignore next */
    if (!editId) return;
    setError('');
    try {
      const res = await bridge.rpc<unknown>('transcript.undoEdit', { videoId, editId });
      setResultPath(undoPath(res));
      setEditId(null);
      setMessage('Undone');
    } catch (err) {
      setError(errMessage(err));
    }
  }, [bridge, videoId, editId]);

  return (
    <section className="feature-panel transcript-panel" aria-label="Transcript">
      <h2>Transcript Editing</h2>
      <p className="assets-intro">
        Strike a word and the video cuts there — fully local, nothing is changed until you Apply,
        and the result is written to a new file so the original is never touched.
      </p>

      {loading && <p data-state="loading">Loading transcript…</p>}
      {!loading && words.length === 0 && (
        <p data-state="empty">No transcript yet — transcribe this video first.</p>
      )}

      {words.length > 0 && (
        <>
          <div className="transcript-tokens" data-section="tokens">
            {words.map((w) => (
              <button
                key={w.wordId}
                type="button"
                className="transcript-token"
                data-word-id={w.wordId}
                data-deleted={deleted.has(w.wordId) ? 'true' : 'false'}
                aria-pressed={deleted.has(w.wordId)}
                onClick={() => strike(w.wordId)}
              >
                {w.text}
              </button>
            ))}
          </div>
          <dl className="transcript-summary">
            <div>
              <dt>Struck (s)</dt>
              <dd data-stat="removedSec">{removedSeconds(words, deleted)}</dd>
            </div>
          </dl>
          <p className="transcript-edited" data-section="editedText">
            {editedText(words, deleted)}
          </p>
        </>
      )}

      <div className="actions">
        <button
          type="button"
          data-action="preview"
          onClick={() => void preview()}
          disabled={previewing || edits.length === 0}
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
        <button
          type="button"
          data-action="undo"
          className="secondary"
          onClick={() => void undo()}
          disabled={!editId}
        >
          Undo
        </button>
      </div>

      {applying && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          <span className="progress-message"> · {message}</span>
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {plan && (
        <dl className="transcript-plan" data-section="plan">
          <div>
            <dt>Cut (s)</dt>
            <dd data-stat="planRemovedSec">{plan.stats.removedSec}</dd>
          </div>
          <div>
            <dt>Kept segments</dt>
            <dd data-stat="keeps">{plan.keeps.length}</dd>
          </div>
          {plan.rejected.length > 0 && (
            <div>
              <dt>Ignored</dt>
              <dd data-stat="rejected">{plan.rejected.map((r) => r.reason).join(', ')}</dd>
            </div>
          )}
        </dl>
      )}

      {resultPath && (
        <div className="output-done" data-section="result">
          <span className="output-done-label">Current cut</span>
          <code>{resultPath}</code>
          {editId && <span data-stat="editId">{editId}</span>}
        </div>
      )}
    </section>
  );
}

export default TranscriptEditor;
