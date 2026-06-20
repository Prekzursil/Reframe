// JobQueue.tsx — the global job-queue slide-over (T6).
//
// Lists every job the sidecar knows about (`job.list`, the U5 protocol.py
// built-in: bounded 100, newest-first) with feature/label/status/pct. While
// the panel is OPEN it re-polls `job.list` every 2 s and live-updates pct from
// `job.progress` notifications (lib/rpc onProgress); while closed it renders
// nothing and makes no RPC calls. Running/queued entries get a Cancel button
// (`job.cancel`); error entries get a Retry button (`job.retry` — the
// stored-request re-dispatch). No new RPC methods (A2 frozen surface only).
//
// The toggle button lives in App.tsx's header; this file owns the panel.
import React, { useCallback, useEffect, useState } from 'react';
import { onProgress, rpc, type JobInfo } from '../lib/rpc';
import './jobqueue.css';

/** How often the open panel re-polls `job.list`. */
export const JOB_POLL_INTERVAL_MS = 2000;

/** Cancel applies to jobs that are still cancellable (queued/running). */
export function canCancel(job: JobInfo): boolean {
  return job.status === 'queued' || job.status === 'running';
}

/** Retry applies to failed jobs only (job.retry re-runs the stored request). */
export function canRetry(job: JobInfo): boolean {
  return job.status === 'error';
}

/**
 * Resume applies to `interrupted` jobs only (a job left running/queued when the
 * sidecar last shut down — rehydrated as `interrupted`, never auto-restarted).
 * Kept SEPARATE from canRetry so the affordance reads as crash-recovery, not a
 * generic failure-retry, even though both re-dispatch via `job.retry`.
 */
export function canResume(job: JobInfo): boolean {
  return job.status === 'interrupted';
}

/**
 * Resume tooltip/microcopy — makes the full re-dispatch + cloud budget
 * re-prompt visible at the point of action (DESIGN §4.3), so Resume is never a
 * surprise spend: the job restarts at 0% and re-flows through the budget-ack
 * gate before any cloud egress.
 */
export const RESUME_TITLE =
  'Re-runs this interrupted job from the start (it restarts at 0%, not where it ' +
  "stopped). If it uses a cloud provider, you'll be asked to confirm the budget " +
  'again before it runs.';

/** Clamp a pct into 0..100 for rendering (NaN -> 0). */
export function clampPct(pct: number): number {
  if (!Number.isFinite(pct)) return 0;
  return Math.min(100, Math.max(0, pct));
}

/**
 * Merge a live `job.progress` event into the polled list: update the job's
 * pct and promote `queued` -> `running` (a progressing job is running).
 * Returns the SAME array when no entry matched (no useless re-render).
 */
export function applyProgress(jobs: JobInfo[], event: { jobId: string; pct: number }): JobInfo[] {
  let changed = false;
  const next = jobs.map((job) => {
    if (job.jobId !== event.jobId) return job;
    changed = true;
    return {
      ...job,
      pct: event.pct,
      status: job.status === 'queued' ? ('running' as const) : job.status,
    };
  });
  return changed ? next : jobs;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export interface JobQueueProps {
  /** Whether the slide-over is visible (polling only happens while open). */
  open: boolean;
  /** Close-button callback (the App header owns the open state). */
  onClose: () => void;
}

export function JobQueue({ open, onClose }: JobQueueProps): React.ReactElement | null {
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await rpc<{ jobs: JobInfo[] }>('job.list');
      setJobs(result?.jobs ?? []);
      setError(null);
    } catch (err) {
      setError(errText(err));
    }
  }, []);

  // Poll lifecycle: fetch on open, every 2 s while open, live pct via
  // job.progress; everything is torn down on close/unmount.
  useEffect(() => {
    if (!open) return undefined;
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, JOB_POLL_INTERVAL_MS);
    const unsubscribe = onProgress((event) => {
      setJobs((prev) => applyProgress(prev, event));
    });
    return () => {
      clearInterval(timer);
      unsubscribe();
    };
  }, [open, refresh]);

  const handleCancel = useCallback(
    async (jobId: string) => {
      try {
        await rpc<{ ok: boolean }>('job.cancel', { jobId });
      } catch (err) {
        setError(errText(err));
      }
      await refresh();
    },
    [refresh],
  );

  const handleRetry = useCallback(
    async (jobId: string) => {
      try {
        await rpc<{ jobId: string }>('job.retry', { jobId });
      } catch (err) {
        setError(errText(err));
      }
      await refresh();
    },
    [refresh],
  );

  if (!open) return null;

  return (
    <aside className="jobqueue" role="complementary" aria-label="Job queue">
      <header className="jobqueue__header">
        <h2 className="jobqueue__title">Jobs</h2>
        <button
          type="button"
          className="jobqueue__close"
          aria-label="Close job queue"
          onClick={onClose}
        >
          ×
        </button>
      </header>

      {error ? (
        <div className="jobqueue__error" role="alert">
          {error}
        </div>
      ) : null}

      {jobs.length === 0 ? (
        <div className="jobqueue__empty">No jobs yet.</div>
      ) : (
        <ul className="jobqueue__list">
          {jobs.map((job) => (
            <li key={job.jobId} className="jobqueue__item">
              <div className="jobqueue__item-head">
                <span className="jobqueue__feature">{job.feature}</span>
                <span className={`jobqueue__status jobqueue__status--${job.status}`}>
                  {job.status}
                </span>
              </div>
              <div className="jobqueue__label" title={job.label}>
                {job.label}
              </div>
              <div className="jobqueue__progress">
                <div className="jobqueue__bar" aria-hidden="true">
                  <div className="jobqueue__bar-fill" style={{ width: `${clampPct(job.pct)}%` }} />
                </div>
                <span className="jobqueue__pct">{Math.round(clampPct(job.pct))}%</span>
              </div>
              {canCancel(job) || canRetry(job) || canResume(job) ? (
                <div className="jobqueue__actions">
                  {canCancel(job) ? (
                    <button
                      type="button"
                      className="jobqueue__cancel"
                      onClick={() => void handleCancel(job.jobId)}
                    >
                      Cancel
                    </button>
                  ) : null}
                  {canRetry(job) ? (
                    <button
                      type="button"
                      className="jobqueue__retry"
                      aria-label={`Retry ${job.label}`}
                      onClick={() => void handleRetry(job.jobId)}
                    >
                      Retry
                    </button>
                  ) : null}
                  {canResume(job) ? (
                    <button
                      type="button"
                      className="jobqueue__resume"
                      aria-label={`Resume ${job.label}`}
                      title={RESUME_TITLE}
                      onClick={() => void handleRetry(job.jobId)}
                    >
                      Resume
                    </button>
                  ) : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

export default JobQueue;
