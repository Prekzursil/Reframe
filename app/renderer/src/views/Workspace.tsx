import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import './workspace.css';
import { TabBar, tabId, tabPanelId, type TabDef } from '../components/TabBar';
import { Player, type PlayerHandle } from '../components/Player';
import { rpc, type Project, type Video } from '../components/api';
import { onProxyState } from '../lib/rpc';
import type { SubtitleTrack as FeatureSubtitleTrack } from '../features/_api';

export interface WorkspaceProps {
  /** The video opened from the Library. */
  video: Video;
  /** Return to the Library home. */
  onBack: () => void;
  /**
   * The panel to open on (a Task Hub deep-link, e.g. 'shortmaker' / 'subtitles').
   * ADDITIVE: omitted → the workspace default (the video lane, project tools).
   *
   * A deep-link PINS its panel's selection context until the user changes the
   * selection, so a link to a clip-scoped tool (`gaze`, `speed`, …) opens that
   * tool even before a clip has been clicked. See `context` below.
   */
  initialTab?: string;
  /**
   * WU-3a4 (retained): the SINGLE-OWNER deep-link into the top-level Make Shorts
   * section. Since L5 the rail hosts Make Shorts under **Produce**, so the
   * workspace no longer mounts a ShortMaker copy at all — an
   * `initialTab='shortmaker'` deep-link still bounces to the single owner here.
   * ADDITIVE: omitted → the deep-link is ignored and the workspace opens on its
   * default (ShortMaker stays reachable from the Produce rail destination).
   */
  onOpenMakeShorts?: (videoId: string) => void;
}

// STATIC lazy imports (punch #3): all panels exist now, so the old
// runtime-variable specifier (`@vite-ignore` + absence shim) is obsolete — and
// actively harmful: Rollup cannot statically analyze a variable import, so every
// PACKAGED build shipped an empty shell. Static literals let the bundler emit
// real chunks; React.lazy still code-splits per panel.
const Transcribe = lazy(() => import('../features/Transcribe'));
const Subtitles = lazy(() => import('../features/Subtitles'));
const Tracks = lazy(() => import('../features/Tracks'));
const Convert = lazy(() => import('../features/Convert'));
const TimelinePanel = lazy(() => import('../features/Timeline'));
const Dub = lazy(() => import('../features/Dub'));
// v1.5: constant-factor speed / slow motion over the existing re-time engine.
const SpeedPanel = lazy(() => import('../features/Speed'));
// v1.5 audiomix-ui: the A/V mixer — music bed / VO under the speaker with
// sidechain auto-ducking, plus EBU R128 loudness normalization of an export.
const AudioMix = lazy(() => import('../features/AudioMix'));
const Assets = lazy(() => import('../features/Assets'));
// captions-export: EDL/CSV NLE timeline export of approved clips.
const NleExport = lazy(() => import('../features/NleExport'));
// system-advanced group: per-video Diarize + Refine + Recipes panels.
const Diarize = lazy(() => import('../features/Diarize'));
const Refine = lazy(() => import('../features/Refine'));
// v1.5 expose-engines: per-video camera-shake removal.
const Stabilize = lazy(() => import('../features/Stabilize'));
// v1.5 flagship #2: transcript-native editing (strike a word -> the video cuts).
const TranscriptEditor = lazy(() => import('../features/TranscriptEditor'));
const Recipes = lazy(() => import('../features/Recipes'));
// intelligence A: semantic transcript search (seeks the player on a hit).
const SemanticSearch = lazy(() => import('../features/SemanticSearch'));
// W18: the multi-lane VIDEO timeline (clips, razor, drag-to-trim, undo). It is
// no longer a tab — it is DOCKED at the bottom of the stage (L5 G-1).
const VideoTimeline = lazy(() => import('../features/VideoTimeline'));
// W17: manual per-shot reframe correction.
const ReframeCorrect = lazy(() => import('../features/ReframeCorrect'));
// W19: eye-contact correction, carrying its likeness-attestation ethics gate.
const Gaze = lazy(() => import('../features/Gaze'));
// W16-UI: auto-b-roll, carrying its uncalibrated-threshold + no-undo disclosures.
const BrollPanel = lazy(() => import('../features/BrollPanel'));

/**
 * THE PANEL REGISTRY — all 21 per-video panels, with the label each is shown
 * under. This list is NOT a tab strip any more.
 *
 * WHAT CHANGED AND WHY (L5, owner-locked). Until this lane the workspace painted
 * this list as ONE horizontal strip: 21 entries, 16 of them painted at once plus
 * 3 group captions, inside the app's fixed 1280px window. It overflowed, clipped
 * mid-word, and "Short-maker" wrapped to a second line.
 *
 * The measured ROOT CAUSE was not the count — it was that the IA had exactly TWO
 * levels: painted-forever, or behind a one-way "Advanced" trapdoor. Every feature
 * carrying an honesty or consent surface (W17 reframeFix, W19 gaze, W16-UI broll)
 * therefore HAD to stay top-level, each argued correctly, and the strip could only
 * grow. Selection-driven disclosure is the missing THIRD level: a panel appears
 * because something is SELECTED, so shipping a feature never adds permanent
 * chrome and the ratchet cannot re-form.
 *
 * ANTI-RATCHET INVARIANT — do not undo this. Re-homing any of these into a fixed,
 * always-present list (a tab strip, a permanent accordion, a "tools" grid) puts
 * the IA back on two levels and the growth pressure returns.
 */
export const WORKSPACE_TABS: TabDef[] = [
  { id: 'transcribe', label: 'Transcribe' },
  { id: 'search', label: 'Search' },
  { id: 'subtitles', label: 'Subtitles' },
  { id: 'transcriptEdit', label: 'Transcript edit' },
  { id: 'diarize', label: 'Diarize' },
  { id: 'refine', label: 'Refine' },
  { id: 'tracks', label: 'Tracks' },
  { id: 'convert', label: 'Convert' },
  { id: 'shortmaker', label: 'Short-maker' },
  { id: 'reframeFix', label: 'Fix framing' },
  // WORK ITEM 6 — "Subtitle timeline" vs "Video timeline" were two DIFFERENT
  // models sharing one word while sitting two tabs apart in the same strip.
  // They are now the two LANES of one dock and are named for what they hold:
  // `timeline` holds caption CUES, `videoTimeline` holds video CLIPS.
  { id: 'timeline', label: 'Caption cues' },
  { id: 'videoTimeline', label: 'Video clips' },
  { id: 'broll', label: 'Auto B-roll' },
  { id: 'stabilize', label: 'Stabilize' },
  { id: 'gaze', label: 'Eye contact' },
  { id: 'speed', label: 'Speed' },
  { id: 'dub', label: 'Dub' },
  { id: 'audiomix', label: 'Audio mix' },
  { id: 'nle', label: 'NLE export' },
  { id: 'recipes', label: 'Recipes' },
  { id: 'assets', label: 'Assets' },
];

/** What is currently selected, which is what the inspector follows (L5 G-5). */
export type InspectorContext = 'clip' | 'cue' | 'audio' | 'project';

/** The dock's lanes. ONE timeline, several lanes (L5 G-2). */
export type DockLane = 'video' | 'captions' | 'audio';

/**
 * L5 G-5, transcribed mechanically from the owner's mapping table. A panel
 * appears BECAUSE something is selected; nothing selected → project tools.
 *
 * RECONCILE-DON'T-DROP: every id in `WORKSPACE_TABS` is accounted for exactly
 * once — here, in `WORKSPACE_DOCK_PANELS` (the two timeline lanes), or in
 * `WORKSPACE_PANELS_ELSEWHERE` (owned by another rail destination).
 * `workspacePanelHome()` below is the mechanical check.
 */
export const WORKSPACE_INSPECTOR_SECTIONS: Record<InspectorContext, readonly string[]> = {
  clip: ['reframeFix', 'speed', 'stabilize', 'gaze', 'broll'],
  cue: ['subtitles', 'transcriptEdit'],
  audio: ['audiomix', 'dub'],
  // "Nothing selected" is the PROJECT. `convert` / `nle` / `tracks` / `assets`
  // are project-scoped output + library tools; L5 G-3 wants them in the Deliver
  // destination and Settings, which live in views this lane does not own
  // (Deliver.tsx has an open PR against it). They are kept reachable here rather
  // than dropped — see the lane report's residual.
  project: [
    'transcribe',
    'search',
    'diarize',
    'refine',
    'recipes',
    'convert',
    'nle',
    'tracks',
    'assets',
  ],
};

/** The two panels that ARE the dock (not inspector sections). */
export const WORKSPACE_DOCK_PANELS: Record<string, DockLane> = {
  videoTimeline: 'video',
  timeline: 'captions',
};

/** Panels a DIFFERENT rail destination owns. `shortmaker` lives in Produce. */
export const WORKSPACE_PANELS_ELSEWHERE: readonly string[] = ['shortmaker'];

/** The dock lane heads. Selecting one is a SELECTION, which the inspector follows. */
export const WORKSPACE_DOCK_LANES: TabDef[] = [
  { id: 'video', label: 'Video clips' },
  { id: 'captions', label: 'Caption cues' },
  { id: 'audio', label: 'Program audio' },
];

/** A human name for the current selection, shown at the top of the inspector. */
export const INSPECTOR_CONTEXT_LABEL: Record<InspectorContext, string> = {
  clip: 'Selected clip',
  cue: 'Caption cues',
  audio: 'Program audio',
  project: 'Project',
};

/**
 * Where a panel lives now. Returns its inspector context, `'dock'`, or
 * `'elsewhere'`; `null` means the id is homeless, which is the reorganisation
 * bug this function exists to make mechanically detectable.
 */
export function workspacePanelHome(
  panelId: string,
): InspectorContext | 'dock' | 'elsewhere' | null {
  for (const context of ['clip', 'cue', 'audio', 'project'] as const) {
    if (WORKSPACE_INSPECTOR_SECTIONS[context].includes(panelId)) return context;
  }
  if (panelId in WORKSPACE_DOCK_PANELS) return 'dock';
  if (WORKSPACE_PANELS_ELSEWHERE.includes(panelId)) return 'elsewhere';
  return null;
}

/** What is selected, given the lane in focus and the clip picked inside it. */
function contextOfSelection(lane: DockLane, clipId: string | null): InspectorContext {
  if (lane === 'captions') return 'cue';
  if (lane === 'audio') return 'audio';
  // The video lane: a clip selected in it, or nothing selected in it.
  return clipId === null ? 'project' : 'clip';
}

/** Which dock lane a selection context corresponds to. */
function laneOfContext(context: InspectorContext): DockLane {
  if (context === 'cue') return 'captions';
  if (context === 'audio') return 'audio';
  // Both 'clip' and 'project' are read off the video lane: a clip selected in it,
  // or nothing selected in it.
  return 'video';
}

/**
 * design-review P1 (retained): the primary Export destination. Export is the
 * user's terminal goal, so it keeps a standing affordance — now in the workspace
 * header rather than at the far end of a scrolling strip it kept falling off.
 */
export const WORKSPACE_EXPORT_TAB = 'convert';

interface OpenResult {
  project: Project;
}

/**
 * Workspace.tsx — the per-video REFINE surface.
 *
 * Layout (L5 G-1): preview on top, the TIMELINE DOCKED beneath it (zero
 * navigation actions to reach it), and a right-hand INSPECTOR whose sections are
 * driven by the current selection.
 */
export function Workspace({
  video,
  onBack,
  initialTab,
  onOpenMakeShorts,
}: WorkspaceProps): React.ReactElement {
  // Which dock lane is selected. The deep-link decides the opening lane so a link
  // to a caption tool does not open on the video lane and hide its own target.
  const [lane, setLane] = useState<DockLane>(() => {
    if (initialTab !== undefined && initialTab in WORKSPACE_DOCK_PANELS) {
      return WORKSPACE_DOCK_PANELS[initialTab];
    }
    const home = initialTab === undefined ? null : workspacePanelHome(initialTab);
    return home === 'dock' || home === 'elsewhere' || home === null ? 'video' : laneOfContext(home);
  });
  // The clip selected INSIDE the video lane (Q7 — VideoTimeline now reports it).
  const [clipId, setClipId] = useState<string | null>(null);
  const clipRef = useRef<string | null>(null);
  /**
   * The section the user (or a deep-link) explicitly chose. It PINS its own
   * context until the selection changes, which is what makes a deep-link to a
   * clip-scoped tool land on that tool before any clip has been clicked. Cleared
   * by any real selection change, after which the selection is authoritative.
   */
  const [sectionPref, setSectionPref] = useState<string | null>(() => {
    if (initialTab === undefined) return null;
    const home = workspacePanelHome(initialTab);
    return home === 'dock' || home === 'elsewhere' || home === null ? null : initialTab;
  });

  const context: InspectorContext =
    sectionPref === null
      ? contextOfSelection(lane, clipId)
      : (workspacePanelHome(sectionPref) as InspectorContext);
  const sections = WORKSPACE_INSPECTOR_SECTIONS[context];
  // `sectionPref` is only ever set to a panel of `context` (it DEFINES the context
  // when set), so it never needs re-validating against the list.
  const active = sectionPref ?? sections[0];

  const selectSection = useCallback((id: string) => setSectionPref(id), []);

  const selectLane = useCallback((id: string) => {
    setLane(id as DockLane);
    // Changing lane IS a selection change: the inspector goes back to following
    // the selection instead of the pinned deep-link/section.
    setSectionPref(null);
  }, []);

  /**
   * Q7: the timeline reports its selection, so the inspector follows the real
   * editing surface instead of a separate switch.
   *
   * Two reports are NOT user actions and must not be treated as one:
   *   * the mount-time `null` from a panel nobody has touched — the ref guard
   *     keeps that a no-op so it cannot wipe a deep-link;
   *   * the same `null` after a REMOUNT. `renderLane()` returns a different
   *     element TYPE per lane, so leaving and re-entering the video lane rebuilds
   *     the panel and it re-reports `null` (VideoTimeline.tsx:145-147). Clearing
   *     `sectionPref` on that report sent `handleExport` — which switches the lane
   *     back to 'video' — to `sections[0]` (Transcribe) instead of Convert. A
   *     vanished clip only invalidates a pin that is CLIP-scoped; a project / cue
   *     / audio pin is about something else and survives.
   * Conversely a NON-null report is a user gesture even when the id is unchanged:
   * after Export pins a project panel the clip is still selected, so re-picking it
   * is the obvious way back to its tools and must drop the pin (VideoTimeline
   * re-publishes a re-pick precisely so this can work).
   */
  const handleSelectClip = useCallback((id: string | null) => {
    if (id === null) {
      if (clipRef.current === null) return;
      clipRef.current = null;
      setClipId(null);
      setSectionPref((pref) =>
        pref !== null && workspacePanelHome(pref) === 'clip' ? null : pref,
      );
      return;
    }
    clipRef.current = id;
    setClipId(id);
    setSectionPref(null);
  }, []);

  // Q7: `tracks.video.render` really encodes a file; before this the only mount
  // omitted `onRendered`, so the finished file was announced nowhere outside the
  // panel. The dock now carries it as a live region.
  const [renderNote, setRenderNote] = useState<string | null>(null);
  const handleRendered = useCallback((path: string) => {
    setRenderNote(`Timeline rendered to ${path}`);
  }, []);

  // Export jumps the inspector to the panel that produces the final file. It is a
  // project-scoped tool, so it also drops the pinned clip/cue context.
  const handleExport = useCallback(() => {
    setLane('video');
    setSectionPref(WORKSPACE_EXPORT_TAB);
  }, []);

  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  // U1: the workspace player strip + its imperative handle (Timeline seeks it).
  const playerRef = useRef<PlayerHandle | null>(null);
  const [playerNote, setPlayerNote] = useState<string | null>(null);
  // `playerEpoch` is the proxy-swap signal: bumped on the job.done that makes the
  // source playable. It drives the Player's `reloadToken` (a shake-free
  // video.load() re-fetch) — NOT a key-remount, which would visibly restart the
  // element mid-load (the "shakiness" bug).
  const [playerEpoch, setPlayerEpoch] = useState(0);
  const [playerError, setPlayerError] = useState<string | null>(null);
  // The last proxy.state phase we heard from the mstream resolver. It gates how a
  // raw <video> `error` is surfaced (see handlePlayerError): before the resolver
  // has spoken ('initial') the raw source may legitimately be undecodable, so a
  // Chromium "media error (code 4)" is EXPECTED and must not flash the loud
  // banner — a calm "Building preview…" note stands in for that window.
  // WU-1e-fix: 'direct' is the resolver's DEFINITIVE "plays without a build"
  // verdict — it advances the phase past 'initial', so a genuine decode error on
  // a source the resolver MISJUDGED as playable goes LOUD (like 'ready') instead
  // of masking behind a "Building preview…" note that never resolves.
  const proxyPhaseRef = useRef<'initial' | 'direct' | 'building' | 'ready' | 'error'>('initial');

  const reloadProject = useCallback(async () => {
    setError(null);
    try {
      const result = await rpc<OpenResult>('project.open', { id: video.id });
      setProject(result?.project ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [video.id]);

  useEffect(() => {
    void reloadProject();
  }, [reloadProject]);

  // WU-3a4 (retained): an `initialTab='shortmaker'` deep-link bounces to the
  // single Make Shorts owner. Since L5 the workspace does not mount ShortMaker at
  // all, so there is nothing left to fall back to and nothing to intercept.
  useEffect(() => {
    if (initialTab === 'shortmaker' && onOpenMakeShorts) {
      onOpenMakeShorts(video.id);
    }
  }, [initialTab, onOpenMakeShorts, video.id]);

  // WU B3: the mstream resolver is now authoritative for playability — it
  // single-flights the proxy build and NEVER streams the raw, undecodable
  // source ("media error code 4"). We only REACT to its build-state pushes:
  //   'building' — show the reason note while the transcode runs;
  //   'ready'    — clear the note + reload the player (shake-free) so it picks
  //                up the now-decodable proxy for the SAME mstream URL;
  //   'error'    — surface the failure LOUDLY (no silent center-crop).
  useEffect(() => {
    // A new video's resolver has not spoken yet: reset the phase so a stale
    // 'ready' from the previous video can't make this one's initial raw-source
    // error surface loudly.
    proxyPhaseRef.current = 'initial';
    const off = onProxyState((evt) => {
      if (evt.videoId !== video.id) return;
      if (evt.state === 'building') {
        proxyPhaseRef.current = 'building';
        setPlayerNote(evt.detail || 'building playback proxy…');
        setPlayerError(null);
      } else if (evt.state === 'direct') {
        // WU-1e-fix: the resolver decided the source is directly playable (or a
        // valid cached proxy) WITHOUT a build. Advance past 'initial' so a later
        // genuine decode error goes loud (handlePlayerError). No reload (the
        // source is already correct) and we DON'T clear playerError — a decode
        // error that raced ahead of this push must stay loud, and repeated
        // per-range-request 'direct' pushes must never wipe it.
        proxyPhaseRef.current = 'direct';
        setPlayerNote(null);
      } else if (evt.state === 'ready') {
        proxyPhaseRef.current = 'ready';
        setPlayerNote(null);
        setPlayerError(null);
        setPlayerEpoch((n) => n + 1);
      } else {
        proxyPhaseRef.current = 'error';
        setPlayerNote(null);
        setPlayerError(evt.detail || 'playback proxy build failed');
      }
    });
    return off;
  }, [video.id]);

  // Route the raw <video>'s load/decode `error` by proxy phase so the initial
  // pre-resolver window never flashes Chromium's "media error (code 4)":
  //   'ready'/'direct'  — the resolver already DECIDED the source is playable (a
  //                        finished proxy, a directly-playable original, or a
  //                        valid cached proxy), so a decode error now is a GENUINE
  //                        failure → surface loudly (never a silent fallback, and
  //                        never a "Building preview…" note that hangs);
  //   'error'           — a specific build-failure reason is already shown; the
  //                        raw error is a downstream echo → keep the real reason;
  //   'initial'/'building' — the resolver has not (yet) produced a decodable
  //                        proxy, so the raw-source error is expected → show a
  //                        calm note instead of the loud banner.
  const handlePlayerError = useCallback((message: string) => {
    const phase = proxyPhaseRef.current;
    if (phase === 'ready' || phase === 'direct') {
      setPlayerError(message);
      return;
    }
    if (phase === 'error') return;
    setPlayerNote((prev) => prev ?? 'Building preview…');
  }, []);

  // components/api types `format` as plain string while the panels' _api uses
  // the SubtitleFormat union — identical wire shape, divergent TS layers
  // (consolidation = punch #11). Convert once at this boundary.
  const tracks = (project?.tracks ?? []) as unknown as FeatureSubtitleTrack[];

  function renderPanel(): React.ReactElement {
    switch (active) {
      case 'subtitles':
        return <Subtitles videoId={video.id} initialTrack={tracks[0] ?? null} />;
      case 'transcriptEdit':
        return <TranscriptEditor videoId={video.id} />;
      case 'diarize':
        return <Diarize videoId={video.id} />;
      case 'refine':
        return <Refine videoId={video.id} />;
      case 'tracks':
        return <Tracks videoId={video.id} availableTracks={tracks} />;
      case 'convert':
        return <Convert videoId={video.id} path={video.path} />;
      case 'reframeFix':
        return <ReframeCorrect videoId={video.id} />;
      case 'broll':
        // No extra props: every `broll.*` method takes either nothing or
        // `{videoId, …}` — the library half is per MACHINE (a `brollDir` scan plus
        // the BR1 registry), so passing this video's path or duration would imply
        // per-video inputs the RPCs do not accept.
        return <BrollPanel videoId={video.id} />;
      case 'stabilize':
        return <Stabilize videoId={video.id} />;
      case 'gaze':
        // No extra props: `gaze.run` accepts only {videoId|path, strength,
        // likeness*} (`gaze.py:619-637`), and the panel owns the strength control
        // plus the likeness attestation itself.
        return <Gaze videoId={video.id} />;
      case 'speed':
        // durationSec drives the before/after prediction only; the sidecar
        // probes the real length itself, so a stale/zero value cannot mis-render.
        return <SpeedPanel videoId={video.id} sourceDurationSec={video.durationSec} />;
      case 'dub':
        return <Dub videoId={video.id} />;
      case 'audiomix':
        return <AudioMix videoId={video.id} />;
      case 'nle':
        return <NleExport videoId={video.id} />;
      case 'recipes':
        return <Recipes videoId={video.id} />;
      case 'search':
        return <SemanticSearch videoId={video.id} playerRef={playerRef} />;
      case 'assets':
        return <Assets />;
      case 'transcribe':
      default:
        return <Transcribe videoId={video.id} />;
    }
  }

  function renderLane(): React.ReactElement {
    if (lane === 'captions') {
      return (
        <TimelinePanel videoId={video.id} durationSec={video.durationSec} playerRef={playerRef} />
      );
    }
    if (lane === 'audio') {
      // WAVE 1 is shell only: this lane NAMES the object whose tools the
      // inspector then offers (Audio mix / Dub). It adds no capability — a
      // waveform and per-region audio editing are wave 2.
      return (
        <div className="workspace__audio-lane" data-role="program-audio">
          <span className="workspace__lane-name">Program audio</span>
          <span className="workspace__lane-source">{video.title}</span>
        </div>
      );
    }
    // `sourcePath`/`sourceDurationSec` are NOT decoration: `tracks.video.addClip`
    // is the only way an ARBITRARY clip reaches a lane, and it needs a real file
    // path plus a `srcOut`. `tracks.video.list` auto-seeds lane 0 with the whole
    // source on first contact (`video_tracks.py:595-612,653`), so the lane is
    // never blank; what the props buy is the ability to put material BACK.
    return (
      <VideoTimeline
        videoId={video.id}
        sourcePath={video.path}
        sourceDurationSec={video.durationSec}
        onRendered={handleRendered}
        onSelectClip={handleSelectClip}
      />
    );
  }

  const sectionTabs = sections.map((id) => WORKSPACE_TABS.find((tab) => tab.id === id) as TabDef);

  return (
    <div className="workspace">
      <header className="workspace__header">
        <button type="button" className="workspace__back" onClick={onBack}>
          ← Library
        </button>
        <h1 className="workspace__title" title={video.path}>
          {video.title}
        </h1>
        {/* Export used to sit at the far end of the tab strip, where the growing
            strip repeatedly pushed it out of the 1280px window. In the header it
            cannot be scrolled away at any panel count. */}
        <button type="button" className="workspace__export" onClick={handleExport}>
          Export
        </button>
      </header>

      {error ? (
        <div className="workspace__error" role="alert">
          {error}
        </div>
      ) : null}

      <div className="workspace__main">
        <div className="workspace__stage">
          <div className="workspace__player">
            {/* key is the videoId ONLY: switching videos remounts (a genuinely
                different source), but a proxy swap for the SAME video reuses the
                element via reloadToken (shake-free). */}
            <Player
              ref={playerRef}
              videoId={video.id}
              key={video.id}
              reloadToken={playerEpoch}
              onError={handlePlayerError}
            />
            {playerNote ? (
              <div className="workspace__player-note" role="status" aria-live="polite">
                {playerNote}
              </div>
            ) : null}
            {playerError ? (
              <div className="workspace__player-error" role="alert">
                {playerError}
              </div>
            ) : null}
          </div>

          {/* THE DOCK (L5 G-1 / G-2): one timeline, several lanes, permanently
              visible beside the preview — reachable with ZERO navigation actions.
              Selecting a lane, or a clip inside the video lane, is what drives the
              inspector. */}
          <section className="workspace__dock" aria-label="Timeline">
            <TabBar tabs={WORKSPACE_DOCK_LANES} active={lane} onSelect={selectLane} />
            <div
              className="workspace__dock-body"
              role="tabpanel"
              id={tabPanelId(lane)}
              aria-labelledby={tabId(lane)}
            >
              <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
                {renderLane()}
              </Suspense>
            </div>
            {renderNote ? (
              <p className="workspace__dock-note" role="status">
                {renderNote}
              </p>
            ) : null}
          </section>
        </div>

        {/* THE INSPECTOR (L5 G-5): its sections exist because something is
            selected. Adding a feature adds a section to a context — never a
            permanent piece of chrome — which is what stops the strip re-growing.
            The section list is VERTICAL (workspace.css), so it cannot overflow
            horizontally however many panels a context gains. */}
        <aside className="workspace__inspector" aria-label="Inspector">
          <p className="workspace__inspector-context" data-role="selection">
            {INSPECTOR_CONTEXT_LABEL[context]}
          </p>
          <TabBar tabs={sectionTabs} active={active} onSelect={selectSection} />
          <div
            className="workspace__body"
            role="tabpanel"
            id={tabPanelId(active)}
            aria-labelledby={tabId(active)}
          >
            <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
              {renderPanel()}
            </Suspense>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default Workspace;
