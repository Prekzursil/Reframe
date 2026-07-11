// BatchQueue.tsx — the primary "folder → shorts" flow (DESIGN §7 panel 3, the
// default landing). Multi-select library sources, pick a template, review the
// pre-run consent summary (§9.1), create → start, and watch live per-source rows
// driven by `onProgress`/`onJobDone` plus the net-new a11y announcer (§7.1).
// Incomplete batches surface a Resume affordance (§7.2).
//
// Driven entirely through the canonical client (`client.batch.*` /
// `client.templates.list` / `client.library.list`) + the frozen `onProgress` /
// `onJobDone` bridge.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  client,
  onJobDone,
  onProgress,
  type BatchConsent,
  type BatchState,
  type BatchSummary,
  type Template,
  type Video,
} from '../lib/rpc';
import { ProgressBar } from '../components/ProgressBar';
import { BatchConsentCard } from './BatchConsentCard';
import { LiveStatusRegion } from './LiveStatusRegion';
import {
  aggregateUpdate,
  incompleteBatches,
  remainingCount,
  statusToken,
  terminalAnnouncement,
} from './repurposeLogic';
import './panels.css';

/** Pull a {jobId} from any deferred result, or '' when absent. */
function jobIdOf(result: unknown): string {
  if (result && typeof result === 'object' && 'jobId' in result) {
    const id = (result as { jobId?: unknown }).jobId;
    if (typeof id === 'string') return id;
  }
  return '';
}

export interface BatchQueueProps {
  /** A deep-link batch id to resume on mount (from the launch toast, §7.2). */
  resumeId?: string;
}

/** The batch queue: source select → template → consent → run → live rows. */
export function BatchQueue({ resumeId }: BatchQueueProps): React.ReactElement {
  const [videos, setVideos] = useState<Video[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [templateId, setTemplateId] = useState('');
  const [batch, setBatch] = useState<BatchState | null>(null);
  const [incomplete, setIncomplete] = useState<BatchSummary[]>([]);
  const [error, setError] = useState('');

  // §9.1 pre-run cloud-egress consent (DESIGN §9 / §9.1). `consent` holds the
  // pure run/skip surface from `batch.plan`; the card is shown until the user
  // acknowledges egress. `confirmCloudBudget` mirrors the persisted setting
  // (default ON, settings_store.py) and drives whether an ack is required.
  const [consent, setConsent] = useState<BatchConsent | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [confirmCloudBudget, setConfirmCloudBudget] = useState(true);

  // a11y live-status state (§7.1).
  const [aggregate, setAggregate] = useState('');
  const [politeLog, setPoliteLog] = useState<string[]>([]);
  const [assertive, setAssertive] = useState('');

  // The parent batch job id. The app-wide `onProgress` stream carries EVERY
  // job's progress under its own jobId (jobs.py fans out per-job); a batch
  // fans out per-source sub-jobs that each stream their own local 0-100 pct
  // under a DIFFERENT jobId. Without this gate a foreign/sub-job event would
  // clobber the aggregate pct bar and hijack the debounced a11y announcement
  // (§7.1). Mirrors the deliberate jobId filter in components/useJob.ts.
  const parentJobIdRef = useRef('');

  // The created-but-not-yet-started batch, held so the post-acknowledge
  // `confirmRun` can start it without re-creating.
  const pendingBatchRef = useRef<BatchState | null>(null);

  const titleFor = useCallback(
    (videoId: string): string => videos.find((v) => v.id === videoId)?.title ?? videoId,
    [videos],
  );

  const reload = useCallback(async () => {
    try {
      const [{ videos: vids }, { templates: tmpl }, { batches }] = await Promise.all([
        client.library.list(),
        client.templates.list(),
        client.batch.list(),
      ]);
      setVideos(vids);
      setTemplates(tmpl);
      setIncomplete(incompleteBatches(batches));
      if (tmpl.length > 0) setTemplateId((prev) => prev || tmpl[0].id);
      // NOTE: a successful reload does NOT clear `error` — a concurrent action
      // (run/resume/status) may have just set one, and clobbering it would hide
      // a real failure. Load failures set the error below; action flows own their
      // own clear.
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Read the persisted §9.1 budget setting once on mount; a rejection keeps the
  // default-ON gate (fail-safe — never silently egress without acknowledgement).
  useEffect(() => {
    void client.settings
      .get()
      .then((s) => {
        setConfirmCloudBudget(s.confirmCloudBudget !== false);
      })
      .catch(() => {
        // Keep the default-ON gate when the setting can't be read.
      });
  }, []);

  // Subscribe to live progress: announce on source-transition only (debounced).
  // Gate to the parent batch jobId so a concurrent/sub-job's progress can never
  // overwrite the batch pct or trigger a foreign a11y announcement.
  useEffect(() => {
    const off = onProgress((event) => {
      if (parentJobIdRef.current === '' || event.jobId !== parentJobIdRef.current) return;
      setAggregate((prev) => aggregateUpdate(prev, event) ?? prev);
      setBatch((prev) => (prev ? { ...prev, pct: event.pct } : prev));
    });
    return off;
  }, []);

  // When the parent job finishes, refresh the durable batch state once.
  const refreshBatch = useCallback(
    async (id: string) => {
      try {
        const { batch: state } = await client.batch.status(id);
        setBatch((prev) => announceTransitions(prev, state, titleFor, setPoliteLog, setAssertive));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Status failed');
      }
    },
    [titleFor],
  );

  useEffect(() => {
    const off = onJobDone(() => {
      if (batch) void refreshBatch(batch.id);
    });
    return off;
  }, [batch, refreshBatch]);

  const toggleVideo = useCallback((id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]));
  }, []);

  // Fire batch.start, track the parent jobId for the progress gate, flip to
  // 'running', and pull the first authoritative status snapshot. Shared by the
  // gate-OFF direct-run path and the post-acknowledge `confirmRun` path.
  const startBatch = useCallback(
    async (created: BatchState, opts: { confirmCloudBudget: boolean; acknowledged?: boolean }) => {
      const started = await client.batch.start(created.id, opts);
      const jobId = jobIdOf(started);
      // Track this batch's parent jobId for the progress gate (when jobId === ''
      // the ref stays '' and the onProgress guard drops everything, matching the
      // status-refresh skip below).
      parentJobIdRef.current = jobId;
      setBatch({ ...created, status: 'running' });
      if (jobId !== '') {
        // pull the first authoritative status snapshot.
        await refreshBatch(created.id);
      }
    },
    [refreshBatch],
  );

  // Step 1 of the run flow: create the batch, then EITHER preview the §9.1
  // consent split (gate ON — the user must acknowledge cloud egress before any
  // egressing source runs) OR start immediately (gate OFF — informational only).
  const runBatch = useCallback(async () => {
    try {
      // Clear optimistically up front; an internal failure (e.g. refreshBatch)
      // owns its own error and we must NOT clobber it after the await.
      setError('');
      const { batch: created } = await client.batch.create('Batch run', templateId, selected);
      setBatch(created);
      pendingBatchRef.current = created;
      setConsent(null);
      setAcknowledged(false);
      setAggregate('');
      setPoliteLog([]);
      setAssertive('');
      // Drop any prior batch's jobId so its late progress can't apply mid-swap.
      parentJobIdRef.current = '';
      if (confirmCloudBudget) {
        // §9.1 budget gate ON: compute the pure run/skip consent surface WITHOUT
        // starting a job (zero provider calls, plan_consent directly) and render
        // the consent card. batch.start is deferred until the user acknowledges
        // cloud egress (onAcknowledge -> confirmRun), so an un-acknowledged
        // egressing source cleanly SKIPs (SKIP_WOULD_EGRESS, re-runnable) rather
        // than hard-erroring on the sidecar's per-call gate.
        const { consent: c } = await client.batch.plan(created.id, {
          confirmCloudBudget,
          acknowledged: false,
        });
        setConsent(c);
        return;
      }
      // Gate OFF: no acknowledgement needed — start immediately (info-only path).
      await startBatch(created, { confirmCloudBudget });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Run failed');
    }
  }, [templateId, selected, confirmCloudBudget, startBatch]);

  // Step 2 (gate ON): the user acknowledged cloud egress on the consent card —
  // start the created batch, threading BOTH the budget flag and the ack so the
  // sidecar's per-call gate lets the egressing sources run.
  const confirmRun = useCallback(async () => {
    try {
      setError('');
      await startBatch(pendingBatchRef.current!, { confirmCloudBudget, acknowledged: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Run failed');
    }
  }, [confirmCloudBudget, startBatch]);

  const resume = useCallback(
    async (id: string) => {
      try {
        setError('');
        // Track the resumed run's parent jobId so its live progress is honoured
        // by the onProgress gate (batch.resume returns {jobId}).
        const out = await client.batch.resume(id);
        parentJobIdRef.current = jobIdOf(out);
        await refreshBatch(id);
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Resume failed');
      }
    },
    [refreshBatch, reload],
  );

  // Deep-linked resume from the launch toast — fire ONCE per resumeId (guard
  // against the effect re-running when its callback identity changes after load).
  const resumedRef = useRef<string | null>(null);
  useEffect(() => {
    if (resumeId && resumedRef.current !== resumeId) {
      resumedRef.current = resumeId;
      void resume(resumeId);
    }
  }, [resumeId, resume]);

  const canRun = selected.length > 0 && templateId !== '';

  return (
    <section className="batch-queue" aria-label="Batch queue">
      {error !== '' ? (
        <p role="alert" className="batch-queue__error">
          {error}
        </p>
      ) : null}

      {incomplete.length > 0 ? (
        <div className="batch-queue__resume">
          <h4>Incomplete batches</h4>
          <ul>
            {incomplete.map((b) => (
              <li key={b.id} className="batch-queue__resume-row">
                <span>
                  {b.name} — {remainingCount(b.counts)} of {b.counts.total} left
                </span>
                <button type="button" onClick={() => void resume(b.id)}>
                  Resume
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="batch-queue__setup">
        <fieldset className="batch-queue__sources">
          <legend>Sources</legend>
          {videos.map((video) => (
            <label key={video.id} className="batch-queue__source">
              <input
                type="checkbox"
                checked={selected.includes(video.id)}
                onChange={() => toggleVideo(video.id)}
              />
              {video.title}
            </label>
          ))}
        </fieldset>

        <label className="batch-queue__template">
          <span>Template</span>
          <select
            aria-label="Template"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            {templates.map((tmpl) => (
              <option key={tmpl.id} value={tmpl.id}>
                {tmpl.name}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          className="batch-queue__run"
          disabled={!canRun}
          onClick={() => void runBatch()}
        >
          Run batch
        </button>
      </div>

      {consent ? (
        <BatchConsentCard
          consent={consent}
          confirmCloudBudget={confirmCloudBudget}
          acknowledged={acknowledged}
          onAcknowledge={() => {
            setAcknowledged(true);
            void confirmRun();
          }}
          titleFor={titleFor}
        />
      ) : null}

      <LiveStatusRegion aggregate={aggregate} politeLog={politeLog} assertive={assertive} />

      {batch ? (
        <div className="batch-queue__live">
          <ProgressBar pct={batch.pct ?? 0} message={aggregate} />
          <ul className="batch-queue__rows">
            {batch.items.map((item) => (
              <li key={item.videoId} className="batch-queue__row">
                <span className="batch-queue__row-title">{titleFor(item.videoId)}</span>
                <span className="batch-queue__row-status" data-status={item.status}>
                  {statusToken(item.status)}
                </span>
                {item.skipReason !== undefined ? (
                  <span className="batch-queue__row-reason" title={item.skipReason}>
                    {item.skipReason}
                  </span>
                ) : null}
                {item.error !== undefined ? (
                  <span className="batch-queue__row-error" title={item.error}>
                    {item.error}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Compute the new batch state and push per-source TERMINAL announcements for any
 * item that newly reached a terminal state (queued/running flips are silent,
 * §7.1). Exported for unit coverage of the announce-on-terminal contract.
 */
export function announceTransitions(
  prev: BatchState | null,
  next: BatchState,
  titleFor: (id: string) => string,
  pushPolite: (fn: (log: string[]) => string[]) => void,
  setAssertive: (text: string) => void,
): BatchState {
  const before = new Map((prev?.items ?? []).map((i) => [i.videoId, i.status]));
  for (const item of next.items) {
    // Only newly-changed items can announce (a status that was already this value
    // was already spoken). `terminalAnnouncement` itself returns null for any
    // non-terminal status, so it is the sole announce gate — no separate terminal
    // check (which would add an unreachable branch).
    if (before.get(item.videoId) === item.status) continue;
    const ann = terminalAnnouncement(titleFor(item.videoId), item);
    if (ann === null) continue;
    if (ann.assertive) {
      setAssertive(ann.text);
    } else {
      pushPolite((log) => [...log, ann.text]);
    }
  }
  return next;
}

export default BatchQueue;
