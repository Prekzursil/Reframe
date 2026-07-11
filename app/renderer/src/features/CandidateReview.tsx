// CandidateReview.tsx — the short-maker candidate-review panel (presentational).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). Holds the live preview (Player +
// CaptionOverlay), the rank/virality sort toggle, the CandidateList, and the
// keyboard-hint legend. Pure presentational: selection/playback state, cues and
// every handler live in the ShortMaker container; the keydown handler is passed
// down so the focusable group keeps its T6 keyboard semantics. The DOM is
// byte-identical to the inline JSX it replaced.

import React, { useEffect, useState } from 'react';

import { Player, type PlayerHandle, type PlayerWindow } from '../components/Player';
import { CaptionOverlay } from '../components/CaptionOverlay';
import { isNoCaption } from '../lib/captionTemplates';
import type { Cue } from '../lib/rpc';
import { CandidateList } from './CandidateList';
import { type CandidateSort, sortReviewItems } from './shortMakerPresets';
import {
  type ReviewItem,
  type ShortMakerControls,
  fmtTime,
  previewWindow,
} from './shortMakerLogic';

export interface CandidateReviewProps {
  items: ReviewItem[];
  selectedId: string | null;
  selected: ReviewItem | null;
  controls: ShortMakerControls;
  videoId: string;
  cues: Cue[];
  currentTime: number;
  playerEpoch: number;
  sortMode: CandidateSort;
  playerRef: React.Ref<PlayerHandle>;
  onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
  onTimeUpdate: (t: number) => void;
  setSortMode: (mode: CandidateSort) => void;
  setSelectedId: (id: string) => void;
  onApprove: (id: string) => void;
  onDiscard: (id: string) => void;
  onReinstate: (id: string) => void;
  onNudge: (id: string, deltaStart: number, deltaEnd: number) => void;
  onReset: (id: string) => void;
}

/**
 * The candidate-review group: live preview + caption overlay, sort toggle,
 * candidate list, and the keyboard-hint legend. Rendered only while candidates
 * exist (the container gates it, but we also guard so it is safe to mount).
 */
export function CandidateReview({
  items,
  selectedId,
  selected,
  controls,
  videoId,
  cues,
  currentTime,
  playerEpoch,
  sortMode,
  playerRef,
  onKeyDown,
  onTimeUpdate,
  setSortMode,
  setSelectedId,
  onApprove,
  onDiscard,
  onReinstate,
  onNudge,
  onReset,
}: CandidateReviewProps): React.JSX.Element | null {
  // A decode/resolver failure on the preview Player must be SHOWN, not swallowed
  // into a silent black frame (a reviewer could otherwise approve a clip they
  // never saw). Player.onError surfaces it here; mirrors Workspace's player-error
  // banner. View-local + transient — cleared whenever the previewed source
  // changes (another candidate, a new video, or a proxy reload).
  const [previewError, setPreviewError] = useState<string | null>(null);
  useEffect(() => {
    setPreviewError(null);
  }, [selectedId, videoId, playerEpoch]);

  if (items.length === 0) return null;

  // P4 §7: the DISPLAY order of the candidate list (ids unchanged, so selection
  // + keyboard nav still address the same items).
  const sortedItems = sortReviewItems(items, sortMode);
  const preview: PlayerWindow | null = selected ? previewWindow(selected.current) : null;

  return (
    <div
      className="sm-review"
      role="group"
      aria-label="Candidate review"
      // Lane 0 F4 (R-M10): advertise the single-letter shortcuts to AT so they
      // are discoverable, not just visually hinted by the legend below.
      aria-keyshortcuts="J K Space A X ArrowLeft ArrowRight"
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      {selected && preview && (
        <div
          className="sm-preview"
          aria-label={`Preview rank ${selected.current.rank}`}
          data-source-start={selected.current.sourceStart}
          data-window-start={preview.start}
          data-window-end={preview.end}
        >
          <div className="sm-phone">
            <Player
              ref={playerRef}
              // key is the videoId ONLY: selecting another candidate changes the
              // `window` prop (the Player re-seeks via its window effect) and a
              // proxy swap rides `reloadToken` (a shake-free video.load()) — both
              // REUSE the element instead of remounting it mid-load (the visible
              // restart/shake bug). P4 §5's epoch is now the reload signal.
              key={videoId}
              videoId={videoId}
              window={preview}
              reloadToken={playerEpoch}
              onTimeUpdate={onTimeUpdate}
              onError={(message) => setPreviewError(message)}
            />
            {/* P4 §5: live caption overlay — mirrors the selected template +
                hook title so the reviewer sees how captions would look. No-ops
                on the "none" template (CaptionOverlay returns null). */}
            {!isNoCaption(controls.captionStyle) && (
              <CaptionOverlay
                cues={cues}
                templateId={controls.captionStyle}
                currentTime={currentTime}
                hookTitle={controls.hookTitle ? selected.current.hook : undefined}
                window={preview}
              />
            )}
            {previewError && (
              <div className="sm-preview-error" role="alert">
                {previewError}
              </div>
            )}
          </div>
          <div className="sm-preview-markers">
            <span className="sm-marker-in" aria-label="In point">
              ⊢ {fmtTime(preview.start)}
            </span>
            <span className="sm-marker-out" aria-label="Out point">
              {fmtTime(preview.end)} ⊣
            </span>
          </div>
        </div>
      )}
      {/* P4 §7: candidate sort toggle (sidecar rank ↔ viralityPct). */}
      <div className="sm-sort" role="group" aria-label="Sort candidates">
        <span className="sm-sort-label">Sort</span>
        <button
          type="button"
          className={`sm-sort-btn${sortMode === 'rank' ? ' is-active' : ''}`}
          aria-pressed={sortMode === 'rank'}
          onClick={() => setSortMode('rank')}
        >
          Rank
        </button>
        <button
          type="button"
          className={`sm-sort-btn${sortMode === 'virality' ? ' is-active' : ''}`}
          aria-pressed={sortMode === 'virality'}
          onClick={() => setSortMode('virality')}
        >
          Virality
        </button>
      </div>
      <CandidateList
        items={sortedItems}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onApprove={onApprove}
        onDiscard={onDiscard}
        onReinstate={onReinstate}
        onNudge={onNudge}
        onReset={onReset}
      />
      {/* T6 legend — exposed to AT (Lane 0 F4 / R-M10): the single-letter
          shortcuts must be discoverable, so it is no longer aria-hidden. */}
      <div className="sm-kbd-hints" aria-label="Keyboard shortcuts">
        <span>
          <kbd>J</kbd>
          <kbd>K</kbd> select
        </span>
        <span>
          <kbd>Space</kbd> play / pause
        </span>
        <span>
          <kbd>A</kbd> approve
        </span>
        <span>
          <kbd>X</kbd> discard
        </span>
        <span>
          <kbd>←</kbd>
          <kbd>→</kbd> slide window
        </span>
        <span>
          <kbd>Shift</kbd> fine 0.2s
        </span>
      </div>
    </div>
  );
}

export default CandidateReview;
