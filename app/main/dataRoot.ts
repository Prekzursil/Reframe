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
 *   3. `exeDataDir` IF `exeDataWritable` — portable default: keep everything in a
 *      `data/` folder beside the executable when that folder can be written.
 *   4. `appDataRoot`                   — historical default + safe fallback when
 *      the install dir is read-only (e.g. Program Files).
 *
 * Whitespace-only / empty candidates are ignored at every tier (they never beat
 * a lower-priority real path). The result is returned VERBATIM (no path joining)
 * so callers control how sub-dirs are derived.
 */
export function chooseDataRoot(input: ChooseDataRootInput): string {
  const env = nonEmpty(input.envOverride);
  if (env !== undefined) return env;

  const marker = nonEmpty(input.markerContent);
  if (marker !== undefined) return marker;

  if (input.exeDataWritable === true) {
    const exe = nonEmpty(input.exeDataDir);
    if (exe !== undefined) return exe;
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
}

/**
 * Resolve the ONE data root from an injected IO seam (G1 preview fix).
 *
 * IMPORTANT BEHAVIOR (regression-locked): the marker + exe-dir are consulted
 * UNCONDITIONALLY — there is NO `isPackaged` switch. The previous main.ts gated
 * them on `app.isPackaged`, so a DEV run ignored the marker and always landed on
 * %APPDATA%/media-studio (which has no library.json) — the root cause of the
 * "preview doesn't work at all -> no subtitles" failure. Now dev resolves the
 * real data folder exactly like a packaged build. An explicit env override still
 * wins (chooseDataRoot priority). Pure given the seam (the seam owns all IO).
 */
export function resolveDataRootFrom(io: DataRootIO): string {
  return chooseDataRoot({
    envOverride: io.envOverride,
    markerContent: io.readMarker(),
    exeDataDir: io.exeDataDir,
    exeDataWritable: io.isExeDataWritable(io.exeDataDir),
    appDataRoot: io.appDataRoot,
  });
}
