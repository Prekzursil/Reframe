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
//
// Q5: the four target ratios used to render as a row of labelled pills directly
// above the tab strip — list items of spans with no handler, no role and no state,
// carrying a comment that called them display-only. In the exact position and visual
// grammar of a target selector, one tab away from the REAL multi-select in
// ExportPresetsPanel, that reads as a chooser that ignores clicks. They are now what
// they always were: information, stated in the intro sentence.

import React, { useState } from 'react';
import { TabBar, tabId, tabPanelId, type TabDef } from '../components/TabBar';
import { BatchQueue } from '../features/BatchQueue';
import { ExportPresetsPanel } from '../features/ExportPresetsPanel';
import { NleExport } from '../features/NleExport';
import { SocialPublishPanel } from '../features/SocialPublishPanel';
import type { Video } from '../lib/rpc';
import './deliver.css';

const TABS: TabDef[] = [
  { id: 'batch', label: 'Batch publish' },
  { id: 'presets', label: 'Platform presets' },
  // C14 direct publish. KEPT beside "Platform presets", and kept even though this
  // build cannot publish, because that is where a user goes looking for it: the
  // presets produce the platform-shaped file, and this tab is the one place that
  // answers what happens next. It now says so instead of offering a control that
  // could never fire (Q4 — see features/SocialPublishPanel.tsx).
  { id: 'publish', label: 'Publish' },
  { id: 'handoff', label: 'Pro handoff' },
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
        Finish a batch of videos in one place — batch renders, per-platform presets for 9:16, 4:5,
        1:1 and 16:9, and a handoff to your pro editor.
      </p>

      <TabBar tabs={TABS} active={active} onSelect={setActive} />
      <div
        className="deliver-view__panel"
        role="tabpanel"
        id={tabPanelId(active)}
        aria-labelledby={tabId(active)}
      >
        {active === 'batch' ? <BatchQueue /> : null}
        {active === 'presets' ? <ExportPresetsPanel /> : null}
        {active === 'publish' ? <SocialPublishPanel /> : null}
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
