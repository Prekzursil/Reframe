// ExportStage.tsx — the SHARED export stage (v1.5 §4, inspector-over-shared-stage).
//
// The one video surface the Export inspector talks about: a THIN CONSUMER of the
// shared editor state (`useEditor`) that previews the exact clip being exported and
// summarizes what is BAKED into it — its length, its captions (from the cues), and
// its framing (reframed vs original, read from the cross-phase cropPlan WITHOUT
// leaking the engine id). It owns no export controls; those live in the inspector.

import React from 'react';
import { Player } from '../../components/Player';
import { fmtSeconds } from '../_api';
import { useEditor } from '../EditorContext';
import { captionSummary, framingSummary } from './exportModel';
import './export.css';

/** The shared export preview: the clip + a plain "what will be baked" summary. */
export function ExportStage(): React.ReactElement {
  const { state } = useEditor();
  const { video } = state;
  const win = video.window;

  return (
    <div className="export-stage" aria-label="Export preview">
      <div className="export-stage__frame">
        <Player videoId={video.videoId} src={video.src} window={win} controls />
      </div>
      <div className="export-stage__summary">
        <div className="export-stage__item">
          <span className="export-stage__label">Length</span>
          <span className="export-stage__value">{fmtSeconds(win.end - win.start)}</span>
        </div>
        <div className="export-stage__item">
          <span className="export-stage__label">Captions</span>
          <span className="export-stage__value">{captionSummary(state)}</span>
        </div>
        <div className="export-stage__item">
          <span className="export-stage__label">Framing</span>
          <span className="export-stage__value">{framingSummary(state)}</span>
        </div>
      </div>
    </div>
  );
}

export default ExportStage;
