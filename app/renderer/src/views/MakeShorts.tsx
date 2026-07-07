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
import React, { useCallback, useEffect, useState } from 'react';
import { TabBar, type TabDef } from '../components/TabBar';
import { Shorts } from './Shorts';
import { Repurpose } from './Repurpose';
import { ShortMaker } from '../features/ShortMaker';
import { ManualInterval } from '../features/ManualInterval';
import { OutputTray, DEFAULT_OUTPUT_TRAY, type OutputTrayState } from '../components/OutputTray';
import { CaptionDesigner } from '../components/CaptionDesigner';
import { buildExportParams } from '../features/shortMakerPresets';
import { candidateId, sanitizeControls } from '../features/shortMakerLogic';
import {
  type CaptionDesign,
  DEFAULT_CAPTION_DESIGN,
  captionDesignWire,
  sampleCaptionCues,
} from '../lib/captionDesign';
import { readPreferences } from '../lib/captionPreferences';
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
  const [tray, setTray] = useState<OutputTrayState>(DEFAULT_OUTPUT_TRAY);
  const [trayOpen, setTrayOpen] = useState(false);
  // P4 §4: the caption design (style + on-frame position) for the manual export,
  // seeded from the persisted Preferences (Settings → Caption defaults).
  const [design, setDesign] = useState<CaptionDesign>(DEFAULT_CAPTION_DESIGN);

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
    if (!hasApi()) return;
    let cancelled = false;
    void client.settings
      .get()
      .then((raw) => {
        if (cancelled) return;
        const prefs = readPreferences(raw);
        setDesign(prefs.design);
        setTray((t) => ({ ...t, subtitleMode: prefs.subtitleMode, language: prefs.language }));
      })
      .catch(() => {
        // Best-effort: keep the built-in defaults if preferences can't be read.
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

  // Output Tray save seams (the caption-editor phase deepens these): record what
  // the user chose to save so the action is acknowledged, never silent.
  const handleSaveShort = useCallback(() => setManualNote('Saved the short.'), []);
  const handleSaveSrt = useCallback(() => setManualNote('Saved the SRT sidecar.'), []);

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
      setTrayOpen(false);
      setManualBusy(true);
      try {
        const wire = captionDesignWire(design);
        // The design's style flows via controls.captionStyle; the position +
        // subtitle delivery flow via the export output options (P4 §4).
        const controls = sanitizeControls({ captionStyle: wire.captionStyle });
        const params = buildExportParams(selectedId, candidates, controls, '', {
          captionPosition: wire.captionPosition,
          subtitleMode: tray.subtitleMode,
        });
        await client.shortmaker.export(selectedId, candidates.map(candidateId), params);
        setManualNote(`Exported ${candidates.length} clip(s) from your ranges.`);
        setTrayOpen(true);
      } catch (err) {
        setManualError(errText(err));
      } finally {
        setManualBusy(false);
      }
    },
    [selectedId, design, tray.subtitleMode],
  );

  return (
    <div className="make-shorts" aria-label="Make Shorts">
      <TabBar tabs={SECTIONS} active={active} onSelect={setActive} />
      <div className="make-shorts__panel">
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
                <section className="make-shorts__ai">
                  <h2 className="make-shorts__heading">AI moment-pick</h2>
                  <ShortMaker videoId={selectedId} />
                </section>

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
                  {trayOpen ? (
                    <OutputTray
                      state={tray}
                      onChange={setTray}
                      onSaveShort={handleSaveShort}
                      onSaveSrt={handleSaveSrt}
                    />
                  ) : null}
                </section>
              </>
            ) : (
              <p className="make-shorts__hint">
                Pick a video to make shorts — AI moment-pick or your own time ranges.
              </p>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default MakeShorts;
