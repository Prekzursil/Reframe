// Export.tsx — the Phase-5 EXPORT view (v1.5 §4): a per-video render as a GUARDED
// COMMIT, and the ONE irreversible, spend/file-writing action.
//
// The integration point: it seeds the shared EditorContext from the open video,
// best-effort loads that video's cues (so the stage summarizes the captions being
// baked), and composes the shared Stage + the guarded-commit Inspector. On the
// explicit confirm it starts the LOCAL render (`client.convert.start`), tracks
// DETERMINATE progress (`onProgress`), waits for the terminal file
// (`waitForJobDone`), and offers a REAL cancel (`job.cancel` + an abort). Terminal
// SUCCESS wires the output file to a "Show in folder" reveal and links INTO Deliver;
// terminal FAILURE/cancel surface an assertive alert with a recovery action.
//
// Division of labour (§4): this is Phase-5 (finish ONE video). The rail "Deliver"
// owns cross-video/batch publish; finishing here links into it via `onDeliver`.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { type ConvertOptions, type Video, client, hasApi, onJobDone, onProgress } from '../lib/rpc';
import type { EditorSeed } from '../lib/editorState';
import {
  DEFAULT_JOB_TIMEOUT_MS,
  JobAbortedError,
  pickField,
  waitForJobDone,
} from '../features/_api';
import { EditorProvider, useEditor } from '../features/EditorContext';
import { ExportStage } from '../features/export/ExportStage';
import { ExportInspector } from '../features/export/ExportInspector';
import { ExportProgress } from '../features/export/ExportProgress';
import { ExportResult, type ExportOutcome } from '../features/export/ExportResult';
import type { PlatformPreset } from '../features/export/exportModel';
import './export.css';

/** idle → running → a terminal outcome (done / failed / cancelled). */
type ExportPhase = 'idle' | 'running' | ExportOutcome;

/** Resolve the OS "reveal in folder" bridge (window.api.openInFolder), or null. */
function openInFolderBridge(): ((path: string) => Promise<boolean>) | null {
  const api = (globalThis as { window?: { api?: { openInFolder?: unknown } } }).window?.api;
  return api && typeof api.openInFolder === 'function'
    ? (api.openInFolder as (path: string) => Promise<boolean>)
    : null;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export interface ExportProps {
  video: Video | null;
  onBack: () => void;
  /** Continue into the Deliver (batch/cross-video) surface after a finish. */
  onDeliver: () => void;
}

/** Inner workspace: a context consumer that loads cues + drives the guarded render. */
function ExportWorkspace({
  video,
  onBack,
  onDeliver,
}: {
  video: Video;
  onBack: () => void;
  onDeliver: () => void;
}): React.ReactElement {
  const { dispatch } = useEditor();
  const [phase, setPhase] = useState<ExportPhase>('idle');
  const [pct, setPct] = useState(0);
  const [message, setMessage] = useState('');
  const [paths, setPaths] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [destination, setDestination] = useState('');
  const jobId = useRef<string | null>(null);
  // A live controller is always present (replaced per commit) so `cancel` never
  // needs a null guard — a stale abort with nothing awaiting it is harmless.
  const abort = useRef<AbortController>(new AbortController());

  // Best-effort: load the cues being exported so the stage can summarize them. The
  // export never REQUIRES captions, so a load failure is silently non-blocking.
  useEffect(() => {
    if (!hasApi()) return;
    void client.captions
      .cues(video.id)
      .then((res) => dispatch({ type: 'setCues', cues: res.cues ?? [] }))
      .catch(() => {
        // best-effort: the clip still exports without a caption summary.
      });
  }, [video.id, dispatch]);

  const onCommit = useCallback(
    async (preset: PlatformPreset, options: ConvertOptions): Promise<void> => {
      if (!hasApi()) return;
      setPhase('running');
      setPct(0);
      setMessage('Starting…');
      setDestination(preset.name);
      setPaths([]);
      setError('');
      const controller = new AbortController();
      abort.current = controller;
      let offProgress = (): void => {};
      try {
        const res = await client.convert.start({ videoId: video.id }, options);
        const id = res.jobId;
        jobId.current = id;
        offProgress = onProgress((event) => {
          if (event.jobId !== id) return;
          setPct(event.pct);
          setMessage(event.message);
        });
        let outPath: string | null = res.path ?? null;
        if (!outPath) {
          outPath = await waitForJobDone(
            { onJobDone },
            id,
            (result) => pickField<string>(result, 'path'),
            DEFAULT_JOB_TIMEOUT_MS,
            controller.signal,
          );
        }
        if (outPath) {
          setPaths([outPath]);
          setPct(100);
          setMessage('Done');
          setPhase('done');
        } else {
          setError('The export finished without producing a file.');
          setPhase('failed');
        }
      } catch (err) {
        if (err instanceof JobAbortedError) {
          setPhase('cancelled');
          return;
        }
        setError(errText(err));
        setPhase('failed');
      } finally {
        offProgress();
        jobId.current = null;
      }
    },
    [video.id],
  );

  const cancel = useCallback(async (): Promise<void> => {
    // Abort the terminal wait (settles the UI to 'cancelled'), then stop the job.
    abort.current.abort();
    const id = jobId.current;
    if (!id) return;
    try {
      await client.job.cancel(id);
    } catch {
      // best-effort: the abort already settled the UI to 'cancelled'.
    }
  }, []);

  const reset = useCallback(() => setPhase('idle'), []);

  const openFolder = openInFolderBridge();
  const reveal = openFolder
    ? (path: string): void => {
        void openFolder(path).catch(() => {
          // best-effort: opening the OS folder is a convenience, not the export.
        });
      }
    : undefined;

  return (
    <section className="export-view" aria-label="Export">
      <header className="export-view__head">
        <button type="button" className="export-view__back" onClick={onBack}>
          ← Library
        </button>
        <h2 className="export-view__title">{video.title}</h2>
      </header>
      <div className="export-view__body">
        <div className="export-view__stage">
          <ExportStage />
        </div>
        <div className="export-view__panel">
          {phase === 'idle' ? (
            <ExportInspector onCommit={(preset, options) => void onCommit(preset, options)} />
          ) : phase === 'running' ? (
            <ExportProgress
              destination={destination}
              pct={pct}
              message={message}
              onCancel={() => void cancel()}
            />
          ) : (
            <ExportResult
              outcome={phase}
              destination={destination}
              paths={paths}
              error={error}
              onReveal={reveal}
              onDeliver={onDeliver}
              onExportAgain={reset}
            />
          )}
        </div>
      </div>
    </section>
  );
}

export function Export({ video, onBack, onDeliver }: ExportProps): React.ReactElement {
  if (!video) {
    return (
      <section className="export-view export-view--empty" aria-label="Export">
        <div className="export-view__empty">
          <h2 className="export-view__empty-title">Open a video to export</h2>
          <p className="export-view__empty-blurb">
            Pick a video from the Library to render and finish it for a platform.
          </p>
          <button type="button" className="export-view__back" onClick={onBack}>
            ← Library
          </button>
        </div>
      </section>
    );
  }

  const seed: EditorSeed = {
    video: {
      videoId: video.id,
      window: { start: 0, end: video.durationSec },
      durationSec: video.durationSec,
    },
  };

  return (
    <EditorProvider key={video.id} seed={seed}>
      <ExportWorkspace video={video} onBack={onBack} onDeliver={onDeliver} />
    </EditorProvider>
  );
}

export default Export;
