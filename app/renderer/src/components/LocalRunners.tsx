// LocalRunners.tsx — Ollama / LM Studio detect + recommend + install advice
// (WU-models/device, deliverable G-1: detect local runners; if present list the
// recommended whisper+LLM to PULL with a copy-able hint; if absent advise install
// with the official link — NEVER an auto-install). Pure presentation: the advice
// rows come from models.runners; copying a pull hint is the only interaction.
import React, { useCallback, useState } from 'react';
import type { RunnerAdvice } from '../lib/rpc';

export interface LocalRunnersProps {
  /** Per-runner detect + recommend + install advice (from models.runners). */
  runners: RunnerAdvice[];
  /**
   * Optional clipboard writer (injected for tests; defaults to the browser
   * clipboard). Returns a promise; a rejection is swallowed (copy is best-effort).
   */
  writeClipboard?: (text: string) => Promise<void>;
}

/* v8 ignore start -- the real navigator.clipboard default only runs in the app; every test injects writeClipboard. */
function defaultClipboard(text: string): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return Promise.resolve();
}
/* v8 ignore stop */

export function LocalRunners({ runners, writeClipboard }: LocalRunnersProps): React.ReactElement {
  const [copied, setCopied] = useState<string>('');
  const write = writeClipboard ?? defaultClipboard;

  const copyPull = useCallback(
    (kind: string, pull: string): void => {
      write(pull)
        .then(() => setCopied(kind))
        .catch(() => setCopied(''));
    },
    [write],
  );

  return (
    <section
      className="local-runners"
      data-section="local-runners"
      aria-labelledby="local-runners-heading"
    >
      <h3 id="local-runners-heading">Local model runners</h3>
      <p className="local-runners__intro">
        Run models on your own machine with Ollama or LM Studio. We detect them and recommend the
        best model for your hardware — we never auto-install or pull anything.
      </p>
      <ul className="local-runners__list">
        {runners.map((runner) => (
          <li
            key={runner.kind}
            className={`local-runner${runner.present ? ' is-present' : ''}`}
            data-runner={runner.kind}
            data-present={runner.present ? 'true' : 'false'}
          >
            <div className="local-runner__head">
              <span className="local-runner__name">{runner.label}</span>
              <span className="local-runner__status" data-field="status">
                {runner.present ? 'Running' : 'Not detected'}
              </span>
            </div>

            {runner.present ? (
              <div className="local-runner__present" data-field="present-detail">
                {runner.installedModels.length > 0 && (
                  <p className="local-runner__installed" data-field="installed">
                    Installed: {runner.installedModels.join(', ')}
                  </p>
                )}
                <p className="local-runner__reco" data-field="reco">
                  Recommended: {runner.recommendedModel.label} — {runner.recommendedModel.reason}
                </p>
                <div className="local-runner__pull">
                  <code className="local-runner__pull-cmd" data-field="pull">
                    {runner.recommendedModel.pull}
                  </code>
                  <button
                    type="button"
                    className="local-runner__copy"
                    data-action="copy-pull"
                    data-runner={runner.kind}
                    onClick={() => copyPull(runner.kind, runner.recommendedModel.pull)}
                  >
                    {copied === runner.kind ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="local-runner__absent" data-field="absent-detail">
                <p className="local-runner__hint" data-field="install-hint">
                  {runner.installHint}
                </p>
                <a
                  className="local-runner__install"
                  data-action="install-link"
                  data-runner={runner.kind}
                  href={runner.installUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Get {runner.label}
                </a>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default LocalRunners;
