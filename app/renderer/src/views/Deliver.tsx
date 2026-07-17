// Deliver.tsx — the rail "Deliver" destination (v1.5 §4): cross-video / batch
// publish, the OTHER half of the Export/Deliver split.
//
// Naming fix (§4): Phase-5 "Export" finishes ONE video (a guarded commit); this
// rail "Deliver" owns batch / cross-video publish, the platform-preset (aspect)
// matrix, and the pro-editor handoff. It reconciles the old Deliver-cluster tabs
// into ONE named home by COMPOSING the shipped, already-covered panels — BatchQueue
// (batch publish), ExportPresetsPanel (the 9:16 / 4:5 / 1:1 / 16:9 preset matrix),
// and NleExport (EDL / CSV pro handoff) — under the TabBar's role=tablist a11y.
// Finishing Phase-5 links INTO here.

import React, { useState } from 'react';
import { TabBar, tabId, tabPanelId, type TabDef } from '../components/TabBar';
import { BatchQueue } from '../features/BatchQueue';
import { ExportPresetsPanel } from '../features/ExportPresetsPanel';
import { NleExport } from '../features/NleExport';
import type { Video } from '../lib/rpc';
import './deliver.css';

const TABS: TabDef[] = [
  { id: 'batch', label: 'Batch publish' },
  { id: 'presets', label: 'Platform presets' },
  { id: 'handoff', label: 'Pro handoff' },
];

/** The target aspect matrix Deliver publishes across (display only). */
const ASPECTS: readonly { ratio: string; label: string }[] = [
  { ratio: '9:16', label: 'Vertical' },
  { ratio: '4:5', label: 'Feed' },
  { ratio: '1:1', label: 'Square' },
  { ratio: '16:9', label: 'Widescreen' },
];

export interface DeliverProps {
  /** The open video (drives the pro-handoff tab); null when none is open. */
  video: Video | null;
  onBack: () => void;
}

export function Deliver({ video, onBack }: DeliverProps): React.ReactElement {
  const [active, setActive] = useState('batch');

  return (
    <section className="deliver-view" aria-label="Deliver">
      <header className="deliver-view__head">
        <button type="button" className="deliver-view__back" onClick={onBack}>
          ← Library
        </button>
        <h2 className="deliver-view__title">Deliver</h2>
      </header>
      <p className="deliver-view__intro">
        Publish across videos and platforms — batch renders, per-platform presets, and a handoff to
        your pro editor.
      </p>
      <ul className="deliver-view__aspects" aria-label="Target aspect ratios">
        {ASPECTS.map((aspect) => (
          <li key={aspect.ratio} className="deliver-view__aspect">
            <span className="deliver-view__aspect-ratio">{aspect.ratio}</span>
            <span className="deliver-view__aspect-label">{aspect.label}</span>
          </li>
        ))}
      </ul>

      <TabBar tabs={TABS} active={active} onSelect={setActive} />
      <div
        className="deliver-view__panel"
        role="tabpanel"
        id={tabPanelId(active)}
        aria-labelledby={tabId(active)}
      >
        {active === 'batch' ? <BatchQueue /> : null}
        {active === 'presets' ? <ExportPresetsPanel /> : null}
        {active === 'handoff' ? (
          video ? (
            <NleExport videoId={video.id} />
          ) : (
            <p className="deliver-view__empty">
              Open a video from the Library to hand its clips off to Premiere or DaVinci Resolve.
            </p>
          )
        ) : null}
      </div>
    </section>
  );
}

export default Deliver;
