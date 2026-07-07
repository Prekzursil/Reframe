// TaskHub.tsx — the per-video TASK HUB landing (WU-3a1).
//
// The destination a video opens onto: a short header (which video) + four large
// job cards (Reframe to vertical / Make shorts / Add subtitles / Director) and a
// persistent "Advanced / all tools" affordance that drops into the full 13-tab
// Workspace unchanged. Purely presentational — it emits the chosen HubChoice and
// the coordinator (views/Edit.tsx) owns the routing. The last-used choice is
// marked so power users can re-pick at a glance (and the coordinator can resume).
import React from 'react';
import './taskHub.css';
import type { Video } from '../lib/rpc';
import { HUB_CARDS, type HubChoice } from '../lib/taskHub';

export interface TaskHubProps {
  /** The opened video the hub acts on. */
  video: Video;
  /** The last choice made for this video (marks the "Last used" affordance). */
  lastChoice: string | null;
  /** A job card — or the "Advanced / all tools" escape — was picked. */
  onChoose: (choice: HubChoice) => void;
}

// Decorative 24×24 stroke glyphs (currentColor), keyed by choice. Defined once at
// module scope: the wrapping <span> is aria-hidden and the visible card title
// carries the accessible name.
const ICONS: Record<HubChoice, React.ReactElement> = {
  // reframe — a portrait crop frame inside a landscape one.
  reframe: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
      <rect x="2" y="6" width="20" height="12" rx="1" />
      <rect x="9" y="3" width="6" height="18" rx="1" />
    </svg>
  ),
  // shorts — a clapperboard (mirrors the top-level "Make Shorts" nav glyph).
  shorts: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
      <path d="M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3Z" />
      <path d="m6.2 5.3 3.1 3.9" />
      <path d="m12.4 3.4 3.1 4" />
      <path d="M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    </svg>
  ),
  // subtitles — a caption card with two text lines.
  subtitles: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M7 12h4" />
      <path d="M15 12h2" />
      <path d="M7 15.5h2" />
      <path d="M13 15.5h4" />
    </svg>
  ),
  // director — a viewfinder / focus reticle (mirrors the Director nav glyph).
  director: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
      <path d="M3 7V5a2 2 0 0 1 2-2h2" />
      <path d="M17 3h2a2 2 0 0 1 2 2v2" />
      <path d="M21 17v2a2 2 0 0 1-2 2h-2" />
      <path d="M7 21H5a2 2 0 0 1-2-2v-2" />
      <circle cx="12" cy="12" r="1" />
      <path d="M18.944 12.33a1 1 0 0 0 0-.66 7.5 7.5 0 0 0-13.888 0 1 1 0 0 0 0 .66 7.5 7.5 0 0 0 13.888 0" />
    </svg>
  ),
  // advanced — a grid of all tools.
  advanced: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
};

/** The per-video hub: four job cards + the "all tools" escape. */
export function TaskHub({ video, lastChoice, onChoose }: TaskHubProps): React.ReactElement {
  return (
    <div className="task-hub" aria-label="Task hub">
      <header className="task-hub__head">
        <p className="task-hub__eyebrow">Video opened</p>
        <h1 className="task-hub__title" title={video.path}>
          {video.title}
        </h1>
        <p className="task-hub__sub">What do you want to do with it?</p>
      </header>

      <div className="task-hub__cards">
        {HUB_CARDS.map((card) => {
          const isLast = card.id === lastChoice;
          return (
            <button
              key={card.id}
              type="button"
              className={`task-hub__card${isLast ? ' is-last' : ''}`}
              onClick={() => onChoose(card.id)}
            >
              <span className="task-hub__card-icon" aria-hidden="true">
                {ICONS[card.id]}
              </span>
              <span className="task-hub__card-title">{card.title}</span>
              <span className="task-hub__card-blurb">{card.blurb}</span>
              {isLast ? <span className="task-hub__last">Last used</span> : null}
            </button>
          );
        })}
      </div>

      <button
        type="button"
        className={`task-hub__advanced${lastChoice === 'advanced' ? ' is-last' : ''}`}
        onClick={() => onChoose('advanced')}
      >
        <span className="task-hub__card-icon" aria-hidden="true">
          {ICONS.advanced}
        </span>
        <span className="task-hub__advanced-label">Advanced / all tools</span>
        <span className="task-hub__advanced-hint">Open the full editing workspace</span>
        {lastChoice === 'advanced' ? <span className="task-hub__last">Last used</span> : null}
      </button>
    </div>
  );
}

export default TaskHub;
