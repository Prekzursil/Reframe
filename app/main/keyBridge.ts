// keyBridge.ts — WU-D2b-1 (MAIN WIRING): the main-process guard that keeps RAW
// provider API keys in the DPAPI keystore and NEVER lets a plaintext key reach
// the sidecar's at-rest store. It is the "defense-in-depth" half agreed by the
// orchestrator (B): main intercepts on the ONE `rpc` channel (ipc.ts), and the
// sidecar's settings_store ALSO strips keys before persist (WU-D2b-2). Together
// the "zero plaintext key bytes at rest" invariant holds on EVERY path.
//
// Two responsibilities, both applied in forwardParams() before sidecar.request:
//
//   1. providers.upsert — pull the RAW `apiKeys` out of the request, restore any
//      redacted last-4 stand-ins back to their stored raw key (mirroring the
//      sidecar's frozen get -> set round-trip contract), persist the resolved raw
//      set into the DPAPI keystore, and forward a FULLY-REDACTED entry so the
//      sidecar only ever sees / persists last-4 metadata — never a raw key.
//
//   2. provider-CALLING methods (ai.*, director.*, shortmaker.*, index.*, plus
//      subtitles.translate and the providers.* reads that need live key material:
//      usage / openrouterUsage / revealKey) — inject the decrypted keys into
//      `params._injectedKeys` for WU-D2b-2 to consume. This travels IN MEMORY over
//      the existing stdio JSON-RPC frame ONLY: never an env var, never argv, never
//      a log line, never persisted by main.
//
// KNOWN + ACCEPTED (D2b-1 in isolation): the sidecar factory still reads keys from
// its settings_store, so runtime provider calls are broken until D2b-2 consumes
// `_injectedKeys`. U2 lands right after in this same run.
import {
  type DecryptedKeys,
  type SafeStorageLike,
  type SecureStatus,
  loadDecryptedKeys,
  saveDecryptedKeys,
  secureStatus,
} from './keystore';

/** The per-request field carrying decrypted keys to the sidecar (in-memory, stdio only). */
export const INJECTED_KEYS_FIELD = '_injectedKeys';

/** The provider write RPC main intercepts to strip raw keys into the keystore. */
export const UPSERT_METHOD = 'providers.upsert';

const ELLIPSIS = '…';
const VISIBLE_TAIL = 4;

/**
 * Mirror of the sidecar's `secrets.redact`: a display-safe last-4 redaction. Long
 * keys render as `…WXYZ` (ellipsis + last 4); keys of 4 or fewer chars (where the
 * "last 4" would expose the whole key) render as a bare `…`. Kept byte-identical
 * to the Python side so a forwarded redaction matches what the sidecar's
 * get -> set restore expects.
 */
export function redactKey(key: string): string {
  return key.length > VISIBLE_TAIL ? `${ELLIPSIS}${key.slice(-VISIBLE_TAIL)}` : ELLIPSIS;
}

/** True when `value` is a raw key: a non-empty string that is NOT a redacted stand-in. */
function isRawKey(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && !value.startsWith(ELLIPSIS);
}

/** Method-name prefixes whose handlers build a provider/pool and need raw keys. */
const INJECT_PREFIXES: readonly string[] = ['ai.', 'director.', 'shortmaker.', 'index.'];

/** Exact provider-calling / key-reading methods outside the prefix families. */
const INJECT_METHODS: ReadonlySet<string> = new Set([
  'subtitles.translate', // the translation seam (TieredTranslator tier-3 hosted pool)
  'providers.usage', // builds the rotation pool to read per-key usage
  'providers.openrouterUsage', // GETs /key per RAW OpenRouter key
  'providers.revealKey', // returns the ONE stored raw key for a user-clicked reveal
]);

/**
 * True when `method`'s sidecar handler needs live raw key material, so main must
 * inject the decrypted keys. Enumerates the real provider-calling seams (ai.* /
 * director.* / shortmaker.* / index.* / translation / the key-reading providers.*
 * reads) — NOT providers.upsert (that is the store path, handled separately) and
 * NOT providers.testKey (its key rides the request params directly, transiently).
 */
export function needsKeyInjection(method: string): boolean {
  return INJECT_PREFIXES.some((prefix) => method.startsWith(prefix)) || INJECT_METHODS.has(method);
}

/**
 * Swap a redacted `incoming` value back to the RAW `stored` key — the TS twin of
 * the sidecar's `SettingsStore._restore_one`. Returns `stored` only when
 * `incoming` is exactly the redaction of a non-empty stored raw key; otherwise
 * `incoming` is a genuinely new value and is returned as-is.
 */
function restoreOne(incoming: unknown, stored: string | undefined): unknown {
  if (
    typeof incoming === 'string' &&
    typeof stored === 'string' &&
    stored !== '' &&
    incoming === redactKey(stored)
  ) {
    return stored;
  }
  return incoming;
}

/** The plan produced from a providers.upsert request before it is forwarded. */
export interface UpsertPlan {
  /** The provider id being upserted, or null when the request carries no valid id. */
  providerId: string | null;
  /**
   * The resolved RAW keys to persist for `providerId`, or null when the upsert
   * carries no `apiKeys` at all (e.g. an enabled/model-only patch) — in which case
   * the keystore is left untouched and the params are forwarded verbatim.
   */
  resolvedKeys: string[] | null;
  /** The params to forward to the sidecar, with every apiKey redacted to last-4. */
  forwardParams: Record<string, unknown>;
}

/** True when `value` is a plain (non-array) object we can treat as a params entry. */
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Plan a providers.upsert: locate the provider entry (the sidecar accepts a bare
 * `{id, apiKeys, …}` OR a nested `{provider: {…}}`), restore redacted stand-ins
 * against `storedFor(id)`, and produce the resolved raw key set + a fully-redacted
 * forward payload. Positional match by index mirrors the sidecar's frozen
 * `_restore_provider` contract the renderer was built against.
 */
export function planUpsert(
  params: Record<string, unknown> | undefined,
  storedFor: (id: string) => string[],
): UpsertPlan {
  const base = params ?? {};
  const nested = base.provider;
  const entryIsNested = isRecord(nested);
  const entry = entryIsNested ? nested : base;
  const id = entry.id;
  const providerId = typeof id === 'string' && id !== '' ? id : null;
  const apiKeys = entry.apiKeys;
  if (providerId === null || !Array.isArray(apiKeys)) {
    return { providerId, resolvedKeys: null, forwardParams: base };
  }
  const stored = storedFor(providerId);
  // Restore each redacted stand-in to its stored raw key, then keep only the
  // real raw keys — a stand-in with no stored counterpart is dropped rather
  // than persisted as a bogus "key".
  const resolvedKeys = apiKeys.map((k, i) => restoreOne(k, stored[i])).filter(isRawKey);
  const redactedEntry = { ...entry, apiKeys: resolvedKeys.map(redactKey) };
  const forwardParams = entryIsNested ? { ...base, provider: redactedEntry } : redactedEntry;
  return { providerId, resolvedKeys, forwardParams };
}

/** Constructor deps for {@link KeyBridge} (safeStorage + keystore path are injected). */
export interface KeyBridgeOptions {
  safeStorage: SafeStorageLike;
  keystorePath: string;
  /**
   * Absolute paths of legacy plaintext key copies the boot-time migration could not
   * shred. Carried here so {@link KeyBridge.secureStatus} can surface them to the
   * renderer banner (the only user-visible channel; console output is lost in a
   * packaged build). Defaults to none.
   */
  unshreddable?: readonly string[];
}

/**
 * The stateful main-process key guard wired into ipc.ts. Holds the injected
 * safeStorage + keystore path and a small IN-MEMORY session overlay used when
 * secure storage is unavailable (session-only) — so key entry still works this
 * run WITHOUT ever writing plaintext to disk. The overlay is also layered over the
 * on-disk keystore so a just-upserted key is injectable without a re-read.
 */
export class KeyBridge {
  private readonly safeStorage: SafeStorageLike;
  private readonly keystorePath: string;
  private readonly unshreddable: readonly string[];
  private session: DecryptedKeys = { providers: {} };

  constructor(opts: KeyBridgeOptions) {
    this.safeStorage = opts.safeStorage;
    this.keystorePath = opts.keystorePath;
    this.unshreddable = opts.unshreddable ?? [];
  }

  /**
   * The live availability/refusal decision surfaced to the renderer banner, overlaid
   * with the boot-time migration's `unshreddable` list so the renderer can also warn
   * about any lingering plaintext copy that could not be deleted.
   */
  secureStatus(): SecureStatus {
    return { ...secureStatus(this.safeStorage), unshreddable: [...this.unshreddable] };
  }

  /** On-disk keystore overlaid with this session's in-memory keys (session wins). */
  private currentKeys(): DecryptedKeys {
    let disk: DecryptedKeys = { providers: {} };
    try {
      disk = loadDecryptedKeys(this.safeStorage, this.keystorePath);
    } catch {
      // A decrypt failure (corrupt / foreign-machine keystore) must never crash
      // the app; fall back to the session overlay so key entry still works.
      disk = { providers: {} };
    }
    const providers = { ...disk.providers, ...this.session.providers };
    const cloudApiKey = this.session.cloudApiKey ?? disk.cloudApiKey;
    return cloudApiKey !== undefined ? { providers, cloudApiKey } : { providers };
  }

  /**
   * Intercept providers.upsert: persist the resolved raw keys into the keystore
   * (or the session overlay when secure storage is unavailable) and return the
   * fully-redacted params to forward. NEVER returns a raw key to the sidecar.
   */
  interceptUpsert(params?: Record<string, unknown>): Record<string, unknown> {
    const current = this.currentKeys();
    const plan = planUpsert(params, (id) => current.providers[id] ?? []);
    if (plan.providerId === null || plan.resolvedKeys === null) {
      // No apiKeys in this upsert (id-less, or an enabled/model-only patch): there
      // is nothing secret to store — forward the request unchanged.
      return plan.forwardParams;
    }
    const nextProviders = { ...current.providers };
    if (plan.resolvedKeys.length > 0) {
      nextProviders[plan.providerId] = plan.resolvedKeys;
    } else {
      delete nextProviders[plan.providerId];
    }
    const next: DecryptedKeys =
      current.cloudApiKey !== undefined
        ? { providers: nextProviders, cloudApiKey: current.cloudApiKey }
        : { providers: nextProviders };
    // Always keep the session overlay current so injection sees the new keys even
    // when the disk write is refused (session-only) or fails.
    this.session = next;
    if (!this.secureStatus().sessionOnly) {
      try {
        saveDecryptedKeys(this.safeStorage, this.keystorePath, next);
      } catch {
        // Never a silent plaintext fallback and never a crash: the session overlay
        // already holds the keys for this run, and the loud SESSION_ONLY banner
        // (getSecureStatus) tells the user that saving is unavailable.
      }
    }
    return plan.forwardParams;
  }

  /**
   * Inject the decrypted keys into a provider-calling request under
   * {@link INJECTED_KEYS_FIELD}. Our value always overwrites any renderer-supplied
   * field. In-memory only — this rides the stdio frame and is never logged.
   */
  inject(params?: Record<string, unknown>): Record<string, unknown> {
    return { ...(params ?? {}), [INJECTED_KEYS_FIELD]: this.currentKeys() };
  }

  /**
   * The single transform ipc.ts applies before forwarding to sidecar.request:
   * strip-into-keystore for providers.upsert, inject decrypted keys for
   * provider-calling methods, and pass everything else straight through.
   */
  forwardParams(
    method: string,
    params?: Record<string, unknown>,
  ): Record<string, unknown> | undefined {
    if (method === UPSERT_METHOD) {
      return this.interceptUpsert(params);
    }
    if (needsKeyInjection(method)) {
      return this.inject(params);
    }
    return params;
  }
}
