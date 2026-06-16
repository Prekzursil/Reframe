// SystemHealth feature panel (system-advanced group, feature 1 + 2).
//
// The single "is my setup OK?" screen. Calls `system.health` (direct-return)
// and renders ffmpeg/ffprobe presence+version, the offline-mode state (with a
// toggle that persists via `settings.set({offline})`), which optional ML
// backends are installed, the model-cache paths, and the external engine
// availability. Consumes the FROZEN window.api bridge via the shared `./_api`
// helpers, exactly like the sibling panels (Assets / Dub).
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { getApi, type MediaStudioApi } from './_api';

// --- system.health wire shapes (field names FROZEN, identical to Python) ----
export interface HealthTool {
  name: string;
  present: boolean;
  path: string;
  version: string;
  hint: string;
}
export interface HealthBackend {
  label: string;
  module: string;
  installed: boolean;
  version: string;
}
export interface HealthPath {
  label: string;
  path: string;
  exists: boolean;
}
export interface HealthEngine {
  name: string;
  description: string;
  available: boolean;
  path: string;
}
export interface HealthReport {
  ok: boolean;
  offline: boolean;
  platform: string;
  tools: HealthTool[];
  backends: HealthBackend[];
  modelPaths: HealthPath[];
  engines: HealthEngine[];
}

// --- pure helpers (exported for tests) -------------------------------------
/** Count installed/total for a backend list — the section's summary badge. */
export function backendSummary(backends: HealthBackend[]): { installed: number; total: number } {
  return { installed: backends.filter((b) => b.installed).length, total: backends.length };
}

/** A one-line overall verdict from the report. */
export function overallVerdict(report: HealthReport | null): string {
  if (!report) return 'Checking…';
  if (!report.ok) return 'Setup needs attention — ffmpeg or ffprobe is missing';
  return report.offline ? 'Setup OK · Offline mode ON' : 'Setup OK';
}

export interface SystemHealthProps {
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function SystemHealth({ api }: SystemHealthProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [report, setReport] = useState<HealthReport | null>(null);
  const [error, setError] = useState<string>('');
  const [busy, setBusy] = useState<boolean>(false);
  const [offlineBusy, setOfflineBusy] = useState<boolean>(false);

  const refresh = useCallback(async (): Promise<void> => {
    setBusy(true);
    setError('');
    try {
      const res = await bridge.rpc<HealthReport>('system.health');
      setReport(res ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [bridge]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Feature 2: the explicit offline switch. Persists via settings.set, then
  // re-runs the health check so every section reflects the new mode.
  const toggleOffline = useCallback(async (): Promise<void> => {
    // defensive: the toggle button renders only when `report` exists and is
    // `disabled={offlineBusy}`, so this guard is never reached via UI.
    /* v8 ignore next */
    if (!report || offlineBusy) return;
    const next = !report.offline;
    setOfflineBusy(true);
    try {
      await bridge.rpc('settings.set', { offline: next });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOfflineBusy(false);
    }
  }, [bridge, report, offlineBusy, refresh]);

  const summary = useMemo(() => (report ? backendSummary(report.backends) : null), [report]);
  // The "(installed/total)" suffix on the ML-backends heading. The heading only
  // renders inside `report && (...)`, where summary is always non-null, so the
  // empty-string arm is defensive only.
  const backendCountLabel =
    /* v8 ignore next */
    summary ? ` (${summary.installed}/${summary.total})` : '';

  return (
    <section className="feature-panel health-panel" aria-label="System Health">
      <h2>System Health</h2>
      <p className="assets-intro">Is your setup OK? Everything the app needs, in one place.</p>

      <div className="actions">
        <button type="button" data-action="refresh" onClick={() => void refresh()} disabled={busy}>
          {busy ? 'Checking…' : 'Re-check'}
        </button>
        {report && (
          <button
            type="button"
            data-action="toggle-offline"
            className="secondary"
            aria-pressed={report.offline}
            onClick={() => void toggleOffline()}
            disabled={offlineBusy}
          >
            {report.offline ? 'Offline mode: ON' : 'Offline mode: OFF'}
          </button>
        )}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {report && (
        <p className={report.ok ? 'health-verdict ok' : 'health-verdict bad'} data-ok={report.ok}>
          {overallVerdict(report)}
        </p>
      )}

      {report && (
        <>
          <h3>Media tools</h3>
          <ul className="health-list" data-section="tools">
            {report.tools.map((tool) => (
              <li key={tool.name} className="health-row" data-tool={tool.name}>
                <span className="health-name">{tool.name}</span>
                <span
                  className={tool.present ? 'asset-state installed' : 'asset-state missing'}
                  title={tool.present ? tool.path : tool.hint}
                >
                  {tool.present ? `present · ${tool.version || 'unknown version'}` : 'missing'}
                </span>
              </li>
            ))}
          </ul>

          <h3>ML backends{backendCountLabel}</h3>
          <ul className="health-list" data-section="backends">
            {report.backends.map((backend) => (
              <li key={backend.module} className="health-row" data-backend={backend.module}>
                <span className="health-name">{backend.label}</span>
                <span
                  className={backend.installed ? 'asset-state installed' : 'asset-state missing'}
                >
                  {backend.installed ? backend.version || 'installed' : 'not installed'}
                </span>
              </li>
            ))}
          </ul>

          <h3>Engines</h3>
          <ul className="health-list" data-section="engines">
            {report.engines.map((engine) => (
              <li key={engine.name} className="health-row" data-engine={engine.name}>
                <span className="health-name" title={engine.description}>
                  {engine.name}
                </span>
                <span
                  className={engine.available ? 'asset-state installed' : 'asset-state missing'}
                  title={engine.path}
                >
                  {engine.available ? 'available' : 'not found'}
                </span>
              </li>
            ))}
          </ul>

          <h3>Model &amp; cache paths</h3>
          <ul className="health-list" data-section="paths">
            {report.modelPaths.map((entry) => (
              <li key={entry.label} className="health-row" data-path={entry.label}>
                <span className="health-name">{entry.label}</span>
                <code title={entry.path}>{entry.path}</code>
                <span className={entry.exists ? 'asset-state installed' : 'asset-state missing'}>
                  {entry.exists ? 'exists' : 'empty'}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export default SystemHealth;
