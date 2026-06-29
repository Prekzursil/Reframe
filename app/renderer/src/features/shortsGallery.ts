// shortsGallery.ts — pure, render-free helpers for the produced-shorts
// virality-score dashboard (V1.1 WU R5, the #1 OpusClip UX borrow): clip sort
// order + duration formatting. Shared by BOTH the global Shorts gallery
// (views/Shorts.tsx) AND the per-video produced-shorts inline gallery
// (ProducedShorts.tsx) so each surfaces the SAME 0-100 virality badge, sortable
// by score — one source of truth, no drift between the two galleries.
//
// These functions never touch React or window.api; they take plain ShortInfo
// data and return NEW data (immutability). Extracted verbatim from
// views/Shorts.tsx, which now re-exports them so its existing importers/tests
// keep their ./Shorts entry point. The 0-100 badge value itself reuses
// `displayVirality` from shortMakerLogic (the candidate cards' helper) so the
// score numeral is normalised identically everywhere.
import type { ShortInfo } from '../lib/rpc';

/** How the produced-shorts gallery is ordered (R5 dashboard / P4 §7). */
export type ShortsSort = 'recent' | 'virality';

/**
 * The sort modes in DISPLAY order for the R5 dashboard toggle. 'virality' (the
 * headline score) leads — the whole point of the borrow is to surface the
 * best-scoring clips first.
 */
export const SHORTS_SORT_MODES: readonly ShortsSort[] = ['virality', 'recent'];

/** Human labels for the sort toggle buttons. */
export const SHORTS_SORT_LABELS: Record<ShortsSort, string> = {
  virality: 'Virality score',
  recent: 'Recent',
};

/** Newest-first by `createdAt`. Returns a NEW array (never mutates input). */
export function sortByCreatedAt(shorts: readonly ShortInfo[]): ShortInfo[] {
  return [...shorts].sort((a, b) => b.createdAt - a.createdAt);
}

/** A short's virality for SORTING: absent/invalid sinks to -1 (sorts last). */
function shortVirality(s: ShortInfo): number {
  return typeof s.viralityPct === 'number' && Number.isFinite(s.viralityPct) ? s.viralityPct : -1;
}

/**
 * Sort the gallery, NON-DESTRUCTIVELY:
 * - 'recent': newest `createdAt` first.
 * - 'virality': highest viralityPct first; missing scores sink, ties fall back
 *   to newest-first so the order is always deterministic.
 */
export function sortShorts(shorts: readonly ShortInfo[], mode: ShortsSort): ShortInfo[] {
  if (mode === 'virality') {
    return [...shorts].sort((a, b) => {
      const d = shortVirality(b) - shortVirality(a);
      return d !== 0 ? d : b.createdAt - a.createdAt;
    });
  }
  return sortByCreatedAt(shorts);
}

/** mm:ss for a clip duration; "--:--" for non-finite / non-positive input. */
export function formatShortDuration(sec: number): string {
  if (!Number.isFinite(sec) || sec <= 0) return '--:--';
  const total = Math.round(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
