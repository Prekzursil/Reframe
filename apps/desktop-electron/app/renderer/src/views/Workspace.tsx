import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import './workspace.css';
import { TabBar, type TabDef } from '../components/TabBar';
import { Player, type PlayerHandle } from '../components/Player';
import { rpc, type Project, type Video } from '../components/api';
import { onJobDone } from '../lib/rpc';
import type { SubtitleTrack as FeatureSubtitleTrack } from '../features/_api';

export interface WorkspaceProps {
  /** The video opened from the Library. */
  video: Video;
  /** Return to the Library home. */
  onBack: () => void;
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

export const WORKSPACE_TABS: TabDef[] = [
  { id: 'transcribe', label: 'Transcribe' },
  { id: 'subtitles', label: 'Subtitles' },
  { id: 'tracks', label: 'Tracks' },
  { id: 'convert', label: 'Convert' },
  { id: 'shortmaker', label: 'Short-maker' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'dub', label: 'Dub' },
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
export function Workspace({ video, onBack }: WorkspaceProps): React.ReactElement {
  const [active, setActive] = useState<string>(WORKSPACE_TABS[0].id);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  // U1: the workspace player strip + its imperative handle (Timeline seeks it).
  const playerRef = useRef<PlayerHandle | null>(null);
  const [playerNote, setPlayerNote] = useState<string | null>(null);
  const [playerEpoch, setPlayerEpoch] = useState(0);

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

  // U1: when the source is not directly playable, kick the proxy build; on its
  // job.done remount the Player — the mstream resolver then serves the cached
  // proxy for the SAME URL. Operations keep using the original path.
  useEffect(() => {
    let alive = true;
    let offDone: (() => void) | null = null;
    rpc<{ playable: boolean; reason?: string; proxyPath?: string }>('media.playable', {
      videoId: video.id,
    })
      .then((v) => {
        if (!alive || v.playable) return undefined;
        setPlayerNote(v.reason ?? 'building playback proxy…');
        return rpc<{ jobId: string }>('media.proxy.start', { videoId: video.id }).then(
          (job) => {
            if (!alive || !job?.jobId) return;
            offDone = onJobDone((evt) => {
              if (evt.jobId !== job.jobId) return;
              setPlayerNote(null);
              setPlayerEpoch((n) => n + 1);
            });
          },
        );
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (offDone) offDone();
    };
  }, [video.id]);

  // components/api types `format` as plain string while the panels' _api uses
  // the SubtitleFormat union — identical wire shape, divergent TS layers
  // (consolidation = punch #11). Convert once at this boundary.
  const tracks = (project?.tracks ?? []) as unknown as FeatureSubtitleTrack[];

  function renderPanel(): React.ReactElement {
    switch (active) {
      case 'subtitles':
        return <Subtitles videoId={video.id} initialTrack={tracks[0] ?? null} />;
      case 'tracks':
        return <Tracks videoId={video.id} availableTracks={tracks} />;
      case 'convert':
        return <Convert videoId={video.id} path={video.path} />;
      case 'shortmaker':
        return <ShortMaker videoId={video.id} />;
      case 'timeline':
        return (
          <TimelinePanel
            videoId={video.id}
            durationSec={video.durationSec}
            playerRef={playerRef}
          />
        );
      case 'dub':
        return <Dub videoId={video.id} />;
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
        <Player ref={playerRef} videoId={video.id} key={`${video.id}:${playerEpoch}`} />
        {playerNote ? <div className="workspace__player-note">{playerNote}</div> : null}
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
