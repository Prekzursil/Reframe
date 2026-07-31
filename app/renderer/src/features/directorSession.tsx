// directorSession.tsx — the Director's SESSION state, hoisted ABOVE the route switch.
//
// F32: every top-level tab click re-runs App's `renderRoute()` switch, which
// UNMOUNTS the whole Director subtree. The panel's goal / plan / per-op review
// decisions lived in component-local `useState`, so leaving the tab silently threw
// away an unapplied plan and every keep/drop + reorder decision made on it — with
// no warning, no confirm, and no read path back. Nothing new is needed at the wire
// to fix that: the renderer already OWNS the complete plan object from the
// `job.done` payload (`director_ops.py` returns `{planId, editPlan, preview}`); it
// was simply being discarded. This provider keeps it alive for the app run.
//
// WHAT IS STORED (and what deliberately is NOT):
//   stored here  — goal, plan, opsStatus, applied  (the user's WORK: irrecoverable
//                  without a re-plan, and a re-plan yields a NON-IDENTICAL plan
//                  because the model is re-run)
//   left local   — preview, evaluation, busy, error, progress, kindFilter, showTour
//                  (transient UI, or cheaply re-fetchable by planId — the panel
//                  re-requests `previewCost` for a restored plan on mount)
//
// SCOPE (both limits are real and deliberate):
//   * IN-MEMORY ONLY. Durable recovery across an app/sidecar restart is a separate,
//     genuinely-unbuilt capability and is NOT folded in here.
//   * ONE SLOT. A session is stamped with its `videoId` and is refused when a
//     DIFFERENT video is open (see resolveSession). Storing a session for video B
//     replaces video A's, so A -> B -> A does not restore A once B was worked on.
//     A `Record<videoId, …>` would remove that, at the cost of an unbounded map.
//
// RESIDUAL, STATED INLINE (NOT closed by this file): the IN-FLIGHT window is still
// lost. The job identity is a per-panel `useRef` and the `job.done` subscription is
// a per-MOUNT effect, so if the user clicks "Plan edit" and tabs away BEFORE the
// job finishes, nobody is subscribed when the result arrives and it is discarded —
// and on return the panel looks coherent and idle while holding the PREVIOUS plan.
// Closing it requires moving the whole job seam (subscription + handleDone + the
// result narrowing) above the route switch, because hoisting the job id alone does
// not help while no component is listening. That is a larger refactor of the
// panel's job seam and is out of this batch's scope; JobQueue still lists the job.

import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { DirectorEditPlan, DirectorOp } from '../lib/directorTypes';

/** The user's in-progress Director work for ONE video. */
export interface DirectorSessionFields {
  /** The editing goal as typed (survives so "Adjust & re-plan" keeps its text). */
  goal: string;
  /** The reviewable plan, including any keep/drop + reorder edits made on it. */
  plan: DirectorEditPlan | null;
  /** Per-op statuses returned by an apply/undo (server truth once present). */
  opsStatus: DirectorOp[] | null;
  /** True once this plan has been applied (gates Evaluate / Undo). */
  applied: boolean;
}

/** A stored session, stamped with the video it belongs to (WU-E1: the plan target). */
export interface DirectorSessionEntry extends DirectorSessionFields {
  videoId: string;
}

/** A session with no work in it — what a first visit (or a different video) gets. */
export const CLEAN_SESSION: DirectorSessionFields = {
  goal: '',
  plan: null,
  opsStatus: null,
  applied: false,
};

/**
 * Decide whether the stored session may be served for the currently-open video.
 *
 * The rule is NOT "key by the open video id" — that is circular in the one state
 * the panel deliberately supports. `DirectorPanel` resolves its plan target as
 * `video?.id ?? plan?.videoId`, so a video CLOSED after planning keeps its plan
 * (pinned by DirectorPanel.test.tsx's "a video closed AFTER planning keeps the
 * plan…"). With `video === null` the only videoId in existence is the one INSIDE
 * the session being read, so keying on the open video would refuse to serve the
 * very session that holds the answer, and the WU-E1 guard would be dropped.
 *
 * So: serve the stored slot when NO video is open; refuse ONLY when a DIFFERENT
 * video is open (that plan's ops must never be applied to another source).
 */
export function resolveSession(
  stored: DirectorSessionEntry | null,
  openVideoId: string | null,
): DirectorSessionFields {
  if (stored === null) return CLEAN_SESSION;
  if (openVideoId === null) return stored;
  if (stored.videoId !== openVideoId) return CLEAN_SESSION;
  return stored;
}

/** A functional session update (mirrors `useState`'s updater contract). */
export type DirectorSessionUpdater = (prev: DirectorSessionFields) => DirectorSessionFields;

/** What `useDirectorSession()` hands back. */
export interface DirectorSessionStore {
  /** The raw stored slot (null when nothing has been stored yet). */
  stored: DirectorSessionEntry | null;
  /**
   * Store/replace the session for `videoId`. The updater receives whatever
   * {@link resolveSession} would serve for that video, so an edit against a
   * DIFFERENT video's slot starts from a clean session instead of inheriting it.
   */
  update(videoId: string, next: DirectorSessionUpdater): void;
}

const DirectorSessionContext = createContext<DirectorSessionStore | null>(null);

/**
 * The store implementation. Used BOTH by {@link DirectorSessionProvider} and as
 * the no-provider fallback in {@link useDirectorSession}, so there is exactly one
 * copy of the semantics.
 */
export function useDirectorSessionStore(): DirectorSessionStore {
  const [stored, setStored] = useState<DirectorSessionEntry | null>(null);
  const update = useCallback((videoId: string, next: DirectorSessionUpdater): void => {
    setStored((prev) => ({ videoId, ...next(resolveSession(prev, videoId)) }));
  }, []);
  return useMemo<DirectorSessionStore>(() => ({ stored, update }), [stored, update]);
}

export interface DirectorSessionProviderProps {
  children: React.ReactNode;
}

/**
 * Hold the Director session ABOVE the route switch. It MUST be mounted outside
 * App's `renderRoute()` switch — inside it, it would be part of the very subtree a
 * tab click unmounts, and would fix nothing.
 */
export function DirectorSessionProvider({
  children,
}: DirectorSessionProviderProps): React.ReactElement {
  const store = useDirectorSessionStore();
  return (
    <DirectorSessionContext.Provider value={store}>{children}</DirectorSessionContext.Provider>
  );
}

/**
 * Read the Director session store.
 *
 * Outside a provider this falls back to a panel-LOCAL store, so `DirectorPanel`
 * stays independently mountable (its own suite renders it bare, as does any
 * one-off host). The fallback behaves identically for a single mount — it just
 * cannot survive an unmount, which is precisely what the provider adds.
 */
export function useDirectorSession(): DirectorSessionStore {
  const ctx = useContext(DirectorSessionContext);
  const fallback = useDirectorSessionStore();
  return ctx ?? fallback;
}

export default DirectorSessionProvider;
