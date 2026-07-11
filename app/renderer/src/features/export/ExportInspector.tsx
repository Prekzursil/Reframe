// ExportInspector.tsx — the Export phase inspector as a GUARDED COMMIT (v1.5 §4).
//
// Export is the ONE irreversible, spend/file-writing action, so this inspector
// guards it: a per-platform destination matrix, a pre-flight SUMMARY (clips /
// aspect / duration / est. time / est. spend), a restated privacy beat, and ONE
// amber approve action — ranked ABOVE the secondary matrix by scale + elevation,
// never an equal-weight tile. The approve is a TWO-STEP guarded commit: the primary
// button opens an explicit confirm gate; only "Export now" fires `onCommit`.
//
// A THIN CONSUMER of the shared editor state (`useEditor`): it reads the video/
// cues/cropPlan to build the pre-flight and never owns the stage or a copy of them.

import React, { useState } from 'react';
import type { ConvertOptions } from '../../lib/rpc';
import { useEditor } from '../EditorContext';
import {
  type PlatformPreset,
  buildPreflight,
  exportConvertOptions,
  firstAvailablePresetId,
  presetById,
  windowDurationSec,
} from './exportModel';
import { PresetMatrix } from './PresetMatrix';
import './export.css';

/** The local-first privacy beat — the same promise the Studio inspector makes. */
export const EXPORT_PRIVACY_NOTE = 'Everything runs on your computer — nothing is uploaded.';

/** The guarded-commit confirm copy: Export IS the bake, and it stays local. */
export const EXPORT_CONFIRM_BLURB =
  'This is the final render — everything you set is baked into the file. It is written to your ' +
  'computer; nothing is uploaded.';

export interface ExportInspectorProps {
  /** Fired only after the explicit confirm — starts the guarded render. */
  onCommit: (preset: PlatformPreset, options: ConvertOptions) => void;
}

export function ExportInspector({ onCommit }: ExportInspectorProps): React.ReactElement {
  const { state } = useEditor();
  const durationSec = windowDurationSec(state);
  const [selected, setSelected] = useState<string>(() => firstAvailablePresetId(durationSec));
  const [confirming, setConfirming] = useState(false);

  const preset = presetById(selected);
  const preflight = buildPreflight(state, preset);

  const commit = (): void => {
    setConfirming(false);
    onCommit(preset, exportConvertOptions());
  };

  return (
    <aside className="export-inspector" aria-label="Export">
      <PresetMatrix
        value={selected}
        onChange={setSelected}
        durationSec={durationSec}
        disabled={confirming}
      />

      <section className="export-inspector__preflight" aria-label="Pre-flight summary">
        <h3 className="export-inspector__preflight-title">Ready to export to {preset.name}</h3>
        <div className="export-inspector__preflight-grid">
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Clips</span>
            <span className="export-inspector__cell-value">{preflight.clipCount}</span>
          </div>
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Aspect</span>
            <span className="export-inspector__cell-value">{preflight.aspect}</span>
          </div>
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Length</span>
            <span className="export-inspector__cell-value">{preflight.durationLabel}</span>
          </div>
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Est. time</span>
            <span className="export-inspector__cell-value">{preflight.estRenderLabel}</span>
          </div>
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Est. cost</span>
            <span className="export-inspector__cell-value">{preflight.estSpendLabel}</span>
          </div>
        </div>
      </section>

      <p className="export-inspector__privacy">{EXPORT_PRIVACY_NOTE}</p>

      {confirming ? (
        <div className="export-inspector__confirm" role="group" aria-label="Confirm export">
          <h3 className="export-inspector__confirm-title">Export to {preset.name}?</h3>
          <p className="export-inspector__confirm-blurb">{EXPORT_CONFIRM_BLURB}</p>
          <div className="export-inspector__confirm-actions">
            <button type="button" className="export-inspector__confirm-approve" onClick={commit}>
              Export now
            </button>
            <button
              type="button"
              className="export-inspector__confirm-cancel"
              onClick={() => setConfirming(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="export-inspector__primary"
          onClick={() => setConfirming(true)}
        >
          Export to {preset.name}
        </button>
      )}
    </aside>
  );
}

export default ExportInspector;
