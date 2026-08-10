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
import { useConfirm } from '../components/ConfirmDialog';
import './panels.css';
import { type SubtitleTrack, extractJobId, getApi, pickField, waitForJobDone } from './_api';

export interface TracksProps {
  videoId: string;
  /** Tracks not yet attached to the video, offered for `tracks.add`. */
  availableTracks?: SubtitleTrack[];
}

type Busy = { kind: 'none' } | { kind: 'list' } | { kind: 'op'; trackId: string; op: string };

export function Tracks({ videoId, availableTracks = [] }: TracksProps): React.ReactElement {
  const [tracks, setTracks] = useState<SubtitleTrack[]>([]);
  const [busy, setBusy] = useState<Busy>({ kind: 'none' });
  const [error, setError] = useState<string>('');
  const [status, setStatus] = useState<string>('');

  // W04: the themed destructive gate that replaced the native `confirm()`.
  const { confirm, confirmDialog } = useConfirm();

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
    (trackId: string) => runOp(trackId, 'add', 'tracks.add', { videoId, trackId }, 'Added'),
    [runOp, videoId],
  );

  const remove = useCallback(
    async (t: SubtitleTrack) => {
      // CONFIRM before the destructive call. `tracks.remove` drops the whole soft
      // track ROW from the project manifest (features/tracks.py:135) and the save
      // overwrites it with no history — and the row carries its `cues` INLINE, so
      // every hand correction, translation and caption-polish layered on the track
      // dies with it (the machine transcript can be regenerated; the edit delta
      // cannot). Same shape as the other destructive sites — views/Shorts.tsx:147,
      // views/Library.tsx:461, features/useShortsGallery.ts:99 — per
      // KeepCopyControl.tsx:21: "never a silent one-click destructive action".
      //
      // `cues` is read defensively: tracks.list returns manifest rows RAW
      // (features/tracks.py:104-106; normalisation happens only on write at
      // :157-180), so a legacy row can arrive with no `cues` key and an unguarded
      // deref here would turn "no confirmation" into a dead button. Timeline.tsx:136
      // guards the same field for the same reason.
      //
      // Wording is deliberately neutral about the outcome: a `kind:"hard"` row's
      // Remove is enabled and merely rejects with HardSubtitleError
      // (features/tracks.py:132-133), so the prompt must not promise a deletion.
      //
      // W04: the THEMED gate replaced the native `confirm()`. The copy below is the
      // native prompt's string split at the blank line into the dialog's title and
      // its described body — same words, same code path, now announceable.
      const ok = await confirm({
        title: `Remove the subtitle track "${t.name}" (${t.id})?`,
        blurb:
          `${t.cues?.length ?? 0} cue(s) would be dropped from this project. Hand edits, ` +
          `translations and caption polish on this track cannot be recovered.`,
        confirmLabel: 'Remove track',
        cancelLabel: 'Keep it',
      });
      if (!ok) return;
      await runOp(t.id, 'remove', 'tracks.remove', { videoId, trackId: t.id }, 'Removed');
    },
    [confirm, runOp, videoId],
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
        const res = await getApi().rpc<{ jobId?: string; path?: string }>('tracks.burn', {
          videoId,
          trackId,
        });
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
        // Reset the job handle + progress so a finished/failed/timed-out burn
        // never leaves a stale half-filled progress bar rendered forever (the
        // bar is gated on an in-flight burn op below).
        setBusy({ kind: 'none' });
        setBurnJobId(null);
        setPct(0);
      }
    },
    [videoId],
  );

  const cancel = useCallback(async () => {
    // The Cancel button only renders while a burn op is in flight AND burnJobId
    // is set, so burnJobId is the live job id here. Best-effort, mirroring the
    // sibling long-job panels (Convert/Transcribe/…): a job.cancel rejection is
    // swallowed and we still drop the panel back to idle.
    try {
      await getApi().rpc('job.cancel', { jobId: burnJobId });
    } catch {
      // best-effort
    }
    setBusy({ kind: 'none' });
    setStatus('Cancelled');
  }, [burnJobId]);

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
                {/* No per-row `Add` button: these rows are the video's OWN
                    attached tracks, so re-adding them just persists a duplicate
                    (media_ops mints a fresh id, dodging add_track's dedupe). Add
                    lives only in the available-tracks section below. */}
                <button type="button" disabled={isBusy} onClick={() => void remove(t)}>
                  {opOn(t.id, 'remove') ? '…' : 'Remove'}
                </button>
                <button type="button" disabled={isBusy} onClick={() => void burn(t.id)}>
                  {opOn(t.id, 'burn') ? 'Burning…' : 'Burn in'}
                </button>
                {/* Cancel is always enabled while the burn job runs (mirrors the
                    sibling panels): disabling it during the panel-wide busy lock
                    would make it dead — the very bug it fixes. */}
                {opOn(t.id, 'burn') && burnJobId && (
                  <button type="button" className="cancel-op" onClick={() => void cancel()}>
                    Cancel
                  </button>
                )}
                <button type="button" disabled={isBusy} onClick={() => void strip(t.id)}>
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
                <button type="button" disabled={isBusy} onClick={() => void add(t.id)}>
                  Add
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {burnJobId && busy.kind === 'op' && busy.op === 'burn' && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
        </div>
      )}

      {confirmDialog}

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
