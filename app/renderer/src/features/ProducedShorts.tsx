// ProducedShorts.tsx — the per-video produced-shorts gallery.
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). P4 §6 / C11: after export the container
// reloads shorts.list {videoId}; this component renders the resulting clips with
// the gallery card actions (play / open-folder / re-export / delete).
//
// WU-C4 (intelligence) adds the per-clip "Pick best frame" action: it runs the
// `thumbnail.select` AI job (frame-egress consented) and swaps the card's poster
// to the chosen frame. The swap is ANNOUNCED (polite live region + updated
// `<img alt>`) and the degrade-to-midpoint fallback is surfaced (visible +
// announced), never silent (DESIGN §3.6). RPC/job state lives per-card here; the
// other card actions stay container-driven callbacks (presentational).

import React, { useCallback, useEffect, useState } from 'react';

import { Player, shortMediaUrl } from '../components/Player';
import { ShortClipActions } from '../components/ShortClipActions';
import { fmtSeconds, getApi } from './_api';
import type { BestFrame, ShortInfo } from '../lib/rpc';

export interface ProducedShortsProps {
  shorts: ShortInfo[];
  /** Path of the clip currently inline-playing ('' = none). */
  playingShortPath: string;
  onPlay: (path: string) => void;
  onOpenFolder: (path: string) => void;
  onReexport: (path: string) => void;
  onDelete: (path: string) => void;
}

const DEGRADE_NOTE = 'No vision model available — used the middle frame';

type PickPhase = 'idle' | 'running' | 'done' | 'error';

/** Read a {@link BestFrame} off a `job.done` result, or `null` if malformed. */
function asBestFrame(result: unknown): BestFrame | null {
  if (
    result &&
    typeof result === 'object' &&
    typeof (result as { frameTimeSec?: unknown }).frameTimeSec === 'number' &&
    typeof (result as { thumbnailPath?: unknown }).thumbnailPath === 'string'
  ) {
    return result as BestFrame;
  }
  return null;
}

/**
 * One produced-short card. Owns the local "Pick best frame" job lifecycle so a
 * pick on one clip never disturbs its siblings. The thumbnail `<img>` shows the
 * existing poster (if any) and is replaced by the chosen frame on done.
 */
function ShortThumbCard({
  short,
  title,
  playing,
  onPlay,
  onOpenFolder,
  onReexport,
  onDelete,
}: {
  short: ShortInfo;
  title: string;
  playing: boolean;
  onPlay: (path: string) => void;
  onOpenFolder: (path: string) => void;
  onReexport: (path: string) => void;
  onDelete: (path: string) => void;
}): React.JSX.Element {
  const [phase, setPhase] = useState<PickPhase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<string>('');
  const [error, setError] = useState<string>('');
  // The swapped poster (overrides short.thumbnailPath once a pick completes).
  const [pickedPath, setPickedPath] = useState<string>('');
  const [pickedSec, setPickedSec] = useState<number | null>(null);
  const [degraded, setDegraded] = useState<boolean>(false);
  // The announce/swap message, computed once the chosen frame arrives.
  const [swapMessage, setSwapMessage] = useState<string>('');

  // Subscribe to progress for the live job (cleaned up when it ends/changes).
  useEffect(() => {
    if (!jobId) return undefined;
    return getApi().onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setProgress(ev.message);
    });
  }, [jobId]);

  // Subscribe to the terminal job.done for the live job.
  useEffect(() => {
    if (!jobId) return undefined;
    const api = getApi();
    if (typeof api.onJobDone !== 'function') return undefined;
    const off = api.onJobDone((ev) => {
      if (ev.jobId !== jobId) return;
      const best = asBestFrame(ev.result);
      if (!best) {
        // A malformed payload can't drive a swap; fail loud rather than silent.
        setError('The best-frame job returned an unreadable result.');
        setPhase('error');
        setJobId(null);
        off();
        return;
      }
      setPickedPath(best.thumbnailPath);
      setPickedSec(best.frameTimeSec);
      setDegraded(best.degraded);
      setSwapMessage(
        best.degraded
          ? DEGRADE_NOTE
          : `Thumbnail updated to the frame at ${fmtSeconds(best.frameTimeSec)}`,
      );
      setPhase('done');
      setJobId(null);
      off();
    });
    return off;
  }, [jobId]);

  const pick = useCallback(async () => {
    setPhase('running');
    setError('');
    setProgress('Starting…');
    try {
      const res = await getApi().rpc<{ jobId?: string }>('thumbnail.select', { path: short.path });
      const id = typeof res.jobId === 'string' ? res.jobId : '';
      if (id) setJobId(id);
      else setPhase('idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase('error');
    }
  }, [short.path]);

  const running = phase === 'running';
  const posterPath = pickedPath || short.thumbnailPath;
  const posterSrc = posterPath ? shortMediaUrl(posterPath) : '';
  const posterAlt =
    pickedSec === null
      ? `Thumbnail for ${title}`
      : `Thumbnail for ${title} — frame at ${fmtSeconds(pickedSec)}`;

  return (
    <li className="shorts__card" data-id={short.id}>
      <div className="shorts__thumb">
        {playing ? (
          <Player className="shorts__player" src={shortMediaUrl(short.path)} autoPlay controls />
        ) : (
          <button
            type="button"
            className="shorts__thumb-btn"
            aria-label={`Play preview of ${title}`}
            onClick={() => onPlay(short.path)}
          >
            {posterSrc ? (
              <img className="shorts__thumb-img" src={posterSrc} alt={posterAlt} />
            ) : (
              <span className="shorts__thumb-glyph" aria-hidden="true">
                ▶
              </span>
            )}
          </button>
        )}
        {typeof short.viralityPct === 'number' && (
          <span className="shorts__virality" aria-label="Virality">
            {short.viralityPct}
            <span className="shorts__virality-pct">%</span>
          </span>
        )}
      </div>
      {short.template && (
        <span className="shorts__template" aria-label="Caption template">
          {short.template}
        </span>
      )}
      <button
        type="button"
        className="shorts__pick-frame"
        aria-label={`Pick the best thumbnail frame for ${title}`}
        aria-busy={running}
        disabled={running}
        onClick={() => void pick()}
      >
        Pick best frame
      </button>
      <p className="shorts__pick-status" aria-live="polite">
        {running ? progress : swapMessage}
      </p>
      {phase === 'done' && degraded && <p className="shorts__degrade-note">{DEGRADE_NOTE}</p>}
      {phase === 'error' && (
        <p className="shorts__pick-error" role="alert">
          {error}
        </p>
      )}
      <ShortClipActions
        path={short.path}
        label={title}
        playing={playing}
        onPlay={onPlay}
        onOpenFolder={onOpenFolder}
        onReexport={onReexport}
        onDelete={onDelete}
      />
    </li>
  );
}

/**
 * The "Produced shorts" grid for the current video. Renders nothing until at
 * least one short exists (the container gates this, but we also guard here so
 * the component is safe to mount unconditionally).
 */
export function ProducedShorts({
  shorts,
  playingShortPath,
  onPlay,
  onOpenFolder,
  onReexport,
  onDelete,
}: ProducedShortsProps): React.JSX.Element | null {
  if (shorts.length === 0) return null;
  return (
    <div className="sm-video-shorts" aria-label="Produced shorts">
      <h3>Produced shorts</h3>
      <ul className="shorts__grid shorts__grid--inline">
        {shorts.map((short) => (
          <ShortThumbCard
            key={short.id}
            short={short}
            title={short.sourceTitle || short.hook || short.path}
            playing={playingShortPath === short.path}
            onPlay={onPlay}
            onOpenFolder={onOpenFolder}
            onReexport={onReexport}
            onDelete={onDelete}
          />
        ))}
      </ul>
    </div>
  );
}

export default ProducedShorts;
