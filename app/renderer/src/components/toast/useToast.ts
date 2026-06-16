// useToast.ts — consume the app-wide toast surface (P2 U3).
import { useContext } from 'react';
import { ToastContext, type ToastApi } from './ToastProvider';

/** Strict accessor: throws when no <ToastProvider> is mounted above. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used inside <ToastProvider>');
  }
  return ctx;
}

/**
 * Lenient accessor: `null` when no provider is mounted. Shared hooks (useJob)
 * use this so they keep working in tests/early boot without the provider —
 * the toast surface then degrades to a no-op while state/onError still fire.
 */
export function useToastOptional(): ToastApi | null {
  return useContext(ToastContext);
}

export default useToast;
