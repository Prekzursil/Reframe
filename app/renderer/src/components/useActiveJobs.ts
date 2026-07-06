// useActiveJobs.ts — the live at-rest heartbeat behind the header "Jobs" pill.
//
// The JobQueue slide-over (JobQueue.tsx) only polls `job.list` while it is OPEN,
// so the collapsed header needs its own lightweight source of truth to show a
// live count + the "work in motion" pulse. This hook polls `job.list` on a SLOW
// heartbeat (5 s, vs the open panel's 2 s) whenever the preload bridge exists,
// and reports how many jobs are currently ACTIVE (queued or running). It is
// best-effort: a failed read keeps the last known count, and with no bridge it
// stays 0 and makes no RPC calls.
import { useEffect, useState } from 'react';
import { hasApi, rpc, type JobInfo } from '../lib/rpc';

/** Header-pill poll cadence — deliberately slower than the open panel's 2 s. */
export const JOBS_HEARTBEAT_MS = 5000;

/** A job is "active" (work in motion) only while queued or running. */
export function isActiveJob(job: JobInfo): boolean {
  return job.status === 'queued' || job.status === 'running';
}

/** Count the active jobs in a `job.list` payload (missing/omitted -> 0). */
export function activeJobCount(jobs: JobInfo[] | undefined): number {
  return (jobs ?? []).filter(isActiveJob).length;
}

/**
 * Live count of in-flight jobs for the header status pill. Polls `job.list` on a
 * slow heartbeat while the preload bridge is present; returns 0 (and polls
 * nothing) when it is absent. Best-effort — a rejected read leaves the count
 * untouched. Torn down on unmount (interval cleared + a cancelled guard so a
 * late resolve after unmount never sets state).
 */
export function useActiveJobs(heartbeatMs: number = JOBS_HEARTBEAT_MS): number {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (!hasApi()) return undefined;
    let cancelled = false;
    const read = async (): Promise<void> => {
      try {
        const result = await rpc<{ jobs?: JobInfo[] }>('job.list');
        if (!cancelled) setCount(activeJobCount(result?.jobs));
      } catch {
        // Best-effort: keep the last known count on a failed read.
      }
    };
    void read();
    const timer = setInterval(() => void read(), heartbeatMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [heartbeatMs]);
  return count;
}
