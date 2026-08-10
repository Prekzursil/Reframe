// ExportInspector.tsx — the Export phase inspector as a GUARDED COMMIT (v1.5 §4).
//
// Export is the ONE irreversible, spend/file-writing action, so this inspector
// guards it: a per-platform destination matrix, a pre-flight SUMMARY (clips /
// framing / duration / est. time / est. spend), a restated privacy beat, and ONE
// amber approve action — ranked ABOVE the secondary matrix by scale + elevation,
// never an equal-weight tile. The approve is a TWO-STEP guarded commit: the primary
// button opens an explicit confirm gate; only "Export now" fires `onCommit`.
//
// A THIN CONSUMER of the shared editor state (`useEditor`): it reads the video/
// cues/cropPlan to build the pre-flight and never owns the stage or a copy of them.

import React, { useState } from 'react';
import type { ConvertOptions } from '../../lib/rpc';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { useEditor } from '../EditorContext';
import {
  type PlatformPreset,
  buildFanoutPreflight,
  exportConvertOptions,
  fanoutDestinationLabel,
  firstAvailablePresetId,
  framingSummary,
  presetsByIds,
  windowDurationSec,
} from './exportModel';
import { PresetMatrix } from './PresetMatrix';
import './export.css';

/** The local-first privacy beat — the same promise the Studio inspector makes. */
export const EXPORT_PRIVACY_NOTE = 'Everything runs on your machine — nothing is uploaded.';

/** The guarded-commit confirm copy: Export IS the bake, and it stays local. */
export const EXPORT_CONFIRM_BLURB =
  'This is the final render — everything you set is baked into the file. It is written to your ' +
  'machine; nothing is uploaded.';

/**
 * The framing beat, restated where the fan-out is decided.
 *
 * This sentence used to live on the destination matrix ("Aspect is set in Reframe
 * — Export keeps your current framing"), where it also served as the excuse for a
 * single-selection radiogroup. The matrix is now a multi-select aspect matrix, so
 * the sentence moved here — where it is a DISCLOSURE rather than a limitation:
 * the fan-out writes one file per aspect, but Export does not re-crop, so each
 * file carries the framing composed upstream in Reframe.
 */
export const EXPORT_FRAMING_NOTE =
  'Every file keeps the framing you composed in Reframe — Export never re-crops.';

export interface ExportInspectorProps {
  /**
   * Fired only after the explicit confirm — starts the guarded render for EVERY
   * chosen destination (the host de-duplicates them into one file per aspect).
   */
  onCommit: (presets: PlatformPreset[], options: ConvertOptions) => void;
}

export function ExportInspector({ onCommit }: ExportInspectorProps): React.ReactElement {
  const { state } = useEditor();
  const durationSec = windowDurationSec(state);
  const [selected, setSelected] = useState<string[]>(() => [firstAvailablePresetId(durationSec)]);
  const [confirming, setConfirming] = useState(false);

  const presets = presetsByIds(selected);
  const destination = fanoutDestinationLabel(presets);
  const preflight = buildFanoutPreflight(state, presets);
  const framing = framingSummary(state);

  const commit = (): void => {
    setConfirming(false);
    onCommit(presets, exportConvertOptions());
  };

  return (
    <aside className="export-inspector" aria-label="Export">
      <PresetMatrix
        values={selected}
        onChange={setSelected}
        durationSec={durationSec}
        disabled={confirming}
      />

      <section className="export-inspector__preflight" aria-label="Pre-flight summary">
        <h3 className="export-inspector__preflight-title">Ready to export to {destination}</h3>
        <div className="export-inspector__preflight-grid">
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Files</span>
            <span className="export-inspector__cell-value">{preflight.clipCount}</span>
          </div>
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Aspects</span>
            <span className="export-inspector__cell-value">{preflight.aspectLabel}</span>
          </div>
          <div className="export-inspector__cell">
            <span className="export-inspector__cell-label">Framing</span>
            <span className="export-inspector__cell-value">{framing}</span>
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
        <p className="export-inspector__framing-note">{EXPORT_FRAMING_NOTE}</p>
      </section>

      <p className="export-inspector__privacy">{EXPORT_PRIVACY_NOTE}</p>

      {confirming ? (
        // W04: the shared themed gate — this inspector was where the pattern was
        // first written, so the six former native-`confirm()` sites now render the
        // SAME component under a different BEM block rather than a second dialog.
        // `block` keeps this skin's class names (and its CSS in export.css) exactly
        // as they were; the alertdialog role, the id wiring and the focus move all
        // moved into the component.
        <ConfirmDialog
          block="export-inspector__confirm"
          title={`Export to ${destination}?`}
          blurb={EXPORT_CONFIRM_BLURB}
          confirmLabel="Export now"
          cancelLabel="Cancel"
          onConfirm={commit}
          onCancel={() => setConfirming(false)}
        />
      ) : (
        <button
          type="button"
          className="export-inspector__primary"
          onClick={() => setConfirming(true)}
        >
          Export to {destination}
        </button>
      )}
    </aside>
  );
}

export default ExportInspector;
