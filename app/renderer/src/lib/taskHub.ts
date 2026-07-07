// taskHub.ts — the per-video TASK HUB model (WU-3a1).
//
// Opening a video lands on a hub of large "job cards" (Reframe to vertical /
// Make shorts / Add subtitles / Director) instead of dropping the user straight
// into the 13-tab Workspace on Transcribe (a prerequisite, not a destination).
// This module is the PURE model: the card catalogue, the routing verdicts, and
// the per-video "last choice" persistence helpers. It holds NO React and NO I/O
// so it is fully unit-testable in isolation; the view (views/TaskHub.tsx) and the
// coordinator (views/Edit.tsx) consume it.
//
// ADDITIVE: nothing here deletes, renames, or reorders any existing tab, panel,
// route, or test-pinned id — every card routes INTO an existing flow.

/** The pickable hub choices: the four job cards plus the "all tools" escape. */
export type HubChoice = 'reframe' | 'shorts' | 'subtitles' | 'director' | 'advanced';

/** A large job card on the hub (the four destinations; NOT 'advanced'). */
export interface HubCard {
  id: Exclude<HubChoice, 'advanced'>;
  title: string;
  blurb: string;
}

/**
 * The four job cards, in landing order. Each routes into an EXISTING flow (see
 * `resumeFor` / views/Edit.tsx for the wiring), never a reimplementation:
 *   - reframe   → the per-video Workspace @ the Short-maker tab (owns the reframe
 *                 engine that produces the 9:16 vertical cut),
 *   - shorts    → the top-level Make Shorts section (the novice front door),
 *   - subtitles → the per-video Workspace @ the Subtitles tab,
 *   - director  → the top-level AI Director section.
 */
export const HUB_CARDS: readonly HubCard[] = [
  {
    id: 'reframe',
    title: 'Reframe to vertical',
    blurb: 'Turn this landscape video into a 9:16 vertical cut that follows the subject.',
  },
  {
    id: 'shorts',
    title: 'Make shorts',
    blurb: 'Let AI find the best moments — or pick your own — and export ready-to-post shorts.',
  },
  {
    id: 'subtitles',
    title: 'Add subtitles',
    blurb: 'Transcribe this video, style the captions, and burn them in.',
  },
  {
    id: 'director',
    title: 'Director',
    blurb: 'Describe the edit you want and let the AI Director plan and cut it.',
  },
];

/**
 * Where a remembered choice RESUMES to when a video is re-opened:
 *   - workspace — resume IN PLACE in the per-video Workspace at `tab` (null = the
 *                 Workspace's own default first tab, for the 'advanced' choice),
 *   - section   — a top-level section (Make Shorts / Director); NOT auto-resumed
 *                 on open (it would bounce the user out of the just-opened video),
 *                 so the hub simply marks it "last used",
 *   - none      — no (valid) remembered choice: show the hub.
 */
export type Resume =
  | { kind: 'workspace'; tab: string | null }
  | { kind: 'section' }
  | { kind: 'none' };

/** Resolve a persisted choice string to its resume verdict. */
export function resumeFor(choice: string | null): Resume {
  switch (choice) {
    case 'reframe':
      return { kind: 'workspace', tab: 'shortmaker' };
    case 'subtitles':
      return { kind: 'workspace', tab: 'subtitles' };
    case 'advanced':
      return { kind: 'workspace', tab: null };
    case 'shorts':
    case 'director':
      return { kind: 'section' };
    default:
      return { kind: 'none' };
  }
}

/** The settings key under which per-video hub choices are persisted. */
export const HUB_CHOICE_KEY = 'taskHubChoiceByVideo';

/**
 * Extract the remembered hub choice for `videoId` from a raw settings blob.
 * Fail-soft: any missing / malformed shape yields null (show the hub).
 */
export function readHubChoice(settings: unknown, videoId: string): string | null {
  if (!settings || typeof settings !== 'object') return null;
  const map = (settings as Record<string, unknown>)[HUB_CHOICE_KEY];
  if (!map || typeof map !== 'object') return null;
  const value = (map as Record<string, unknown>)[videoId];
  return typeof value === 'string' ? value : null;
}

/**
 * Immutably merge a new per-video choice into the prior map (read-modify-write):
 * copies the well-formed string entries so OTHER videos' choices survive, then
 * sets `videoId`. `prev` may be any raw value (missing / malformed → empty base).
 */
export function mergeHubChoice(
  prev: unknown,
  videoId: string,
  choice: string,
): Record<string, string> {
  const next: Record<string, string> = {};
  if (prev && typeof prev === 'object') {
    for (const [key, value] of Object.entries(prev as Record<string, unknown>)) {
      if (typeof value === 'string') next[key] = value;
    }
  }
  next[videoId] = choice;
  return next;
}
