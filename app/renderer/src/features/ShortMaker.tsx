// ShortMaker.tsx — the short-maker review loop (unit: ui-shortmaker).
//
// Flow (CONTRACTS.md §2 shortmaker.* + §3 Candidate):
//   prompt + structured controls -> shortmaker.select (Job, show progress)
//   -> ranked candidate list (rank, score, hook, why) with preview
//   -> approve / nudge-boundaries / regenerate / discard, ALL non-destructive
//      (originals recoverable; nothing auto-exports)
//   -> shortmaker.export the approved candidates.
//
// P2 additions:
//   * audio-track picker (A2): "Original" + tracks.audio.list entries; the
//     chosen id is sent as shortmaker.export's optional `audioTrackId`.
//   * candidate preview (U1): the review area mounts components/Player in
//     window mode seeking the SELECTED candidate's sourceStart→end span, with
//     in/out markers.
//   * keyboard review (T6): with the review group focused — J/K prev/next
//     candidate (loads its window), Space play/pause, A approve, X discard,
//     ArrowLeft/ArrowRight slide the window ∓/± 1s (shift = 0.2s).
//
// P3 additions (frozen P3 mini-contract extending CONTRACTS.md A2/A3):
//   * controls gain {hookTitle (default ON), removeFillers (default OFF,
//     experimental)} — flow through shortmaker.select AND shortmaker.export
//     params like captionStyle/reframeEngine already do.
//   * candidates gain factors{hookStrength,emotionalFlow,perceivedValue,
//     shareability} 0-100 + factorNotes + viralityPct (batch-percentile);
//     the card headlines viralityPct, demotes the legacy score to a tooltip,
//     and expands a four-bar factor breakdown.
//   * feedback flywheel: approve/discard/nudge/successful-export fire
//     feedback.record (fire-and-forget, silent-logged); a footer line shows
//     feedback.stats ("Taste profile: N labels · …").
//   * exported clips surface {fillersRemoved, fillerSeconds} when present.
//
// Uses window.api.rpc + window.api.onProgress.
//
// CONTRACT-NOTE: §2's frozen method registry exposes only `shortmaker.select`
// and `shortmaker.export` (plus `job.cancel`). There is NO `shortmaker.nudge`
// RPC, and LC2 says nudge "re-snaps, doesn't re-select" and must be
// non-destructive. So nudge is applied LOCALLY to the candidate's start/end
// (clamped to the 20-60s hard window from §5 / LB5 / LC2), keeping the original
// boundaries recoverable via "reset". Regenerate = re-run `shortmaker.select`.
// Export sends only the explicitly-approved candidate ids -> `shortmaker.export`.
//
// CONTRACT-NOTE: this unit owns ONLY this file. The `window.api` typing and the
// typed rpc client (lib/rpc.ts / preload.ts) are owned by other units, so a
// minimal `Api` shape is declared locally here to match the §2 signatures
// (`rpc(method, params)` + `onProgress(cb)`) without importing another unit's
// files. It is intentionally structural so the real preload type is compatible.

import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import './shortmaker.css';
import './shortmaker-p3.css';
import '../views/shorts.css';
import { type PlayerHandle } from '../components/Player';
import { JobAbortedError } from './_api';
import { defaultEmphasisForStyle } from '../lib/captionTemplates';
import type { Cue, ShortReexportHint } from '../lib/rpc';
import { CandidateReview } from './CandidateReview';
import { ShortMakerControls as ShortMakerControlsPanel } from './ShortMakerControls';
import { ShortMakerBrandKit } from './ShortMakerBrandKit';
import { ProducedShorts } from './ProducedShorts';
import { useShortsGallery } from './useShortsGallery';
import {
  type Api,
  type FeedbackStats,
  type JobProgress,
  type AudioTrackOption,
  type PlayableResult,
  type SelectResult,
  type ExportResult,
  type ExportedClipInfo,
  type JobHandle,
  EXPORT_JOB_TIMEOUT_MS,
  NUDGE_COARSE_SEC,
  NUDGE_FINE_SEC,
  type ShortMakerControls,
  approvedCandidates,
  approvedIds,
  candidateId,
  displayPct,
  errMsg,
  extractCandidates,
  extractClips,
  isJobHandle,
  moveSelection,
  nudgeCandidate,
  recordFeedback,
  resolveJobResult,
  resolveWindowApi,
  reviewReducer,
  sanitizeControls,
  tasteProfileLine,
  waitForJobDone,
} from './shortMakerLogic';
import {
  type CandidateSort,
  type PlatformPreset,
  type PlatformPresetId,
  type BrandSettings,
  PLATFORM_PRESETS,
  PLATFORM_PRESET_IDS,
  EMPTY_BRAND_SETTINGS,
  sortReviewItems,
  applyPreset,
  topByVirality,
  buildExportParams,
  readBrandSettings,
  brandSettingsPatch,
} from './shortMakerPresets';
// Re-export the pure logic + §7/§8c/§8d helpers through this module so existing
// importers and the unit tests keep ONE entry point (the helpers physically live
// in ./shortMakerLogic + ./shortMakerPresets, extracted to respect the 800-line
// file budget). The component body below is the only render-bearing code here.
export * from './shortMakerLogic';
export { CandidateList, CandidateRow, NUDGE_STEP } from './CandidateList';
export {
  type CandidateSort,
  type PlatformPreset,
  type PlatformPresetId,
  type BrandSettings,
  PLATFORM_PRESETS,
  PLATFORM_PRESET_IDS,
  EMPTY_BRAND_SETTINGS,
  sortReviewItems,
  applyPreset,
  topByVirality,
  buildExportParams,
  readBrandSettings,
  brandSettingsPatch,
};
// ---------------------------------------------------------------------------
// React component
// ---------------------------------------------------------------------------

export interface ShortMakerProps {
  videoId: string;
  /** Injectable for tests; defaults to window.api. */
  api?: Api;
  initialControls?: Partial<ShortMakerControls>;
  /**
   * P4 §6 / C11: re-exporting a produced clip is a NAVIGATION concern. The panel
   * fires `shorts.reexport` and hands the hint up; the host (App via Workspace)
   * re-opens the Short-maker primed. Optional — absent in standalone tests.
   */
  onReexport?: (hint: ShortReexportHint) => void;
}

type Phase = 'idle' | 'selecting' | 'reviewing' | 'exporting';

export function ShortMaker({
  videoId,
  api,
  initialControls,
  onReexport,
}: ShortMakerProps): React.JSX.Element {
  const resolvedApi: Api = api ?? (resolveWindowApi() as Api);

  const [prompt, setPrompt] = useState('');
  const [controls, setControls] = useState<ShortMakerControls>(() =>
    sanitizeControls(initialControls ?? {}),
  );
  const [phase, setPhase] = useState<Phase>('idle');
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  // F1: which operation a "Retry" should re-run (null = no retryable failure).
  // A DISTINCT failure state from the confirmed-zero "No candidates" empty copy.
  const [retryAction, setRetryAction] = useState<'select' | 'batch' | 'export' | null>(null);
  const [items, dispatch] = useReducer(reviewReducer, []);
  const [exportedClips, setExportedClips] = useState<ExportedClipInfo[] | null>(null);

  // A2: the audio-track picker ('' = keep the clip's original audio).
  const [audioTracks, setAudioTracks] = useState<AudioTrackOption[]>([]);
  const [audioTrackId, setAudioTrackId] = useState('');

  // P3-D: the taste-profile footer (feedback.stats — optional sugar).
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null);

  // U1/T6: the review selection + the preview player's imperative handle.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const playerRef = useRef<PlayerHandle | null>(null);

  // P4 §7: candidate list ordering — the sidecar's rank (default) or viralityPct.
  const [sortMode, setSortMode] = useState<CandidateSort>('rank');

  // P4 §8d: the brand kit (logo / default caption template / default font),
  // hydrated from settings.get (tolerating absent keys) and persisted on edit.
  const [brand, setBrand] = useState<BrandSettings>(EMPTY_BRAND_SETTINGS);
  const [brandOpen, setBrandOpen] = useState(false);

  // DATA ROOT: the user-facing "data folder" (models/envs/exports/...). Loaded
  // once from the preload bridge; Change… picks a new dir, persists a marker, and
  // flags a restart (no files are moved — resolveDataRoot applies it next launch).
  const [dataFolder, setDataFolder] = useState<string | null>(null);
  const [dataFolderLoaded, setDataFolderLoaded] = useState(false);
  const [dataFolderPendingRestart, setDataFolderPendingRestart] = useState(false);

  // P4 §5: live caption overlay — word-level cues + the playhead driving it.
  const [cues, setCues] = useState<Cue[]>([]);
  const [currentTime, setCurrentTime] = useState(0);

  // P4 §5 preview-remount fix: ShortMaker's OWN remount epoch. Bumped when the
  // (separately-built, by Workspace) proxy makes the source playable — see the
  // root-cause note above. NOT a second proxy build.
  const [playerEpoch, setPlayerEpoch] = useState(0);

  // Track the active job so progress notifications are matched to it.
  const activeJobRef = useRef<string | null>(null);
  // F2: aborts the in-flight job.done wait on cancel/unmount so the wait rejects
  // (JobAbortedError) and the subscription/timer tear down instead of leaking.
  const abortRef = useRef<AbortController | null>(null);

  const busy = phase === 'selecting' || phase === 'exporting';

  // ---- progress wiring ----------------------------------------------------
  useEffect(() => {
    // resolvedApi is always present (prop or window.api) and exposes onProgress,
    // so this guard is defensive against a malformed bridge.
    /* v8 ignore next */
    if (!resolvedApi || typeof resolvedApi.onProgress !== 'function') return;
    const off = resolvedApi.onProgress((p) => {
      if (activeJobRef.current && p.jobId !== activeJobRef.current) return;
      setProgress(p);
    });
    return off;
  }, [resolvedApi]);

  // ---- audio tracks (A2): populate the picker from tracks.audio.list -------
  useEffect(() => {
    if (!resolvedApi || !videoId) return undefined;
    let alive = true;
    Promise.resolve(
      resolvedApi.rpc<{ audioTracks?: AudioTrackOption[] }>('tracks.audio.list', { videoId }),
    )
      .then((res) => {
        if (alive && res && Array.isArray(res.audioTracks)) setAudioTracks(res.audioTracks);
      })
      .catch(() => {
        // The picker is optional sugar: on failure keep the "Original" default
        // rather than blocking the review loop with an error.
      });
    return () => {
      alive = false;
    };
  }, [resolvedApi, videoId]);

  // ---- taste profile (P3-D): populate the footer from feedback.stats -------
  useEffect(() => {
    // resolvedApi is always present; defensive guard for a missing bridge.
    /* v8 ignore next */
    if (!resolvedApi) return undefined;
    let alive = true;
    Promise.resolve(resolvedApi.rpc<{ labels?: unknown; calibrated?: unknown }>('feedback.stats'))
      .then((res) => {
        if (alive && res && typeof res.labels === 'number' && typeof res.calibrated === 'boolean') {
          setFeedbackStats({ labels: res.labels, calibrated: res.calibrated });
        }
      })
      .catch(() => {
        // The footer is optional sugar: a stats failure never surfaces.
      });
    return () => {
      alive = false;
    };
  }, [resolvedApi]);

  // ---- review selection: always a valid row once candidates exist ----------
  useEffect(() => {
    setSelectedId((cur) => (cur && items.some((i) => i.id === cur) ? cur : (items[0]?.id ?? null)));
  }, [items]);

  // ---- P4 §8d: hydrate the brand kit from settings (tolerate absent keys) ---
  // settings.get is free-form (C12); missing keys default to '' via
  // readBrandSettings. A failure leaves the empty kit rather than blocking.
  useEffect(() => {
    // resolvedApi is always present; defensive guard for a missing bridge.
    /* v8 ignore next */
    if (!resolvedApi) return undefined;
    let alive = true;
    Promise.resolve(resolvedApi.rpc<Record<string, unknown>>('settings.get'))
      .then((res) => {
        if (alive) setBrand(readBrandSettings(res));
      })
      .catch(() => {
        // No settings store -> keep the empty brand kit.
      });
    return () => {
      alive = false;
    };
  }, [resolvedApi]);

  // ---- DATA ROOT: hydrate the current data folder from the preload bridge ----
  // getDataFolder is a MAIN-process call (not a sidecar RPC). A missing bridge
  // (older preload / test stub) or a failure leaves the section in its
  // "Unavailable" state — never blocks the panel.
  useEffect(() => {
    if (typeof resolvedApi?.getDataFolder !== 'function') {
      setDataFolderLoaded(true);
      return undefined;
    }
    let alive = true;
    Promise.resolve(resolvedApi.getDataFolder())
      .then((folder) => {
        if (alive) setDataFolder(folder || null);
      })
      .catch(() => {
        // Bridge present but failed -> show "Unavailable" rather than blocking.
      })
      .finally(() => {
        if (alive) setDataFolderLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [resolvedApi]);

  // DATA ROOT: open the native directory picker, persist the choice to the
  // marker, and flag a restart. We optimistically show the chosen path so the
  // user sees what WILL apply (the live root only changes on the next launch).
  const changeDataFolder = useCallback(async () => {
    if (
      typeof resolvedApi?.pickDataFolder !== 'function' ||
      typeof resolvedApi?.setDataFolder !== 'function'
    ) {
      setError('Data-folder picker is unavailable (preload bridge not wired).');
      return;
    }
    try {
      const chosen = await resolvedApi.pickDataFolder();
      if (!chosen) return; // user cancelled
      const res = await resolvedApi.setDataFolder(chosen);
      if (!res.ok) {
        setError('Could not save the data folder (the install directory may be read-only).');
        return;
      }
      setDataFolder(chosen);
      setDataFolderPendingRestart(true);
    } catch (e) {
      setError(errMsg(e));
    }
  }, [resolvedApi]);

  // ---- P4 §5: word-level cues for the live caption overlay -----------------
  // captions.cues returns SOURCE-absolute word cues; the overlay re-bases them
  // to the preview window. Optional sugar: a failure leaves the overlay caption-
  // less (the preview still plays) rather than blocking the review loop.
  useEffect(() => {
    if (!resolvedApi || !videoId) return undefined;
    let alive = true;
    Promise.resolve(resolvedApi.rpc<{ cues?: Cue[] }>('captions.cues', { videoId }))
      .then((res) => {
        if (alive && res && Array.isArray(res.cues)) setCues(res.cues);
      })
      .catch(() => {
        // No cues -> the overlay simply shows the hook title only.
      });
    return () => {
      alive = false;
    };
  }, [resolvedApi, videoId]);

  // ---- P4 §5: preview-remount fix (see the root-cause note above) ----------
  // Check media.playable; while not playable, re-poll it on each job.done and
  // remount the preview Player (epoch bump) once it becomes playable — WITHOUT
  // starting a second proxy build (Workspace owns that).
  useEffect(() => {
    if (!resolvedApi || !videoId) return undefined;
    let alive = true;
    let offDone: (() => void) | null = null;
    Promise.resolve(resolvedApi.rpc<PlayableResult>('media.playable', { videoId }))
      .then((v) => {
        if (!alive || !v || v.playable) return; // already playable: nothing to do
        if (typeof resolvedApi.onJobDone !== 'function') return;
        offDone = resolvedApi.onJobDone(() => {
          // Any job finished — re-poll: the Workspace proxy build may have made
          // the source playable. Bump the epoch (remount) only on the flip.
          Promise.resolve(resolvedApi.rpc<PlayableResult>('media.playable', { videoId }))
            .then((again) => {
              if (alive && again && again.playable) setPlayerEpoch((n) => n + 1);
            })
            .catch(() => undefined);
        });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (offDone) offDone();
    };
  }, [resolvedApi, videoId]);

  // Reset the playhead when the previewed candidate changes (overlay re-bases).
  useEffect(() => {
    setCurrentTime(0);
  }, [selectedId]);

  const setControl = useCallback(
    <K extends keyof ShortMakerControls>(key: K, value: ShortMakerControls[K]) => {
      setControls((prev) => {
        const next = { ...prev, [key]: value };
        // P4 §8a: when the user picks a new caption style, SEED the emphasis
        // control from that style's per-style default (the renderer mirror of the
        // sidecar `default_emphasis_for_style`) so the picker reflects what would
        // actually render — ON for OpusClip-style templates, OFF for clean/minimal
        // — while still letting the user toggle it back afterwards. We resolve to
        // an explicit 'on'/'off' (not 'default') so the value is visible and an
        // explicit choice flows into buildExportParams.
        if (key === 'captionStyle') {
          next.emphasis = defaultEmphasisForStyle(String(value)) ? 'on' : 'off';
        }
        return sanitizeControls(next);
      });
    },
    [],
  );

  // ---- P4 §8c: platform preset (sets aspect/maxSec/count, keeps the rest) ---
  const applyPlatformPreset = useCallback((presetId: string) => {
    setControls((prev) => applyPreset(prev, presetId));
  }, []);

  // ---- P4 §8d: brand kit edit + persist (best-effort settings.set) ----------
  // Each edit updates the in-memory kit immediately, then persists ONLY the
  // three FROZEN keys. Persistence is best-effort: a failure surfaces an error
  // but never reverts the local edit (the user can retry).
  const setBrandField = useCallback(
    (key: keyof BrandSettings, value: string) => {
      setBrand((prev) => {
        const next = { ...prev, [key]: value };
        if (resolvedApi && typeof resolvedApi.rpc === 'function') {
          Promise.resolve(resolvedApi.rpc('settings.set', brandSettingsPatch(next))).catch((e) => {
            setError(errMsg(e));
          });
        }
        return next;
      });
    },
    [resolvedApi],
  );

  // P4 §8d: open the native logo picker (preload bridge) and persist the choice.
  const pickLogo = useCallback(async () => {
    if (typeof resolvedApi?.pickLogoFile !== 'function') {
      setError('Logo picker is unavailable (preload pickLogoFile bridge not wired).');
      return;
    }
    try {
      const path = await resolvedApi.pickLogoFile();
      if (path) setBrandField('brandLogoPath', path);
    } catch (e) {
      setError(errMsg(e));
    }
  }, [resolvedApi, setBrandField]);

  // ---- select / regenerate ------------------------------------------------
  const runSelect = useCallback(async () => {
    // resolvedApi is always present; the submit button is disabled while busy.
    /* v8 ignore next */
    if (!resolvedApi || busy) return;
    setError(null);
    setRetryAction(null);
    setExportedClips(null);
    setProgress({ jobId: '', pct: 0, message: 'Selecting candidates…' });
    setPhase('selecting');
    const clean = sanitizeControls(controls);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const res = await resolvedApi.rpc<SelectResult | JobHandle>('shortmaker.select', {
        videoId,
        prompt,
        controls: clean,
      });
      let candidates = extractCandidates(res);
      if (candidates === null && isJobHandle(res)) {
        activeJobRef.current = res.jobId;
        // Deferred job: wait for job.done if a hook exists, else the rpc already
        // resolved above with the handle — fall through with empty list. F2: the
        // wait carries a timeout + the cancel/unmount AbortSignal.
        candidates = await waitForJobDone(
          resolvedApi,
          res.jobId,
          extractCandidates,
          EXPORT_JOB_TIMEOUT_MS,
          ctrl.signal,
        );
      }
      if (candidates === null) candidates = [];
      // Bug-sweep: a synchronously-resolved select must still honor a mid-flight
      // Cancel. The abort signal is only checked inside waitForJobDone, so without
      // this a cancel during the (non-job) sync path would still load results and
      // override the idle reset. Treat it as a clean cancel (the catch returns).
      if (ctrl.signal.aborted) throw new JobAbortedError();
      dispatch({ type: 'load', candidates });
      setPhase('reviewing');
    } catch (e) {
      // F2: an aborted wait is a clean cancel — cancel() already reset to idle.
      if (e instanceof JobAbortedError) return;
      setError(errMsg(e));
      setRetryAction('select');
      setPhase('idle');
    } finally {
      activeJobRef.current = null;
      abortRef.current = null;
      setProgress(null);
    }
  }, [resolvedApi, busy, controls, videoId, prompt]);

  // ---- review actions (all non-destructive) -------------------------------
  // P3-D: each decision doubles as an implicit taste label — fire-and-forget
  // feedback.record with the candidate AS REVIEWED (current, possibly nudged).
  const approve = useCallback(
    (id: string) => {
      dispatch({ type: 'approve', id });
      const it = items.find((i) => i.id === id);
      if (it) recordFeedback(resolvedApi, videoId, it.current, 'approved');
    },
    [items, resolvedApi, videoId],
  );
  const discard = useCallback(
    (id: string) => {
      dispatch({ type: 'discard', id });
      const it = items.find((i) => i.id === id);
      if (it) recordFeedback(resolvedApi, videoId, it.current, 'discarded');
    },
    [items, resolvedApi, videoId],
  );
  const reinstate = useCallback((id: string) => dispatch({ type: 'pending', id }), []);
  const nudge = useCallback(
    (id: string, deltaStart: number, deltaEnd: number) => {
      dispatch({ type: 'nudge', id, deltaStart, deltaEnd });
      const it = items.find((i) => i.id === id);
      // Record the POST-nudge boundaries (what the user steered toward).
      if (it) {
        recordFeedback(
          resolvedApi,
          videoId,
          nudgeCandidate(it.current, deltaStart, deltaEnd),
          'nudged',
        );
      }
    },
    [items, resolvedApi, videoId],
  );
  const reset = useCallback((id: string) => dispatch({ type: 'reset', id }), []);

  const approved = useMemo(() => approvedIds(items), [items]);

  // ---- P4 §6 / C11: per-video produced-shorts (enriched card actions) ------
  // The list + the play/open-folder/re-export/delete handlers live in a small
  // feature hook; `reloadVideoShorts` is wired into the export/batch flows below
  // so the exported clips gain the gallery card actions after each export.
  const {
    videoShorts,
    playingShortPath,
    reloadVideoShorts,
    playShort,
    openShortFolder,
    reexportShort,
    deleteShort,
  } = useShortsGallery({ resolvedApi, videoId, setError, onReexport });

  // ---- export (only explicitly-approved; nothing auto-exports) ------------
  const runExport = useCallback(async () => {
    // resolvedApi is always present; the export button is disabled while busy.
    /* v8 ignore next */
    if (!resolvedApi || busy) return;
    const ids = approvedIds(items);
    // The export button is also disabled with 0 approved, so this guard is defensive.
    /* v8 ignore next 4 */
    if (ids.length === 0) {
      setError('Approve at least one clip before exporting.');
      return;
    }
    setError(null);
    setRetryAction(null);
    setProgress({ jobId: '', pct: 0, message: 'Exporting approved clips…' });
    setPhase('exporting');
    const clean = sanitizeControls(controls);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      // §2 sends `candidateIds`; the sidecar resolves them against its cached
      // select result. We ALSO forward the full approved `candidates` objects
      // (we have them via approvedCandidates) so export still resolves real clips
      // even if the server-side selection cache was lost (e.g. a sidecar restart)
      // — the sidecar's _resolve_candidates prefers an inline `candidates` list.
      // (INTEGRATION-REPORT HIGH-3: ids alone were unsatisfiable.)
      // T4b: the caption style + reframe engine override flow into export as
      // OPTIONAL params (consumed sidecar-side per WIRING-T4B.md; the current
      // export handler safely ignores unknown params until that patch lands).
      // A2: audioTrackId is included ONLY when a track is chosen ("Original"
      // sends nothing — the sidecar keeps each clip's own audio).
      // P3: hookTitle + removeFillers flow into export exactly like
      // captionStyle/reframeEngine already do (frozen P3 mini-contract).
      const res = await resolvedApi.rpc<ExportResult | JobHandle>(
        'shortmaker.export',
        buildExportParams(videoId, approvedCandidates(items), clean, audioTrackId),
      );
      let clips = extractClips(res);
      if (clips === null && isJobHandle(res)) {
        activeJobRef.current = res.jobId;
        // F2: race the wait against a timeout (and the cancel/unmount signal) so a
        // dead sidecar surfaces a user-facing error instead of hanging the UI.
        clips = await waitForJobDone(
          resolvedApi,
          res.jobId,
          extractClips,
          EXPORT_JOB_TIMEOUT_MS,
          ctrl.signal,
        );
      }
      setExportedClips(clips ?? []);
      // P3-D: a successful export is the strongest implicit label — record
      // one 'exported' action per exported candidate (fire-and-forget).
      for (const c of approvedCandidates(items)) {
        recordFeedback(resolvedApi, videoId, c, 'exported');
      }
      // P4 §6 / C11: reload the produced-shorts list for this video so the
      // exported clips gain the gallery card actions (fire-and-forget).
      void reloadVideoShorts();
      setPhase('reviewing');
    } catch (e) {
      // F2: an aborted wait is a clean cancel — cancel() already reset to idle.
      if (e instanceof JobAbortedError) return;
      setError(errMsg(e));
      setRetryAction('export');
      setPhase('reviewing');
    } finally {
      activeJobRef.current = null;
      abortRef.current = null;
      setProgress(null);
    }
  }, [resolvedApi, busy, items, videoId, controls, audioTrackId, reloadVideoShorts]);

  // ---- P4 §8c: unattended batch "Make N" ----------------------------------
  // Runs the existing RPC flow end-to-end with no manual review:
  //   shortmaker.select -> auto-approve the top N by viralityPct (topByVirality)
  //   -> shortmaker.export. Progress shows through the same setProgress channel.
  // The selected candidates are ALSO loaded into the review list so the user can
  // inspect/adjust afterwards; nothing is destructive.
  const runBatch = useCallback(async () => {
    // resolvedApi/videoId are always present; the batch button is disabled while busy.
    /* v8 ignore next */
    if (!resolvedApi || busy || !videoId) return;
    setError(null);
    setRetryAction(null);
    setExportedClips(null);
    const clean = sanitizeControls(controls);
    setPhase('selecting');
    setProgress({ jobId: '', pct: 0, message: `Finding the top ${clean.count} clips…` });
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const selRes = await resolvedApi.rpc<SelectResult | JobHandle>('shortmaker.select', {
        videoId,
        prompt,
        controls: clean,
      });
      // F2: select also carries a timeout + the cancel/unmount AbortSignal.
      const found = await resolveJobResult(
        resolvedApi,
        selRes,
        extractCandidates,
        activeJobRef,
        EXPORT_JOB_TIMEOUT_MS,
        ctrl.signal,
      );
      const candidates = found ?? [];
      dispatch({ type: 'load', candidates }); // surface for post-hoc review
      const top = topByVirality(candidates, clean.count);
      if (top.length === 0) {
        // F1: a confirmed zero-result is NOT an error — fall through to the
        // "No candidates were proposed" empty state (no error/Retry surfaced).
        setPhase('reviewing');
        return;
      }
      for (const c of top) dispatch({ type: 'approve', id: candidateId(c) });
      setPhase('exporting');
      setProgress({ jobId: '', pct: 0, message: `Exporting ${top.length} clips…` });
      const expRes = await resolvedApi.rpc<ExportResult | JobHandle>(
        'shortmaker.export',
        buildExportParams(videoId, top, clean, audioTrackId),
      );
      const clips = await resolveJobResult(
        resolvedApi,
        expRes,
        extractClips,
        activeJobRef,
        EXPORT_JOB_TIMEOUT_MS,
        ctrl.signal,
      );
      setExportedClips(clips ?? []);
      for (const c of top) recordFeedback(resolvedApi, videoId, c, 'exported');
      void reloadVideoShorts();
      setPhase('reviewing');
    } catch (e) {
      // F2: an aborted wait is a clean cancel — cancel() already reset to idle.
      if (e instanceof JobAbortedError) return;
      setError(errMsg(e));
      setRetryAction('batch');
      setPhase('reviewing');
    } finally {
      activeJobRef.current = null;
      abortRef.current = null;
      setProgress(null);
    }
  }, [resolvedApi, busy, videoId, prompt, controls, audioTrackId, reloadVideoShorts]);

  // F2: abort any in-flight job.done wait (cancel/unmount) so the wait rejects
  // with JobAbortedError and its subscription/timer tear down instead of leaking.
  const tearDownWait = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  // ---- cancel the active job ----------------------------------------------
  // F2: ALWAYS resets to idle (tears down the wait + clears progress) regardless
  // of whether a job.done ever arrives — cancelled jobs emit none, so without
  // this the UI would wedge in 'selecting'/'exporting' forever. The aborted wait
  // rejects with JobAbortedError, which the run loops swallow (a clean cancel).
  const cancel = useCallback(async () => {
    const jobId = activeJobRef.current;
    tearDownWait();
    setPhase('idle');
    setProgress(null);
    // The Cancel button renders only while busy with an active job; defensive guard.
    /* v8 ignore next */
    if (!resolvedApi || !jobId) return;
    try {
      await resolvedApi.rpc('job.cancel', { jobId });
    } catch (e) {
      setError(errMsg(e));
    }
  }, [resolvedApi, tearDownWait]);

  // ---- F1 retry: re-run the failed operation ------------------------------
  const retry = useCallback(() => {
    if (retryAction === 'select') void runSelect();
    else if (retryAction === 'batch') void runBatch();
    else void runExport(); // retryAction === 'export' (the only remaining value)
  }, [retryAction, runSelect, runBatch, runExport]);

  // F2: tear down any in-flight job wait when the panel unmounts (no leak).
  useEffect(() => tearDownWait, [tearDownWait]);

  // ---- keyboard review (T6) -------------------------------------------------
  const selected = useMemo(
    () => items.find((i) => i.id === selectedId) ?? null,
    [items, selectedId],
  );

  // P4 §7: the DISPLAY order of the candidate list (the ids are unchanged, so
  // selection + keyboard nav still address the same items). J/K navigate the
  // sorted order — see moveSelection consumers.
  const sortedItems = useMemo(() => sortReviewItems(items, sortMode), [items, sortMode]);

  // Active ONLY while focus is inside the review group (the handler lives on
  // that focusable container, so events elsewhere never reach it). Text-entry
  // targets and modified chords are left alone.
  function handleReviewKeys(e: React.KeyboardEvent<HTMLDivElement>): void {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (e.target as HTMLElement).tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    switch (e.key) {
      case 'j':
      case 'J':
        e.preventDefault();
        // J/K follow the on-screen order (P4 §7 sort), not the raw rank order.
        setSelectedId((cur) => moveSelection(sortedItems, cur, +1));
        break;
      case 'k':
      case 'K':
        e.preventDefault();
        setSelectedId((cur) => moveSelection(sortedItems, cur, -1));
        break;
      case ' ': {
        e.preventDefault(); // Space must toggle playback, never scroll
        const player = playerRef.current;
        if (player) {
          if (player.isPlaying()) player.pause();
          else player.play();
        }
        break;
      }
      case 'a':
      case 'A':
        e.preventDefault();
        if (selectedId) approve(selectedId);
        break;
      case 'x':
      case 'X':
        e.preventDefault();
        if (selectedId) discard(selectedId);
        break;
      case 'ArrowLeft':
      case 'ArrowRight': {
        e.preventDefault(); // arrows nudge the window, never scroll
        if (selectedId) {
          const step = e.shiftKey ? NUDGE_FINE_SEC : NUDGE_COARSE_SEC;
          const delta = e.key === 'ArrowLeft' ? -step : step;
          // Slide the whole window (start AND end) — re-snap, not re-select.
          nudge(selectedId, delta, delta);
        }
        break;
      }
      default:
        break;
    }
  }

  // ---- render -------------------------------------------------------------
  return (
    <section className="shortmaker" aria-label="Short maker">
      <h2>Short-maker</h2>

      <ShortMakerControlsPanel
        videoId={videoId}
        prompt={prompt}
        controls={controls}
        audioTracks={audioTracks}
        audioTrackId={audioTrackId}
        busy={busy}
        hasCandidates={phase === 'reviewing' && items.length > 0}
        setPrompt={setPrompt}
        setControl={setControl}
        setAudioTrackId={setAudioTrackId}
        applyPlatformPreset={applyPlatformPreset}
        onSubmit={() => void runSelect()}
        onBatch={() => void runBatch()}
        onCancel={() => void cancel()}
      />

      {/* P4 §8d: brand kit — logo watermark + default caption template/font,
          persisted via settings.set (tolerant load via settings.get). */}
      <ShortMakerBrandKit
        brand={brand}
        open={brandOpen}
        onToggle={() => setBrandOpen((v) => !v)}
        onPickLogo={() => void pickLogo()}
        setBrandField={setBrandField}
        dataFolder={dataFolder}
        dataFolderLoaded={dataFolderLoaded}
        dataFolderPendingRestart={dataFolderPendingRestart}
        onChangeDataFolder={() => void changeDataFolder()}
      />

      {error && (
        <div className="sm-error" role="alert">
          <span className="sm-error-message">{error}</span>
          {retryAction && (
            <button type="button" className="secondary sm-retry" onClick={retry}>
              Retry
            </button>
          )}
        </div>
      )}

      {busy && progress && (
        <div className="sm-progress" role="status" aria-live="polite">
          <progress max={100} value={displayPct(progress.pct)} />
          <span>
            {displayPct(progress.pct)}% {progress.message ?? ''}
          </span>
        </div>
      )}

      {phase === 'reviewing' && items.length === 0 && !busy && !error && (
        <div className="sm-empty">
          <div className="sm-empty__poster" aria-hidden="true">
            <span className="sm-empty__glyph">▶</span>
          </div>
          <p className="sm-empty__title">No candidates were proposed</p>
          <p className="sm-empty__hint">Adjust the prompt or controls and retry.</p>
        </div>
      )}

      <CandidateReview
        items={items}
        selectedId={selectedId}
        selected={selected}
        controls={controls}
        videoId={videoId}
        cues={cues}
        currentTime={currentTime}
        playerEpoch={playerEpoch}
        sortMode={sortMode}
        playerRef={playerRef}
        onKeyDown={handleReviewKeys}
        onTimeUpdate={setCurrentTime}
        setSortMode={setSortMode}
        setSelectedId={setSelectedId}
        onApprove={approve}
        onDiscard={discard}
        onReinstate={reinstate}
        onNudge={nudge}
        onReset={reset}
      />

      {items.length > 0 && (
        <div className="sm-export">
          <span aria-label="Approved count">{approved.length} approved</span>
          <button
            type="button"
            onClick={() => void runExport()}
            disabled={busy || approved.length === 0}
          >
            Export approved
          </button>
        </div>
      )}

      {exportedClips && (
        <div className="sm-exported" role="status">
          <h3>Exported {exportedClips.length} clip(s)</h3>
          <ul>
            {exportedClips.map((c, i) => (
              <li key={`${c.path}-${i}`}>
                {c.path}
                {typeof c.fillersRemoved === 'number' && (
                  <span className="sm-fillers" aria-label="Fillers removed">
                    {' '}
                    removed {c.fillersRemoved} fillers ({(c.fillerSeconds ?? 0).toFixed(1)}s)
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* P4 §6 / C11: the produced shorts FOR THIS VIDEO with gallery card
          actions (play / open-folder / re-export / delete). Reloaded after every
          export via shorts.list {videoId}; absent until at least one export. */}
      <ProducedShorts
        shorts={videoShorts}
        playingShortPath={playingShortPath}
        onPlay={playShort}
        onOpenFolder={(p) => void openShortFolder(p)}
        onReexport={(p) => void reexportShort(p)}
        onDelete={(p) => void deleteShort(p)}
      />

      {/* P3-D: the taste-profile footer (quiet; hidden until stats resolve). */}
      {feedbackStats && (
        <p className="sm-feedback-stats" aria-label="Taste profile">
          {tasteProfileLine(feedbackStats)}
        </p>
      )}
    </section>
  );
}

export default ShortMaker;
