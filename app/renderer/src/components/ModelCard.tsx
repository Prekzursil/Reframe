// ModelCard.tsx — one model/component card in the per-model grid. Surfaces the
// quality-vs-cost story: friendly name, what it improves (from the advisor
// reason), VRAM cost, a will-it-run badge, a commercial/local-only license chip,
// a two-bar mini-meter (quality = tier rank, cost = VRAM/budget), and a
// Download/Manage button gated on installed-state + fit. Pure presentational:
// install + asset state are passed in.
import React from 'react';
import type { ComponentStatus } from '../lib/rpc';
import { fillPct, fmtMb, licenseChip, prettyName } from './advisorMeta';
import { VerdictBadge } from './VerdictBadge';

/**
 * The "Installed" check — an inline Lucide-style 24×24 stroke icon (NEVER an
 * emoji glyph, which renders inconsistently and reads as content). Decorative:
 * the button's "Installed" text carries the meaning, so it is aria-hidden.
 */
function CheckIcon(): React.ReactElement {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      aria-hidden="true"
      data-icon="installed"
      className="model-card__check"
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

export interface ModelCardProps {
  component: ComponentStatus;
  /** Quality rank 0..1 (tier-derived) for the quality mini-bar. */
  qualityFraction: number;
  /** The VRAM budget MB the cost mini-bar is relative to (0 -> no GPU). */
  vramBudgetMb: number;
  /** Whether this model's weights are already installed (drives the button). */
  installed: boolean;
  /** On-disk download size in MB (from the asset manifest), or null if unknown. */
  sizeMb: number | null;
  /** True while a download job for this model is in flight. */
  downloading: boolean;
  /** Trigger the download (assets.ensure) — only called when enabled. */
  onDownload: (name: string) => void;
}

export function ModelCard({
  component,
  qualityFraction,
  vramBudgetMb,
  installed,
  sizeMb,
  downloading,
  onDownload,
}: ModelCardProps): React.ReactElement {
  const license = licenseChip(component.licenseCommercialOk);
  const costPct = fillPct(component.vramMb ?? 0, vramBudgetMb);
  const qualityPct = Math.min(100, Math.max(0, Math.round(qualityFraction * 100)));
  // A license-blocked model can never be enabled; a won't-run-for-other-reasons
  // model still offers download (the user may free VRAM / change build later),
  // but we grey it when license is the blocker.
  const licenseBlocked = component.verdict === 'unavailable' && !component.licenseCommercialOk;
  const downloadDisabled = installed || downloading || licenseBlocked;
  const sizeText = fmtMb(sizeMb);
  const downloadTip = licenseBlocked
    ? 'Blocked by a non-commercial license in this build.'
    : installed
      ? 'Already downloaded.'
      : `Downloads ${sizeText} on first use (Tier-1 prompt-to-download). Tier-0 needs zero downloads.`;

  return (
    <li
      className="model-card"
      data-model={component.name}
      data-verdict={component.verdict}
      title={`${prettyName(component.name)} — ${component.reason}`}
    >
      <div className="model-card__head">
        <span className="model-card__name">{prettyName(component.name)}</span>
        <VerdictBadge verdict={component.verdict} reason={component.reason} />
      </div>

      <p className="model-card__improves">{component.reason}</p>

      <div className="model-card__chips">
        <span className="model-card__vram" title="Resident VRAM while this model runs">
          {component.vramMb === null ? 'CPU' : fmtMb(component.vramMb)}
        </span>
        <span className={`license-chip ${license.cls}`} data-license={license.cls}>
          {license.label}
        </span>
        <span className="model-card__size" title="On-disk download size">
          {sizeText}
        </span>
      </div>

      <div className="model-card__meters" aria-hidden="true">
        <div
          className="mini-meter"
          data-kind="quality"
          title={`Quality contribution: ${qualityPct}%`}
        >
          <span className="mini-meter__label">Quality</span>
          <div className="mini-meter__track">
            <div className="mini-meter__fill is-quality" style={{ width: `${qualityPct}%` }} />
          </div>
        </div>
        <div className="mini-meter" data-kind="cost" title={`VRAM cost vs budget: ${costPct}%`}>
          <span className="mini-meter__label">Cost</span>
          <div className="mini-meter__track">
            <div className="mini-meter__fill is-cost" style={{ width: `${costPct}%` }} />
          </div>
        </div>
      </div>

      <div className="model-card__actions">
        <button
          type="button"
          className="model-card__download"
          data-action="download"
          data-model={component.name}
          data-state={installed ? 'installed' : downloading ? 'downloading' : 'download'}
          disabled={downloadDisabled}
          title={downloadTip}
          onClick={() => onDownload(component.name)}
        >
          {installed ? (
            <>
              <CheckIcon />
              Installed
            </>
          ) : downloading ? (
            'Downloading…'
          ) : sizeText === '—' ? (
            'Download'
          ) : (
            `Download (${sizeText})`
          )}
        </button>
      </div>
    </li>
  );
}

export default ModelCard;
