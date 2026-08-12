// LibraryCard.tsx — one content-first Library card (v1.5 §4). A re-skin of the
// shipped card: a real focusable OPEN button (aria-label = title + duration +
// status), a poster-frame thumb, additive meta (format + date + a FAILED attention
// badge + the quiet Transcript chip), the multi-select checkbox, and the "N shorts"
// label that opens the produced-shorts gallery (the P0 one-to-many affordance).
//
// v1.5b — "the card has no primary action". Precisely: the open affordance EXISTED
// (this `.library__item-open` button, keyboard- and SR-reachable) but was invisible
// — library-cards.css:40-53 strips its chrome (`border:none; background:transparent;
// padding:0`) and its only name is an aria-label. So on the rendered pixels the sole
// action VERB was the destructive "Remove", which made deletion read as the card's
// call to action. Three changes, all inside this file:
//   1. a VISIBLE CTA ("Open" / "Show history") painted inside the open button as a
//      non-interactive <span>, so the primary action finally has a label;
//   2. Remove demoted to an icon-only ghost control (accessible name kept on
//      aria-label + title) so the destructive action is no longer the peer — let
//      alone the only member — of the labelled-action set;
//   3. an overflow menu that deep-links into Deliver PRE-FILLED (L5-NAV G-3): the
//      card hands over `(video, shortcutId)` and nothing else. It never implements
//      conversion — a second converter here would be the tab-strip ratchet in a new
//      costume. Opt-in via the `deliver` prop, so a host that has not wired the
//      Deliver route yet renders exactly what it renders today.
//
// A11Y: the open action and the select/remove/shorts/overflow controls are SIBLINGS,
// never nested inside one another (no nested-interactive); resting depth is the
// surface ladder + --elev-* (library-cards.css), not a border-everywhere box. The
// overflow panel is ALWAYS mounted and merely toggles `hidden` (the WAI-ARIA
// disclosure rule CardProvenanceDisclosure already follows) so `aria-controls` is
// never a dangling IDREF.
//
// STILL OWED, and deliberately NOT faked here — this lane's file scope is this file
// alone, so it ships the structure and leaves the paint to a `library-cards.css`
// follow-up. Three rules that file must add:
//   * `.library__item-cta` has NO style yet, so the visible CTA currently renders as
//     inherited body text. It is the hook; it is not yet the button-weight the card
//     deserves.
//   * `.library__card-menu-trigger` / `-panel` / `-item` are likewise unstyled. The
//     panel is a plain absolute-less <div>; it needs positioning + a surface.
//   * TARGET SIZE (WCAG 2.5.8): the now icon-only `.library__remove-btn` and the "⋯"
//     trigger inherit only shell.css's `--control-pad-btn`. That is UNVERIFIED as
//     >=24x24 — and library-cards.css:236 explicitly sets `min-height:
//     var(--size-target-min)` on `.card-provenance__toggle`, which is evidence the
//     base padding alone was NOT judged sufficient. Settle it by measuring the two
//     controls' rendered box in the running app (the ui-audit tap-target gate), or
//     pre-empt it by adding the same `min-height` rule to both.
import React, { useId, useState } from 'react';

import { rpc } from '../components/api';
import type { Video } from '../components/api';
import { useVideoThumbnail, type VideoThumbnailRpc } from '../components/useVideoThumbnail';
import type { ProvenanceHandlers } from '../features/LibraryProvenance';
import { CardProvenanceDisclosure } from './CardProvenanceDisclosure';
import {
  type LibraryVideo,
  cardAriaLabel,
  cardBadges,
  formatAdded,
  formatDuration,
  shortsCountLabel,
  shortsOpenAriaLabel,
} from './libraryModel';
import '../components/library-cards.css';

/**
 * `library.thumbnail({id})` adapter over the shared `rpc` bridge — the thin RPC
 * slice `useVideoThumbnail` needs. Stable across renders so the hook's effect does
 * not re-fire every card render.
 */
const thumbnailRpc: VideoThumbnailRpc = {
  thumbnail: (videoId: string) =>
    rpc<{ thumbnailPath: string }>('library.thumbnail', { id: videoId }),
};

/**
 * Library-card poster: serves the source video's `thumb:` poster as a real <img>,
 * generating it on demand (idempotent server-side). A missing / failed poster
 * (empty URL or an <img> load error) falls back to the ▶ glyph and NEVER blocks
 * the gallery. The duration badge always renders (mm:ss).
 */
function VideoThumb({ video }: { video: Video }): React.ReactElement {
  const posterUrl = useVideoThumbnail(thumbnailRpc, video.id, video.thumbnailPath ?? '');
  const [imgFailed, setImgFailed] = useState(false);
  const showImg = posterUrl !== '' && !imgFailed;

  return (
    <div className="library__thumb">
      {showImg ? (
        <img
          className="library__thumb-img"
          src={posterUrl}
          alt=""
          aria-hidden="true"
          onError={() => setImgFailed(true)}
        />
      ) : (
        <div className="library__thumb-fallback" aria-hidden="true">
          ▶
        </div>
      )}
      <span className="library__thumb-duration">{formatDuration(video.durationSec)}</span>
    </div>
  );
}

/**
 * The source container shown on the card's meta line, derived from the file
 * extension of `path`.
 *
 * That extension is the ONLY format signal available: the FROZEN library payload
 * (`sidecar/contract/spec.py` `Video` → `components/api.ts:65`) carries exactly
 * `id/path/title/addedAt/durationSec/hasTranscript/thumbnailPath?` — there is no
 * container, codec or RESOLUTION field, so a "1080p" chip cannot be rendered
 * honestly here and is deliberately absent rather than guessed.
 *
 * Returns '' (meaning "say nothing") unless the BASENAME has a trailing dot
 * followed by 1-5 alphanumerics — so `C:\my.videos\talk` (dotted directory),
 * `.env` (leading dot, no name) and `talk.backupcopy` (not an extension) all
 * stay quiet instead of shouting a wrong format at the user.
 */
export function formatContainer(path: string): string {
  const base = path.slice(Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\')) + 1);
  const dot = base.lastIndexOf('.');
  if (dot <= 0) return '';
  const ext = base.slice(dot + 1);
  return /^[a-z0-9]{1,5}$/i.test(ext) ? ext.toUpperCase() : '';
}

/**
 * The card's ONE quiet meta line — "MP4 · Added 2026-06-11". Either half may be
 * unknown (see `formatContainer`; `formatAdded` returns '' for an unparseable
 * timestamp), and '' means the line is omitted entirely rather than rendered as a
 * stray separator. Duration is NOT repeated here: it already rides the poster as
 * the timecode badge (the editing-room convention), and printing it twice on one
 * card is noise, not information.
 */
export function cardMetaLine(video: LibraryVideo): string {
  const parts: string[] = [];
  const container = formatContainer(video.path);
  if (container) parts.push(container);
  const added = formatAdded(video.addedAt);
  if (added) parts.push(`Added ${added}`);
  return parts.join(' · ');
}

/**
 * The VISIBLE primary-action label. It must track `cardAriaLabel`'s verb, or the
 * card would show "Open" while activating the history drawer.
 */
export function cardActionLabel(lineageView: boolean): string {
  return lineageView ? 'Show history' : 'Open';
}

/** One pre-filled Deliver preset offered in the card's overflow menu. */
export interface DeliverShortcut {
  /** Which Deliver preset to pre-fill (e.g. 'convert' | 'nle' | 'tracks'). */
  id: string;
  /** The menu row's visible text. */
  label: string;
}

/**
 * The card's overflow-menu contract. The card owns NO catalogue and NO conversion
 * logic: the host supplies the shortcut list and receives `(video, shortcutId)` to
 * route into the Deliver form with the source pre-filled.
 */
export interface DeliverMenu {
  shortcuts: readonly DeliverShortcut[];
  onSelect: (video: LibraryVideo, shortcutId: string) => void;
}

/**
 * The trailing "⋯" overflow: a disclosure (not an ARIA menu widget) matching the
 * house pattern in `CardProvenanceDisclosure`. Choosing a row closes it, because a
 * shortcut that leaves its own menu open reads as a settings panel.
 */
function CardOverflowMenu({
  video,
  deliver,
}: {
  video: LibraryVideo;
  deliver: DeliverMenu;
}): React.ReactElement {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className="library__card-menu">
      <button
        type="button"
        className="library__card-menu-trigger"
        aria-label={`More actions for ${video.title}`}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">⋯</span>
      </button>

      <div id={panelId} className="library__card-menu-panel" hidden={!open}>
        {deliver.shortcuts.map((shortcut) => (
          <button
            key={shortcut.id}
            type="button"
            className="library__card-menu-item"
            onClick={() => {
              setOpen(false);
              deliver.onSelect(video, shortcut.id);
            }}
          >
            {shortcut.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export interface LibraryCardProps {
  video: LibraryVideo;
  /** Lineage view re-labels the open action + diverts it to the history drawer. */
  lineageView: boolean;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  onOpen: (video: LibraryVideo) => void;
  onRemove: (id: string, event: React.MouseEvent) => void;
  /** How many produced shorts this video has (the done-signal + gallery count). */
  shortsCount: number;
  onOpenShorts: (video: LibraryVideo) => void;
  /** L5 provenance handlers; when present the card shows its source-file row. */
  provenance?: ProvenanceHandlers;
  /**
   * Deliver deep-link shortcuts. OPTIONAL and additive: with no shortcuts wired
   * the card renders no overflow control at all, so a host that has not adopted
   * the Deliver route is unchanged.
   */
  deliver?: DeliverMenu;
}

export function LibraryCard({
  video,
  lineageView,
  selected,
  onToggleSelect,
  onOpen,
  onRemove,
  shortsCount,
  onOpenShorts,
  provenance,
  deliver,
}: LibraryCardProps): React.ReactElement {
  const badges = cardBadges(video);
  const meta = cardMetaLine(video);

  return (
    <li className="library__item">
      <label className="library__select">
        <input
          type="checkbox"
          className="library__select-box"
          checked={selected}
          aria-label={`Select ${video.title}`}
          onChange={() => onToggleSelect(video.id)}
        />
      </label>

      <button
        type="button"
        className="library__item-open"
        aria-label={cardAriaLabel(video, lineageView)}
        onClick={() => onOpen(video)}
      >
        <VideoThumb video={video} />
        <div className="library__item-main">
          <span className="library__item-title">{video.title}</span>
          {badges.length > 0 ? (
            <div className="library__chips">
              {badges.map((badge) => (
                <span
                  key={badge.kind}
                  className={`library__badge library__chip library__chip--${badge.kind}`}
                  title={badge.label}
                >
                  {badge.label}
                </span>
              ))}
            </div>
          ) : null}
          {provenance ? null : (
            <span className="library__item-path" title={video.path}>
              {video.path}
            </span>
          )}
          {meta ? <span className="library__item-added">{meta}</span> : null}
          {/* The visible primary action. A <span>, never a nested <button>: the
              enclosing .library__item-open already IS the control and owns the
              accessible name, so this is decoration and is hidden from AT to
              avoid announcing the verb twice. */}
          <span className="library__item-cta" aria-hidden="true">
            {cardActionLabel(lineageView)}
          </span>
        </div>
      </button>

      {provenance ? (
        <CardProvenanceDisclosure
          video={{ id: video.id, path: video.path, title: video.title }}
          handlers={provenance}
        />
      ) : null}

      <div className="library__item-meta">
        {shortsCount > 0 ? (
          <button
            type="button"
            className="library__shorts-label"
            aria-label={shortsOpenAriaLabel(shortsCount, video.title)}
            onClick={() => onOpenShorts(video)}
          >
            {shortsCountLabel(shortsCount)}
          </button>
        ) : null}
        {deliver && deliver.shortcuts.length > 0 ? (
          <CardOverflowMenu video={video} deliver={deliver} />
        ) : null}
        {/* Destructive, and therefore ICON-ONLY: the word "Remove" was the card's
            only visible verb, which made deletion look like the primary action.
            The accessible name is unchanged (aria-label), and `title` gives sighted
            users the same word on hover. */}
        <button
          type="button"
          className="library__remove-btn"
          aria-label={`Remove ${video.title}`}
          title="Remove"
          onClick={(event) => onRemove(video.id, event)}
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
    </li>
  );
}

export default LibraryCard;
