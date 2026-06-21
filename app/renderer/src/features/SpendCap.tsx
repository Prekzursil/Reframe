// SpendCap.tsx — the "Monthly spend cap" control inside Providers & Keys
// (WU-spend-cap). The budget surface for cloud-AI egress: soft + hard dollar
// limits, an enforce-hard toggle, and a clear MONTH-TO-DATE spend readout with a
// progress meter that visibly WARNS near/over the soft cap and shows a BLOCKED
// state at the hard cap.
//
// Wiring: reads `providers.spend` (one read drives BOTH the MTD readout AND the
// input defaults — the RPC returns the configured caps too), writes through
// `settings.set` (top-level shallow merge of monthlySoftLimitCents /
// monthlyHardLimitCents / enforceMonthlyHardLimit) then refetches.
//
// Design (gate-2 invariants, mirrors UsageBar):
//   * the zone (ok / near / blocked) is conveyed by TEXT + ICON, never hue-only;
//   * every control has an explicit <label htmlFor> + aria wiring; the meter is
//     role="meter" with aria-valuetext;
//   * a fully-unconfigured install (both caps 0) shows a helpful zero/empty state
//     ("No spend cap set …"), not a broken bar;
//   * dark-theme tokens only; reduced motion respected (CSS).
//
// Pure money/zone math lives in spendCapLogic.ts (separately unit-tested).
import React, { useCallback, useEffect, useState } from 'react';
import './spendCap.css';
import { client, type SpendInfo } from '../lib/rpc';
import {
  centsToDollars,
  dollarsToCents,
  formatDollars,
  progressCeilingCents,
  progressPercent,
  spendZone,
  zoneGlyph,
  zoneMessage,
} from './spendCapLogic';

/** Error text from an unknown thrown value (mirrors the sibling panels). */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The injectable RPC slice this control needs (defaults to the real client). */
export type SpendCapClient = {
  providers: { spend: () => Promise<SpendInfo> };
  settings: { set: (values: Record<string, unknown>) => Promise<unknown> };
};

export interface SpendCapProps {
  /** Inject the typed client for tests; defaults to the real lib/rpc client. */
  rpcClient?: SpendCapClient;
}

/** The month-to-date readout + progress meter (presentation only). */
function SpendMeter({ info }: { info: SpendInfo }): React.ReactElement {
  const zone = spendZone(info);
  const ceiling = progressCeilingCents(info);
  const pct = progressPercent(info);
  const glyph = zoneGlyph(zone);
  const mtd = formatDollars(info.monthToDateCents);
  const bounded = ceiling > 0;
  const valueText = bounded
    ? `${mtd} of ${formatDollars(ceiling)} this month`
    : `${mtd} this month (no cap)`;

  return (
    <div className="spend-cap__meter" data-zone={zone}>
      <div className="spend-cap__readout">
        <span className="spend-cap__readout-label">Month to date</span>
        <span className="spend-cap__readout-value" data-mtd={info.monthToDateCents}>
          {mtd}
        </span>
        <span className="spend-cap__readout-month">{info.month}</span>
      </div>
      {bounded ? (
        <div
          className="spend-cap__track"
          role="meter"
          aria-label="Month-to-date spend against your cap"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-valuetext={valueText}
          data-zone={zone}
        >
          <div className="spend-cap__fill" data-zone={zone} style={{ width: `${pct}%` }} />
        </div>
      ) : null}
      <p className="spend-cap__status" data-zone={zone} role="status">
        <span className="spend-cap__status-glyph" aria-hidden="true">
          {glyph}
        </span>
        <span className="spend-cap__status-text">{zoneMessage(zone, info.enforceHardLimit)}</span>
      </p>
    </div>
  );
}

/**
 * Monthly spend cap — the full budget control. Loads `providers.spend` once
 * (seeds BOTH the readout and the input defaults), edits soft/hard dollar limits
 * + the enforce toggle locally, and saves through `settings.set`.
 */
export function SpendCap({ rpcClient }: SpendCapProps): React.ReactElement {
  /* v8 ignore next -- the `?? client` default only runs in the real app; every test injects rpcClient. */
  const api = rpcClient ?? client;

  const [info, setInfo] = useState<SpendInfo | null>(null);
  const [soft, setSoft] = useState('0.00');
  const [hard, setHard] = useState('0.00');
  const [enforce, setEnforce] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  // Seed the form + readout from the single spend read.
  const load = useCallback(
    (signal: { alive: boolean }) => {
      setLoading(true);
      setError('');
      Promise.resolve(api.providers.spend())
        .then((s) => {
          if (!signal.alive) return;
          setInfo(s);
          setSoft(centsToDollars(s.softLimitCents));
          setHard(centsToDollars(s.hardLimitCents));
          setEnforce(s.enforceHardLimit);
          setLoading(false);
        })
        .catch((err: unknown) => {
          if (!signal.alive) return;
          setError(errText(err));
          setLoading(false);
        });
    },
    [api],
  );

  useEffect(() => {
    const signal = { alive: true };
    load(signal);
    return () => {
      signal.alive = false;
    };
  }, [load]);

  // Persist the caps, then refetch so the readout reflects the new ceilings.
  const save = useCallback(async (): Promise<void> => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      await api.settings.set({
        monthlySoftLimitCents: dollarsToCents(soft),
        monthlyHardLimitCents: dollarsToCents(hard),
        enforceMonthlyHardLimit: enforce,
      });
      const fresh = await api.providers.spend();
      setInfo(fresh);
      setSoft(centsToDollars(fresh.softLimitCents));
      setHard(centsToDollars(fresh.hardLimitCents));
      setEnforce(fresh.enforceHardLimit);
      setSaved(true);
    } catch (err) {
      setError(errText(err));
    } finally {
      setSaving(false);
    }
  }, [api, soft, hard, enforce]);

  if (loading) {
    return (
      <section className="spend-cap" aria-label="Monthly spend cap">
        <div className="spend-cap__loading" aria-busy="true">
          Loading spend…
        </div>
      </section>
    );
  }

  return (
    <section className="spend-cap" aria-labelledby="spend-cap-title">
      <header className="spend-cap__header">
        <h3 id="spend-cap-title" className="spend-cap__title">
          Monthly spend cap
        </h3>
        <p className="spend-cap__hint">
          Cap how much cloud-AI processing can cost per month. The soft limit warns you as you
          approach it; the hard limit can block new cloud runs once reached.
        </p>
      </header>

      {error ? (
        <p className="spend-cap__error" role="alert">
          {error}
        </p>
      ) : null}

      {/* info is always set once loaded (load sets it before clearing loading). */}
      {info ? <SpendMeter info={info} /> : null}

      <div className="spend-cap__fields">
        <div className="spend-cap__field">
          <label className="spend-cap__label" htmlFor="spend-cap-soft">
            Soft limit (warn)
          </label>
          <div className="spend-cap__money">
            <span className="spend-cap__money-sign" aria-hidden="true">
              $
            </span>
            <input
              id="spend-cap-soft"
              className="spend-cap__input"
              type="number"
              inputMode="decimal"
              min={0}
              step="0.01"
              value={soft}
              disabled={saving}
              aria-describedby="spend-cap-soft-help"
              onChange={(e) => setSoft(e.target.value)}
            />
          </div>
          <p id="spend-cap-soft-help" className="spend-cap__field-help">
            Show a warning once month-to-date spend reaches this amount. Leave 0 for no warning.
          </p>
        </div>

        <div className="spend-cap__field">
          <label className="spend-cap__label" htmlFor="spend-cap-hard">
            Hard limit (block)
          </label>
          <div className="spend-cap__money">
            <span className="spend-cap__money-sign" aria-hidden="true">
              $
            </span>
            <input
              id="spend-cap-hard"
              className="spend-cap__input"
              type="number"
              inputMode="decimal"
              min={0}
              step="0.01"
              value={hard}
              disabled={saving}
              aria-describedby="spend-cap-hard-help"
              onChange={(e) => setHard(e.target.value)}
            />
          </div>
          <p id="spend-cap-hard-help" className="spend-cap__field-help">
            The monthly ceiling enforcement uses. Leave 0 for no ceiling.
          </p>
        </div>
      </div>

      <div className="spend-cap__enforce">
        <input
          id="spend-cap-enforce"
          className="spend-cap__enforce-input"
          type="checkbox"
          checked={enforce}
          disabled={saving}
          onChange={(e) => setEnforce(e.target.checked)}
        />
        <label className="spend-cap__enforce-label" htmlFor="spend-cap-enforce">
          Block new cloud runs at the hard limit
        </label>
        <p className="spend-cap__enforce-help">
          When off, the hard limit is shown for reference but cloud runs still proceed over it.
        </p>
      </div>

      <div className="spend-cap__actions">
        <button
          type="button"
          className="spend-cap__save"
          disabled={saving}
          aria-disabled={saving}
          title={saving ? 'Saving…' : undefined}
          onClick={() => void save()}
        >
          {saving ? 'Saving…' : 'Save spend cap'}
        </button>
        {saved && !saving ? (
          <span className="spend-cap__saved" role="status" data-saved="true">
            <span aria-hidden="true">✓</span> Saved
          </span>
        ) : null}
      </div>
    </section>
  );
}

export default SpendCap;
