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

  const startBuild = useCallback(async () => {
    setError('');
    try {
      // Cloud-budget pre-flight: `index.build` egress is gated exactly like the
      // AI jobs (vision_ops `_enforce_egress_gates`), so a cloud-configured
      // embedder rejects the build unless we echo the plan's cacheKey as
      // `confirmBudget`. `index.plan` is a pure planning RPC (ZERO provider
      // calls); we only attach the ack when the plan says it WILL egress (a
      // local/consent-denied build must NOT send one).
      const plan = await getApi().rpc<AiPlan>('index.plan', { videoId });
      const params = plan.willEgress ? { videoId, confirmBudget: plan.cacheKey } : { videoId };
      const res = await getApi().rpc<{ jobId: string }>('index.build', params);
      setBuild({ jobId: res.jobId, pct: 0, message: 'Building…' });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [videoId]);

  const runSearch = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = query.trim();
      if (!q) return;
      setError('');
      setPhase('searching');
      setSearchedQuery(q);
      try {
        // Same cloud-budget pre-flight as the build path: a cloud-embedder
        // `index.search` is egress-gated, so echo the plan's cacheKey as
        // `confirmBudget` when the plan will egress (never for a local search).
        const plan = await getApi().rpc<AiPlan>('index.plan', { videoId, query: q });
        const res = await getApi().rpc<{ hits: IndexHit[] }>(
          'index.search',
          plan.willEgress
            ? { videoId, query: q, topK: 8, confirmBudget: plan.cacheKey }
            : { videoId, query: q, topK: 8 },
        );
        const list = res.hits ?? [];
        setHits(list);
        setPhase(list.length ? 'results' : 'empty');
      } catch (err) {
        setHits([]);
        setError(err instanceof Error ? err.message : String(err));
        setPhase('error');
      }
    },
    [query, videoId],
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
