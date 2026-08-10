// reframeDegraded.ts — the renderer-side reader for the sidecar's WU-3
// NO-SILENT-FALLBACK reframe signal.
//
// THE DEFECT THIS CLOSES (W12): the sidecar stamps a per-clip
// `reframeDegraded` notice on the §2 export clip payload
// (`sidecar/media_studio/features/shortmaker.py` — `_clip_payload`) precisely so
// the UI can tell a real tracked reframe apart from a fallback. Until this module
// existed the renderer never declared or read the key, so a degraded clip was
// presented to the user as a plain success — the exact silent fallback the
// sidecar contract was written to prevent.
//
// HONESTY CONSTRAINT baked into the API: two different producers share ONE notice
// type —
//   * `reframe_claudeshorts.make_degraded_notice` — tracking unavailable, a dumb
//     CENTER CROP was used;
//   * `reframe_multispeaker.make_engine_degrade_notice` — the multi-speaker
//     engine was unavailable, the SINGLE-SPEAKER tracker was used (still real
//     tracking, a quality downgrade).
// So a summary line must NOT paraphrase the outcome (it would be false for one of
// them). `describeDegraded` states the COUNT only; the per-clip line renders the
// sidecar's own `message`, which is accurate for whichever producer fired.

/** The wire key the sidecar stamps on a degraded clip (pinned by conformance). */
export const REFRAME_DEGRADED_KEY = 'reframeDegraded';

/** The sidecar's typed degrade notice (`{type, message, reason}`). */
export interface ReframeDegradedNotice {
  /** The notice type id (shared by both producers). */
  type: string;
  /** The human line the sidecar authored — rendered verbatim, never rewritten. */
  message: string;
  /** The specific cause, when the sidecar supplied one. */
  reason?: string;
}

/** A string value, or '' for anything else (untrusted wire data). */
function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * The degrade notice on an exported clip, or `null` when reframe tracked
 * normally. A notice with no usable `message` is treated as absent: a badge with
 * no explanation is worse than no badge, and the sidecar always sends one.
 */
export function reframeDegradedNotice(clip: unknown): ReframeDegradedNotice | null {
  if (!clip || typeof clip !== 'object') return null;
  const raw = (clip as Record<string, unknown>)[REFRAME_DEGRADED_KEY];
  if (!raw || typeof raw !== 'object') return null;
  const notice = raw as Record<string, unknown>;
  const message = str(notice.message).trim();
  if (!message) return null;
  const reason = str(notice.reason).trim();
  return { type: str(notice.type), message, ...(reason ? { reason } : {}) };
}

/** How many of these clips carry a degrade notice. */
export function countDegraded(clips: readonly unknown[]): number {
  return clips.filter((clip) => reframeDegradedNotice(clip) !== null).length;
}

/**
 * A count-only summary of the degraded clips, or `null` when every clip reframed
 * normally (no scary banner on a clean export). Deliberately names no outcome —
 * see the module header.
 */
export function describeDegraded(clips: readonly unknown[]): string | null {
  const degraded = countDegraded(clips);
  if (degraded === 0) return null;
  return `Reframe degraded on ${degraded} of ${clips.length} clip(s) — see the note on each file below.`;
}
