// Caption.tsx — the CAPTION phase view (v1.5 pilot, §7.2).
//
// The integration point that makes the pilot real in the shell: it seeds the
// shared EditorContext from the open video, loads that video's word-level cues via
// the TYPED #282 client (`client.captions.cues`, not the old stringly rpc), and
// composes the shared Stage + keyboard clip lane + Inspector — each a thin consumer
// of the one editor state. Generating captions (no transcript yet) runs
// `client.subtitles.generate` then re-reads the cues, again through the typed
// client. The provider remounts per video (`key`) so a video switch re-seeds cleanly.

import React, { useCallback, useEffect, useState } from 'react';
import { type Cue, type Video, client, hasApi } from '../lib/rpc';
import type { EditorSeed } from '../lib/editorState';
import { EditorProvider, useEditor } from '../features/EditorContext';
import { CaptionStage } from '../features/caption/CaptionStage';
import { CaptionClipLane } from '../features/caption/CaptionClipLane';
import { CaptionInspector } from '../features/caption/CaptionInspector';
import './caption.css';

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Read the cue list off a captions.cues response (defensive against a malformed body). */
function cuesOf(res: { cues?: Cue[] }): Cue[] {
  return res.cues ?? [];
}

export interface CaptionProps {
  video: Video | null;
  onBack: () => void;
}

/** Inner workspace: a context consumer that loads/generates cues + composes panels. */
function CaptionWorkspace({
  video,
  onBack,
}: {
  video: Video;
  onBack: () => void;
}): React.ReactElement {
  const { dispatch } = useEditor();
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!hasApi()) return;
    void client.captions
      .cues(video.id)
      .then((res) => dispatch({ type: 'setCues', cues: cuesOf(res) }))
      .catch((err) => setError(errText(err)));
  }, [video.id, dispatch]);

  const generate = useCallback(async () => {
    if (!hasApi()) return;
    setGenerating(true);
    setError(null);
    try {
      await client.subtitles.generate(video.id);
      const res = await client.captions.cues(video.id);
      dispatch({ type: 'setCues', cues: cuesOf(res) });
    } catch (err) {
      setError(errText(err));
    } finally {
      setGenerating(false);
    }
  }, [video.id, dispatch]);

  return (
    <section className="caption-view" aria-label="Caption editor">
      <header className="caption-view__head">
        <button type="button" className="caption-view__back" onClick={onBack}>
          ← Library
        </button>
        <h2 className="caption-view__title">{video.title}</h2>
      </header>
      {error && (
        <p className="caption-view__error" role="alert">
          {error}
        </p>
      )}
      <div className="caption-view__body">
        <div className="caption-view__stage">
          <CaptionStage />
          <CaptionClipLane />
        </div>
        <CaptionInspector onGenerate={() => void generate()} generating={generating} />
      </div>
    </section>
  );
}

export function Caption({ video, onBack }: CaptionProps): React.ReactElement {
  if (!video) {
    return (
      <section className="caption-view caption-view--empty" aria-label="Caption editor">
        <div className="caption-view__empty">
          <h2 className="caption-view__empty-title">Open a video to caption</h2>
          <p className="caption-view__empty-blurb">
            Pick a video from the Library to design and time its captions.
          </p>
          <button type="button" className="caption-view__back" onClick={onBack}>
            ← Library
          </button>
        </div>
      </section>
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
      <CaptionWorkspace video={video} onBack={onBack} />
    </EditorProvider>
  );
}

export default Caption;
