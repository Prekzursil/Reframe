// CaptionInspector.tsx — the Caption phase inspector (v1.5 pilot, §4/§7.2).
//
// The inspector-over-shared-stage proof: this panel is a THIN CONSUMER of the
// shared editor state (`useEditor`) that COMPOSES the shipped, verified caption
// controls — the look-named preset gallery, the CaptionCustomizer tuning
// disclosure, and the guarded burn/soft delivery choice — and dispatches their
// edits back into the ONE state the Stage renders. It owns no layout of the
// stage/timeline and no copy of the design; it only reads + writes context.
//
// Transcript gate (§2 disagreement 7): caption styling has a TRUE data dependency
// on a transcript, so with no cues the inspector shows a single, explicit
// "generate captions first" state instead of a wall of dead controls — the one
// place the Caption phase is legitimately disabled.

import React, { useState } from 'react';
import { CaptionCustomizer } from '../../components/CaptionCustomizer';
import type { CaptionContentContext } from '../../lib/captionDefaults';
import { transcriptReady } from '../../lib/editorState';
import { useEditor } from '../EditorContext';
import { CaptionGallery } from './CaptionGallery';
import { CaptionDelivery, type CaptionDeliveryMode } from './CaptionDelivery';
import './captionInspector.css';

export interface CaptionInspectorProps {
  /** Invoked when the user asks to generate captions (shown while no transcript). */
  onGenerate?: () => void;
  /** True while a generate request is in flight (disables the generate button). */
  generating?: boolean;
  /** Per-language reading-speed context threaded to the customizer. */
  content?: CaptionContentContext;
}

export function CaptionInspector({
  onGenerate,
  generating = false,
  content,
}: CaptionInspectorProps): React.ReactElement {
  const { state, dispatch } = useEditor();
  const [delivery, setDelivery] = useState<CaptionDeliveryMode>('soft');

  if (!transcriptReady(state)) {
    return (
      <aside className="caption-inspector" aria-label="Caption inspector">
        <div className="caption-inspector__empty">
          <h3 className="caption-inspector__empty-title">Generate captions first</h3>
          <p className="caption-inspector__empty-blurb">
            Caption styling needs a transcript. Generate captions to unlock the style gallery, text
            tuning, and delivery options.
          </p>
          <button
            type="button"
            className="caption-inspector__generate"
            disabled={generating}
            onClick={onGenerate}
          >
            {generating ? 'Generating…' : 'Generate captions'}
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="caption-inspector" aria-label="Caption inspector">
      <CaptionGallery
        value={state.design.style}
        onChange={(style) => dispatch({ type: 'setStyle', style })}
      />
      <CaptionCustomizer
        value={state.design.override}
        onChange={(override) => dispatch({ type: 'setOverride', override })}
        style={state.design.style}
        content={content}
      />
      <CaptionDelivery value={delivery} onChange={setDelivery} />
    </aside>
  );
}

export default CaptionInspector;
