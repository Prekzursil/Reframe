// EditorContext.tsx — the React binding for the shared editor state (v1.5 pilot).
//
// Wraps the pure `editorState` reducer (lib/editorState.ts) in a Context so a
// Stage, a Timeline, and an Inspector become THIN CONSUMERS that read + write ONE
// state via `useEditor()`, instead of each owning its own layout + copy of the
// video/cues/design. The Caption phase pilots the pattern; the other four
// redesigned phases reuse this same provider.
//
// The provider is UNCONTROLLED: it seeds the reducer once (useReducer init). A
// host that swaps the media should remount the provider (e.g. `key={videoId}`) so
// the fresh seed takes — the pilot's Caption view does exactly that.

import React, { createContext, useContext, useMemo, useReducer } from 'react';
import {
  type EditorAction,
  type EditorSeed,
  type EditorState,
  editorReducer,
  initialEditorState,
} from '../lib/editorState';

/** What `useEditor()` returns: the current state + the reducer dispatch. */
export interface EditorContextValue {
  state: EditorState;
  dispatch: React.Dispatch<EditorAction>;
}

const EditorContext = createContext<EditorContextValue | null>(null);

export interface EditorProviderProps {
  seed: EditorSeed;
  children: React.ReactNode;
}

/** Provide the shared editor state to the Stage / Timeline / Inspector tree. */
export function EditorProvider({ seed, children }: EditorProviderProps): React.ReactElement {
  const [state, dispatch] = useReducer(editorReducer, seed, initialEditorState);
  const value = useMemo<EditorContextValue>(() => ({ state, dispatch }), [state]);
  return <EditorContext.Provider value={value}>{children}</EditorContext.Provider>;
}

/** Read the shared editor state. Throws if used outside an `EditorProvider`. */
export function useEditor(): EditorContextValue {
  const ctx = useContext(EditorContext);
  if (!ctx) {
    throw new Error('useEditor must be used within an EditorProvider');
  }
  return ctx;
}

export default EditorProvider;
