// ToastProvider.tsx — app-wide toast surface (P2 U3).
//
// Dependency-free toast system: React context + reducer, auto-dismiss timers,
// kinds info/success/error, and an optional action-button slot (used by
// useJob's error surface for "Retry" once U5's job.retry RPC is wired).
//
// CONTRACT-NOTE: toast internals are not part of the frozen CONTRACTS.md
// surface; this module only renders what frozen pieces (the A3 job.done error
// payload, surfaced by useJob) hand to it. Defaults chosen here: info/success
// auto-dismiss after DEFAULT_DURATION_MS; error toasts are sticky
// (durationMs null) so failures stay visible until dismissed — pass an
// explicit durationMs to override either way.
import React, { createContext, useCallback, useEffect, useMemo, useReducer, useRef } from 'react';

export type ToastKind = 'info' | 'success' | 'error';

/** Optional action button rendered inside a toast (e.g. "Retry"). */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  kind?: ToastKind;
  /** ms until auto-dismiss; `null` = sticky until dismissed manually. */
  durationMs?: number | null;
  action?: ToastAction;
}

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  durationMs: number | null;
  action?: ToastAction;
}

/** Auto-dismiss default for info/success toasts (errors default to sticky). */
export const DEFAULT_DURATION_MS = 5000;

// ---- reducer (pure; exported for unit tests) -------------------------------

export type ToastReducerAction =
  | { type: 'push'; toast: Toast }
  | { type: 'dismiss'; id: number }
  | { type: 'clear' };

export function toastReducer(
  state: readonly Toast[],
  action: ToastReducerAction,
): readonly Toast[] {
  switch (action.type) {
    case 'push':
      return [...state, action.toast];
    case 'dismiss':
      return state.some((toast) => toast.id === action.id)
        ? state.filter((toast) => toast.id !== action.id)
        : state;
    case 'clear':
      return state.length === 0 ? state : [];
    default:
      return state;
  }
}

// ---- context ----------------------------------------------------------------

type KindOptions = Omit<ToastOptions, 'kind'>;

export interface ToastApi {
  /** Live toast list (render order = enqueue order). */
  toasts: readonly Toast[];
  /** Enqueue a toast; returns its id. */
  push: (message: string, options?: ToastOptions) => number;
  /** Remove one toast (also clears its pending auto-dismiss timer). */
  dismiss: (id: number) => void;
  /** Remove all toasts and cancel all pending timers. */
  clear: () => void;
  info: (message: string, options?: KindOptions) => number;
  success: (message: string, options?: KindOptions) => number;
  error: (message: string, options?: KindOptions) => number;
}

/** Exported so useToast.ts / ToastHost.tsx can consume it. */
export const ToastContext = createContext<ToastApi | null>(null);
ToastContext.displayName = 'ToastContext';

function defaultDuration(kind: ToastKind): number | null {
  return kind === 'error' ? null : DEFAULT_DURATION_MS;
}

export interface ToastProviderProps {
  children?: React.ReactNode;
}

/**
 * Mount once near the app root (see WIRING-U3.md); pair with <ToastHost /> to
 * actually render the stack. Owns the queue (reducer) + auto-dismiss timers.
 */
export function ToastProvider({ children }: ToastProviderProps): React.ReactElement {
  const [toasts, dispatch] = useReducer(toastReducer, [] as readonly Toast[]);
  const nextIdRef = useRef(1);
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number): void => {
    const timer = timersRef.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    dispatch({ type: 'dismiss', id });
  }, []);

  const push = useCallback((message: string, options?: ToastOptions): number => {
    const id = nextIdRef.current;
    nextIdRef.current += 1;
    const kind: ToastKind = options?.kind ?? 'info';
    const durationMs =
      options?.durationMs === undefined ? defaultDuration(kind) : options.durationMs;
    const toast: Toast = { id, kind, message, durationMs, action: options?.action };
    dispatch({ type: 'push', toast });
    if (durationMs !== null && Number.isFinite(durationMs)) {
      const timer = setTimeout(() => {
        timersRef.current.delete(id);
        dispatch({ type: 'dismiss', id });
      }, durationMs);
      timersRef.current.set(id, timer);
    }
    return id;
  }, []);

  const clear = useCallback((): void => {
    for (const timer of timersRef.current.values()) clearTimeout(timer);
    timersRef.current.clear();
    dispatch({ type: 'clear' });
  }, []);

  // Cancel all pending auto-dismiss timers when the provider unmounts.
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
    };
  }, []);

  const info = useCallback(
    (message: string, options?: KindOptions): number => push(message, { ...options, kind: 'info' }),
    [push],
  );
  const success = useCallback(
    (message: string, options?: KindOptions): number =>
      push(message, { ...options, kind: 'success' }),
    [push],
  );
  const error = useCallback(
    (message: string, options?: KindOptions): number =>
      push(message, { ...options, kind: 'error' }),
    [push],
  );

  const value = useMemo<ToastApi>(
    () => ({ toasts, push, dismiss, clear, info, success, error }),
    [toasts, push, dismiss, clear, info, success, error],
  );

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export default ToastProvider;
