// DeviceModelReco.tsx — the device-ranked MODEL recommendation banner
// (WU-models/device, deliverable G-7/8/9: "recommended for your machine: X
// because RAM/VRAM Y"). Surfaces the two local picks the sidecar ranked against
// the probed device — the whisper (ASR) model and the LLM — each with the reason
// that NAMES the device numbers. Pure presentation; the picks come from
// models.runners.
import React from 'react';
import type { ModelReco } from '../lib/rpc';

export interface DeviceModelRecoProps {
  /** The device-ranked whisper (ASR) pick + its "because RAM/VRAM Y" reason. */
  whisper: ModelReco;
  /** The device-ranked LLM pick + its "because RAM/VRAM Y" reason. */
  llm: ModelReco;
}

interface RecoRow {
  key: string;
  kind: string;
  reco: ModelReco;
}

export function DeviceModelReco({ whisper, llm }: DeviceModelRecoProps): React.ReactElement {
  const rows: RecoRow[] = [
    { key: 'whisper', kind: 'Speech (Whisper)', reco: whisper },
    { key: 'llm', kind: 'Language model', reco: llm },
  ];
  return (
    <section
      className="device-reco"
      data-section="device-reco"
      aria-labelledby="device-reco-heading"
    >
      <h3 id="device-reco-heading">Recommended for your machine</h3>
      <ul className="device-reco__list">
        {rows.map((row) => (
          <li key={row.key} className="device-reco__row" data-reco={row.key}>
            <span className="device-reco__kind">{row.kind}</span>
            <span className="device-reco__model" data-field="model">
              {row.reco.label}
            </span>
            <span className="device-reco__reason" data-field="reason">
              {row.reco.reason}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default DeviceModelReco;
