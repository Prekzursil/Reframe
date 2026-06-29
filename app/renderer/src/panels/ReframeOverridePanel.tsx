// ReframeOverridePanel.tsx — manual per-shot speaker / layout / crop correction
// (V1.1 Lane R, WU R2). Makes an imperfect active-speaker-detection (ASD) result
// shippable (OpusClip-parity manual reframe): for each detected shot the panel
// shows the chosen active speaker + layout, and lets the user FLIP the speaker to
// another detected candidate, SWITCH the layout (single / split / composite), or
// NUDGE / ZOOM the crop. It then computes EXACTLY which shots changed and the
// "Re-render" action hands that affected-shot set to the parent (the R1 engine
// re-renders ONLY those shots — never the whole clip).
//
// Reuses the Director panel's pattern (a thin render shell over pure lib logic +
// per-row controls, immutable state) and the draggable-caption crop infra concept
// (the crop is the same normalised-to-source rectangle CaptionBox edits). All edit
// math is the pure `lib/reframeOverride` helpers; this component only holds the
// override map + wires controls, so it is covered to 100% in isolation.
import React, { useCallback, useMemo, useState } from 'react';
import '../features/panels.css';
import './reframeOverridePanel.css';
import {
  NUDGE_PX,
  SHOT_LAYOUTS,
  ZOOM_IN_FACTOR,
  ZOOM_OUT_FACTOR,
  affectedShotIndices,
  applyShotOverrides,
  cycleSpeaker,
  nudgeCrop,
  type Crop,
  type ShotDecision,
  type ShotLayout,
  type ShotOverride,
  type ShotPlan,
  zoomCrop,
} from '../lib/reframeOverride';

/** The directional crop-nudge buttons (one render callback, four data rows). */
const CROP_NUDGES = [
  { key: 'left', label: '◀', aria: 'Nudge crop left', dx: -NUDGE_PX, dy: 0 },
  { key: 'right', label: '▶', aria: 'Nudge crop right', dx: NUDGE_PX, dy: 0 },
  { key: 'up', label: '▲', aria: 'Nudge crop up', dx: 0, dy: -NUDGE_PX },
  { key: 'down', label: '▼', aria: 'Nudge crop down', dx: 0, dy: NUDGE_PX },
] as const;

/** The zoom-step buttons (tighter / wider crop). */
const ZOOM_STEPS = [
  { key: 'in', label: 'Zoom in', factor: ZOOM_IN_FACTOR },
  { key: 'out', label: 'Zoom out', factor: ZOOM_OUT_FACTOR },
] as const;

/** A friendly noun per layout (the chip + select option label). */
const LAYOUT_LABELS: Record<ShotLayout, string> = {
  single: 'Single speaker',
  split: 'Split screen',
  composite: 'Composite',
};

/** A speaker id shown to the user ("" -> "Auto / none"). */
function speakerLabel(speaker: string): string {
  return speaker === '' ? 'Auto / none' : speaker;
}

/** Round a crop to whole source pixels for display. */
function cropText(crop: Crop): string {
  return crop.map((n) => Math.round(n)).join(', ');
}

export interface ReframeOverridePanelProps {
  /** The editable per-shot plan (derived from a trace / the R1 engine). */
  plan: ShotPlan;
  /** Called with the affected shot indices when the user re-renders. */
  onRerender: (shotIndices: readonly number[]) => void;
}

export function ReframeOverridePanel({ plan, onRerender }: ReframeOverridePanelProps): React.ReactElement {
  const [overrides, setOverrides] = useState<Record<number, ShotOverride>>({});

  const overrideList = useMemo(() => Object.values(overrides), [overrides]);
  const resolved = useMemo(() => applyShotOverrides(plan, overrideList), [plan, overrideList]);
  const affected = useMemo(() => affectedShotIndices(plan, resolved), [plan, resolved]);
  const changed = useMemo(() => new Set(affected), [affected]);

  // Merge a patch into one shot's override (immutable; always carries the index).
  const patch = useCallback((index: number, p: Partial<ShotOverride>): void => {
    setOverrides((prev) => ({ ...prev, [index]: { ...prev[index], index, ...p } }));
  }, []);

  const flipSpeaker = useCallback(
    (shot: ShotDecision): void => patch(shot.index, { speaker: cycleSpeaker(shot.speaker, shot.speakers) }),
    [patch],
  );
  const setLayout = useCallback(
    (index: number, layout: ShotLayout): void => patch(index, { layout }),
    [patch],
  );
  const nudge = useCallback(
    (shot: ShotDecision, dx: number, dy: number): void =>
      patch(shot.index, { crop: nudgeCrop(shot.crop, dx, dy, plan.sourceWidth, plan.sourceHeight) }),
    [patch, plan.sourceWidth, plan.sourceHeight],
  );
  const zoom = useCallback(
    (shot: ShotDecision, factor: number): void =>
      patch(shot.index, { crop: zoomCrop(shot.crop, factor, plan.sourceWidth, plan.sourceHeight) }),
    [patch, plan.sourceWidth, plan.sourceHeight],
  );
  const reset = useCallback((index: number): void => {
    setOverrides((prev) => {
      const next = { ...prev };
      delete next[index];
      return next;
    });
  }, []);

  const rerender = useCallback((): void => onRerender(affected), [onRerender, affected]);

  return (
    <section className="feature-panel reframe-override" aria-label="Manual reframe correction">
      <h2>Fix the framing</h2>
      <p className="reframe-override__intro">
        For each shot, the auto-reframe picked who to follow and how to lay it out. Flip the speaker,
        switch the layout, or nudge the crop on any shot it got wrong — then re-render just those shots.
      </p>

      <div className="reframe-override__shots" data-section="shots">
        {resolved.shots.map((shot) => (
          <ShotRow
            key={shot.index}
            shot={shot}
            changed={changed.has(shot.index)}
            onFlip={flipSpeaker}
            onLayout={setLayout}
            onNudge={nudge}
            onZoom={zoom}
            onReset={reset}
          />
        ))}
      </div>

      <div className="reframe-override__footer" data-section="footer">
        <button
          type="button"
          data-action="rerender"
          onClick={rerender}
          disabled={affected.length === 0}
        >
          {affected.length === 0
            ? 'No changes to re-render'
            : `Re-render ${affected.length} shot${affected.length === 1 ? '' : 's'}`}
        </button>
      </div>
    </section>
  );
}

interface ShotRowProps {
  shot: ShotDecision;
  changed: boolean;
  onFlip: (shot: ShotDecision) => void;
  onLayout: (index: number, layout: ShotLayout) => void;
  onNudge: (shot: ShotDecision, dx: number, dy: number) => void;
  onZoom: (shot: ShotDecision, factor: number) => void;
  onReset: (index: number) => void;
}

function ShotRow({ shot, changed, onFlip, onLayout, onNudge, onZoom, onReset }: ShotRowProps): React.ReactElement {
  const canFlip = shot.speakers.length > 1;
  return (
    <div
      className={`reframe-shot${changed ? ' is-changed' : ''}`}
      data-shot={shot.index}
      data-changed={changed ? 'yes' : 'no'}
    >
      <div className="reframe-shot__head">
        <span className="reframe-shot__title">Shot {shot.index + 1}</span>
        <span className="reframe-shot__range">
          frames {shot.startFrame}–{shot.endFrame}
        </span>
        {changed && <span className="reframe-shot__changed-tag">edited</span>}
      </div>

      <div className="reframe-shot__controls">
        <span className="reframe-shot__group">
          <span data-testid={`speaker-${shot.index}`}>Speaker: {speakerLabel(shot.speaker)}</span>
          <button
            type="button"
            data-action="flip-speaker"
            disabled={!canFlip}
            title={canFlip ? 'Switch to the next detected speaker' : 'Only one speaker detected in this shot'}
            onClick={() => onFlip(shot)}
          >
            Flip
          </button>
        </span>

        <span className="reframe-shot__group">
          <label htmlFor={`layout-${shot.index}`}>Layout</label>
          <select
            id={`layout-${shot.index}`}
            data-action="layout"
            value={shot.layout}
            onChange={(e) => onLayout(shot.index, e.target.value as ShotLayout)}
          >
            {SHOT_LAYOUTS.map((layout) => (
              <option key={layout} value={layout}>
                {LAYOUT_LABELS[layout]}
              </option>
            ))}
          </select>
        </span>

        <span className="reframe-shot__group" data-group="crop">
          {CROP_NUDGES.map((n) => (
            <button
              key={n.key}
              type="button"
              data-action={`nudge-${n.key}`}
              aria-label={n.aria}
              onClick={() => onNudge(shot, n.dx, n.dy)}
            >
              {n.label}
            </button>
          ))}
          {ZOOM_STEPS.map((z) => (
            <button
              key={z.key}
              type="button"
              data-action={`zoom-${z.key}`}
              onClick={() => onZoom(shot, z.factor)}
            >
              {z.label}
            </button>
          ))}
        </span>

        <span className="reframe-shot__crop" data-testid={`crop-${shot.index}`}>
          [{cropText(shot.crop)}]
        </span>

        <button
          type="button"
          data-action="reset"
          className="secondary"
          disabled={!changed}
          onClick={() => onReset(shot.index)}
        >
          Reset
        </button>
      </div>
    </div>
  );
}

export default ReframeOverridePanel;
