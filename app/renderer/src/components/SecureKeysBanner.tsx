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

/**
 * WHY the on-disk keystore could not be read — mirror of keystore.ts
 * KeystoreUnreadableReason. Every value means "the blob EXISTS but its contents could
 * not be trusted", never "there is no keystore yet".
 */
export type KeystoreUnreadableReason =
  | 'read-failed'
  | 'parse-failed'
  | 'shape-invalid'
  | 'decrypt-failed';

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
  /**
   * WHY the on-disk keystore could not be read, or `null` when it is healthy /
   * genuinely absent. Optional so an older/partial payload degrades to "no problem";
   * main always sends it (KeyBridge.secureStatus overlays the live value). While this
   * is non-null the bridge REFUSES to overwrite the keystore (fail-closed), so a key
   * the user enters does NOT persist — hence it must be shown, or saving looks like
   * it worked and silently did not.
   */
  keystoreUnreadable?: KeystoreUnreadableReason | null;
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
    `could not be removed automatically and remain${many ? '' : 's'} readable on disk. ` +
    `Delete ${many ? 'them' : 'it'} manually: ${paths.join(', ')}`
  );
}

/**
 * The per-reason cause clause appended to the unreadable-keystore warning. Named
 * CAUSES only — never the offending value — so nothing here can carry key material.
 */
const KEYSTORE_UNREADABLE_CAUSE: Record<KeystoreUnreadableReason, string> = {
  'read-failed': 'the file could not be opened — another program may be holding it open',
  'parse-failed': 'the file is incomplete, so an earlier save was probably interrupted',
  'shape-invalid': 'the file contents are not in the expected format',
  'decrypt-failed':
    'this computer could not decrypt it — it may have been copied from another machine or user profile',
};

/**
 * Concrete text for a keystore whose contents could not be trusted. Deliberately does
 * NOT name a path (the keystore lives under Electron's userData directory, which is
 * NOT the user-chosen data folder, so naming that folder would be actively wrong) and
 * deliberately does NOT claim permanent loss — a `read-failed` lock can be transient,
 * so restarting is the first thing to try.
 */
export function keystoreUnreadableBannerText(reason: KeystoreUnreadableReason): string {
  return (
    'Your saved API keys could not be read, so new keys cannot be saved and will only ' +
    `work until you quit. Cause: ${KEYSTORE_UNREADABLE_CAUSE[reason]}. ` +
    'Try restarting the app; the existing key file is left untouched.'
  );
}

/** One rendered warning line (session-only, lingering-plaintext, or unreadable-keystore). */
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
  // One truthiness test covers BOTH `undefined` (an older/partial payload) and the
  // `null` main actually sends for a healthy or absent keystore.
  if (status.keystoreUnreadable) {
    messages.push({
      key: 'keystore-unreadable',
      text: keystoreUnreadableBannerText(status.keystoreUnreadable),
    });
  }
  return messages;
}

/**
 * Renders nothing while secure storage is healthy AND no plaintext copy was left
 * behind AND the keystore reads cleanly (or the bridge is absent). Surfaces a
 * persistent non-blocking alert for three independent, possibly-simultaneous keystore
 * conditions: `sessionOnly` (keys can't be saved at rest), `unshreddable` (a legacy
 * plaintext copy the migration could not delete), and `keystoreUnreadable` (the stored
 * keys could not be read, so the bridge fail-closed refuses to overwrite them) — so a
 * user never silently loses a key NOR silently keeps a recoverable plaintext one on
 * disk NOR believes a save succeeded that was actually refused.
 *
 * KNOWN LIMITS of this surface (deliberate scope, not oversights):
 *  1. MOUNT-ONCE SNAPSHOT, stale in BOTH directions. `getSecureStatus()` runs exactly
 *     once in a `[]` effect below, and each call costs a full synchronous read+decrypt
 *     of the keystore in main, so it is not polled. Consequences: (a) FALSE NEGATIVE —
 *     a lock that appears mid-session (the `read-failed` AV/indexer case, typically at
 *     the moment the user clicks Add key and the bridge refuses) renders NOTHING here,
 *     while the Providers panel still reports the key as verified; (b) FALSE POSITIVE —
 *     a keystore unreadable at mount but healthy afterwards leaves this alert up for
 *     the rest of the session. The cheap remedy is to re-query after an explicit
 *     `providers.upsert` (one read per deliberate user action, not a poll), or to have
 *     main push `secure.status` when the refusal branch is taken. Neither is wired yet.
 *  2. DISPLAY-ONLY. This tells the user; it does not repair anything. In particular the
 *     key-LIST shrinkage that accompanies an unreadable keystore is NOT fixed: an add
 *     re-sends the provider's existing REDACTED keys, `planUpsert` resolves the stored
 *     set as empty, and the raw-key filter drops every redacted stand-in, so previously
 *     listed keys also disappear from the Providers list. That is a separate defect.
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
