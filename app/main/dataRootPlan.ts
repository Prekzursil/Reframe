// dataRootPlan.ts — pure DATA-LOSS-SAFE data-root decision (WU-R1).
//
// WHY this exists: a PACKAGED build with no `data-dir.txt`/env override used to
// resolve its data root to `<exeDir>/data` (dataRoot.ts's writable-exe-data
// auto-pick, gated on `app.isPackaged`). But `<exeDir>` is the NSIS install dir
// ($INSTDIR), and electron-updater's in-place NSIS upgrade REPLACES $INSTDIR — so
// a default install's `library.db` + multi-GB model envs were WIPED on the very
// auto-update v1.4 relies on. electron-builder.yml already documents the intended
// home as `%APPDATA%/media-studio` (bootstrap.py provisions there); the exe-data
// auto-pick was a regression away from that intent.
//
// THE FIX (packaged only; dev is UNCHANGED — it already lands on %APPDATA%):
//   1. an explicit override (MEDIA_STUDIO_CONFIG_DIR / data-dir.txt) STILL WINS,
//      verbatim — an existing user pointing at D:/Reframe/data keeps that root.
//   2. if a legacy `<exeDir>/data` ALREADY EXISTS (a prior default install) and the
//      safe %APPDATA%/media-studio home is not already occupied, MIGRATE it OUT of
//      $INSTDIR on first launch. The move is atomic + space-checked in the seam
//      ({@link runMigration}); on ANY failure it falls back to the legacy root
//      UNCHANGED with a LOUD warning (never a partial move, never silent loss).
//   3. a FRESH packaged install (no override, no legacy dir) uses %APPDATA%.
//
// This module is the PURE decision (env-free, IO-free, 100% unit-testable). The
// filesystem move + free-space/existence probes are an injected seam that lives in
// dataRootMigrateIo.ts; main.ts wires the two together in resolveDataRoot().
import { chooseDataRoot } from './dataRoot';

/**
 * The resolved plan for the data root:
 *  - `use`     — resolve to `root` directly (override, or the safe appData home).
 *  - `migrate` — a packaged legacy `<exeDir>/data` must be moved to `to`
 *                (%APPDATA%/media-studio) before it can be used safely.
 */
export type DataRootPlan =
  | { readonly kind: 'use'; readonly root: string }
  | { readonly kind: 'migrate'; readonly from: string; readonly to: string };

/** Inputs to {@link planDataRoot} (all pre-resolved by the IO wrapper in main.ts). */
export interface PlanDataRootInput {
  /** `process.env.MEDIA_STUDIO_CONFIG_DIR` — the explicit power-user override. */
  readonly envOverride?: string;
  /** Trimmed contents of `<exeDir>/data-dir.txt` (the user's chosen folder). */
  readonly markerContent?: string;
  /** `app.isPackaged` — the legacy migration is PACKAGED-ONLY (dev never migrates). */
  readonly packaged: boolean;
  /** `<exeDir>/data` — the legacy default location, INSIDE $INSTDIR (unsafe home). */
  readonly legacyExeDataDir: string;
  /** True when `<exeDir>/data` already exists and is non-empty (a prior install). */
  readonly legacyExeDataExists: boolean;
  /** `%APPDATA%/media-studio` — the SAFE default home, OUTSIDE $INSTDIR. */
  readonly appDataRoot: string;
  /**
   * True when `%APPDATA%/media-studio` already exists and is non-empty. Guards the
   * migration from CLOBBERING an occupied safe home: when set, we never move the
   * legacy tree on top of it — we use the safe home directly and leave the legacy
   * dir intact (both preserved; the user can reconcile manually).
   */
  readonly appDataOccupied: boolean;
}

/** Trim a candidate and return it only when it has non-whitespace content. */
function nonEmpty(value: string | undefined): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

/**
 * Decide the data-root plan (pure). Precedence:
 *
 *   1. explicit env / marker override — resolved (and security-validated) by
 *      {@link chooseDataRoot}; wins UNCONDITIONALLY, returned as a `use` plan.
 *   2. packaged legacy rescue — no override, `packaged`, a non-empty legacy
 *      `<exeDir>/data` exists, and the safe appData home is NOT occupied ->
 *      `migrate` plan (the seam moves it before use).
 *   3. otherwise — the safe `%APPDATA%/media-studio` home as a `use` plan (fresh
 *      packaged install, an occupied appData home we must not clobber, or DEV —
 *      all of which already resolve to appData via `chooseDataRoot` here).
 *
 * The exe-data AUTO-PICK is disabled here (`exeDataWritable:false` +
 * `preferExeDataDir:false`) precisely because that pick was the data-loss vector;
 * a legacy exe-data tree is only ever REACHED to be migrated OUT, never chosen as
 * a fresh default. An unsafe override (UNC/device/`..`) still throws via
 * `chooseDataRoot` (DataRootSecurityError) — no silent fallback.
 */
export function planDataRoot(input: PlanDataRootInput): DataRootPlan {
  // Resolve override > appData with the exe-data auto-pick DISABLED. Throws on an
  // unsafe env/marker (security-validated inside chooseDataRoot).
  const base = chooseDataRoot({
    envOverride: input.envOverride,
    markerContent: input.markerContent,
    exeDataDir: input.legacyExeDataDir,
    exeDataWritable: false,
    preferExeDataDir: false,
    appDataRoot: input.appDataRoot,
  });

  const overrideChosen =
    nonEmpty(input.envOverride) !== undefined || nonEmpty(input.markerContent) !== undefined;

  // Only a packaged build with a real legacy tree and a FREE safe home migrates.
  if (!overrideChosen && input.packaged && input.legacyExeDataExists && !input.appDataOccupied) {
    return { kind: 'migrate', from: input.legacyExeDataDir, to: input.appDataRoot };
  }

  return { kind: 'use', root: base };
}

/**
 * The injected filesystem seam a planned migration executes against. Concrete
 * node:fs implementations live in dataRootMigrateIo.ts; tests pass fakes so every
 * branch of {@link runMigration} is exercised without touching a real disk.
 */
export interface MigrationSeam {
  /** Bytes the legacy tree occupies (recursive). */
  readonly sourceSize: () => number;
  /** Bytes available on the volume that will hold the destination. */
  readonly destFree: () => number;
  /**
   * Atomically move the legacy tree to the destination. MUST be all-or-nothing:
   * on any failure it throws and leaves BOTH the source intact and NO partial
   * destination (see dataRootMigrateIo.atomicMoveDir).
   */
  readonly move: () => void;
  /** Loud diagnostic sink for the abort/failure paths (console.error in main). */
  readonly warn: (message: string) => void;
}

/**
 * Execute a planned legacy -> appData migration through the injected {@link
 * MigrationSeam}. Returns true when the data now lives safely at the destination;
 * false — with a LOUD warning — when it could not be moved (insufficient space or
 * any move error), in which case the caller keeps using the legacy root UNCHANGED
 * (data preserved in place, never partially moved, never silently lost).
 */
export function runMigration(from: string, to: string, seam: MigrationSeam): boolean {
  try {
    const needed = seam.sourceSize();
    const free = seam.destFree();
    if (free < needed) {
      seam.warn(
        `[data-root] migration ABORTED: not enough free space to move ${from} -> ${to} ` +
          `(need ${needed} bytes, ${free} available). Keeping data at ${from}; it remains ` +
          'INSIDE the install dir and may be lost on the next auto-update — free up space ' +
          'or set MEDIA_STUDIO_CONFIG_DIR to relocate it.',
      );
      return false;
    }
    seam.move();
    return true;
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    seam.warn(
      `[data-root] migration FAILED (${reason}): could not move ${from} -> ${to}. Keeping data ` +
        `at ${from} UNCHANGED; it remains inside the install dir and may be lost on the next ` +
        'auto-update — set MEDIA_STUDIO_CONFIG_DIR to relocate it.',
    );
    return false;
  }
}

/**
 * The final data root after the seam ran: the destination when the move
 * SUCCEEDED, otherwise the legacy source UNCHANGED (loud-fallback; see {@link
 * runMigration}). Pure — the branch a caller picks based on the boolean outcome.
 */
export function migratedRoot(from: string, to: string, migrated: boolean): string {
  return migrated ? to : from;
}
