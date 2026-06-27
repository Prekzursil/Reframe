// Edit.tsx — the V1 "Edit" SECTION (manual per-video editing, IA §h).
//
// Edit is the per-video manual surface: Trim / Cut / Join / Reorder / Reframe /
// Stabilize / Cleanup + Transcript & Captions + Audio. Those panels already
// live in the per-video Workspace (the tabbed body), so Edit hosts the Workspace
// for the currently-open video and shows a clear empty state when none is open
// (the user opens a video from the Library, which routes here). NOTHING is
// deleted — every existing edit/transcript/audio capability remains reachable.
import React from 'react';
import { Workspace } from './Workspace';
import type { Video } from '../lib/rpc';

export interface EditProps {
  /** The video to edit, or null when none has been opened yet. */
  video: Video | null;
  /** Return to the Library home. */
  onBack: () => void;
}

/** The Edit section: the per-video Workspace, or an empty state. */
export function Edit({ video, onBack }: EditProps): React.ReactElement {
  if (!video) {
    return (
      <div className="edit edit--empty" aria-label="Edit">
        <p className="edit__empty-title">No video open</p>
        <p className="edit__empty-hint">
          Open a video from the Library to trim, cut, join, reframe, caption, and more — every edit
          tool lives here.
        </p>
      </div>
    );
  }
  return <Workspace video={video} onBack={onBack} />;
}

export default Edit;
