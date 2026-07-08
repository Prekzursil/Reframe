// dataRoot.ts — pure resolution of the app's ONE relocatable DATA ROOT.
//
// WHY this exists: every heavy artifact (models, envs, exports, proxies, peaks,
// dubs, voices, feedback, chrome) derives from the sidecar's
// `settings_store.default_config_dir()`, which honors `MEDIA_STUDIO_CONFIG_DIR`
// first and otherwise falls back to `%APPDATA%/media-studio`. Defaulting that to
// %APPDATA% buries multiple GB inside AppData. This module computes the data root
// the Electron main process should USE (and propagate to the sidecar via
// `MEDIA_STUDIO_CONFIG_DIR`) so the whole tree can live in one chosen folder.
//
// The IO orchestration (reading the marker file, probing exe-dir writability,
// `app.getPath('appData')`) lives in main.ts (`resolveDataRoot`) so this module
// stays electron-free and unit-testable (dataRoot.test.ts). The two MUST agree:
// whatever main passes here is the SAME root the sidecar + first-run bootstrap
// inherit via the env override — otherwise the `short:`/`dub:` resolvers and the
// embeddable `._pth` env dir would point at a different tree than the sidecar.

/** The marker filename (lives next to the packaged executable). */
export const DATA_DIR_MARKER = 'data-dir.txt';

/**
 * Thrown when an attacker-influenceable data-root input (the `data-dir.txt`
 * marker or `MEDIA_STUDIO_CONFIG_DIR`) is NOT an absolute LOCAL path — a UNC
 * share (`\\host\share`), a Windows device namespace (`\\.\`, `\\?\`), a `..`
 * traversal, or a relative path. The sidecar pip-installs models into (and reads
 * executables out of) the data root, so such a value is a code-exec vector and is
 * REFUSED loudly rather than honored (A4/R7 — no silent fallback).
 */
export class DataRootSecurityError extends Error {
  constructor(source: string, value: string) {
    super(
      `refusing unsafe ${source} data root ${JSON.stringify(value)}: must be an absolute ` +
        'LOCAL path (no UNC \\\\host, device \\\\.\\, or ".." traversal)',
    );
    this.name = 'DataRootSecurityError';
  }
}

/**
 * True when `candidate` is an absolute LOCAL filesystem path safe to use as the
 * data root. Rejects (a) UNC / device namespaces — any value beginning with two
 * path separators (`\\server\share`, `\\.\dev`, `\\?\C:\…`, `//host/share`); (b)
 * any `..` path segment (traversal into a sibling/parent tree); (c) a
 * non-absolute path. Accepts a Windows drive root (`C:\…` / `C:/…`) or a POSIX
 * root (`/…`). `candidate` is expected already trimmed (see {@link chooseDataRoot}).
 */
export function isSafeLocalDataRoot(candidate: string): boolean {
  // (a) UNC (\\server\share) and Windows device namespaces (\\.\, \\?\) both begin
  //     with two path separators — never a valid LOCAL data root.
  if (/^[\\/]{2}/.test(candidate)) return false;
  // (b) Any `..` segment is a traversal out of the intended tree.
  if (candidate.split(/[\\/]+/).some((seg) => seg === '..')) return false;
  // (c) Require an ABSOLUTE path: a Windows drive root or a POSIX root.
  return /^[A-Za-z]:[\\/]/.test(candidate) || candidate.startsWith('/');
}

/** Inputs to {@link chooseDataRoot} (all already resolved by the IO wrapper). */
export interface ChooseDataRootInput {
  /** `process.env.MEDIA_STUDIO_CONFIG_DIR` — an explicit power-user override. */
  envOverride?: string;
  /** Trimmed contents of `<exeDir>/data-dir.txt` (the user's chosen folder). */
  markerContent?: string;
  /** `<exeDir>/data` — the portable "keep data beside the app" location. */
  exeDataDir?: string;
  /** True when `exeDataDir` is creatable/writable (false on a read-only install). */
  exeDataWritable?: boolean;
  /**
   * Whether the writable `<exeDir>/data` auto-pick (tier 3) is allowed. This is
   * the PORTABLE-INSTALL default and is only sensible for a PACKAGED build (where
   * `<exeDir>` is the install folder). In dev, `process.execPath` is
   * `node_modules/electron/dist/electron.exe`, so `<exeDir>/data` is a writable
   * but EMPTY folder with no `library.json` — auto-picking it silently broke
   * preview (empty library -> mstream 404 -> blank <video> -> no subtitles). Set
   * to `app.isPackaged`. Defaults to `true` (backward compatible) so the env +
   * marker tiers stay UNCONDITIONAL — only this auto-pick tier is gated.
   */
  preferExeDataDir?: boolean;
  /**
   * True when `exeDataDir` already holds a provisioning marker
   * (`.first-run-complete.json` / `library.json` / `library.db`). Optional; when
   * omitted the root is treated as un-provisioned (the pre-A4 tier order). Feeds
   * the CONTENT-aware anti-brick: an empty portable `<exeDir>/data` never wins
   * over a provisioned lower tier.
   */
  exeDataProvisioned?: boolean;
  /** True when `appDataRoot` already holds a provisioning marker (see above). */
  appDataProvisioned?: boolean;
  /** `%APPDATA%/media-studio` — the historical default + final fallback. */
  appDataRoot: string;
}

/** Trim a candidate and return it only when it has non-whitespace content. */
function nonEmpty(value: string | undefined): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

/**
 * Choose the ONE data root, in priority order:
 *
 *   1. `envOverride` (trimmed)         — explicit `MEDIA_STUDIO_CONFIG_DIR` wins
 *      so a power user / test can force any location.
 *   2. `markerContent` (trimmed)       — the user's chosen folder, persisted in
 *      `<exeDir>/data-dir.txt` by the in-app "Change…" action (survives restart).
 *   3. `exeDataDir` IF `exeDataWritable` AND `preferExeDataDir` — portable
 *      default: keep everything in a `data/` folder beside the executable when
 *      that folder can be written. Gated on `preferExeDataDir` (= app.isPackaged)
 *      so a DEV run never auto-picks the empty `node_modules/electron/dist/data`
 *      (the preview-blocker trap). `preferExeDataDir` defaults to `true`.
 *   4. `appDataRoot`                   — historical default + safe fallback when
 *      the install dir is read-only (e.g. Program Files) or, in dev, when tier 3
 *      is gated off and no env/marker is set.
 *
 * Whitespace-only / empty candidates are ignored at every tier (they never beat
 * a lower-priority real path). The result is returned VERBATIM (no path joining)
 * so callers control how sub-dirs are derived.
 */
export function chooseDataRoot(input: ChooseDataRootInput): string {
  const env = nonEmpty(input.envOverride);
  if (env !== undefined) {
    if (!isSafeLocalDataRoot(env)) throw new DataRootSecurityError('MEDIA_STUDIO_CONFIG_DIR', env);
    return env;
  }

  const marker = nonEmpty(input.markerContent);
  if (marker !== undefined) {
    if (!isSafeLocalDataRoot(marker))
      throw new DataRootSecurityError('data-dir.txt marker', marker);
    return marker;
  }

  // The portable auto-pick is gated: only when explicitly preferred (packaged).
  // `preferExeDataDir` defaults to true so existing callers keep portable behavior.
  const exeEligible = input.exeDataWritable === true && input.preferExeDataDir !== false;
  const exe = exeEligible ? nonEmpty(input.exeDataDir) : undefined;
  if (exe !== undefined) {
    // CONTENT-aware anti-brick (A4): when the portable `<exeDir>/data` is EMPTY
    // (not provisioned) but a lower tier (appData) already holds a provisioned
    // tree, prefer the provisioned root rather than opening an empty library.
    // When BOTH (or neither) are provisioned, the deterministic tier order keeps
    // the higher-priority portable dir. The two roots are NEVER merged/migrated.
    if (input.exeDataProvisioned !== true && input.appDataProvisioned === true) {
      return input.appDataRoot;
    }
    return exe;
  }

  return input.appDataRoot;
}

/**
 * The IO seam {@link resolveDataRootFrom} needs (so the data-root RESOLUTION
 * policy is testable without Electron). main.ts provides the concrete impl
 * (reading the marker, probing exe-dir writability, app.getPath('appData')).
 */
export interface DataRootIO {
  /** `process.env.MEDIA_STUDIO_CONFIG_DIR` (or undefined). */
  envOverride: string | undefined;
  /** `<exeDir>/data` — the portable default location. */
  exeDataDir: string;
  /** `%APPDATA%/media-studio`. */
  appDataRoot: string;
  /** Read the marker file's trimmed contents, or undefined if absent/unreadable. */
  readMarker: () => string | undefined;
  /** True when `exeDataDir` is creatable/writable. */
  isExeDataWritable: (dir: string) => boolean;
  /**
   * Whether the writable `<exeDir>/data` auto-pick is allowed (= app.isPackaged).
   * Optional for backward compatibility; omitting it keeps the portable default
   * (`true`). main.ts passes `app.isPackaged` so dev never auto-picks the empty
   * `node_modules/electron/dist/data` trap. See {@link ChooseDataRootInput}.
   */
  preferExeDataDir?: boolean;
  /**
   * True when `root` already holds a provisioning marker
   * (`.first-run-complete.json` / `library.json` / `library.db`). Optional for
   * backward compatibility; when omitted every root is treated as un-provisioned
   * (the pre-A4 tier order). main.ts passes `isProvisionedRoot` (dataRootIo.ts) so
   * a clean install with an EMPTY portable `<exeDir>/data` but a provisioned
   * `%APPDATA%` auto-selects the provisioned root instead of a blank library.
   */
  isProvisioned?: (root: string) => boolean;
}

/**
 * Resolve the ONE data root from an injected IO seam (G1 preview fix).
 *
 * IMPORTANT BEHAVIOR (regression-locked): the env override + marker are consulted
 * UNCONDITIONALLY — there is NO `isPackaged` switch on them. The previous main.ts
 * gated the marker too, so a DEV run ignored it and always landed on
 * %APPDATA%/media-studio — part of the "preview doesn't work -> no subtitles"
 * failure. Now dev honors a marker/env exactly like a packaged build.
 *
 * The writable `<exeDir>/data` AUTO-PICK (tier 3), however, IS gated — via
 * `io.preferExeDataDir` (= app.isPackaged). In dev `process.execPath` is
 * `node_modules/electron/dist/electron.exe`, so `<exeDir>/data` is a writable but
 * EMPTY folder; auto-picking it silently re-broke preview (empty library -> 404 ->
 * blank <video>). Gating the auto-pick on packaged makes dev fall through to
 * %APPDATA% (the historical default) UNLESS the user set an env/marker. Pure
 * given the seam (the seam owns all IO).
 */
export function resolveDataRootFrom(io: DataRootIO): string {
  // Default to un-provisioned when the seam omits the probe (pre-A4 behavior).
  const isProvisioned = io.isProvisioned ?? (() => false);
  return chooseDataRoot({
    envOverride: io.envOverride,
    markerContent: io.readMarker(),
    exeDataDir: io.exeDataDir,
    exeDataWritable: io.isExeDataWritable(io.exeDataDir),
    exeDataProvisioned: isProvisioned(io.exeDataDir),
    appDataProvisioned: isProvisioned(io.appDataRoot),
    preferExeDataDir: io.preferExeDataDir,
    appDataRoot: io.appDataRoot,
  });
}
