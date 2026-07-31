// CaptionClipLane.tsx — the KEYBOARD-operable caption clip lane (v1.5 §4, item 6).
//
// The redesign's charter removes a locked WCAG-A barrier: the shipped Timeline
// edits cues with mouse-only pointer drags (no key handlers). This lane is the
// keyboard-first replacement for the CAPTION phase — a thin consumer of the shared
// editor state that renders each cue as a focusable clip over the window's time
// axis and edits it entirely from the keyboard:
//   * Enter / Space  — seek the shared playhead to the clip start (and select it);
//   * Arrow Left/Right — MOVE the whole clip earlier/later (neighbor-clamped);
//   * Shift+Arrow      — RESIZE the clip's out-point (neighbor-clamped).
// All cue math is the shipped, unit-tested `timelineOps` (nudgeAt/dragEdge) — the
// same neighbor-clamping the mouse Timeline uses, reused, not rewritten.
//
// SCOPE OF THE MOVE (read before "fixing" a silent arrow key). A move preserves
// duration, so a clip whose neighbor ABUTS it has zero legal room — and real word
// cues abut exactly (the sidecar emits a word's end and the next word's start from
// one array element). Moving such a clip necessarily RETIMES a neighbor, i.e. a
// ripple / overwrite / swap semantics, and picking one is a product decision that
// is deliberately NOT implemented here: this lane only ever edits the ONE focused
// cue. What is implemented is that the refusal is never silent — the boundary is
// announced through the polite live region below, so the key has a defined,
// perceivable outcome instead of doing nothing. Until ripple ships, "arrow keys
// move a clip" means "within its own gap".

import React from 'react';
import { type Cue, MIN_CUE_SEC, dragEdge, nudgeAt } from '../../lib/timelineOps';
import { useEditor } from '../EditorContext';
import './captionClipLane.css';

/** One keyboard nudge = 0.1s (fine, predictable caption timing steps). */
export const CLIP_NUDGE_SEC = 0.1;

/** Clamp a percentage into [0, 100] for absolute positioning. */
function pct(value: number): number {
  return Math.min(Math.max(value, 0), 100);
}

export function CaptionClipLane(): React.ReactElement {
  const { state, dispatch } = useEditor();
  // Declared BEFORE the empty-cues early return so hook order is unconditional.
  const [notice, setNotice] = React.useState('');
  const { cues, video, playhead, selection } = state;
  const { start: winStart, end: winEnd } = video.window;
  const span = Math.max(winEnd - winStart, MIN_CUE_SEC);

  if (cues.length === 0) {
    return (
      <div className="caption-clip-lane caption-clip-lane--empty" aria-label="Caption clips">
        <p className="caption-clip-lane__empty">
          No caption clips yet — generate captions to edit their timing here.
        </p>
      </div>
    );
  }

  const onClipKeyDown =
    (pos: number, cue: Cue) =>
    (e: React.KeyboardEvent): void => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        dispatch({ type: 'selectCue', index: pos });
        dispatch({ type: 'setPlayhead', playhead: cue.start });
        return;
      }
      const dir = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (dir === 0) return;
      e.preventDefault();
      const delta = dir * CLIP_NUDGE_SEC;
      // Shift = resize the out-point; plain arrow = TRANSLATE the whole clip
      // (duration-preserving). Both are neighbor-clamped by timelineOps.
      const next = e.shiftKey
        ? dragEdge(cues, pos, 'end', cue.end + delta)
        : nudgeAt(cues, pos, delta);
      if (next === cues) {
        // Nothing legal to do (see SCOPE OF THE MOVE above). Announce it and bail
        // BEFORE dispatching, so a no-room press does not rebuild editor state.
        setNotice(`Caption ${pos + 1} has no room to move ${dir > 0 ? 'later' : 'earlier'}.`);
        return;
      }
      setNotice('');
      dispatch({ type: 'setCues', cues: next });
    };

  return (
    <div
      className="caption-clip-lane"
      role="group"
      aria-label="Caption clips — arrow keys move a clip, Shift+arrow resizes, Enter seeks"
    >
      <div className="caption-clip-lane__track">
        {cues.map((cue, pos) => {
          const selected = pos === selection;
          return (
            <button
              key={`${cue.index}-${pos}`}
              type="button"
              className={`caption-clip${selected ? ' is-selected' : ''}`}
              data-clip={pos}
              aria-pressed={selected}
              aria-label={`Caption ${pos + 1}: ${cue.text}`}
              style={{
                left: `${pct(((cue.start - winStart) / span) * 100)}%`,
                width: `${pct(((cue.end - cue.start) / span) * 100)}%`,
              }}
              onClick={() => dispatch({ type: 'selectCue', index: pos })}
              onKeyDown={onClipKeyDown(pos, cue)}
            >
              <span className="caption-clip__text">{cue.text}</span>
            </button>
          );
        })}
        <div
          className="caption-clip-lane__playhead"
          data-testid="clip-playhead"
          style={{ left: `${pct(((playhead - winStart) / span) * 100)}%` }}
        />
      </div>
      {/* Mounted while EMPTY (a region inserted with its text is not reliably
          announced) and a <div>, which has no default margin — so an empty
          notice costs no layout and the lane needs no extra CSS. */}
      <div className="caption-clip-lane__status" role="status" aria-live="polite">
        {notice}
      </div>
    </div>
  );
}

export default CaptionClipLane;
