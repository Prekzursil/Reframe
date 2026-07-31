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
  // A non-error explanation for an action the sidecar declined (today: a resume
  // refused because the batch's parent job is still live). Kept separate from
  // `error` so it announces politely (role="status") and never reads as a failure.
  const [notice, setNotice] = useState('');
  // The initial load is indistinguishable from "loaded and empty" without this
  // (docs/design-system.md defines both a skeleton and an empty-state pattern).
  const [loading, setLoading] = useState(true);

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
    } finally {
      // In a `finally` so a FAILED load also stops claiming to be busy.
      setLoading(false);
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
      setNotice('');
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
        setNotice('');
        const out = await client.batch.resume(id);
        const jobId = jobIdOf(out);
        if (jobId === '') {
          // The sidecar declined: this batch's parent job is still live, so it
          // returned the {jobId: null} no-op shape. Do NOT assign the ref — '' makes
          // the onProgress gate (:129) drop every event for the run that IS in
          // flight, freezing the bar and the a11y announcer. Say why instead; a
          // silent no-op click would be a new dead control.
          setNotice('That batch is already running.');
        } else {
          // Track the resumed run's parent jobId so its live progress is honoured
          // by the onProgress gate (batch.resume returns {jobId}).
          parentJobIdRef.current = jobId;
        }
        await refreshBatch(id);
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Resume failed');
      }
    },
    [refreshBatch, reload],
  );

  // Drop an abandoned batch record. NO renderer liveness guard on purpose: the
  // durable aggregate status cannot distinguish live from crashed (and is `queued`
  // for the whole window between resume's on-disk re-enqueue and the pooled
  // worker's first `running` checkpoint), so `BatchService.delete` refuses a live
  // batch server-side and that refusal surfaces here as an error.
  const removeBatch = useCallback(
    async (id: string) => {
      try {
        setError('');
        setNotice('');
        await client.batch.delete(id);
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Delete failed');
      }
    },
    [reload],
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

      {notice !== '' ? (
        <p role="status" className="batch-queue__notice">
          {notice}
        </p>
      ) : null}

      {loading ? (
        // Rendered INLINE, not as an early return: unlike ProvidersKeys this panel
        // can set an error DURING the load (the `resumeId` deep-link resumes
        // concurrently), and an early return would hide that alert and the resume
        // list until the load settled.
        <p className="batch-queue__loading" role="status" aria-busy="true">
          Loading your sources and templates…
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
                <button
                  type="button"
                  aria-label={`Remove ${b.name}`}
                  onClick={() => void removeBatch(b.id)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="batch-queue__setup">
        <fieldset className="batch-queue__sources">
          <legend>Sources</legend>
          {videos.length === 0 ? (
            <p className="batch-queue__empty">Add videos in your Library first.</p>
          ) : (
            videos.map((video) => (
              <label key={video.id} className="batch-queue__source">
                <input
                  type="checkbox"
                  checked={selected.includes(video.id)}
                  onChange={() => toggleVideo(video.id)}
                />
                {video.title}
              </label>
            ))
          )}
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
        {/* Mount-agnostic wording on purpose: the Deliver mount (Deliver.tsx) has
            no Templates tab, so "see the Templates tab" would point at nothing. */}
        {templates.length === 0 ? (
          <p className="batch-queue__template-hint">Save a template first.</p>
        ) : null}

        <button
          type="button"
          className="batch-queue__run"
          disabled={!canRun}
          aria-describedby={canRun ? undefined : 'batch-queue-run-hint'}
          onClick={() => void runBatch()}
        >
          Run batch
        </button>
        {/* The hint text MUST live outside the button (≈15 tests match its exact
            textContent) and stays visible-sibling-first: a native disabled button is
            out of the tab order, so aria-describedby alone would announce nothing. */}
        {canRun ? null : (
          <p id="batch-queue-run-hint" className="batch-queue__run-hint">
            Select at least one source and a template to run a batch.
          </p>
        )}
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
 *
 * Also carries the last-known `pct` forward. `pct` is a LIVE-ONLY overlay —
 * `_merge_live_status` (`batch.py`) adds nothing once the parent job is finished or
 * evicted — so a terminal snapshot arrives with no `pct` and the aggregate bar
 * would fall back to 0% next to its own "done" label. The last OBSERVED pct is
 * carried instead of forcing 100: a cancelled or halted-early batch never reached
 * 100 and claiming it did would be a fresh lie. The carry-forward is scoped to the
 * SAME batch id because `resume` refreshes without resetting `batch`, so an
 * evicted/terminal resume would otherwise leak the previous batch's pct.
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
  const carried = prev !== null && prev.id === next.id ? prev.pct : undefined;
  return { ...next, pct: next.pct ?? carried };
}

export default BatchQueue;
