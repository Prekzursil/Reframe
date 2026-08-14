// timecode.ts — THE definition of a displayed timecode. One concept, one function.
//
// WHY THIS MODULE EXISTS. `formatTimecode` was exported TWICE, from two modules, in
// one bundle — components/Transport.tsx and features/manualIntervalLogic.ts — with
// the same name, the same signature, the same output shape, and DIVERGENT ROUNDING:
//
//   manualIntervalLogic:  Math.round(sec)   ->  formatTimecode(599.9) === '10:00'
//   Transport:            Math.floor(sec)   ->  formatTimecode(599.9) === '9:59'
//
// Two answers to the same question, decided by which import a file happened to use.
//
// FLOOR IS THE CORRECT SEMANTICS and is what survives here. A playhead at 599.9s has
// not reached 10:00; rounding up shows a time the media is not at, which is wrong for
// scrubbing, in/out marking and frame-stepping — every NLE floors. It is also the
// behaviour already PINNED by a test (Transport.test.tsx asserts 599.9 -> '9:59').
// Adopting it costs the other call site nothing: manualIntervalLogic's own tests use
// only integer inputs (83, 0, 3723, -5, NaN), none of which distinguish the two.
//
// NOT merged in here, deliberately: `features/_api.ts` `fmtSeconds` is a THIRD
// seconds formatter, but it is a genuinely DIFFERENT contract — it has no hour field,
// so it renders 3661s as "61:01" where this renders "1:01:01". Folding it in would
// silently change output at every one of its call sites. It is flagged, not absorbed.

/**
 * Format seconds as `M:SS`, or `H:MM:SS` once past an hour.
 *
 * Truncates toward zero (see the module note): the displayed time is the last whole
 * second the media has actually reached. Non-finite, negative and zero inputs all
 * collapse to `0:00`, so a caller never has to pre-guard.
 */
export function formatTimecode(seconds: number): string {
  const total = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, '0');
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${secs}`;
  return `${minutes}:${secs}`;
}
