// VerdictBadge.tsx — the will-it-run pill (green "Will run" / amber "Tight" /
// red "Won't run") used on every ModelCard and TierCard. Pure presentational:
// it maps a verdict to label + color + an explanatory tooltip (the
// load->infer->unload rule is surfaced so users understand the bars show
// resident VRAM in isolation, one heavy model at a time).
import React from 'react';
import type { AdvisorVerdict } from '../lib/rpc';
import { verdictClass, verdictHint, verdictLabel } from './advisorMeta';

export interface VerdictBadgeProps {
  verdict: AdvisorVerdict;
  /** Extra reason copy appended to the standard verdict hint (optional). */
  reason?: string;
}

const SEQUENTIAL_NOTE =
  'Models load one at a time (load → infer → unload); the VRAM figure is each model resident on its own.';

export function VerdictBadge({ verdict, reason }: VerdictBadgeProps): React.ReactElement {
  const title = [verdictHint(verdict), reason, SEQUENTIAL_NOTE].filter(Boolean).join(' ');
  return (
    <span
      className={`verdict-badge ${verdictClass(verdict)}`}
      data-verdict={verdict}
      role="status"
      title={title}
    >
      {verdictLabel(verdict)}
    </span>
  );
}

export default VerdictBadge;
