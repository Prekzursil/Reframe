// ShortMakerControls.tsx — the short-maker controls form (presentational).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). This is a PURE presentational component:
// it owns no state and no side effects — every value + handler is passed in by
// the ShortMaker container, which keeps all logic/state. The rendered DOM
// (labels, classes, structure) is byte-identical to the inline JSX it replaced,
// so the existing aria-label-driven component tests stay green.

import React from 'react';

import {
  type EmphasisChoice,
  type AudioTrackOption,
  ASPECT_OPTIONS,
  EMPHASIS_LABELS,
  EMPHASIS_OPTIONS,
  MIN_CLIP_SEC,
  MAX_CLIP_SEC,
  REFRAME_ENGINE_LABELS,
  REFRAME_ENGINE_OPTIONS,
  type ShortMakerControls as ShortMakerControlsState,
  clamp,
} from './shortMakerLogic';
import {
  type PlatformPresetId,
  PLATFORM_PRESETS,
  PLATFORM_PRESET_IDS,
} from './shortMakerPresets';
import { CAPTION_STYLES } from './shortMakerLogic';

export interface ShortMakerControlsProps {
  videoId: string;
  prompt: string;
  controls: ShortMakerControlsState;
  audioTracks: AudioTrackOption[];
  audioTrackId: string;
  busy: boolean;
  /** True once at least one candidate exists (drives the submit-button label). */
  hasCandidates: boolean;
  setPrompt: (value: string) => void;
  setControl: <K extends keyof ShortMakerControlsState>(
    key: K,
    value: ShortMakerControlsState[K],
  ) => void;
  setAudioTrackId: (value: string) => void;
  applyPlatformPreset: (presetId: PlatformPresetId) => void;
  onSubmit: () => void;
  onBatch: () => void;
  onCancel: () => void;
}

/**
 * The structured controls form: prompt, count/duration/aspect/language/style,
 * caption + reframe + audio pickers, the P3/P4 toggles, the platform presets,
 * and the select/batch/cancel actions.
 */
export function ShortMakerControls({
  videoId,
  prompt,
  controls,
  audioTracks,
  audioTrackId,
  busy,
  hasCandidates,
  setPrompt,
  setControl,
  setAudioTrackId,
  applyPlatformPreset,
  onSubmit,
  onBatch,
  onCancel,
}: ShortMakerControlsProps): React.JSX.Element {
  return (
    <form
      className="shortmaker-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <label className="sm-field">
        <span>Prompt</span>
        <textarea
          aria-label="Prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What kind of shorts do you want? (e.g. the most quotable moments)"
          rows={3}
        />
      </label>

      <div className="sm-controls">
        <label className="sm-field">
          <span>Count</span>
          <input
            aria-label="Count"
            type="number"
            min={1}
            value={controls.count}
            onChange={(e) => setControl('count', Number(e.target.value))}
          />
        </label>

        <label className="sm-field">
          <span>Min seconds</span>
          <input
            aria-label="Min seconds"
            type="number"
            min={MIN_CLIP_SEC}
            max={MAX_CLIP_SEC}
            value={controls.minSec}
            onChange={(e) => setControl('minSec', Number(e.target.value))}
          />
        </label>

        <label className="sm-field">
          <span>Max seconds</span>
          <input
            aria-label="Max seconds"
            type="number"
            min={MIN_CLIP_SEC}
            max={MAX_CLIP_SEC}
            value={controls.maxSec}
            onChange={(e) => setControl('maxSec', Number(e.target.value))}
          />
        </label>

        <label className="sm-field">
          <span>Aspect</span>
          <select
            aria-label="Aspect"
            value={controls.aspect}
            onChange={(e) => setControl('aspect', e.target.value)}
          >
            {ASPECT_OPTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>

        <label className="sm-field">
          <span>Language</span>
          <input
            aria-label="Language"
            type="text"
            value={controls.language}
            onChange={(e) => setControl('language', e.target.value)}
          />
        </label>

        <label className="sm-field">
          <span>Caption style</span>
          <select
            aria-label="Caption style"
            value={controls.captionStyle}
            onChange={(e) => setControl('captionStyle', e.target.value)}
          >
            {CAPTION_STYLES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>

        <label className="sm-field">
          <span>Reframe engine</span>
          <select
            aria-label="Reframe engine"
            value={controls.reframeEngine}
            onChange={(e) => setControl('reframeEngine', e.target.value)}
          >
            {REFRAME_ENGINE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {REFRAME_ENGINE_LABELS[r]}
              </option>
            ))}
          </select>
        </label>

        <label className="sm-field">
          <span>Audio track</span>
          <select
            aria-label="Audio track"
            value={audioTrackId}
            onChange={(e) => setAudioTrackId(e.target.value)}
          >
            <option value="">Original</option>
            {audioTracks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.lang}, {t.kind})
              </option>
            ))}
          </select>
        </label>

        {/* P3-A: hook-title overlay toggle (default ON). */}
        <label className="sm-field sm-toggle">
          <span>Hook title</span>
          <input
            aria-label="Hook title"
            type="checkbox"
            checked={controls.hookTitle}
            onChange={(e) => setControl('hookTitle', e.target.checked)}
          />
        </label>

        {/* P3-B: filler-removal toggle (default OFF until proven). */}
        <label className="sm-field sm-toggle">
          <span>
            Remove fillers <span className="sm-tag-exp">experimental</span>
          </span>
          <input
            aria-label="Remove fillers"
            type="checkbox"
            checked={controls.removeFillers}
            onChange={(e) => setControl('removeFillers', e.target.checked)}
          />
        </label>

        {/* P4 §8a: keyword/emoji emphasis — tri-state (Auto defers to the
            template's per-style default; On/Off override it). */}
        <label className="sm-field">
          <span>Emphasis</span>
          <select
            aria-label="Emphasis"
            value={controls.emphasis}
            onChange={(e) => setControl('emphasis', e.target.value as EmphasisChoice)}
          >
            {EMPHASIS_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {EMPHASIS_LABELS[opt]}
              </option>
            ))}
          </select>
        </label>

        {/* P4 §8b: auto punch-in zoom on emphasis beats (default OFF). */}
        <label className="sm-field sm-toggle">
          <span>Auto zoom</span>
          <input
            aria-label="Auto zoom"
            type="checkbox"
            checked={controls.autoZoom}
            onChange={(e) => setControl('autoZoom', e.target.checked)}
          />
        </label>
      </div>

      {/* P4 §8c: platform presets — one tap sets aspect/maxSec/count. */}
      <div className="sm-presets" role="group" aria-label="Platform presets">
        <span className="sm-presets-label">Presets</span>
        {PLATFORM_PRESET_IDS.map((id) => {
          const p = PLATFORM_PRESETS[id];
          // The effective max obeys the §5 hard window (sidecar clamps too).
          const effMax = clamp(p.maxSec, MIN_CLIP_SEC, MAX_CLIP_SEC);
          return (
            <button
              key={id}
              type="button"
              className="sm-preset"
              data-preset={id}
              aria-label={`${p.label} preset`}
              title={`${p.aspect} · up to ${effMax}s · ${p.count} clips`}
              disabled={busy}
              onClick={() => applyPlatformPreset(id as PlatformPresetId)}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      <div className="sm-actions">
        <button type="submit" disabled={busy || !videoId}>
          {hasCandidates ? 'Regenerate' : 'Find clips'}
        </button>
        {/* P4 §8c: unattended batch — select, auto-approve top N, export. */}
        <button
          type="button"
          className="sm-batch"
          aria-label="Make N shorts"
          disabled={busy || !videoId}
          onClick={() => onBatch()}
        >
          Make {controls.count} shorts
        </button>
        {busy && (
          <button type="button" onClick={() => onCancel()}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

export default ShortMakerControls;
