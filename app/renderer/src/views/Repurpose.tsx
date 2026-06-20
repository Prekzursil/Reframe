// Repurpose.tsx — the Repurpose view (DESIGN §7): a tabbed surface over the three
// panels. BatchQueue is the DEFAULT landing (the primary folder→shorts flow);
// TemplateEditor and ExportPresetsPanel are the secondary config surfaces. The
// inner tab strip rides `TabBar`'s role=tablist/tab/aria-selected a11y for free.
import React, { useState } from 'react';
import { TabBar, type TabDef } from '../components/TabBar';
import { BatchQueue } from '../features/BatchQueue';
import { TemplateEditor } from '../features/TemplateEditor';
import { ExportPresetsPanel } from '../features/ExportPresetsPanel';

const TABS: TabDef[] = [
  { id: 'queue', label: 'Batch queue' },
  { id: 'templates', label: 'Templates' },
  { id: 'presets', label: 'Export presets' },
];

export interface RepurposeProps {
  /** A deep-link batch id to resume on mount (from the launch toast, §7.2). */
  resumeId?: string;
}

/** The Repurpose view: batch queue (default) + template + preset panels. */
export function Repurpose({ resumeId }: RepurposeProps): React.ReactElement {
  const [active, setActive] = useState('queue');

  return (
    <div className="repurpose" aria-label="Repurpose">
      <TabBar tabs={TABS} active={active} onSelect={setActive} />
      <div className="repurpose__panel">
        {active === 'queue' ? <BatchQueue resumeId={resumeId} /> : null}
        {active === 'templates' ? <TemplateEditor /> : null}
        {active === 'presets' ? <ExportPresetsPanel /> : null}
      </div>
    </div>
  );
}

export default Repurpose;
