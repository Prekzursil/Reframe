// BrollPanel.tsx — "Auto B-roll" (W16-UI: the renderer surface for v1.5 flagship #3).
//
// WHY THIS PANEL EXISTS (measured, detector controlled BOTH ways).
// The sidecar ships the whole flagship: `features/broll_ops.py`, `broll_plan.py`,
// `broll_index.py`, `broll_compose.py` (~58 KB) and SEVEN registered RPCs, frozen
// into the authoritative method list (`sidecar/tests/test_handlers_rpc_surface.py`).
// Probe run at `2e1f5fbf`:
//   target : `rg -i broll app/`     -> 0 files
//   control: `rg -i broll sidecar/` -> 15 files  (so the matcher fires)
// A zero with a live control is a real absence: not one line of the flagship was
// reachable by any user. BR1 (#393) added the registration door — `broll.assets` /
// `broll.addAsset` / `broll.removeAsset` — so the library can now be FILLED from
// the app, which is what makes a panel worth mounting. This lane is renderer-only;
// it changes nothing under `sidecar/`.
//
// TRANSPORT (`_api.ts` CONTRACT-NOTE). `status` / `assets` / `addAsset` /
// `removeAsset` are DIRECT-return. `index` / `suggest` / `apply` are deferred JOBS:
// the rpc promise carries `{jobId}` only and the payload arrives on the later
// `job.done`, so those three go through `waitForJobDone` — same shape as
// `Stabilize.tsx` / `Gaze.tsx`.
//
// ─── THE THRESHOLD IS A GUESS, AND MOUNTING A UI MAKES IT USER-VISIBLE ───────
// `broll_plan.py:77` `DEFAULT_MIN_SIMILARITY = 0.22` is documented at
// `broll_plan.py:50-55` as an UNCALIBRATED placeholder carried from the design
// doc, with the settling experiment named at
// `docs/plans/v1.5/flagship-auto-broll.md` §11.2 (20-30 (segment, relevant-asset,
// decoy) triples per tier, pick the precision/recall knee). It is inert today
// because nothing reaches it. The moment this panel exposes matching, that guess
// decides which clips a user is offered: too high offers nothing and reads as
// "broken", too low offers junk and reads as "stupid".
//
// DECISION: option (a) — EXPOSE A THRESHOLD SLIDER, presented as adjustable rather
// than authoritative. Two reasons it is (a) and not (b) "calibrate it":
//   * (b) needs a labelled probe set AND a real SigLIP-2 tower, and would change
//     `broll_plan.py` — outside this lane's file scope, which is renderer-only;
//   * the sidecar module itself prescribes (a) in so many words: "Until then treat
//     the default as 'requires a threshold slider', not as a tuned constant."
// So the panel SENDS an explicit `threshold` on every call. That matters beyond
// cosmetics: if the field were omitted the sidecar default would silently be the
// authority, and the number on screen would not be the number that ran. The
// disclosure below states the value, that it is uncalibrated, that it is
// PER-BACKBONE (the docstring's second warning), and the experiment that settles
// it. Shipping 0.22 silently, as though tuned, is the thing this avoids.
//
// ─── WHAT IS STILL MISSING — THE COPY MUST NOT IMPLY OTHERWISE ──────────────
//   * BR2 content-hash staleness is ABSENT. `add_broll` leaves `content_hash`
//     NULL on purpose (a whole-file BLAKE3 inside a synchronous RPC), so
//     freshness is size+mtime only — an edit that preserves both is invisible.
//   * B-roll POSTER extraction does not exist. `thumbnailPath` is
//     unconditionally `""`; the only writer, `Library.set_thumbnail`, is
//     `role='source'`-scoped, and `set_thumbnail(<brollAssetId>, …)` was measured
//     to return `None` and change nothing. So the grid is designed for the ABSENT
//     case and renders a labelled placeholder, never an <img> that would 404.
//   * BR6 REVERSIBILITY is design-only. `broll.apply` renders a flat
//     `{stem}.broll.mp4` (`broll_ops.py:450`) — there is no inverse op and no
//     overlay track, so a user who dislikes the result has no undo beyond
//     re-exporting. That is disclosed ABOVE the Apply button, not after it.
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import './panels.css';
import './broll.css';
import { extractJobId, getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';
import type { BrollAsset, BrollAssetsResult, BrollInsertion, BrollStatus } from '../lib/rpc';

/**
 * Mirror of `broll_plan.DEFAULT_MIN_SIMILARITY` — the slider's starting point, NOT
 * a tuned value. Pinned against the real `.py` by `brollClient.conformance.test.ts`
 * so a calibration landing in the sidecar cannot leave this seed behind.
 */
export const DEFAULT_BROLL_THRESHOLD = 0.22;

/** Mirror of `broll_plan.DEFAULT_MAX_COVERAGE_PCT` (also conformance-pinned). */
export const DEFAULT_BROLL_MAX_COVERAGE_PCT = 40;

/** Mirror of `broll_plan.LAYOUTS`; `[0]` is `DEFAULT_LAYOUT`. */
export const BROLL_LAYOUTS = ['cutaway', 'pip'] as const;

/** Mirror of `broll_ops.NO_CONFIDENT_MATCH` — the honest empty-plan reason. */
export const BROLL_REASON_NO_MATCH = 'no confident match';

/** Mirror of `broll_ops.MATCHED`. */
export const BROLL_REASON_MATCHED = 'matched';

/** Shown in place of a poster. Registered assets have none (see the header). */
export const NO_POSTER_LABEL = 'No preview';

/**
 * The threshold disclosure. Names the number, that it is UNCALIBRATED, that it is
 * per-backbone, and the experiment that would settle it — so the slider reads as
 * adjustable rather than authoritative.
 */
export const THRESHOLD_IS_UNCALIBRATED =
  'Match threshold: a suggestion is only offered when the cosine similarity between ' +
  'the spoken segment and the asset reaches this value. The starting value of 0.22 is ' +
  'an UNCALIBRATED placeholder, not a tuned number — no labelled probe set has been ' +
  'measured yet, and the right value is specific to the matching backbone, so a ' +
  'different backbone needs its own. Treat it as a dial, not an answer: raise it if ' +
  'you are offered junk, lower it if you are offered nothing. The calibration that ' +
  'would replace it is described in docs/plans/v1.5/flagship-auto-broll.md section 11.2.';

/**
 * The BR6 disclosure, rendered directly ABOVE the Apply control. A user must know
 * an apply cannot be undone BEFORE clicking, not from a support thread afterwards.
 */
export const APPLY_IS_ONE_WAY =
  'Apply is a ONE-WAY render: it writes a new flat video file into the broll folder ' +
  'under your exports, with the b-roll burned in. Your source video is never ' +
  'modified, but there is no undo and no separate b-roll track to switch off — ' +
  'reversible apply is designed and not built yet. If you dislike the result, delete ' +
  'that file and apply a different selection.';

/** What the engine cannot yet do. Stated so the panel never implies otherwise. */
export const BROLL_KNOWN_LIMITS =
  'Two engine limits worth knowing: staleness is tracked by file size and modified ' +
  'time only (a re-edit that preserves both will not trigger a re-index, so use ' +
  'Re-embed everything after one), and there is no preview extraction for b-roll ' +
  'files yet — every tile below shows a no preview placeholder rather than a frame.';

/** The badge the design doc asks for, driven by the WIRE and not by a promise. */
export const BROLL_LOCAL_ONLY =
  'Fully local: matching runs on this machine, and no frame, transcript or filename ' +
  'is uploaded.';

/** Rendered instead of the badge if the sidecar ever reports egress on this path. */
export const BROLL_EGRESS_WARNING =
  'This build reports that b-roll matching would send data off this machine. That is ' +
  'not the designed behaviour for auto-b-roll — stop and check the build before using it.';

// --- pure helpers (exported for tests) -------------------------------------

/** The message text of any thrown value (shared by every catch below). */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * True when `row` carries the two fields every consumer dereferences. A row that
 * fails this is DROPPED rather than rendered as a phantom the user cannot act on
 * (`removeAsset` needs the id, `apply` needs the path).
 */
function isAssetRow(row: unknown): row is BrollAsset {
  const rec = asRecord(row);
  return str(rec.assetId).length > 0 && str(rec.path).length > 0;
}

/**
 * Read `broll.assets` -> `{assets, missing}`.
 *
 * The two halves are a PARTITION of one sidecar snapshot (`broll_assets` reads the
 * registry exactly once), so this keeps them together rather than re-deriving
 * `missing` from `assets` — a second derivation is how an asset ends up in both
 * halves or in neither.
 */
export function readBrollAssets(result: unknown): BrollAssetsResult {
  const rec = asRecord(result);
  const pickList = (value: unknown): BrollAsset[] =>
    Array.isArray(value) ? value.filter(isAssetRow) : [];
  return { assets: pickList(rec.assets), missing: pickList(rec.missing) };
}

/**
 * Read `broll.status`. `null` for a shapeless payload so the panel renders nothing
 * instead of a snapshot of invented zeros presented as measurements.
 */
export function readBrollStatus(result: unknown): BrollStatus | null {
  if (typeof result !== 'object' || result === null) return null;
  const rec = result as Record<string, unknown>;
  return {
    indexed: rec.indexed === true,
    assetCount: num(rec.assetCount),
    libraryCount: num(rec.libraryCount),
    model: str(rec.model),
    dim: num(rec.dim),
    stale: rec.stale === true,
    staleCount: num(rec.staleCount),
    willEgress: rec.willEgress === true,
  };
}

/**
 * Read a `broll.suggest` job.done payload. An unusable payload becomes the HONEST
 * empty plan (`no confident match`) rather than an error: "nothing cleared the
 * threshold" is a legitimate result and the whole point of the gate.
 */
export function readBrollPlan(result: unknown): { insertions: BrollInsertion[]; reason: string } {
  const rec = asRecord(result);
  const rows = Array.isArray(rec.insertions) ? rec.insertions.filter(isAssetRow) : [];
  const insertions = rows as unknown as BrollInsertion[];
  return {
    insertions,
    reason: insertions.length > 0 ? str(rec.reason) : BROLL_REASON_NO_MATCH,
  };
}

/**
 * A human label for an asset: the registry title, else the file's basename, else
 * the id. Never blank — a nameless tile is not actionable.
 */
export function assetLabel(asset: BrollAsset): string {
  const title = str(asset.title).trim();
  if (title.length > 0) return title;
  const parts = asset.path.split(/[\\/]/);
  const base = parts[parts.length - 1];
  return base.length > 0 ? base : asset.assetId;
}

/**
 * The duration cell. FACT: `durationSec` is `number | null` — a SCANNED row always
 * reports `null` and a registered still (or a failed ffprobe) reports `0.0`, so
 * neither may be printed as a duration. A still is labelled as such; anything
 * without a positive finite length is explicitly UNKNOWN.
 */
export function assetDurationLabel(asset: BrollAsset): string {
  if (asset.kind === 'image') return 'still';
  const value = asset.durationSec;
  if (typeof value !== 'number') return '—';
  if (!Number.isFinite(value)) return '—';
  return value > 0 ? `${value.toFixed(1)}s` : '—';
}

/**
 * The poster source, or `null` when there is none. FACT: `add_broll` writes `""`
 * and no b-roll poster extractor exists, so `null` is the NORMAL answer and the
 * grid must render a placeholder rather than an <img> with an empty `src`.
 */
export function posterSrc(asset: BrollAsset): string | null {
  const path = str(asset.thumbnailPath);
  return path.length > 0 ? path : null;
}

/** The timeline window a suggestion would occupy, in the source's own seconds. */
export function insertionWindowLabel(insertion: BrollInsertion): string {
  return `${insertion.start.toFixed(1)}s - ${insertion.end.toFixed(1)}s (${insertion.duration.toFixed(1)}s)`;
}

// --- component -------------------------------------------------------------

export interface BrollPanelProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function BrollPanel({ videoId, api }: BrollPanelProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  // library state (global to the app, not to this video)
  const [assets, setAssets] = useState<BrollAsset[]>([]);
  const [missing, setMissing] = useState<BrollAsset[]>([]);
  const [status, setStatus] = useState<BrollStatus | null>(null);
  const [addPath, setAddPath] = useState<string>('');
  const [addTitle, setAddTitle] = useState<string>('');
  const [force, setForce] = useState<boolean>(false);
  // matching controls
  const [threshold, setThreshold] = useState<number>(DEFAULT_BROLL_THRESHOLD);
  const [coverage, setCoverage] = useState<number>(DEFAULT_BROLL_MAX_COVERAGE_PCT);
  const [layout, setLayout] = useState<string>(BROLL_LAYOUTS[0]);
  // the reviewed plan — PER VIDEO (see the reset effect below)
  const [insertions, setInsertions] = useState<BrollInsertion[]>([]);
  const [accepted, setAccepted] = useState<boolean[]>([]);
  const [reason, setReason] = useState<string>('');
  const [planned, setPlanned] = useState<boolean>(false);
  const [appliedPath, setAppliedPath] = useState<string>('');
  // job lane
  const [busy, setBusy] = useState<string>('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');

  const loadLibrary = useCallback(async (): Promise<void> => {
    const [assetsRes, statusRes] = await Promise.all([
      bridge.rpc<unknown>('broll.assets'),
      bridge.rpc<unknown>('broll.status'),
    ]);
    const parsed = readBrollAssets(assetsRes);
    setAssets(parsed.assets);
    setMissing(parsed.missing);
    setStatus(readBrollStatus(statusRes));
  }, [bridge]);

  useEffect(() => {
    void (async () => {
      try {
        await loadLibrary();
      } catch (err) {
        // A corrupt `library.json` really does fail this read (the registry half
        // runs `Library._open` -> `_migrate`). Showing the error beats showing an
        // empty grid, which would look like "you have no b-roll".
        setError(errText(err));
      }
    })();
  }, [loadLibrary]);

  // ─── A PLAN BELONGS TO EXACTLY ONE VIDEO ───────────────────────────────────
  // `broll.apply` sends the CURRENT `videoId` together with whatever insertions
  // are on screen and composites them verbatim, so a plan left over from the
  // previous video would burn video A's windows and assets into video B. This
  // panel is mounted UNKEYED (`views/Workspace.tsx` renderPanel), and App.tsx's
  // launch-restore effect swaps the open video IN PLACE without an unmount, so the
  // stale-plan state is reachable rather than hypothetical.
  //
  // useLAYOUTEffect, not useEffect: a passive effect runs after the browser can
  // paint, so React could commit — and show — the new video with the old plan and
  // an enabled Apply button for one frame. Clearing before paint closes it
  // outright. The LIBRARY state is deliberately NOT reset: the b-roll library and
  // its index are per MACHINE, not per video, and re-reading them on every video
  // switch would cost a scan plus a SQLite read for no new information.
  const videoIdRef = useRef<string>(videoId);
  useLayoutEffect(() => {
    videoIdRef.current = videoId;
    setInsertions([]);
    setAccepted([]);
    setReason('');
    setPlanned(false);
    setAppliedPath('');
    setError('');
  }, [videoId]);

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  /** Start a deferred job and resolve its terminal `job.done` payload. */
  const runJob = useCallback(
    async (method: string, params: Record<string, unknown>): Promise<unknown> => {
      const res = await bridge.rpc<unknown>(method, params);
      const id = extractJobId(res);
      setJobId(id ?? null);
      // waitForJobDone REJECTS on an `{error}` job.done payload, so a failed job is
      // never laundered into a silent success.
      return id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
    },
    [bridge],
  );

  /**
   * Run a VIDEO-SCOPED deferred job and apply its outcome only if the panel is
   * still showing the video that asked for it.
   *
   * ONE gate for BOTH the success and the failure write, on purpose: video A's
   * plan must not appear under video B, and neither must video A's error message.
   * The write is deferred into `settle` so a single `if` covers both paths — an
   * id COMPARISON rather than a latch, so switching away and back re-admits it.
   */
  const runVideoJob = useCallback(
    async (
      method: string,
      params: Record<string, unknown>,
      onResult: (result: unknown) => void,
    ): Promise<void> => {
      const startedFor = videoId;
      let settle: () => void;
      try {
        const result = await runJob(method, { videoId, ...params });
        settle = () => onResult(result);
      } catch (err) {
        const text = errText(err);
        settle = () => setError(text);
      }
      if (videoIdRef.current === startedFor) settle();
    },
    [runJob, videoId],
  );

  /**
   * Shared prologue/epilogue so every action has ONE busy + progress + error
   * contract. It SWALLOWS the rejection (surfacing it as `error` instead), which is
   * why a caller must never chain post-success work onto the returned promise — see
   * `addAsset`. Deliberately NOT called `act`: React's test `act()` is all over this
   * panel's suite and a same-named callback inside the component reads as that.
   */
  const withBusy = useCallback(async (label: string, body: () => Promise<void>): Promise<void> => {
    setBusy(label);
    setError('');
    setPct(0);
    setMessage('Starting…');
    try {
      await body();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy('');
      setJobId(null);
    }
  }, []);

  const refresh = useCallback(
    (label: string, mutate: () => Promise<unknown>): Promise<void> =>
      withBusy(label, async () => {
        await mutate();
        await loadLibrary();
      }),
    [loadLibrary, withBusy],
  );

  const addAsset = useCallback(
    (): Promise<void> =>
      withBusy('add', async () => {
        const title = addTitle.trim();
        await bridge.rpc('broll.addAsset', {
          path: addPath.trim(),
          // A blank field means "no title", which is the ABSENT param — not an
          // empty-string title. `add_broll` falls back to the file stem itself.
          ...(title.length > 0 ? { title } : {}),
        });
        // Cleared INSIDE the body and only after the rpc resolves. `withBusy`
        // swallows the rejection, so a `.then()` chained onto it would also run on
        // the REFUSAL path — and the registry door refuses three real cases (missing
        // path, a directory with a media extension, a non-b-roll extension). Wiping
        // the field there would make the user retype a path they need to CORRECT,
        // right next to the error telling them what was wrong with it.
        setAddPath('');
        setAddTitle('');
        await loadLibrary();
      }),
    [addPath, addTitle, bridge, loadLibrary, withBusy],
  );

  const removeAsset = useCallback(
    (id: string): Promise<void> => refresh('remove', () => bridge.rpc('broll.removeAsset', { id })),
    [bridge, refresh],
  );

  const runIndex = useCallback(
    (): Promise<void> => refresh('index', () => runJob('broll.index', { force })),
    [force, refresh, runJob],
  );

  const suggest = useCallback(
    (): Promise<void> =>
      withBusy('suggest', () =>
        runVideoJob(
          'broll.suggest',
          // Sent EXPLICITLY, always: an omitted threshold would make the sidecar's
          // uncalibrated 0.22 the silent authority and the slider a decoration.
          { threshold, maxCoveragePct: coverage, layout },
          (result) => {
            const plan = readBrollPlan(result);
            setInsertions(plan.insertions);
            setAccepted(plan.insertions.map(() => true));
            setReason(plan.reason);
            setPlanned(true);
            setAppliedPath('');
          },
        ),
      ),
    [coverage, layout, runVideoJob, threshold, withBusy],
  );

  const approved = insertions.filter((_row, index) => accepted[index]);

  const apply = useCallback(
    (): Promise<void> =>
      withBusy('apply', () =>
        runVideoJob('broll.apply', { insertions: approved }, (result) => {
          setAppliedPath(str(pickField<string>(result, 'path')));
        }),
      ),
    [approved, runVideoJob, withBusy],
  );

  const cancel = useCallback(async (): Promise<void> => {
    // Defensive: Cancel renders only while `busy && jobId`.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort — a failed cancel must not become a panel error.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  const toggleAccept = useCallback((index: number): void => {
    setAccepted((prev) => prev.map((on, at) => (at === index ? !on : on)));
  }, []);

  const working = busy !== '';

  return (
    <section className="feature-panel broll-panel" aria-label="Auto B-roll">
      <h2>Auto B-roll</h2>
      <p className="assets-intro">
        Match what you are SAYING to clips and stills you already own, then cut them in. Nothing is
        inserted unless a segment clears the match threshold, and nothing is rendered until you
        review the list — a confidently wrong cutaway is worse than no cutaway.
      </p>

      {status?.willEgress === true ? (
        <p className="broll-egress" data-section="egress-warning" role="alert">
          {BROLL_EGRESS_WARNING}
        </p>
      ) : (
        <p className="broll-local" data-section="local-only" role="status">
          {BROLL_LOCAL_ONLY}
        </p>
      )}

      <p className="broll-limits" data-section="limits">
        {BROLL_KNOWN_LIMITS}
      </p>

      <h3>Library</h3>
      {status && (
        <dl className="broll-status" data-section="status">
          <div>
            <dt>In library</dt>
            <dd data-field="libraryCount">{status.libraryCount}</dd>
          </div>
          <div>
            <dt>Indexed</dt>
            <dd data-field="indexed">{status.indexed ? status.assetCount : 'not yet'}</dd>
          </div>
          <div>
            <dt>Needs embedding</dt>
            <dd data-field="stale">{status.stale ? status.staleCount : 'none'}</dd>
          </div>
          <div>
            <dt>Matcher</dt>
            <dd data-field="model">
              <code>{status.model || 'none'}</code>
              {status.dim > 0 ? ` · ${status.dim}d` : ''}
            </dd>
          </div>
        </dl>
      )}

      <div className="field broll-add">
        <label>
          Add a b-roll file{' '}
          <input
            data-input="add-path"
            type="text"
            placeholder="D:/pictures/hero dog.png"
            value={addPath}
            onChange={(e) => setAddPath(e.target.value)}
            disabled={working}
          />
        </label>
        <label>
          Name it (optional){' '}
          <input
            data-input="add-title"
            type="text"
            placeholder="Hero dog"
            value={addTitle}
            onChange={(e) => setAddTitle(e.target.value)}
            disabled={working}
          />
        </label>
        <button
          type="button"
          data-action="add"
          onClick={() => void addAsset()}
          disabled={working || addPath.trim().length === 0}
        >
          Register
        </button>
        <span className="broll-add-hint">
          The file is referenced where it lives — nothing is copied or moved, and unregistering
          never deletes it. A folder set as your bulk b-roll directory is scanned as well; both
          sources are merged into the one list below.
        </span>
      </div>

      {assets.length > 0 && (
        <ul className="broll-grid" data-section="grid">
          {assets.map((asset) => {
            const poster = posterSrc(asset);
            return (
              <li key={asset.assetId} data-asset-id={asset.assetId} className="broll-tile">
                {poster ? (
                  <img className="broll-poster" src={poster} alt="" />
                ) : (
                  <span className="broll-poster broll-poster--none" data-poster="none">
                    {NO_POSTER_LABEL}
                  </span>
                )}
                <span className="broll-tile-name">{assetLabel(asset)}</span>
                <span className="broll-tile-meta">
                  <span data-field="kind">{asset.kind}</span>
                  {' · '}
                  <span data-field="duration">{assetDurationLabel(asset)}</span>
                  {' · '}
                  <span data-field="origin">{asset.registered ? 'registered' : 'folder scan'}</span>
                </span>
                <code className="broll-tile-path">{asset.path}</code>
                {asset.registered && (
                  <button
                    type="button"
                    className="secondary"
                    data-action="unregister"
                    onClick={() => void removeAsset(asset.assetId)}
                    disabled={working}
                  >
                    Unregister
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* A registered asset whose file has vanished is REPORTED, never silently
          dropped: it is excluded from indexing (a dead path would fail the whole
          batch), so without this section it would simply disappear. */}
      {missing.length > 0 && (
        <div className="broll-missing" data-section="missing" role="status">
          <h3>Missing files</h3>
          <p>
            These are still registered, but the file is no longer where it was. They are left out of
            matching until you put the file back or unregister them.
          </p>
          <ul>
            {missing.map((asset) => (
              <li key={asset.assetId} data-missing-id={asset.assetId}>
                <span className="broll-missing-name">{assetLabel(asset)}</span>
                <code>{asset.path}</code>
                <button
                  type="button"
                  className="secondary"
                  data-action="unregister-missing"
                  onClick={() => void removeAsset(asset.assetId)}
                  disabled={working}
                >
                  Unregister
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="actions broll-index-actions">
        <button
          type="button"
          data-action="index"
          onClick={() => void runIndex()}
          disabled={working}
        >
          {busy === 'index' ? 'Indexing…' : 'Index library'}
        </button>
        <label className="broll-force">
          <input
            data-input="force"
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            disabled={working}
          />{' '}
          Re-embed everything (needed after a matcher change)
        </label>
      </div>

      <h3>Matching</h3>
      <p className="broll-threshold-copy" data-section="threshold-disclosure">
        {THRESHOLD_IS_UNCALIBRATED}
      </p>
      <div className="field broll-match">
        <label>
          Match threshold{' '}
          <input
            data-input="threshold"
            type="range"
            min={0.05}
            max={0.9}
            step={0.01}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            disabled={working}
          />{' '}
          <span className="broll-threshold-value">{threshold.toFixed(2)}</span>
        </label>
        <label>
          Most of the video b-roll may cover (%){' '}
          <input
            data-input="coverage"
            type="number"
            min={1}
            max={100}
            value={coverage}
            onChange={(e) => setCoverage(Number(e.target.value))}
            disabled={working}
          />
        </label>
        <label>
          Style{' '}
          <select
            data-input="layout"
            value={layout}
            onChange={(e) => setLayout(e.target.value)}
            disabled={working}
          >
            {BROLL_LAYOUTS.map((option) => (
              <option key={option} value={option}>
                {option === 'cutaway' ? 'Full-frame cutaway' : 'Inset (picture in picture)'}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="actions">
        <button
          type="button"
          data-action="suggest"
          onClick={() => void suggest()}
          disabled={working}
        >
          {busy === 'suggest' ? 'Matching…' : 'Suggest b-roll'}
        </button>
        {working && jobId && (
          <button
            type="button"
            data-action="cancel"
            className="secondary"
            onClick={() => void cancel()}
          >
            Cancel
          </button>
        )}
      </div>

      {working && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {/* "Nothing cleared the threshold" is a RESULT, not a failure. Saying so
          plainly — with the dial to change it right above — is the honest answer;
          inserting something anyway is the competitor behaviour being avoided. */}
      {planned && insertions.length === 0 && (
        <p className="broll-no-match" data-section="no-match" role="status">
          No confident match: nothing in your library scored at or above {threshold.toFixed(2)} for
          any segment, so nothing is offered. Lower the threshold, or add assets that match what you
          talk about, and try again. Reason from the engine: {reason}
        </p>
      )}

      {insertions.length > 0 && (
        <div className="broll-review" data-section="review">
          <h3>
            Review ({approved.length} of {insertions.length} selected)
          </h3>
          <ul>
            {insertions.map((insertion, index) => (
              <li
                key={`${insertion.segmentIndex}-${insertion.start}-${insertion.assetId}`}
                data-insertion={index}
                className="broll-review-row"
              >
                <label>
                  <input
                    data-input="accept"
                    type="checkbox"
                    checked={accepted[index] === true}
                    onChange={() => toggleAccept(index)}
                    disabled={working}
                  />{' '}
                  <span data-field="window">{insertionWindowLabel(insertion)}</span>
                </label>
                <span className="broll-review-score" data-field="score">
                  {insertion.score.toFixed(2)}
                </span>
                <span className="broll-review-reason" data-field="reason">
                  {insertion.reason}
                </span>
                <code data-field="path">{insertion.path}</code>
              </li>
            ))}
          </ul>

          <p className="broll-one-way" data-section="one-way" role="status">
            {APPLY_IS_ONE_WAY}
          </p>
          <div className="actions">
            <button
              type="button"
              data-action="apply"
              onClick={() => void apply()}
              disabled={working || approved.length === 0}
            >
              {busy === 'apply' ? 'Rendering…' : `Apply ${approved.length} cutaway(s)`}
            </button>
          </div>
        </div>
      )}

      {appliedPath && (
        <div className="output-done" data-section="result">
          <span className="output-done-label">B-roll rendered</span>
          <code>{appliedPath}</code>
        </div>
      )}
    </section>
  );
}

export default BrollPanel;
