// Convert feature panel — the ffmpeg options form.
//
// Calls the sidecar convert methods (CONTRACTS.md §2):
//   convert.start({videoId|path, options}) -> {jobId} -> {path}   (long job)
//   convert.batch({items})                 -> {jobId} -> {paths}  (long job)
// options = {container,vcodec,acodec,scale,fps,crf,audioOnly,audioFormat}
//
// Consumes the frozen `window.api` surface via the shared local types in `./_api`.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import {
  type ConvertBatchItem,
  type ConvertOptions,
  extractJobId,
  getApi,
  pickField,
  waitForJobDone,
} from './_api';

export interface ConvertProps {
  /** Source video id (preferred). */
  videoId?: string;
  /** Source path (alternative to videoId per `{videoId|path}`). */
  path?: string;
  /** When set, the panel offers a batch run over these sources. */
  batchItems?: ConvertBatchItem[];
}

// CONTRACT-NOTE: §2 fixes the options FIELD NAMES but not their value sets, so
// these dropdown choices are UI conveniences; the empty string means "leave to
// the encoder / ffmpeg default" and is sent through verbatim (the sidecar
// convert unit decides defaults). `scale`/`fps`/`crf` are strings per §2.
const CONTAINERS = ['mp4', 'mkv', 'mov', 'webm'];
const VCODECS = ['', 'libx264', 'libx265', 'libvpx-vp9', 'copy'];
const ACODECS = ['', 'aac', 'libopus', 'libmp3lame', 'copy'];
const AUDIO_FORMATS = ['mp3', 'aac', 'wav', 'flac', 'opus'];
const SCALES = ['', '1920:-2', '1280:-2', '854:-2', '640:-2'];

const DEFAULT_OPTIONS: ConvertOptions = {
  container: 'mp4',
  vcodec: 'libx264',
  acodec: 'aac',
  scale: '',
  fps: '',
  crf: '23',
  audioOnly: false,
  audioFormat: 'mp3',
};

type Phase = 'idle' | 'running' | 'done' | 'error';

export function Convert({ videoId, path, batchItems }: ConvertProps): React.ReactElement {
  const [options, setOptions] = useState<ConvertOptions>(DEFAULT_OPTIONS);
  const [phase, setPhase] = useState<Phase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [outPaths, setOutPaths] = useState<string[]>([]);

  useEffect(() => {
    if (!jobId) return;
    const off = getApi().onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [jobId]);

  const set = useCallback(<K extends keyof ConvertOptions>(key: K, value: ConvertOptions[K]) => {
    setOptions((o) => ({ ...o, [key]: value }));
  }, []);

  const hasSource = Boolean(videoId || path);
  const running = phase === 'running';
  const canBatch = Boolean(batchItems && batchItems.length > 0);

  const beginRun = useCallback(() => {
    setPhase('running');
    setError('');
    setPct(0);
    setMessage('Starting…');
    setOutPaths([]);
  }, []);

  const start = useCallback(async () => {
    beginRun();
    try {
      // §2: `{videoId|path}` — send whichever identifier we have.
      const params: Record<string, unknown> = { options };
      if (videoId) params.videoId = videoId;
      else if (path) params.path = path;
      // §2 long job: rpc resolves with {jobId} only; the terminal {path} arrives
      // via a `job.done` notification, so we await onJobDone for it.
      const res = await getApi().rpc<{ jobId?: string; path?: string }>('convert.start', params);
      const id = extractJobId(res);
      if (id) setJobId(id);
      let outPath = res.path ?? null;
      if (!outPath && id) {
        outPath = await waitForJobDone(getApi(), id, (r) => pickField<string>(r, 'path'));
      }
      if (outPath) {
        setOutPaths([outPath]);
        setPct(100);
        setMessage('Done');
        setPhase('done');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase('error');
    } finally {
      // F1/F2: a job that finished with neither a path nor an error (or a
      // timed-out wait) must NOT stick on 'running' forever — drop back to idle.
      setPhase((p) => (p === 'running' ? 'idle' : p));
    }
  }, [beginRun, options, videoId, path]);

  const startBatch = useCallback(async () => {
    // defensive: the batch button only renders when `canBatch` (batchItems
    // present and non-empty), so this guard is never reached via UI.
    /* v8 ignore next */
    if (!batchItems || batchItems.length === 0) return;
    beginRun();
    try {
      // Apply the current form options to any item that didn't carry its own.
      const items: ConvertBatchItem[] = batchItems.map((it) => ({
        ...it,
        options: it.options ?? options,
      }));
      const res = await getApi().rpc<{ jobId?: string; paths?: string[] }>('convert.batch', {
        items,
      });
      const id = extractJobId(res);
      if (id) setJobId(id);
      // §2 long job: terminal {paths} arrives via `job.done`.
      let outPaths = res.paths ?? null;
      if (!outPaths && id) {
        outPaths = await waitForJobDone(getApi(), id, (r) => pickField<string[]>(r, 'paths'));
      }
      if (outPaths) {
        setOutPaths(outPaths);
        setPct(100);
        setMessage('Done');
        setPhase('done');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase('error');
    } finally {
      // F1/F2: a job that finished with neither paths nor an error (or a
      // timed-out wait) must NOT stick on 'running' forever — drop back to idle.
      setPhase((p) => (p === 'running' ? 'idle' : p));
    }
  }, [beginRun, batchItems, options]);

  const cancel = useCallback(async () => {
    // defensive: the Cancel button only renders while `running && jobId`, so
    // cancel is never invoked with a null jobId via UI.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await getApi().rpc('job.cancel', { jobId });
    } catch {
      // best-effort
    }
    setPhase('idle');
    setMessage('Cancelled');
  }, [jobId]);

  const { audioOnly } = options;
  const sourceLabel = useMemo(() => videoId ?? path ?? '(no source)', [videoId, path]);

  return (
    <section className="feature-panel convert-panel" aria-label="Convert">
      <h2>Convert</h2>
      <p className="source-label">
        Source: <code>{sourceLabel}</code>
      </p>

      <form
        className="convert-form"
        onSubmit={(e) => {
          e.preventDefault();
          void start();
        }}
      >
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={audioOnly}
            disabled={running}
            onChange={(e) => set('audioOnly', e.target.checked)}
          />
          Audio only
        </label>

        {audioOnly ? (
          <div className="field">
            <label htmlFor="convert-audio-format">Audio format</label>
            <select
              id="convert-audio-format"
              value={options.audioFormat}
              disabled={running}
              onChange={(e) => set('audioFormat', e.target.value)}
            >
              {AUDIO_FORMATS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <>
            <div className="field">
              <label htmlFor="convert-container">Container</label>
              <select
                id="convert-container"
                value={options.container}
                disabled={running}
                onChange={(e) => set('container', e.target.value)}
              >
                {CONTAINERS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="convert-vcodec">Video codec</label>
              <select
                id="convert-vcodec"
                value={options.vcodec}
                disabled={running}
                onChange={(e) => set('vcodec', e.target.value)}
              >
                {VCODECS.map((c) => (
                  <option key={c || 'default'} value={c}>
                    {c || 'default'}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="convert-acodec">Audio codec</label>
              <select
                id="convert-acodec"
                value={options.acodec}
                disabled={running}
                onChange={(e) => set('acodec', e.target.value)}
              >
                {ACODECS.map((c) => (
                  <option key={c || 'default'} value={c}>
                    {c || 'default'}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="convert-scale">Scale</label>
              <select
                id="convert-scale"
                value={options.scale}
                disabled={running}
                onChange={(e) => set('scale', e.target.value)}
              >
                {SCALES.map((s) => (
                  <option key={s || 'source'} value={s}>
                    {s || 'source size'}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="convert-fps">FPS</label>
              <input
                id="convert-fps"
                type="text"
                inputMode="numeric"
                placeholder="source"
                value={options.fps}
                disabled={running}
                onChange={(e) => set('fps', e.target.value)}
              />
            </div>

            <div className="field">
              <label htmlFor="convert-crf">CRF</label>
              <input
                id="convert-crf"
                type="text"
                inputMode="numeric"
                placeholder="23"
                value={options.crf}
                disabled={running}
                onChange={(e) => set('crf', e.target.value)}
              />
            </div>
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={running || !hasSource}>
            {running ? 'Converting…' : 'Convert'}
          </button>
          {canBatch && (
            <button type="button" onClick={startBatch} disabled={running} className="secondary">
              Convert batch ({batchItems!.length})
            </button>
          )}
          {running && jobId && (
            <button type="button" onClick={cancel} className="secondary">
              Cancel
            </button>
          )}
        </div>
      </form>

      {(running || phase === 'done') && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {outPaths.length > 0 && (
        <div className="output-paths">
          <h3>Output</h3>
          <ul>
            {outPaths.map((p) => (
              <li key={p}>
                <code>{p}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {phase === 'error' && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default Convert;
