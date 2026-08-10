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
import { reframeDegradedNotice } from '../lib/reframeDegraded';
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
  CAPTION_STYLE_OPTIONS,
  DEFAULT_CAPTION_STYLE,
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
  type ExportOutputOptions,
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
  type ExportOutputOptions,
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
  /**
   * F45 / P4 §4 — the caption POSITION box + the subtitle DELIVERY mode + the
   * V1.1 caption OVERRIDE chosen on the HOST surface (Make Shorts' caption editor
   * and Output Tray). Forwarded verbatim to `buildExportParams` at BOTH export
   * call sites (review and unattended batch). Read at export time, not at mount,
   * so a mid-session change is honoured. Omitted (standalone/tests) => the export
   * payload carries none of those keys, exactly as before.
   */
  output?: ExportOutputOptions;
}

type Phase = 'idle' | 'selecting' | 'reviewing' | 'exporting';

export function ShortMaker({
  videoId,
  api,
  initialControls,
  onReexport,
  // NOT defaulted to `{}` on purpose: `buildExportParams`'s own `output = {}`
  // default already tolerates `undefined`, so leaving it undefined adds no branch.
  output,
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

  // ---- LANE OWNERSHIP ------------------------------------------------------
  // `activeJobRef`, `abortRef` and `progress` are ONE slot each, shared by all
  // three run loops — a single visible lane. The reset effect below leaves
  // `phase` at 'idle' after a video switch, so the user CAN start a second job
  // while the first is still in flight (up to EXPORT_JOB_TIMEOUT_MS = 35 min),
  // and the first job then settles into a lane the second one owns.
  //
  // So every lane write is scoped to its owner: `abortRef` holds exactly one
  // controller — the current owner's — which makes `abortRef.current === ctrl`
  // the ownership test. Without it, video 1's settle-time teardown cleared all
  // three slots and (measured) video 2's progress bar never returned for the
  // rest of its job, its Cancel emitted no `job.cancel` because the handle it
  // reads had been nulled, and video 1's own in-flight events were relayed onto
  // video 2's bar once video 1's late handle won the single slot.
  //
  // A non-owning `finally` may safely skip the teardown because the handle slot
  // is re-initialised by whichever run takes the lane NEXT, and while no run owns
  // the lane nothing can read it: both the progress relay and the Cancel button
  // are gated on `busy`, which is false outside a run.
  //
  // Not closed by this (single-lane by design, disclosed rather than widened):
  // a job for a video that is NOT on screen is invisible — its progress fails
  // the relay filter and `busy` is false — and it cannot be cancelled from the
  // UI, because Cancel addresses the visible lane. The work still completes
  // sidecar-side and its files still land; only the on-screen receipt is
  // dropped (see the guard-the-write-not-the-work note in runBatch).
  const busy = phase === 'selecting' || phase === 'exporting';

  // ---- progress wiring ----------------------------------------------------
  useEffect(() => {
    // resolvedApi is always present (prop or window.api) and exposes onProgress,
    // so this guard is defensive against a malformed bridge.
    /* v8 ignore next */
    if (!resolvedApi || typeof resolvedApi.onProgress !== 'function') return;
    const off = resolvedApi.onProgress((p) => {
      const active = activeJobRef.current;
      // Once the active jobId is known, relay only that job's progress. Before it
      // is known (sync / pre-handle window), accept ONLY jobId-less early progress
      // ('') so a concurrent job's real-jobId events cannot hijack the bar.
      if (active ? p.jobId !== active : p.jobId !== '') return;
      setProgress(p);
    });
    return off;
  }, [resolvedApi]);

  // ---- reset per-video review state on videoId change ----------------------
  // The panel stays MOUNTED across a video switch (the parent swaps only the
  // videoId prop), so without this the previous video's candidate list, exported
  // clips, phase, prompt and audio-track choice persist — and "Export approved"
  // would carve the NEW video at the OLD video's timestamps. Clear ONLY per-video
  // review state (NOT app-level controls/brand/data-folder). Every reset is
  // idempotent against the initial state, so it is a harmless no-op on first mount.
  //
  // The reset alone is NOT sufficient. It closes the AFTER case (a job settles,
  // THEN the user switches) but not the IN-FLIGHT one: shortmaker.select and
  // shortmaker.export are DEFERRED jobs awaited for up to EXPORT_JOB_TIMEOUT_MS
  // (35 min, _api.ts:62), this effect does NOT abort `abortRef.current` (only
  // Cancel/unmount does), and each run loop closes over the videoId it started
  // on. So a switch during those 35 minutes runs this reset FIRST and the
  // in-flight job's own writes land AFTER it — re-creating the defect one seam
  // over (measured: v1's clip paths rendered as v2's `.sm-exported` receipt, v1's
  // candidates loaded into v2's review list, and `shorts.list {videoId:v1}`
  // populating the gallery shown under v2). `videoIdRef` is the other half: it
  // mirrors the COMMITTED prop so a settled job can ask "am I still the selected
  // video?" before writing. Kept as a ref rather than read from the closure
  // because the closure is frozen at start-of-job. This mirrors the same
  // guard-the-write fix in views/MakeShorts.tsx:184-191 for the manual path.
  const videoIdRef = useRef(videoId);
  useEffect(() => {
    videoIdRef.current = videoId;
    dispatch({ type: 'clear' });
    setExportedClips(null);
    setPhase('idle');
    setRetryAction(null);
    setError(null);
    setAudioTrackId('');
    setSelectedId(null);
    setPrompt('');
  }, [videoId]);

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
        if (alive) {
          const brandKit = readBrandSettings(res);
          setBrand(brandKit);
          // P4 §8d: seed the Caption style control from the persisted brand
          // default so a brand template flows through buildExportParams — but
          // ONLY while the control is still at the picker DEFAULT. The
          // `prev.captionStyle === DEFAULT_CAPTION_STYLE` guard is load-bearing:
          // it must never clobber an explicit user pick if settings.get resolves
          // late. Immutable update returns a NEW controls object.
          const tpl = (brandKit.brandCaptionTemplate || '').trim();
          if (tpl && CAPTION_STYLE_OPTIONS.includes(tpl)) {
            setControls((prev) =>
              prev.captionStyle === DEFAULT_CAPTION_STYLE
                ? sanitizeControls({
                    ...prev,
                    captionStyle: tpl,
                    emphasis: defaultEmphasisForStyle(tpl) ? 'on' : 'off',
                  })
                : prev,
            );
          }
        }
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
              if (alive && again && again.playable) {
                setPlayerEpoch((n) => n + 1);
                // Latch on the flip: tear THIS subscription down so later job.done
                // events (a subsequent export, a transcribe, another video's jobs)
                // can never re-poll media.playable or re-bump the epoch — which
                // would reload/interrupt the in-progress candidate preview.
                if (offDone) {
                  offDone();
                  offDone = null;
                }
              }
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
    // The video this run is FOR. Every settle-time write below is a factual claim
    // about THIS id, so each is gated on the selection still being it when the job
    // finishes (see `videoIdRef` above). Switching away and back re-admits the
    // writes — by then they describe the selected video again, which is the
    // truthful outcome, not a stale one.
    const startedFor = videoId;
    setError(null);
    setRetryAction(null);
    setExportedClips(null);
    setProgress({ jobId: '', pct: 0, message: 'Selecting candidates…' });
    setPhase('selecting');
    const clean = sanitizeControls(controls);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // This run is the new lane owner and has no handle yet, so drop any previous
    // owner's. The relay's documented pre-handle rule ("accept ONLY jobId-less
    // early progress") only actually holds while this slot is null.
    activeJobRef.current = null;
    try {
      const res = await resolvedApi.rpc<SelectResult | JobHandle>('shortmaker.select', {
        videoId,
        prompt,
        controls: clean,
      });
      let candidates = extractCandidates(res);
      if (candidates === null && isJobHandle(res)) {
        // LANE OWNERSHIP (see above): a second job may have started during this
        // rpc. Claiming the handle then would point the progress relay and Cancel
        // at THIS job instead of the visible one.
        if (abortRef.current === ctrl) activeJobRef.current = res.jobId;
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
      // The user may have switched the picker during the wait. Loading v1's
      // candidates into v2's review list is the WORST case in this family: the
      // list is what "Export approved" carves from, so it would export the NEW
      // video at the OLD video's timestamps — the exact hazard the reset effect's
      // own comment names. Drop the load rather than mis-attribute it.
      if (videoIdRef.current !== startedFor) return;
      dispatch({ type: 'load', candidates });
      setPhase('reviewing');
    } catch (e) {
      // F2: an aborted wait is a clean cancel — cancel() already reset to idle.
      if (e instanceof JobAbortedError) return;
      // Same rule for the failure half — v1's error is not v2's, and its Retry
      // would re-run against the newly selected video.
      if (videoIdRef.current !== startedFor) return;
      setError(errMsg(e));
      setRetryAction('select');
      setPhase('idle');
    } finally {
      // LANE OWNERSHIP (see above): only the current owner tears the lane down.
      if (abortRef.current === ctrl) {
        activeJobRef.current = null;
        abortRef.current = null;
        setProgress(null);
      }
    }
  }, [resolvedApi, busy, controls, videoId, prompt]);

  // ---- review actions (all non-destructive) -------------------------------
  // P3-D: each decision doubles as an implicit taste label — fire-and-forget
  // feedback.record with the candidate AS REVIEWED (current, possibly nudged).
  //
  // These three send the CURRENT `videoId` prop with the CURRENT `items` entry, so
  // unlike the export label below they are only correct while `items` belongs to
  // the selected video. On main they were genuinely MIS-ATTRIBUTABLE: the
  // stale-select path loaded v1's candidates into v2's review list, and clicking
  // Approve then sent `feedback.record {videoId: 'v2'}` carrying v1's `start`
  // (measured on main; silent post-fix). Nothing here changed — the fix is
  // UPSTREAM, in runSelect/runBatch, which now never load another video's
  // candidates. Do not "fix" this by freezing videoId in the closure: that would
  // paper over a stale list instead of preventing it.
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
    // W04: the hook owns the themed delete gate but cannot mount it — this
    // container renders it beside the gallery it guards.
    confirmDialog: shortsConfirmDialog,
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
    // See `runSelect` above: the video this export is a receipt FOR.
    const startedFor = videoId;
    setError(null);
    setRetryAction(null);
    setProgress({ jobId: '', pct: 0, message: 'Exporting approved clips…' });
    setPhase('exporting');
    const clean = sanitizeControls(controls);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // See runSelect: the new owner starts with no handle (LANE OWNERSHIP above).
    activeJobRef.current = null;
    try {
      // §2 sends `candidateIds`; the sidecar resolves them against its cached
      // select result. We ALSO forward the full approved `candidates` objects
      // (we have them via approvedCandidates) so export still resolves real clips
      // even if the server-side selection cache was lost (e.g. a sidecar restart)
      // — the sidecar's _resolve_candidates prefers an inline `candidates` list.
      // (INTEGRATION-REPORT HIGH-3: ids alone were unsatisfiable.)
      // T4b: the caption style + reframe engine override flow into export as
      // OPTIONAL params (consumed sidecar-side per docs/wiring/WIRING-T4B.md; the current
      // export handler safely ignores unknown params until that patch lands).
      // A2: audioTrackId is included ONLY when a track is chosen ("Original"
      // sends nothing — the sidecar keeps each clip's own audio).
      // P3: hookTitle + removeFillers flow into export exactly like
      // captionStyle/reframeEngine already do (frozen P3 mini-contract).
      const res = await resolvedApi.rpc<ExportResult | JobHandle>(
        'shortmaker.export',
        // F45: `output` carries the host surface's caption position + subtitle
        // delivery + override. Without it the AI path silently dropped all three.
        buildExportParams(videoId, approvedCandidates(items), clean, audioTrackId, output),
      );
      let clips = extractClips(res);
      if (clips === null && isJobHandle(res)) {
        // LANE OWNERSHIP (see above): mirror runSelect — a handle that arrives
        // after a second job started must not claim the visible lane.
        if (abortRef.current === ctrl) activeJobRef.current = res.jobId;
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
      // Bug-sweep: mirror runSelect's guard — a synchronously-resolved export must
      // still honor a mid-flight Cancel. The abort signal is only checked inside
      // waitForJobDone (skipped on the sync path), so without this a cancel during
      // the sync path would still load clips and record 'exported' feedback,
      // overriding the idle reset. Treat it as a clean cancel (the catch returns).
      if (ctrl.signal.aborted) throw new JobAbortedError();
      // P3-D: a successful export is the strongest implicit label — record
      // one 'exported' action per exported candidate (fire-and-forget).
      //
      // DELIBERATELY ABOVE the stale guard, and NOT gated by it: `videoId` and
      // `items` here are the CLOSURE's (frozen at export start), so each label is
      // correctly attributed to the video that was actually exported, and this
      // writes no component state. Dropping it after a mid-flight switch would
      // lose a TRUE label rather than prevent a false claim. (Moving it above the
      // guard leaves the RPC order unchanged: export -> feedback.record ->
      // shorts.list.) This is the honest counterpart to the single-lane busy flag
      // that views/MakeShorts.tsx:293-297 leaves unguarded for the same reason.
      //
      // SCOPE: that holds for THIS label only, because its arguments are frozen.
      // It is NOT a claim that feedback.record was never mis-attributed — the
      // review-action labels (see the note at `approve` above) were, on main.
      for (const c of approvedCandidates(items)) {
        recordFeedback(resolvedApi, videoId, c, 'exported');
      }
      // The user may have switched the picker during the wait: this receipt then
      // describes a video that is no longer on screen. Both writes below are
      // claims about the CURRENTLY selected video — `exportedClips` renders as its
      // `.sm-exported` file list, and `reloadVideoShorts` resolves `shorts.list`
      // for the OLD id into the produced-shorts gallery shown under the NEW one.
      if (videoIdRef.current !== startedFor) return;
      setExportedClips(clips ?? []);
      // P4 §6 / C11: reload the produced-shorts list for this video so the
      // exported clips gain the gallery card actions (fire-and-forget).
      void reloadVideoShorts();
      setPhase('reviewing');
    } catch (e) {
      // F2: an aborted wait is a clean cancel — cancel() already reset to idle.
      if (e instanceof JobAbortedError) return;
      // Same rule for the failure half — v1's error is not v2's.
      if (videoIdRef.current !== startedFor) return;
      setError(errMsg(e));
      setRetryAction('export');
      setPhase('reviewing');
    } finally {
      // LANE OWNERSHIP (see above): only the current owner tears the lane down.
      if (abortRef.current === ctrl) {
        activeJobRef.current = null;
        abortRef.current = null;
        setProgress(null);
      }
    }
  }, [resolvedApi, busy, items, videoId, controls, audioTrackId, output, reloadVideoShorts]);

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
    // See `runSelect` above: the video this batch is a receipt FOR.
    const startedFor = videoId;
    setError(null);
    setRetryAction(null);
    setExportedClips(null);
    const clean = sanitizeControls(controls);
    setPhase('selecting');
    setProgress({ jobId: '', pct: 0, message: `Finding the top ${clean.count} clips…` });
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    // See runSelect: the new owner starts with no handle (LANE OWNERSHIP above).
    activeJobRef.current = null;
    try {
      const selRes = await resolvedApi.rpc<SelectResult | JobHandle>('shortmaker.select', {
        videoId,
        prompt,
        controls: clean,
      });
      // F2: select also carries a timeout + the cancel/unmount AbortSignal.
      // LANE OWNERSHIP (see above): `resolveJobResult` records the deferred handle
      // on the ref it is handed, and does so SYNCHRONOUSLY (no await precedes the
      // write), so choosing the ref here is equivalent to gating that write. A
      // non-owner gets a throwaway sink: its job is real and still awaited, it
      // just must not claim the visible lane's progress/cancel handle.
      const found = await resolveJobResult(
        resolvedApi,
        selRes,
        extractCandidates,
        abortRef.current === ctrl ? activeJobRef : { current: null },
        EXPORT_JOB_TIMEOUT_MS,
        ctrl.signal,
      );
      // Bug-sweep: honor a mid-flight Cancel on the synchronous-resolve path so a
      // cancel during the select phase never dispatches the export rpc (closes the
      // orphaned-export window without extra job.cancel plumbing).
      if (ctrl.signal.aborted) throw new JobAbortedError();
      const candidates = found ?? [];
      const top = topByVirality(candidates, clean.count);
      // The user may have switched the picker during the select wait. GUARD THE
      // WRITES, NOT THE WORK: every component-state write below is a factual claim
      // about the CURRENTLY selected video, but the export itself is the batch the
      // user asked for, and `buildExportParams` uses the CLOSURE's `videoId`, so it
      // still produces the requested clips for the right video. Suppressing only
      // the on-screen receipt is the smaller cost — abandoning the export would
      // trade a false-status defect for silently dropped work. Re-checked after the
      // export wait, because the switch can land during THAT wait instead.
      const mine = videoIdRef.current === startedFor;
      if (mine) {
        dispatch({ type: 'load', candidates }); // surface for post-hoc review
        // A no-op when `top` is empty, so hoisting it above the zero-result return
        // below is behaviour-identical to approving after that check.
        for (const c of top) dispatch({ type: 'approve', id: candidateId(c) });
      }
      if (top.length === 0) {
        // F1: a confirmed zero-result is NOT an error — fall through to the
        // "No candidates were proposed" empty state (no error/Retry surfaced).
        // Guarded too: that empty state would be a claim about a video this batch
        // never asked about.
        if (mine) setPhase('reviewing');
        return;
      }
      if (mine) {
        setPhase('exporting');
        setProgress({ jobId: '', pct: 0, message: `Exporting ${top.length} clips…` });
      }
      const expRes = await resolvedApi.rpc<ExportResult | JobHandle>(
        'shortmaker.export',
        // F45: same `output` slice as the review path (see runExport).
        buildExportParams(videoId, top, clean, audioTrackId, output),
      );
      const clips = await resolveJobResult(
        resolvedApi,
        expRes,
        extractClips,
        // Same lane-ownership choice as the select stage above — and this is the
        // one the videoId guard made newly reachable: with `setPhase('exporting')`
        // now skipped for a non-owner, video 2 is idle and startable, so video 1's
        // export handle can arrive while video 2 owns the lane.
        abortRef.current === ctrl ? activeJobRef : { current: null },
        EXPORT_JOB_TIMEOUT_MS,
        ctrl.signal,
      );
      // Bug-sweep: honor a mid-flight Cancel before loading the exported clips.
      if (ctrl.signal.aborted) throw new JobAbortedError();
      // Unguarded for the same reason as runExport's copy: correctly attributed to
      // the closure's video, and no component state is written.
      for (const c of top) recordFeedback(resolvedApi, videoId, c, 'exported');
      // Re-read (not `mine`): the switch may have landed during the export wait.
      if (videoIdRef.current !== startedFor) return;
      setExportedClips(clips ?? []);
      void reloadVideoShorts();
      setPhase('reviewing');
    } catch (e) {
      // F2: an aborted wait is a clean cancel — cancel() already reset to idle.
      if (e instanceof JobAbortedError) return;
      // Same rule for the failure half — v1's error is not v2's.
      if (videoIdRef.current !== startedFor) return;
      setError(errMsg(e));
      setRetryAction('batch');
      setPhase('reviewing');
    } finally {
      // LANE OWNERSHIP (see above): only the current owner tears the lane down.
      if (abortRef.current === ctrl) {
        activeJobRef.current = null;
        abortRef.current = null;
        setProgress(null);
      }
    }
  }, [resolvedApi, busy, videoId, prompt, controls, audioTrackId, output, reloadVideoShorts]);

  // F2: abort any in-flight job.done wait (cancel/unmount) so the wait rejects
  // with JobAbortedError and its subscription/timer tear down instead of leaking.
  // It releases the CONTROLLER only: after a cancel the aborted run's `finally` is
  // no longer the owner and skips the teardown, so the handle slot stays set until
  // the next run takes the lane and re-initialises it. Nulling it here as well was
  // tried and REMOVED — no test could distinguish it (the mutation survived),
  // because the handle is unreadable while `phase` is idle: the relay renders only
  // when `busy`, and Cancel renders only when `busy`.
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
    // Cancel renders on `busy` ALONE (ShortMakerControls.tsx:349), NOT on "busy
    // with a known handle" — so this half is a REAL path, not a defensive one: a
    // cancel in the pre-handle window (the rpc that returns the handle is still in
    // flight) has nothing to cancel server-side, and resetting the UI is the whole
    // job. It used to share a `v8 ignore` with the guard below, which hid a
    // reachable branch behind an unreachable one; it is covered by its own test now.
    if (!jobId) return;
    // resolvedApi is always present (prop or window.api); defensive guard.
    /* v8 ignore next */
    if (!resolvedApi) return;
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
            {exportedClips.map((c, i) => {
              // W12 — the sidecar's WU-3 NO-SILENT-FALLBACK notice. Without this
              // the reframe could collapse to a center crop and the clip still
              // read as a successful tracked reframe. The sidecar's own message
              // is rendered verbatim: two producers share this notice type and
              // mean different things, so a paraphrase would be false for one.
              const degraded = reframeDegradedNotice(c);
              return (
                <li key={`${c.path}-${i}`}>
                  {c.path}
                  {typeof c.fillersRemoved === 'number' && (
                    <span className="sm-fillers" aria-label="Fillers removed">
                      {' '}
                      removed {c.fillersRemoved} fillers ({(c.fillerSeconds ?? 0).toFixed(1)}s)
                    </span>
                  )}
                  {degraded && (
                    <span className="sm-degraded" aria-label="Reframe degraded">
                      {degraded.message}
                    </span>
                  )}
                </li>
              );
            })}
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
        onReexport={onReexport ? (p) => void reexportShort(p) : undefined}
        onDelete={(p) => void deleteShort(p)}
      />
      {shortsConfirmDialog}

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
