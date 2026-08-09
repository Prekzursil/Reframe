// TransitionPicker.tsx — the control that lets a user CHOOSE a transition
// (v1.5 transitions lane).
//
// Every join in Reframe was a hard cut and there was no surface anywhere to say
// otherwise: the Director could only be asked for one in prose, and no op kind
// existed to carry the answer. This is that surface — pick the clips, pick the
// style, pick the length, and it emits a wire-valid `transition` op the existing
// `director.apply` path renders.
//
// It is deliberately an HONEST control, which is most of what the markup is for:
//
//   * the running total is the OVERLAP-SUBTRACTED duration, shown next to how
//     much shorter that is than a hard cut — because "the timeline got shorter"
//     is the surprising part of a transition and hiding it would be a trap;
//   * the re-encode cost appears as soon as there is a boundary, before the user
//     commits, not in a tooltip afterwards;
//   * a selection the ENGINE would reject (a clip that cannot outlast the
//     transition) is blocked HERE with the offending clip named, so the failure
//     costs a glance instead of a render.
//
// A thin render shell: all arithmetic and all guard logic is `lib/transitions`,
// so this file holds only selection state and wiring.
//
// NOT YET MOUNTED — read this before citing the feature as user-reachable. This
// component is complete and covered, but nothing imports it except its own test:
// `WORKSPACE_TABS` (views/Workspace.tsx) has no transitions tab, so today a
// `transition` op reaches the engine only through `director.apply` (the AI
// prompt), like the other "engine exists, no UI" ops the v1.5 editing-surface
// audit lists. Mounting needs one thing this component cannot supply itself: a
// list of joinable clips WITH probed durations — `available` is typed to demand
// `durationMs` precisely because the guard and the running total are worthless
// without it, and `Project.clips` does not carry it today.
import React, { useCallback, useMemo, useState } from 'react';
import '../features/panels.css';
import './transitionPicker.css';
import type { DirectorOp } from '../lib/rpc';
import {
  DEFAULT_TRANSITION_MS,
  DEFAULT_TRANSITION_STYLE,
  MAX_TRANSITION_MS,
  MIN_TRANSITION_MS,
  TRANSITION_STYLES,
  type TransitionStyleId,
  buildTransitionOp,
  clampTransitionMs,
  transitionBlocker,
  transitionOutputMs,
  transitionReencodeNote,
  transitionStyleBlurb,
} from '../lib/transitions';

/** One clip the picker can join — its path, a human name, and its real length. */
export interface TransitionClip {
  /** The path handed to the sidecar in `params.clips`. */
  path: string;
  /** The name shown on the chip (never the raw path). */
  label: string;
  /** Probed length in ms — the transition guard and the total both need it. */
  durationMs: number;
}

export interface TransitionPickerProps {
  /** Op id for the emitted op (caller-owned, so plan ids stay deterministic). */
  opId: string;
  /** The clip already on the timeline — the first side of the first boundary. */
  source: TransitionClip;
  /** The clips the user may append with a transition. */
  available: readonly TransitionClip[];
  /** Receives the wire-valid `transition` op when the user commits. */
  onAdd: (op: DirectorOp) => void;
  /** True while a job runs / after apply — every control goes inert. */
  disabled?: boolean;
}

/** Render a millisecond duration as a one-decimal second count ("1.2s"). */
function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

export function TransitionPicker({
  opId,
  source,
  available,
  onAdd,
  disabled = false,
}: TransitionPickerProps): React.ReactElement {
  const [style, setStyle] = useState<TransitionStyleId>(DEFAULT_TRANSITION_STYLE);
  const [durationMs, setDurationMs] = useState<number>(DEFAULT_TRANSITION_MS);
  // The picked CLIPS, not their paths: holding the objects means the durations
  // the guard and the total need are always in hand, with no lookup that could
  // miss and no `?? 0` fallback standing in for a length we do not know. Pick
  // ORDER is the join order, so this is a list, not a set.
  const [picked, setPicked] = useState<readonly TransitionClip[]>([]);

  // The source clip is always the first side of the first boundary, so it takes
  // part in both the total and the too-short guard.
  const chainMs = useMemo<number[]>(
    () => [source.durationMs, ...picked.map((clip) => clip.durationMs)],
    [source.durationMs, picked],
  );

  const outputMs = transitionOutputMs(chainMs, durationMs);
  const hardCutMs = chainMs.reduce((sum, ms) => sum + ms, 0);
  const blocker = transitionBlocker(chainMs, durationMs);
  const reencode = transitionReencodeNote(chainMs.length);
  const blurb = transitionStyleBlurb(style);

  const toggleClip = useCallback((clip: TransitionClip): void => {
    setPicked((prev) =>
      prev.some((c) => c.path === clip.path)
        ? prev.filter((c) => c.path !== clip.path)
        : [...prev, clip],
    );
  }, []);

  const changeStyle = useCallback((e: React.ChangeEvent<HTMLSelectElement>): void => {
    setStyle(e.target.value as TransitionStyleId);
  }, []);

  const changeDuration = useCallback((e: React.ChangeEvent<HTMLInputElement>): void => {
    setDurationMs(clampTransitionMs(Number(e.target.value)));
  }, []);

  const add = useCallback((): void => {
    onAdd(buildTransitionOp({ id: opId, clips: picked.map((c) => c.path), style, durationMs }));
    setPicked([]);
  }, [onAdd, opId, picked, style, durationMs]);

  return (
    <section className="feature-panel transition-picker" aria-label="Add a transition">
      <h2>Join with a transition</h2>
      <p className="transition-picker__intro">
        A plain join is a hard cut. Pick the clips to follow <strong>{source.label}</strong> and how
        the picture should carry between them.
      </p>

      <div className="transition-picker__row">
        <label htmlFor="transition-style">Style</label>
        <select
          id="transition-style"
          data-action="style"
          value={style}
          onChange={changeStyle}
          disabled={disabled}
        >
          {TRANSITION_STYLES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>

        <label htmlFor="transition-duration">Length</label>
        <input
          id="transition-duration"
          data-action="duration"
          type="range"
          min={MIN_TRANSITION_MS}
          max={MAX_TRANSITION_MS}
          step={100}
          value={durationMs}
          onChange={changeDuration}
          disabled={disabled}
        />
        <span data-testid="duration-readout">{seconds(durationMs)}</span>
      </div>

      <p className="transition-picker__blurb" data-testid="style-blurb">
        {blurb}
      </p>

      {available.length === 0 ? (
        <p data-testid="empty">No other clips are available to join to yet.</p>
      ) : (
        <div className="transition-picker__clips" data-section="clips">
          {available.map((clip) => {
            const isPicked = picked.some((c) => c.path === clip.path);
            return (
              <button
                key={clip.path}
                type="button"
                className="transition-picker__clip"
                data-clip={clip.path}
                aria-pressed={isPicked}
                onClick={() => toggleClip(clip)}
                disabled={disabled}
              >
                {isPicked ? '✓ ' : ''}
                {clip.label} · {seconds(clip.durationMs)}
              </button>
            );
          })}
        </div>
      )}

      <p className="transition-picker__total" data-testid="total">
        {picked.length + 1} clips · {seconds(outputMs)} — {seconds(hardCutMs - outputMs)} shorter
        than a hard cut, because each transition overlaps the clips it joins.
      </p>

      {reencode === '' ? null : (
        <p className="transition-picker__reencode" data-testid="reencode">
          {reencode}
        </p>
      )}

      {blocker === null ? null : (
        <p className="transition-picker__blocker" data-testid="blocker" role="status">
          {blocker}
        </p>
      )}

      <button type="button" data-action="add" onClick={add} disabled={disabled || blocker !== null}>
        Add transition
      </button>
    </section>
  );
}
