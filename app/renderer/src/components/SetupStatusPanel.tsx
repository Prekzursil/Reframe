// SetupStatusPanel.tsx — the first-run self-diagnostic surface (WU-2).
//
// Consumes the cheap direct `system.selfTest` RPC and renders a CLEAR pass/fail
// setup-status panel: an overall banner (ready vs blocked), one row per check
// with its detail + actionable fix hint, and a re-run control. It reports LOUDLY
// — a required dependency that is missing (e.g. OpenCV for reframe) shows the
// problem AND how to fix it, so the user never wanders into a broken render. A
// load failure degrades to a visible alert; it never crashes the host view.
//
// Consumes the FROZEN window.api bridge through the typed `client` from lib/rpc.
import React, { useCallback, useEffect, useState } from 'react';
import { client, type SelfTestReport } from '../lib/rpc';
import './setupStatus.css';

/** Error text from an unknown thrown value (mirrors the sibling panels). */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export interface SetupStatusPanelProps {
  /** Inject the typed client for tests; defaults to the real lib/rpc client. */
  rpcClient?: Pick<typeof client, 'system'>;
  /** Section heading; defaults to a neutral label the host can reuse. */
  title?: string;
}

export function SetupStatusPanel({
  rpcClient,
  title = 'Setup status',
}: SetupStatusPanelProps): React.ReactElement {
  /* v8 ignore next -- the `?? client` default only runs in the real app; every test injects rpcClient. */
  const api = rpcClient ?? client;
  const [report, setReport] = useState<SelfTestReport | null>(null);
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  // Bumping the nonce re-triggers the diagnostic effect (the Re-run control).
  const [nonce, setNonce] = useState<number>(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    setReport(null);
    Promise.resolve(api.system.selfTest())
      .then((res) => {
        if (alive) {
          setReport(res ?? null);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (alive) {
          setError(errText(err));
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [api, nonce]);

  const rerun = useCallback(() => setNonce((n) => n + 1), []);

  return (
    <section className="setup-status" aria-label={title}>
      <div className="setup-status__head">
        <h3 className="setup-status__title">{title}</h3>
        <button
          type="button"
          className="setup-status__rerun"
          data-action="rerun"
          onClick={rerun}
          disabled={loading}
        >
          Re-run check
        </button>
      </div>

      {loading ? (
        <div className="setup-status__loading" aria-busy="true">
          Checking your setup…
        </div>
      ) : error ? (
        <p className="setup-status__error" role="alert">
          Could not run the setup check: {error}
        </p>
      ) : report ? (
        <>
          {report.ok ? (
            <div className="setup-status__summary is-ok" role="status">
              Everything looks good — your install is ready.
            </div>
          ) : (
            <div className="setup-status__summary is-blocked" role="alert">
              Some required components are missing — fix the items below before rendering.
            </div>
          )}

          <ul className="setup-status__checks">
            {report.checks.map((c) => (
              <li
                key={c.id}
                className={`setup-status__check ${c.ok ? 'is-ok' : 'is-failed'}`}
                data-check-id={c.id}
              >
                <div className="setup-status__check-head">
                  <span className="setup-status__check-name">{c.label}</span>
                  <span className="setup-status__check-state" data-state={c.ok ? 'ok' : 'failed'}>
                    {c.ok ? 'Pass' : c.required ? 'Problem' : 'Warning'}
                  </span>
                </div>
                <p className="setup-status__check-detail">{c.detail}</p>
                {c.fixHint && (
                  <p className="setup-status__check-fix" data-role="fix-hint">
                    Fix: {c.fixHint}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="setup-status__empty">No diagnostic result available.</p>
      )}
    </section>
  );
}

export default SetupStatusPanel;
