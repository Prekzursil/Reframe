// keystore.ts — WU-D2: DPAPI-backed secure key storage + one-time plaintext migration.
//
// THREAT MODEL (R7): API keys must never sit in plaintext at rest. Electron's
// `safeStorage` wraps the OS keychain (DPAPI on Windows, Keychain on macOS,
// libsecret/kwallet on Linux). This module is the MAIN-process owner of that
// secret material:
//
//   * keys are ENCRYPTED with safeStorage and stored base64 in the app userData
//     dir (`secure-keys.json`) — never in `settings.json`, never an env var/argv;
//   * decryption happens ONLY here in main (the renderer never sees a raw key);
//   * a one-time migration re-encrypts any legacy plaintext keys already in
//     `settings.json`, then SHREDS every prior copy (the file, its `.tmp`, and
//     any backups) so zero plaintext key bytes survive on disk;
//   * if the OS only offers the `basic_text` fallback (or encryption is
//     unavailable), we REFUSE to persist — keys are session-only and the renderer
//     shows a loud banner — rather than silently writing a weakly/never-encrypted
//     key to disk.
//
// The logic is Electron-light: `safeStorage` and the file paths are injected so
// the whole surface is unit-testable with a fake safeStorage + tmp dirs.
import {
  closeSync,
  copyFileSync,
  constants as fsConstants,
  ftruncateSync,
  lstatSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, join, resolve as resolvePath, sep } from 'node:path';

/** The encrypted keystore file, kept in the app userData dir (NOT settings.json). */
export const KEYSTORE_FILENAME = 'secure-keys.json';

/** Extension of a timestamped pre-overwrite keystore backup (CIPHERTEXT only). */
export const KEYSTORE_BACKUP_EXT = '.bak';

/**
 * How many timestamped keystore backups are retained; the oldest are pruned.
 * Bounded so an edit-heavy user does not accumulate backups forever, deep enough
 * that several bad generations in a row are still recoverable.
 */
export const KEYSTORE_BACKUP_RETENTION = 5;

/** Linux plaintext fallback backend name — persisting to it is REFUSED. */
export const BASIC_TEXT_BACKEND = 'basic_text';

/** Loud renderer banner shown when secure storage is unavailable (session-only mode). */
export const SESSION_ONLY_BANNER =
  'Secure key storage is unavailable on this system, so API keys cannot be saved. ' +
  'Keys you enter will be used for this session only and are cleared when you quit.';

/** The subset of Electron `safeStorage` this module needs (injectable for tests). */
export interface SafeStorageLike {
  isEncryptionAvailable(): boolean;
  encryptString(plaintext: string): Buffer;
  decryptString(encrypted: Buffer): string;
  /** Present on Linux (returns e.g. 'basic_text' | 'gnome_libsecret'); may throw elsewhere. */
  getSelectedStorageBackend?(): string;
}

/** Availability/refusal decision surfaced to the renderer for the banner. */
export interface SecureStatus {
  /** safeStorage.isEncryptionAvailable(). */
  available: boolean;
  /** The selected backend, or null when the platform doesn't report one. */
  backend: string | null;
  /** True when keys can only live in memory this session (no secure at-rest store). */
  sessionOnly: boolean;
  /** Loud banner text when refusing to persist, else null. */
  banner: string | null;
  /**
   * Absolute paths of legacy plaintext key copies the boot-time migration could not
   * shred (still recoverable on disk). Optional here because the pure availability
   * decision has no migration context; {@link KeyBridge.secureStatus} overlays the
   * real list (possibly empty) so the renderer can surface it to the user — a
   * main-process `console.warn` is invisible in a packaged build.
   */
  unshreddable?: string[];
  /**
   * WHY the on-disk keystore could not be read, or `null` when it is healthy /
   * genuinely absent. Optional here for the same reason as `unshreddable`: the pure
   * availability decision has no keystore context; {@link KeyBridge.secureStatus}
   * overlays the live value. While this is non-null the bridge REFUSES to overwrite
   * the keystore (fail-closed) — so the user must be told, or their keys look
   * silently un-saveable.
   */
  keystoreUnreadable?: KeystoreUnreadableReason | null;
}

/**
 * One connected social platform's OAuth material (C14).
 *
 * `accessToken` / `refreshToken` are CREDENTIALS; the remaining fields are display
 * metadata. The whole record is encrypted as a single blob rather than field-by-
 * field, so no future field can be added on the non-secret side by mistake.
 */
export interface SocialToken {
  accessToken: string;
  /** `''` when the platform issued none (some flows return only an access token). */
  refreshToken: string;
  /** Epoch seconds; `0` when the platform did not say. */
  expiresAt: number;
  /** Display-only account name shown in the UI (e.g. the channel title). */
  accountLabel: string;
  /** The scopes actually granted, so the UI can show what was consented to. */
  scopes: string[];
}

/** The decrypted key material main injects into the sidecar per-request (never to disk). */
export interface DecryptedKeys {
  /** providerId -> its raw API keys (rotation pool order preserved). */
  providers: Record<string, string[]>;
  /** The legacy single cloud key, when one was stored. */
  cloudApiKey?: string;
  /**
   * C14: platformId -> its OAuth token record, when any platform is connected.
   *
   * This section is part of `DecryptedKeys` for a load-bearing reason:
   * {@link saveDecryptedKeys} REBUILDS the whole keystore document from this value
   * rather than patching the file, so a section missing from here is a section
   * ERASED from disk on the next write. Keeping social tokens out of this type
   * would mean any `providers.upsert` silently destroyed every connected social
   * account (and vice versa) — see `socialTokens.test.ts`.
   */
  social?: Record<string, SocialToken>;
}

/** Outcome of the one-time legacy-plaintext migration. */
export interface MigrationResult {
  status: 'migrated' | 'noop' | 'refused';
  /** Count of provider keys re-encrypted into the keystore. */
  migratedProviderKeys: number;
  /** Whether a legacy cloudApiKey was re-encrypted. */
  migratedCloudKey: boolean;
  /** Absolute paths whose plaintext key material was shredded. */
  shredded: string[];
  /**
   * Absolute paths of plaintext key copies that EXISTED but could NOT be shredded
   * (locked / read-only / unwritable / a directory — both the truncate and the
   * unlink failed). These are still fully recoverable on disk, so the user should
   * remove them manually; the caller surfaces them in a loud warning rather than
   * letting a lingering plaintext copy stay silent. An `absent` copy never lands
   * here (nothing to remove).
   */
  unshreddable: string[];
  /** True when the refuse path left keys session-only (secure storage unavailable). */
  sessionOnly: boolean;
  /** Loud banner text on the refuse path, else null. */
  banner: string | null;
}

/** Raised when an encrypt is attempted without a secure backend. */
export class KeystoreUnavailableError extends Error {
  constructor(message: string = SESSION_ONLY_BANNER) {
    super(message);
    this.name = 'KeystoreUnavailableError';
  }
}

/**
 * WHY a keystore read failed. Every value means "the blob EXISTS but its contents
 * could not be trusted" — never "there is no keystore yet" (that is `'absent'`).
 *   - `'read-failed'`    — the bytes could not be read at all (locked / EACCES / a
 *                          directory in the way).
 *   - `'parse-failed'`   — not valid JSON: a truncated or partial write.
 *   - `'shape-invalid'`  — valid JSON of the wrong shape (not an object, a
 *                          non-object `providers` map, a non-array key list, a
 *                          non-string `cloudApiKey`).
 *   - `'decrypt-failed'` — well-formed, but `safeStorage` could not unwrap the
 *                          ciphertext: a DPAPI failure, a moved Windows profile, or
 *                          a keystore copied from another machine.
 * Deliberately an enum of CAUSES and never the offending value, so a diagnostic can
 * be logged / surfaced without ever carrying key material.
 */
export type KeystoreUnreadableReason =
  | 'read-failed'
  | 'parse-failed'
  | 'shape-invalid'
  | 'decrypt-failed';

/**
 * The three distinguishable end-states of a keystore READ — the same 3-state idiom
 * as {@link ShredOutcome}, and for the same reason: a two-state "keys or empty"
 * answer conflated **absent** with **unreadable**, and that conflation is a
 * CREDENTIAL-DESTROYING bug. An unreadable keystore reported as empty makes the very
 * next {@link saveDecryptedKeys} write a fresh store over it, PERMANENTLY wiping
 * every stored credential (a single DPAPI hiccup, a locked file, a partial write, or
 * a profile move was enough).
 *
 * `keys` is `null` — not `{}` — on `'unreadable'`, so "silently continue as empty"
 * is not merely discouraged but structurally impossible: a caller that wants keys
 * MUST handle the refusal.
 */
export type KeystoreRead =
  | { outcome: 'loaded' | 'absent'; keys: DecryptedKeys; reason: null }
  | { outcome: 'unreadable'; keys: null; reason: KeystoreUnreadableReason };

/**
 * Raised when a caller that cannot meaningfully continue reads an UNREADABLE
 * keystore (see {@link loadDecryptedKeys}). Fail-closed: refusing loudly is always
 * safer than reporting an empty store that the next write would make permanent.
 */
export class KeystoreUnreadableError extends Error {
  /** The classified cause (never carries key material). */
  readonly reason: KeystoreUnreadableReason;
  constructor(reason: KeystoreUnreadableReason) {
    super(
      `the secure keystore exists but could not be read (${reason}); refusing to treat it as empty`,
    );
    this.name = 'KeystoreUnreadableError';
    this.reason = reason;
  }
}

/**
 * Raised when an EXISTING keystore blob could not be copied aside before being
 * overwritten. The caller must then NOT overwrite it: without a backup an overwrite
 * is irreversible, and the whole point of the backup is that no write is ever
 * destructive.
 */
export class KeystoreBackupError extends Error {
  constructor(keystorePath: string) {
    super(`could not back up the existing keystore before overwriting it: ${keystorePath}`);
    this.name = 'KeystoreBackupError';
  }
}

/** On-disk encrypted keystore shape (values are base64 of safeStorage ciphertext). */
interface KeystoreFile {
  version: 1;
  providers: Record<string, string[]>;
  cloudApiKey?: string;
  /**
   * C14: platformId -> base64 safeStorage ciphertext of the JSON
   * {@link SocialToken}. ABSENT in every keystore written before C14, which is why
   * the reader treats a missing `social` key as "no connected accounts" and only an
   * ill-SHAPED one as corruption.
   */
  social?: Record<string, string>;
}

/**
 * Report the platform-selected backend, or null when it can't be determined.
 *
 * `getSelectedStorageBackend` only exists on Linux; on Windows/macOS it is absent
 * or throws. A null return means "not a basic_text refusal" — the DPAPI/Keychain
 * backends there are secure whenever `isEncryptionAvailable()` is true.
 */
export function selectedBackend(safeStorage: SafeStorageLike): string | null {
  const fn = safeStorage.getSelectedStorageBackend;
  if (typeof fn !== 'function') {
    return null;
  }
  try {
    const backend = fn.call(safeStorage);
    return typeof backend === 'string' ? backend : null;
  } catch {
    return null; // platform without the query -> treat as "no basic_text refusal"
  }
}

/**
 * Decide whether keys can be securely persisted, and the banner/session-only
 * fallback when they can't. Refuses when encryption is unavailable OR the backend
 * is the plaintext `basic_text` fallback — NEVER a silent plaintext write.
 */
export function secureStatus(safeStorage: SafeStorageLike): SecureStatus {
  const available = safeStorage.isEncryptionAvailable();
  const backend = selectedBackend(safeStorage);
  const secure = available && backend !== BASIC_TEXT_BACKEND;
  if (secure) {
    return { available, backend, sessionOnly: false, banner: null };
  }
  return { available, backend, sessionOnly: true, banner: SESSION_ONLY_BANNER };
}

/** Encrypt `plaintext` to a base64 string; throws when no secure backend exists. */
export function encryptToBase64(safeStorage: SafeStorageLike, plaintext: string): string {
  if (secureStatus(safeStorage).sessionOnly) {
    throw new KeystoreUnavailableError();
  }
  return safeStorage.encryptString(plaintext).toString('base64');
}

/** Decrypt a base64 string produced by {@link encryptToBase64} (MAIN process only). */
export function decryptFromBase64(safeStorage: SafeStorageLike, b64: string): string {
  return safeStorage.decryptString(Buffer.from(b64, 'base64'));
}

/** True when `value` is a real raw key (non-empty and not a redacted "…last4" stand-in). */
function isRawKey(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && !value.startsWith('…');
}

/**
 * Path-injection barrier (CodeQL js/path-injection). The keystore/settings file
 * paths derive from the app userData dir / the data root (itself already validated
 * by dataRoot.ts `isSafeLocalDataRoot`), so they are trusted — but a filesystem
 * path is still a tainted sink CodeQL tracks. Re-derive the target from its
 * resolved directory + a `path.basename` (which cannot contain a separator or
 * `..`) and prove it stays inside that directory. This is the SAME resolve +
 * `startsWith(root + sep)` containment shape used by main.ts `dataRootChild` and
 * exportPath.ts — the barrier CodeQL recognises as a sanitizer. The paths are
 * already safe, so the guard never fires in practice; a genuine escape fails
 * closed (throw) rather than touching a file outside its directory.
 */
function safeFilePath(path: string): string {
  const dir = resolvePath(dirname(path));
  const target = resolvePath(dir, basename(path));
  if (target !== dir && !target.startsWith(dir + sep)) {
    throw new Error('keystore path escaped its directory');
  }
  return target;
}

/**
 * Whitelist-style guard for a provider id used as an OBJECT PROPERTY KEY (CodeQL
 * js/remote-property-injection). The id originates from a renderer providers.upsert
 * request / a legacy settings.json, so a hostile `__proto__` / `constructor` /
 * `prototype` key — or one carrying a path/JSON separator — must never reach a
 * computed property write (prototype-pollution vector). Legitimate provider ids are
 * simple slugs (`groq`, `openrouter`, `cloud`, …), so this rejects nothing real.
 */
function isSafeProviderId(id: string): boolean {
  return (
    id !== '__proto__' &&
    id !== 'constructor' &&
    id !== 'prototype' &&
    !id.includes('/') &&
    !id.includes('\\')
  );
}

/** Extract the raw (non-redacted) plaintext keys currently living in a settings object. */
export function extractPlaintextKeys(settings: unknown): DecryptedKeys {
  const out: DecryptedKeys = { providers: {} };
  if (!settings || typeof settings !== 'object') {
    return out;
  }
  const obj = settings as Record<string, unknown>;
  const providers = obj.providers;
  if (Array.isArray(providers)) {
    for (const entry of providers) {
      if (!entry || typeof entry !== 'object') continue;
      const p = entry as Record<string, unknown>;
      const id = p.id;
      const keys = p.apiKeys;
      if (typeof id !== 'string' || !Array.isArray(keys)) continue;
      const raw = keys.filter(isRawKey);
      if (raw.length > 0 && isSafeProviderId(id)) {
        out.providers[id] = raw;
      }
    }
  }
  if (isRawKey(obj.cloudApiKey)) {
    out.cloudApiKey = obj.cloudApiKey;
  }
  return out;
}

/** True when `settings` still holds any raw plaintext key (drives the migration decision). */
function hasPlaintextKeys(keys: DecryptedKeys): boolean {
  return Object.keys(keys.providers).length > 0 || keys.cloudApiKey !== undefined;
}

/** True for a plain (non-null, non-array) object — the only valid keystore shape. */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Decode one decrypted {@link SocialToken} blob, or `null` when it is unusable.
 *
 * `null` means CORRUPTION, and the caller escalates it to a store-wide
 * `'shape-invalid'` refusal rather than dropping the entry: a connected account
 * whose record cannot be read must not be reported as "not connected", because the
 * next write would then make that loss permanent (the same reasoning as
 * {@link KeystoreRead}).
 *
 * A record with no non-empty `accessToken` is corruption by definition — there is no
 * credential in it, so it cannot represent a connected account. The remaining fields
 * are display metadata and are defaulted rather than rejected, so a token written by
 * an older/newer build that omits one still loads.
 */
function parseSocialToken(plaintext: string): SocialToken | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(plaintext);
  } catch {
    return null;
  }
  if (!isPlainObject(parsed)) {
    return null;
  }
  const accessToken = parsed.accessToken;
  if (typeof accessToken !== 'string' || accessToken === '') {
    return null;
  }
  const scopes = parsed.scopes;
  return {
    accessToken,
    refreshToken: typeof parsed.refreshToken === 'string' ? parsed.refreshToken : '',
    expiresAt: typeof parsed.expiresAt === 'number' ? parsed.expiresAt : 0,
    accountLabel: typeof parsed.accountLabel === 'string' ? parsed.accountLabel : '',
    scopes: Array.isArray(scopes) ? scopes.filter((s): s is string => typeof s === 'string') : [],
  };
}

/**
 * A JSON read that DISTINGUISHES "not there" from "there but unusable" — the
 * distinction {@link readKeystore} is built on. `readJson` below folds both back into
 * `undefined` for the settings-file callers, which only need "did I get an object".
 */
type ClassifiedJson =
  | { kind: 'json'; value: unknown }
  | { kind: 'absent' }
  | { kind: 'unreadable'; reason: 'read-failed' | 'parse-failed' };

function readJsonClassified(path: string): ClassifiedJson {
  let text: string;
  try {
    text = readFileSync(safeFilePath(path), 'utf8');
  } catch (err) {
    // ENOENT is the ONLY code that means "nothing is stored here". Everything else
    // (EACCES / EBUSY / EISDIR / EPERM) means a blob exists that we must not clobber.
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
      return { kind: 'absent' };
    }
    return { kind: 'unreadable', reason: 'read-failed' };
  }
  try {
    return { kind: 'json', value: JSON.parse(text) };
  } catch {
    return { kind: 'unreadable', reason: 'parse-failed' };
  }
}

function readJson(path: string): unknown {
  const read = readJsonClassified(path);
  return read.kind === 'json' ? read.value : undefined;
}

/** Atomic JSON write (temp sibling + rename) mirroring the sidecar's settings store. */
function writeJsonAtomic(path: string, data: unknown): void {
  const safe = safeFilePath(path);
  const tmp = safeFilePath(`${safe}.tmp`);
  writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
  renameSync(tmp, safe);
}

/**
 * The three distinguishable end-states of a {@link shredFile} attempt. A plain
 * boolean conflated `absent` with `intact`, so the migration could not tell a
 * copy that was safely gone from one that survived, recoverable, on disk. The
 * caller keys off this to warn ONLY about a lingering plaintext copy.
 *   - `'shredded'` — the plaintext at that path is genuinely gone (truncated OR
 *                    removed).
 *   - `'absent'`   — nothing was there to shred (ENOENT); no action needed.
 *   - `'intact'`   — the target EXISTED but could NOT be scrubbed (both arms
 *                    failed); a still-recoverable copy the user must remove.
 */
export type ShredOutcome = 'shredded' | 'absent' | 'intact';

/**
 * `'r+'` (`O_RDWR`) open flags, plus `O_NOFOLLOW` on the platforms that define it, so
 * the open ITSELF refuses a symlink with no check-then-use window at all. Windows
 * does not expose the flag (`fs.constants.O_NOFOLLOW === undefined` there), which is
 * why {@link isLinkedElsewhere} is a mandatory pre-check rather than a belt-and-braces
 * extra. Pure + injectable so BOTH platform shapes are unit-pinned from either host.
 */
export function shredOpenFlags(constants: { O_RDWR: number; O_NOFOLLOW?: number }): number {
  return constants.O_RDWR | (constants.O_NOFOLLOW ?? 0);
}

const SHRED_OPEN_FLAGS = shredOpenFlags(fsConstants);

/**
 * True when the bytes at `safe` are shared with a file OUTSIDE this path, so a shred
 * would destroy an unrelated file rather than a plaintext copy:
 *   - a SYMLINK / junction (`lstat` does not follow it, unlike the `'r+'` open, which
 *     is exactly how a hostile or stale `settings.json.bak -> <victim>` link turned
 *     the shred into an arbitrary-file truncation); or
 *   - a HARD LINK (`nlink > 1`): truncating one name zeroes the shared inode, so the
 *     other name's content is destroyed too (measured: a 23-byte victim -> 0 bytes).
 *     No symlink privilege is needed to plant one, so this variant matters most.
 *
 * TOCTOU residual, stated plainly: between this `lstat` and the `openSync` below, a
 * writer able to swap the path could still win a race. `O_NOFOLLOW`
 * ({@link shredOpenFlags}) closes that window on POSIX; Windows does not offer the
 * flag, so a narrow window remains there. Both paths swept live under the app's own
 * userData / data root, so an attacker who can win that race can already write those
 * files directly. A probe that itself fails (a malformed path) answers `false` and
 * lets the open classify the path — {@link shredFile} must stay total, because its
 * caller sweeps in a loop and must not abort mid-sweep.
 */
function isLinkedElsewhere(safe: string): boolean {
  try {
    const stat = lstatSync(safe, { throwIfNoEntry: false });
    return stat !== undefined && (stat.isSymbolicLink() || stat.nlink > 1);
  } catch {
    return false;
  }
}

/**
 * Truncate a file's bytes to zero then delete it, so a plaintext copy cannot be
 * recovered from the freed inode by a casual read.
 *
 * SECURITY CONTRACT (returns the outcome so the caller learns the state WITHOUT a
 * separate `existsSync` probe — see the TOCTOU note below):
 *   - `'shredded'` ONLY when the bytes were truncated OR the file was removed — i.e.
 *             the plaintext at that path is genuinely gone. The caller (migration)
 *             lists these in `shredded[]` as "plaintext key material destroyed".
 *   - `'absent'`   when the target does not exist (ENOENT) — nothing to shred, and
 *             nothing for the user to clean up.
 *   - `'intact'`   when the target EXISTED but is still fully on disk — a LOCKED /
 *             read-only / unwritable file, or a directory, where BOTH the truncate
 *             and the unlink failed. Reporting such a file as shredded would let the
 *             caller wrongly believe a recoverable plaintext copy is gone; instead
 *             the migration lists it in `unshreddable[]` so it is surfaced for manual
 *             removal. "Existed" is NOT "shredded".
 *
 * No `existsSync`-based check-then-act (CodeQL js/file-system-race): existence is
 * still decided by the OPEN, not by a probe, and the caller needs NO
 * `existsSync`-AFTER-shred to distinguish absent from intact (that separate probe
 * would re-introduce a race, plus a js/path-injection sink) — the 3-state return
 * carries that fact out directly. We open with `O_RDWR` (+`O_NOFOLLOW` where the
 * platform has it) — a single atomic syscall that REQUIRES the file to exist and
 * never creates it — so a truly-absent file fails `ENOENT` (returning `'absent'`)
 * instead of being silently created by a later write. The ONE pre-open probe is the
 * `lstat` link check ({@link isLinkedElsewhere}), which is a SAFETY guard, not an
 * existence check: it can only turn a destructive truncate into a refusal, and its
 * residual race window is documented inline there.
 */
export function shredFile(path: string): ShredOutcome {
  const safe = safeFilePath(path);
  if (isLinkedElsewhere(safe)) {
    // The bytes at this path are NOT a private plaintext copy — they live in (or are
    // shared with) a file somewhere else, so truncating "the copy" would destroy an
    // unrelated user file. Report 'intact' (surfaced in `unshreddable[]` for manual
    // review) instead of following the link. See isLinkedElsewhere.
    return 'intact';
  }
  let scrubbed = false;
  let fd: number | undefined;
  try {
    fd = openSync(safe, SHRED_OPEN_FLAGS);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
      return 'absent'; // truly absent — nothing to shred
    }
    /* EISDIR/EACCES/EBUSY/…: exists but can't be opened r+; try the unlink below */
  }
  if (fd !== undefined) {
    try {
      ftruncateSync(fd, 0); // scrub the bytes in place before unlinking
      scrubbed = true; // the plaintext bytes are now zeroed
    } catch {
      /* truncate failed (e.g. lock acquired) — fall through to the unlink attempt */
    } finally {
      try {
        closeSync(fd);
      } catch {
        /* ignore a close failure — the fd is abandoned on process exit */
      }
    }
  }
  try {
    unlinkSync(safe);
    scrubbed = true; // the file is gone — no plaintext left at this path
  } catch {
    /* unlink failed; `scrubbed` reflects whether the truncate succeeded */
  }
  // Only report a real shred: a locked/unwritable/intact file (both arms failed)
  // returns 'intact' so the caller never lists a still-recoverable copy as destroyed.
  return scrubbed ? 'shredded' : 'intact';
}

/**
 * Every prior on-disk copy of the settings file that could hold a plaintext key:
 * the atomic-write `.tmp` sibling and any backup files (`settings.json.bak`,
 * `settings.json.backup`, `settings.json.1`, …) beside it. The canonical file
 * itself is scrubbed in-place separately (its non-secret settings are preserved).
 * Exported for direct unit coverage of the unreadable-directory arm.
 */
export function priorCopies(settingsPath: string): string[] {
  // Route through the containment barrier so `dir` is a sanitised (post-guard)
  // value before it reaches the `readdirSync` sink (CodeQL js/path-injection).
  const safe = safeFilePath(settingsPath);
  const dir = dirname(safe);
  const base = basename(safe);
  const out: string[] = [];
  let names: string[];
  try {
    names = readdirSync(dir);
  } catch {
    return out;
  }
  for (const name of names) {
    // A sibling that starts with the settings basename but is NOT the canonical
    // file (e.g. "settings.json.tmp", "settings.json.bak") is a stale copy.
    if (name.startsWith(base) && name !== base) {
      out.push(join(dir, name));
    }
  }
  return out;
}

/**
 * True when a prior copy is READABLE, parses as JSON, and provably holds NO plaintext
 * keys — i.e. a non-secret settings backup the sweep must NOT destroy. Anything we
 * cannot prove key-free is deliberately NOT this: unreadable/locked, a directory, or
 * non-JSON (which could still hold raw key bytes — e.g. a `"…backup sk-live…"` blob),
 * as well as JSON that DOES contain keys. So a pre-migration backup that captured the
 * plaintext keys is still destroyed (it holds keys), while a post-migration key-free
 * backup a user kept is preserved.
 *
 * "Key-free" means key-free PER THE APP'S OWN KEY MODEL — the very same
 * {@link extractPlaintextKeys} the migration uses to decide migrate-vs-noop, which is
 * exactly the two shapes the app (main + sidecar settings_store) ever writes:
 * `providers[].apiKeys` (safe id) and top-level `cloudApiKey`. This is deliberate and
 * symmetric: a settings.json copy the app produced carries its keys ONLY in those
 * shapes, so every app-written sibling with keys is detected and swept.
 *
 * IRREDUCIBLE RESIDUAL (intentional, reviewed): a HAND-CRAFTED sibling holding a key
 * outside those shapes (e.g. `{"notes":"sk-ant-…"}`, a top-level array, or a key under
 * an unsafe provider id) parses key-free and is preserved. This is not reachable by any
 * file the app writes, and it is exactly symmetric with the live settings.json (the same
 * detector governs both — a key the migration wouldn't manage there, it doesn't manage
 * here). A broader entropy/substring scanner is deliberately NOT used: it would be
 * asymmetric with the migration and would false-positive-destroy legitimate non-secret
 * backups (paths, UUIDs, tokens) — reintroducing the very data-loss this predicate fixes.
 */
function isKeyFreeSettingsCopy(path: string): boolean {
  const parsed = readJson(path);
  if (parsed === undefined) {
    return false; // unreadable / not valid JSON — cannot prove it is key-free
  }
  return !hasPlaintextKeys(extractPlaintextKeys(parsed));
}

/**
 * Shred every prior plaintext copy of settings.json that could hold key material,
 * classifying each outcome. A readable, valid-JSON, key-FREE sibling is a non-secret
 * settings backup and is LEFT UNTOUCHED (see {@link isKeyFreeSettingsCopy}) — the
 * sweep only ever destroys copies that hold (or might hold) plaintext keys.
 *
 * Run on EVERY boot (not only when settings.json still holds keys) so a copy the app
 * could NOT delete on an earlier boot keeps being re-attempted and re-reported until
 * it is truly gone — otherwise the security warning silently vanishes on the next
 * restart (settings.json is already stripped, so the migration is a no-op) while a
 * recoverable plaintext key copy lingers on disk.
 */
function sweepPriorPlaintextCopies(settingsPath: string): {
  shredded: string[];
  unshreddable: string[];
} {
  const shredded: string[] = [];
  const unshreddable: string[] = [];
  for (const copy of priorCopies(settingsPath)) {
    if (isKeyFreeSettingsCopy(copy)) {
      continue; // a non-secret settings backup — never destroy the user's data
    }
    const outcome = shredFile(copy);
    if (outcome === 'shredded') {
      shredded.push(copy); // plaintext genuinely destroyed
    } else if (outcome === 'intact') {
      unshreddable.push(copy); // existed but survived — surface for manual removal
    }
    // 'absent' copies (already gone by the time we looked) need no action.
  }
  return { shredded, unshreddable };
}

/**
 * Where the CURRENT keystore ciphertext is copied before it is overwritten. The stamp
 * is UTC, fixed-width, and punctuation-free (`20260725T054751123`) so a plain
 * lexicographic sort of the sibling names IS chronological order — which is what
 * {@link pruneKeystoreBackups} relies on to decide which generations are oldest.
 */
export function keystoreBackupPath(keystorePath: string, when: Date): string {
  const stamp = when.toISOString().replace(/[-:.]/g, '').replace(/Z$/, '');
  return `${keystorePath}.${stamp}${KEYSTORE_BACKUP_EXT}`;
}

/**
 * Delete all but the newest `keep` timestamped backups and return what was removed.
 * Never throws: a backup that cannot be deleted is simply left in place (a stale
 * ciphertext file is harmless; aborting a key save over it would not be).
 */
export function pruneKeystoreBackups(keystorePath: string, keep: number): string[] {
  // Route through the containment barrier so `dir` is a sanitised (post-guard) value
  // before it reaches the `readdirSync` sink (CodeQL js/path-injection), exactly as
  // priorCopies does.
  const safe = safeFilePath(keystorePath);
  const dir = dirname(safe);
  const prefix = `${basename(safe)}.`;
  let names: string[];
  try {
    names = readdirSync(dir);
  } catch {
    return [];
  }
  const backups = names
    .filter((name) => name.startsWith(prefix) && name.endsWith(KEYSTORE_BACKUP_EXT))
    .sort();
  const pruned: string[] = [];
  for (const name of backups.slice(0, Math.max(0, backups.length - keep))) {
    const target = join(dir, name);
    try {
      unlinkSync(safeFilePath(target));
      pruned.push(target);
    } catch {
      /* leave an un-deletable stale backup alone — never fail a key save over it */
    }
  }
  return pruned;
}

/** Whether a pre-overwrite backup was taken, or there was simply nothing to protect. */
export type KeystoreBackupOutcome = 'backed-up' | 'nothing-to-back-up';

/**
 * Copy the CURRENT keystore blob aside under a timestamped name so NO overwrite is
 * ever destructive — the second half of the wipe fix. Even a caller that correctly
 * fails closed on an unreadable read can be overwriting a blob it merely *believes*
 * is disposable (a stale generation, a `safeStorage` that recovers on the next boot),
 * so the last-resort recovery copy is unconditional.
 *
 * A raw byte copy, deliberately NOT a JSON round-trip: a corrupt blob must be
 * preserved EXACTLY as found, because that is the only thing a recovery could work
 * from. The bytes are `safeStorage` ciphertext, so this writes no plaintext key.
 *
 * @throws KeystoreBackupError when a blob EXISTS but could not be copied — the caller
 *         must then abandon the overwrite rather than destroy the only copy.
 */
export function backupKeystore(keystorePath: string, when: Date): KeystoreBackupOutcome {
  const source = safeFilePath(keystorePath);
  const target = safeFilePath(keystoreBackupPath(keystorePath, when));
  try {
    copyFileSync(source, target);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
      // The first-ever write: there is no prior generation to protect. (ENOENT on the
      // TARGET's directory lands here too, but then the atomic write that follows
      // fails the same way, so no blob is lost either.)
      return 'nothing-to-back-up';
    }
    throw new KeystoreBackupError(keystorePath);
  }
  pruneKeystoreBackups(keystorePath, KEYSTORE_BACKUP_RETENTION);
  return 'backed-up';
}

/**
 * Persist the encrypted keystore (base64 ciphertext) atomically to `keystorePath`,
 * after copying any existing generation aside ({@link backupKeystore}).
 *
 * Order matters: encrypt FIRST (so a session-only refusal costs no backup), back up
 * SECOND, write LAST. A backup failure propagates and the write never happens.
 */
function writeKeystore(
  safeStorage: SafeStorageLike,
  keystorePath: string,
  keys: DecryptedKeys,
): void {
  const file: KeystoreFile = { version: 1, providers: {} };
  for (const [id, rawKeys] of Object.entries(keys.providers)) {
    if (!isSafeProviderId(id)) continue; // never persist a proto-polluting key id
    file.providers[id] = rawKeys.map((k) => encryptToBase64(safeStorage, k));
  }
  if (keys.cloudApiKey !== undefined) {
    file.cloudApiKey = encryptToBase64(safeStorage, keys.cloudApiKey);
  }
  if (keys.social !== undefined) {
    // C14: one ciphertext blob per platform. The WHOLE record is encrypted (not
    // just the two token fields) so a field added later cannot land on the
    // plaintext side by omission.
    const social: Record<string, string> = {};
    for (const [platform, token] of Object.entries(keys.social)) {
      if (!isSafeProviderId(platform)) continue; // never persist a proto-polluting id
      social[platform] = encryptToBase64(safeStorage, JSON.stringify(token));
    }
    file.social = social;
  }
  backupKeystore(keystorePath, new Date());
  writeJsonAtomic(keystorePath, file);
}

/**
 * Persist the full {@link DecryptedKeys} map (re-encrypted) to `keystorePath`.
 *
 * The public writer used by the live providers.upsert interception (keyBridge.ts)
 * to keep the keystore the single at-rest home of raw keys. REFUSES (throws
 * {@link KeystoreUnavailableError} via {@link encryptToBase64}) when no secure
 * backend exists — NEVER a silent plaintext write; the caller falls back to a
 * session-only in-memory overlay.
 */
export function saveDecryptedKeys(
  safeStorage: SafeStorageLike,
  keystorePath: string,
  keys: DecryptedKeys,
): void {
  writeKeystore(safeStorage, keystorePath, keys);
}

/**
 * Load + decrypt the keystore, CLASSIFYING the outcome — the read every caller that
 * might go on to WRITE must use.
 *
 * `'absent'` (no keystore yet) and `'unreadable'` (a blob that exists but cannot be
 * trusted) are kept strictly apart, because conflating them is the credential wipe:
 * an unreadable store reported as empty gets silently replaced by the next save. On
 * `'unreadable'` no partial key set is returned (`keys === null`) — a half-decrypted
 * store is exactly as dangerous to persist as an empty one.
 *
 * Total by contract: read, parse, shape and decrypt failures are all classified, so
 * this NEVER throws and a caller can always reach a decision.
 */
export function readKeystore(safeStorage: SafeStorageLike, keystorePath: string): KeystoreRead {
  const unreadable = (reason: KeystoreUnreadableReason): KeystoreRead => ({
    outcome: 'unreadable',
    keys: null,
    reason,
  });
  const raw = readJsonClassified(keystorePath);
  if (raw.kind === 'absent') {
    return { outcome: 'absent', keys: { providers: {} }, reason: null };
  }
  if (raw.kind === 'unreadable') {
    return unreadable(raw.reason);
  }
  if (!isPlainObject(raw.value)) {
    return unreadable('shape-invalid');
  }
  const file = raw.value as Partial<KeystoreFile>;
  const out: DecryptedKeys = { providers: {} };
  if (file.providers !== undefined) {
    if (!isPlainObject(file.providers)) {
      return unreadable('shape-invalid');
    }
    for (const [id, encKeys] of Object.entries(file.providers)) {
      if (!Array.isArray(encKeys)) {
        return unreadable('shape-invalid'); // a corrupt key list, NOT an empty one
      }
      // A `__proto__`/`constructor` id cannot have come from writeKeystore (it filters
      // them) and is not loadable provider material, so it is dropped rather than
      // escalated to a store-wide refusal — dropping it loses no usable credential.
      if (!isSafeProviderId(id)) continue;
      try {
        out.providers[id] = encKeys.map((b64) => decryptFromBase64(safeStorage, b64));
      } catch {
        return unreadable('decrypt-failed');
      }
    }
  }
  if (file.cloudApiKey !== undefined) {
    if (typeof file.cloudApiKey !== 'string') {
      return unreadable('shape-invalid');
    }
    try {
      out.cloudApiKey = decryptFromBase64(safeStorage, file.cloudApiKey);
    } catch {
      return unreadable('decrypt-failed');
    }
  }
  // C14 social tokens. An ABSENT section is the normal pre-C14 shape and means "no
  // connected accounts"; a present-but-ill-shaped one is corruption and fails
  // closed, so a save can never quietly replace real tokens with nothing.
  if (file.social !== undefined) {
    if (!isPlainObject(file.social)) {
      return unreadable('shape-invalid');
    }
    const social: Record<string, SocialToken> = {};
    for (const [platform, blob] of Object.entries(file.social)) {
      if (typeof blob !== 'string') {
        return unreadable('shape-invalid');
      }
      // As with a provider id, a `__proto__`/`constructor` key cannot have come from
      // writeKeystore and is not a loadable account, so it is dropped rather than
      // escalated — dropping it loses no usable credential.
      if (!isSafeProviderId(platform)) continue;
      let plaintext: string;
      try {
        plaintext = decryptFromBase64(safeStorage, blob);
      } catch {
        return unreadable('decrypt-failed');
      }
      const token = parseSocialToken(plaintext);
      if (token === null) {
        return unreadable('shape-invalid');
      }
      social[platform] = token;
    }
    out.social = social;
  }
  return { outcome: 'loaded', keys: out, reason: null };
}

/**
 * Load + decrypt the keystore for main to inject into the sidecar per-request
 * over the existing stdio JSON-RPC frame (NEVER env/argv/settings.json). Returns
 * empty when no keystore exists yet.
 *
 * FAILS CLOSED: an existing-but-unreadable keystore throws
 * {@link KeystoreUnreadableError} rather than returning an empty map. Callers that
 * must distinguish (and in particular any caller that may then WRITE) should use
 * {@link readKeystore} and handle `'unreadable'` explicitly — see keyBridge.ts.
 */
export function loadDecryptedKeys(
  safeStorage: SafeStorageLike,
  keystorePath: string,
): DecryptedKeys {
  const read = readKeystore(safeStorage, keystorePath);
  if (read.outcome === 'unreadable') {
    throw new KeystoreUnreadableError(read.reason);
  }
  return read.keys;
}

/** Rewrite a settings object with every raw key stripped (metadata preserved). */
export function stripKeysFromSettings(settings: unknown): Record<string, unknown> {
  const obj = (
    settings && typeof settings === 'object' ? { ...(settings as Record<string, unknown>) } : {}
  ) as Record<string, unknown>;
  const providers = obj.providers;
  if (Array.isArray(providers)) {
    obj.providers = providers.map((entry) => {
      if (!entry || typeof entry !== 'object') return entry;
      const p = entry as Record<string, unknown>;
      if (!Array.isArray(p.apiKeys)) return entry;
      return { ...p, apiKeys: [] };
    });
  }
  if ('cloudApiKey' in obj) {
    delete obj.cloudApiKey;
  }
  return obj;
}

/**
 * One-time v1.3 migration: re-encrypt any legacy plaintext keys in `settingsPath`
 * into the DPAPI keystore, then SHRED every prior plaintext copy.
 *
 *   * NO plaintext keys present   -> `noop` (nothing to migrate) — but still SWEEP any
 *     lingering prior plaintext copy so a still-recoverable legacy copy is cleaned
 *     up / re-reported on every restart, not only the boot that migrated.
 *   * Keys present, secure store  -> encrypt into `keystorePath`, strip the keys
 *     from settings.json, and shred the `.tmp` + backup siblings. After this the
 *     migration guarantees ZERO plaintext key bytes remain on disk.
 *   * Keys present, NO secure store -> `refused`: we neither encrypt (impossible)
 *     nor destroy the user's only key copy; keys are session-only and a loud
 *     banner is returned. NEVER a silent plaintext keystore write.
 */
export function migrateLegacyPlaintextKeys(
  safeStorage: SafeStorageLike,
  settingsPath: string,
  keystorePath: string,
): MigrationResult {
  const settings = readJson(settingsPath);
  const keys = extractPlaintextKeys(settings);

  if (!hasPlaintextKeys(keys)) {
    // Nothing to migrate, but a legacy plaintext copy from an earlier boot may still
    // be on disk (settings.json was stripped, so we'd never reach the shred loop
    // below). Sweep them here too so a lingering, still-recoverable copy is cleaned
    // up — or re-reported when it can't be — on EVERY restart, not just the one boot
    // that happened to migrate. See sweepPriorPlaintextCopies.
    const swept = sweepPriorPlaintextCopies(settingsPath);
    return {
      status: 'noop',
      migratedProviderKeys: 0,
      migratedCloudKey: false,
      shredded: swept.shredded,
      unshreddable: swept.unshreddable,
      sessionOnly: false,
      banner: null,
    };
  }

  const status = secureStatus(safeStorage);
  if (status.sessionOnly) {
    // Cannot encrypt AND must not destroy the user's only copy: refuse loudly.
    return {
      status: 'refused',
      migratedProviderKeys: 0,
      migratedCloudKey: false,
      shredded: [],
      unshreddable: [],
      sessionOnly: true,
      banner: status.banner,
    };
  }

  // 1. Re-encrypt every plaintext key into the DPAPI keystore.
  writeKeystore(safeStorage, keystorePath, keys);

  // 2. Strip the raw keys from settings.json (preserving all non-secret settings),
  //    then shred every stale prior copy that could still hold plaintext.
  writeJsonAtomic(settingsPath, stripKeysFromSettings(settings));
  const swept = sweepPriorPlaintextCopies(settingsPath);

  const providerKeyCount = Object.values(keys.providers).reduce((n, arr) => n + arr.length, 0);
  return {
    status: 'migrated',
    migratedProviderKeys: providerKeyCount,
    migratedCloudKey: keys.cloudApiKey !== undefined,
    shredded: swept.shredded,
    unshreddable: swept.unshreddable,
    sessionOnly: false,
    banner: null,
  };
}

/** Absolute path of the encrypted keystore inside `userDataDir`. */
export function keystorePathFor(userDataDir: string): string {
  return join(userDataDir, KEYSTORE_FILENAME);
}
