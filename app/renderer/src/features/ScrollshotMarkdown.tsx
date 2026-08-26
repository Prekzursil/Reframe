import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './panels.css';
import {
  extractJobId,
  getApi,
  JobAbortedError,
  waitForJobDone,
  type MediaStudioApi,
} from './_api';

export type ScrollshotVerdict =
  | 'FULL_DOCUMENT_COMPLETE'
  | 'RECORDED_SPAN_COMPLETE'
  | 'INCOMPLETE'
  | 'REVIEW_REQUIRED';

export interface ScrollshotExportResult {
  schemaVersion: string;
  runId: string;
  verdict: ScrollshotVerdict;
  markdownPath: string;
  panoramaPaths: string[];
  manifestPath: string;
  reviewRequired: boolean;
  warnings: string[];
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string');
}

function normalizeLegacyVerdict(value: unknown): ScrollshotVerdict | null {
  if (value === 'complete') return 'FULL_DOCUMENT_COMPLETE';
  if (value === 'recorded_span_complete' || value === 'recorded-span-complete') {
    return 'RECORDED_SPAN_COMPLETE';
  }
  if (value === 'review_required' || value === 'review-required') {
    return 'REVIEW_REQUIRED';
  }
  if (value === 'incomplete') return 'INCOMPLETE';
  return null;
}

function normalizeVerdict(value: unknown): ScrollshotVerdict | null {
  if (
    value === 'FULL_DOCUMENT_COMPLETE' ||
    value === 'RECORDED_SPAN_COMPLETE' ||
    value === 'INCOMPLETE' ||
    value === 'REVIEW_REQUIRED'
  ) {
    return value;
  }
  return normalizeLegacyVerdict(value);
}

export function parseScrollshotResult(result: unknown): ScrollshotExportResult | null {
  if (result === null || typeof result !== 'object') return null;
  const value = result as Record<string, unknown>;
  const verdict = normalizeVerdict(value.verdict ?? value.coverageVerdict);
  const markdownPath = typeof value.markdownPath === 'string' ? value.markdownPath : null;
  const manifestPath = typeof value.manifestPath === 'string' ? value.manifestPath : null;
  const runId =
    typeof value.runId === 'string'
      ? value.runId
      : typeof value.bundleId === 'string'
        ? value.bundleId
        : null;
  const schemaVersion =
    typeof value.schemaVersion === 'string'
      ? value.schemaVersion
      : runId !== null
        ? 'legacy'
        : null;
  if ('panoramaPaths' in value && !isStringArray(value.panoramaPaths)) return null;
  if ('warnings' in value && !isStringArray(value.warnings)) return null;
  const panoramaPaths = isStringArray(value.panoramaPaths)
    ? value.panoramaPaths
    : typeof value.imagePath === 'string'
      ? [value.imagePath]
      : [];
  const warnings = isStringArray(value.warnings) ? value.warnings : [];
  if (verdict === null || markdownPath === null || manifestPath === null || runId === null || schemaVersion === null) {
    return null;
  }
  const reviewRequired =
    typeof value.reviewRequired === 'boolean' ? value.reviewRequired : verdict === 'REVIEW_REQUIRED';
  return {
    schemaVersion,
    runId,
    verdict,
    markdownPath,
    panoramaPaths,
    manifestPath,
    reviewRequired,
    warnings,
  };
}

export function describeScrollshotVerdict(
  verdict: ScrollshotVerdict,
): { title: string; detail: string } {
  if (verdict === 'FULL_DOCUMENT_COMPLETE') {
    return {
      title: 'Full document captured',
      detail: 'The recovered markdown covers the full source document span.',
    };
  }
  if (verdict === 'RECORDED_SPAN_COMPLETE') {
    return {
      title: 'Recorded span captured',
      detail: 'The recovered markdown is complete for the span this recording actually covered.',
    };
  }
  if (verdict === 'REVIEW_REQUIRED') {
    return {
      title: 'Review required',
      detail: 'The export completed, but one or more joins still need manual review before you rely on it.',
    };
  }
  return {
    title: 'Incomplete capture',
    detail: 'The recording is missing enough evidence that the markdown needs manual review.',
  };
}

export function resultNeedsReview(result: ScrollshotExportResult): boolean {
  return (
    result.reviewRequired ||
    result.verdict === 'REVIEW_REQUIRED' ||
    result.verdict === 'INCOMPLETE'
  );
}

export interface ScrollshotMarkdownProps {
  videoId: string;
  title?: string;
  api?: MediaStudioApi;
}

export function ScrollshotMarkdown({
  videoId,
  title = '',
  api,
}: ScrollshotMarkdownProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);
  const abortRef = useRef<AbortController | null>(null);
  const cancelRequestedRef = useRef(false);

  const [draftTitle, setDraftTitle] = useState(title);
  const [language, setLanguage] = useState('');
  const [assurance, setAssurance] = useState<'standard' | 'high'>('standard');
  const [running, setRunning] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState(0);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState<ScrollshotExportResult | null>(null);

  useEffect(() => {
    setDraftTitle(title);
    setLanguage('');
    setAssurance('standard');
    setRunning(false);
    setJobId(null);
    setPct(0);
    setMessage('');
    setError('');
    setResult(null);
    cancelRequestedRef.current = false;
    abortRef.current?.abort();
    abortRef.current = null;
  }, [title, videoId]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((event) => {
      if (event.jobId !== jobId) return;
      setPct(event.pct);
      setMessage(event.message);
    });
    return off;
  }, [bridge, jobId]);

  const run = useCallback(async (): Promise<void> => {
    cancelRequestedRef.current = false;
    setRunning(true);
    setJobId(null);
    setPct(0);
    setMessage('Starting…');
    setError('');
    setResult(null);

    const trimmedTitle = draftTitle.trim();
    const trimmedLanguage = language.trim();
    const params: Record<string, unknown> = { videoId, assurance };
    if (trimmedTitle) params.title = trimmedTitle;
    if (trimmedLanguage) params.language = trimmedLanguage;

    let controller: AbortController | null = null;
    try {
      const start = await bridge.rpc<{ jobId?: string }>('scrollshot.exportMarkdown', params);
      const activeJobId = extractJobId(start);
      if (activeJobId === undefined) {
        setError('Scrollshot export did not return a job id.');
        setRunning(false);
        setMessage('');
        return;
      }

      setJobId(activeJobId);
      controller = new AbortController();
      abortRef.current = controller;
      const raw = await waitForJobDone<unknown>(
        bridge,
        activeJobId,
        (payload) => payload ?? null,
        undefined,
        controller.signal,
      );
      if (cancelRequestedRef.current && raw === null) return;

      const parsed = parseScrollshotResult(raw);
      if (parsed === null) {
        setError(
          typeof bridge.onJobDone === 'function'
            ? 'Scrollshot export finished with an unexpected result shape.'
            : 'This app build cannot observe scrollshot completion results yet. Update the desktop bridge and retry.',
        );
        return;
      }

      setResult(parsed);
      setPct(100);
      setMessage(resultNeedsReview(parsed) ? 'Review required' : 'Done');
    } catch (err) {
      if (err instanceof JobAbortedError) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      cancelRequestedRef.current = false;
      if (abortRef.current === controller) abortRef.current = null;
      setRunning(false);
      setJobId(null);
    }
  }, [assurance, bridge, draftTitle, language, videoId]);

  const cancel = useCallback(
    async (activeJobId: string): Promise<void> => {
      cancelRequestedRef.current = true;
      try {
        await bridge.rpc('job.cancel', { jobId: activeJobId });
      } catch {
        // Best-effort cancel — the terminal payload settles the UI.
      }
      setMessage('Cancelling…');
    },
    [bridge],
  );

  const verdictCopy = result ? describeScrollshotVerdict(result.verdict) : null;
  const reviewRequired = result ? resultNeedsReview(result) : false;

  return (
    <section className="feature-panel scrollshot-panel" aria-label="Scrollshot Markdown">
      <h2>Scrollshot to Markdown</h2>
      <p className="assets-intro">
        Recover a long-scroll capture from this video into Markdown. Processing stays fully local,
        remains evidence-preserving, and the original video stays untouched.
      </p>

      <div className="scrollshot-guide" data-section="verdict-guide">
        <p>
          <strong>Full document</strong> means the recovered markdown covers the full source span.
        </p>
        <p>
          <strong>Recorded span</strong> means the markdown is complete for what the recording
          actually captured.
        </p>
        <p>
          <strong>Review required</strong> means the export completed but still needs a human check.
        </p>
        <p>
          <strong>Incomplete</strong> means the recording is missing enough evidence to trust the
          output yet.
        </p>
      </div>

      <div className="field">
        <label htmlFor="scrollshot-title">Document title</label>
        <input
          id="scrollshot-title"
          data-input="title"
          type="text"
          value={draftTitle}
          onChange={(event) => setDraftTitle(event.target.value)}
        />
      </div>

      <div className="scrollshot-fields">
        <div className="field">
          <label htmlFor="scrollshot-language">Language hint</label>
          <input
            id="scrollshot-language"
            data-input="language"
            type="text"
            placeholder="auto"
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="scrollshot-assurance">Assurance</label>
          <select
            id="scrollshot-assurance"
            data-input="assurance"
            value={assurance}
            onChange={(event) => setAssurance(event.target.value as 'standard' | 'high')}
          >
            <option value="standard">standard</option>
            <option value="high">high</option>
          </select>
        </div>
      </div>

      <div className="actions">
        <button
          type="button"
          data-action="export-markdown"
          onClick={() => void run()}
          disabled={running}
        >
          {running ? 'Exporting…' : 'Export markdown'}
        </button>
        {running && jobId ? (
          <button
            type="button"
            data-action="cancel"
            className="secondary"
            onClick={() => void cancel(jobId)}
          >
            Cancel
          </button>
        ) : null}
      </div>

      {running ? (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message ? <span className="progress-message"> · {message}</span> : null}
        </div>
      ) : null}

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {result && verdictCopy ? (
        <div className="scrollshot-result" data-section="result">
          <div
            className={`scrollshot-verdict ${
              reviewRequired ? 'scrollshot-verdict--review' : 'scrollshot-verdict--done'
            }`}
            data-section="verdict"
          >
            <strong>{verdictCopy.title}</strong>
            <p>{verdictCopy.detail}</p>
          </div>

          {reviewRequired ? (
            <p className="scrollshot-review" data-section="review-required">
              Manual review is required before you treat this markdown as final.
            </p>
          ) : null}

          {result.warnings.length > 0 ? (
            <ul className="scrollshot-warnings" data-section="warnings">
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}

          <div className="scrollshot-paths">
            <div className="scrollshot-path" data-field="markdownPath">
              <span>Markdown</span>
              <code>{result.markdownPath}</code>
            </div>
            <div className="scrollshot-path" data-field="manifestPath">
              <span>Manifest</span>
              <code>{result.manifestPath}</code>
            </div>
            <div className="scrollshot-path" data-field="runId">
              <span>Run</span>
              <code>
                {result.runId} · schema {result.schemaVersion}
              </code>
            </div>
          </div>

          {result.panoramaPaths.length > 0 ? (
            <div className="scrollshot-panorama-list" data-section="panoramaPaths">
              <span>Aligned panoramas</span>
              <ul>
                {result.panoramaPaths.map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export default ScrollshotMarkdown;
