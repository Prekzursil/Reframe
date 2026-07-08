// Assets feature panel (PLAN-P2 U4).
//
// Lists the manifest's assets (`assets.list`, CONTRACTS.md A2) with their
// install state, offers per-asset / install-all `assets.ensure` (a long job:
// `{jobId}` + `job.progress` stream + `job.done`), and a cancel button that
// calls `assets.cancel`. Consumes the frozen `window.api` surface via the
// shared local helpers in `./_api` (same pattern as the sibling panels).
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

// --- A3 AssetInfo (field names FROZEN, identical to the Python side) ------
export interface AssetInfo {
  name: string;
  kind: 'model' | 'env' | 'tool';
  sizeMB: number;
  installed: boolean;
  dest: string;
}

// CONTRACT-NOTE: A2 leaves assets.ensure's job.done.result unspecified; the
// sidecar (assets/manager.py) returns {installed:[name], assets:[AssetInfo]}
// so the panel can refresh straight from the done payload.
export interface EnsureDoneResult {
  installed: string[];
  assets: AssetInfo[];
}

// --- pure helpers (exported for tests) ------------------------------------
/** Human size from the A3 `sizeMB` field. */
export function fmtSize(sizeMB: number): string {
  if (!Number.isFinite(sizeMB) || sizeMB <= 0) return '—';
  if (sizeMB >= 1024) return `${(sizeMB / 1024).toFixed(1)} GB`;
  if (sizeMB < 1) return '<1 MB';
  return `${Math.round(sizeMB)} MB`;
}

/** Names of the not-yet-installed assets (the "Install all" payload). */
export function missingNames(assets: AssetInfo[]): string[] {
  return assets.filter((a) => !a.installed).map((a) => a.name);
}

/** Pull the updated asset list out of a job.done result (null when absent). */
export function extractAssets(result: unknown): AssetInfo[] | null {
  const assets = pickField<AssetInfo[]>(result, 'assets');
  return Array.isArray(assets) ? assets : null;
}

export interface AssetsProps {
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function Assets({ api }: AssetsProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  const [assets, setAssets] = useState<AssetInfo[]>([]);
  const [listError, setListError] = useState<string>('');
  const [busy, setBusy] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [ensureError, setEnsureError] = useState<string>('');

  const refresh = useCallback(async (): Promise<void> => {
    setListError('');
    try {
      const res = await bridge.rpc<{ assets: AssetInfo[] }>('assets.list');
      setAssets(Array.isArray(res?.assets) ? res.assets : []);
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    }
  }, [bridge]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Relay job.progress notifications for the active ensure job only.
  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const ensure = useCallback(
    async (names: string[]): Promise<void> => {
      // defensive: the install / install-all buttons are disabled while busy and
      // when there is nothing missing, so this guard is never reached via UI.
      /* v8 ignore next */
      if (names.length === 0 || busy) return;
      setBusy(true);
      setEnsureError('');
      setPct(0);
      setMessage('Starting…');
      try {
        // §2 long job: rpc resolves IMMEDIATELY with {jobId}; the terminal
        // payload arrives via the job.done notification (see _api.ts note).
        const res = await bridge.rpc<{ jobId: string }>('assets.ensure', { names });
        const id = res?.jobId ?? null;
        setJobId(id);
        // F1: waitForJobDone REJECTS on an {error} job.done payload (surfaced by
        // the catch below) — no more silent doneErrorMessage swallow.
        const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
        const updated = extractAssets(result);
        if (updated) {
          setAssets(updated);
        } else {
          await refresh();
        }
        setPct(100);
        setMessage('Done');
      } catch (err) {
        setEnsureError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
        setJobId(null);
      }
    },
    [bridge, busy, refresh],
  );

  const cancel = useCallback(async (): Promise<void> => {
    // defensive: the Cancel button renders only while `busy && jobId`, so cancel
    // is never invoked with a null jobId via UI.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('assets.cancel', { jobId });
    } catch {
      // Best-effort: the job may already have finished.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  const missing = useMemo(() => missingNames(assets), [assets]);

  return (
    <section className="feature-panel assets-panel" aria-label="Assets">
      <h2>Assets</h2>
      <p className="assets-intro">
        Models, runtime environments and tools the app downloads on demand.
      </p>

      <div className="actions">
        <button
          type="button"
          data-action="install-all"
          onClick={() => void ensure(missing)}
          disabled={busy || missing.length === 0}
        >
          {missing.length === 0
            ? 'Everything installed'
            : `Install all missing (${missing.length})`}
        </button>
        <button
          type="button"
          data-action="refresh"
          className="secondary"
          onClick={() => void refresh()}
          disabled={busy}
        >
          Refresh
        </button>
        {busy && jobId && (
          <button
            type="button"
            data-action="cancel"
            className="secondary"
            onClick={() => void cancel()}
          >
            Cancel
          </button>
        )}
      </div>

      {busy && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {listError && (
        <p className="error" role="alert">
          {listError}
        </p>
      )}
      {ensureError && (
        <p className="error" role="alert">
          {ensureError}
        </p>
      )}

      <ul className="asset-list">
        {assets.map((asset) => (
          <li key={asset.name} className="asset-row" data-asset={asset.name}>
            <span className="asset-name">{asset.name}</span>
            <span className={`asset-kind asset-kind--${asset.kind}`}>{asset.kind}</span>
            <span className="asset-size">{fmtSize(asset.sizeMB)}</span>
            <span
              className={asset.installed ? 'asset-state installed' : 'asset-state missing'}
              title={asset.dest}
            >
              {asset.installed ? 'Installed' : 'Not installed'}
            </span>
            {!asset.installed && (
              <button
                type="button"
                data-action="install"
                data-asset={asset.name}
                onClick={() => void ensure([asset.name])}
                disabled={busy}
              >
                Install
              </button>
            )}
          </li>
        ))}
      </ul>
      {assets.length === 0 && !listError && (
        <div className="asset-empty asset-empty--ghost">
          <div className="asset-empty__poster" aria-hidden="true">
            <span className="asset-empty__glyph">◇</span>
          </div>
          <p className="asset-empty__title">No assets registered</p>
          <p className="asset-empty__hint">
            Installed models and resources appear here once you add them.
          </p>
        </div>
      )}
    </section>
  );
}

export default Assets;
