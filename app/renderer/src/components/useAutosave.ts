// useAutosave.ts — debounced, gated workspace autosave (UX/QoL WU-11).
//
// The workspace persists edits with `project.save` (handlers.py:276-287,
// caller-driven — the sidecar never auto-persists). WU-11 wires the renderer to
// fire that save automatically a short, COALESCED moment after the user stops
// editing, gated on the WU-0 `autosave.enabled` setting:
//
//   * with `enabled=true`, N rapid edits collapse to ONE save `debounceMs` after
//     the LAST edit (the falsifiable coalescing claim);
//   * with `enabled=false`, edits NEVER trigger a save.
//
// The hook is deliberately decoupled from any specific RPC: the caller injects a
// `save` callback (`() => client.project.save(project)` in the real workspace),
// which keeps it pure-testable with fake timers + a fake save fn, and reusable by
// any future caller-driven persistence surface.
import { useCallback, useEffect, useRef } from 'react';

/** The WU-0 autosave config slice this hook reads (mirrors `AutosaveSettings`). */
export interface AutosaveConfig {
  enabled: boolean;
  debounceMs: number;
}

/** What `useAutosave` returns: `schedule()` arms/re-arms the debounced save. */
export interface AutosaveControls {
  /** Mark the document dirty — schedules ONE save `debounceMs` after the last call. */
  schedule: () => void;
}

/**
 * Debounce a caller-driven `save` on a per-edit `schedule()` signal.
 *
 * Each `schedule()` call (re)arms a single timer; only the trailing edit's timer
 * survives, so a burst of edits coalesces into ONE `save` after the window. When
 * `enabled` is false, `schedule()` is inert (zero saves). The pending timer is
 * cleared on unmount and whenever `enabled`/`debounceMs` change, so a config flip
 * can never fire a stale, wrongly-timed save. `save` is read through a ref so a
 * changing closure (e.g. a fresh `project`) never resets the timer.
 */
export function useAutosave(save: () => void, config: AutosaveConfig): AutosaveControls {
  const { enabled, debounceMs } = config;
  const saveRef = useRef(save);
  saveRef.current = save;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clear = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const schedule = useCallback(() => {
    if (!enabled) return;
    clear();
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      saveRef.current();
    }, debounceMs);
  }, [enabled, debounceMs, clear]);

  // A config change (or unmount) drops any in-flight timer so it can't fire with
  // stale timing / after autosave was turned off.
  useEffect(() => clear, [enabled, debounceMs, clear]);

  return { schedule };
}
