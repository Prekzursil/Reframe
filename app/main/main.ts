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
import { app, BrowserWindow, safeStorage, session, shell } from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, writeFileSync, promises as fsp } from 'node:fs';
import { extname, join, resolve as resolvePath, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { resolveDataRootFrom } from './dataRoot';
import {
  dataDirMarkerPath,
  exeDataDir,
  isExeDataWritable,
  isProvisionedRoot,
  readDataDirMarker,
} from './dataRootIo';
import { registerDataFolderIpc } from './dataFolderIpc';
import { registerRepairSetupIpc } from './repairSetupIpc';
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
  FIRST_RUN_COMPLETE_MARKER,
  needsFirstRunSetup,
  shouldStartSidecarAfterFailedFirstRun,
} from './firstRunGate';
import {
  keystorePathFor,
  migrateLegacyPlaintextKeys,
  type SafeStorageLike,
} from './keystore';
import { KeyBridge } from './keyBridge';
import { Sidecar } from './sidecar';

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

/** All live, non-destroyed windows (for notification fan-out). */
function liveWindows(): BrowserWindow[] {
  return BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed());
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
// %APPDATA%/media-studio. We resolve the data root HERE (chooseDataRoot is the
// pure part) and propagate it to the sidecar + first-run bootstrap by setting
// process.env.MEDIA_STUDIO_CONFIG_DIR before either spawns (both inherit
// process.env — buildSidecarEnv spreads it; bootstrap inherits it).
//
// BEHAVIOR (G1 preview fix + dev-trap hardening): dev consults the data-dir.txt
// MARKER and MEDIA_STUDIO_CONFIG_DIR the SAME way as a packaged build (the old
// code gated the marker on app.isPackaged, so a dev run ignored it and landed on
// %APPDATA% — empty, no library.json -> empty library -> getPathForVideoId null ->
// mstream 404 -> <video> never loads -> no subtitles, since subtitles are
// downstream of timeupdate). HOWEVER, the writable <exeDir>/data PORTABLE auto-pick
// is gated on app.isPackaged (see resolveDataRoot's preferExeDataDir): in dev,
// process.execPath is node_modules/electron/dist/electron.exe, so <exeDir>/data is
// a writable but EMPTY folder — auto-picking it would re-break preview exactly the
// same way. So a dev run with NO env/marker now falls to %APPDATA% (the historical
// default) instead of the node_modules trap; to point dev at a real data folder,
// set MEDIA_STUDIO_CONFIG_DIR or write a data-dir.txt marker. An explicit env
// override still wins in both modes (chooseDataRoot priority order).

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
 * Resolve the data root to USE this session (IO wrapper over chooseDataRoot).
 *
 * The env override + marker are consulted in BOTH dev and packaged builds (G1
 * preview fix): the env override wins, then the marker. The writable <exeDir>/data
 * auto-pick is PACKAGED-ONLY (preferExeDataDir below). The pure priority logic
 * lives in chooseDataRoot; the FILESYSTEM seam (exeDir/marker/writability probe)
 * lives in dataRootIo.ts (directly unit-tested); this wrapper only joins them with
 * the Electron-specific bits (process.env, app.getPath, app.isPackaged).
 */
function resolveDataRoot(): string {
  return resolveDataRootFrom({
    envOverride: process.env.MEDIA_STUDIO_CONFIG_DIR,
    exeDataDir: exeDataDir(),
    appDataRoot: join(app.getPath('appData'), 'media-studio'),
    readMarker: readDataDirMarker,
    isExeDataWritable,
    // A4 content-aware anti-brick: probe each candidate root for a provisioning
    // marker so an EMPTY portable <exeDir>/data never wins over a provisioned
    // %APPDATA% (clean install opens the real library, no manual data-dir.txt).
    isProvisioned: isProvisionedRoot,
    // PORTABLE auto-pick gate (preview-blocker fix): only a PACKAGED build may
    // silently use a writable <exeDir>/data. In dev, <exeDir> is
    // node_modules/electron/dist, so that dir is empty (no library.json) — auto-
    // picking it re-broke preview. Dev falls back to %APPDATA% unless the user
    // sets MEDIA_STUDIO_CONFIG_DIR or a data-dir.txt marker (both still honored).
    preferExeDataDir: app.isPackaged,
  });
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
  try {
    const result = migrateLegacyPlaintextKeys(store, settingsJsonPath(), keystorePath);
    if (result.status === 'refused') {
      // Loud, actionable: keys can't be saved at rest; SecureKeysBanner shows the
      // session-only message. Never a silent plaintext write, never a destroyed key.
      // eslint-disable-next-line no-console
      console.error(`[keystore] plaintext migration refused (session-only): ${result.banner ?? ''}`);
    } else if (result.status === 'migrated') {
      // eslint-disable-next-line no-console
      console.error(
        `[keystore] migrated ${result.migratedProviderKeys} provider key(s)` +
          `${result.migratedCloudKey ? ' + cloud key' : ''}; shredded ${result.shredded.length} stale copy(ies)`,
      );
    }
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(`[keystore] plaintext migration failed (continuing): ${(err as Error).message}`);
  }
  return new KeyBridge({ safeStorage: store, keystorePath });
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
  for (const win of liveWindows()) {
    if (!win.webContents.isDestroyed()) {
      win.webContents.send(BOOTSTRAP_PROGRESS_CHANNEL, { state, line });
    }
  }
}

/**
 * WU-1 FAIL-LOUD: push the ACTIONABLE first-run failure message to every live
 * renderer so the SidecarBanner can surface it (what failed + where + how to
 * fix). Separate from broadcastBootstrap's progress stream because this is the
 * terminal, user-facing error — not a progress line.
 */
function broadcastBootstrapError(message: string): void {
  for (const win of liveWindows()) {
    if (!win.webContents.isDestroyed()) {
      win.webContents.send(BOOTSTRAP_ERROR_CHANNEL, message);
    }
  }
}

/**
 * WU B3: push a playback-proxy build-state transition to every live renderer so
 * the Workspace can show the "building…" note, reload on 'ready', and surface a
 * build failure loudly on 'error'.
 */
function broadcastProxyState(videoId: string, state: ProxyBuildState, detail: string): void {
  for (const win of liveWindows()) {
    if (!win.webContents.isDestroyed()) {
      win.webContents.send(PROXY_STATE_CHANNEL, { videoId, state, detail });
    }
  }
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
  return sc
    .request<{ jobId: string }>('media.proxy.start', { videoId })
    .then(
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
 */
function runFirstRunBootstrap(): Promise<boolean> {
  return new Promise((resolveRun) => {
    const res = getResourcesPath();
    const python = process.env.MEDIA_STUDIO_PYTHON?.trim() || join(res, 'python', 'python.exe');
    const script = join(res, 'sidecar', 'runtime_setup', 'bootstrap.py');
    broadcastBootstrap('running', 'first-run setup starting');
    const child = spawn(python, [script], {
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

  // T5: in a packaged build whose runtime env was never built, stage 2 must
  // run BEFORE the sidecar starts (the embeddable python cannot serve
  // `-m media_studio` until bootstrap.py rewrites its ._pth). Dev builds (and
  // already-bootstrapped packaged builds) start immediately, exactly as before.
  const firstRun = needsFirstRunSetup(app.isPackaged, existsSync(firstRunCompletePath()));
  if (!firstRun) {
    // T5 hardening: a packaged build whose env already exists still needs THIS
    // copy's embeddable ._pth pointed at it (the sentinel is shared in appData,
    // the ._pth is per-copy — see ensurePthActivated). The first-run path lets
    // bootstrap.py write the ._pth instead.
    ensurePthActivated();
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
  disposeRepairSetupIpc = registerRepairSetupIpc({
    isBootstrapInFlight: () => bootstrapChild !== null,
    runBootstrap: runFirstRunBootstrap,
    onBootstrapSucceeded: () => {
      ensurePthActivated();
      sidecar?.restart();
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

  if (firstRun) {
    const sc2 = sidecar;
    const begin = (): void => {
      void runFirstRunBootstrap().then((ok) => {
        if (ok) {
          sc2.start();
        } else if (shouldStartSidecarAfterFailedFirstRun(existsSync(firstRunSentinelPath()))) {
          // Re-provision of an already-working install failed (e.g. an upgrade
          // back-filling new deps hit a transient download error). Start the
          // EXISTING env degraded rather than brick it — the loud bootstrap
          // error banner already surfaced what failed.
          ensurePthActivated();
          // eslint-disable-next-line no-console
          console.error('[bootstrap] first-run setup failed; starting existing env (degraded)');
          sc2.start();
        } else {
          // eslint-disable-next-line no-console
          console.error('[bootstrap] first-run setup failed; sidecar not started');
        }
      });
    };
    // Spawn once the renderer is up so it can observe bootstrap.progress.
    if (win.webContents.isLoading()) {
      win.webContents.once('did-finish-load', begin);
    } else {
      begin();
    }
  }
}

app.whenReady().then(() => {
  // The native "About Reframe" panel (Help ▸ About / macOS app menu) — the single
  // user-facing About surface. applicationName is the display brand "Reframe";
  // applicationVersion reads package.json.version (1.3.0) via Electron.
  app.setAboutPanelOptions({ applicationName: 'Reframe', applicationVersion: app.getVersion() });
  bootstrap();

  app.on('activate', () => {
    // macOS: re-create a window when the dock icon is clicked and none are open.
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  // Quit on all platforms except macOS (standard Electron convention).
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Ensure the sidecar is torn down before the process exits.
app.on('will-quit', (event) => {
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
  event.preventDefault();
  void sc.stop().finally(() => app.exit(0));
});
