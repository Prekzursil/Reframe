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

type Busy = 'none' | 'generating' | 'translating' | 'exporting' | 'saving' | 'importing';

/** File-picker filter for the import control (`ssa` is an alias of `ass`). */
const IMPORT_ACCEPT = '.srt,.vtt,.ass,.ssa';

/**
 * The format token to send for a picked file: everything after the LAST dot, so a
 * dotted stem (`ep.01.final.vtt`) still resolves to `vtt`. A name with no dot is
 * forwarded unchanged and the sidecar rejects it with a named, typed error rather
 * than this panel inventing its own format vocabulary.
 */
export function formatFromFilename(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot === -1 ? name : name.slice(dot + 1);
}

/**
 * Read a picked file as UTF-8 text.
 *
 * Deliberately `FileReader` and not `Blob.text()`: `Blob.prototype.text` is
 * MISSING in jsdom 24.1.3 (measured — `typeof Blob.prototype.text === 'undefined'`)
 * while `FileReader` is implemented, and Chromium (the real Electron renderer) has
 * both. One code path that works in production AND under test beats a `.text()`
 * call that needs a polyfill shim in the suite — a shim would mean the test
 * exercises the polyfill rather than the code that ships.
 *
 * A read failure (file deleted or permissions revoked between pick and read) is a
 * real, reachable path, so it rejects rather than resolving empty text — an empty
 * string would reach the sidecar as a bogus "no cues found".
 */
export function readFileText(file: File): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsText(file);
  });
}

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

  // captions-export: bilingual stacked subtitles (original + translation).
  const [bilingual, setBilingual] = useState<boolean>(false);
  const [bilingualOrder, setBilingualOrder] = useState<'original-first' | 'translation-first'>(
    'original-first',
  );

  // F19: the Workspace derives `initialTrack` from `project.tracks[0]`, but
  // `project.open` is fired from a POST-COMMIT effect (Workspace.tsx:173-176) and
  // can land AFTER this lazily-imported panel has mounted — so the prop must be
  // ADOPTED, not only captured once at mount by `useState(initialTrack)` above.
  // Without this the panel shows "Generate subtitles" forever and the project's
  // existing (possibly hand-edited) track is invisible for the panel's lifetime.
  //
  // Guarded on `!track` so it hydrates the EMPTY panel only, and never clobbers a
  // generated / translated / locally-edited track (a later project reload would
  // otherwise overwrite unsaved keystrokes). `setTrack`, NOT `applyTrack`
  // (:81-87): hydrating from the parent's own data must not fire `onTrackChange`
  // back at the parent.
  //
  // Accepted residual: a Generate clicked BEFORE `project.open` lands is visibly
  // superseded — the hydrate fills the empty slot first, then the generate
  // response replaces it. Cosmetic only; the generated track still wins.
  useEffect(() => {
    if (initialTrack && !track) setTrack(initialTrack);
  }, [initialTrack, track]);

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
      // defensive null-narrowing: saveEdits is only wired to the cue inputs'
      // onBlur, which render only inside `track && (...)`, so track is non-null.
      /* v8 ignore next */
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
      // defensive null-narrowing: editCueText is only wired to the cue inputs'
      // onChange, which render only inside `track && (...)`, so track is non-null.
      /* v8 ignore next */
      if (!track) return;
      // Local optimistic update; persisted on blur via saveEdits.
      const cues = track.cues.map((c) => (c.index === index ? { ...c, text } : c));
      setTrack({ ...track, cues });
    },
    [track],
  );

  // Import a hand-corrected subtitle file (v1.5 captions audit §5.1). Reads the
  // picked file's TEXT with the standard File API and sends the text, so no
  // Electron dialog/preload channel is needed and the sidecar never opens a
  // renderer-supplied path. Deliberately available with NO track present — a user
  // who already has their own SRT should not have to generate one first.
  const importFile = useCallback(
    async (ev: React.ChangeEvent<HTMLInputElement>) => {
      const input = ev.target;
      const file = input.files?.[0];
      if (!file) return; // picker dismissed
      setBusy('importing');
      setError('');
      setStatus(`Importing ${file.name}…`);
      try {
        const text = await readFileText(file);
        const res = await getApi().rpc<{ track: SubtitleTrack }>('subtitles.import', {
          videoId,
          text,
          format: formatFromFilename(file.name),
          name: file.name,
        });
        applyTrack(res.track);
        setStatus(`Imported ${res.track.cues.length} cues from ${file.name}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setStatus('');
      } finally {
        setBusy('none');
        // Clear the input so re-picking the SAME file fires `change` again.
        input.value = '';
      }
    },
    [videoId, applyTrack],
  );

  const translate = useCallback(async () => {
    // defensive null-narrowing: the Translate button renders only inside
    // `track && (...)`, so track is non-null here.
    /* v8 ignore next */
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
        bilingual
          ? { trackId: track.id, targetLang, bilingual: true, order: bilingualOrder }
          : { trackId: track.id, targetLang },
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
  }, [track, targetLang, bilingual, bilingualOrder, applyTrack]);

  const exportTrack = useCallback(async () => {
    // defensive null-narrowing: the Export button renders only inside
    // `track && (...)`, so track is non-null here.
    /* v8 ignore next */
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
    // defensive: the Cancel button renders only while `translating && jobId`,
    // so cancel is never invoked with a null jobId via UI.
    /* v8 ignore next */
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

      {/* Import sits OUTSIDE the `track && (...)` block on purpose: a user who
          already hand-corrected an SRT must not have to generate one first. */}
      <div className="field import-row">
        <label htmlFor="subtitles-import-file">
          {busy === 'importing' ? 'Importing…' : 'Import subtitle file'}
        </label>
        <input
          id="subtitles-import-file"
          type="file"
          accept={IMPORT_ACCEPT}
          disabled={anyBusy || !videoId}
          onChange={importFile}
        />
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

          {/* captions-export: bilingual stacked subtitles (original + translation). */}
          <div className="field bilingual-row">
            <label className="bilingual-toggle">
              <input
                type="checkbox"
                checked={bilingual}
                disabled={anyBusy}
                onChange={(e) => setBilingual(e.target.checked)}
              />
              Bilingual (stack original + translation)
            </label>
            {bilingual && (
              <select
                aria-label="Bilingual line order"
                value={bilingualOrder}
                disabled={anyBusy}
                onChange={(e) =>
                  setBilingualOrder(e.target.value as 'original-first' | 'translation-first')
                }
              >
                <option value="original-first">Original on top</option>
                <option value="translation-first">Translation on top</option>
              </select>
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
