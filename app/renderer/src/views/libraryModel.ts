// libraryModel.ts — pure, render-free helpers for the content-first Library
// (v1.5). No React, no I/O: grouping produced shorts by source video, the
// search/sort model, the card's additive badges + meta, and the a11y open-label.
// Keeping the branchy logic here lets LibraryCard/Library stay thin render shells
// and pins each rule once (coverage + no drift). Everything returns NEW data.

import type { Video } from '../components/api';
import type { ShortInfo } from '../lib/rpc';

/**
 * A library video enriched with an OPTIONAL, forward-compatible processing
 * status. The frozen `library.list` payload carries no failure field yet, so
 * `failed` is `undefined` in production until the sidecar surfaces it (PR
 * follow-up: a `Video.status`/job-failure field). The FAILED badge and its
 * derivation are covered here + in LibraryCard so wiring it later is a one-liner.
 */
export type LibraryVideo = Video & { failed?: boolean };

/** How the library grid is ordered (the per-library sort control). */
export type LibrarySort = 'recent' | 'title' | 'duration' | 'shorts';

/** Sort modes in DISPLAY order (recent leads — the default home ordering). */
export const LIBRARY_SORT_MODES: readonly LibrarySort[] = ['recent', 'title', 'duration', 'shorts'];

/** Human labels for the sort control. */
export const LIBRARY_SORT_LABELS: Record<LibrarySort, string> = {
  recent: 'Recently added',
  title: 'Title (A–Z)',
  duration: 'Duration',
  shorts: 'Most shorts',
};

/**
 * Group produced shorts by their source `videoId` (the P0 one-to-many index).
 * Shorts with no source id are skipped (they cannot attach to a card). Immutable.
 */
export function groupShortsByVideo(shorts: readonly ShortInfo[]): Record<string, ShortInfo[]> {
  const out: Record<string, ShortInfo[]> = {};
  for (const s of shorts) {
    if (!s.videoId) continue;
    (out[s.videoId] ??= []).push(s);
  }
  return out;
}

/** Case-insensitive title search (trimmed; empty query → all). Never mutates. */
export function filterVideos(videos: readonly LibraryVideo[], query: string): LibraryVideo[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...videos];
  return videos.filter((v) => v.title.toLowerCase().includes(q));
}

/**
 * Sort a COPY of the list by the chosen mode; `shortsCount` supplies the 'shorts'
 * ordering (the plumbing count is injected, not re-derived here). Deterministic:
 * every mode falls back to title A–Z on a tie, so the order never flickers.
 */
export function sortVideos(
  videos: readonly LibraryVideo[],
  mode: LibrarySort,
  shortsCount: (id: string) => number,
): LibraryVideo[] {
  const byTitle = (a: LibraryVideo, b: LibraryVideo): number => a.title.localeCompare(b.title);
  const copy = [...videos];
  if (mode === 'title') return copy.sort(byTitle);
  if (mode === 'duration')
    return copy.sort((a, b) => b.durationSec - a.durationSec || byTitle(a, b));
  if (mode === 'shorts') {
    return copy.sort((a, b) => shortsCount(b.id) - shortsCount(a.id) || byTitle(a, b));
  }
  // 'recent': newest addedAt first (ISO strings sort lexicographically). A STABLE
  // sort (ES2019+) preserves the incoming order for equal timestamps, so freshly
  // added videos (library.add prepends newest) keep their order rather than being
  // re-shuffled by a title tie-break.
  return copy.sort((a, b) => b.addedAt.localeCompare(a.addedAt));
}

/**
 * mm:ss (or h:mm:ss past an hour) for a source-video duration; '--:--' for a
 * non-finite / non-positive input. Behaviour identical to the prior in-Library
 * helper the card thumbnail relies on.
 */
export function formatDuration(sec: number): string {
  if (!Number.isFinite(sec) || sec <= 0) return '--:--';
  const total = Math.round(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** A card status badge — reserved for ATTENTION states (failed) + provenance. */
export interface CardBadge {
  kind: 'transcript' | 'failed';
  label: string;
}

/**
 * The card's badges, additive and ORDER-STABLE: the FAILED attention badge leads
 * (when a video is in a failed state), then the quiet Transcript provenance chip.
 * Never a duplicate of the meta line or the shorts count.
 */
export function cardBadges(video: LibraryVideo): CardBadge[] {
  const badges: CardBadge[] = [];
  if (video.failed) badges.push({ kind: 'failed', label: 'Failed' });
  if (video.hasTranscript) badges.push({ kind: 'transcript', label: 'Transcript' });
  return badges;
}

/**
 * The open-affordance accessible name: title + duration + status — one
 * self-describing name so the card is fully usable by screen readers (the P0
 * a11y contract). Duration is omitted when unknown so the name never reads a
 * bare '--:--'.
 */
export function cardAriaLabel(video: LibraryVideo, lineageView: boolean): string {
  const parts = [lineageView ? `Show history of ${video.title}` : `Open ${video.title}`];
  const dur = formatDuration(video.durationSec);
  if (dur !== '--:--') parts.push(dur);
  parts.push(
    video.failed ? 'processing failed' : video.hasTranscript ? 'transcript ready' : 'no transcript',
  );
  return parts.join(', ');
}

/** The date part (YYYY-MM-DD) of an ISO `addedAt`; '' when unparseable. */
export function formatAdded(iso: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(iso);
  return m ? m[1] : '';
}
