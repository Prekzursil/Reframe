// VideoTimeline.tsx — the DIRECT-MANIPULATION multi-lane video editor.
//
// This is the panel Reframe did not have: stacked video lanes holding real
// CLIPS (source windows), drag-to-trim handles on the clip itself, a razor, and
// drag-to-reorder — persisted in the project manifest under `videoTracks` and
// rendered through the shipped frame-accurate cutter.
//
// It is NOT `Timeline.tsx`. That panel edits subtitle CUES (text over time) and
// is owned elsewhere; this one edits VIDEO (source windows over time). The two
// models are different and deliberately do not share state.
//
// THE ONE RULE THIS FILE EXISTS TO ENFORCE: what is on screen equals what is
// stored. A drag shows a local clamped `draft` so the gesture feels continuous,
// but on release the edit is committed to the sidecar and the lanes are RE-READ
// from it. If the commit FAILS the draft is dropped and the error is shown — the
// UI snaps back to the stored truth rather than leaving a phantom edit the user
// believes is saved. That is the difference between an editor and a demo.
//
// UNDO is an INVERSE-CALL stack, not a local state stack. Because every commit
// re-reads from the sidecar, a local "previous lanes" snapshot could never be
// restored without a call anyway — a history stack here would leave a
// permanently-disabled Undo button, which is exactly the kind of dead control
// this panel must not ship. So an op that CAN be inverted by one existing wire
// call (move, trim) pushes its inverse; an op that cannot (split, remove, lane
// add/remove) CLEARS the stack, because we can no longer walk back past it. The
// button is enabled exactly when a real inverse is available.
//
// Wire surface consumed (features/video_tracks.py):
//   tracks.video.list / addLane / removeLane / trimClip / splitClip / moveClip
//   tracks.video.removeClip / tracks.video.render  (render is a long JOB)

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { extractJobError } from '../components/useJob';
import {
  type ClipEdge,
  type Fps,
  type VideoClip,
  type VideoLane,
  applyClips,
  clipRectStyle,
  clipTimelineEnd,
  findClip,
  laneRows,
  movePreview,
  snapToFrame,
  splitPreview,
  timeFromClientX,
  timelineDuration,
  trimPreview,
} from '../lib/videoTimelineOps';
import { getApi } from './_api';
import './panels.css';
import './videoTimeline.css';
import * as client from './videoTimelineClient';

export interface VideoTimelineProps {
  videoId: string;
  /** Called with the rendered file path once `tracks.video.render` finishes. */
  onRendered?: (path: string) => void;
}

/** What a mouse gesture in progress is doing. */
interface Drag {
  clipId: string;
  laneId: string;
  kind: 'trim' | 'move';
  edge: ClipEdge;
}

/** A single-call reversal of a committed edit. */
interface Inverse {
  label: string;
  run: () => Promise<void>;
}

type Busy = '' | 'list' | 'commit' | 'render';

/** How many reversible edits to remember. */
export const MAX_UNDO = 50;

const ERR = (e: unknown): string => (e instanceof Error ? e.message : String(e));

export function VideoTimeline({ videoId, onRendered }: VideoTimelineProps): React.ReactElement {
  const [stored, setStored] = useState<VideoLane[] | null>(null);
  const [fps, setFps] = useState<Fps>(30);
  const [draft, setDraft] = useState<VideoLane[] | null>(null);
  const [inverses, setInverses] = useState<Inverse[]>([]);
  const [busy, setBusy] = useState<Busy>('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [pct, setPct] = useState(0);

  const dragRef = useRef<Drag | null>(null);
  const trackRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // -- load ------------------------------------------------------------------
  /**
   * Re-read the authoritative lane state.
   *
   * `clearError` MUST be false when this runs as the ROLLBACK half of a failed
   * commit. Clearing unconditionally wiped the message the commit had just set,
   * so a refused edit snapped back with NO explanation — a silent drop, the one
   * behaviour this panel exists to prevent. Caught by
   * "a FAILED commit shows the error and re-reads".
   */
  const refresh = useCallback(
    async (clearError = true) => {
      if (!videoId) return;
      setBusy('list');
      if (clearError) setError('');
      try {
        const state = await client.fetchLanes(getApi(), videoId);
        setFps(state.fps);
        setStored(state.lanes);
      } catch (err) {
        setError(ERR(err));
      } finally {
        setBusy('');
      }
    },
    [videoId],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // `storedLanes` is the sidecar's version; `lanes` is what is on screen (the
  // drag draft when one is in flight). Narrowing the null ONCE here means every
  // op below works on a plain array — no repeated `stored === null` guard that no
  // input could ever take (clips only render once `stored` is set).
  const storedLanes = stored ?? [];
  const lanes = draft ?? storedLanes;
  const rows = useMemo(() => laneRows(lanes), [lanes]);
  // The ruler spans the authored timeline (gaps included) with a 1s floor so an
  // empty timeline still has a clickable track rather than a zero-width strip.
  const duration = Math.max(timelineDuration(lanes), 1);

  /**
   * Run an edit, then RE-READ the lanes so the panel shows the sidecar's version
   * of what happened. On failure the local draft is dropped and the error is
   * surfaced — never a phantom edit left on screen.
   *
   * `inverse === null` means the edit cannot be reversed by a single call, so the
   * undo stack is CLEARED rather than left offering a reversal that would land on
   * the wrong state.
   */
  const commit = useCallback(
    async (label: string, call: () => Promise<void>, inverse: Inverse | null) => {
      setBusy('commit');
      setError('');
      setStatus('');
      let ok = false;
      try {
        await call();
        ok = true;
        setStatus(label);
      } catch (err) {
        setError(ERR(err));
      } finally {
        setDraft(null);
        setBusy('');
      }
      if (ok) {
        setInverses((prev) => (inverse === null ? [] : [...prev, inverse].slice(-MAX_UNDO)));
      }
      // Re-read on BOTH paths: after a success it is the authoritative result,
      // after a failure it is the rollback. Keep the failure message on the
      // rollback path so the snap-back is explained, not silent.
      await refresh(ok);
    },
    [refresh],
  );

  /** Run the newest inverse. Does NOT push an inverse of its own (that is redo). */
  const undoLast = useCallback(() => {
    const top = inverses[inverses.length - 1];
    /* v8 ignore next -- the button is disabled when the stack is empty */
    if (!top) return;
    setInverses((prev) => prev.slice(0, -1));
    setBusy('commit');
    setError('');
    setStatus('');
    void (async () => {
      let ok = false;
      try {
        await top.run();
        ok = true;
        setStatus(`Undid: ${top.label}`);
      } catch (err) {
        setError(ERR(err));
      } finally {
        setDraft(null);
        setBusy('');
      }
      await refresh(ok); // keep the failure message on the rollback path
    })();
  }, [inverses, refresh]);

  // -- mouse gestures --------------------------------------------------------
  const laneTime = useCallback(
    (laneId: string, clientX: number): number => {
      const el = trackRefs.current.get(laneId);
      /* v8 ignore next -- the ref is set by the same render that binds the handler */
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      return timeFromClientX(clientX, rect.left, rect.width, duration);
    },
    [duration],
  );

  const startDrag =
    (clipId: string, laneId: string, kind: Drag['kind'], edge: ClipEdge) =>
    (e: React.MouseEvent): void => {
      e.stopPropagation();
      dragRef.current = { clipId, laneId, kind, edge };
      // Seed the draft so every later mousemove has a base to clamp against.
      setDraft(lanes);
      setSelected(clipId);
    };

  const onTrackMouseMove =
    (laneId: string) =>
    (e: React.MouseEvent<HTMLDivElement>): void => {
      const drag = dragRef.current;
      if (!drag || drag.laneId !== laneId) return;
      const t = laneTime(laneId, e.clientX);
      setDraft((prev) => {
        // NOTE: a v8 ignore comment must be ONE line — v8 miscounts `next N` across a
        // wrapped block comment, which silently leaves the line uncovered instead.
        /* v8 ignore next -- mousedown seeds the draft, so `prev` is never null here */
        const base = prev ?? lanes;
        const at = findClip(base, drag.clipId);
        /* v8 ignore next -- the drag was started from a clip in this very list */
        if (!at) return base;
        const next =
          drag.kind === 'trim'
            ? trimPreview(at.lane, drag.clipId, drag.edge, t, fps)
            : movePreview(at.lane, drag.clipId, t, fps);
        // A null preview means "nothing legal to propose" — keep the last good
        // draft rather than rendering a clip at NaN.
        return next === null ? base : applyClips(base, drag.clipId, [next]);
      });
    };

  const commitTrim = useCallback(
    (clipId: string, edge: ClipEdge, to: number, from: number) =>
      commit('Trimmed', () => client.trimClip(getApi(), videoId, clipId, edge, to), {
        label: 'trim',
        run: () => client.trimClip(getApi(), videoId, clipId, edge, from),
      }),
    [commit, videoId],
  );

  const commitMove = useCallback(
    (clipId: string, to: number, from: number) =>
      commit('Moved', () => client.moveClip(getApi(), videoId, clipId, to), {
        label: 'move',
        run: () => client.moveClip(getApi(), videoId, clipId, from),
      }),
    [commit, videoId],
  );

  const endDrag = (): void => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    /* v8 ignore start -- mousedown seeded the draft from the very list the clip was
       rendered from, so both lookups always hit; this is the runtime guard for a lane
       refresh landing mid-gesture, which no test can schedule deterministically. */
    const edited = draft === null ? null : findClip(draft, drag.clipId);
    const before = findClip(storedLanes, drag.clipId);
    if (!edited || !before) {
      setDraft(null);
      return;
    }
    /* v8 ignore stop */
    const next = edited.clip;
    const prev = before.clip;
    if (drag.kind === 'trim') {
      const to = drag.edge === 'start' ? next.timelineStart : clipTimelineEnd(next);
      const from = drag.edge === 'start' ? prev.timelineStart : clipTimelineEnd(prev);
      // A drag that ended where it started is not an edit — do not spend an RPC
      // on it and do not put a no-op on the undo stack.
      if (to === from) {
        setDraft(null);
        return;
      }
      void commitTrim(drag.clipId, drag.edge, to, from);
      return;
    }
    if (next.timelineStart === prev.timelineStart) {
      setDraft(null);
      return;
    }
    void commitMove(drag.clipId, next.timelineStart, prev.timelineStart);
  };

  // -- toolbar / keyboard ops ------------------------------------------------
  const razor = useCallback(() => {
    /* v8 ignore start -- the Split button is disabled without a selection, and a selected clip is by definition in the list it was selected from */
    if (selected === null) return;
    const at = findClip(storedLanes, selected);
    if (!at) return;
    /* v8 ignore stop */
    // Refuse locally with the SAME rule the sidecar uses, so a mis-aimed razor
    // says why instead of firing a call that comes back as an error.
    if (splitPreview(at.clip, playhead, fps) === null) {
      setError(
        'Put the playhead inside the selected clip (at least one frame either side) to split it.',
      );
      return;
    }
    // A split has no single-call inverse (there is no merge method), so it clears
    // the undo stack rather than pretending to be reversible.
    void commit('Split', () => client.splitClip(getApi(), videoId, selected, playhead), null);
  }, [commit, fps, playhead, selected, storedLanes, videoId]);

  const nudge = useCallback(
    (clipId: string, frames: number) => {
      const at = findClip(storedLanes, clipId);
      /* v8 ignore next -- the handler is bound to a clip in this very list */
      if (!at) return;
      const target = Math.max(0, at.clip.timelineStart + frames / fps);
      const next = movePreview(at.lane, clipId, target, fps);
      if (next === null || next.timelineStart === at.clip.timelineStart) return;
      void commitMove(clipId, next.timelineStart, at.clip.timelineStart);
    },
    [commitMove, fps, storedLanes],
  );

  const trimToPlayhead = useCallback(
    (clipId: string, edge: ClipEdge) => {
      const at = findClip(storedLanes, clipId);
      /* v8 ignore next -- the handler is bound to a clip in this very list */
      if (!at) return;
      const next = trimPreview(at.lane, clipId, edge, playhead, fps);
      if (next === null) return;
      const to = edge === 'start' ? next.timelineStart : clipTimelineEnd(next);
      const from = edge === 'start' ? at.clip.timelineStart : clipTimelineEnd(at.clip);
      if (to === from) return;
      void commitTrim(clipId, edge, to, from);
    },
    [commitTrim, fps, playhead, storedLanes],
  );

  const removeClip = useCallback(
    (clipId: string) => {
      setSelected(null);
      // Removing a clip cannot be inverted by one call (re-adding mints a new id),
      // so the stack is cleared.
      void commit('Removed', () => client.removeClip(getApi(), videoId, clipId), null);
    },
    [commit, videoId],
  );

  const onClipKeyDown =
    (clipId: string) =>
    (e: React.KeyboardEvent): void => {
      const step = e.shiftKey ? 10 : 1;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        nudge(clipId, -step);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        nudge(clipId, step);
      } else if (e.key === '[') {
        e.preventDefault();
        trimToPlayhead(clipId, 'start');
      } else if (e.key === ']') {
        e.preventDefault();
        trimToPlayhead(clipId, 'end');
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        removeClip(clipId);
      }
    };

  // -- render (a long job) ---------------------------------------------------
  const doRender = useCallback(async () => {
    setBusy('render');
    setError('');
    setStatus('');
    setPct(0);
    const api = getApi();
    let jobId = '';
    try {
      jobId = await client.startRender(api, videoId);
    } catch (err) {
      setError(ERR(err));
      setBusy('');
      return;
    }
    const offProgress = api.onProgress((ev) => {
      if (ev.jobId === jobId) {
        setPct(ev.pct);
        setStatus(ev.message);
      }
    });
    try {
      const path = await new Promise<string>((resolve, reject) => {
        /* v8 ignore next 4 -- the real preload bridge always exposes onJobDone */
        if (typeof api.onJobDone !== 'function') {
          reject(new Error('This build cannot report job completion.'));
          return;
        }
        const off = api.onJobDone((ev) => {
          if (ev.jobId !== jobId) return;
          off();
          const failure = extractJobError(ev.result);
          if (failure) {
            reject(new Error(failure.message));
            return;
          }
          const result = ev.result as { path?: unknown } | undefined;
          if (typeof result?.path !== 'string') {
            reject(new Error('The render finished without reporting an output file.'));
            return;
          }
          resolve(result.path);
        });
      });
      setStatus(`Rendered ${path}`);
      onRendered?.(path);
    } catch (err) {
      setError(ERR(err));
    } finally {
      offProgress();
      setBusy('');
    }
  }, [onRendered, videoId]);

  // -- view ------------------------------------------------------------------
  const isBusy = busy !== '';
  const clipLabel = (clip: VideoClip): string => {
    // Index the last element rather than `.pop() ?? path`: split always yields at
    // least one element, so the `??` fallback was a branch no input could take.
    const parts = clip.path.split(/[\\/]/);
    return `${parts[parts.length - 1]} ${clip.srcIn.toFixed(2)}-${clip.srcOut.toFixed(2)}`;
  };

  return (
    <section className="panel vtl" aria-label="Video timeline">
      <div className="vtl__bar">
        <button
          type="button"
          data-action="undo"
          disabled={inverses.length === 0 || isBusy}
          onClick={undoLast}
        >
          Undo
        </button>
        <button type="button" data-action="split" disabled={!selected || isBusy} onClick={razor}>
          Split at playhead
        </button>
        <button
          type="button"
          data-action="remove-clip"
          disabled={!selected || isBusy}
          onClick={() => selected !== null && removeClip(selected)}
        >
          Remove clip
        </button>
        <button
          type="button"
          data-action="add-lane"
          disabled={isBusy}
          onClick={() => void commit('Lane added', () => client.addLane(getApi(), videoId), null)}
        >
          Add lane
        </button>
        <span className="vtl__spacer" />
        <span className="vtl__readout" data-role="playhead">
          {playhead.toFixed(2)}s / {duration.toFixed(2)}s @ {fps}fps
        </span>
        <button
          type="button"
          data-action="render"
          disabled={isBusy}
          onClick={() => void doRender()}
        >
          Render timeline
        </button>
      </div>

      {busy === 'render' && (
        <progress data-role="render-progress" max={100} value={pct}>
          {pct}%
        </progress>
      )}
      {error !== '' && (
        <p className="vtl__error" role="alert" data-role="error">
          {error}
        </p>
      )}
      {status !== '' && (
        <p className="vtl__status" data-role="status">
          {status}
        </p>
      )}

      <div className="vtl__lanes">
        {rows.length === 0 && (
          <p className="vtl__empty" data-role="empty">
            No video lanes yet.
          </p>
        )}
        {rows.map((lane) => (
          <div className="vtl__lane" key={lane.id} data-lane-id={lane.id}>
            <div className="vtl__laneHead">
              <span className="vtl__laneName">{lane.name}</span>
              <button
                type="button"
                data-action="remove-lane"
                data-lane={lane.id}
                aria-label={`Remove lane ${lane.name}`}
                disabled={isBusy}
                onClick={() =>
                  void commit(
                    'Lane removed',
                    () => client.removeLane(getApi(), videoId, lane.id),
                    null,
                  )
                }
              >
                &times;
              </button>
            </div>
            <div
              className="vtl__track"
              data-role="track"
              data-lane={lane.id}
              ref={(el) => {
                if (el) trackRefs.current.set(lane.id, el);
                else trackRefs.current.delete(lane.id);
              }}
              onMouseMove={onTrackMouseMove(lane.id)}
              onMouseUp={endDrag}
              onMouseLeave={endDrag}
              onClick={(e) => setPlayhead(snapToFrame(laneTime(lane.id, e.clientX), fps))}
            >
              {lane.clips.map((clip) => {
                const { leftPct, widthPct } = clipRectStyle(clip, duration);
                return (
                  <button
                    type="button"
                    key={clip.id}
                    data-clip-id={clip.id}
                    className={`vtl__clip${selected === clip.id ? ' vtl__clip--selected' : ''}`}
                    style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                    aria-pressed={selected === clip.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelected(clip.id);
                    }}
                    onMouseDown={startDrag(clip.id, lane.id, 'move', 'start')}
                    onKeyDown={onClipKeyDown(clip.id)}
                  >
                    {clipLabel(clip)}
                    <span
                      data-edge="start"
                      data-clip={clip.id}
                      className="vtl__edge vtl__edge--start"
                      onMouseDown={startDrag(clip.id, lane.id, 'trim', 'start')}
                    />
                    <span
                      data-edge="end"
                      data-clip={clip.id}
                      className="vtl__edge vtl__edge--end"
                      onMouseDown={startDrag(clip.id, lane.id, 'trim', 'end')}
                    />
                  </button>
                );
              })}
              <span
                className="vtl__playhead"
                data-role="playhead-marker"
                style={{ left: `${Math.min((playhead / duration) * 100, 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
