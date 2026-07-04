// SecureKeysBanner.tsx — WU-D2b-1: the loud "keys can't be saved" surface.
//
// When the OS secure key store (DPAPI on Windows, Keychain on macOS,
// libsecret/kwallet on Linux) is unavailable — or only offers the Linux plaintext
// `basic_text` fallback — the main process REFUSES to persist API keys rather than
// write them weakly-encrypted at rest. Any key the user enters then lives in
// memory for THIS session only and is cleared on quit. This banner makes that
// non-obvious, security-relevant state visible instead of silently losing keys.
//
// The status is queried ONCE on mount via window.api.getSecureStatus() (the
// `secure.status` IPC channel). Bridge access is structural (the renderer never
// imports the preload module), so the banner degrades to inert when the bridge is
// absent (tests / early boot) — it simply renders nothing.
import React, { useEffect, useState } from 'react';

/** Mirror of keystore.ts SecureStatus / preload SecureStatus. */
export interface SecureStatus {
  available: boolean;
  backend: string | null;
  /** True when keys can only live in memory this session (no secure at-rest store). */
  sessionOnly: boolean;
  /** Loud banner text when refusing to persist, else null. */
  banner: string | null;
}

interface SecureBridge {
  /** WU-D2b-1: query secure-key-storage availability (drives this banner). */
  getSecureStatus?: () => Promise<SecureStatus>;
}

/** Read the preload-injected bridge without a global Window augmentation. */
function bridge(): SecureBridge | null {
  return (globalThis as { window?: { api?: SecureBridge } }).window?.api ?? null;
}

/**
 * Fallback banner text used when main reports `sessionOnly` without an explicit
 * message — kept in sync with keystore.ts SESSION_ONLY_BANNER so the user always
 * sees a concrete, actionable explanation.
 */
export const SESSION_ONLY_BANNER =
  'Secure key storage is unavailable on this system, so API keys cannot be saved. ' +
  'Keys you enter will be used for this session only and are cleared when you quit.';

/**
 * Renders nothing while secure storage is healthy (or the bridge is absent). When
 * main reports `sessionOnly`, shows a persistent non-blocking alert with the
 * session-only explanation so a user never silently loses an entered key.
 */
export function SecureKeysBanner(): React.ReactElement | null {
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.getSecureStatus !== 'function') return;
    let cancelled = false;
    api
      .getSecureStatus()
      .then((status) => {
        // Only surface the banner for the refusal state; a healthy store (or a
        // stale resolve after unmount) leaves the app chrome untouched.
        if (cancelled || !status || !status.sessionOnly) return;
        setMessage(status.banner ?? SESSION_ONLY_BANNER);
      })
      .catch(() => {
        // Best-effort: absent a status the banner stays hidden (never a crash).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (message === null) return null;

  return (
    <div className="secure-keys-banner" role="alert" aria-live="assertive">
      <span className="secure-keys-banner__message">{message}</span>
    </div>
  );
}

export default SecureKeysBanner;
