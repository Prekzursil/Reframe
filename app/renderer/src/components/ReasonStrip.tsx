// ReasonStrip.tsx — the M2 novice "using X because Y" reason strip + device card
// (DESIGN §2.3 step 3 / §2.4). Surfaces, in one glance, what will actually run
// and WHY: the ASR + LLM picks with the LLM's REAL quant + VRAM estimate when a
// detected Ollama runner exposes metadata (else the advisor's verbatim reason),
// plus a device card whose RAM reads "unknown" when the probe found none (F3).
// Pure presentation: the data comes from `models.overview`.
import React from 'react';
import type { ModelsOverview } from '../lib/rpc';
import { chosenLlm, deviceFacts, reasonSummary } from './reasonStripCopy';

export interface ReasonStripProps {
  /** The composed Models & System overview (hardware + plan + eligibility). */
  overview: ModelsOverview;
}

export function ReasonStrip({ overview }: ReasonStripProps): React.ReactElement {
  const summary = reasonSummary(overview);
  const llm = chosenLlm(overview);
  const facts = deviceFacts(overview);
  return (
    <section
      className="reason-strip"
      data-section="reason-strip"
      data-source={llm.fromMetadata ? 'metadata' : 'ladder'}
      aria-label="Why these models"
    >
      <p className="reason-strip__summary" data-field="summary">
        {summary}
      </p>
      <dl className="reason-strip__device" data-section="reason-device">
        {facts.map((fact) => (
          <div key={fact.key} className="reason-strip__fact" data-fact={fact.key}>
            <dt className="reason-strip__label">{fact.label}</dt>
            <dd className="reason-strip__value">{fact.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default ReasonStrip;
