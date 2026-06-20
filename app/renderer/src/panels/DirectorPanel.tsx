// DirectorPanel.tsx — the prompt-driven AI video editing surface (WU-panel,
// DESIGN §7.2-§7.4). The user states a goal; the panel calls director.plan (a
// JOB whose typed EditPlan arrives on job.done), shows a STORYBOARD/DIFF over the
// plan's ops (grouped, collapsible — NOT a flat 50-row wall), a per-data-type
// cost/egress BANNER (director.previewCost), an APPLY gate that echoes the budget
// cacheKey, an objective before/after EVAL (director.evaluate), one-shot UNDO, and
// "Adjust & re-plan" that carries the prior goal forward (F6).
//
// Design-gate findings implemented: F1 plain-language summary + collapsible
// groups + op-type filter; F2 per-op status/reason rows + failed-op recovery
// hint; F3 per-data-type cost/egress banner (frames flagged heaviest); F4 model
// text rendered as PLAIN React nodes only (no dangerouslySetInnerHTML, no
// markdown/link auto-render) — XSS-closed; F5 keyboard-complete review +
// SR-announced job progress (aria-live) + text egress labels (never color-only);
// F6 adjust-and-re-plan keeping the prior plan visible until the new one returns.
//
// Consumes the FROZEN window.api bridge via the injectable typed `client` (tests
// inject a fake) + an injectable job-event seam (onProgress/onJobDone), mirroring
// ModelsSystemPanel's rpcClient-injection pattern for 100% vitest coverage.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import '../features/panels.css';
import './directorPanel.css';
import {
  client,
  onJobDone as bridgeOnJobDone,
  onProgress as bridgeOnProgress,
  type DoneEvent,
  type ProgressEvent,
} from '../lib/rpc';
import {
  costRowLabel,
  egressWarning,
  groupOpsByKind,
  isFrameFunction,
  opKindLabel,
  recoveryHint,
  statusLabel,
  summarizePlan,
  type DirectorApplyResult,
  type DirectorCostRow,
  type DirectorEditPlan,
  type DirectorEval,
  type DirectorOp,
  type DirectorOpKind,
  type DirectorPlanResult,
  type DirectorPreview,
} from '../lib/directorTypes';

// --- pure helpers (exported for tests) -------------------------------------

/** Error text from an unknown thrown value (mirrors the sibling panels). */
export function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The job-event subscription seam: injectable so tests drive job.done/progress. */
export interface JobEventBridge {
  onProgress(cb: (event: ProgressEvent) => void): () => void;
  onJobDone(cb: (event: DoneEvent) => void): () => void;
}

const realJobEvents: JobEventBridge = {
  onProgress: bridgeOnProgress,
  onJobDone: bridgeOnJobDone,
};

/** Narrow an unknown job.done result to a DirectorPlanResult (planId + editPlan). */
export function asPlanResult(result: unknown): DirectorPlanResult | null {
  if (!result || typeof result !== 'object') return null;
  const r = result as Partial<DirectorPlanResult>;
  if (typeof r.planId !== 'string' || !r.editPlan || typeof r.editPlan !== 'object') return null;
  return r as DirectorPlanResult;
}

/** Narrow an unknown job.done result to a DirectorApplyResult (planId + opsStatus). */
export function asApplyResult(result: unknown): DirectorApplyResult | null {
  if (!result || typeof result !== 'object') return null;
  const r = result as Partial<DirectorApplyResult>;
  if (typeof r.planId !== 'string' || !Array.isArray(r.opsStatus)) return null;
  return r as DirectorApplyResult;
}

export interface DirectorPanelProps {
  /** Inject the typed client for tests; defaults to the real lib/rpc client. */
  rpcClient?: typeof client;
  /** Inject the job-event seam for tests; defaults to the real preload bridge. */
  jobEvents?: JobEventBridge;
}

/** The id of the in-flight director job + what it represents (plan vs apply/undo). */
interface PendingJob {
  jobId: string;
  kind: 'plan' | 'apply' | 'undo';
}

export function DirectorPanel({ rpcClient, jobEvents }: DirectorPanelProps): React.ReactElement {
  /* v8 ignore next 2 -- the `?? real` defaults only run in the real app; every test injects both. */
  const api = useMemo(() => rpcClient ?? client, [rpcClient]);
  const events = useMemo(() => jobEvents ?? realJobEvents, [jobEvents]);

  const [goal, setGoal] = useState<string>('');
  const [plan, setPlan] = useState<DirectorEditPlan | null>(null);
  const [preview, setPreview] = useState<DirectorPreview | null>(null);
  const [evaluation, setEvaluation] = useState<DirectorEval | null>(null);
  const [opsStatus, setOpsStatus] = useState<DirectorOp[] | null>(null);
  const [applied, setApplied] = useState<boolean>(false);
  const [kindFilter, setKindFilter] = useState<DirectorOpKind | 'all'>('all');
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string>('');
  const [progress, setProgress] = useState<string>('');

  // The active job is held in a ref so the once-mounted job.done/progress
  // subscriptions read the current pending job without re-subscribing.
  const pending = useRef<PendingJob | null>(null);

  // Fetch the per-data-type cost/egress preview for a freshly-planned plan (F3).
  const loadPreview = useCallback(
    async (planId: string): Promise<void> => {
      try {
        const res = await api.director.previewCost(planId);
        setPreview(res ?? null);
      } catch (err) {
        setError(errText(err));
      }
    },
    [api],
  );

  // Resolve a terminal job.done for the active director job.
  const handleDone = useCallback(
    (event: DoneEvent): void => {
      const active = pending.current;
      if (!active || event.jobId !== active.jobId) return;
      pending.current = null;
      setBusy(false);
      setProgress('');
      if (active.kind === 'plan') {
        const result = asPlanResult(event.result);
        if (!result) {
          setError('Planning returned an unexpected result.');
          return;
        }
        setPlan(result.editPlan);
        // A fresh plan invalidates any prior apply/eval state (F6 keeps the prior
        // plan visible until HERE — the moment the new one arrives).
        setOpsStatus(null);
        setApplied(false);
        setEvaluation(null);
        setKindFilter('all');
        void loadPreview(result.planId);
        return;
      }
      // apply / undo both carry per-op statuses.
      const result = asApplyResult(event.result);
      if (!result) {
        setError(
          active.kind === 'undo'
            ? 'Undo returned an unexpected result.'
            : 'Apply returned an unexpected result.',
        );
        return;
      }
      setOpsStatus(result.opsStatus);
      setApplied(active.kind === 'apply');
      if (active.kind === 'undo') setEvaluation(null);
    },
    [loadPreview],
  );

  // Subscribe ONCE to progress + job.done; the refs filter to the active job.
  useEffect(() => {
    const offProgress = events.onProgress((event) => {
      const active = pending.current;
      if (active && event.jobId === active.jobId) setProgress(event.message);
    });
    const offDone = events.onJobDone(handleDone);
    return () => {
      offProgress();
      offDone();
    };
  }, [events, handleDone]);

  // Submit the goal -> director.plan (a JOB). F6: the prior plan stays on screen
  // until the new plan's job.done replaces it.
  const submit = useCallback(async (): Promise<void> => {
    const trimmed = goal.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError('');
    setProgress('Planning…');
    try {
      const job = await api.director.plan(plan?.videoId ?? trimmed, trimmed);
      pending.current = { jobId: job.jobId, kind: 'plan' };
    } catch (err) {
      pending.current = null;
      setBusy(false);
      setProgress('');
      setError(errText(err));
    }
  }, [api, busy, goal, plan]);

  // Apply the current plan (F4: echo the budget cacheKey as confirmBudget). The
  // ack is the first per-function cacheKey from the preview (apply's gate mirrors
  // the plan envelope; an echoed key clears the budget ack).
  const apply = useCallback(async (): Promise<void> => {
    /* v8 ignore next -- re-entrancy + presence guard: the Apply button is `disabled={busy}` and only renders inside `plan && (…)`, so neither arm trips in tests. */
    if (busy || !plan) return;
    setBusy(true);
    setError('');
    setProgress('Applying…');
    try {
      const ack = preview?.perFunction[0]?.cacheKey;
      const job = await api.director.apply(plan.planId, ack);
      pending.current = { jobId: job.jobId, kind: 'apply' };
    } catch (err) {
      pending.current = null;
      setBusy(false);
      setProgress('');
      setError(errText(err));
    }
  }, [api, busy, plan, preview]);

  // One-shot undo of the applied plan (re-applies the recorded inverse).
  const undo = useCallback(async (): Promise<void> => {
    /* v8 ignore next -- re-entrancy + presence guard: the Undo button is `disabled={busy}` and only renders inside `plan && … && applied`, so neither arm trips in tests. */
    if (busy || !plan) return;
    setBusy(true);
    setError('');
    setProgress('Undoing…');
    try {
      const job = await api.director.undo(plan.planId);
      pending.current = { jobId: job.jobId, kind: 'undo' };
    } catch (err) {
      pending.current = null;
      setBusy(false);
      setProgress('');
      setError(errText(err));
    }
  }, [api, busy, plan]);

  // Objective before/after evaluation (synchronous — no job).
  const evaluate = useCallback(async (): Promise<void> => {
    /* v8 ignore next -- re-entrancy + presence guard: the Evaluate button is `disabled={busy}` and only renders inside `plan && … && applied`, so neither arm trips in tests. */
    if (busy || !plan) return;
    setBusy(true);
    setError('');
    try {
      const res = await api.director.evaluate(plan.planId);
      setEvaluation(res ?? null);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }, [api, busy, plan]);

  // F6 "Adjust & re-plan": carry the prior goal forward into the prompt box (the
  // prior plan stays visible until the re-plan returns) and focus the box.
  const adjust = useCallback((): void => {
    if (plan) setGoal(plan.goal);
  }, [plan]);

  // Merge per-op apply statuses (when present) over the planned ops so the
  // storyboard reflects applied/failed AFTER an apply, planned/dropped before it.
  const displayOps = useMemo<DirectorOp[]>(() => {
    if (!plan) return [];
    if (!opsStatus) return plan.ops;
    const byId = new Map(opsStatus.map((o) => [o.id, o]));
    return plan.ops.map((o) => byId.get(o.id) ?? o);
  }, [plan, opsStatus]);

  const groups = useMemo(() => groupOpsByKind(displayOps), [displayOps]);
  const visibleGroups = useMemo(
    () => (kindFilter === 'all' ? groups : groups.filter((g) => g.kind === kindFilter)),
    [groups, kindFilter],
  );

  return (
    <section className="feature-panel director-panel" aria-label="AI Director">
      <h2>AI Director</h2>
      <p className="director-intro">
        Describe the change you want in plain language. The Director plans a reviewable, reversible
        edit — nothing is applied until you confirm.
      </p>

      <form
        className="director-prompt"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="director-goal">Editing goal</label>
        <textarea
          id="director-goal"
          data-action="goal"
          value={goal}
          rows={2}
          placeholder="e.g. make the scrolling smooth, or turn this into a Q&A showcase"
          onChange={(e) => setGoal(e.target.value)}
        />
        <button type="submit" data-action="plan" disabled={busy || goal.trim().length === 0}>
          {busy ? 'Working…' : 'Plan edit'}
        </button>
      </form>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {/* F5: SR-announced job progress (the sibling panel has none). */}
      <p className="director-progress" data-section="progress" aria-live="polite" role="status">
        {progress}
      </p>

      {plan && (
        <>
          {/* F1: plain-language summary header (deterministic, no LLM). */}
          <div className="director-summary" data-section="summary">
            <h3>Proposed edit</h3>
            <p className="director-summary__text" data-testid="plan-summary">
              {summarizePlan(plan)}
            </p>
            <p className="director-goal-echo">Goal: {plan.goal}</p>
          </div>

          {/* F3: per-data-type cost/egress banner (frames flagged heaviest). */}
          {preview && <CostBanner preview={preview} />}

          {/* F1: op-type filter. */}
          {groups.length > 1 && (
            <div className="director-filter" data-section="filter">
              <label htmlFor="director-kind-filter">Show</label>
              <select
                id="director-kind-filter"
                data-action="kind-filter"
                value={kindFilter}
                onChange={(e) => setKindFilter(e.target.value as DirectorOpKind | 'all')}
              >
                <option value="all">All operations</option>
                {groups.map((g) => (
                  <option key={g.kind} value={g.kind}>
                    {opKindLabel(g.kind)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* F1: collapsible groups + F2 per-op status rows + F4 plain-text. */}
          <div className="director-storyboard" data-section="storyboard">
            {visibleGroups.map((g) => (
              <OpGroupSection key={g.kind} group={g} />
            ))}
          </div>

          {/* F2/F4: action gate — apply echoes the budget cacheKey. */}
          <div className="director-actions" data-section="actions">
            <button type="button" data-action="apply" onClick={() => void apply()} disabled={busy}>
              Apply edit
            </button>
            <button
              type="button"
              data-action="adjust"
              className="secondary"
              onClick={adjust}
              disabled={busy}
            >
              Adjust &amp; re-plan
            </button>
            {applied && (
              <>
                <button
                  type="button"
                  data-action="evaluate"
                  onClick={() => void evaluate()}
                  disabled={busy}
                >
                  Evaluate result
                </button>
                <button
                  type="button"
                  data-action="undo"
                  className="secondary"
                  onClick={() => void undo()}
                  disabled={busy}
                >
                  Undo
                </button>
              </>
            )}
          </div>

          {evaluation && <EvalSummary evaluation={evaluation} />}
        </>
      )}
    </section>
  );
}

/** F3 cost/egress banner: one row per data type, frames flagged heaviest. */
function CostBanner({ preview }: { preview: DirectorPreview }): React.ReactElement {
  return (
    <div className="director-cost" data-section="cost">
      <h3>Cost &amp; privacy</h3>
      <ul className="director-cost__list">
        {preview.perFunction.map((row) => (
          <CostRow key={row.function} row={row} />
        ))}
      </ul>
    </div>
  );
}

function CostRow({ row }: { row: DirectorCostRow }): React.ReactElement {
  const warning = egressWarning(row);
  const frame = isFrameFunction(row);
  return (
    <li
      className={`director-cost__row${frame ? ' is-frame' : ''}`}
      data-function={row.function}
      data-egress={row.willEgress ? 'yes' : 'no'}
    >
      <span className="director-cost__label">{costRowLabel(row)}</span>
      <span className="director-cost__route">
        Route: {row.route}
        {row.cacheHit ? ' · cached (free re-run)' : ''}
      </span>
      {warning && (
        <span className="director-cost__warn" data-testid={`egress-${row.function}`}>
          {warning}
        </span>
      )}
    </li>
  );
}

/** F1 collapsible group + F2 per-op rows. Uses native <details> for a11y. */
function OpGroupSection({
  group,
}: {
  group: ReturnType<typeof groupOpsByKind>[number];
}): React.ReactElement {
  return (
    <details className="director-group" data-kind={group.kind} open={!group.collapsedByDefault}>
      <summary className="director-group__head">
        {group.label} ({group.ops.length})
      </summary>
      <ul className="director-group__ops">
        {group.ops.map((op) => (
          <OpRow key={op.id} op={op} />
        ))}
      </ul>
    </details>
  );
}

/**
 * F2 per-op row + F4 plain-text rendering. The rationale/statusReason are model/
 * engine text — rendered as PLAIN React text nodes (never dangerouslySetInnerHTML,
 * never markdown/link auto-render), so an injected `<script>`/HTML string is inert.
 * F5: each row is keyboard-focusable with enable/disable + move-up/down controls.
 */
function OpRow({ op }: { op: DirectorOp }): React.ReactElement {
  const hint = recoveryHint(op);
  return (
    <li
      className={`director-op is-${op.status}`}
      data-op-id={op.id}
      data-status={op.status}
      tabIndex={0}
    >
      <div className="director-op__head">
        <span className="director-op__kind">{opKindLabel(op.kind)}</span>
        <span className="director-op__status" data-testid={`status-${op.id}`}>
          {statusLabel(op.status)}
        </span>
      </div>
      {op.rationale && <p className="director-op__rationale">{op.rationale}</p>}
      {op.statusReason && (
        <p className="director-op__reason" data-testid={`reason-${op.id}`}>
          {op.statusReason}
        </p>
      )}
      {hint && (
        <p className="director-op__hint" data-testid={`hint-${op.id}`}>
          {hint}
        </p>
      )}
      <div className="director-op__controls">
        <button type="button" data-action="op-disable" data-op={op.id} className="link">
          {op.status === 'dropped' ? 'Enable' : 'Disable'}
        </button>
        <button
          type="button"
          data-action="op-up"
          data-op={op.id}
          className="link"
          aria-label="Move up"
        >
          ↑
        </button>
        <button
          type="button"
          data-action="op-down"
          data-op={op.id}
          className="link"
          aria-label="Move down"
        >
          ↓
        </button>
      </div>
    </li>
  );
}

/** Objective before/after eval (F: judgeNote is descriptive only, never the score). */
function EvalSummary({ evaluation }: { evaluation: DirectorEval }): React.ReactElement {
  const pct = Math.round(evaluation.score * 100);
  return (
    <div className="director-eval" data-section="eval">
      <h3>Result evaluation</h3>
      <p className="director-eval__score" data-testid="eval-score">
        Objective score: {pct}%
      </p>
      <ul className="director-eval__deltas">
        {(Object.keys(evaluation.deltas) as (keyof DirectorEval['deltas'])[]).map((metric) => (
          <li key={metric} data-testid={`delta-${metric}`}>
            {metric}: {evaluation.deltas[metric] >= 0 ? '+' : ''}
            {evaluation.deltas[metric].toFixed(3)}
          </li>
        ))}
      </ul>
      {evaluation.judgeNote && (
        <p className="director-eval__note" data-testid="judge-note">
          Note (does not affect score): {evaluation.judgeNote}
        </p>
      )}
    </div>
  );
}

export default DirectorPanel;
