// ToastHost.tsx — portal that renders the live toast stack (P2 U3).
//
// Mount once near the app root, INSIDE <ToastProvider> (see WIRING-U3.md).
// Renders into document.body via a portal so toasts overlay every view.
// Styling lives in toast.css; per the shell.css convention, App.tsx (wiring)
// owns the top-level CSS import.
//
// Outside a provider (tests/early boot) it renders nothing rather than throw.
import React from 'react';
import { createPortal } from 'react-dom';
import { useToastOptional } from './useToast';
import type { Toast, ToastApi } from './ToastProvider';

export interface ToastHostProps {
  /** Portal target; defaults to document.body (overridable for tests). */
  container?: Element | null;
}

interface ToastCardProps {
  toast: Toast;
  api: ToastApi;
}

function ToastCard({ toast, api }: ToastCardProps): React.ReactElement {
  const { id, kind, message, action } = toast;
  return (
    <div
      className={`toast toast--${kind}`}
      role={kind === 'error' ? 'alert' : 'status'}
      data-toast-id={id}
    >
      <span className="toast__message">{message}</span>
      {action ? (
        <button
          type="button"
          className="toast__action"
          onClick={() => {
            // The action consumes the toast (e.g. Retry replaces it with a
            // fresh job), so dismiss right after invoking it.
            action.onClick();
            api.dismiss(id);
          }}
        >
          {action.label}
        </button>
      ) : null}
      <button
        type="button"
        className="toast__close"
        aria-label="Dismiss"
        onClick={() => api.dismiss(id)}
      >
        ×
      </button>
    </div>
  );
}

export function ToastHost({ container }: ToastHostProps = {}): React.ReactElement | null {
  const api = useToastOptional();
  // Once a provider exists, ALWAYS portal the .toast-host container so the
  // aria-live="polite" region is permanently mounted (empty when idle) and later
  // toast insertions are mutations of a pre-existing live region — freshly-inserted
  // polite/status regions are announced unreliably by NVDA/JAWS. Mirrors
  // LiveStatusRegion.tsx, which also keeps its polite region mounted while empty.
  if (!api) return null;
  // document is always defined in the Electron renderer (and in jsdom under test),
  // so the SSR-style `typeof document` guard's false arm is unreachable here.
  /* v8 ignore next */
  const target = container ?? (typeof document !== 'undefined' ? document.body : null);
  if (!target) return null;
  return createPortal(
    <div className="toast-host" aria-live="polite">
      {api.toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} api={api} />
      ))}
    </div>,
    target,
  );
}

export default ToastHost;
