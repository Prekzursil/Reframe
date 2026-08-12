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
//      Deliver route yet renders exactly what it renders today — which, at HEAD, is
//      EVERY host: see SCOPE-ESCAPE 1. Item 3 is a contract, not a shipped feature.
//
// A11Y: the open action and the select/remove/shorts/overflow controls are SIBLINGS,
// never nested inside one another (no nested-interactive); resting depth is the
// surface ladder + --elev-* (library-cards.css), not a border-everywhere box. The
// overflow panel is ALWAYS mounted and merely toggles `hidden` (the WAI-ARIA
// disclosure rule CardProvenanceDisclosure already follows) so `aria-controls` is
// never a dangling IDREF. The visible CTA tracks `cardAriaLabel`'s verb, so the
// accessible name still STARTS with the visible string (WCAG 2.5.3 Label in Name).
//
// SCOPE-ESCAPE — declared, not deferred. This lane's file scope is this file alone,
// so two of the three items above cannot LAND here. They are reported up rather than
// described as shipped; a residual reads as optional polish, and these are not.
//
//   1. WI-3 IS STRUCTURE ONLY AND RENDERS IN ZERO PIXELS. `deliver` is optional and
//      the sole production mount — views/Library.tsx — never passes it
//      (`git grep -c deliver -- app/renderer/src/views/Library.tsx` returns 0 at
//      origin/main). PR #423 owns Library.tsx, so the wiring is a SCOPE-ESCAPE into
//      that file, not a residual of this one. Until it lands, CardOverflowMenu and
//      its tests describe a contract the app never instantiates.
//
//   2. WI-1/WI-2 SHIP THE SEMANTIC HALF; THE PAINT IS A SCOPE-ESCAPE INTO
//      components/library-cards.css. `.library__item-cta` and
//      `.library__card-menu-trigger` / `-panel` / `-item` have ZERO rules anywhere in
//      the tree, and `.library__item-open` is `padding:0; border:none;
//      background:transparent; font:inherit` (library-cards.css:40-53) inside a plain
//      flex column, so at HEAD the CTA paints as an ordinary body-text line under the
//      meta line — a primary action in the DOM, a stray word on the pixels — while
//      `.library__remove-btn` keeps its whole box and merely loses its word. Net:
//      Remove is still the only element on the card that reads as a control. That CSS
//      must land in the SAME release or the card is worse than before, not better.
//
// TWO TRAPS THE CSS LANE INHERITS, measured here so it does not rediscover them:
//   * `[hidden]` vs `display`. The panel is hidden ONLY by the UA `[hidden] {
//     display: none }` rule. `.library__card-menu-panel` and `[hidden]` are both
//     specificity 0-1-0, so ANY `display:` declaration added to that class wins on
//     source order and silently un-hides the closed panel — while every overflow test
//     stays green, because they assert `panel.hidden === true`, never computed
//     display. Scope it: `.library__card-menu-panel:not([hidden]) { display: … }`.
//   * TARGET SIZE (WCAG 2.5.8) — SPLIT by measurement, not carried as one blanket
//     risk. `.library__remove-btn` IS named in shell.css:395-401's raised-voice list,
//     so it takes `--control-pad-btn` = 6px 14px (tokens.css:199) at
//     `--type-control-size` 12px (:159) plus 1px borders => >=26px tall and ~37px
//     wide against `--size-target-min` 24px (:192): MET at AA (AAA 44x44 still fails).
//     The "⋯" trigger is NOT in that list and the Library view has no `.feature-panel`
//     ancestor (that list is explicit classes, not a bare `button` selector), so it
//     alone falls through to raw Chromium UA chrome and is the control genuinely at
//     risk. CORRECTION: an earlier draft of this header cited library-cards.css:236 as
//     evidence the base padding was judged insufficient — that was a MISREAD.
//     `.card-provenance__toggle` uses `--space-1 --space-2` + the caption font, not
//     `--control-pad-btn`, which is precisely why it needed its own min-height; it is
//     silent about the raised voice. Settle the trigger with the ui-audit tap-target
//     gate, or pre-empt it with a `min-height: var(--size-target-min)` rule.
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
 * The trailing "⋯" overflow: a DISCLOSURE, not an ARIA menu widget — exactly the
 * contract `CardProvenanceDisclosure` (:42-57) uses, `aria-expanded` +
 * `aria-controls` + an always-mounted `hidden` panel, and nothing more.
 *
 * It deliberately does NOT set `aria-haspopup`. ARIA 1.2 makes
 * `aria-haspopup="true"` a synonym for `"menu"`, so it would announce a menu
 * button over a popup that keeps none of the APG menu-button contract: no
 * `role="menu"`/`"menuitem"`, no roving tabindex, no arrow keys, no Escape, no
 * focus return to the trigger. No axe rule flags a haspopup/role mismatch, so
 * nothing but the pinned assertion in LibraryCard.test.tsx guards it. A later
 * lane wanting real menu semantics must add the WHOLE contract, not the
 * attribute — and once library-cards.css turns the panel into a positioned
 * overlay, outside-click dismissal becomes genuinely owed too.
 *
 * Choosing a row closes it, because a shortcut that leaves its own menu open
 * reads as a settings panel.
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
        {/* Destructive, and therefore LABELLED. Round 2 reversed an earlier draft
            that demoted this to an icon-only `×` + `title="Remove"`: this control
            has no resting box to fall back on (the GHOST voice at shell.css:520-529
            zeroes its background, border-colour and shadow), it deletes with NO
            confirm and NO undo (views/Library.tsx:386-419), and `title` surfaces on
            mouse-hover dwell but not on keyboard focus — so the glyph left a
            keyboard user an unnamed control on an irreversible action. Remove stops
            being the primary-action PEER by the CTA gaining weight, not by the
            destructive verb losing its name. */}
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
