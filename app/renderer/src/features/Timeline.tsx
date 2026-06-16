// Timeline.tsx — timeline subtitle editor (P2 T1).
//
// Waveform strip (from `timeline.peaks`) + a cue lane of draggable rects over
// the same time axis. Click anywhere on the lane to seek the U1 Player (via
// the imperative `playerRef` handle and/or the `onSeek` callback); click a cue
// to select it; edit its text; split / merge / retime with the toolbar; drag a
// selected cue's edges (neighbor-clamped); thin linear undo/redo; save back
// through `subtitles.edit`. The track loads via `tracks.list`.
//
// All cue math lives in the PURE `lib/timelineOps` module (unit-tested there);
// this component owns only state wiring + rendering, tested under jsdom in
// Timeline.test.tsx with a faked RPC bridge.
//
// CONTRACT-NOTE: `timeline.peaks` (A2) returns `{sampleRate, peaks[0..1]}` but
// no duration; the time axis uses the `durationSec` prop (the Video row has
// it), falling back to `library.list` and finally to the last cue end.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import './timeline.css';
import { getApi, type Cue, type MediaStudioApi, type SubtitleTrack } from './_api';
import type { PlayerHandle } from '../components/Player';
import {
  MIN_CUE_SEC,
  canRedo,
  canUndo,
  createHistory,
  cueRectStyle,
  dragEdge,
  mergeAt,
  pushHistory,
  redo,
  renumber,
  retimeAt,
  splitAt,
  timeFromClientX,
  undo,
  type CueEdge,
  type History,
} from '../lib/timelineOps';

/** jsdom returns a zero rect; a fixed virtual lane width keeps math sane. */
export const FALLBACK_LANE_WIDTH = 1000;

export interface PeaksPayload {
  sampleRate: number;
  peaks: number[];
}

export interface TimelineProps {
  videoId: string;
  /** Injected RPC bridge (defaults to the preload `window.api`). */
  api?: MediaStudioApi;
  /** The U1 Player handle — lane clicks call `seek()` on it. */
  playerRef?: React.RefObject<PlayerHandle | null>;
  /** The video duration (Video.durationSec). Fallback: library.list, cues. */
  durationSec?: number;
  /** Edit a specific track; default = the first track from tracks.list. */
  trackId?: string;
  /** Fired with the target time on every lane click-to-seek. */
  onSeek?: (timeSec: number) => void;
}

// ---------------------------------------------------------------------------
// pure helpers (exported for unit tests)
// ---------------------------------------------------------------------------

/** Pick the track to edit: explicit id match, else the first track. */
export function pickTrack(tracks: SubtitleTrack[], trackId?: string): SubtitleTrack | null {
  if (trackId) return tracks.find((t) => t.id === trackId) ?? null;
  return tracks[0] ?? null;
}

/** Split point: the playhead when strictly inside the cue, else the middle. */
export function chooseSplitTime(cue: Cue, playhead: number): number {
  if (playhead > cue.start + MIN_CUE_SEC && playhead < cue.end - MIN_CUE_SEC) {
    return playhead;
  }
  return (cue.start + cue.end) / 2;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// ---------------------------------------------------------------------------
// the component
// ---------------------------------------------------------------------------

export function Timeline({
  videoId,
  api: apiProp,
  playerRef,
  durationSec,
  trackId,
  onSeek,
}: TimelineProps): React.ReactElement {
  const api = apiProp ?? getApi();

  const [track, setTrack] = useState<SubtitleTrack | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [draft, setDraft] = useState<Cue[] | null>(null); // in-flight drag preview
  const [selected, setSelected] = useState<number | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [peaks, setPeaks] = useState<PeaksPayload | null>(null);
  const [probedDuration, setProbedDuration] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [textDraft, setTextDraft] = useState('');
  const [startDraft, setStartDraft] = useState('');
  const [endDraft, setEndDraft] = useState('');

  const laneRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dragRef = useRef<{ pos: number; edge: CueEdge } | null>(null);

  const cues: Cue[] = draft ?? history?.present ?? [];

  const lastCueEnd = useMemo(() => cues.reduce((acc, c) => Math.max(acc, c.end), 0), [cues]);
  const duration =
    durationSec && durationSec > 0 ? durationSec : (probedDuration ?? Math.max(lastCueEnd, 1));

  // -- load track + peaks (+ duration fallback) ----------------------------
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await api.rpc<{ tracks: SubtitleTrack[] }>('tracks.list', {
          videoId,
        });
        if (!alive) return;
        const found = pickTrack(res?.tracks ?? [], trackId);
        if (found) {
          setTrack(found);
          setHistory(createHistory(found.cues ?? []));
          setSelected(null);
        } else {
          setError('No subtitle track on this video — generate one first.');
        }
      } catch (err: unknown) {
        if (alive) setError(errorMessage(err));
      }
    })();
    void (async () => {
      try {
        const res = await api.rpc<PeaksPayload>('timeline.peaks', { videoId });
        if (alive && res && Array.isArray(res.peaks)) setPeaks(res);
      } catch {
        // The waveform is decoration — cue editing must work without it.
        if (alive) setPeaks(null);
      }
    })();
    if (!(durationSec && durationSec > 0)) {
      void (async () => {
        try {
          const res = await api.rpc<{ videos: Array<{ id: string; durationSec: number }> }>(
            'library.list',
          );
          const video = res?.videos?.find((v) => v.id === videoId);
          if (alive && video && video.durationSec > 0) {
            setProbedDuration(video.durationSec);
          }
        } catch {
          /* fall back to the cue extent */
        }
      })();
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, trackId]);

  // -- sync the editor inputs to the selected cue --------------------------
  const selectedCue = selected !== null ? (cues[selected] ?? null) : null;
  useEffect(() => {
    if (selectedCue) {
      setTextDraft(selectedCue.text);
      setStartDraft(String(selectedCue.start));
      setEndDraft(String(selectedCue.end));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, history]);

  // -- waveform canvas ------------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !peaks || peaks.peaks.length === 0) return;
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext('2d');
    } catch {
      return; // jsdom without node-canvas — waveform is visual-only
    }
    if (!ctx) return;
    const { width, height } = canvas;
    ctx.clearRect(0, 0, width, height);
    // DESIGN (tokens-only): the JS-drawn waveform consumes the same token
    // ladder as the CSS — read the lane's --timeline-wave alias (set in
    // features/timeline.css, pointing at --text-faint) off the canvas. The
    // literal below only backstops non-CSSOM environments (jsdom) and mirrors
    // the --text-faint token value.
    let wave = '';
    try {
      wave = getComputedStyle(canvas).getPropertyValue('--timeline-wave').trim();
    } catch {
      /* non-browser test envs: fall through to the token mirror */
    }
    ctx.fillStyle = wave || '#50555f';
    const n = peaks.peaks.length;
    const mid = height / 2;
    for (let i = 0; i < n; i += 1) {
      const x = (i / n) * width;
      const barW = Math.max(width / n, 1);
      const h = Math.max(peaks.peaks[i] * height, 1);
      ctx.fillRect(x, mid - h / 2, barW, h);
    }
  }, [peaks]);

  // -- commit an op into the history ----------------------------------------
  const commit = useCallback((next: Cue[]) => {
    setHistory((h) => (h ? pushHistory(h, next) : h));
    setStatus(null);
  }, []);

  // -- lane interaction ------------------------------------------------------
  const laneTime = useCallback(
    (clientX: number): number => {
      const lane = laneRef.current;
      const rect = lane?.getBoundingClientRect();
      const width = rect && rect.width > 0 ? rect.width : FALLBACK_LANE_WIDTH;
      const left = rect ? rect.left : 0;
      return timeFromClientX(clientX, left, width, duration);
    },
    [duration],
  );

  const handleLaneClick = (e: React.MouseEvent<HTMLDivElement>): void => {
    const t = laneTime(e.clientX);
    setPlayhead(t);
    playerRef?.current?.seek(t);
    onSeek?.(t);
    const cueEl = (e.target as HTMLElement).closest?.('[data-cue]');
    if (cueEl) {
      const pos = Number(cueEl.getAttribute('data-cue'));
      if (Number.isInteger(pos)) setSelected(pos);
    }
  };

  const handleEdgeMouseDown =
    (pos: number, edge: CueEdge) =>
    (e: React.MouseEvent): void => {
      e.stopPropagation();
      if (!history) return;
      dragRef.current = { pos, edge };
      setDraft(history.present);
    };

  const handleLaneMouseMove = (e: React.MouseEvent<HTMLDivElement>): void => {
    const drag = dragRef.current;
    if (!drag || !history) return;
    const t = laneTime(e.clientX);
    setDraft((prev) => dragEdge(prev ?? history.present, drag.pos, drag.edge, t));
  };

  const handleLaneMouseUp = (): void => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    setDraft(null);
    if (draft && history && draft !== history.present) commit(draft);
  };

  // -- toolbar ops -----------------------------------------------------------
  const present = history?.present ?? [];

  const handleSplit = (): void => {
    if (selected === null || !history) return;
    const cue = present[selected];
    if (!cue) return;
    const next = splitAt(present, selected, chooseSplitTime(cue, playhead));
    if (next !== present) commit(next);
  };

  const handleMerge = (): void => {
    if (selected === null || !history) return;
    const next = mergeAt(present, selected);
    if (next !== present) commit(next);
  };

  const handleRetime = (): void => {
    if (selected === null || !history) return;
    const start = Number.parseFloat(startDraft);
    const end = Number.parseFloat(endDraft);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return;
    const next = retimeAt(present, selected, start, end);
    if (next !== present) commit(next);
  };

  const handleApplyText = (): void => {
    if (selected === null || !history) return;
    const cue = present[selected];
    if (!cue || cue.text === textDraft) return;
    commit(present.map((c, i) => (i === selected ? { ...c, text: textDraft } : c)));
  };

  const handleUndo = (): void => {
    setSelected(null);
    setHistory((h) => (h ? undo(h) : h));
  };

  const handleRedo = (): void => {
    setSelected(null);
    setHistory((h) => (h ? redo(h) : h));
  };

  const handleSave = async (): Promise<void> => {
    if (!track || !history) return;
    setStatus('Saving…');
    try {
      const res = await api.rpc<{ track: SubtitleTrack }>('subtitles.edit', {
        trackId: track.id,
        cues: renumber(history.present),
      });
      if (res?.track) {
        setTrack(res.track);
        setHistory((h) => (h ? pushHistory(h, res.track.cues ?? []) : h));
      }
      setStatus('Saved');
    } catch (err: unknown) {
      setError(errorMessage(err));
      setStatus(null);
    }
  };

  // -- render ----------------------------------------------------------------
  return (
    <section className="timeline">
      <h2 className="timeline__title">Timeline</h2>

      {error && (
        <p role="alert" className="timeline__error">
          {error}
        </p>
      )}
      {status && <p className="timeline__status">{status}</p>}

      <div
        ref={laneRef}
        className="timeline__lane"
        data-testid="timeline-lane"
        onClick={handleLaneClick}
        onMouseMove={handleLaneMouseMove}
        onMouseUp={handleLaneMouseUp}
        style={{ position: 'relative' }}
      >
        <canvas
          ref={canvasRef}
          className="timeline__waveform"
          width={FALLBACK_LANE_WIDTH}
          height={80}
        />
        <div className="timeline__cues" style={{ position: 'relative', height: 36 }}>
          {cues.map((cue, pos) => {
            const { leftPct, widthPct } = cueRectStyle(cue, duration);
            const isSelected = pos === selected;
            return (
              <div
                key={`${cue.start}-${cue.end}-${pos}`}
                data-cue={pos}
                data-selected={isSelected || undefined}
                className={`timeline__cue${isSelected ? ' timeline__cue--selected' : ''}`}
                title={cue.text}
                style={{
                  position: 'absolute',
                  left: `${leftPct}%`,
                  width: `${widthPct}%`,
                  top: 0,
                  bottom: 0,
                }}
              >
                {isSelected && (
                  <>
                    <span
                      data-edge="start"
                      className="timeline__edge timeline__edge--start"
                      onMouseDown={handleEdgeMouseDown(pos, 'start')}
                    />
                    <span
                      data-edge="end"
                      className="timeline__edge timeline__edge--end"
                      onMouseDown={handleEdgeMouseDown(pos, 'end')}
                    />
                  </>
                )}
              </div>
            );
          })}
        </div>
        <div
          className="timeline__playhead"
          data-testid="playhead"
          style={{
            position: 'absolute',
            left: `${duration > 0 ? (playhead / duration) * 100 : 0}%`,
            top: 0,
            bottom: 0,
            width: 1,
          }}
        />
      </div>

      <div className="timeline__toolbar">
        <button
          type="button"
          data-action="split"
          disabled={selected === null}
          onClick={handleSplit}
        >
          Split
        </button>
        <button
          type="button"
          data-action="merge"
          disabled={selected === null || selected >= cues.length - 1}
          onClick={handleMerge}
        >
          Merge with next
        </button>
        <button
          type="button"
          data-action="undo"
          disabled={!history || !canUndo(history)}
          onClick={handleUndo}
        >
          Undo
        </button>
        <button
          type="button"
          data-action="redo"
          disabled={!history || !canRedo(history)}
          onClick={handleRedo}
        >
          Redo
        </button>
        <button
          type="button"
          data-action="save"
          disabled={!track || !history}
          onClick={() => {
            void handleSave();
          }}
        >
          Save
        </button>
      </div>

      {selectedCue && (
        <div className="timeline__editor">
          <label>
            Text
            <textarea
              data-action="cue-text"
              value={textDraft}
              onChange={(e) => setTextDraft(e.target.value)}
              onBlur={handleApplyText}
            />
          </label>
          <button type="button" data-action="apply-text" onClick={handleApplyText}>
            Apply text
          </button>
          <label>
            Start (s)
            <input
              data-action="retime-start"
              type="number"
              step="0.01"
              value={startDraft}
              onChange={(e) => setStartDraft(e.target.value)}
            />
          </label>
          <label>
            End (s)
            <input
              data-action="retime-end"
              type="number"
              step="0.01"
              value={endDraft}
              onChange={(e) => setEndDraft(e.target.value)}
            />
          </label>
          <button type="button" data-action="retime" onClick={handleRetime}>
            Apply times
          </button>
        </div>
      )}
    </section>
  );
}

export default Timeline;
