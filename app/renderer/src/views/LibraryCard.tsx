// LibraryCard.tsx — one content-first Library card (v1.5 §4). A re-skin of the
// shipped card: a real focusable OPEN button (aria-label = title + duration +
// status), a poster-frame thumb, additive meta (date + a FAILED attention badge +
// the quiet Transcript chip), the multi-select checkbox, and the "N shorts" label
// that opens the produced-shorts gallery (the P0 one-to-many affordance).
//
// A11Y: the open action and the select/remove/shorts controls are SIBLINGS, never
// nested inside one another (no nested-interactive); resting depth is the surface
// ladder + --elev-* (library-cards.css), not a border-everywhere box.
//
// SCOPE of the "finish the card" work, MEASURED at this tip. Three of the four
// asks were already satisfied by the shipped card; only the fourth is open, and
// two of them would be REGRESSIONS if done again:
//   * PRIMARY ACTION — EXISTS, and is the visually dominant control. The card
//     BODY is the button (`.library__item-open` below) and its accessible name
//     already begins with "Open" (cardAriaLabel -> "Open Talk, 10:05, no
//     transcript"). It is `background: transparent` ON PURPOSE
//     (library-cards.css:40-53) because the PARENT paints for it: `li.library__
//     item` is `--surface-raised` + `--elev-1` at rest (:29/:31), lifts with
//     `--shadow-raise` + `translateY(-3px)` on hover (:55-61), presses on active
//     (:69-72), takes `--focus-ring` on `:focus-visible` (:63-67) and shows
//     `cursor: pointer` (:52). Reading that one CHILD rule alone and concluding
//     "nothing paints as Open at rest" is a whole-component verdict drawn from a
//     single selector — the parent rule three declarations above refutes it.
//   * DEMOTE REMOVE — ALREADY DONE; doing it again would be a regression.
//     `.library__remove-btn` carries the GHOST voice (shell.css:520-527 — no
//     fill, no edge, no shadow at rest, `--text-muted`) with a never-filled
//     quiet-red hover (:588-593). It is the QUIETEST control here, not the
//     loudest.
//   * METADATA — DELIVERED to the limit of the record. `library.list` returns
//     id, path, title, addedAt, durationSec, hasTranscript, thumbnailPath and
//     nothing else (components/api.ts:65-78) — no resolution, codec or fps — so
//     duration (the poster badge) + container format (`sourceFormatLabel`) is
//     the entire available surface. Anything richer needs a sidecar field first.
//   * THE ONE RESIDUAL — no VISIBLE text on the card reads "Open"; the
//     affordance rides entirely on depth, cursor and the accessible name. On a
//     card with shorts the painted "N shorts" pill is a second text-labelled
//     control, so "the only labelled control is the destructive one" holds only
//     when shortsCount is 0. Closing the residual needs
//     `components/library-cards.css`, OUTSIDE this lane's file scope, so it is
//     reported rather than reached for.
//
// Two constraints for whoever closes that residual, both measured here:
//   1. Do NOT nest a control inside `.library__item-open` — it IS a <button>, so
//      a nested <button>Open</button> is invalid HTML and breaks keyboard/AT. A
//      non-interactive <span> is the shape that works. This is now enforced by a
//      TEST, not a comment (LibraryCard.test.tsx, "free of NESTED interactive").
//   2. Do NOT give the label fill or elevation — its parent already carries
//      `--surface-raised` + `--elev-1`, and a raised box inside a raised box
//      fights the documented depth-not-outline decision (library-cards.css:17-21).
// And not a shortcut: reusing `.library__shorts-label` to get a painted pill with
// zero CSS is reachable from this file, but that class is an INTERACTIVE voice —
// `cursor: pointer` (library-cards.css:208) plus a hover fill (:214-217) — so a
// non-interactive cue wearing it renders a phantom button. Being reachable inside
// file scope is not the same as being coherent.
import React, { useState } from 'react';

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
 *
 * The failure is remembered as the URL THAT FAILED, not as a boolean, so the
 * guard self-resets on a genuinely NEW poster URL instead of stranding the card
 * on the ▶ glyph until it unmounts.
 *
 * SCOPE, measured: NO transition currently reaches that benefit. This is PURE
 * DEFENSIVE HARDENING, not a fix for an observed bug. An <img> renders only
 * while `posterUrl` is non-empty, and `posterUrl` holds ONE value for the rest
 * of the component's lifetime — so `failedUrl !== posterUrl` is equivalent to a
 * boolean `!failed`, UNCONDITIONALLY (not merely "for a fixed data directory").
 * (It is NOT necessarily '' on the first render, as an earlier draft of this
 * note said: `useVideoThumbnail` seeds its state SYNCHRONOUSLY from
 * `thumbnailPath` (components/useVideoThumbnail.ts:51), so a row that already
 * carries a poster path is non-empty immediately. That does not disturb the
 * one-value-per-lifetime invariant, which is what the equivalence rests on.)
 * Three independent reasons, any ONE alone sufficient:
 *   1. The URL is a pure function of the STORED PATH STRING: `thumbMediaUrl`
 *      embeds the whole path and adds no cache-buster (Player.tsx:121-123), so
 *      the data ROOT is not an input to it.
 *   2. Nothing rewrites that string once non-empty. Its only writer is
 *      `set_thumbnail` (library.py:484-485, the sole `UPDATE entity SET
 *      thumbnail_path`), reached only by the on-demand generator
 *      (handlers/library_ops.py:183/:194) — and the renderer calls that RPC
 *      ONLY while `thumbnailPath` is empty, because the hook short-circuits
 *      first (components/useVideoThumbnail.ts:53-58).
 *   3. The list is IDENTITY-KEYED: Library.tsx renders `<LibraryCard
 *      key={video.id}>` (views/Library.tsx:797-798), so a sort / filter / search
 *      re-order cannot hand a SURVIVING mounted card a DIFFERENT video. That
 *      closes the last route by which one mounted card could ever observe a
 *      second non-empty poster URL.
 * So a data-DIRECTORY change re-roots the FILES but not the row `library.list`
 * returns; relink (relink.py never touches thumbnailPath) and keepCopy
 * (library.py:929-930 rewrites the project manifest, not the entity row) emit
 * none either; and a refreshed `thumbnailPath` prop on this mounted card —
 * which the hook DOES re-serve (useVideoThumbnail.ts:75) — resolves to the same
 * deterministic `data_dir/thumbnails/<id>.jpg`, hence the same URL. The
 * URL-keyed form is kept because it is strictly no-worse than the boolean and
 * self-heals if a future writer ever diverges the path, NOT because anything
 * reaches it today. UNVERIFIED that no OUT-OF-BAND writer exists (a hand-edited
 * DB, a future migration); settle it by changing the data directory with the
 * Library view open and logging whether `library.thumbnail` is ever dispatched
 * for a video whose row already holds a poster path — prediction: zero.
 */
function VideoThumb({ video }: { video: Video }): React.ReactElement {
  const posterUrl = useVideoThumbnail(thumbnailRpc, video.id, video.thumbnailPath ?? '');
  const [failedUrl, setFailedUrl] = useState('');
  const showImg = posterUrl !== '' && failedUrl !== posterUrl;

  return (
    <div className="library__thumb">
      {showImg ? (
        <img
          className="library__thumb-img"
          src={posterUrl}
          alt=""
          aria-hidden="true"
          onError={() => setFailedUrl(posterUrl)}
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
 * The source CONTAINER format for the card's quiet meta line — the extension of
 * `video.path`, uppercased ("MP4", "MOV"). The frozen `library.list` payload has
 * no resolution / codec / fps fields at all (`components/api.ts:65-78` — id,
 * path, title, addedAt, durationSec, hasTranscript, thumbnailPath), so the
 * container is the only technical fact the record actually supports; anything
 * richer has to come from the sidecar, not from a guess here.
 *
 * Returns '' when the path carries no usable extension (an extensionless file,
 * or a leading-dot name with no stem) so the caller drops the segment instead of
 * rendering a stray separator.
 */
function sourceFormatLabel(path: string): string {
  const match = /[^\\/.]\.([A-Za-z0-9]{1,5})$/.exec(path);
  return match ? match[1].toUpperCase() : '';
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
}: LibraryCardProps): React.ReactElement {
  const badges = cardBadges(video);
  const added = formatAdded(video.addedAt);
  // One quiet caption carries both technical facts the record supports, dot-
  // separated ("MP4 · Added 2026-06-11"). Either half may be missing, so the
  // line is assembled from the present parts and omitted entirely when empty —
  // never an orphan separator and never an empty <span>.
  const meta = [sourceFormatLabel(video.path), added ? `Added ${added}` : '']
    .filter(Boolean)
    .join(' · ');

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
        <button
          type="button"
          className="library__remove-btn"
          aria-label={`Remove ${video.title}`}
          onClick={(event) => onRemove(video.id, event)}
        >
          Remove
        </button>
      </div>
    </li>
  );
}

export default LibraryCard;
