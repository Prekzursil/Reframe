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
import { app, BrowserWindow, shell } from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, resolve as resolvePath } from 'node:path';
import { chooseDataRoot, DATA_DIR_MARKER } from './dataRoot';
import { registerDataFolderIpc } from './dataFolderIpc';
import { registerDialogIpc } from './dialogIpc';
import { resolveScopedMediaPath } from './exportPath';
import { registerIpc } from './ipc';
import { registerMediaProtocol, registerMediaSchemePrivileges } from './mediaProtocol';
import { registerShellIpc } from './shellIpc';
import { pthZipName, renderPthBody } from './pthActivation';
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

let bootstrapChild: ChildProcess | null = null;

/** `process.resourcesPath` (Electron-only) without an Electron-types dependency. */
function getResourcesPath(): string {
  return (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath ?? '';
}

// ---- DATA ROOT (the one relocatable folder; default OUT of %APPDATA%) -------
//
// Every heavy artifact (models/envs/exports/proxies/peaks/dubs/voices/feedback/
// chrome) derives from the sidecar's settings_store.default_config_dir(), which
// honors MEDIA_STUDIO_CONFIG_DIR first and otherwise falls back to
// %APPDATA%/media-studio. We resolve the data root HERE (chooseDataRoot is the
// pure part) and, in a packaged build, propagate it to the sidecar + first-run
// bootstrap by setting process.env.MEDIA_STUDIO_CONFIG_DIR before either spawns
// (both inherit process.env — buildSidecarEnv spreads it; bootstrap inherits it).
// DEV stays byte-identical to the old behavior: only packaged builds consider the
// exe-dir / marker, so a dev run still resolves %APPDATA%/media-studio.

/** Directory holding the running executable (where the marker file lives). */
function exeDir(): string {
  return dirname(process.execPath);
}

/** Absolute path of the data-folder marker file (`<exeDir>/data-dir.txt`). */
function dataDirMarkerPath(): string {
  return join(exeDir(), DATA_DIR_MARKER);
}

/** Read the marker file's trimmed contents, or undefined if absent/unreadable. */
function readDataDirMarker(): string | undefined {
  try {
    return readFileSync(dataDirMarkerPath(), 'utf8');
  } catch {
    return undefined; // no marker (or unreadable) -> ignored by chooseDataRoot
  }
}

/** True when `<exeDir>/data` is creatable/writable (a writable install dir). */
function isExeDataWritable(dir: string): boolean {
  try {
    mkdirSync(dir, { recursive: true });
    // Prove writability (mkdir on an existing dir succeeds even when read-only).
    const probe = join(dir, `.write-probe-${process.pid}`);
    writeFileSync(probe, '');
    try {
      unlinkSync(probe);
    } catch {
      /* probe cleanup is best-effort */
    }
    return true;
  } catch {
    return false; // read-only install (e.g. Program Files) -> fall back to appData
  }
}

/**
 * Resolve the data root to USE this session (IO wrapper over chooseDataRoot).
 * In a packaged build the exe-dir / marker are considered; in dev only the env
 * override + the %APPDATA% fallback are (so dev stays byte-identical).
 */
function resolveDataRoot(): string {
  const appDataRoot = join(app.getPath('appData'), 'media-studio');
  const envOverride = process.env.MEDIA_STUDIO_CONFIG_DIR;
  if (!app.isPackaged) {
    return chooseDataRoot({ envOverride, appDataRoot });
  }
  const exeDataDir = join(exeDir(), 'data');
  return chooseDataRoot({
    envOverride,
    markerContent: readDataDirMarker(),
    exeDataDir,
    exeDataWritable: isExeDataWritable(exeDataDir),
    appDataRoot,
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
 * SAME tree main joins for `short:`/`dub:`/the `._pth` env dir. Packaged-only and
 * never clobbers an explicit override (a power-user value wins), so dev stays
 * byte-identical (no env set; sidecar falls back to %APPDATA%/media-studio).
 */
function propagateDataRootEnv(): void {
  if (!app.isPackaged) return;
  if (!process.env.MEDIA_STUDIO_CONFIG_DIR) {
    process.env.MEDIA_STUDIO_CONFIG_DIR = DATA_ROOT;
  }
}

/** WIRING-T5 §2: the sidecar-env sentinel bootstrap.py writes on success. */
function firstRunSentinelPath(): string {
  return join(DATA_ROOT, 'envs', 'sidecar', '.media-studio-env.json');
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
      resolveRun(false);
    });
    child.on('exit', (code: number | null) => {
      bootstrapChild = null;
      const ok = code === 0;
      broadcastBootstrap(ok ? 'done' : 'error', `bootstrap exited (code ${code ?? 'null'})`);
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
    title: 'Reframe - Media Studio',
    webPreferences: {
      preload: join(__dirname, '../preload/preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.once('ready-to-show', () => win.show());

  // Open external links in the OS browser, not inside the app window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: 'deny' };
  });

  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (isDev && devUrl) {
    void win.loadURL(devUrl);
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'));
  }

  return win;
}

function bootstrap(): void {
  // Set MEDIA_STUDIO_CONFIG_DIR BEFORE the sidecar is created or first-run
  // bootstrap is spawned, so both inherit the SAME data root main derives its
  // short:/dub:/._pth paths from (the cross-process invariant below).
  propagateDataRootEnv();

  sidecar = createSidecar();

  // T5: in a packaged build whose runtime env was never built, stage 2 must
  // run BEFORE the sidecar starts (the embeddable python cannot serve
  // `-m media_studio` until bootstrap.py rewrites its ._pth). Dev builds (and
  // already-bootstrapped packaged builds) start immediately, exactly as before.
  const firstRun = app.isPackaged && !existsSync(firstRunSentinelPath());
  if (!firstRun) {
    // T5 hardening: a packaged build whose env already exists still needs THIS
    // copy's embeddable ._pth pointed at it (the sentinel is shared in appData,
    // the ._pth is per-copy — see ensurePthActivated). The first-run path lets
    // bootstrap.py write the ._pth instead.
    ensurePthActivated();
    sidecar.start();
  }

  disposeIpc = registerIpc(sidecar, liveWindows);
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

  // U1: stream local media to <video> with Range support. The resolver returns
  // the PLAYABLE path for a videoId: the cached remux/proxy when media.playable
  // reports one, otherwise the original library path.
  const sc = sidecar; // capture for the closure (sidecar is module-level let)
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
    // MEDIA_STUDIO_CONFIG_DIR first; bootstrap() (packaged) sets that env var to
    // DATA_ROOT before spawning the sidecar, and DATA_ROOT is exactly what we
    // join here — so the two roots stay equal whether the data folder is the
    // %APPDATA% default or a user-chosen location. If anyone changes how the
    // sidecar resolves its root WITHOUT updating DATA_ROOT (or stops propagating
    // the env), the roots diverge and every `short:` URL 404s silently.
    if (videoId.startsWith('short:')) {
      const exportsRoot = resolvePath(DATA_ROOT, 'exports');
      return resolveScopedMediaPath(videoId, 'short:', exportsRoot);
    }
    if (!sc) return null;
    try {
      const verdict = await sc.request<{ playable: boolean; proxyPath?: string }>(
        'media.playable',
        { videoId },
      );
      if (verdict.proxyPath) return verdict.proxyPath;
      const { videos } = await sc.request<{ videos: { id: string; path: string }[] }>(
        'library.list',
      );
      return videos.find((v) => v.id === videoId)?.path ?? null;
    } catch {
      return null; // resolver failure -> handler responds 404 (never hangs)
    }
  });

  const win = createWindow();

  if (firstRun) {
    const sc2 = sidecar;
    const begin = (): void => {
      void runFirstRunBootstrap().then((ok) => {
        if (ok) {
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
  event.preventDefault();
  void sc.stop().finally(() => app.exit(0));
});
