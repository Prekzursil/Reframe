// Subtitle-track management panel.
//
// Calls the sidecar tracks methods (CONTRACTS.md §2):
//   tracks.list({videoId})              -> {tracks}
//   tracks.rename({trackId, name})
//   tracks.relabel({trackId, lang})
//   tracks.add({videoId, trackId})
//   tracks.remove({videoId, trackId})
//   tracks.burn({videoId, trackId})     -> {jobId} -> {path}  (long job)
//   tracks.strip({videoId, trackId})    -> {path}
//
// Consumes the frozen `window.api` surface via the shared local types in `./_api`.
import React, { useCallback, useEffect, useState } from 'react';
import './panels.css';
import { type SubtitleTrack, extractJobId, getApi, pickField, waitForJobDone } from './_api';

export interface TracksProps {
  videoId: string;
  /** Tracks not yet attached to the video, offered for `tracks.add`. */
  availableTracks?: SubtitleTrack[];
}

type Busy =
  | { kind: 'none' }
  | { kind: 'list' }
  | { kind: 'op'; trackId: string; op: string };

export function Tracks({ videoId, availableTracks = [] }: TracksProps): React.ReactElement {
  const [tracks, setTracks] = useState<SubtitleTrack[]>([]);
  const [busy, setBusy] = useState<Busy>({ kind: 'none' });
  const [error, setError] = useState<string>('');
  const [status, setStatus] = useState<string>('');

  // Burn is a long job; track its progress.
  const [burnJobId, setBurnJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);

  const refresh = useCallback(async () => {
    if (!videoId) return;
    setBusy({ kind: 'list' });
    setError('');
    try {
      const res = await getApi().rpc<{ tracks: SubtitleTrack[] }>('tracks.list', {
        videoId,
      });
      setTracks(res.tracks ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy({ kind: 'none' });
    }
  }, [videoId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!burnJobId) return;
    const off = getApi().onProgress((ev) => {
      if (ev.jobId !== burnJobId) return;
      setPct(ev.pct);
      setStatus(ev.message);
    });
    return off;
  }, [burnJobId]);

  const isBusy = busy.kind !== 'none';
  const opOn = (trackId: string, op: string): boolean =>
    busy.kind === 'op' && busy.trackId === trackId && busy.op === op;

  // Generic small mutation helper (rename/relabel/add/remove). Refreshes after.
  const runOp = useCallback(
    async (
      trackId: string,
      op: string,
      method: string,
      params: Record<string, unknown>,
      doneMsg: string,
    ) => {
      setBusy({ kind: 'op', trackId, op });
      setError('');
      setStatus('');
      try {
        await getApi().rpc(method, params);
        setStatus(doneMsg);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy({ kind: 'none' });
      }
    },
    [refresh],
  );

  const rename = useCallback(
    (trackId: string, name: string) =>
      runOp(trackId, 'rename', 'tracks.rename', { trackId, name }, 'Renamed'),
    [runOp],
  );

  const relabel = useCallback(
    (trackId: string, lang: string) =>
      runOp(trackId, 'relabel', 'tracks.relabel', { trackId, lang }, 'Relabelled'),
    [runOp],
  );

  const add = useCallback(
    (trackId: string) =>
      runOp(trackId, 'add', 'tracks.add', { videoId, trackId }, 'Added'),
    [runOp, videoId],
  );

  const remove = useCallback(
    (trackId: string) =>
      runOp(trackId, 'remove', 'tracks.remove', { videoId, trackId }, 'Removed'),
    [runOp, videoId],
  );

  const strip = useCallback(
    async (trackId: string) => {
      setBusy({ kind: 'op', trackId, op: 'strip' });
      setError('');
      setStatus('Stripping…');
      try {
        const res = await getApi().rpc<{ path: string }>('tracks.strip', {
          videoId,
          trackId,
        });
        setStatus(`Stripped → ${res.path}`);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy({ kind: 'none' });
      }
    },
    [videoId, refresh],
  );

  const burn = useCallback(
    async (trackId: string) => {
      setBusy({ kind: 'op', trackId, op: 'burn' });
      setError('');
      setPct(0);
      setStatus('Burning in…');
      try {
        // §2 long job: rpc resolves with {jobId} only; the terminal {path}
        // arrives via a `job.done` notification, so we await onJobDone for it.
        const res = await getApi().rpc<{ jobId?: string; path?: string }>(
          'tracks.burn',
          { videoId, trackId },
        );
        const id = extractJobId(res);
        if (id) setBurnJobId(id);
        let outPath = res.path ?? null;
        if (!outPath && id) {
          outPath = await waitForJobDone(getApi(), id, (r) => pickField<string>(r, 'path'));
        }
        if (outPath) {
          setPct(100);
          setStatus(`Burned → ${outPath}`);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy({ kind: 'none' });
      }
    },
    [videoId],
  );

  return (
    <section className="feature-panel tracks-panel" aria-label="Subtitle tracks">
      <h2>Subtitle tracks</h2>

      <div className="actions">
        <button type="button" onClick={refresh} disabled={isBusy || !videoId}>
          {busy.kind === 'list' ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {tracks.length === 0 ? (
        <p className="empty">No subtitle tracks.</p>
      ) : (
        <ul className="track-list">
          {tracks.map((t) => (
            <li key={t.id} className="track-row">
              <div className="track-fields">
                <input
                  type="text"
                  className="track-name"
                  defaultValue={t.name}
                  aria-label={`Track ${t.id} name`}
                  disabled={isBusy}
                  onBlur={(e) => {
                    const v = e.target.value.trim();
                    if (v && v !== t.name) void rename(t.id, v);
                  }}
                />
                <input
                  type="text"
                  className="track-lang"
                  defaultValue={t.lang}
                  aria-label={`Track ${t.id} language`}
                  disabled={isBusy}
                  onBlur={(e) => {
                    const v = e.target.value.trim();
                    if (v && v !== t.lang) void relabel(t.id, v);
                  }}
                />
                <span className="track-kind">{t.kind}</span>
                <span className="track-format">{t.format.toUpperCase()}</span>
              </div>
              <div className="track-ops">
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => void add(t.id)}
                >
                  {opOn(t.id, 'add') ? '…' : 'Add'}
                </button>
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => void remove(t.id)}
                >
                  {opOn(t.id, 'remove') ? '…' : 'Remove'}
                </button>
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => void burn(t.id)}
                >
                  {opOn(t.id, 'burn') ? 'Burning…' : 'Burn in'}
                </button>
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => void strip(t.id)}
                >
                  {opOn(t.id, 'strip') ? 'Stripping…' : 'Strip'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {availableTracks.length > 0 && (
        <div className="available-tracks">
          <h3>Add an existing track</h3>
          <ul>
            {availableTracks.map((t) => (
              <li key={t.id}>
                <span>
                  {t.name || t.id} · {t.lang}
                </span>
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => void add(t.id)}
                >
                  Add
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {burnJobId && (busy.kind === 'op' ? busy.op === 'burn' : pct < 100) && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
        </div>
      )}

      {status && !error && <p className="status">{status}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default Tracks;
