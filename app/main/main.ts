// main.ts — Electron main process entry (CONTRACTS.md §1: app entry,
// BrowserWindow, sidecar supervisor). Responsibilities:
//   1. create the application window with the sandboxed preload,
//   2. start + supervise the Python sidecar (see sidecar.ts),
//   3. register the `rpc` ipc handler + relay sidecar notifications (ipc.ts),
//   4. shut the sidecar down cleanly on quit.
//
// CONTRACT-NOTE (CONTRACTS.md §0/§7): local personal app — no auth, no network
// servers, no telemetry. The renderer is loaded from the electron-vite dev
// server in development (ELECTRON_RENDERER_URL) and from the built bundle
// (out/renderer/index.html) in production. Security baseline: contextIsolation
// ON, nodeIntegration OFF, sandbox ON — the renderer only sees `window.api`.
import { app, BrowserWindow, ipcMain, safeStorage, session, shell } from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, writeFileSync, promises as fsp } from 'node:fs';
import { extname, join, resolve as resolvePath, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { migratedRoot, type MigrationSeam, planDataRoot, runMigration } from './dataRootPlan';
import { dataDirMarkerPath, exeDataDir, readDataDirMarker } from './dataRootIo';
import { atomicMoveDir, dirHasContent, dirSizeBytes, freeSpaceBytes } from './dataRootMigrateIo';
import {
  acquireDataRootLock,
  DATA_ROOT_LOCK_FILE,
  type LockDecision,
  type LockIo,
  releaseDataRootLock,
} from './dataRootLock';
import { bootProbe, createLockIo, selfLockOwner } from './dataRootLockIo';
import { registerDataFolderIpc } from './dataFolderIpc';
import { registerRepairSetupIpc } from './repairSetupIpc';
import { registerInstallProfileIpc } from './installProfileIpc';
import {
  INSTALL_PROFILE_FILE,
  parsePersistedInstallProfile,
  resolveInstallChoice,
  type ResolvedInstallChoice,
} from './installProfiles';
import { registerDialogIpc } from './dialogIpc';
import { resolveScopedMediaPath } from './exportPath';
import {
  cspResponseHeaders,
  isAllowedExternalUrl,
  isAllowedNavigation,
  shouldGrantPermission,
} from './security';
import { registerIpc } from './ipc';
import {
  registerMediaProtocol,
  registerMediaSchemePrivileges,
  SidecarUnavailableError,
} from './mediaProtocol';
import { PlaybackProxy, type PlayableVerdict, type ProxyBuildState } from './playbackProxy';
import type { DoneNotification } from './sidecar';
import { registerShellIpc } from './shellIpc';
import { pthZipName, renderPthBody } from './pthActivation';
import {
  classifyFirstRun,
  FIRST_RUN_COMPLETE_MARKER,
  FIRST_RUN_REQUIREMENTS_FINGERPRINT_FILE,
  fingerprintInSync,
  hashedLockFilename,
  requirementsFingerprint,
  shouldBackfillFingerprint,
  shouldClearProvisioningOnSidecarStatus,
  shouldSpawnBootstrap,
  shouldStartSidecarAfterFailedFirstRun,
} from './firstRunGate';
import { broadcastToLiveWindows } from './windowsBroadcast';
import {
  decideDidFailLoad,
  decideRenderProcessGone,
  describeUncaughtException,
  describeUnhandledRejection,
} from './rendererRecovery';
import { keystorePathFor, migrateLegacyPlaintextKeys, type SafeStorageLike } from './keystore';
import { KeyBridge } from './keyBridge';
import { Sidecar } from './sidecar';
import { autoUpdater } from 'electron-updater';
import {
  registerUpdater,
  UPDATE_STATUS_CHANNEL,
  type AutoUpdaterLike,
  type UpdateStatus,
  type UpdaterHandle,
} from './updater';

// mstream:// must be declared privileged BEFORE app ready (U1).
// NOTE: registerSchemesAsPrivileged may only be called ONCE per app — if
// another scheme is ever needed, merge its entry into this one call.
registerMediaSchemePrivileges();

const isDev = !app.isPackaged;

let sidecar: Sidecar | null = null;
let disposeIpc: (() => void) | null = null;
let disposeDialogIpc: (() => void) | null = null;
let disposeShellIpc: (() => void) | null = null;
let disposeDataFolderIpc: (() => void) | null = null;
let disposeRepairSetupIpc: (() => void) | null = null;
let disposeInstallProfileIpc: (() => void) | null = null;
let disposeProvisioningIpc: (() => void) | null = null;
let disposeUpdater: (() => void) | null = null;

/**
 * WU-1b: the CURRENT latched first-run provisioning state, mirrored by every
 * `broadcastProvisioning` call and seeded from `firstRun` in bootstrap() BEFORE
 * the window loads. `provisioning.get` returns this so the renderer's first frame
 * can withhold the shell until provisioning is definitively over.
 */
let provisioningActive = false;

/**
 * WU-1c: true on a FIRST-EVER run while the supervisor is WAITING for the user's
 * install-profile choice before spawning bootstrap. Mirrored into every
 * `broadcastProvisioning` fan-out + returned by `provisioning.get` so the renderer
 * shows the ProfilePicker (not a progress bar) on the first frame. Flips false the
 * moment a profile is chosen and bootstrap actually spawns. A silent WU-S2
 * re-bootstrap never sets it (it reuses the persisted profile).
 */
let awaitingProfileActive = false;

/** All live, non-destroyed windows (for notification fan-out). */
function liveWindows(): BrowserWindow[] {
  return BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed());
}

/**
 * WU-S1: bring the already-running instance's window to the foreground. Called
 * from the `second-instance` handler when a second launch of THIS app copy is
 * rejected by `requestSingleInstanceLock` — restore it if minimized, then focus.
 */
function focusPrimaryWindow(): void {
  const [win] = BrowserWindow.getAllWindows();
  if (!win || win.isDestroyed()) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

// ---- WIRING-T5 §2: packaged-mode first-run setup ---------------------------
//
// Stage 1 (the slim installer/portable zip) ships the Electron app + the
// embeddable CPython + ffmpeg + the sidecar SOURCE only. Stage 2
// (sidecar/runtime_setup/bootstrap.py) builds the heavy runtime env under
// %APPDATA%/media-studio on FIRST run. The sentinel is the env-success file
// bootstrap.py itself writes (envs/sidecar/.media-studio-env.json), so a
// failed/aborted bootstrap is simply retried on the next launch. Everything
// here is guarded by app.isPackaged — dev behavior is byte-identical.

/** ipc channel carrying `{state, line}` bootstrap progress to the renderer. */
const BOOTSTRAP_PROGRESS_CHANNEL = 'bootstrap.progress';
/**
 * WU-1 FAIL-LOUD: ipc channel carrying the ACTIONABLE first-run failure message
 * (bootstrap.py's terminal `FAILED:bootstrap …` line, or a spawn-failure
 * fallback) to the renderer's SidecarBanner. Must match preload.ts
 * BOOTSTRAP_ERROR_CHANNEL + the renderer bridge `onBootstrapError`. A broken
 * first run is then visible + actionable instead of a silent empty app.
 */
const BOOTSTRAP_ERROR_CHANNEL = 'bootstrap.error';

/**
 * WU-1a: ipc channel carrying the EXPLICIT first-run PROVISIONING signal
 * (`{active}`) to the renderer — DISTINCT from a crashed sidecar
 * (`sidecar.status` = 'down') and from the terminal bootstrap error
 * (`bootstrap.error`). `active:true` is emitted when first-run bootstrap starts;
 * `active:false` when the sidecar reaches 'running' or bootstrap fails
 * terminally. This lets the renderer tell "first-run provisioning in progress"
 * apart from "sidecar down/error". Must match preload.ts PROVISIONING_STATE_CHANNEL
 * + the renderer bridge `onProvisioningState`.
 */
const PROVISIONING_STATE_CHANNEL = 'provisioning.state';

/**
 * WU-1b: request/response ipc channel for the CURRENT latched provisioning state
 * (`{active}`). The `provisioning.state` PUSH above can't cover the renderer's
 * FIRST frame — a first run raises it at did-finish-load (after React has already
 * mounted the shell), and a normal launch fires its `running`/`active:false`
 * before the window even exists (both MISSED). The renderer therefore QUERIES
 * this at mount to decide, deterministically, whether to withhold the shell (and
 * its sidecar RPCs) — killing the frame-0 "sidecar is not running" banner. Must
 * match preload.ts PROVISIONING_GET_CHANNEL + the bridge `getProvisioningState`.
 */
const PROVISIONING_GET_CHANNEL = 'provisioning.get';

/**
 * WU B3: ipc channel carrying the playback-proxy build state for a videoId to
 * the renderer's Workspace (`{videoId, state, detail}`). `state` is
 * 'building' | 'ready' | 'error' — the renderer shows a "building…" note, swaps
 * to the now-decodable proxy on 'ready', and surfaces the reason LOUDLY on
 * 'error'. Must match preload.ts PROXY_STATE_CHANNEL + `onProxyState`.
 */
const PROXY_STATE_CHANNEL = 'proxy.state';

/**
 * WU B3: the bounded await for a single-flight proxy build. Generous enough for
 * a real transcode to finish inline (the <video> request just waits), but
 * finite so a wedged build becomes a transient "building" 503 the renderer can
 * retry — never an unbounded hang and never a fall-back to the raw source.
 */
const PROXY_BUILD_TIMEOUT_MS = 15 * 60_000;

let bootstrapChild: ChildProcess | null = null;

/** `process.resourcesPath` (Electron-only) without an Electron-types dependency. */
function getResourcesPath(): string {
  return (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath ?? '';
}

/**
 * Resolve the runtime BrowserWindow icon (WU A2 — Concept A "Crop Pull").
 * Packaged: the 512px PNG shipped to resources/icons/ (extraResources). Dev:
 * the same master out of the repo build/icons tree — __dirname is
 * <repo>/app/out/main at runtime, so three levels up reaches the repo root.
 * The exe/installer/taskbar icon is the .ico (electron-builder win.icon); this
 * PNG is what nativeImage loads for the live window.
 */
function resolveWindowIcon(): string {
  return app.isPackaged
    ? join(getResourcesPath(), 'icons', 'reframe-512.png')
    : resolvePath(__dirname, '..', '..', '..', 'build', 'icons', 'reframe-512.png');
}

// ---- DATA ROOT (the one relocatable folder; default OUT of %APPDATA%) -------
//
// Every heavy artifact (models/envs/exports/proxies/peaks/dubs/voices/feedback/
// chrome) derives from the sidecar's settings_store.default_config_dir(), which
// honors MEDIA_STUDIO_CONFIG_DIR first and otherwise falls back to
// %APPDATA%/media-studio. We resolve the data root HERE (planDataRoot is the
// pure part) and propagate it to the sidecar + first-run bootstrap by setting
// process.env.MEDIA_STUDIO_CONFIG_DIR before either spawns (both inherit
// process.env — buildSidecarEnv spreads it; bootstrap inherits it).
//
// BEHAVIOR (WU-R1 data-loss fix): the safe default home is %APPDATA%/media-studio
// in BOTH dev and packaged builds. A packaged build NO LONGER auto-picks the
// writable <exeDir>/data — that dir is INSIDE $INSTDIR and electron-updater's
// in-place NSIS upgrade REPLACES $INSTDIR, so a default install's library.db +
// multi-GB model envs were wiped on the very auto-update the app relies on. The
// data-dir.txt MARKER and MEDIA_STUDIO_CONFIG_DIR override still WIN, verbatim, in
// both modes (a user pointing at D:/Reframe/data keeps it). A packaged build that
// finds a legacy <exeDir>/data from a prior default install MIGRATES it out to
// %APPDATA%/media-studio on first launch (atomic + space-checked; on any failure
// it stays put UNCHANGED with a loud warning — never a partial move). Dev is
// unchanged (it already resolved to %APPDATA% with no env/marker). See resolveDataRoot.

/**
 * Containers Chromium can decode (subset of mediaProtocol's MIME map limited to
 * the formats <video>/<audio> can actually play). A cached proxy with any other
 * extension is treated as not-playable so the resolver falls back to the source.
 */
const PLAYABLE_EXTENSIONS = new Set([
  '.mp4',
  '.m4v',
  '.webm',
  '.ogv',
  '.mp3',
  '.m4a',
  '.aac',
  '.wav',
  '.flac',
  '.ogg',
  '.opus',
]);

/**
 * True when `path` exists, is a regular file, and has a Chromium-decodable media
 * extension. Guards `verdict.proxyPath` (G1 robustness): a stale/half-written
 * proxy that no longer exists — or a non-decodable container — must NOT be
 * returned (it would 404 or blank the player); the resolver falls back to the
 * original library path instead. Any stat error -> false (treat as absent).
 */
async function isPlayableFile(path: string): Promise<boolean> {
  if (!PLAYABLE_EXTENSIONS.has(extname(path).toLowerCase())) return false;
  try {
    const stat = await fsp.stat(path);
    return stat.isFile();
  } catch {
    return false;
  }
}

/**
 * Resolve the data root to USE this session (IO wrapper over the pure plan).
 *
 * DATA-LOSS FIX (WU-R1): a PACKAGED build no longer auto-picks the writable
 * `<exeDir>/data` — that dir is INSIDE $INSTDIR and electron-updater's in-place
 * NSIS upgrade REPLACES $INSTDIR, wiping a default install's library.db + model
 * envs on the very auto-update the app relies on. The safe home is
 * `%APPDATA%/media-studio` (the location electron-builder.yml + bootstrap.py
 * already document). Precedence (see planDataRoot):
 *   1. an explicit MEDIA_STUDIO_CONFIG_DIR / data-dir.txt override still WINS,
 *      verbatim (a user pointing at D:/Reframe/data keeps it);
 *   2. a packaged build with a legacy `<exeDir>/data` from a prior default install
 *      MIGRATES it OUT to %APPDATA%/media-studio (atomic + space-checked; on ANY
 *      failure it stays put UNCHANGED with a loud warning — never a partial move);
 *   3. everything else (fresh packaged install, an already-occupied appData home,
 *      or DEV) uses %APPDATA%/media-studio directly.
 *
 * The pure DECISION is planDataRoot (env-free, 100% unit-tested); the filesystem
 * probes + atomic move are the dataRootMigrateIo seam; this wrapper joins them
 * with the Electron-specific bits (process.env, app.getPath, app.isPackaged).
 */
function resolveDataRoot(): string {
  const legacyExeDataDir = exeDataDir();
  // The safe home literal MUST stay `join(app.getPath('appData'), 'media-studio')`
  // (brand.test.ts guard): stable across upgrades, independent of productName.
  const appDataRoot = join(app.getPath('appData'), 'media-studio');
  const plan = planDataRoot({
    envOverride: process.env.MEDIA_STUDIO_CONFIG_DIR,
    markerContent: readDataDirMarker(),
    packaged: app.isPackaged,
    legacyExeDataDir,
    legacyExeDataExists: dirHasContent(legacyExeDataDir),
    appDataRoot,
    appDataOccupied: dirHasContent(appDataRoot),
  });
  if (plan.kind === 'use') return plan.root;

  // A packaged legacy tree must be moved out of $INSTDIR before use. The seam
  // measures the tree, probes free space on the destination volume (%APPDATA%'s
  // parent always exists), and moves atomically; runMigration owns the abort /
  // failure -> loud-fallback branches so no data is ever partially moved or lost.
  const seam: MigrationSeam = {
    sourceSize: () => dirSizeBytes(plan.from),
    destFree: () => freeSpaceBytes(app.getPath('appData')),
    move: () => atomicMoveDir(plan.from, plan.to),
    warn: (message) => console.error(message),
  };
  const migrated = runMigration(plan.from, plan.to, seam);
  return migratedRoot(plan.from, plan.to, migrated);
}

/** The data root resolved once at startup; all data paths below derive from it. */
const DATA_ROOT = resolveDataRoot();

/**
 * Propagate the resolved data root to the sidecar + first-run bootstrap.
 *
 * Both inherit `process.env` (buildSidecarEnv spreads it; runFirstRunBootstrap's
 * spawn inherits it), so setting `MEDIA_STUDIO_CONFIG_DIR` here — BEFORE either
 * is spawned in bootstrap() — makes the sidecar's `settings_store` resolve the
 * SAME tree main joins for `short:`/`dub:`/the `._pth` env dir.
 *
 * BEHAVIOR CHANGE (G1 preview fix): this is NO LONGER packaged-only. In dev the
 * Electron main process now resolves a real data root via the marker/exe-dir
 * (see resolveDataRoot), but the Python SIDECAR is a separate process whose
 * settings_store independently defaults to %APPDATA%/media-studio unless told
 * otherwise. Without exporting the env in dev, main would read library.json from
 * D:\Reframe\data while the sidecar read an empty %APPDATA% — the cross-process
 * root would diverge and library.list/getPathForVideoId would still come back
 * empty. Exporting DATA_ROOT in dev too keeps both processes on the SAME tree.
 * Still never clobbers an explicit override (a power-user value wins).
 */
function propagateDataRootEnv(): void {
  if (!process.env.MEDIA_STUDIO_CONFIG_DIR) {
    process.env.MEDIA_STUDIO_CONFIG_DIR = DATA_ROOT;
  }
}

const UNSAFE_DATA_PATH_MESSAGE = 'data-root derived path escaped the data root';

/**
 * Path-injection barrier (CodeQL js/path-injection): the data root is derived
 * from `MEDIA_STUDIO_CONFIG_DIR` / a marker file, so any path joined onto it and
 * handed to `fs.existsSync` is a tainted sink. Canonicalise the joined path with
 * `path.resolve` and prove (via `startsWith(root + sep)`) it stays inside the
 * resolved data root — the resolve+containment barrier shape CodeQL recognises
 * (identical to `resolveScopedMediaPath`'s guard). The relative parts here are
 * fixed constants, so the check never fires; it exists to sanitise the sink.
 */
function dataRootChild(...parts: string[]): string {
  const root = resolvePath(DATA_ROOT);
  const target = resolvePath(DATA_ROOT, ...parts);
  if (target !== root && !target.startsWith(root + sep)) {
    throw new Error(UNSAFE_DATA_PATH_MESSAGE);
  }
  return target;
}

/** WIRING-T5 §2: the sidecar-env sentinel bootstrap.py writes on success. */
function firstRunSentinelPath(): string {
  return dataRootChild('envs', 'sidecar', '.media-studio-env.json');
}

// ---- WU-S1: DATA-ROOT single-holder lock ----------------------------------
//
// `app.requestSingleInstanceLock()` (wired at the bottom of this file) only
// excludes two launches of THIS app copy. The data root is RELOCATABLE, so two
// DIFFERENT installs can point at the SAME folder — a second bootstrap/sidecar
// there would race the first over the pip env + library.db. The lockfile below
// (in the resolved DATA_ROOT, holding the owner pid) is the cross-copy guard: a
// second copy that finds a LIVE holder does NOT spawn — it surfaces the loud
// contention message via the existing bootstrap-error banner and starts aborted.
// A stale lock from a crashed/dead holder is reclaimed. The DECISION logic lives
// in the fully-tested pure dataRootLock.ts; this is only the fs/process seam.

/** Absolute path of the DATA-ROOT lockfile (traversal-guarded, in DATA_ROOT). */
function dataRootLockPath(): string {
  return dataRootChild(DATA_ROOT_LOCK_FILE);
}

/**
 * The filesystem/process seam the pure dataRootLock acquire/release inject
 * (exclusive-create/read/overwrite/remove of the lockfile). The liveness probe,
 * per-boot id and host id also live in dataRootLockIo.ts (bootProbe/selfLockOwner)
 * — all Electron-free + unit-tested there.
 */
const dataRootLockIo: LockIo = createLockIo({
  lockPath: dataRootLockPath,
  dataRoot: () => DATA_ROOT,
});

/**
 * ATOMICALLY (re)acquire the DATA-ROOT lock for THIS process. The single choke
 * point: bootstrap() calls it before starting the sidecar, and runFirstRunBootstrap
 * re-checks it before EVERY bootstrap spawn — so a CONTENDED copy can never spawn
 * bootstrap.py / restart the sidecar against a folder a live copy holds, even via
 * the "Retry setup" banner. Decision logic is the fully-tested pure dataRootLock.ts.
 */
function acquireDataRootLockNow(): LockDecision {
  return acquireDataRootLock(dataRootLockIo, selfLockOwner(), Date.now(), bootProbe);
}

/** The loud, actionable message shown when the data folder is held by a live copy. */
function dataRootBusyMessage(): string {
  return (
    `Another Reframe is already using this data folder (${DATA_ROOT}). ` +
    'Close the other Reframe window, or choose a different data folder, then relaunch.'
  );
}

/**
 * WU-D2b-1: the sidecar's settings.json inside the data root. The Python
 * settings_store derives its config path from `default_config_dir()`, which honors
 * `MEDIA_STUDIO_CONFIG_DIR` (== DATA_ROOT, set by propagateDataRootEnv) — so this
 * is exactly the file the one-time plaintext-key migration must scrub.
 */
function settingsJsonPath(): string {
  return dataRootChild('settings.json');
}

/**
 * WU-D2b-1: the DPAPI key guard wired into the `rpc` ipc channel (providers.upsert
 * interception + per-request decrypted-key injection). Constructed in bootstrap()
 * after the one-time migration and before the sidecar starts.
 */
let keyBridge: KeyBridge | null = null;

/**
 * WU-D2b-1 (defense-in-depth, ruling B): re-encrypt any legacy PLAINTEXT keys
 * sitting in the sidecar's settings.json into the DPAPI keystore, then shred every
 * prior plaintext copy — BEFORE the sidecar starts, so no plaintext key is ever
 * read by (or persisted through) the running sidecar. On the `refused` path
 * (secure storage unavailable) we do NOT destroy the user's only copy and the
 * renderer's SecureKeysBanner surfaces the session-only warning (via
 * getSecureStatus). Builds and returns the {@link KeyBridge} either way. Fail-open:
 * a migration IO error is logged and key handling continues (the keystore/session
 * overlay still guards new keys) rather than blocking app startup.
 */
function initKeyBridge(): KeyBridge {
  const store = safeStorage as unknown as SafeStorageLike;
  const keystorePath = keystorePathFor(app.getPath('userData'));
  // Carried onto the KeyBridge so getSecureStatus surfaces any lingering plaintext
  // copy in the renderer banner — a console.warn alone is invisible in a packaged
  // build. Stays empty on the refuse/skip paths and if the migration throws.
  let unshreddable: string[] = [];
  try {
    const result = migrateLegacyPlaintextKeys(store, settingsJsonPath(), keystorePath);
    unshreddable = result.unshreddable;
    if (result.status === 'refused') {
      // Loud, actionable: keys can't be saved at rest; SecureKeysBanner shows the
      // session-only message. Never a silent plaintext write, never a destroyed key.
      // eslint-disable-next-line no-console
      console.error(
        `[keystore] plaintext migration refused (session-only): ${result.banner ?? ''}`,
      );
    } else if (result.status === 'migrated') {
      // eslint-disable-next-line no-console
      console.error(
        `[keystore] migrated ${result.migratedProviderKeys} provider key(s)` +
          `${result.migratedCloudKey ? ' + cloud key' : ''}; shredded ${result.shredded.length} stale copy(ies)`,
      );
    }
    if (result.unshreddable.length > 0) {
      // Loud, actionable: a legacy plaintext copy EXISTED but could not be scrubbed
      // (locked / read-only / unwritable / a directory) — it is still recoverable on
      // disk, so name each path and tell the user to remove it manually. Never silent.
      // eslint-disable-next-line no-console
      console.warn(
        `[keystore] WARNING: ${result.unshreddable.length} legacy plaintext key copy(ies) ` +
          'could NOT be shredded and remain recoverable on disk — remove them manually: ' +
          result.unshreddable.join(', '),
      );
    }
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(`[keystore] plaintext migration failed (continuing): ${(err as Error).message}`);
  }
  return new KeyBridge({ safeStorage: store, keystorePath, unshreddable });
}

/**
 * WIRING-T5 §2 (provisioning hardening): the FIRST-RUN-COMPLETE marker
 * bootstrap.py writes at the data root ONLY after a full provision (env + every
 * model + the S3FD/LR-ASD weights) succeeds. Gating first-run on THIS — not the
 * env sentinel — is what stops a run that built the env but failed the model
 * downloads from looking "done" and leaving a half-provisioned, silently
 * centre-cropping app on the next launch.
 */
function firstRunCompletePath(): string {
  return dataRootChild(FIRST_RUN_COMPLETE_MARKER);
}

/**
 * WU-S2 (version-aware re-bootstrap): the persisted requirements-fingerprint file
 * at the DATA ROOT, next to the completion marker. The DECISION logic (hash,
 * compare, backfill, classify) is the fully-tested pure firstRunGate.ts; the four
 * helpers below are only the thin read/write/compute IO seams around it.
 */
function firstRunFingerprintPath(): string {
  return dataRootChild(FIRST_RUN_REQUIREMENTS_FINGERPRINT_FILE);
}

/**
 * The fingerprint of the sidecar requirements SHIPPED with THIS build, or `null`
 * when it cannot be read (dev/unpackaged where resources are absent). A `null`
 * result is treated as in-sync, so an unreadable shipped file never forces a
 * re-bootstrap — the drift check fails SAFE, never silently loops.
 *
 * WU-S2-FIX: fingerprint the ACTIVE install source, mirroring bootstrap.py
 * `install_env` -> `resolve_active_lock`. The packaged env is installed from the
 * SIBLING fully-hashed lock (`requirements-sidecar.lock.txt`, `pip
 * --require-hashes`) when it is staged, so we hash THAT when present — else the
 * loose pinned `requirements-sidecar.txt`. Hashing only the loose file missed a
 * lock-only / transitive-dependency bump, starting a stale env against the new
 * pip target. Scope is the sidecar env only (chatterbox re-provisions at its own
 * point-of-use — see firstRunGate.ts).
 */
function shippedRequirementsFingerprint(): string | null {
  try {
    const res = getResourcesPath();
    if (!res) return null;
    const runtimeSetup = join(res, 'sidecar', 'runtime_setup');
    const reqName = 'requirements-sidecar.txt';
    const lockFile = join(runtimeSetup, hashedLockFilename(reqName));
    const activeFile = existsSync(lockFile) ? lockFile : join(runtimeSetup, reqName);
    if (!existsSync(activeFile)) return null;
    return requirementsFingerprint(readFileSync(activeFile, 'utf8'));
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(
      `[bootstrap] could not fingerprint shipped requirements: ${(err as Error).message}`,
    );
    return null;
  }
}

/** The requirements fingerprint persisted by the last successful bootstrap, or `null`. */
function readPersistedRequirementsFingerprint(): string | null {
  try {
    const path = firstRunFingerprintPath();
    if (!existsSync(path)) return null;
    const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'));
    const fp = (parsed as { fingerprint?: unknown }).fingerprint;
    return typeof fp === 'string' && fp !== '' ? fp : null;
  } catch {
    // A corrupt/unreadable fingerprint file is treated as absent (null) -> the
    // supervisor backfills the current fingerprint rather than looping bootstrap.
    return null;
  }
}

/**
 * Record the CURRENT shipped requirements fingerprint at the data root (WU-S2).
 * Called after a successful bootstrap (first-ever OR re-bootstrap) and on a
 * legacy-marker backfill. FAIL-OPEN: a write failure is logged, never fatal — a
 * missing fingerprint just re-arms as a backfill on the next launch.
 */
function persistRequirementsFingerprint(): void {
  const fp = shippedRequirementsFingerprint();
  if (fp === null) return;
  try {
    writeFileSync(
      firstRunFingerprintPath(),
      `${JSON.stringify({ fingerprint: fp }, null, 2)}\n`,
      'utf8',
    );
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(
      `[bootstrap] could not persist requirements fingerprint: ${(err as Error).message}`,
    );
  }
}

/**
 * WU-1c: the persisted install-profile file at the DATA ROOT (sibling of the
 * completion marker). Written when the user picks a profile on a first-ever run so
 * a later SILENT WU-S2 re-bootstrap can REPLAY the same profile instead of
 * re-prompting. The DECISION logic (validate/parse/resolve) is the fully-tested
 * pure installProfiles.ts; this is only the thin read/write IO seam.
 */
function installProfilePath(): string {
  return dataRootChild(INSTALL_PROFILE_FILE);
}

/**
 * Persist the chosen install profile at the data root. FAIL-OPEN: a write failure
 * is logged, never fatal — a missing profile file just makes a later re-bootstrap
 * fall back to the argless default set (which still includes the core floor).
 */
function persistInstallProfile(choice: ResolvedInstallChoice): void {
  try {
    writeFileSync(
      installProfilePath(),
      `${JSON.stringify({ profile: choice.profile, bundles: choice.bundles }, null, 2)}\n`,
      'utf8',
    );
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(`[bootstrap] could not persist install profile: ${(err as Error).message}`);
  }
}

/**
 * WU-1c: the assets a re-bootstrap / repair should install, resolved from the
 * PERSISTED profile. Returns `null` when no valid profile is persisted (a legacy
 * pre-WU-1c install, a corrupt file, or an unreadable data root) so the caller
 * spawns bootstrap ARGLESS — replicating the pre-WU-1c default_first_run_assets()
 * behaviour, which still includes the core floor. Never throws: a bad file
 * degrades to the safe default rather than blocking a re-provision.
 */
function readPersistedInstallAssets(): readonly string[] | null {
  try {
    const path = installProfilePath();
    if (!existsSync(path)) return null;
    const persisted = parsePersistedInstallProfile(JSON.parse(readFileSync(path, 'utf8')));
    if (persisted === null) return null;
    return resolveInstallChoice(persisted.profile, persisted.bundles).assets;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(
      `[bootstrap] could not read persisted install profile: ${(err as Error).message}`,
    );
    return null;
  }
}

/**
 * WIRING-T5 §2 (packaging hardening): re-activate THIS copy's embeddable `._pth`.
 *
 * The embeddable interpreter runs ISOLATED — it ignores PYTHONPATH and does not
 * add the cwd, so the ONLY thing that puts the first-run env
 * (`%APPDATA%/media-studio/envs/sidecar`) + the bundled sidecar source on
 * `sys.path` is `resources/python/python3XX._pth`. bootstrap.py writes that file
 * on first run, but it lives in THIS copy's resources while the env-success
 * sentinel lives in the SHARED appData dir. So a freshly extracted/rebuilt
 * portable (pristine `._pth`) whose appData env already exists from an earlier
 * build is judged "not first run", skips bootstrap, and spawns a sidecar that
 * cannot import anything ("No module named media_studio"). Rewriting the `._pth`
 * for the running copy each packaged launch keeps the per-copy activation in sync
 * with the shared env. Idempotent (only writes on change) and FAIL-OPEN (a write
 * failure is logged; the sidecar banner + Restart still surface any startup
 * problem). No-op in dev (no embeddable `._pth`).
 */
function ensurePthActivated(): void {
  try {
    if (!app.isPackaged) return;
    const res = getResourcesPath();
    if (!res) return;
    const embedDir = join(res, 'python');
    if (!existsSync(embedDir)) return;
    const pthName = readdirSync(embedDir).find(
      (f) => f.startsWith('python3') && f.endsWith('._pth'),
    );
    if (!pthName) return; // not an embeddable build (full CPython / dev venv)
    const pth = join(embedDir, pthName);
    // DATA ROOT: the env dir MUST match the data root the sidecar uses (it is
    // spawned with MEDIA_STUDIO_CONFIG_DIR == DATA_ROOT below), or the freshly
    // re-activated ._pth would point at a DIFFERENT env than the one the sidecar
    // looks for — the exact desync this hardening exists to prevent.
    const envDir = resolvePath(DATA_ROOT, 'envs', 'sidecar');
    const sidecarDir = join(res, 'sidecar');
    const zipName = pthZipName(pthName); // python312._pth -> python312.zip
    const body = renderPthBody(zipName, envDir, sidecarDir);
    if (existsSync(pth) && readFileSync(pth, 'utf8') === body) return; // already activated
    writeFileSync(pth, body, 'utf8');
    // eslint-disable-next-line no-console
    console.error(`[bootstrap] re-activated embeddable ._pth -> ${envDir}`);
  } catch (err) {
    // Fail-open: never crash the app over a ._pth write (read-only install dir,
    // AV lock, etc.). The resulting sidecar startup failure surfaces in the UI.
    // eslint-disable-next-line no-console
    console.error(`[bootstrap] ._pth activation failed: ${(err as Error).message}`);
  }
}

function broadcastBootstrap(state: 'running' | 'done' | 'error', line: string): void {
  broadcastToLiveWindows(liveWindows(), BOOTSTRAP_PROGRESS_CHANNEL, { state, line });
}

/**
 * WU-1 FAIL-LOUD: push the ACTIONABLE first-run failure message to every live
 * renderer so the SidecarBanner can surface it (what failed + where + how to
 * fix). Separate from broadcastBootstrap's progress stream because this is the
 * terminal, user-facing error — not a progress line.
 */
function broadcastBootstrapError(message: string): void {
  broadcastToLiveWindows(liveWindows(), BOOTSTRAP_ERROR_CHANNEL, message);
}

/**
 * WU-1a: push the EXPLICIT first-run PROVISIONING signal to every live renderer.
 * `active:true` means first-run setup is under way (emitted at bootstrap start);
 * `active:false` means it finished (the sidecar reached 'running') or failed
 * terminally. Kept SEPARATE from the bootstrap-error + sidecar-status channels so
 * the renderer can distinguish "provisioning in progress" from "sidecar crashed".
 */
function broadcastProvisioning(active: boolean, awaitingProfile = false): void {
  // WU-1b: latch the state so the `provisioning.get` query stays authoritative
  // for renderers that mount AFTER this push (which they otherwise miss).
  // WU-1c: `awaitingProfile` rides the same signal — every non-profile call
  // defaults it false, so spawning bootstrap (which calls broadcastProvisioning(true))
  // flips the renderer from the ProfilePicker to the progress view automatically.
  provisioningActive = active;
  awaitingProfileActive = awaitingProfile;
  broadcastToLiveWindows(liveWindows(), PROVISIONING_STATE_CHANNEL, { active, awaitingProfile });
}

/**
 * WU B3: push a playback-proxy build-state transition to every live renderer so
 * the Workspace can show the "building…" note, reload on 'ready', and surface a
 * build failure loudly on 'error'.
 */
function broadcastProxyState(videoId: string, state: ProxyBuildState, detail: string): void {
  broadcastToLiveWindows(liveWindows(), PROXY_STATE_CHANNEL, { videoId, state, detail });
}

/**
 * WU-U: push an in-place auto-update lifecycle status to every live renderer so
 * the UpdateBanner can surface 'Update available -> Download', download progress,
 * 'Ready -> Restart to update', or an error.
 */
function broadcastUpdateStatus(status: UpdateStatus): void {
  broadcastToLiveWindows(liveWindows(), UPDATE_STATUS_CHANNEL, status);
}

/**
 * WU-U: wire electron-updater to a GitHub-Releases feed and auto-check on launch.
 *
 * PACKAGED-ONLY: electron-updater reads `app-update.yml` (emitted into the app by
 * electron-builder's github `publish` block), which exists only in a packaged
 * build; a dev run has no feed and `checkForUpdates()` would throw. The real
 * singleton is cast to {@link AutoUpdaterLike} (the same structural-cast seam used
 * for safeStorage) and injected into the testable {@link registerUpdater} state
 * machine. autoDownload stays OFF — the user confirms the download in the
 * UpdateBanner; quitAndInstall() then runs the NSIS in-place upgrade, which
 * PRESERVES userData (the DPAPI keystore secure-keys.json + settings + the data
 * root). The app is UNSIGNED (no CSC in electron-builder.yml), so Windows
 * SmartScreen may warn when the downloaded installer runs — expected; we
 * deliberately do not add signing. The launch check is deferred until the
 * renderer has loaded so it can observe the status stream, and it degrades
 * quietly (never crashes) when offline or when no release exists yet.
 */
function wireAutoUpdater(win: BrowserWindow): UpdaterHandle {
  const handle = registerUpdater({
    autoUpdater: autoUpdater as unknown as AutoUpdaterLike,
    broadcast: broadcastUpdateStatus,
    // eslint-disable-next-line no-console
    log: (message) => console.error(message),
  });
  const kickoff = (): void => {
    void handle.checkForUpdates();
  };
  if (win.webContents.isLoading()) {
    win.webContents.once('did-finish-load', kickoff);
  } else {
    kickoff();
  }
  return handle;
}

/**
 * WU B3: start the sidecar `media.proxy.start` job for `videoId` and resolve
 * with the built proxy's absolute path once its terminal `job.done` arrives.
 * Rejects LOUDLY when the job reports an error payload (a failed transcode) or
 * finishes without a path — so the caller never silently serves the raw source.
 * The bounded await lives in {@link PlaybackProxy}; this just bridges the job's
 * done-event to a promise (and always detaches its listener).
 */
function buildProxyJob(sc: Sidecar, videoId: string): Promise<string> {
  return sc.request<{ jobId: string }>('media.proxy.start', { videoId }).then(
    ({ jobId }) =>
      new Promise<string>((resolveBuild, rejectBuild) => {
        const onDone = (done: DoneNotification): void => {
          if (done.jobId !== jobId) return;
          sc.off('done', onDone);
          const result = (done.result ?? {}) as { path?: string; error?: { message?: string } };
          if (result.error) {
            rejectBuild(new Error(result.error.message ?? `proxy build failed for ${videoId}`));
          } else if (typeof result.path === 'string' && result.path !== '') {
            resolveBuild(result.path);
          } else {
            rejectBuild(new Error(`proxy build for ${videoId} returned no path`));
          }
        };
        sc.on('done', onDone);
      }),
  );
}

/**
 * Spawn `runtime_setup/bootstrap.py` with the bundled embeddable python and
 * relay its progress lines (`[bootstrap] ...` on stderr, the terminal
 * SUCCESS:/FAILED: line on stdout) to the renderer over 'bootstrap.progress'.
 * Both pipes are line-drained (A6.2: never hold an unread PIPE). Resolves
 * `true` on exit code 0 — only then is the sidecar startable.
 *
 * WU-1c: `assets` routes the chosen install profile into bootstrap.py's
 * `--assets`. A non-empty list installs EXACTLY that set (always ⊇ the core floor
 * — the resolver guarantees it); `null`/empty spawns ARGLESS, which bootstrap.py
 * treats as its default_first_run_assets() set (the pre-WU-1c behaviour, still
 * core-floor-complete) — used by repair / a legacy re-bootstrap with no persisted
 * profile.
 */
function runFirstRunBootstrap(assets: readonly string[] | null = null): Promise<boolean> {
  // WU-S1-FIX (HIGH): the DATA-ROOT lock is the SINGLE choke point. RE-CHECK it
  // before EVERY bootstrap spawn — not just at startup — so a CONTENDED copy can
  // never spawn bootstrap.py against a data folder a live copy holds, even when the
  // user hits "Retry setup" on the busy banner (repairSetup -> runFirstRunBootstrap).
  // A non-ours lock REFUSES loudly: re-surface the busy message and resolve false
  // (no spawn) — and, because this resolves false, performRepairSetup never calls
  // onBootstrapSucceeded, so the sidecar is never (re)started against the shared tree.
  const lock = acquireDataRootLockNow();
  if (!shouldSpawnBootstrap(lock.ok)) {
    // eslint-disable-next-line no-console
    console.error(
      `[lock] refusing bootstrap: data folder busy (held by live pid ${lock.heldBy ?? 'unknown'})`,
    );
    broadcastBootstrapError(dataRootBusyMessage());
    // WU-1a: return BEFORE broadcastProvisioning(true) below — a busy copy must
    // never fan a provisioning signal out (it would raise a setup gate it can
    // never finish); only the loud busy banner surfaces.
    return Promise.resolve(false);
  }
  return new Promise((resolveRun) => {
    const res = getResourcesPath();
    const python = process.env.MEDIA_STUDIO_PYTHON?.trim() || join(res, 'python', 'python.exe');
    const script = join(res, 'sidecar', 'runtime_setup', 'bootstrap.py');
    // WU-1c: route the chosen profile's assets into bootstrap.py's `--assets`.
    // Empty/null spawns argless (bootstrap.py's default_first_run_assets()).
    const argv = assets && assets.length > 0 ? [script, '--assets', ...assets] : [script];
    broadcastBootstrap('running', 'first-run setup starting');
    // WU-1a: raise the EXPLICIT provisioning signal now that a real bootstrap is
    // spawning (past the busy-lock guard above). It is cleared when the sidecar
    // reaches 'running' or on the terminal error branches below.
    // WU-1c: awaitingProfile defaults false here, so this spawn transitions the
    // renderer from the ProfilePicker to the live progress view.
    broadcastProvisioning(true);
    const child = spawn(python, argv, {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    bootstrapChild = child;
    // WU-1 FAIL-LOUD: remember bootstrap.py's terminal actionable failure line
    // (`FAILED:bootstrap …`) so we can surface it to the UI on a non-zero exit.
    let lastFailLine = '';
    const relayLines = (stream: NodeJS.ReadableStream | null): void => {
      if (!stream) return;
      let buffer = '';
      stream.setEncoding('utf8');
      stream.on('data', (chunk: string) => {
        buffer += chunk;
        let nl = buffer.indexOf('\n');
        while (nl !== -1) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (line !== '') {
            // eslint-disable-next-line no-console
            console.error(`[bootstrap] ${line}`);
            if (line.startsWith('FAILED:bootstrap')) lastFailLine = line;
            broadcastBootstrap('running', line);
          }
          nl = buffer.indexOf('\n');
        }
      });
    };
    relayLines(child.stdout);
    relayLines(child.stderr);
    child.on('error', (err: Error) => {
      bootstrapChild = null;
      // eslint-disable-next-line no-console
      console.error(`[bootstrap] spawn error: ${err.message}`);
      broadcastBootstrap('error', `bootstrap spawn failed: ${err.message}`);
      broadcastBootstrapError(
        `First-run setup could not start: ${err.message}. ` +
          'Reinstall to a writable location, or set MEDIA_STUDIO_PYTHON, then relaunch.',
      );
      // WU-1a: terminal provisioning failure — clear the provisioning signal so
      // the renderer drops the "setting up" state and surfaces the error banner.
      broadcastProvisioning(false);
      resolveRun(false);
    });
    child.on('exit', (code: number | null) => {
      bootstrapChild = null;
      const ok = code === 0;
      broadcastBootstrap(ok ? 'done' : 'error', `bootstrap exited (code ${code ?? 'null'})`);
      if (!ok) {
        // Prefer bootstrap.py's actionable FAILED line; fall back to a generic
        // but still-actionable message if the process died before printing one.
        broadcastBootstrapError(
          lastFailLine !== ''
            ? lastFailLine
            : `First-run setup failed (exit ${code ?? 'null'}). Check that the data ` +
                'folder is writable and has free disk space, then relaunch.',
        );
        // WU-1a: terminal provisioning failure — clear the provisioning signal.
        // On success (ok) the signal instead clears when the sidecar reaches
        // 'running' (createSidecar's status handler), so it stays raised across
        // the sidecar spawn until the runtime is actually up.
        broadcastProvisioning(false);
      }
      resolveRun(ok);
    });
  });
}

function createSidecar(): Sidecar {
  const sc = new Sidecar({ packaged: app.isPackaged });
  // Surface sidecar stderr to the main-process console for debugging only.
  sc.on('log', (line: string) => {
    // eslint-disable-next-line no-console
    console.error(`[sidecar] ${line}`);
  });
  sc.on('exit', (code: number | null) => {
    // eslint-disable-next-line no-console
    console.error(`[sidecar] exited with code ${code ?? 'null'}`);
  });
  sc.on('restart', (attempt: number) => {
    // eslint-disable-next-line no-console
    console.error(`[sidecar] restarting (attempt ${attempt})`);
  });
  sc.on('status', (state: string) => {
    // eslint-disable-next-line no-console
    console.error(`[sidecar] status: ${state}`);
    // WU-1a-FIX: the FIRST sidecar status transition of ANY kind ends first-run
    // provisioning — the supervisor only starts the sidecar AFTER bootstrap
    // succeeded, so 'running' is the success terminal AND 'restarting'/'down' mean
    // the sidecar crashed AFTER a successful bootstrap. Clearing on all three stops
    // a post-bootstrap crash (which reaches 'down' but never 'running') from
    // masquerading as provisioning behind the FirstRunSetup gate forever; the crash
    // now surfaces via the sidecar-status channel / SidecarBanner instead (the two
    // signals stay deliberately separate — this just stops provisioning latching).
    if (shouldClearProvisioningOnSidecarStatus(state)) broadcastProvisioning(false);
  });
  sc.on('error', (err: Error) => {
    // eslint-disable-next-line no-console
    console.error(`[sidecar] supervisor error: ${err.message}`);
  });
  return sc;
}

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 940,
    minHeight: 600,
    show: false,
    backgroundColor: '#101014',
    title: 'Reframe',
    icon: resolveWindowIcon(),
    webPreferences: {
      preload: join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.once('ready-to-show', () => win.show());

  // F3c defense-in-depth: the renderer must never become a window into the OS or
  // a remote origin. Open external links in the OS browser, but ONLY web (http/s)
  // URLs — a `file:`/`javascript:`/`smb:` url handed to the OS would launch an
  // executable or run script (isAllowedExternalUrl parses + denies on failure).
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) {
      void shell.openExternal(url);
    } else {
      // eslint-disable-next-line no-console
      console.error(`[security] blocked openExternal for non-web url: ${url}`);
    }
    return { action: 'deny' };
  });

  const devUrl = process.env.ELECTRON_RENDERER_URL;
  const appUrl =
    isDev && devUrl ? devUrl : pathToFileURL(join(__dirname, '../renderer/index.html')).href;

  // F3c: `will-navigate` allowlist — block any navigation that leaves the app's
  // own origin (a poisoned renderer or injected <a target=_top> can't redirect
  // the window to a hostile site). Same-origin route/hash changes still pass.
  win.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url, appUrl)) {
      event.preventDefault();
      // eslint-disable-next-line no-console
      console.error(`[security] blocked cross-origin navigation to: ${url}`);
    }
  });

  // WU2 resilience (defense-in-depth): recover a renderer that the in-app
  // <ErrorBoundary> cannot — a crashed/OOM'd render PROCESS, or a failed load of
  // index.html — by reloading the window (bounded, so a persistently-broken bundle
  // never becomes a reload storm). The pure decision/log lives in
  // rendererRecovery.ts; this is only the Electron event seam.
  let rendererReloadCount = 0;
  win.webContents.on('did-finish-load', () => {
    // A successful load clears the recovery budget so later, unrelated transient
    // failures each get their own fresh set of retries.
    rendererReloadCount = 0;
  });
  win.webContents.on('render-process-gone', (_event, details) => {
    const decision = decideRenderProcessGone(
      { reason: details.reason, exitCode: details.exitCode },
      rendererReloadCount,
    );
    // eslint-disable-next-line no-console
    console.error(decision.log);
    if (decision.reload && !win.isDestroyed()) {
      rendererReloadCount += 1;
      win.webContents.reload();
    }
  });
  win.webContents.on(
    'did-fail-load',
    (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      const decision = decideDidFailLoad(
        { errorCode, errorDescription, validatedURL, isMainFrame },
        rendererReloadCount,
      );
      // eslint-disable-next-line no-console
      console.error(decision.log);
      if (decision.reload && !win.isDestroyed()) {
        rendererReloadCount += 1;
        win.webContents.reload();
      }
    },
  );

  if (isDev && devUrl) {
    void win.loadURL(devUrl);
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'));
  }

  return win;
}

/**
 * F3c session-level defense-in-depth (applies to every renderer in the default
 * session): deny ALL permission requests (a local media app needs none), and
 * serve the CSP as a real response header via onHeadersReceived so a poisoned
 * index.html cannot strip it. Wired once at startup, before any window loads.
 */
function installSessionSecurity(): void {
  const ses = session.defaultSession;
  // Deny-by-default: both the async request path and the sync check path.
  ses.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(shouldGrantPermission(permission));
  });
  ses.setPermissionCheckHandler((_wc, permission) => shouldGrantPermission(permission));
  // Authoritative CSP on every response (overrides any header-injected CSP).
  ses.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: cspResponseHeaders(details.responseHeaders ?? undefined) });
  });
}

function bootstrap(): void {
  // Set MEDIA_STUDIO_CONFIG_DIR BEFORE the sidecar is created or first-run
  // bootstrap is spawned, so both inherit the SAME data root main derives its
  // short:/dub:/._pth paths from (the cross-process invariant below).
  propagateDataRootEnv();

  // F3c: install permission/CSP guards on the default session before any load.
  installSessionSecurity();

  // WU-D2b-1: run the one-time plaintext-key migration + build the DPAPI key guard
  // BEFORE the sidecar starts, so no plaintext key is ever read by the sidecar and
  // every providers.upsert is intercepted from the very first request.
  keyBridge = initKeyBridge();

  sidecar = createSidecar();

  // WU-S1: acquire the DATA-ROOT lock BEFORE spawning bootstrap/the sidecar, so a
  // SECOND app copy pointed at the SAME data folder never races the first over the
  // pip env build / library.db. A LIVE holder (`ok:false`) aborts spawning: the
  // window + IPC still come up so the loud contention banner is visible, but no
  // sidecar/bootstrap starts against the shared tree. A crashed holder's stale
  // lock is reclaimed. Decision logic is the fully-tested pure dataRootLock.ts.
  const lock = acquireDataRootLockNow();
  if (lock.stale) {
    // eslint-disable-next-line no-console
    console.error(`[lock] reclaimed a stale data-root lock (dead pid ${lock.heldBy ?? 'unknown'})`);
  } else if (!lock.ok) {
    // eslint-disable-next-line no-console
    console.error(
      `[lock] data folder busy (held by live pid ${lock.heldBy ?? 'unknown'}); aborting spawn`,
    );
  }

  // T5: in a packaged build whose runtime env was never built, stage 2 must
  // run BEFORE the sidecar starts (the embeddable python cannot serve
  // `-m media_studio` until bootstrap.py rewrites its ._pth). Dev builds (and
  // already-bootstrapped packaged builds) start immediately, exactly as before.
  // WU-S1: only when we HOLD the data-root lock — a busy folder starts aborted.
  // WU-S2 (version-aware re-bootstrap): a completed install re-provisions when the
  // shipped sidecar requirements fingerprint DRIFTED from the one persisted at the
  // last successful bootstrap (an auto-update changed the env). A `null` shipped
  // fingerprint (unreadable resources) or `null` persisted (legacy pre-feature
  // marker) is treated as in-sync — the latter is BACKFILLED below so future bumps
  // are caught without a surprise re-provision now.
  const markerExists = existsSync(firstRunCompletePath());
  const shippedFp = shippedRequirementsFingerprint();
  const persistedFp = markerExists ? readPersistedRequirementsFingerprint() : null;
  const inSync = shippedFp === null ? true : fingerprintInSync(persistedFp, shippedFp);
  const firstRunKind = classifyFirstRun(app.isPackaged, markerExists, inSync);
  if (firstRunKind === 're-bootstrap') {
    // eslint-disable-next-line no-console
    console.error('[bootstrap] shipped sidecar requirements changed — re-provisioning (silent)');
  }
  const firstRun = lock.ok && firstRunKind !== 'none';
  // WU-1c: a FIRST-EVER run is INTERACTIVE — the supervisor waits for the user's
  // install-profile choice before spawning bootstrap (awaitingProfile). A silent
  // WU-S2 re-bootstrap reuses the persisted profile and auto-spawns (no picker).
  const awaitingProfile = firstRun && firstRunKind === 'first-ever';
  // WU-1b: seed the provisioning latch BEFORE the window loads so the renderer's
  // mount-time `provisioning.get` query is correct on the very first frame — a
  // first/re- run withholds the shell (no sidecar to serve its RPCs yet), an
  // already-provisioned launch mounts it immediately. WU-1c: awaitingProfile rides
  // the same query so a first-ever run shows the ProfilePicker on the first frame.
  provisioningActive = firstRun;
  awaitingProfileActive = awaitingProfile;
  disposeProvisioningIpc = ((): (() => void) => {
    ipcMain.handle(PROVISIONING_GET_CHANNEL, () => ({
      active: provisioningActive,
      awaitingProfile: awaitingProfileActive,
    }));
    return () => ipcMain.removeHandler(PROVISIONING_GET_CHANNEL);
  })();
  if (lock.ok && !firstRun) {
    // T5 hardening: a packaged build whose env already exists still needs THIS
    // copy's embeddable ._pth pointed at it (the sentinel is shared in appData,
    // the ._pth is per-copy — see ensurePthActivated). The first-run path lets
    // bootstrap.py write the ._pth instead.
    ensurePthActivated();
    // WU-S2: a legacy install (marker present, no persisted fingerprint) is
    // assumed to match the currently-shipped requirements — record it so a FUTURE
    // bump is detected, without re-provisioning now.
    if (
      app.isPackaged &&
      shippedFp !== null &&
      shouldBackfillFingerprint(markerExists, persistedFp)
    ) {
      persistRequirementsFingerprint();
    }
    sidecar.start();
  }

  disposeIpc = registerIpc(sidecar, liveWindows, keyBridge);
  disposeDialogIpc = registerDialogIpc();
  // P4 (§6, C9): open-in-folder (shell.showItemInFolder) + brand-logo picker.
  disposeShellIpc = registerShellIpc();
  // DATA ROOT: get/pick/set the user-facing data folder. The marker write target
  // is THIS copy's <exeDir>/data-dir.txt (read back by resolveDataRoot on the
  // next launch); getDataRoot returns the root in use THIS session.
  disposeDataFolderIpc = registerDataFolderIpc({
    getDataRoot: () => DATA_ROOT,
    markerPath: dataDirMarkerPath(),
  });

  // WU A5: on-demand "Retry setup / Repair". Re-runs the idempotent first-run
  // bootstrap (pip re-checks satisfied deps, only missing assets re-download) so
  // a user whose first run partially failed recovers in place — without waiting
  // for the next launch. Single-flight on the live bootstrap child; on success
  // it re-activates THIS copy's embeddable ._pth and (re)starts the sidecar so
  // the freshly-provisioned runtime is picked up.
  // WU-1c: the shared post-bootstrap settle — the first-ever profile-choice spawn
  // AND the silent re-bootstrap both funnel through it. On success persist the
  // fingerprint + start the sidecar; on a re-provision failure of an already-working
  // install, start the existing env DEGRADED (never brick it); a truly-empty failed
  // first run stays down + loud (the bootstrap-error banner said what to fix).
  const sc2 = sidecar;
  const onFirstRunBootstrapSettled = (ok: boolean): void => {
    if (ok) {
      // WU-S2: the env now matches THIS build's shipped requirements.
      persistRequirementsFingerprint();
      sc2.start();
    } else if (shouldStartSidecarAfterFailedFirstRun(existsSync(firstRunSentinelPath()))) {
      ensurePthActivated();
      // eslint-disable-next-line no-console
      console.error('[bootstrap] first-run setup failed; starting existing env (degraded)');
      sc2.start();
    } else {
      // eslint-disable-next-line no-console
      console.error('[bootstrap] first-run setup failed; sidecar not started');
    }
  };
  const kickoffBootstrap = (assets: readonly string[] | null): void => {
    void runFirstRunBootstrap(assets).then(onFirstRunBootstrapSettled);
  };

  // WU A5: on-demand "Retry setup / Repair". Re-runs the idempotent first-run
  // bootstrap (pip re-checks satisfied deps, only missing assets re-download) so
  // a user whose first run partially failed recovers in place — without waiting
  // for the next launch. Single-flight on the live bootstrap child; on success
  // it re-activates THIS copy's embeddable ._pth and (re)starts the sidecar so
  // the freshly-provisioned runtime is picked up. WU-1c: repair REUSES the
  // persisted install profile (argless default when none was persisted).
  disposeRepairSetupIpc = registerRepairSetupIpc({
    isBootstrapInFlight: () => bootstrapChild !== null,
    runBootstrap: () => runFirstRunBootstrap(readPersistedInstallAssets()),
    onBootstrapSucceeded: () => {
      // WU-S2: a repair re-runs the full bootstrap against the CURRENTLY-shipped
      // requirements, so record their fingerprint — the env now matches this build.
      persistRequirementsFingerprint();
      ensurePthActivated();
      sidecar?.restart();
    },
  });

  // WU-1c: the FIRST-EVER-run install-profile choice. On a first-ever run the
  // renderer shows the ProfilePicker (gated on awaitingProfile) and invokes this
  // when the user picks; the handler validates + PERSISTS the profile, then flips
  // the gate to provisioning and spawns bootstrap.py with the resolved `--assets`.
  disposeInstallProfileIpc = registerInstallProfileIpc({
    isBootstrapInFlight: () => bootstrapChild !== null,
    resolveChoice: resolveInstallChoice,
    persist: persistInstallProfile,
    beginBootstrap: (assets) => {
      // Flip the gate picker->progress deterministically (even if the busy-lock
      // guard inside runFirstRunBootstrap early-returns), then spawn + settle.
      broadcastProvisioning(true, false);
      kickoffBootstrap(assets);
    },
  });

  // U1: stream local media to <video> with Range support. The resolver returns
  // the PLAYABLE path for a videoId: the cached remux/proxy when media.playable
  // reports one, otherwise the original library path.
  const sc = sidecar; // capture for the closure (sidecar is module-level let)
  // WU B3: single-flight, bounded playback-proxy orchestration. A non-playable
  // source is transcoded ONCE (concurrent <video> range requests share the same
  // in-flight build), awaited within PROXY_BUILD_TIMEOUT_MS, and its state is
  // pushed to the renderer — a build FAILURE is surfaced loudly (502) instead of
  // streaming the raw, undecodable original ("media error code 4").
  const playbackProxy = new PlaybackProxy({
    probePlayable: async (videoId) => {
      try {
        return await sc.request<PlayableVerdict>('media.playable', { videoId });
      } catch (err) {
        throw new SidecarUnavailableError(
          `media.playable failed for ${videoId}: ${(err as Error).message}`,
        );
      }
    },
    resolveOriginal: async (videoId) => {
      try {
        const { videos } = await sc.request<{ videos: { id: string; path: string }[] }>(
          'library.list',
        );
        return videos.find((v) => v.id === videoId)?.path ?? null;
      } catch (err) {
        throw new SidecarUnavailableError(
          `library.list failed for ${videoId}: ${(err as Error).message}`,
        );
      }
    },
    buildProxy: (videoId) => buildProxyJob(sc, videoId),
    isPlayableFile,
    notify: broadcastProxyState,
    timeoutMs: PROXY_BUILD_TIMEOUT_MS,
  });
  registerMediaProtocol(async (videoId) => {
    // T2 (WIRING-T2 §6): serve finished dub WAVs from the sidecar's dub output
    // dir ONLY (no arbitrary-disk streaming through the media scheme).
    if (videoId.startsWith('dub:')) {
      const dubsRoot = resolvePath(DATA_ROOT, 'dubs');
      return resolveScopedMediaPath(videoId, 'dub:', dubsRoot);
    }
    // P4 (§6, C10): play an EXPORTED short clip — not a library video. The id is
    // `short:<absolute path>`; resolve it ONLY inside the exports root (same
    // path-traversal guard as `dub:`). Also serves a clip's poster frame
    // (`<clip>.thumb.jpg`, written by shorts.thumbnail) — both live under the
    // exports root. Pure mediaProtocol.ts planners unchanged.
    //
    // CROSS-PROCESS INVARIANT (verify before changing): this exports root MUST
    // equal the sidecar's. The sidecar derives it from
    // `settings_store.default_config_dir()` + `/exports`
    // (handlers.Services.exports_dir). default_config_dir() honors
    // MEDIA_STUDIO_CONFIG_DIR first; bootstrap() sets that env var to DATA_ROOT
    // before spawning the sidecar (in dev AND packaged — see propagateDataRootEnv),
    // and DATA_ROOT is exactly what we join here — so the two roots stay equal
    // whether the data folder is the %APPDATA% default or a user-chosen location.
    // If anyone changes how the sidecar resolves its root WITHOUT updating
    // DATA_ROOT (or stops propagating the env), the roots diverge and every
    // `short:` URL 404s silently.
    if (videoId.startsWith('short:')) {
      const exportsRoot = resolvePath(DATA_ROOT, 'exports');
      return resolveScopedMediaPath(videoId, 'short:', exportsRoot);
    }
    // WU-3 (ux-qol §WU-3): serve a SOURCE library video's poster frame
    // (`<videoId>.jpg`, written by the sidecar's library.thumbnail RPC into
    // DATA_ROOT/thumbnails) over the same traversal-guarded mstream resolver so
    // `<img src>` can load it in the sandbox (raw fs paths cannot). The id is
    // `thumb:<absolute path>`; resolve it ONLY inside the thumbnails root (same
    // path-traversal guard as `dub:`/`short:`). The thumbnails root is derived
    // from DATA_ROOT — the SAME source as `short:`/`dub:` above — so it stays in
    // lockstep with the sidecar's data dir (see the short: cross-process
    // invariant note above: bootstrap() propagates DATA_ROOT to the sidecar as
    // MEDIA_STUDIO_CONFIG_DIR, and the sidecar joins `/thumbnails` onto the same
    // root in library.thumbnail).
    if (videoId.startsWith('thumb:')) {
      const thumbnailsRoot = resolvePath(DATA_ROOT, 'thumbnails');
      return resolveScopedMediaPath(videoId, 'thumb:', thumbnailsRoot);
    }
    if (!sc) return null;
    // WU B3: playability resolution + single-flight, bounded proxy build. The
    // cached proxy is served when present + decodable; a directly-playable source
    // streams its original; a NON-playable source is transcoded (once) and awaited
    // — never streaming the raw, undecodable original. Throws propagate as:
    // SidecarUnavailableError -> 503, ProxyBuildingError -> 503 (still building),
    // ProxyBuildFailedError -> 502 (loud). A missing id resolves to null -> 404.
    return playbackProxy.resolve(videoId);
  });

  const win = createWindow();

  // WU-S1: the data folder is held by another LIVE Reframe — surface the loud,
  // actionable contention message on the SidecarBanner (reusing the bootstrap-
  // error channel) once the renderer is up. No sidecar/bootstrap was started
  // above, so the app opens read-only/aborted instead of racing the other copy.
  if (!lock.ok) {
    const surfaceBusy = (): void => broadcastBootstrapError(dataRootBusyMessage());
    if (win.webContents.isLoading()) {
      win.webContents.once('did-finish-load', surfaceBusy);
    } else {
      surfaceBusy();
    }
  }

  // WU-1c: branch the first-run kick-off on interactivity.
  //   * FIRST-EVER (awaitingProfile) — do NOT auto-spawn. The renderer's
  //     ProfilePicker drives it: installProfile.choose -> beginBootstrap above.
  //   * RE-BOOTSTRAP (silent WU-S2 drift) — auto-spawn, REUSING the persisted
  //     profile (argless default when a legacy install has none). Never re-prompts.
  if (firstRun && !awaitingProfile) {
    const begin = (): void => kickoffBootstrap(readPersistedInstallAssets());
    // Spawn once the renderer is up so it can observe bootstrap.progress.
    if (win.webContents.isLoading()) {
      win.webContents.once('did-finish-load', begin);
    } else {
      begin();
    }
  }

  // WU-U: IN-PLACE AUTO-UPDATE — packaged-only (electron-updater needs the
  // app-update.yml a packaged build carries; a dev run has no feed). Checks
  // GitHub Releases on launch and drives the renderer's UpdateBanner. See
  // wireAutoUpdater for the autoDownload/quitAndInstall + unsigned/userData notes.
  if (app.isPackaged) {
    disposeUpdater = wireAutoUpdater(win).dispose;
  }
}

// WU2 resilience (defense-in-depth): keep the MAIN process alive on an otherwise-
// fatal uncaughtException / unhandledRejection. A single stray throw or unobserved
// promise rejection (e.g. in an async IPC callback) must not tear down the whole
// app + sidecar — log it loudly for diagnosis and keep running so the user's work
// survives. The pure log-string decisions live in rendererRecovery.ts.
process.on('uncaughtException', (err) => {
  // eslint-disable-next-line no-console
  console.error(describeUncaughtException(err));
});
process.on('unhandledRejection', (reason) => {
  // eslint-disable-next-line no-console
  console.error(describeUnhandledRejection(reason));
});

// WU-S1: SINGLE-INSTANCE GUARD (same app copy). Acquire Electron's per-copy
// instance lock BEFORE creating any window or spawning the sidecar. A second
// launch of THIS copy loses the lock: it focuses the running window (via the
// primary's `second-instance` handler) and quits immediately, so only one
// process ever drives the app + sidecar. This is COMPLEMENTARY to the DATA-ROOT
// lock in bootstrap(): this guards one copy launched twice; the data-root lock
// guards two DIFFERENT copies aimed at the same relocatable data folder.
if (!app.requestSingleInstanceLock()) {
  // Losing the instance lock means a primary is already running — hand off and go.
  app.quit();
} else {
  app.on('second-instance', focusPrimaryWindow);

  app.whenReady().then(() => {
    // The native "About Reframe" panel (Help ▸ About / macOS app menu) — the single
    // user-facing About surface. applicationName is the display brand "Reframe";
    // applicationVersion reads package.json.version (1.4.0) via Electron.
    app.setAboutPanelOptions({ applicationName: 'Reframe', applicationVersion: app.getVersion() });
    bootstrap();

    app.on('activate', () => {
      // macOS: re-create a window when the dock icon is clicked and none are open.
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });
}

app.on('window-all-closed', () => {
  // Quit on all platforms except macOS (standard Electron convention).
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Ensure the sidecar is torn down before the process exits.
app.on('will-quit', (event) => {
  // WU-S1: release the DATA-ROOT lock — but only when it is still OURS (a busy/
  // aborted launch that never acquired it leaves the live holder's lock intact).
  releaseDataRootLock(dataRootLockIo, selfLockOwner());
  // Don't orphan a half-finished first-run setup (it retries next launch —
  // the sentinel is only written on success).
  if (bootstrapChild && bootstrapChild.exitCode === null) {
    try {
      bootstrapChild.kill();
    } catch {
      /* already gone */
    }
    bootstrapChild = null;
  }
  if (!sidecar) return;
  const sc = sidecar;
  sidecar = null;
  if (disposeIpc) {
    disposeIpc();
    disposeIpc = null;
  }
  if (disposeDialogIpc) {
    disposeDialogIpc();
    disposeDialogIpc = null;
  }
  if (disposeShellIpc) {
    disposeShellIpc();
    disposeShellIpc = null;
  }
  if (disposeDataFolderIpc) {
    disposeDataFolderIpc();
    disposeDataFolderIpc = null;
  }
  if (disposeRepairSetupIpc) {
    disposeRepairSetupIpc();
    disposeRepairSetupIpc = null;
  }
  if (disposeInstallProfileIpc) {
    disposeInstallProfileIpc();
    disposeInstallProfileIpc = null;
  }
  if (disposeProvisioningIpc) {
    disposeProvisioningIpc();
    disposeProvisioningIpc = null;
  }
  if (disposeUpdater) {
    disposeUpdater();
    disposeUpdater = null;
  }
  event.preventDefault();
  void sc.stop().finally(() => app.exit(0));
});
