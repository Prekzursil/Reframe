// Director.tsx — the DIRECTOR phase view (v1.5, §4 "Director").
//
// The first-class rail destination for prompt-driven AI editing, built ON the
// shipped DirectorPanel (COMPOSED, not rewritten) inside the ONE consciously
// low-density, editorial-spacious screen — the strongest home for the serif
// display voice, left-anchored and composed so no form is stranded in dead space.
//
// It seeds the shared EditorContext from the open video and reads that video's
// word-level cues via the typed #282 client (so the hand-off's Caption landing
// zone reflects whether a transcript already exists), then composes the
// DirectorPanel (planning / reviewable storyboard / cost-egress banner / apply
// gate / one-shot undo) beside the DirectorHandoff — the surface that makes the
// "output lands as REVIEWABLE per-phase diffs, nothing applied until you confirm"
// promise legible (cuts -> Edit, keyframes -> Caption, crop -> Reframe). The
// provider remounts per video (`key`) so a video switch re-seeds cleanly. With no
// video open, the DirectorPanel's own "No video open" empty state carries the CTA.

import React, { useEffect, useState } from 'react';
import { type Cue, type Video, client, hasApi } from '../lib/rpc';
import type { EditorSeed } from '../lib/editorState';
import { EditorProvider, useEditor } from '../features/EditorContext';
import { DirectorPanel } from '../panels/DirectorPanel';
import { DirectorHandoff } from '../features/director/DirectorHandoff';
import './director.css';

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Read the cue list off a captions.cues response (defensive against a malformed body). */
function cuesOf(res: { cues?: Cue[] }): Cue[] {
  return res.cues ?? [];
}

export interface DirectorProps {
  video: Video | null;
  /** Route to the Library — the shell back control AND the DirectorPanel empty CTA. */
  onChooseVideo: () => void;
}

/** The editorial screen chrome: the serif hero + a back control + a low lede. */
function DirectorFrame({
  onChooseVideo,
  children,
}: {
  onChooseVideo: () => void;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <section className="director-view" aria-label="Director">
      <header className="director-view__head">
        <button type="button" className="director-view__back" onClick={onChooseVideo}>
          ← Library
        </button>
        <h1 className="director-view__title">Direct the edit</h1>
        <p className="director-view__lede">
          One prompt in. A reviewable plan out — phase by phase.
        </p>
      </header>
      {children}
    </section>
  );
}

/** Inner workspace: seeds the editor, loads cues, composes the panel + hand-off. */
function DirectorWorkspace({
  video,
  onChooseVideo,
}: {
  video: Video;
  onChooseVideo: () => void;
}): React.ReactElement {
  const { dispatch } = useEditor();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasApi()) return;
    void client.captions
      .cues(video.id)
      .then((res) => dispatch({ type: 'setCues', cues: cuesOf(res) }))
      .catch((err) => setError(errText(err)));
  }, [video.id, dispatch]);

  return (
    <DirectorFrame onChooseVideo={onChooseVideo}>
      {error && (
        <p className="director-view__error" role="alert">
          {error}
        </p>
      )}
      <div className="director-view__body">
        <div className="director-view__main">
          <DirectorPanel video={video} onChooseVideo={onChooseVideo} />
        </div>
        <DirectorHandoff />
      </div>
    </DirectorFrame>
  );
}

export function Director({ video, onChooseVideo }: DirectorProps): React.ReactElement {
  if (!video) {
    return (
      <DirectorFrame onChooseVideo={onChooseVideo}>
        <div className="director-view__body director-view__body--empty">
          <DirectorPanel video={null} onChooseVideo={onChooseVideo} />
        </div>
      </DirectorFrame>
    );
  }

  const seed: EditorSeed = {
    video: {
      videoId: video.id,
      window: { start: 0, end: video.durationSec },
      durationSec: video.durationSec,
    },
  };

  return (
    <EditorProvider key={video.id} seed={seed}>
      <DirectorWorkspace video={video} onChooseVideo={onChooseVideo} />
    </EditorProvider>
  );
}

export default Director;
