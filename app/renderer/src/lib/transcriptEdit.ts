/**
 * Transcript-native editing — the PURE renderer half (v1.5 flagship #2, WU-T2).
 *
 * "Delete a word and the video cuts." This module owns the token model the
 * Transcript inspector reasons over and the translation from a UI selection to
 * the `transcript.previewEdit` / `transcript.applyEdit` wire payload. It is
 * deliberately pure: no React, no RPC, no clock — so every branch is unit
 * testable and the inspector pane stays a thin view over it.
 *
 * The sidecar (`media_studio/features/transcript_edit.py`) is the authority on
 * the final cut: it re-resolves each `wordId`, unions the deletes with the
 * shipped filler/silence math, and renders ONCE. `keepSpansFor` / `remapTime`
 * here mirror that math ONLY so the UI can scrub an instant local preview
 * before the round-trip — they are an ESTIMATE, never the applied edit.
 *
 * SCOPE: `delete` and `trim` (the monotonic half). `reorder` is deferred
 * backend-side and is intentionally not expressible here — see the plan's C3.
 */

/** A word with the stable address `transcript.get` stamps on it. */
export type TranscriptWord = {
  readonly wordId: string;
  readonly segmentIndex: number;
  readonly wordIndex: number;
  readonly text: string;
  readonly start: number;
  readonly end: number;
};

/** The §3 transcript as it arrives over the wire (fields are defensive). */
export type Transcript = {
  readonly language?: string | null;
  readonly durationSec?: number;
  readonly segments?: readonly unknown[];
};

/** The ops the sidecar translator applies; anything else it drops with a reason. */
export type EditOp = 'delete' | 'trim';

/** One entry of the `edits` array sent to `transcript.previewEdit`/`applyEdit`. */
export type EditSpan = {
  readonly op: EditOp;
  readonly wordId?: string;
  readonly startMs?: number;
  readonly endMs?: number;
};

/** A `[start, end]` keep span in ORIGINAL-video seconds. */
export type KeepSpan = readonly [number, number];

const round3 = (n: number): number => Math.round(n * 1000) / 1000;

const asArray = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : []);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const finite = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/**
 * Flatten a transcript into addressed words, in transcript order.
 *
 * Malformed input never throws: a non-object segment/word is skipped, a word
 * without finite `start`/`end` is skipped (it cannot address a cut), and a word
 * the sidecar did not stamp falls back to the same `w{seg}-{idx}` address the
 * sidecar would have generated.
 */
export function flattenWords(transcript: Transcript | null | undefined): TranscriptWord[] {
  const out: TranscriptWord[] = [];
  asArray(transcript?.segments).forEach((segment, segmentIndex) => {
    if (!isRecord(segment)) return;
    asArray(segment.words).forEach((word, wordIndex) => {
      if (!isRecord(word)) return;
      const start = finite(word.start);
      const end = finite(word.end);
      if (start === null || end === null) return;
      const stamped =
        typeof word.wordId === 'string' && word.wordId
          ? word.wordId
          : `w${segmentIndex}-${wordIndex}`;
      out.push({
        wordId: stamped,
        segmentIndex,
        wordIndex,
        text: typeof word.text === 'string' ? word.text : '',
        start,
        end,
      });
    });
  });
  return out;
}

/** Immutably toggle a word's deleted state (strike-through in the inspector). */
export function toggleWord(deleted: ReadonlySet<string>, wordId: string): Set<string> {
  const next = new Set(deleted);
  if (!next.delete(wordId)) next.add(wordId);
  return next;
}

/**
 * The inclusive word ids between two anchors (a shift-click / drag selection).
 * Order-insensitive; `[]` when either anchor is not in `words`.
 */
export function selectRange(
  words: readonly TranscriptWord[],
  fromId: string,
  toId: string,
): string[] {
  const from = words.findIndex((w) => w.wordId === fromId);
  const to = words.findIndex((w) => w.wordId === toId);
  if (from < 0 || to < 0) return [];
  const lo = Math.min(from, to);
  const hi = Math.max(from, to);
  return words.slice(lo, hi + 1).map((w) => w.wordId);
}

/**
 * The `edits` payload for the sidecar: one `delete` per deleted word, in
 * transcript order. Ids that are not in `words` are dropped here so the wire
 * payload can never carry an address the backend would only reject.
 */
export function buildEditSpans(
  words: readonly TranscriptWord[],
  deleted: ReadonlySet<string>,
): EditSpan[] {
  return words
    .filter((w) => deleted.has(w.wordId))
    .map((w) => ({ op: 'delete' as const, wordId: w.wordId }));
}

/** The client-side estimate of how much time the current selection removes. */
export function removedSeconds(
  words: readonly TranscriptWord[],
  deleted: ReadonlySet<string>,
): number {
  const total = words
    .filter((w) => deleted.has(w.wordId))
    .reduce((sum, w) => sum + Math.max(0, w.end - w.start), 0);
  return round3(total);
}

/** The transcript text as it will read after the cut (single-spaced). */
export function editedText(words: readonly TranscriptWord[], deleted: ReadonlySet<string>): string {
  return words
    .filter((w) => !deleted.has(w.wordId))
    .map((w) => w.text.trim())
    .join(' ');
}

/**
 * The keep-list the current selection implies, mirroring the sidecar's
 * invert-the-union math. Overlapping deletions merge into one gap; a deletion
 * that would remove the WHOLE clip degrades to the untouched clip (an empty
 * keep-list is unrenderable — `build_segment_cut_argv` rejects it).
 */
export function keepSpansFor(
  words: readonly TranscriptWord[],
  deleted: ReadonlySet<string>,
  durationSec: number,
): KeepSpan[] {
  if (durationSec <= 0) return [];
  const removed = words
    .filter((w) => deleted.has(w.wordId))
    .map((w): KeepSpan => [w.start, Math.min(durationSec, w.end)])
    .sort((a, b) => a[0] - b[0]);

  const keeps: KeepSpan[] = [];
  let cursor = 0;
  for (const [start, end] of removed) {
    if (start > cursor) keeps.push([round3(cursor), round3(start)]);
    cursor = Math.max(cursor, end);
  }
  if (cursor < durationSec) keeps.push([round3(cursor), round3(durationSec)]);
  return keeps.length > 0 ? keeps : [[0, round3(durationSec)]];
}

/**
 * Map an ORIGINAL-video time onto the cut clip's local timeline — the renderer
 * mirror of `fillers.remap_time`, used to drive the preview playhead. A time
 * inside a removed span collapses onto the cut point; a time before the first
 * keep clamps to 0.
 */
export function remapTime(t: number, keeps: readonly KeepSpan[]): number {
  let elapsed = 0;
  for (const [start, end] of keeps) {
    if (t < start) return round3(elapsed);
    if (t <= end) return round3(elapsed + (t - start));
    elapsed += end - start;
  }
  return round3(elapsed);
}

/** The word under the playhead (karaoke highlight), or `null` between words. */
export function wordAt(words: readonly TranscriptWord[], t: number): TranscriptWord | null {
  return words.find((w) => t >= w.start && t <= w.end) ?? null;
}
