// SemanticSearch feature panel (WU-A6).
//
// A keyboard-operable semantic search over the video's transcript. Mounts into
// the per-video Workspace; drives the three `index.*` states (DESIGN §1.6):
//
//   - NOT built (`index.status.built === false`): a disabled search box + an
//     inline "Build the search index" CTA that calls `index.build`.
//   - BUILDING (`index.build` is a long job): a polite progress region fed by
//     `onProgress`; the box stays disabled until the job's `onJobDone` flips it
//     built.
//   - BUILT: the box is enabled; submitting runs `index.search` and renders the
//     hits as real focusable <button> rows. Activating a hit (Enter/Space/click)
//     seeks the workspace player to that hit's start.
//
// Status is announced via a polite `aria-live` region ("Searching…"/result
// count/"No matches"); errors surface via `role="alert"` (mirroring
// Workspace.tsx:176 / Transcribe.tsx:149).
//
// §9.1 CLOUD-BUDGET ACKNOWLEDGEMENT. When the user's persisted
// `confirmCloudBudget` setting is ON and `index.plan` says the run WILL egress,
// the run is DEFERRED behind a consent card that shows the planned cost/egress,
// and only the user's click supplies the sidecar's ack token
// (`_enforce_cloud_budget_ack`, ai_ops.py:256). Mirrors BatchQueue.tsx:193-240:
// plan first, render the card, defer the real call. Previously this panel read
// the plan and answered the challenge itself, so a user who deliberately turned
// the setting ON still got zero confirmation from this surface.
//
// TWO HONESTY INVARIANTS the deferral must not break — both are asserted:
//   1. A DEFERRED run has produced no result, so the panel must claim none. The
//      searched-query label and the phase are committed inside `execute` (i.e.
//      only once a request is really in flight), and deferring a search DROPS
//      the previous query's verdict — otherwise the live region and
//      `.search-empty` re-announce the old outcome under the NEW query's name.
//   2. The card must not quote a number it does not have. `index.plan` sizes an
//      index BUILD from an 11-byte `"index.build"` sentinel (vision_ops.py:750),
//      not from the corpus the build embeds, so the build card states the size
//      is unestimated instead of quoting that figure (see the card below).
import React, { useCallback, useEffect, useState } from 'react';
import './panels.css';
import { fmtSeconds, getApi } from './_api';
import type { AiPlan } from '../components/useAiJob';
import type { PlayerHandle } from '../components/Player';
import type { IndexHit, IndexStatus } from '../lib/rpc';

export interface SemanticSearchProps {
  videoId: string;
  /** The workspace Player handle — activating a hit seeks it to the hit start. */
  playerRef?: React.RefObject<PlayerHandle | null>;
}

type Phase = 'idle' | 'searching' | 'results' | 'empty' | 'error';

interface BuildState {
  jobId: string;
  pct: number;
  message: string;
}

/**
 * A planned run held back for the user's §9.1 cloud-budget acknowledgement.
 * `query` is the searched text ('' for a build, which has no query).
 */
interface PendingRun {
  kind: 'build' | 'search';
  plan: AiPlan;
  query: string;
}

/** The message an unknown rejection surfaces in the panel's error banner. */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function SemanticSearch({ videoId, playerRef }: SemanticSearchProps): React.ReactElement {
  const [built, setBuilt] = useState<boolean>(false);
  const [query, setQuery] = useState<string>('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [hits, setHits] = useState<IndexHit[]>([]);
  const [error, setError] = useState<string>('');
  const [build, setBuild] = useState<BuildState | null>(null);
  // The query string that produced the current empty/results state, so the
  // "No matches for '<query>'" message names the searched term (not a later edit).
  const [searchedQuery, setSearchedQuery] = useState<string>('');
  // §9.1: the persisted budget gate (default ON, settings_store.py) and the run
  // held back waiting for the user to acknowledge it.
  const [confirmCloudBudget, setConfirmCloudBudget] = useState<boolean>(true);
  const [pending, setPending] = useState<PendingRun | null>(null);

  // Read the persisted §9.1 budget setting once on mount; a rejection keeps the
  // default-ON gate (fail-safe — never egress without acknowledgement). Same
  // read + same fail-safe as BatchQueue.tsx:123-132, through this panel's own
  // `getApi()` accessor (the panel deliberately holds no runtime `lib/rpc` dep).
  useEffect(() => {
    void getApi()
      .rpc<Record<string, unknown>>('settings.get')
      .then((s) => {
        setConfirmCloudBudget(s.confirmCloudBudget !== false);
      })
      .catch(() => {
        // Keep the default-ON gate when the setting can't be read.
      });
  }, []);

  // Probe the index status on mount (and whenever the video changes). A probe
  // failure degrades to "unbuilt" (CTA shown), never an error banner.
  useEffect(() => {
    if (!videoId) return;
    let alive = true;
    getApi()
      .rpc<IndexStatus>('index.status', { videoId })
      .then((status) => {
        if (alive) setBuilt(Boolean(status?.built));
      })
      .catch(() => {
        if (alive) setBuilt(false);
      });
    return () => {
      alive = false;
    };
  }, [videoId]);

  // Relay build-job progress + completion for THIS job only.
  useEffect(() => {
    if (!build) return;
    // The effect only subscribes while a build is in flight (and re-runs on every
    // `build` change), so the captured `build` is non-null inside both callbacks.
    const { jobId } = build;
    const api = getApi();
    const offProgress = api.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setBuild({ jobId, pct: ev.pct, message: ev.message });
    });
    const offDone = api.onJobDone
      ? api.onJobDone((ev) => {
          if (ev.jobId !== jobId) return;
          setBuilt(true);
          setBuild(null);
        })
      : () => undefined;
    return () => {
      offProgress();
      offDone();
    };
  }, [build]);

  // Dispatch a PLANNED run. The ack token (`confirmBudget`) is attached only
  // when the plan says the run WILL egress — a local/consent-denied run must NOT
  // send one (the sidecar gate never fires for it). Throws on RPC failure; each
  // caller owns how that surfaces.
  const execute = useCallback(
    async (run: PendingRun): Promise<void> => {
      const ack = run.plan.willEgress ? { confirmBudget: run.plan.cacheKey } : {};
      if (run.kind === 'build') {
        const res = await getApi().rpc<{ jobId: string }>('index.build', { videoId, ...ack });
        setBuild({ jobId: res.jobId, pct: 0, message: 'Building…' });
        return;
      }
      // Committed HERE, not at submit: `searchedQuery` names the query whose
      // verdict the panel is about to render, so it may only advance once a
      // request is genuinely in flight (invariant 1 in the header).
      setSearchedQuery(run.query);
      setPhase('searching');
      const res = await getApi().rpc<{ hits: IndexHit[] }>('index.search', {
        videoId,
        query: run.query,
        topK: 8,
        ...ack,
      });
      const list = res.hits ?? [];
      setHits(list);
      setPhase(list.length ? 'results' : 'empty');
    },
    [videoId],
  );

  // §9.1 gate: an egressing run under a live `confirmCloudBudget` waits for the
  // user's acknowledgement; everything else runs straight through (behaviour
  // with the setting OFF is unchanged).
  const startOrDefer = useCallback(
    async (run: PendingRun): Promise<void> => {
      if (run.plan.willEgress && confirmCloudBudget) {
        if (run.kind === 'search') {
          // Nothing ran, so nothing may be shown: drop the PREVIOUS query's
          // result surface. Left standing it is re-labelled with the new,
          // un-run query — `.search-empty` and the polite live region both read
          // `searchedQuery` — which is an affirmative false claim about a
          // request the panel never sent. (A deferred BUILD does not touch the
          // search surface, so it leaves the last real result alone.)
          setHits([]);
          setPhase('idle');
        }
        setPending(run);
        return;
      }
      await execute(run);
    },
    [confirmCloudBudget, execute],
  );

  const startBuild = useCallback(async () => {
    setError('');
    try {
      // Cloud-budget pre-flight: `index.build` egress is gated exactly like the
      // AI jobs (vision_ops `_enforce_egress_gates`), so a cloud-configured
      // embedder rejects the build unless the plan's cacheKey is echoed as
      // `confirmBudget`. `index.plan` is a pure planning RPC (ZERO provider
      // calls) — it only PREVIEWS the cost so the user can decide.
      const plan = await getApi().rpc<AiPlan>('index.plan', { videoId });
      await startOrDefer({ kind: 'build', plan, query: '' });
    } catch (err) {
      setError(errText(err));
    }
  }, [videoId, startOrDefer]);

  const runSearch = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = query.trim();
      if (!q) return;
      setError('');
      try {
        // Same cloud-budget pre-flight as the build path. `phase` AND
        // `searchedQuery` are committed inside `execute`, i.e. only once a
        // search is REALLY in flight — a deferred search announces nothing and
        // labels nothing, because nothing is running until the user
        // acknowledges.
        const plan = await getApi().rpc<AiPlan>('index.plan', { videoId, query: q });
        await startOrDefer({ kind: 'search', plan, query: q });
      } catch (err) {
        setHits([]);
        setError(errText(err));
        setPhase('error');
      }
    },
    [query, videoId, startOrDefer],
  );

  // The user acknowledged the previewed cost: run the held-back job now, with
  // the ack the sidecar demands. Failure surfaces exactly as it would have on
  // the direct path (a search additionally drops stale hits + enters 'error').
  const acknowledge = useCallback(
    async (run: PendingRun): Promise<void> => {
      setPending(null);
      setError('');
      try {
        await execute(run);
      } catch (err) {
        if (run.kind === 'search') {
          setHits([]);
          setPhase('error');
        }
        setError(errText(err));
      }
    },
    [execute],
  );

  const activate = useCallback(
    (hit: IndexHit) => {
      playerRef?.current?.seek(hit.start);
    },
    [playerRef],
  );

  const building = build !== null;
  // The live region announces the current search state for screen readers.
  const liveMessage =
    phase === 'searching'
      ? 'Searching…'
      : phase === 'results'
        ? `${hits.length} ${hits.length === 1 ? 'match' : 'matches'}`
        : phase === 'empty'
          ? `No matches for '${searchedQuery}'`
          : '';

  return (
    <section className="feature-panel semantic-search-panel" aria-label="Semantic search">
      <h2>Search the transcript</h2>

      <form className="search-form" onSubmit={runSearch}>
        <div className="field">
          <label htmlFor="semantic-search-query">Search the transcript</label>
          <input
            id="semantic-search-query"
            type="search"
            aria-label="Search the transcript"
            value={query}
            disabled={!built || building}
            placeholder="Find a moment by meaning…"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="actions">
          <button type="submit" disabled={!built || building}>
            Search
          </button>
          {/* Rebuild affordance: index.status reports built purely on file
              existence, and the sidecar refuses a STALE/dim-mismatched index
              with "run index.build to rebuild it first". The Build CTA only
              renders while unbuilt, so once built the ONLY escape from that
              dead-end is this Rebuild action (re-runs index.build over the
              current transcript). */}
          {built && !building && (
            <button type="button" className="rebuild" onClick={startBuild}>
              Rebuild index
            </button>
          )}
        </div>
      </form>

      {!built && !building && (
        <div className="search-cta">
          <p>Build a semantic index of this transcript to search it by meaning.</p>
          <button type="button" onClick={startBuild} disabled={!videoId}>
            Build the search index
          </button>
        </div>
      )}

      {pending !== null && (
        // §9.1 consent card — the user's own confirm-cloud-budget setting is ON
        // and this run WOULD leave the machine, so it names what is about to be
        // sent, where, and whether it is billable BEFORE anything runs.
        <section className="search-consent" aria-label="Cloud egress consent">
          <h3 className="search-consent__title">
            Before this {pending.kind === 'build' ? 'index build' : 'search'} runs
          </h3>
          {pending.kind === 'build' ? (
            // HONESTY (invariant 2): `index.plan` plans a build over an 11-byte
            // `"index.build"` SENTINEL (vision_ops.py:750) — not over the corpus
            // `index_build` actually embeds — so its `egressBytes`, `requests`,
            // `withinFreeLimits` AND the `preview` string derived from them are
            // orders of magnitude low for a build. A spend confirmation quoting
            // "11 bytes … within the provider free limits" would be worse than
            // no number at all, so the card names WHO receives the data (that
            // part is real) and says plainly that the size is not estimated.
            // The sentinel also UNDER-METERS the sidecar's monthly cap and the
            // recorded egress cents for a build — a sidecar-lane defect
            // (vision_ops.index_build:549-559), not fixable from this panel.
            <p className="search-consent__egress">
              It sends this video&apos;s entire transcript to{' '}
              {pending.plan.costEst.providers.join(', ')} to be embedded. The pre-flight plan does
              not size an index build, so the bytes, the request count and the free-tier fit are not
              estimated here.
            </p>
          ) : (
            <>
              <p className="search-consent__egress">
                It sends {pending.plan.costEst.egressBytes} bytes of search-query text to{' '}
                {pending.plan.costEst.providers.join(', ')} in {pending.plan.costEst.requests}{' '}
                request(s) — {pending.plan.costEst.withinFreeLimits ? 'within' : 'outside'} the
                provider free limits.
              </p>
              <p className="search-consent__preview">{pending.plan.preview}</p>
            </>
          )}
          <div className="actions">
            <button
              type="button"
              className="search-consent__ack"
              onClick={() => void acknowledge(pending)}
            >
              Acknowledge cloud egress and continue
            </button>
            <button
              type="button"
              className="search-consent__cancel"
              onClick={() => setPending(null)}
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      {building && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={build.pct} />
          <span className="progress-pct">{Math.round(build.pct)}%</span>
          {build.message && <span className="progress-message"> · {build.message}</span>}
        </div>
      )}

      <div className="search-status" aria-live="polite">
        {liveMessage}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {phase === 'empty' && <p className="search-empty">{liveMessage}</p>}

      {phase === 'results' && (
        <ul className="search-hits">
          {hits.map((hit) => {
            const stamp = fmtSeconds(hit.start);
            const label = `Seek to ${stamp} — '${hit.text}'`;
            return (
              <li key={hit.segmentIndex}>
                <button type="button" aria-label={label} onClick={() => activate(hit)}>
                  <span className="hit-time">{stamp}</span>
                  <span className="hit-text">{hit.text}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default SemanticSearch;
