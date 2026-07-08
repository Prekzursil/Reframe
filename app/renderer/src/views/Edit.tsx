// Edit.tsx — the V1 "Edit" SECTION (per-video editing, IA §h) + the TASK HUB
// landing (WU-3a1).
//
// Opening a video from the Library routes here. Instead of dropping the user
// straight into the 13-tab Workspace on Transcribe (a prerequisite, not a
// destination), Edit now LANDS on a per-video Task Hub: four large job cards
// (Reframe to vertical / Make shorts / Add subtitles / Director), each routing
// into the RIGHT EXISTING flow, plus a persistent "Advanced / all tools" escape
// that opens the full Workspace UNCHANGED. Nothing is deleted — every edit /
// transcript / audio capability stays reachable (via a card or the escape), and
// when no video is open the same empty state shows.
//
// ADDITIVE: the four cards route into existing surfaces, never reimplementations —
//   - Reframe to vertical → Workspace @ the Short-maker tab (the reframe engine),
//   - Add subtitles       → Workspace @ the Subtitles tab,
//   - Make shorts         → the top-level Make Shorts section (onMakeShorts),
//   - Director            → the top-level AI Director section (onDirector).
// The last choice is remembered per video so a returning power user resumes the
// workspace-scoped tool in place rather than seeing the hub again.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Workspace } from './Workspace';
import { TaskHub } from './TaskHub';
import { hasApi, rpc, type Video } from '../lib/rpc';
import {
  HUB_CHOICE_KEY,
  type HubChoice,
  mergeHubChoice,
  readHubChoice,
  resumeFor,
} from '../lib/taskHub';

export interface EditProps {
  /** The video to edit, or null when none has been opened yet. */
  video: Video | null;
  /** Return to the Library home. */
  onBack: () => void;
  /** Route to the top-level Make Shorts section (the "Make shorts" job card). */
  onMakeShorts?: () => void;
  /**
   * WU-3a4: route to the top-level Make Shorts section PRE-SELECTED to a video —
   * the Workspace "Short-maker" tab deep-links here (the single ShortMaker owner)
   * rather than mounting a second copy in the Workspace.
   */
  onMakeShortsForVideo?: (videoId: string) => void;
  /** Route to the top-level AI Director section (the "Director" job card). */
  onDirector?: () => void;
}

/**
 * The per-video body: the Task Hub landing, or (on a card / advanced pick, or a
 * remembered workspace choice) the full Workspace. Split out so `video` is always
 * non-null here — the null case is the empty state in `Edit` below.
 */
function EditVideo({
  video,
  onBack,
  onMakeShorts,
  onMakeShortsForVideo,
  onDirector,
}: EditProps & { video: Video }): React.ReactElement {
  const [mode, setMode] = useState<'hub' | 'workspace'>('hub');
  // The Workspace tab to land on (null = its own default first tab).
  const [tab, setTab] = useState<string | null>(null);
  const [lastChoice, setLastChoice] = useState<string | null>(null);
  // The last-read settings blob, kept so a persist is a read-modify-write that
  // preserves OTHER videos' remembered choices without a second settings.get.
  const settingsRef = useRef<Record<string, unknown> | null>(null);
  const videoId = video.id;

  // On (re)open of a video: reset to the hub, then best-effort read the remembered
  // choice — a workspace-scoped one resumes IN PLACE so a returning power user is
  // not slowed by the hub; a section choice only marks "last used".
  useEffect(() => {
    setMode('hub');
    setTab(null);
    setLastChoice(null);
    settingsRef.current = null;
    if (!hasApi()) return;
    let cancelled = false;
    void rpc<Record<string, unknown>>('settings.get')
      .then((settings) => {
        if (cancelled) return;
        settingsRef.current = settings ?? null;
        const choice = readHubChoice(settings, videoId);
        setLastChoice(choice);
        const resume = resumeFor(choice);
        if (resume.kind === 'workspace') {
          setTab(resume.tab);
          setMode('workspace');
        }
      })
      .catch(() => {
        // Best-effort: a failed read simply keeps the hub landing.
      });
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  // Persist the picked choice for this video (best-effort, in-memory reflected
  // immediately). Read-modify-write against the cached settings so sibling videos'
  // choices survive.
  const persist = useCallback(
    (choice: string) => {
      setLastChoice(choice);
      const map = mergeHubChoice(settingsRef.current?.[HUB_CHOICE_KEY], videoId, choice);
      settingsRef.current = { ...(settingsRef.current ?? {}), [HUB_CHOICE_KEY]: map };
      if (!hasApi()) return;
      void rpc('settings.set', { [HUB_CHOICE_KEY]: map }).catch(() => {
        // Persisting is best-effort; the in-memory choice already reflects intent.
      });
    },
    [videoId],
  );

  const handleChoose = useCallback(
    (choice: HubChoice) => {
      persist(choice);
      const resume = resumeFor(choice);
      if (resume.kind === 'workspace') {
        setTab(resume.tab);
        setMode('workspace');
        return;
      }
      // Section choices route to a top-level surface (kept in App shell state).
      if (choice === 'shorts') {
        onMakeShorts?.();
        return;
      }
      onDirector?.();
    },
    [persist, onMakeShorts, onDirector],
  );

  if (mode === 'workspace') {
    return (
      <Workspace
        video={video}
        onBack={onBack}
        initialTab={tab ?? undefined}
        onOpenMakeShorts={onMakeShortsForVideo}
      />
    );
  }
  return <TaskHub video={video} lastChoice={lastChoice} onChoose={handleChoose} />;
}

/** The Edit section: the per-video Task Hub / Workspace, or an empty state. */
export function Edit({
  video,
  onBack,
  onMakeShorts,
  onMakeShortsForVideo,
  onDirector,
}: EditProps): React.ReactElement {
  if (!video) {
    return (
      <div className="edit edit--empty" aria-label="Edit">
        <div className="edit__empty-poster" aria-hidden="true">
          <span className="edit__empty-glyph">▶</span>
          <span className="edit__empty-timecode">--:--</span>
        </div>
        <p className="edit__empty-title">No video open</p>
        <p className="edit__empty-hint">
          Open a video from the Library to trim, cut, join, reframe, caption, and more — every edit
          tool lives here.
        </p>
      </div>
    );
  }
  return (
    <EditVideo
      video={video}
      onBack={onBack}
      onMakeShorts={onMakeShorts}
      onMakeShortsForVideo={onMakeShortsForVideo}
      onDirector={onDirector}
    />
  );
}

export default Edit;
