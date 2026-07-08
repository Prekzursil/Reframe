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
import { DirectorOnboarding } from '../components/DirectorOnboarding';
import {
  client,
  onJobDone as bridgeOnJobDone,
  onProgress as bridgeOnProgress,
  type DoneEvent,
  type ProgressEvent,
  type Video,
} from '../lib/rpc';
import {
  canMoveOp,
  costRowLabel,
  egressWarning,
  groupOpsByKind,
  isFrameFunction,
  moveOpWithinKind,
  opKindLabel,
  recoveryHint,
  statusLabel,
  summarizePlan,
  toggleOpStatus,
  type DirectorApplyResult,
  type DirectorCostRow,
  type DirectorEditPlan,
  type DirectorEval,
  type DirectorOp,
  type DirectorOpKind,
  type OpMoveDirection,
  type DirectorPlanResult,
  type DirectorPreview,
} from '../lib/directorTypes';

// Lucide-style 24x24 line icons (stroke-based, currentColor) for the per-op
// reorder controls — inline SVG, NEVER emoji-as-icon (DESIGN: pro-UI rails).
const ICON_PATHS: Record<OpMoveDirection, string> = {
  up: 'M12 19V5 M5 12l7-7 7 7',
  down: 'M12 5v14 M19 12l-7 7-7-7',
};

function MoveIcon({ dir }: { dir: OpMoveDirection }): React.ReactElement {
  return (
    <svg
      className="director-op__icon"
      width={16}
      height={16}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICON_PATHS[dir].split(' M').map((seg, i) => (
        // eslint-disable-next-line react/no-array-index-key -- static two-segment icon path
        <path key={i} d={i === 0 ? seg : `M${seg}`} />
      ))}
    </svg>
  );
}

// WU-E2: clickable example goals that prefill the prompt so a first-time user
// has a working starting point (plain-language, matched to real op kinds). Kept
// here (exported) so the copy is single-sourced with any test that asserts it.
export const DIRECTOR_EXAMPLES: readonly string[] = [
  'Make the scrolling smooth and steady',
  'Turn this into a punchy Q&A showcase',
  'Trim the dead air and tighten the pacing',
  'Add captions over the key moments',
];

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
  /**
   * The app-selected video this panel edits (App's `editVideo`, set by
   * `openVideo`), or null when none is open. Its `id` is the plan target — WU-E1:
   * the goal string is NEVER used as the videoId. When null (and no prior plan is
   * on screen) the panel shows a "Choose a video" empty state instead of the
   * prompt form, so a first run can never mis-fire the goal as the videoId.
   */
  video?: Video | null;
  /** Route to the real video selection (the Library) from the empty-state CTA. */
  onChooseVideo?: () => void;
}

/** The id of the in-flight director job + what it represents (plan vs apply/undo). */
interface PendingJob {
  jobId: string;
  kind: 'plan' | 'apply' | 'undo';
}

export function DirectorPanel({
  rpcClient,
  jobEvents,
  video,
  onChooseVideo,
}: DirectorPanelProps): React.ReactElement {
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
  // WU-E2: the first-run guided tour (focus-trapped DirectorOnboarding). Gated on
  // settings.directorOnboardingSeen, and re-openable from the header at any time.
  const [showTour, setShowTour] = useState<boolean>(false);

  // The active job is held in a ref so the once-mounted job.done/progress
  // subscriptions read the current pending job without re-subscribing.
  const pending = useRef<PendingJob | null>(null);

  // WU-E1: the video this panel plans against — the app-selected `video.id`, or
  // (if that video was closed while a prior plan is still on screen) the plan's
  // own `videoId`. NEVER the goal text. `null` == no video and no plan → the
  // panel renders the "Choose a video" empty state instead of the prompt form.
  const activeVideoId: string | null = video?.id ?? plan?.videoId ?? null;

  // WU-E2 + WU-D6a: read settings and open the first-run tour when the user has
  // not seen it — but ONLY once a video is actually open. Best-effort: a failed
  // read simply leaves the tour closed (we never nag on an unreadable settings
  // store). Re-runs when the active video changes, so the tour fires the first
  // time the user has something to edit, until the "seen" flag is persisted.
  useEffect(() => {
    // WU-D6a: never auto-open the focus-trapped tour over the "No video open"
    // empty state. With nothing to edit, its copy ("it reads the video you have
    // open", "press Plan edit") is wrong and the trap would sit OVER the only
    // actionable control ("Choose a video"). Gate on a video being open; the tour
    // then fires the moment the user actually has something to edit. The header
    // "What is Director?" affordance still re-opens it on demand in either state.
    if (activeVideoId === null) return;
    void api.settings
      .get()
      .then((s) => {
        if (!s.directorOnboardingSeen) setShowTour(true);
      })
      .catch(() => {
        // Best-effort: keep the tour closed if settings can't be read.
      });
  }, [api, activeVideoId]);

  // Dismiss the tour (Skip / Got it / Escape all route here) and persist the
  // "seen" flag so it never re-opens on its own. Best-effort persistence — the
  // tour is already closed in-memory regardless of the write's outcome.
  const finishTour = useCallback((): void => {
    setShowTour(false);
    void api.settings.set({ directorOnboardingSeen: true }).catch(() => {
      // Best-effort: the tour is closed locally even if the write fails.
    });
  }, [api]);

  // Re-open the tour on demand (the header "What is Director?" affordance).
  const reopenTour = useCallback((): void => setShowTour(true), []);

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
    /* v8 ignore next -- presence guard: the prompt form (hence submit) only renders when activeVideoId is non-null, so this never fires in practice. */
    if (activeVideoId === null) return;
    setBusy(true);
    setError('');
    setProgress('Planning…');
    try {
      // WU-E1: plan against the resolved video id — NEVER the goal string.
      const job = await api.director.plan(activeVideoId, trimmed);
      pending.current = { jobId: job.jobId, kind: 'plan' };
    } catch (err) {
      pending.current = null;
      setBusy(false);
      setProgress('');
      setError(errText(err));
    }
  }, [api, busy, goal, activeVideoId]);

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

  // WU-director-controls: enable/disable one op (toggle planned<->dropped) in the
  // REVIEWABLE plan. The edit lands in `plan.ops` (the same state apply reads via
  // planId), immutably, so the storyboard + the plain-language summary update and
  // the change rides the next director.apply. A no-op while busy or post-apply.
  const toggleOp = useCallback((opId: string): void => {
    setPlan((prev) =>
      /* v8 ignore next -- presence guard: the controls only render inside `plan && …`, so `prev` is non-null whenever this fires. */
      prev ? { ...prev, ops: toggleOpStatus(prev.ops, opId) } : prev,
    );
  }, []);

  // WU-director-controls: reorder one op up/down past its nearest same-kind
  // neighbour (within-group, so the move is visible) in the reviewable plan.
  const moveOp = useCallback((opId: string, dir: OpMoveDirection): void => {
    setPlan((prev) =>
      /* v8 ignore next -- presence guard: the controls only render inside `plan && …`, so `prev` is non-null whenever this fires. */
      prev ? { ...prev, ops: moveOpWithinKind(prev.ops, opId, dir) } : prev,
    );
  }, []);

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

  // The per-op controls edit the REVIEWABLE plan, so they are interactive only
  // BEFORE an apply (once applied, the op statuses are server truth — the user
  // undoes, not edits) and never mid-job. Disabled controls keep their reason.
  const controlsEnabled = !applied && opsStatus === null && !busy;

  // WU-E2: one reusable header (title + a persistent "What is Director?" entry
  // point to the tour) and the first-run overlay, shared by BOTH return branches
  // so the explainer is reachable whether or not a video is open.
  const header = (
    <div className="director-head">
      <h2>AI Director</h2>
      <button
        type="button"
        className="secondary director-head__tour"
        data-action="director-tour"
        onClick={reopenTour}
      >
        What is Director?
      </button>
    </div>
  );
  const onboarding = showTour ? <DirectorOnboarding onDone={finishTour} /> : null;

  // WU-E1: with no video open AND no plan on screen, there is nothing to edit —
  // show a "Choose a video" empty state (wired to the real selection) instead of
  // a prompt box that would otherwise mis-fire the goal as the videoId.
  if (activeVideoId === null) {
    return (
      <section
        className="feature-panel director-panel director-panel--empty"
        aria-label="AI Director"
      >
        {header}
        <div className="director-empty" data-section="empty">
          <div className="director-empty__poster" aria-hidden="true">
            <span className="director-empty__glyph">▶</span>
            <span className="director-empty__timecode">--:--</span>
          </div>
          <p className="director-empty__title">No video open</p>
          <p className="director-empty__hint">
            Open a video from your Library to plan a reviewable, reversible AI edit for it — the
            Director always edits the video you have selected.
          </p>
          <button
            type="button"
            data-action="choose-video"
            className="director-empty__cta"
            onClick={onChooseVideo}
          >
            Choose a video
          </button>
        </div>
        {onboarding}
      </section>
    );
  }

  return (
    <section className="feature-panel director-panel" aria-label="AI Director">
      {header}
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

      {/* WU-E2: clickable example goals prefill the prompt for a first-time user. */}
      <div className="director-examples" data-section="examples">
        <span className="director-examples__label">Try an example:</span>
        <ul className="director-examples__chips">
          {DIRECTOR_EXAMPLES.map((example) => (
            <li key={example}>
              <button
                type="button"
                className="director-chip"
                data-action="example-chip"
                data-example={example}
                disabled={busy}
                onClick={() => setGoal(example)}
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>

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
              <OpGroupSection
                key={g.kind}
                group={g}
                allOps={displayOps}
                controlsEnabled={controlsEnabled}
                onToggle={toggleOp}
                onMove={moveOp}
              />
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
      {onboarding}
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

/** Per-op control wiring threaded down to each {@link OpRow}. */
interface OpControlProps {
  /** The full ordered op list (for same-kind boundary detection). */
  allOps: DirectorOp[];
  /** Controls are interactive only on the REVIEWABLE plan (pre-apply, not busy). */
  controlsEnabled: boolean;
  /** Toggle one op enabled<->disabled in the edit plan. */
  onToggle: (opId: string) => void;
  /** Reorder one op up/down within its kind in the edit plan. */
  onMove: (opId: string, dir: OpMoveDirection) => void;
}

/** F1 collapsible group + F2 per-op rows. Uses native <details> for a11y. */
function OpGroupSection({
  group,
  allOps,
  controlsEnabled,
  onToggle,
  onMove,
}: { group: ReturnType<typeof groupOpsByKind>[number] } & OpControlProps): React.ReactElement {
  return (
    <details className="director-group" data-kind={group.kind} open={!group.collapsedByDefault}>
      <summary className="director-group__head">
        {group.label} ({group.ops.length})
      </summary>
      <ul className="director-group__ops">
        {group.ops.map((op) => (
          <OpRow
            key={op.id}
            op={op}
            allOps={allOps}
            controlsEnabled={controlsEnabled}
            onToggle={onToggle}
            onMove={onMove}
          />
        ))}
      </ul>
    </details>
  );
}

/**
 * F2 per-op row + F4 plain-text rendering. The rationale/statusReason are model/
 * engine text — rendered as PLAIN React text nodes (never dangerouslySetInnerHTML,
 * never markdown/link auto-render), so an injected `<script>`/HTML string is inert.
 * F5 + WU-director-controls: the row is keyboard-focusable AND its enable/disable
 * + move-up/down controls are WIRED — click via each button's onClick, and the
 * focusable row's onKeyDown activates them (Enter/Space toggle; ArrowUp/ArrowDown
 * move within kind). jsdom does NOT fire a native <button> onClick on keydown, so
 * keyboard support lives on the row, exactly where the focus is. Move buttons at a
 * same-kind boundary are disabled (opacity + not-allowed + an explanatory title).
 */
function OpRow({
  op,
  allOps,
  controlsEnabled,
  onToggle,
  onMove,
}: { op: DirectorOp } & OpControlProps): React.ReactElement {
  const hint = recoveryHint(op);
  const dropped = op.status === 'dropped';
  const canUp = controlsEnabled && canMoveOp(allOps, op.id, 'up');
  const canDown = controlsEnabled && canMoveOp(allOps, op.id, 'down');

  // The row's keyboard seam (a custom control, so it owns its key handling). It
  // only acts on keys it handles AND only when controls are live; everything else
  // bubbles (so Tab/Shift+Tab still move focus naturally).
  const onKeyDown = (e: React.KeyboardEvent<HTMLLIElement>): void => {
    // Only act when the ROW itself is focused. A keydown bubbling up from a child
    // button (Tab to "Move up", press Enter) must keep its OWN native activation
    // (button onClick) — without this guard the row would hijack it and toggle.
    if (e.target !== e.currentTarget) return;
    if (!controlsEnabled) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onToggle(op.id);
    } else if (e.key === 'ArrowUp') {
      if (!canUp) return;
      e.preventDefault();
      onMove(op.id, 'up');
    } else if (e.key === 'ArrowDown') {
      if (!canDown) return;
      e.preventDefault();
      onMove(op.id, 'down');
    }
  };

  return (
    <li
      className={`director-op is-${op.status}`}
      data-op-id={op.id}
      data-status={op.status}
      tabIndex={0}
      aria-label={`${opKindLabel(op.kind)} — ${statusLabel(op.status)}`}
      onKeyDown={onKeyDown}
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
        <button
          type="button"
          data-action="op-disable"
          data-op={op.id}
          className="link"
          aria-pressed={dropped}
          disabled={!controlsEnabled}
          title={
            controlsEnabled
              ? dropped
                ? 'Re-enable this step in the plan'
                : 'Disable this step (kept in the plan but skipped)'
              : 'Editing is available before you apply the plan'
          }
          onClick={() => onToggle(op.id)}
        >
          {dropped ? 'Enable' : 'Disable'}
        </button>
        <button
          type="button"
          data-action="op-up"
          data-op={op.id}
          className="link"
          aria-label="Move up"
          disabled={!canUp}
          title={canUp ? 'Move up' : 'Already first of its kind'}
          onClick={() => onMove(op.id, 'up')}
        >
          <MoveIcon dir="up" />
        </button>
        <button
          type="button"
          data-action="op-down"
          data-op={op.id}
          className="link"
          aria-label="Move down"
          disabled={!canDown}
          title={canDown ? 'Move down' : 'Already last of its kind'}
          onClick={() => onMove(op.id, 'down')}
        >
          <MoveIcon dir="down" />
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
