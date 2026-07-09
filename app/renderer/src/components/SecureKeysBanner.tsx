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
  /**
   * Absolute paths of legacy PLAINTEXT key copies the boot-time migration could not
   * shred (locked / read-only / a directory) — still readable on disk. Optional so
   * an older/partial payload degrades to "none"; main always sends it (possibly []).
   * A `console.warn` in the main process is invisible in a packaged build, so this is
   * the surface that actually reaches the user.
   */
  unshreddable?: string[];
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
 * Concrete, actionable text naming the plaintext key copies the migration could not
 * delete, so the user can remove them by hand. Grammar agrees with the count.
 */
export function unshreddableBannerText(paths: readonly string[]): string {
  const many = paths.length !== 1;
  return (
    `${paths.length} old plaintext API-key file${many ? 's' : ''} ` +
    'could not be removed automatically and remain readable on disk. ' +
    `Delete ${many ? 'them' : 'it'} manually: ${paths.join(', ')}`
  );
}

/** One rendered warning line (session-only refusal or a lingering-plaintext notice). */
interface BannerMessage {
  key: string;
  text: string;
}

/** Derive the warning line(s) to show for a resolved status (may be empty). */
function messagesFor(status: SecureStatus): BannerMessage[] {
  const messages: BannerMessage[] = [];
  if (status.sessionOnly) {
    messages.push({ key: 'session', text: status.banner ?? SESSION_ONLY_BANNER });
  }
  if (status.unshreddable && status.unshreddable.length > 0) {
    messages.push({ key: 'unshreddable', text: unshreddableBannerText(status.unshreddable) });
  }
  return messages;
}

/**
 * Renders nothing while secure storage is healthy AND no plaintext copy was left
 * behind (or the bridge is absent). Surfaces a persistent non-blocking alert for two
 * independent, possibly-simultaneous keystore conditions: `sessionOnly` (keys can't
 * be saved at rest) and `unshreddable` (a legacy plaintext copy the migration could
 * not delete) — so a user never silently loses a key NOR silently keeps a recoverable
 * plaintext one on disk.
 */
export function SecureKeysBanner(): React.ReactElement | null {
  const [messages, setMessages] = useState<readonly BannerMessage[]>([]);

  useEffect(() => {
    const api = bridge();
    if (!api || typeof api.getSecureStatus !== 'function') return;
    let cancelled = false;
    api
      .getSecureStatus()
      .then((status) => {
        // Ignore a stale resolve after unmount or an absent status; otherwise derive
        // the (possibly empty) warning set — an empty set leaves the chrome untouched.
        if (cancelled || !status) return;
        setMessages(messagesFor(status));
      })
      .catch(() => {
        // Best-effort: absent a status the banner stays hidden (never a crash).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (messages.length === 0) return null;

  return (
    <div className="secure-keys-banner" role="alert" aria-live="assertive">
      {messages.map((m) => (
        <span key={m.key} className="secure-keys-banner__message">
          {m.text}
        </span>
      ))}
    </div>
  );
}

export default SecureKeysBanner;
