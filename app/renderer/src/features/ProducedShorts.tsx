// ProducedShorts.tsx — the per-video produced-shorts gallery (presentational).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget
// (coding-style.md: files <800 lines). P4 §6 / C11: after export the container
// reloads shorts.list {videoId}; this component renders the resulting clips with
// the gallery card actions (play / open-folder / re-export / delete). Pure
// presentational — all RPC/state live in the ShortMaker container. DOM is
// byte-identical to the inline JSX it replaced.

import React from 'react';

import { Player, shortMediaUrl } from '../components/Player';
import { ShortClipActions } from '../components/ShortClipActions';
import type { ShortInfo } from '../lib/rpc';

export interface ProducedShortsProps {
  shorts: ShortInfo[];
  /** Path of the clip currently inline-playing ('' = none). */
  playingShortPath: string;
  onPlay: (path: string) => void;
  onOpenFolder: (path: string) => void;
  onReexport: (path: string) => void;
  onDelete: (path: string) => void;
}

/**
 * The "Produced shorts" grid for the current video. Renders nothing until at
 * least one short exists (the container gates this, but we also guard here so
 * the component is safe to mount unconditionally).
 */
export function ProducedShorts({
  shorts,
  playingShortPath,
  onPlay,
  onOpenFolder,
  onReexport,
  onDelete,
}: ProducedShortsProps): React.JSX.Element | null {
  if (shorts.length === 0) return null;
  return (
    <div className="sm-video-shorts" aria-label="Produced shorts">
      <h3>Produced shorts</h3>
      <ul className="shorts__grid shorts__grid--inline">
        {shorts.map((short) => {
          const title = short.sourceTitle || short.hook || short.path;
          return (
            <li className="shorts__card" data-id={short.id} key={short.id}>
              <div className="shorts__thumb">
                {playingShortPath === short.path ? (
                  <Player
                    className="shorts__player"
                    src={shortMediaUrl(short.path)}
                    autoPlay
                    controls
                  />
                ) : (
                  <button
                    type="button"
                    className="shorts__thumb-btn"
                    aria-label={`Play preview of ${title}`}
                    onClick={() => onPlay(short.path)}
                  >
                    <span className="shorts__thumb-glyph" aria-hidden="true">
                      ▶
                    </span>
                  </button>
                )}
                {typeof short.viralityPct === 'number' && (
                  <span className="shorts__virality" aria-label="Virality">
                    {short.viralityPct}
                    <span className="shorts__virality-pct">%</span>
                  </span>
                )}
              </div>
              {short.template && (
                <span className="shorts__template" aria-label="Caption template">
                  {short.template}
                </span>
              )}
              <ShortClipActions
                path={short.path}
                label={title}
                playing={playingShortPath === short.path}
                onPlay={onPlay}
                onOpenFolder={onOpenFolder}
                onReexport={onReexport}
                onDelete={onDelete}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default ProducedShorts;
