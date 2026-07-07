import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import './workspace.css';
import { TabBar, type TabDef } from '../components/TabBar';
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
   * The tab to open on (a Task Hub deep-link, e.g. 'shortmaker' / 'subtitles').
   * ADDITIVE: omitted → the existing default (the first tab, Transcribe).
   */
  initialTab?: string;
}

// STATIC lazy imports (punch #3): all 8 panels exist now, so the old
// runtime-variable specifier (`@vite-ignore` + absence shim) is obsolete — and
// actively harmful: Rollup cannot statically analyze a variable import, so every
// PACKAGED build shipped an empty shell. Static literals let the bundler emit
// real chunks; React.lazy still code-splits per panel.
const Transcribe = lazy(() => import('../features/Transcribe'));
const Subtitles = lazy(() => import('../features/Subtitles'));
const Tracks = lazy(() => import('../features/Tracks'));
const Convert = lazy(() => import('../features/Convert'));
const ShortMaker = lazy(() => import('../features/ShortMaker'));
const TimelinePanel = lazy(() => import('../features/Timeline'));
const Dub = lazy(() => import('../features/Dub'));
const Assets = lazy(() => import('../features/Assets'));
// captions-export: EDL/CSV NLE timeline export of approved clips.
const NleExport = lazy(() => import('../features/NleExport'));
// system-advanced group: per-video Diarize + Refine + Recipes panels.
const Diarize = lazy(() => import('../features/Diarize'));
const Refine = lazy(() => import('../features/Refine'));
const Recipes = lazy(() => import('../features/Recipes'));
// intelligence A: semantic transcript search (seeks the player on a hit).
const SemanticSearch = lazy(() => import('../features/SemanticSearch'));

export const WORKSPACE_TABS: TabDef[] = [
  { id: 'transcribe', label: 'Transcribe' },
  { id: 'search', label: 'Search' },
  { id: 'subtitles', label: 'Subtitles' },
  { id: 'diarize', label: 'Diarize' },
  { id: 'refine', label: 'Refine' },
  { id: 'tracks', label: 'Tracks' },
  { id: 'convert', label: 'Convert' },
  { id: 'shortmaker', label: 'Short-maker' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'dub', label: 'Dub' },
  { id: 'nle', label: 'Timeline export' },
  { id: 'recipes', label: 'Recipes' },
  { id: 'assets', label: 'Assets' },
];

interface OpenResult {
  project: Project;
}

/**
 * Workspace.tsx — the tabbed per-video workspace.
 * Opens the project (project.open) and mounts the active feature panel, passing
 * each the props it declares (videoId + project-derived optionals).
 */
export function Workspace({ video, onBack, initialTab }: WorkspaceProps): React.ReactElement {
  const [active, setActive] = useState<string>(initialTab ?? WORKSPACE_TABS[0].id);
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
      case 'diarize':
        return <Diarize videoId={video.id} />;
      case 'refine':
        return <Refine videoId={video.id} />;
      case 'tracks':
        return <Tracks videoId={video.id} availableTracks={tracks} />;
      case 'convert':
        return <Convert videoId={video.id} path={video.path} />;
      case 'shortmaker':
        return <ShortMaker videoId={video.id} />;
      case 'timeline':
        return (
          <TimelinePanel videoId={video.id} durationSec={video.durationSec} playerRef={playerRef} />
        );
      case 'dub':
        return <Dub videoId={video.id} />;
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

  return (
    <div className="workspace">
      <header className="workspace__header">
        <button type="button" className="workspace__back" onClick={onBack}>
          ← Library
        </button>
        <h1 className="workspace__title" title={video.path}>
          {video.title}
        </h1>
      </header>

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
        {playerNote ? <div className="workspace__player-note">{playerNote}</div> : null}
        {playerError ? (
          <div className="workspace__player-error" role="alert">
            {playerError}
          </div>
        ) : null}
      </div>

      <TabBar tabs={WORKSPACE_TABS} active={active} onSelect={setActive} />

      {error ? (
        <div className="workspace__error" role="alert">
          {error}
        </div>
      ) : null}

      <div className="workspace__body" role="tabpanel">
        <Suspense fallback={<div className="panel panel--loading">Loading…</div>}>
          {renderPanel()}
        </Suspense>
      </div>
    </div>
  );
}

export default Workspace;
