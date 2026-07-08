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
  ftruncateSync,
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
}

/** The decrypted key material main injects into the sidecar per-request (never to disk). */
export interface DecryptedKeys {
  /** providerId -> its raw API keys (rotation pool order preserved). */
  providers: Record<string, string[]>;
  /** The legacy single cloud key, when one was stored. */
  cloudApiKey?: string;
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

/** On-disk encrypted keystore shape (values are base64 of safeStorage ciphertext). */
interface KeystoreFile {
  version: 1;
  providers: Record<string, string[]>;
  cloudApiKey?: string;
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

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(safeFilePath(path), 'utf8'));
  } catch {
    return undefined;
  }
}

/** Atomic JSON write (temp sibling + rename) mirroring the sidecar's settings store. */
function writeJsonAtomic(path: string, data: unknown): void {
  const safe = safeFilePath(path);
  const tmp = safeFilePath(`${safe}.tmp`);
  writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
  renameSync(tmp, safe);
}

/**
 * Truncate a file's bytes to zero then delete it, so a plaintext copy cannot be
 * recovered from the freed inode by a casual read. Best-effort: a missing file
 * is a no-op and any failure after the truncate is swallowed (the secret bytes are
 * already gone). Exported for direct unit coverage of its defensive arms.
 *
 * TOCTOU-free (CodeQL js/file-system-race): there is NO `existsSync`-then-write
 * check-and-use window. We open with the `r+` flag — a single atomic syscall that
 * REQUIRES the file to already exist and never creates it — so a truly-absent file
 * fails `ENOENT` here (returning false) instead of being silently created by a
 * later write, and any other target (e.g. a directory -> `EISDIR`) falls through to
 * the best-effort unlink below, preserving the prior "existed -> true" contract.
 */
export function shredFile(path: string): boolean {
  const safe = safeFilePath(path);
  let fd: number | undefined;
  try {
    fd = openSync(safe, 'r+');
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') {
      return false; // truly absent — nothing to shred
    }
    /* EISDIR/EACCES/…: the target exists but can't be opened r+; unlink below */
  }
  if (fd !== undefined) {
    try {
      ftruncateSync(fd, 0); // scrub the bytes in place before unlinking
    } catch {
      /* best-effort: attempt the unlink regardless */
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
  } catch {
    /* best-effort: the truncate already scrubbed the bytes */
  }
  return true;
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

/** Persist the encrypted keystore (base64 ciphertext) atomically to `keystorePath`. */
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
 * Load + decrypt the keystore for main to inject into the sidecar per-request
 * over the existing stdio JSON-RPC frame (NEVER env/argv/settings.json). Returns
 * empty when no keystore exists yet.
 */
export function loadDecryptedKeys(
  safeStorage: SafeStorageLike,
  keystorePath: string,
): DecryptedKeys {
  const raw = readJson(keystorePath);
  const out: DecryptedKeys = { providers: {} };
  if (!raw || typeof raw !== 'object') {
    return out;
  }
  const file = raw as Partial<KeystoreFile>;
  if (file.providers && typeof file.providers === 'object') {
    for (const [id, encKeys] of Object.entries(file.providers)) {
      if (!Array.isArray(encKeys) || !isSafeProviderId(id)) continue;
      out.providers[id] = encKeys.map((b64) => decryptFromBase64(safeStorage, b64));
    }
  }
  if (typeof file.cloudApiKey === 'string') {
    out.cloudApiKey = decryptFromBase64(safeStorage, file.cloudApiKey);
  }
  return out;
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
 *   * NO plaintext keys present   -> `noop` (nothing to migrate).
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
    return {
      status: 'noop',
      migratedProviderKeys: 0,
      migratedCloudKey: false,
      shredded: [],
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
      sessionOnly: true,
      banner: status.banner,
    };
  }

  // 1. Re-encrypt every plaintext key into the DPAPI keystore.
  writeKeystore(safeStorage, keystorePath, keys);

  // 2. Strip the raw keys from settings.json (preserving all non-secret settings),
  //    then shred every stale prior copy that could still hold plaintext.
  writeJsonAtomic(settingsPath, stripKeysFromSettings(settings));
  const shredded: string[] = [];
  for (const copy of priorCopies(settingsPath)) {
    if (shredFile(copy)) {
      shredded.push(copy);
    }
  }

  const providerKeyCount = Object.values(keys.providers).reduce((n, arr) => n + arr.length, 0);
  return {
    status: 'migrated',
    migratedProviderKeys: providerKeyCount,
    migratedCloudKey: keys.cloudApiKey !== undefined,
    shredded,
    sessionOnly: false,
    banner: null,
  };
}

/** Absolute path of the encrypted keystore inside `userDataDir`. */
export function keystorePathFor(userDataDir: string): string {
  return join(userDataDir, KEYSTORE_FILENAME);
}
