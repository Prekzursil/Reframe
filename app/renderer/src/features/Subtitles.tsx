// Subtitles feature panel.
//
// Calls the sidecar subtitles methods (CONTRACTS.md §2):
//   subtitles.generate({videoId})         -> {track}
//   subtitles.edit({trackId, cues})        -> {track}
//   subtitles.translate({trackId, targetLang}) -> {jobId} -> {track}  (long job)
//   subtitles.export({trackId, format})    -> {path}     (format: srt|ass|vtt)
//
// Consumes the frozen `window.api` surface via the shared local types in `./_api`.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import {
  type Cue,
  type SubtitleFormat,
  type SubtitleTrack,
  extractJobId,
  fmtSeconds,
  getApi,
  pickField,
  waitForJobDone,
} from './_api';

export interface SubtitlesProps {
  videoId: string;
  /** Optional initial track (e.g. loaded from the project). */
  initialTrack?: SubtitleTrack | null;
  /** Notified whenever the active track changes (generate/edit/translate). */
  onTrackChange?: (track: SubtitleTrack) => void;
}

const FORMATS: SubtitleFormat[] = ['srt', 'ass', 'vtt'];

const TARGET_LANGS: Array<{ code: string; label: string }> = [
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

type Busy = 'none' | 'generating' | 'translating' | 'exporting' | 'saving';

export function Subtitles({
  videoId,
  initialTrack = null,
  onTrackChange,
}: SubtitlesProps): React.ReactElement {
  const [track, setTrack] = useState<SubtitleTrack | null>(initialTrack);
  const [busy, setBusy] = useState<Busy>('none');
  const [error, setError] = useState<string>('');
  const [status, setStatus] = useState<string>('');

  // Translate is a long job; track its progress.
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);

  const [targetLang, setTargetLang] = useState<string>('en');
  const [exportFormat, setExportFormat] = useState<SubtitleFormat>('srt');
  const [lastExportPath, setLastExportPath] = useState<string>('');

  useEffect(() => {
    if (!jobId) return;
    const off = getApi().onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setStatus(ev.message);
    });
    return off;
  }, [jobId]);

  const applyTrack = useCallback(
    (t: SubtitleTrack) => {
      setTrack(t);
      onTrackChange?.(t);
    },
    [onTrackChange],
  );

  const generate = useCallback(async () => {
    setBusy('generating');
    setError('');
    setStatus('Generating subtitles…');
    try {
      const res = await getApi().rpc<{ track: SubtitleTrack }>('subtitles.generate', {
        videoId,
      });
      applyTrack(res.track);
      setStatus('Generated');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('none');
    }
  }, [videoId, applyTrack]);

  // Persist in-place cue edits via subtitles.edit({trackId, cues}).
  const saveEdits = useCallback(
    async (cues: Cue[]) => {
      if (!track) return;
      setBusy('saving');
      setError('');
      setStatus('Saving edits…');
      try {
        const res = await getApi().rpc<{ track: SubtitleTrack }>('subtitles.edit', {
          trackId: track.id,
          cues,
        });
        applyTrack(res.track);
        setStatus('Saved');
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy('none');
      }
    },
    [track, applyTrack],
  );

  const editCueText = useCallback(
    (index: number, text: string) => {
      if (!track) return;
      // Local optimistic update; persisted on blur via saveEdits.
      const cues = track.cues.map((c) => (c.index === index ? { ...c, text } : c));
      setTrack({ ...track, cues });
    },
    [track],
  );

  const translate = useCallback(async () => {
    if (!track) return;
    setBusy('translating');
    setError('');
    setPct(0);
    setStatus('Translating…');
    try {
      // §2 long job: rpc resolves with {jobId} only; the terminal {track} arrives
      // via a `job.done` notification, so we await onJobDone for it (the working
      // ShortMaker.tsx pattern).
      const res = await getApi().rpc<{ jobId?: string; track?: SubtitleTrack }>(
        'subtitles.translate',
        { trackId: track.id, targetLang },
      );
      const id = extractJobId(res);
      if (id) setJobId(id);
      let translated = res.track ?? null;
      if (!translated && id) {
        translated = await waitForJobDone(getApi(), id, (r) =>
          pickField<SubtitleTrack>(r, 'track'),
        );
      }
      if (translated) {
        applyTrack(translated);
        setPct(100);
        setStatus('Translated');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('none');
    }
  }, [track, targetLang, applyTrack]);

  const exportTrack = useCallback(async () => {
    if (!track) return;
    setBusy('exporting');
    setError('');
    setStatus(`Exporting ${exportFormat.toUpperCase()}…`);
    try {
      const res = await getApi().rpc<{ path: string }>('subtitles.export', {
        trackId: track.id,
        format: exportFormat,
      });
      setLastExportPath(res.path);
      setStatus('Exported');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('none');
    }
  }, [track, exportFormat]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    try {
      await getApi().rpc('job.cancel', { jobId });
    } catch {
      // best-effort
    }
    setBusy('none');
    setStatus('Cancelled');
  }, [jobId]);

  const cueCount = track ? track.cues.length : 0;
  const translating = busy === 'translating';
  const anyBusy = busy !== 'none';

  const sortedCues = useMemo(
    () => (track ? [...track.cues].sort((a, b) => a.start - b.start) : []),
    [track],
  );

  return (
    <section className="feature-panel subtitles-panel" aria-label="Subtitles">
      <h2>Subtitles</h2>

      <div className="actions">
        <button type="button" onClick={generate} disabled={anyBusy || !videoId}>
          {busy === 'generating' ? 'Generating…' : 'Generate subtitles'}
        </button>
      </div>

      {track && (
        <>
          <div className="track-meta">
            <span>
              Track <strong>{track.name || track.id}</strong> · {track.lang} ·{' '}
              {track.format.toUpperCase()} · {track.kind} · {cueCount} cues
            </span>
          </div>

          <div className="field translate-row">
            <label htmlFor="subtitles-target-lang">Translate to</label>
            <select
              id="subtitles-target-lang"
              value={targetLang}
              disabled={anyBusy}
              onChange={(e) => setTargetLang(e.target.value)}
            >
              {TARGET_LANGS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
            <button type="button" onClick={translate} disabled={anyBusy}>
              {translating ? 'Translating…' : 'Translate'}
            </button>
            {translating && jobId && (
              <button type="button" className="secondary" onClick={cancel}>
                Cancel
              </button>
            )}
          </div>

          <div className="field export-row">
            <label htmlFor="subtitles-export-format">Export as</label>
            <select
              id="subtitles-export-format"
              value={exportFormat}
              disabled={anyBusy}
              onChange={(e) => setExportFormat(e.target.value as SubtitleFormat)}
            >
              {FORMATS.map((f) => (
                <option key={f} value={f}>
                  {f.toUpperCase()}
                </option>
              ))}
            </select>
            <button type="button" onClick={exportTrack} disabled={anyBusy}>
              {busy === 'exporting' ? 'Exporting…' : 'Export'}
            </button>
          </div>

          <div className="cue-editor">
            <h3>Edit cues</h3>
            <ol className="cue-list">
              {sortedCues.map((cue) => (
                <li key={cue.index} className="cue-row">
                  <span className="cue-time">
                    {fmtSeconds(cue.start)} → {fmtSeconds(cue.end)}
                  </span>
                  <input
                    className="cue-text"
                    type="text"
                    value={cue.text}
                    disabled={anyBusy}
                    aria-label={`Cue ${cue.index} text`}
                    onChange={(e) => editCueText(cue.index, e.target.value)}
                    onBlur={() => track && saveEdits(track.cues)}
                  />
                </li>
              ))}
            </ol>
          </div>
        </>
      )}

      {translating && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
        </div>
      )}

      {status && !error && <p className="status">{status}</p>}
      {lastExportPath && (
        <p className="export-path">
          Saved to <code>{lastExportPath}</code>
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default Subtitles;
