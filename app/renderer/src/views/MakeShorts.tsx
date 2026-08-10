// MakeShorts.tsx — the V1 "Make Shorts" SECTION (novice front door, IA §h).
//
// Consolidates everything about producing shorts into ONE section (killing the
// old split across the "Create" gallery + a buried Short-maker sub-tab + the
// separate "Repurpose" batch surface):
//   * Make    — pick a video, then AI moment-pick (ShortMaker) OR Manual
//               interval ranges (ManualInterval -> inline shortmaker.export),
//               with the shared Output Tray after a manual export.
//   * Gallery — the SINGLE produced-shorts gallery (Shorts view).
//   * Batch   — batch / templates / export presets (Repurpose view).
//
// Re-export from the gallery jumps to Make primed with the source video. The
// heavy children own their own tests; this view owns the section routing +
// video selection + the manual-export wiring.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { TabBar, tabId, tabPanelId, type TabDef } from '../components/TabBar';
import { Shorts } from './Shorts';
import { Repurpose } from './Repurpose';
import { ShortMaker } from '../features/ShortMaker';
import { ManualInterval } from '../features/ManualInterval';
import { OutputTray, DEFAULT_OUTPUT_TRAY, type OutputTrayState } from '../components/OutputTray';
import { CaptionDesigner } from '../components/CaptionDesigner';
import { buildExportParams, type ExportOutputOptions } from '../features/shortMakerPresets';
import {
  candidateId,
  sanitizeControls,
  extractClips,
  isJobHandle,
  waitForJobDone,
  EXPORT_JOB_TIMEOUT_MS,
  resolveWindowApi,
  type Api,
  type ExportedClipInfo,
} from '../features/shortMakerLogic';
import { describeDegraded, reframeDegradedNotice } from '../lib/reframeDegraded';
import {
  type CaptionDesign,
  DEFAULT_CAPTION_DESIGN,
  captionDesignWire,
  sampleCaptionCues,
} from '../lib/captionDesign';
import { readPreferences, translationTargetLanguage } from '../lib/captionPreferences';
import { client, hasApi, type Candidate, type ShortReexportHint, type Video } from '../lib/rpc';
import './makeShorts.css';

/** Seconds of the source the caption editor previews (style/position rehearsal). */
const CAPTION_PREVIEW_SEC = 6;

const SECTIONS: TabDef[] = [
  { id: 'make', label: 'Make' },
  { id: 'gallery', label: 'Produced shorts' },
  { id: 'batch', label: 'Batch & Templates' },
];

export interface MakeShortsProps {
  /** A deep-link batch id to resume on mount (forwarded to the Batch surface). */
  resumeId?: string;
  /**
   * WU-3a4: a deep-linked source video to pre-select on the Make front door. The
   * Workspace "Short-maker" tab routes here (this section is the single ShortMaker
   * owner) with the open video threaded through so AI moment-pick is immediately
   * revealed — no re-picking. Omitted → the picker starts empty (unchanged).
   */
  videoId?: string;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The Make Shorts section: AI/manual making + the single gallery + batch. */
export function MakeShorts({ resumeId, videoId }: MakeShortsProps): React.ReactElement {
  // Resume deep-links land on the Batch surface; otherwise the Make front door.
  const [active, setActive] = useState<string>(resumeId ? 'batch' : 'make');
  const [videos, setVideos] = useState<Video[]>([]);
  // WU-3a4: seed the picker from a deep-linked source video (the Workspace
  // Short-maker tab redirect) so AI moment-pick is revealed on arrival.
  const [selectedId, setSelectedId] = useState(videoId ?? '');
  const [manualBusy, setManualBusy] = useState(false);
  const [manualNote, setManualNote] = useState<string | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);
  // W06: the clips the export job actually reported. Previously the resolved
  // payload was read for `.length` and thrown away, so the surface had nothing
  // true to show and fell back to fabricated "Saved …" copy. Keeping the records
  // also carries the sidecar's per-clip `reframeDegraded` notice (W12).
  const [exportedClips, setExportedClips] = useState<ExportedClipInfo[]>([]);
  const [tray, setTray] = useState<OutputTrayState>(DEFAULT_OUTPUT_TRAY);
  const [trayOpen, setTrayOpen] = useState(false);
  // P4 §4: the caption design (style + on-frame position) for the manual export,
  // seeded from the persisted Preferences (Settings → Caption defaults).
  const [design, setDesign] = useState<CaptionDesign>(DEFAULT_CAPTION_DESIGN);
  // Gate the AI flow's mount on the persisted-preferences read so the ShortMaker
  // seed (initialControls, read ONCE in its useState initializer) sees the saved
  // caption/language default and not the built-in one. Fail-open: a missing bridge
  // or a failed read still flips this true so the AI flow always mounts.
  const [prefsLoaded, setPrefsLoaded] = useState(false);

  useEffect(() => {
    if (!hasApi()) return;
    let cancelled = false;
    void client.library
      .list()
      .then(({ videos: vids }) => {
        if (!cancelled) setVideos(vids);
      })
      .catch(() => {
        // Best-effort: the picker simply stays empty if the list fails.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // P4 §4: seed the caption design + output defaults from the persisted
  // Preferences so a new short starts from the user's chosen style/position/
  // delivery. Best-effort: a missing/failed settings read keeps the built-in
  // defaults (never blocks the front door).
  useEffect(() => {
    // No bridge → nothing to seed; mount the AI flow with the built-in defaults.
    if (!hasApi()) {
      setPrefsLoaded(true);
      return;
    }
    let cancelled = false;
    void client.settings
      .get()
      .then((raw) => {
        if (cancelled) return;
        const prefs = readPreferences(raw);
        setDesign(prefs.design);
        // `prefs.language` may be the auto-detect sentinel (it is a transcription
        // SOURCE hint), but the tray field it seeds doubles as the translation
        // TARGET, which cannot be auto-detected — so funnel it.
        setTray((t) => ({
          ...t,
          subtitleMode: prefs.subtitleMode,
          language: translationTargetLanguage(prefs.language),
        }));
        setPrefsLoaded(true);
      })
      .catch(() => {
        // Best-effort: keep the built-in defaults if preferences can't be read,
        // but still mount the AI flow (fail-open) rather than blocking it.
        if (!cancelled) setPrefsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-export from the gallery: jump to Make primed with the source video.
  const handleReexport = useCallback((hint: ShortReexportHint) => {
    if (hint.videoId) setSelectedId(hint.videoId);
    setActive('make');
  }, []);

  // ---- clear the manual-export RECEIPT when the selected video changes ------
  // The manual section is NOT unmounted by a video switch (the outer conditional
  // is only `selectedId ?`), so without this every receipt below survives into the
  // next video: the real clip paths, the W12 degrade summary, the "Exported N
  // clip(s)" note and the tray. W06 is what made that concrete — it replaced vague
  // stale copy with REAL paths and a REAL degrade warning, so a survived receipt
  // stopped being cosmetic and became a false factual claim about the newly
  // selected video's data (measured: export v1, switch to v2 → the panel still
  // showed v1's files and v1's warning while the child ShortMaker had already
  // re-keyed to v2). `manualNote`/`trayOpen` are cleared alongside `exportedClips`
  // for the same reason: all four describe an export of the PREVIOUS video, and
  // clearing only some of them would leave the same lie one line over.
  // This mirrors ShortMaker.tsx:255-264, which resets its own per-video review
  // state for exactly this reason. Every reset is idempotent against the initial
  // state, so it is a harmless no-op on first mount.
  useEffect(() => {
    setExportedClips([]);
    setManualNote(null);
    setManualError(null);
    setTrayOpen(false);
  }, [selectedId]);

  // W06 — the tray's "Save short" / "Save SRT separately" controls are
  // deliberately NOT wired here, and the tray hides a save button whose handler
  // is omitted (OutputTray.tsx:139-148). They used to call `setManualNote('Saved
  // the short.')` / `setManualNote('Saved the SRT sidecar.')` and issue ZERO IPC:
  // the surface announced a save it had not performed.
  //
  // Neither is a real action on THIS surface. `shortmaker.export` has already
  // written each mp4 into the exports root before the tray is even shown (there
  // is no unsaved short held in memory), and a standalone subtitle file is
  // precisely the tray's own "Subtitles -> Separate file" delivery
  // (`SUBTITLE_MODE_META.sidecar`), which flows through `exportOutput` on the NEXT
  // export. Re-adding a handler here without an RPC behind it re-opens the defect.
  // What the user actually needed — WHERE the files landed — is rendered below
  // from the job's own payload.

  // The caption design's export slice (style id + wire-rounded position box +
  // the optional V1.1 tuning patch), computed ONCE for every consumer: the
  // manual export payload, the AI flow's `output` prop, and the AI flow's
  // mount-time style seed. Recomputed only when the design changes.
  const wire = useMemo(() => captionDesignWire(design), [design]);

  // F08 — the Output Tray's "Caption" checkbox is the COARSE switch: unchecking
  // it means "no captions at all", which the contract already expresses as the
  // 'none' delivery mode (the sidecar skips the whole caption stage). The tray's
  // own onChange flips only `caption` and hides the delivery select, so nothing
  // else translates the intent — without this gate an explicit "captions off"
  // was silently discarded and the next export HARD-BURNED them into the pixels.
  //
  // H6/F45 — this is deliberately ONE expression shared by BOTH export paths
  // (the manual `buildExportParams` call below AND the AI flow's `output` prop).
  // Gating only the manual path would leave the identical defect one seam over.
  const subtitleMode = tray.caption ? tray.subtitleMode : 'none';

  // F45 — the caption POSITION, the subtitle DELIVERY mode and the V1.1 caption
  // OVERRIDE the user chose in this section. Both export paths send them; before
  // this the AI/batch call sites omitted the whole slice, so a top/centre box, a
  // soft-track/sidecar delivery and any override were dropped on the floor.
  // Memoised so the AI flow's export/batch callbacks are not re-created on every
  // render by a fresh object literal.
  const exportOutput = useMemo<ExportOutputOptions>(
    () => ({
      captionPosition: wire.captionPosition,
      subtitleMode,
      captionOverride: wire.captionOverride,
    }),
    [wire, subtitleMode],
  );

  // Manual export runs only from the ManualInterval control, which is rendered
  // ONLY once a video is selected (so `selectedId` is always set here, and the
  // video list is populated only when the preload bridge is present — no extra
  // guards needed). The export params reuse the AI flow's contract; the client
  // wrapper supplies videoId + candidateIds, so the full params object is a safe
  // opts payload (duplicate keys carry identical values).
  const runManualExport = useCallback(
    async (candidates: Candidate[]) => {
      setManualNote(null);
      setManualError(null);
      setExportedClips([]);
      setTrayOpen(false);
      setManualBusy(true);
      try {
        // The design's style flows via controls.captionStyle; the position +
        // subtitle delivery + the V1.1 within-template tuning patch flow via the
        // export output options (P4 §4 / V1.1 CaptionOverride).
        const controls = sanitizeControls({ captionStyle: wire.captionStyle });
        const params = buildExportParams(selectedId, candidates, controls, '', exportOutput);
        const res = await client.shortmaker.export(selectedId, candidates.map(candidateId), params);
        // shortmaker.export is a DEFERRED job: the immediate resolution carries
        // only {jobId}; the exported clips (or a job.done ERROR) arrive later.
        // Wait for the real outcome so the success note reflects the true clip
        // count, a job.done failure surfaces (never a silent success), and
        // manualBusy stays true until the export actually settles.
        let clips = extractClips(res);
        if (clips === null && isJobHandle(res)) {
          clips = await waitForJobDone(
            resolveWindowApi() as Api,
            res.jobId,
            extractClips,
            EXPORT_JOB_TIMEOUT_MS,
          );
        }
        const produced = clips ?? [];
        setExportedClips(produced);
        setManualNote(`Exported ${produced.length} clip(s) from your ranges.`);
        setTrayOpen(true);
      } catch (err) {
        setManualError(errText(err));
      } finally {
        setManualBusy(false);
      }
    },
    // `wire` + `exportOutput` are memoised, so listing them (rather than
    // `design`/`tray.*`) keeps the callback fresh across a design change AND a
    // tray Caption/delivery change. MANDATORY: `react-hooks/exhaustive-deps` is
    // off in app/.oxlintrc.json, so a missing dep here is caught only by tests —
    // and it would silently make the F08 gate above a no-op (the memoised
    // callback would keep the pre-toggle binding).
    [selectedId, wire, exportOutput],
  );

  // W12: null when every clip reframed normally (no scary banner on a clean run).
  const degradedSummary = describeDegraded(exportedClips);

  return (
    <div className="make-shorts" aria-label="Make Shorts">
      <TabBar tabs={SECTIONS} active={active} onSelect={setActive} />
      {/* A real `role="tabpanel"` owned by the active tab. Without this the
          tablist's `aria-controls` pointed at nothing and axe failed CI with a
          CRITICAL `aria-valid-attr-value` (`aria-controls="tabpanel-make"`).
          The id/aria-labelledby pair is the same bidirectional wiring Workspace,
          Repurpose, Deliver and Settings already use. */}
      <div
        className="make-shorts__panel"
        role="tabpanel"
        id={tabPanelId(active)}
        aria-labelledby={tabId(active)}
      >
        {active === 'gallery' ? <Shorts onReexport={handleReexport} /> : null}
        {active === 'batch' ? <Repurpose resumeId={resumeId} /> : null}
        {active === 'make' ? (
          <div className="make-shorts__make">
            <label className="make-shorts__picker">
              <span>Video</span>
              <select
                aria-label="Source video"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                <option value="">Select a video…</option>
                {videos.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.title}
                  </option>
                ))}
              </select>
            </label>

            {selectedId ? (
              <>
                {prefsLoaded ? (
                  <section className="make-shorts__ai">
                    <h2 className="make-shorts__heading">AI moment-pick</h2>
                    {/* Seed the AI flow from the SAME persisted caption/language
                        default the manual path uses, so both agree (P4 §4). The
                        wired caption-style value matches the manual export's.
                        F45: `output` carries the caption position + subtitle
                        delivery + override into BOTH AI export call sites (review
                        and unattended batch) — the same slice the manual path
                        sends, so the two paths cannot diverge again. */}
                    <ShortMaker
                      videoId={selectedId}
                      onReexport={handleReexport}
                      initialControls={{
                        captionStyle: wire.captionStyle,
                        language: tray.language,
                      }}
                      output={exportOutput}
                    />
                  </section>
                ) : null}

                <section className="make-shorts__captions">
                  <h2 className="make-shorts__heading">Caption &amp; style</h2>
                  <p className="make-shorts__sub">
                    Drag the caption box to position it, pick a style — previewed live on your
                    video.
                  </p>
                  <CaptionDesigner
                    videoId={selectedId}
                    window={{ start: 0, end: CAPTION_PREVIEW_SEC }}
                    cues={sampleCaptionCues({ start: 0, end: CAPTION_PREVIEW_SEC })}
                    design={design}
                    onChange={setDesign}
                  />
                </section>

                <section className="make-shorts__manual">
                  <h2 className="make-shorts__heading">Manual intervals</h2>
                  <ManualInterval onSubmit={(c) => void runManualExport(c)} busy={manualBusy} />
                  {manualError ? (
                    <p className="make-shorts__error" role="alert">
                      {manualError}
                    </p>
                  ) : null}
                  {manualNote ? (
                    <p className="make-shorts__note" role="status">
                      {manualNote}
                    </p>
                  ) : null}
                  {/* W12 — the sidecar's WU-3 NO-SILENT-FALLBACK signal. The
                      summary states the COUNT only: the same notice type is
                      raised both by a center-crop fallback AND by the
                      multi-speaker engine falling back to the single-speaker
                      tracker, so naming an outcome here would be false for one of
                      them. Each clip shows the sidecar's own message instead. */}
                  {degradedSummary ? (
                    <p className="make-shorts__warn" role="status">
                      {degradedSummary}
                    </p>
                  ) : null}
                  {exportedClips.length > 0 ? (
                    <ul className="make-shorts__outputs" aria-label="Exported files">
                      {exportedClips.map((clip, i) => {
                        const degraded = reframeDegradedNotice(clip);
                        return (
                          <li key={`${clip.path}-${i}`} className="make-shorts__output">
                            <span className="make-shorts__output-path">{clip.path}</span>
                            {degraded ? (
                              <span className="make-shorts__degraded">{degraded.message}</span>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                  {trayOpen ? <OutputTray state={tray} onChange={setTray} /> : null}
                </section>
              </>
            ) : (
              <div className="make-shorts__empty">
                <div className="make-shorts__empty-poster" aria-hidden="true">
                  <span className="make-shorts__empty-glyph">▶</span>
                  <span className="make-shorts__empty-timecode">--:--</span>
                </div>
                <p className="make-shorts__empty-title">No video selected</p>
                <p className="make-shorts__hint">
                  Pick a video to make shorts — AI moment-pick or your own time ranges.
                </p>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default MakeShorts;
