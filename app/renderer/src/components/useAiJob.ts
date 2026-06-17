import { useCallback, useState } from 'react';
import { rpc } from './api';
import { type JobError, type UseJobOptions, useJob } from './useJob';

// ---- AI-Job envelope wire shapes (WU-envelope) -------------------------------
// These mirror the sidecar ``ai_job.py`` JSON the ``ai.planJob`` RPC returns and
// that an AI job surfaces — the renderer reads these field names verbatim.

/** Egress bytes split by data kind (text transcripts vs vision frames). */
export interface AiEgressKinds {
  text: number;
  frames: number;
}

/** The pre-flight cost / egress budget (``models/budget.py`` Budget). */
export interface AiBudget {
  requests: number;
  providers: string[];
  egressBytes: number;
  egressKinds: AiEgressKinds;
  withinFreeLimits: boolean;
}

/** How a planned AI call will run (the resolved route flags). */
export interface AiRoute {
  providers: string[];
  degradeChain: string[];
  cacheHit: boolean;
  willEgress: boolean;
}

/** The full ``ai.planJob`` pre-flight payload (ZERO provider calls). */
export interface AiPlan {
  route: AiRoute;
  costEst: AiBudget;
  cacheHit: boolean;
  willEgress: boolean;
  budget: AiBudget;
  preview: string;
  cacheKey: string;
}

/** What a request to ``ai.planJob`` carries (all optional; pre-flight only). */
export interface AiPlanRequest {
  messages?: { role: string; content: string }[];
  model?: string;
  params?: Record<string, unknown>;
  request?: { targetSize?: number; textBytes?: number; frameBytes?: number };
  capability?: 'text' | 'vision';
}

/** The cost/route/preview surface the AI-job UI shows alongside job progress. */
export interface AiPreviewState {
  route: AiRoute | null;
  costEst: AiBudget | null;
  preview: string | null;
  cacheHit: boolean;
  willEgress: boolean;
}

const NO_PREVIEW: AiPreviewState = {
  route: null,
  costEst: null,
  preview: null,
  cacheHit: false,
  willEgress: false,
};

function planToPreview(plan: AiPlan): AiPreviewState {
  return {
    route: plan.route,
    costEst: plan.costEst,
    preview: plan.preview,
    cacheHit: plan.cacheHit,
    willEgress: plan.willEgress,
  };
}

/**
 * Drives an AI job on the AI-Job envelope (WU-envelope): a pre-flight `plan`
 * surfaces the cost/route/preview WITHOUT executing (the `ai.planJob` RPC, zero
 * provider calls), and `start` runs the real AI job through the underlying
 * {@link useJob} (so progress / cancel / `job.done` + the error toast bridge are
 * all reused unchanged). The hook adds the `costEst` / `route` / `preview`
 * surface on top of `useJob`'s job state.
 */
export function useAiJob(options?: UseJobOptions) {
  const job = useJob(options);
  const [preview, setPreview] = useState<AiPreviewState>(NO_PREVIEW);

  /** Pre-flight: fetch the cost/route/preview for a planned AI call (no run). */
  const plan = useCallback(async (req?: AiPlanRequest): Promise<AiPlan> => {
    const result = await rpc<AiPlan>('ai.planJob', { ...(req ?? {}) });
    setPreview(planToPreview(result));
    return result;
  }, []);

  /** Run the AI job: delegates to useJob.start (tracks progress + job.done). */
  const start = useCallback(
    async <T = { jobId: string }>(method: string, params?: Record<string, unknown>): Promise<T> => {
      return job.start<T>(method, params);
    },
    [job],
  );

  /** Clear both the job state and the pre-flight preview. */
  const reset = useCallback((): void => {
    setPreview(NO_PREVIEW);
    job.reset();
  }, [job]);

  return {
    state: job.state,
    preview,
    plan,
    start,
    cancel: job.cancel,
    finish: job.finish,
    reset,
  };
}

export type { JobError, UseJobOptions };
export default useAiJob;
