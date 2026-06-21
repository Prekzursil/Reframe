// ModelsSystemPanel.tsx — the "Models & System" graphics-settings-style panel.
//
// Opt-in hardware analysis for the Phase-8 moment-finding pipeline: the user
// runs "Analyze my system", which calls the cheap direct RPCs system.probe +
// system.advisor (+ asr.engines + assets.list for download gating). It then
// renders, in one graphics-settings surface:
//   * a hardware header with VRAM / RAM availability BARS + CPU / GPU chips,
//   * a recommended-preset banner with Apply,
//   * a Tier-0/1/2 selector (radio cards with will-it-run verdicts),
//   * a per-model grid (quality-vs-cost, VRAM, size, license, gated Download),
//   * the advisor notes strip (verbatim manifest alerts),
//   * an ASR + diarize backend selector,
//   * a first-run 3-step onboarding overlay (a clear 101).
//
// Consumes the FROZEN window.api bridge through the typed `client`/`rpc` from
// lib/rpc. All settings flow through settings.get/set — no new store.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import '../features/panels.css';
import './modelsSystem.css';
import {
  client,
  type AdvisorReport,
  type AsrEngine,
  type AssetInfo,
  type CatalogResponse,
  type ComponentStatus,
  type HardwareInfo,
  type Recommendation,
  type RoutingBlock,
  type UsageRow,
} from '../lib/rpc';
import { componentAsset, presetLabel, presetTier } from '../components/advisorMeta';
import { ResourceBar } from '../components/ResourceBar';
import { TierCard } from '../components/TierCard';
import { ModelCard } from '../components/ModelCard';
import { ModelsOnboarding } from '../components/ModelsOnboarding';
import { UsageBars } from '../components/UsageBar';
import { PresetPicker } from '../components/PresetPicker';
import { FirstRunChooser } from '../components/FirstRunChooser';
import { ReadinessRollup } from '../components/ReadinessRollup';
import type { ReadinessAction } from '../lib/rpc';

// --- pure helpers (exported for tests) -------------------------------------

/** Error text from an unknown thrown value (mirrors the sibling panels). */
export function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * The quality fraction (0..1) for a model card's quality mini-bar: which tier
 * the component belongs to, normalized over the max tier. A higher-tier model
 * contributes "more quality". Components not in any tier (speech extras) map to
 * the mid value so the bar is never empty/misleading.
 */
export function qualityFraction(componentName: string, report: AdvisorReport): number {
  const maxTier = report.tiers.reduce((m, t) => Math.max(m, t.tier), 0) || 1;
  const owning = report.tiers.find((t) => t.components.includes(componentName));
  if (!owning) return 0.5;
  return owning.tier / maxTier;
}

/** Map asset name -> AssetInfo for O(1) size/installed lookup. */
export function indexAssets(assets: AssetInfo[]): Record<string, AssetInfo> {
  const out: Record<string, AssetInfo> = {};
  for (const a of assets) out[a.name] = a;
  return out;
}

/** Whether a model card's weights are installed (zero-download floors -> true). */
export function isInstalled(
  component: ComponentStatus,
  byAsset: Record<string, AssetInfo>,
): boolean {
  const asset = componentAsset(component.name);
  if (!asset) return true; // CPU floor — nothing to download.
  return Boolean(byAsset[asset]?.installed);
}

/** The download size MB for a model card (null = zero-download floor / unknown). */
export function sizeForComponent(
  component: ComponentStatus,
  byAsset: Record<string, AssetInfo>,
): number | null {
  const asset = componentAsset(component.name);
  if (!asset) return null;
  const info = byAsset[asset];
  return info && Number.isFinite(info.sizeMB) ? info.sizeMB : null;
}

/**
 * WU-B3 — whether `system.recommend` could not detect the device (G-B1). The
 * sidecar's typed fallback returns an EMPTY `routing.perFunction`, so an empty
 * map is the falsifiable "unavailable" signal the card renders as an announced
 * "could not detect" message (never a blank card).
 */
export function recommendationUnavailable(rec: Recommendation): boolean {
  return Object.keys(rec.routing.perFunction).length === 0;
}

/**
 * WU-B3 — whether the user's CURRENT settings already match the recommendation,
 * so Apply is a no-op. True iff the active preset equals the recommended preset,
 * the recommended ASR engine is already selected (or none is proposed), the
 * recommendation proposes no downloads, AND every per-function route it proposes
 * already matches the current routing. The routing check is load-bearing: the
 * recommender folds detected-local-server deltas (e.g. `select → local-ollama`,
 * the headline "no cloud egress" value) INDEPENDENTLY of the preset, so a
 * preset+ASR match can still hide a pending routing delta — omitting it would
 * declare "already optimal" and make that local-routing recommendation
 * un-appliable from the card. Pure (settings + recommendation in).
 */
export function recommendationAlreadyOptimal(
  rec: Recommendation,
  activePreset: string | undefined,
  asrEngine: string | undefined,
  currentRouting: RoutingBlock | undefined,
): boolean {
  if (rec.preset !== activePreset) return false;
  if (rec.downloads.length > 0) return false;
  const current = currentRouting?.perFunction ?? {};
  for (const [function_, slot] of Object.entries(rec.routing.perFunction)) {
    if (current[function_]?.provider !== slot.provider) return false;
  }
  return rec.asrEngine === null || rec.asrEngine === asrEngine;
}

/**
 * WU-B3 — a short, perceivable outcome summary announced after Apply runs (the
 * polite live region). Pure: derives the human sentence from what was applied so
 * the one-click result is conveyed without re-reading the panel.
 */
export function applyOutcomeText(rec: Recommendation): string {
  const parts = [`preset ${rec.preset}`];
  if (rec.asrEngine) parts.push(`ASR → ${rec.asrEngine}`);
  if (rec.downloads.length > 0) {
    parts.push(`${rec.downloads.length} download${rec.downloads.length === 1 ? '' : 's'} started`);
  }
  return `Applied: ${parts.join(', ')}.`;
}

export interface ModelsSystemPanelProps {
  /** Inject the typed client for tests; defaults to the real lib/rpc client. */
  rpcClient?: typeof client;
  /**
   * WU-PROVIDERS: navigate to the Providers & Keys section. A readiness fix
   * action of kind `openProviders` (add a key) or `setConsent` (grant consent)
   * routes here instead of dead-ending on this panel. Optional: when absent the
   * key/consent actions no-op (the host did not wire navigation).
   */
  onOpenProviders?: () => void;
}

interface SettingsShape {
  phase8Tier?: number;
  asrEngine?: string;
  diarizeBackend?: string;
  commercial?: boolean;
  modelsOnboardingSeen?: boolean;
  activePreset?: string;
  routing?: RoutingBlock;
  firstRunChoiceMade?: boolean;
}

export function ModelsSystemPanel({
  rpcClient,
  onOpenProviders,
}: ModelsSystemPanelProps): React.ReactElement {
  /* v8 ignore next -- the `?? client` default only runs in the real app; every test injects rpcClient. */
  const api = useMemo(() => rpcClient ?? client, [rpcClient]);

  const [hardware, setHardware] = useState<HardwareInfo | null>(null);
  const [report, setReport] = useState<AdvisorReport | null>(null);
  const [assets, setAssets] = useState<AssetInfo[]>([]);
  const [engines, setEngines] = useState<AsrEngine[]>([]);
  const [settings, setSettings] = useState<SettingsShape>({});
  const [analyzed, setAnalyzed] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string>('');
  const [downloading, setDownloading] = useState<string | null>(null);
  const [showTour, setShowTour] = useState<boolean>(false);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [presetBusy, setPresetBusy] = useState<boolean>(false);
  // WU-B3 device-aware recommendation card + one-click Apply.
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [applying, setApplying] = useState<boolean>(false);
  const [applyOutcome, setApplyOutcome] = useState<string>('');

  const byAsset = useMemo(() => indexAssets(assets), [assets]);

  // Load persisted settings up-front (cheap) so the tier/ASR/commercial controls
  // reflect saved choices even before the opt-in analysis runs.
  useEffect(() => {
    let alive = true;
    api.settings
      .get()
      .then((s) => {
        if (alive) setSettings((s ?? {}) as SettingsShape);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [api]);

  // Progressive disclosure: load the CHEAP, probe-INDEPENDENT data up-front so
  // the AI-presets, ASR/diarization, and provider-usage controls work BEFORE the
  // user opts into the (heavier, privacy-sensitive) hardware analysis. None of
  // these reads touches the hardware probe, so the opt-in-probe contract holds.
  // A failed read degrades that one control quietly (never the panel, never the
  // alert region) — the opt-in prompt still renders.
  useEffect(() => {
    let alive = true;
    Promise.all([
      api.providers.catalog().catch(() => null),
      api.asr.engines().catch(() => null),
      api.providers.usage().catch(() => null),
    ])
      .then(([catalogRes, engineRes, usageRes]) => {
        if (alive) {
          if (catalogRes) setCatalog(catalogRes);
          if (engineRes) setEngines(Array.isArray(engineRes.engines) ? engineRes.engines : []);
          if (usageRes) setUsage(Array.isArray(usageRes.usage) ? usageRes.usage : []);
        }
      })
      /* v8 ignore next 2 -- every inner read already .catch()es to null, so the outer Promise.all never rejects; this is a belt-and-braces guard. */
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [api]);

  // Opt-in analysis: probe hardware + advisor + asset/engine state in parallel.
  const analyze = useCallback(async (): Promise<void> => {
    /* v8 ignore next -- re-entrancy guard: the Analyze button is disabled while busy, so this never trips in tests. */
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const commercial = Boolean(settings.commercial);
      const [hw, rep, assetRes, engineRes, usageRes, catalogRes, recRes] = await Promise.all([
        api.system.probe(),
        api.system.advisor({ commercial }),
        api.assets.list(),
        api.asr.engines(),
        api.providers.usage(),
        api.providers.catalog(),
        api.system.recommend({ commercial }),
      ]);
      setHardware(hw ?? null);
      setReport(rep ?? null);
      setAssets(Array.isArray(assetRes?.assets) ? assetRes.assets : []);
      setEngines(Array.isArray(engineRes?.engines) ? engineRes.engines : []);
      setUsage(Array.isArray(usageRes?.usage) ? usageRes.usage : []);
      setCatalog(catalogRes ?? null);
      setRecommendation(recRes?.recommendation ?? null);
      setApplyOutcome('');
      setAnalyzed(true);
      // First-run tour: show once if the user hasn't seen it.
      if (!settings.modelsOnboardingSeen) setShowTour(true);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }, [api, busy, settings.commercial, settings.modelsOnboardingSeen]);

  // Re-probe only the hardware (cheap), e.g. after plugging in a GPU.
  const reprobe = useCallback(async (): Promise<void> => {
    try {
      const hw = await api.system.probe();
      setHardware(hw ?? null);
    } catch (err) {
      setError(errText(err));
    }
  }, [api]);

  // Refresh per-key usage on demand (cached on the sidecar; no poll burst).
  const refreshUsage = useCallback(async (): Promise<void> => {
    try {
      const res = await api.providers.usage();
      setUsage(Array.isArray(res?.usage) ? res.usage : []);
    } catch (err) {
      setError(errText(err));
    }
  }, [api]);

  // Persist a settings patch and reflect it locally (best-effort).
  const patchSettings = useCallback(
    async (patch: SettingsShape): Promise<void> => {
      setSettings((prev) => ({ ...prev, ...patch }));
      try {
        await api.settings.set(patch as Record<string, unknown>);
      } catch (err) {
        setError(errText(err));
      }
    },
    [api],
  );

  const selectTier = useCallback(
    (tier: number) => void patchSettings({ phase8Tier: tier }),
    [patchSettings],
  );

  // WU-presets: apply a smart preset -> server resolves routing.perFunction.
  const applyAiPreset = useCallback(
    async (name: string): Promise<void> => {
      setPresetBusy(true);
      setError('');
      try {
        const res = await api.providers.applyPreset(name);
        setSettings((prev) => ({ ...prev, activePreset: res.activePreset, routing: res.routing }));
      } catch (err) {
        setError(errText(err));
      } finally {
        setPresetBusy(false);
      }
    },
    [api],
  );

  // WU-presets: override one function's routed provider.
  const setFunctionModel = useCallback(
    async (function_: string, provider: string): Promise<void> => {
      setPresetBusy(true);
      setError('');
      try {
        const res = await api.providers.setFunctionModel(function_, provider);
        setSettings((prev) => ({ ...prev, activePreset: res.activePreset, routing: res.routing }));
      } catch (err) {
        setError(errText(err));
      } finally {
        setPresetBusy(false);
      }
    },
    [api],
  );

  // WU-presets P1 #6: the first-run local-vs-cloud choice flips routing + sets
  // firstRunChoiceMade so the chooser never shows again.
  const chooseFirstRun = useCallback(
    async (choice: 'privacy' | 'bestFreeCloud'): Promise<void> => {
      setPresetBusy(true);
      setError('');
      try {
        const res = await api.providers.firstRun(choice);
        setSettings((prev) => ({
          ...prev,
          firstRunChoiceMade: res.firstRunChoiceMade,
          activePreset: res.activePreset ?? prev.activePreset,
          routing: res.routing ?? prev.routing,
        }));
      } catch (err) {
        setError(errText(err));
      } finally {
        setPresetBusy(false);
      }
    },
    [api],
  );

  // WU-B3 one-click Apply: reuses the EXISTING mutation RPCs only (no new
  // mutation path). Order: applyPreset (base routing) -> per-function deltas the
  // recommender folded over the base (detected-local capture) -> persist the ASR
  // engine -> queue the proposed downloads. Announces the outcome politely.
  const applyRecommendation = useCallback(
    async (rec: Recommendation): Promise<void> => {
      setApplying(true);
      setApplyOutcome('');
      setError('');
      try {
        const base = await api.providers.applyPreset(rec.preset);
        let routing = base.routing;
        let activePreset = base.activePreset;
        for (const [function_, slot] of Object.entries(rec.routing.perFunction)) {
          const current = base.routing.perFunction[function_];
          if (current?.provider !== slot.provider) {
            const res = await api.providers.setFunctionModel(function_, slot.provider);
            routing = res.routing;
            activePreset = res.activePreset;
          }
        }
        if (rec.asrEngine) await api.settings.set({ asrEngine: rec.asrEngine });
        if (rec.downloads.length > 0) {
          await api.assets.ensure(rec.downloads.map((d) => d.assetName));
        }
        setSettings((prev) => ({
          ...prev,
          activePreset,
          routing,
          ...(rec.asrEngine ? { asrEngine: rec.asrEngine } : {}),
        }));
        setApplyOutcome(applyOutcomeText(rec));
      } catch (err) {
        setError(errText(err));
      } finally {
        setApplying(false);
      }
    },
    [api],
  );

  const applyPreset = useCallback(() => {
    /* v8 ignore next -- the Apply-preset button only renders inside the `analyzed && report` block, so report is always set here. */
    if (!report) return;
    void patchSettings({ phase8Tier: presetTier(report.recommendedPreset) });
  }, [report, patchSettings]);

  const toggleCommercial = useCallback(() => {
    void patchSettings({ commercial: !settings.commercial });
  }, [patchSettings, settings.commercial]);

  const finishTour = useCallback(() => {
    setShowTour(false);
    void patchSettings({ modelsOnboardingSeen: true });
  }, [patchSettings]);

  // Download a single model (assets.ensure long job) then refresh asset state.
  const download = useCallback(
    async (componentName: string): Promise<void> => {
      const asset = componentAsset(componentName);
      /* v8 ignore next -- defensive guard: floor components (no asset) render an "Installed", disabled button, and the Download button is disabled while downloading, so neither arm trips in tests. */
      if (!asset || downloading) return;
      setDownloading(componentName);
      setError('');
      try {
        await api.assets.ensure([asset]);
        const res = await api.assets.list();
        setAssets(Array.isArray(res?.assets) ? res.assets : []);
        // Re-run the advisor so installed-state flips the verdicts/recommendation.
        const rep = await api.system.advisor({ commercial: Boolean(settings.commercial) });
        setReport(rep ?? null);
      } catch (err) {
        setError(errText(err));
      } finally {
        setDownloading(null);
      }
    },
    [api, downloading, settings.commercial],
  );

  // WU-14 / WU-PROVIDERS: the readiness roll-up surfaces a fix action per
  // not-ready capability.
  //   * `assets.ensure` — install the named weights here, then re-list assets +
  //     re-run the advisor (same effect as a per-model Download).
  //   * `openProviders` (add a key) / `setConsent` (grant consent) — navigate to
  //     the Providers & Keys section via `onOpenProviders` (fixes the previous
  //     early-return dead-end where these actions did nothing).
  const handleReadinessAction = useCallback(
    async (action: ReadinessAction): Promise<void> => {
      if (action.kind === 'openProviders' || action.kind === 'setConsent') {
        onOpenProviders?.();
        return;
      }
      if (!action.assets || action.assets.length === 0) return;
      setError('');
      try {
        await api.assets.ensure(action.assets);
        const res = await api.assets.list();
        setAssets(Array.isArray(res?.assets) ? res.assets : []);
        const rep = await api.system.advisor({ commercial: Boolean(settings.commercial) });
        setReport(rep ?? null);
      } catch (err) {
        setError(errText(err));
      }
    },
    [api, settings.commercial, onOpenProviders],
  );

  const currentTier = settings.phase8Tier ?? 1;
  const recommendedTier = report ? presetTier(report.recommendedPreset) : 0;
  // WU-B3 derived card state (pure helpers; recomputed on settings/rec change).
  const recUnavailable = recommendation ? recommendationUnavailable(recommendation) : false;
  const recOptimal =
    recommendation !== null &&
    !recUnavailable &&
    recommendationAlreadyOptimal(
      recommendation,
      settings.activePreset,
      settings.asrEngine,
      settings.routing,
    );
  const applyDisabled = applying || recOptimal;
  const applyName = recOptimal
    ? 'Your settings already match the recommendation'
    : 'Apply recommended settings';

  return (
    <section className="feature-panel models-system-panel" aria-label="Models and System">
      <h2>Models &amp; System</h2>
      <p className="assets-intro">
        See what your machine can run, pick a quality tier for moment-finding, and download only the
        models you need. Analysis is opt-in and runs locally — nothing is uploaded.
      </p>

      <ReadinessRollup
        rpcClient={api}
        title="What works right now"
        onAction={(action) => void handleReadinessAction(action)}
      />

      <div className="actions">
        <button
          type="button"
          data-action="analyze"
          onClick={() => void analyze()}
          disabled={busy}
          title={busy ? 'Analysis is already running…' : undefined}
        >
          {busy ? 'Analyzing…' : analyzed ? 'Re-analyze' : 'Analyze my system'}
        </button>
        {analyzed && (
          <button
            type="button"
            data-action="tour"
            className="secondary"
            onClick={() => setShowTour(true)}
          >
            Show tour again
          </button>
        )}
        <label className="commercial-toggle" title="Hide models with non-commercial licenses">
          <input
            type="checkbox"
            data-action="commercial"
            checked={Boolean(settings.commercial)}
            onChange={toggleCommercial}
          />
          <span>Commercial use</span>
        </label>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!analyzed && !busy && (
        <div className="empty-state" data-section="prompt">
          <p className="empty-state__title">See what your machine can run</p>
          <p className="empty-state__body">
            Detect your hardware to see per-model and per-tier “will it run” verdicts and a
            recommended setup. The presets, speech engine, and provider-usage controls below already
            work — analysis is opt-in and runs locally.
          </p>
          <button
            type="button"
            className="empty-state__cta"
            data-action="analyze-cta"
            onClick={() => void analyze()}
          >
            Analyze my system
          </button>
        </div>
      )}

      {/* WU-B3: loading live region while system.recommend (inside analyze) runs. */}
      {busy && (
        <p className="status" data-section="recommend-loading" role="status" aria-live="polite">
          Analysing your machine…
        </p>
      )}

      {analyzed && hardware && (
        <div className="hardware-header" data-section="hardware">
          <h3>Your hardware</h3>
          <div className="hardware-header__bars">
            <ResourceBar
              label="VRAM budget"
              used={report?.vramBudgetMb ?? hardware.vramMb}
              total={hardware.vramMb}
              hint="Each heavy model must fit under this on its own."
            />
            <ResourceBar label="System RAM" used={hardware.ramMb} total={hardware.ramMb} />
          </div>
          <div className="hardware-header__chips">
            <span className="hw-chip" data-chip="cpu">
              {hardware.cpuCount ? `${hardware.cpuCount} CPU cores` : 'CPU cores: unknown'}
            </span>
            <span className={`hw-chip${hardware.gpuPresent ? ' is-on' : ''}`} data-chip="gpu">
              {hardware.gpuPresent ? 'GPU detected' : 'No GPU detected'}
            </span>
            <button
              type="button"
              data-action="reprobe"
              className="secondary"
              onClick={() => void reprobe()}
            >
              Re-probe
            </button>
          </div>
        </div>
      )}

      {analyzed && report && (
        <>
          <div
            className="preset-banner"
            data-section="preset"
            data-preset={report.recommendedPreset}
          >
            <div className="preset-banner__text">
              <span className="preset-banner__eyebrow">Recommended for your machine</span>
              <span className="preset-banner__name">{presetLabel(report.recommendedPreset)}</span>
            </div>
            <button type="button" data-action="apply-preset" onClick={applyPreset}>
              Apply preset
            </button>
          </div>

          {/* WU-B3: device-aware recommendation card + one-click Apply. */}
          {recommendation && (
            <section
              className="recommend-card"
              data-section="recommend"
              aria-labelledby="recommend-card-heading"
            >
              <h3 id="recommend-card-heading">Recommended setup for your machine</h3>
              {recUnavailable ? (
                <p
                  className="recommend-card__unavailable"
                  data-section="recommend-unavailable"
                  role="status"
                  aria-live="polite"
                >
                  Could not detect your hardware — pick a preset manually using the controls below.
                </p>
              ) : (
                <>
                  <dl className="recommend-card__plan" data-section="recommend-plan">
                    <div className="recommend-card__row">
                      <dt>Preset</dt>
                      <dd data-field="preset">{presetLabel(recommendation.preset)}</dd>
                    </div>
                    {recommendation.asrEngine && (
                      <div className="recommend-card__row">
                        <dt>Speech engine</dt>
                        <dd data-field="asr">{recommendation.asrEngine}</dd>
                      </div>
                    )}
                    {recommendation.downloads.length > 0 && (
                      <div className="recommend-card__row">
                        <dt>Downloads</dt>
                        <dd data-field="downloads">
                          {recommendation.downloads.map((d) => d.label).join(', ')}
                        </dd>
                      </div>
                    )}
                  </dl>

                  <h4 className="recommend-card__why-heading">Why</h4>
                  <ul className="recommend-card__rationale" data-section="recommend-rationale">
                    {recommendation.rationale.map((line) => (
                      <li key={line} className="recommend-card__rationale-item">
                        {line}
                      </li>
                    ))}
                  </ul>

                  <button
                    type="button"
                    className="recommend-card__apply"
                    data-action="apply-recommendation"
                    aria-label={applyName}
                    // DISABLED clarity: a hover tooltip surfaces the WHY (the same
                    // reason the SR-only aria-label carries) so a sighted user
                    // learns why a greyed Apply is inert.
                    title={applyName}
                    aria-busy={applying}
                    disabled={applyDisabled}
                    onClick={() => void applyRecommendation(recommendation)}
                  >
                    {applying ? 'Applying…' : 'Apply recommended settings'}
                  </button>
                  {recOptimal && (
                    <p className="recommend-card__optimal" data-section="recommend-optimal">
                      Your settings already match the recommendation.
                    </p>
                  )}
                  <p
                    className="recommend-card__outcome"
                    data-section="recommend-outcome"
                    role="status"
                    aria-live="polite"
                  >
                    {applyOutcome}
                  </p>
                </>
              )}
            </section>
          )}

          <h3>Quality tier</h3>
          <div className="tier-grid" data-section="tiers">
            {report.tiers.map((tier) => (
              <TierCard
                key={tier.tier}
                tier={tier}
                selected={currentTier === tier.tier}
                recommended={recommendedTier === tier.tier}
                onSelect={selectTier}
              />
            ))}
          </div>

          <h3>Models</h3>
          <ul className="model-grid" data-section="models">
            {report.components.map((component) => (
              <ModelCard
                key={component.name}
                component={component}
                qualityFraction={qualityFraction(component.name, report)}
                vramBudgetMb={report.vramBudgetMb}
                installed={isInstalled(component, byAsset)}
                sizeMb={sizeForComponent(component, byAsset)}
                downloading={downloading === component.name}
                onDownload={download}
              />
            ))}
          </ul>

          {report.notes.length > 0 && (
            <div className="notes-strip" data-section="notes">
              <h3>Notes</h3>
              <ul className="notes-list">
                {report.notes.map((note) => (
                  <li key={note} className="notes-item">
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {/* Progressive disclosure: these are probe-INDEPENDENT controls (their data
          loads on mount), so they render whether or not the user has opted into
          the hardware analysis — the panel is never a blank "analyze first" wall. */}
      <h3>Speech &amp; diarization</h3>
      <div className="speech-section" data-section="speech">
        <div className="field">
          <label htmlFor="asr-engine">ASR engine</label>
          <select
            id="asr-engine"
            data-action="asr-engine"
            value={settings.asrEngine ?? 'whisper'}
            onChange={(e) => void patchSettings({ asrEngine: e.target.value })}
          >
            {(engines.length > 0 ? engines : [{ id: 'whisper', label: 'Whisper', installed: true }]).map(
              (engine) => (
                <option key={engine.id} value={engine.id}>
                  {engine.label}
                  {engine.installed ? '' : ' (not installed)'}
                </option>
              ),
            )}
          </select>
        </div>
        <div className="field">
          <label htmlFor="diarize-backend">Diarization backend</label>
          <select
            id="diarize-backend"
            data-action="diarize-backend"
            value={settings.diarizeBackend ?? 'speechbrain'}
            onChange={(e) => void patchSettings({ diarizeBackend: e.target.value })}
          >
            <option value="speechbrain">SpeechBrain (token-free, default)</option>
            <option value="pyannote">pyannote 3.1 (needs HF token)</option>
          </select>
          {(settings.diarizeBackend ?? 'speechbrain') === 'pyannote' && (
            <p className="field-hint" data-hint="pyannote">
              pyannote needs an HF token (HF_TOKEN) and both gated repos accepted.
            </p>
          )}
        </div>
      </div>

      <div className="usage-section" data-section="usage">
        <div className="usage-section__head">
          <h3>Provider usage</h3>
          <button
            type="button"
            data-action="refresh-usage"
            className="secondary"
            onClick={() => void refreshUsage()}
          >
            Refresh usage
          </button>
        </div>
        <p className="usage-section__intro">
          Live per-key quota from your loaded providers — request- and token-limited keys are shown
          separately and never combined. Updated from response headers, not a poller.
        </p>
        <UsageBars rows={usage} />
      </div>

      {catalog && (
        <div className="presets-section" data-section="presets-section">
          <PresetPicker
            catalog={catalog}
            routing={settings.routing ?? { perFunction: {} }}
            activePreset={settings.activePreset ?? ''}
            onApplyPreset={(name) => void applyAiPreset(name)}
            onSetFunction={(fn, provider) => void setFunctionModel(fn, provider)}
            busy={presetBusy}
          />
        </div>
      )}

      {!settings.firstRunChoiceMade && (
        <FirstRunChooser onChoose={(choice) => void chooseFirstRun(choice)} busy={presetBusy} />
      )}

      {showTour && <ModelsOnboarding onDone={finishTour} />}
    </section>
  );
}

export default ModelsSystemPanel;
