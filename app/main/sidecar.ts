// sidecar.ts — spawn / supervise the Python compute sidecar and speak the
// frozen stdio JSON-RPC 2.0 newline-delimited protocol (CONTRACTS.md §2).
//
// Transport contract (CONTRACTS.md §2):
//   - We write one JSON object per line to the sidecar's STDIN (requests).
//   - The sidecar writes one JSON object per line to STDOUT:
//       responses        {jsonrpc,id,result}     | {jsonrpc,id,error}
//       progress notif.   {jsonrpc,method:"job.progress",params:{jobId,pct,message}}
//       done notif.       {jsonrpc,method:"job.done",params:{jobId,result}}
//   - STDERR is logs only — never parsed as protocol.
//
// CONTRACT-NOTE (launch command): the sidecar is started as
//   `py -3.12 -m media_studio`  (cwd = <repo>/sidecar)
// on Windows, matching CONTRACTS.md §7 (Python 3.12, stdlib JSON-RPC). We launch
// the ASSEMBLED entry point `media_studio` (its `__main__.py` registers every §2
// feature handler via handlers.register_all, THEN serves), NOT `media_studio.rpc`
// — the bare core registers only ping/job.* and would answer every feature call
// with METHOD_NOT_FOUND. The command + cwd + interpreter are overridable via the
// SidecarOptions / env (MEDIA_STUDIO_PYTHON, MEDIA_STUDIO_SIDECAR_DIR) so a
// configured python (e.g. a venv) can be used instead of the `py` launcher.
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

export interface ProgressNotification {
  jobId: string;
  pct: number;
  message: string;
}

export interface DoneNotification {
  jobId: string;
  result?: unknown;
}

export interface SidecarOptions {
  /** Python interpreter/launcher argv[0]. Default: resolvePython() (env -> .venv -> py). */
  python?: string;
  /** Extra args before `-m media_studio`. Default: resolvePython() ([] for a
   *  concrete interpreter; ['-3.12'] only for the `py` launcher). */
  pythonArgs?: string[];
  /** Working dir for the sidecar (where the `media_studio` package lives). */
  cwd?: string;
  /** Max automatic restarts within the restart window before giving up. */
  maxRestarts?: number;
  /** Restart-count window (ms); restarts older than this don't count. */
  restartWindowMs?: number;
  /**
   * Packaged-build flag (pass `app.isPackaged`; WIRING-T5 §2). When true the
   * supervisor resolves the BUNDLED embeddable python + sidecar source under
   * `process.resourcesPath` and injects the MEDIA_STUDIO_PYTHON / SIDECAR_DIR /
   * FFMPEG / FFPROBE env quartet into the child. Default false — dev behavior
   * is byte-identical.
   */
  packaged?: boolean;
}

interface PendingCall {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  /** Timeout guard so a hung-but-alive handler never freezes the channel. */
  timer?: ReturnType<typeof setTimeout>;
}

/**
 * A single in-flight request that never sees its `id` response — a hung-but-alive
 * synchronous handler — used to freeze the whole RPC channel forever (every later
 * rpc() queued behind it). Reject it after this generous bound instead. The
 * quick-ack `{jobId}` contract means a real response is fast; long work completes
 * via the `done` event, NOT this promise, so 60s never truncates real work.
 */
const REQUEST_TIMEOUT_MS = 60_000;

/**
 * Supervisor lifecycle state surfaced to the renderer (self-healing banner).
 *   'running'    — the sidecar process is alive and serving.
 *   'restarting' — a restart is pending (auto-restart backoff OR a manual
 *                  restart()); the next transition is 'running' or 'down'.
 *   'down'       — auto-restart gave up (crash budget exhausted). NOT terminal:
 *                  restart() resets the window and brings it back to 'running'.
 */
export type SidecarState = 'running' | 'restarting' | 'down';

// Launch the assembled entry point (`-m media_studio` -> media_studio/__main__.py),
// which registers all §2 feature handlers before serving — NOT the bare core
// `media_studio.rpc` (ping/job.* only).
const RPC_MODULE_ARGS = ['-m', 'media_studio'];

/** `process.resourcesPath` (Electron-only) without depending on Electron types. */
function getResourcesPath(): string | undefined {
  return (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath;
}

/**
 * Pick the Python interpreter + the args that precede `-m media_studio`. Order:
 * MEDIA_STUDIO_PYTHON env -> the sidecar's own `.venv` -> the Windows `py`
 * launcher with a `-3.12` selector (-> `python3` elsewhere).
 *
 * IMPORTANT: `-3.12` is a `py`-LAUNCHER flag only. A concrete interpreter
 * (the venv or an env-named python) must NOT receive it, so `args` is empty in
 * those cases — passing `-3.12` to `python.exe` makes it exit with
 * "Unknown option: -3".
 */
function resolvePython(sidecarDir: string, packaged = false): { python: string; args: string[] } {
  const fromEnv = process.env.MEDIA_STUDIO_PYTHON;
  if (fromEnv && fromEnv.trim() !== '') return { python: fromEnv, args: [] };
  // WIRING-T5 §2: packaged builds ship the embeddable CPython at
  // resources/python/python.exe (staged by build/python-embed-setup.ps1).
  if (packaged) {
    const res = getResourcesPath();
    if (res) return { python: resolve(res, 'python', 'python.exe'), args: [] };
  }
  const venv =
    process.platform === 'win32'
      ? resolve(sidecarDir, '.venv', 'Scripts', 'python.exe')
      : resolve(sidecarDir, '.venv', 'bin', 'python');
  if (existsSync(venv)) return { python: venv, args: [] };
  if (process.platform === 'win32') return { python: 'py', args: ['-3.12'] };
  return { python: 'python3', args: [] };
}

/**
 * Resolve the default sidecar working directory. In dev the package lives at
 * `<repo>/sidecar`; from the built app it may be relocated, so allow an env
 * override. Falls back to a best-effort relative path from this file.
 */
function defaultSidecarDir(packaged = false): string {
  const fromEnv = process.env.MEDIA_STUDIO_SIDECAR_DIR;
  if (fromEnv && fromEnv.trim() !== '') return fromEnv;
  // WIRING-T5 §2: packaged builds ship the sidecar source at resources/sidecar.
  if (packaged) {
    const res = getResourcesPath();
    if (res) return resolve(res, 'sidecar');
  }
  // out/main/main.js (built) or main/ (dev, via electron-vite) -> repo/sidecar.
  // Probe a couple of plausible relative roots and use the first that exists.
  const candidates = [
    resolve(process.cwd(), 'sidecar'),
    resolve(process.cwd(), '..', 'sidecar'),
    resolve(__dirname, '..', '..', '..', 'sidecar'),
    resolve(__dirname, '..', '..', 'sidecar'),
  ];
  for (const dir of candidates) {
    if (existsSync(dir)) return dir;
  }
  return candidates[0]!;
}

/**
 * Build the sidecar child env (WIRING-T4A §3 / WIRING-T2 §5 / WIRING-T5 §2).
 *
 * - MEDIA_STUDIO_NODE_EXE: the remotion render CLI runs on the app's OWN
 *   Electron exe with ELECTRON_RUN_AS_NODE=1 (set by the python engine); the
 *   engine's resolution chain is env -> settings -> dev fallback.
 * - MEDIA_STUDIO_RENDER_JS / MEDIA_STUDIO_REMOTION_BUNDLE: only when the
 *   packaged resources actually exist (the existsSync gate keeps dev runs on
 *   the engine's repo fallbacks).
 * - PIP_EXTRA_INDEX_URL: chatterbox-env's torch +cu124 wheels resolve only
 *   with the PyTorch index visible (assets.ensure inherits this env).
 * - packaged=true (WIRING-T5 §2): inject the bundled-resource quartet —
 *   MEDIA_STUDIO_PYTHON (embeddable CPython), MEDIA_STUDIO_SIDECAR_DIR,
 *   MEDIA_STUDIO_FFMPEG / MEDIA_STUDIO_FFPROBE (ffmpeg.py's env link) — so the
 *   sidecar (and anything it spawns, e.g. bootstrap re-runs) resolves the
 *   shipped binaries on a machine with no dev paths.
 * Pre-set env vars always win (never clobber a user override).
 */
export function buildSidecarEnv(packaged = false): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env };
  env.MEDIA_STUDIO_NODE_EXE = env.MEDIA_STUDIO_NODE_EXE ?? process.execPath;
  env.PIP_EXTRA_INDEX_URL = env.PIP_EXTRA_INDEX_URL ?? 'https://download.pytorch.org/whl/cu124';
  const resourcesPath = getResourcesPath();
  if (resourcesPath) {
    const renderJs = resolve(resourcesPath, 'render-cli', 'dist', 'render.js');
    if (!env.MEDIA_STUDIO_RENDER_JS && existsSync(renderJs)) {
      env.MEDIA_STUDIO_RENDER_JS = renderJs;
      env.MEDIA_STUDIO_REMOTION_BUNDLE = resolve(
        resourcesPath,
        'render-cli',
        'out',
        'remotion-bundle',
      );
    }
    if (packaged) {
      // WIRING-T5 §2 packaged-mode supervisor block (names FROZEN there).
      env.MEDIA_STUDIO_PYTHON =
        env.MEDIA_STUDIO_PYTHON ?? resolve(resourcesPath, 'python', 'python.exe');
      env.MEDIA_STUDIO_SIDECAR_DIR =
        env.MEDIA_STUDIO_SIDECAR_DIR ?? resolve(resourcesPath, 'sidecar');
      env.MEDIA_STUDIO_FFMPEG =
        env.MEDIA_STUDIO_FFMPEG ?? resolve(resourcesPath, 'bin', 'ffmpeg.exe');
      env.MEDIA_STUDIO_FFPROBE =
        env.MEDIA_STUDIO_FFPROBE ?? resolve(resourcesPath, 'bin', 'ffprobe.exe');
    }
  }
  return env;
}

/**
 * Supervises the Python sidecar process and bridges JSON-RPC over its stdio.
 *
 * Events:
 *   'progress'  (ProgressNotification)
 *   'done'      (DoneNotification)
 *   'log'       (string)        — a line the sidecar wrote to stderr
 *   'exit'      (code|null)     — the sidecar process exited
 *   'restart'   (attempt:number)
 *   'status'    (SidecarState)  — running | restarting | down (self-healing)
 *   'error'     (Error)         — auto-restart gave up; the object stays usable
 *                                 (restart() resets the window and respawns)
 */
export class Sidecar extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private readonly pending = new Map<number, PendingCall>();
  private stdoutBuffer = '';
  private stderrBuffer = '';
  private stopping = false;
  private restartTimestamps: number[] = [];
  /** Last state we emitted, so 'status' only fires on a real transition. */
  private lastState: SidecarState | null = null;

  private readonly python: string;
  private readonly pythonArgs: string[];
  private readonly cwd: string;
  private readonly maxRestarts: number;
  private readonly restartWindowMs: number;
  private readonly packaged: boolean;

  constructor(options: SidecarOptions = {}) {
    super();
    this.packaged = options.packaged ?? false;
    this.cwd = options.cwd ?? defaultSidecarDir(this.packaged);
    const resolved = resolvePython(this.cwd, this.packaged);
    this.python = options.python ?? resolved.python;
    this.pythonArgs = options.pythonArgs ?? resolved.args;
    this.maxRestarts = options.maxRestarts ?? 5;
    this.restartWindowMs = options.restartWindowMs ?? 60_000;
  }

  /** Whether the sidecar process is currently alive. */
  get running(): boolean {
    return this.child !== null && this.child.exitCode === null && !this.child.killed;
  }

  /**
   * Emit a 'status' event only when the lifecycle state actually changes, so
   * idempotent start()/restart() calls don't spam the renderer.
   */
  private emitStatus(state: SidecarState): void {
    if (this.lastState === state) return;
    this.lastState = state;
    this.emit('status', state);
  }

  /** Spawn the sidecar. Idempotent: a second call while running is a no-op. */
  start(): void {
    if (this.running) return;
    this.stopping = false;
    const args = [...this.pythonArgs, ...RPC_MODULE_ARGS];
    const child = spawn(this.python, args, {
      cwd: this.cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: buildSidecarEnv(this.packaged),
      windowsHide: true,
    }) as ChildProcessWithoutNullStreams;

    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk: string) => this.onStdout(chunk));
    child.stderr.on('data', (chunk: string) => this.onStderr(chunk));
    // Capture the child per-listener so a LATE 'exit'/'error' from a process we
    // already replaced (via restart()) is ignored — see onExit/onSpawnError's
    // `this.child !== child` guard. Without this, child1's delayed exit would
    // reject child2's in-flight calls, null this.child (orphaning the live
    // child2) and spawn a redundant child3 (two live sidecars + misrouting).
    child.on('exit', (code) => this.onExit(child, code));
    child.on('error', (err) => this.onSpawnError(child, err));

    this.child = child;
    this.emitStatus('running');
  }

  /**
   * Self-healing manual restart (renderer "Restart sidecar" action). RESETS the
   * crash-budget window — clearing the auto-restart give-up state — and respawns
   * the process, so this works even AFTER the supervisor emitted 'down'. Emits
   * 'status' 'restarting' immediately, then 'running' once the new child spawns
   * (or the spawn 'error'/'exit' path drives it back through auto-restart).
   *
   * Returns `{ ok }`: `true` once a fresh process is spawned, `false` if the
   * synchronous spawn threw (e.g. interpreter missing). Never throws — the ipc
   * handler forwards the boolean so the UI can re-offer Restart.
   */
  restart(): { ok: boolean } {
    // Clear the give-up state: forget prior crash timestamps so maybeRestart()
    // is armed again, and re-arm the supervisor (a prior stop() set stopping).
    this.restartTimestamps = [];
    this.stopping = false;
    this.emitStatus('restarting');
    // Reject in-flight calls IMMEDIATELY (mirroring stop()/onExit): the old child's
    // later 'exit' is intentionally dropped by the per-child guard once start()
    // reassigns this.child, so without this any request in flight AT restart() time
    // would linger until the 60s REQUEST_TIMEOUT_MS instead of failing loudly now.
    // Unconditional (not inside the `if (existing)` block) so it also covers the
    // post-give-up restart where this.child is already null (pending is empty -> no-op).
    this.rejectAllPending(new Error('sidecar restarting'));
    const existing = this.child;
    // If a process is somehow still alive, tear it down first (best-effort) so
    // we don't leak it. Its later 'exit'/'error' is ignored by the per-child
    // guard in onExit/onSpawnError (this.child !== existing) — so we KEEP those
    // listeners attached. We DO detach its stdout/stderr 'data' listeners,
    // because a buffered late stdout chunk from the OLD child cannot be guarded
    // by child identity inside onStdout and would otherwise dispatch into the
    // NEW child's pending-call map (response misrouting).
    if (existing) {
      this.child = null;
      existing.stdout.removeAllListeners('data');
      existing.stderr.removeAllListeners('data');
      try {
        existing.kill();
      } catch {
        /* already gone */
      }
    }
    try {
      this.start();
      return { ok: this.running };
    } catch (err) {
      this.emit('log', `[sidecar] restart spawn error: ${(err as Error).message}`);
      this.emitStatus('down');
      return { ok: false };
    }
  }

  /** Stop the sidecar and reject all in-flight calls. No auto-restart after. */
  async stop(): Promise<void> {
    this.stopping = true;
    const child = this.child;
    this.child = null;
    this.rejectAllPending(new Error('sidecar stopped'));
    if (!child || child.exitCode !== null) return;
    return new Promise<void>((resolveStop) => {
      const done = (): void => resolveStop();
      child.once('exit', done);
      try {
        child.kill();
      } catch {
        done();
        return;
      }
      // Hard-kill fallback if it ignores the graceful signal.
      setTimeout(() => {
        if (child.exitCode === null) {
          try {
            child.kill('SIGKILL');
          } catch {
            /* already gone */
          }
        }
      }, 2_000).unref?.();
    });
  }

  /**
   * Send a JSON-RPC request and resolve with its `result` (or reject on
   * `error`). The renderer/ipc layer treats this single promise as the job's
   * terminal value: for long jobs we resolve when the matching `id` response
   * arrives. (The sidecar's long-job convention is to return `{jobId}` and the
   * actual completion is observed via the `done` event by ipc.ts.)
   */
  request<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
    if (!this.running || !this.child) {
      return Promise.reject(new Error('sidecar is not running'));
    }
    const id = this.nextId++;
    const payload = {
      jsonrpc: '2.0' as const,
      id,
      method,
      params: params ?? {},
    };
    return new Promise<T>((resolveCall, rejectCall) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        rejectCall(
          new Error(`sidecar request '${method}' timed out after ${REQUEST_TIMEOUT_MS}ms`),
        );
      }, REQUEST_TIMEOUT_MS);
      // Node timers keep the event loop alive; unref so a pending request never
      // blocks a clean shutdown (the reject still fires if the loop is running).
      timer.unref?.();
      this.pending.set(id, {
        resolve: (value) => resolveCall(value as T),
        reject: rejectCall,
        timer,
      });
      try {
        this.child!.stdin.write(`${JSON.stringify(payload)}\n`);
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        rejectCall(err instanceof Error ? err : new Error(String(err)));
      }
    });
  }

  // ---- stdio plumbing -----------------------------------------------------

  private onStdout(chunk: string): void {
    this.stdoutBuffer += chunk;
    let newlineIndex = this.stdoutBuffer.indexOf('\n');
    while (newlineIndex !== -1) {
      const line = this.stdoutBuffer.slice(0, newlineIndex).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);
      if (line !== '') this.dispatchLine(line);
      newlineIndex = this.stdoutBuffer.indexOf('\n');
    }
  }

  private onStderr(chunk: string): void {
    this.stderrBuffer += chunk;
    let newlineIndex = this.stderrBuffer.indexOf('\n');
    while (newlineIndex !== -1) {
      const line = this.stderrBuffer.slice(0, newlineIndex);
      this.stderrBuffer = this.stderrBuffer.slice(newlineIndex + 1);
      this.emit('log', line);
      newlineIndex = this.stderrBuffer.indexOf('\n');
    }
  }

  private dispatchLine(line: string): void {
    let msg: unknown;
    try {
      msg = JSON.parse(line);
    } catch {
      // Not protocol JSON — treat as a stray log line rather than crashing.
      this.emit('log', line);
      return;
    }
    if (!msg || typeof msg !== 'object') return;
    const record = msg as Record<string, unknown>;

    // Notification (no id): job.progress / job.done.
    if (record.id === undefined || record.id === null) {
      this.handleNotification(record);
      return;
    }

    const id = record.id;
    if (typeof id !== 'number') return;
    const call = this.pending.get(id);
    if (!call) return;
    this.pending.delete(id);
    if (call.timer) clearTimeout(call.timer);

    if ('error' in record && record.error) {
      const err = record.error as { code?: number; message?: string };
      const message = err.message ?? 'sidecar error';
      const wrapped = new Error(message);
      if (typeof err.code === 'number') {
        (wrapped as Error & { code?: number }).code = err.code;
      }
      call.reject(wrapped);
      return;
    }
    call.resolve(record.result);
  }

  private handleNotification(record: Record<string, unknown>): void {
    const method = record.method;
    const params = (record.params ?? {}) as Record<string, unknown>;
    if (method === 'job.progress') {
      this.emit('progress', {
        jobId: String(params.jobId ?? ''),
        pct: Number(params.pct ?? 0),
        message: String(params.message ?? ''),
      } satisfies ProgressNotification);
    } else if (method === 'job.done') {
      this.emit('done', {
        jobId: String(params.jobId ?? ''),
        result: params.result,
      } satisfies DoneNotification);
    }
    // Unknown notifications are ignored (forward-compatible).
  }

  // ---- lifecycle / restart ------------------------------------------------

  private onSpawnError(child: ChildProcessWithoutNullStreams, err: Error): void {
    // Ignore an 'error' from a child we already replaced (restart-race guard):
    // acting on it would reject the live child's calls, null this.child and
    // trigger a redundant respawn.
    if (this.child !== child) return;
    this.emit('log', `[sidecar] spawn error: ${err.message}`);
    this.rejectAllPending(err);
    this.child = null;
    this.maybeRestart();
  }

  private onExit(child: ChildProcessWithoutNullStreams, code: number | null): void {
    // Ignore an 'exit' from a child we already replaced (restart-race guard):
    // acting on it would reject the live child's calls, null this.child
    // (orphaning the live process) and spawn a redundant second sidecar.
    if (this.child !== child) return;
    this.emit('exit', code);
    this.rejectAllPending(new Error(`sidecar exited (code ${code ?? 'null'})`));
    this.child = null;
    this.maybeRestart();
  }

  private maybeRestart(): void {
    if (this.stopping) return;
    const now = Date.now();
    this.restartTimestamps = this.restartTimestamps.filter((t) => now - t < this.restartWindowMs);
    if (this.restartTimestamps.length >= this.maxRestarts) {
      // Give up AUTO-restart, but stay usable: emit 'down' so the renderer can
      // offer a manual Restart (which resets the window via restart()).
      this.emitStatus('down');
      this.emit(
        'error',
        new Error(
          `sidecar crashed ${this.restartTimestamps.length} times within ` +
            `${this.restartWindowMs}ms; giving up auto-restart`,
        ),
      );
      return;
    }
    this.restartTimestamps.push(now);
    const attempt = this.restartTimestamps.length;
    this.emitStatus('restarting');
    this.emit('restart', attempt);
    // Small backoff so a tight crash loop doesn't spin the CPU.
    setTimeout(
      () => {
        if (!this.stopping) this.start();
      },
      Math.min(250 * attempt, 2_000),
    ).unref?.();
  }

  private rejectAllPending(reason: Error): void {
    for (const [, call] of this.pending) {
      if (call.timer) clearTimeout(call.timer);
      call.reject(reason);
    }
    this.pending.clear();
  }
}

/**
 * WU B3: start the sidecar `media.proxy.start` job for `videoId` and resolve with
 * the built proxy's absolute path once its terminal `job.done` arrives. Rejects
 * LOUDLY when the job reports an error payload (a failed transcode), finishes
 * without a path, OR the sidecar process EXITS mid-build (a crash) — so the build
 * promise ALWAYS settles instead of hanging until REQUEST_TIMEOUT_MS, and the
 * caller (PlaybackProxy) never silently serves the raw source or wedges its
 * in-flight map. This just bridges the job's done/exit events to a promise and
 * always detaches BOTH listeners on settle.
 */
export function buildProxyJob(sc: Sidecar, videoId: string): Promise<string> {
  return sc.request<{ jobId: string }>('media.proxy.start', { videoId }).then(
    ({ jobId }) =>
      new Promise<string>((resolveBuild, rejectBuild) => {
        const onDone = (done: DoneNotification): void => {
          if (done.jobId !== jobId) return;
          sc.off('done', onDone);
          sc.off('exit', onExit);
          const result = (done.result ?? {}) as { path?: string; error?: { message?: string } };
          if (result.error) {
            rejectBuild(new Error(result.error.message ?? `proxy build failed for ${videoId}`));
          } else if (typeof result.path === 'string' && result.path !== '') {
            resolveBuild(result.path);
          } else {
            rejectBuild(new Error(`proxy build for ${videoId} returned no path`));
          }
        };
        // A sidecar crash mid-build emits 'exit' but NEVER a matching 'done', so
        // without this the promise would hang until the 60s request timeout. Reject
        // loudly on exit and detach the done listener (once: 'exit' fires at most
        // once for this build).
        const onExit = (code: number | null): void => {
          sc.off('done', onDone);
          rejectBuild(
            new Error(`sidecar exited (code ${code ?? 'null'}) during proxy build for ${videoId}`),
          );
        };
        sc.on('done', onDone);
        sc.once('exit', onExit);
      }),
  );
}
