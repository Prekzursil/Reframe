// sidecar.teardown.test.ts — V1.5 process-tree teardown. On Windows a bare
// child.kill() leaves the sidecar's grandchildren (ffmpeg / llama-server / the
// `wsl` verthor bridge) orphaned and burning CPU/GPU; stop()/restart() must
// instead `taskkill /PID <pid> /T /F` the WHOLE tree. child_process.spawn is
// mocked so we can (a) capture the taskkill argv and (b) drive the fake child's
// lifecycle. process.platform is stubbed per-test so BOTH the win32 tree-kill and
// the POSIX kill() fallback are exercised regardless of the CI runner OS.
import type { ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

interface FakeChild extends EventEmitter {
  stdin: { write: ReturnType<typeof vi.fn> };
  stdout: EventEmitter & { setEncoding: ReturnType<typeof vi.fn> };
  stderr: EventEmitter & { setEncoding: ReturnType<typeof vi.fn> };
  kill: ReturnType<typeof vi.fn>;
  pid?: number;
  exitCode: number | null;
  killed: boolean;
  fakeExit(code: number | null): void;
}

function makeChild(pid = 4321): FakeChild {
  const child = new EventEmitter() as FakeChild;
  const stdout = Object.assign(new EventEmitter(), { setEncoding: vi.fn() });
  const stderr = Object.assign(new EventEmitter(), { setEncoding: vi.fn() });
  child.stdin = { write: vi.fn() };
  child.stdout = stdout;
  child.stderr = stderr;
  child.pid = pid;
  child.exitCode = null;
  child.killed = false;
  const kill = vi.fn().mockImplementation(() => {
    child.killed = true;
    return true;
  });
  child.kill = kill;
  child.fakeExit = (code: number | null): void => {
    child.exitCode = code ?? 0;
    child.emit('exit', code);
  };
  return child;
}

// Every spawn (the sidecar AND any taskkill) is recorded with its argv.
const spawnCalls: Array<{ cmd: string; args: string[] }> = [];
const spawnMock = vi.fn();

vi.mock('node:child_process', () => ({
  spawn: (cmd: string, args: string[]) => {
    spawnCalls.push({ cmd, args: args ?? [] });
    return spawnMock();
  },
}));

vi.mock('node:fs', () => ({ existsSync: () => false }));

import { killProcessTree, Sidecar } from './sidecar';

const originalPlatform = process.platform;

function setPlatform(value: NodeJS.Platform): void {
  Object.defineProperty(process, 'platform', { value, configurable: true });
}

beforeEach(() => {
  spawnCalls.length = 0;
  spawnMock.mockReset();
  spawnMock.mockImplementation(() => makeChild());
});

afterEach(() => {
  setPlatform(originalPlatform);
  vi.useRealTimers();
});

function lastChild(): FakeChild {
  return spawnMock.mock.results.at(-1)!.value as FakeChild;
}

/** Only the taskkill spawns (not the sidecar spawns). */
function taskkillCalls(): Array<{ cmd: string; args: string[] }> {
  return spawnCalls.filter((c) => c.cmd === 'taskkill');
}

/** The fake is a partial mock; killProcessTree only touches pid/kill/on. */
function asChild(child: FakeChild): ChildProcessWithoutNullStreams {
  return child as unknown as ChildProcessWithoutNullStreams;
}

describe('killProcessTree', () => {
  it('taskkills the whole tree on Windows (/PID <pid> /T /F)', () => {
    setPlatform('win32');
    const child = makeChild(1234);

    killProcessTree(asChild(child));

    expect(taskkillCalls()).toHaveLength(1);
    expect(taskkillCalls()[0].args).toEqual(['/PID', '1234', '/T', '/F']);
    // The tree-kill replaces the direct signal — child.kill is NOT used.
    expect(child.kill).not.toHaveBeenCalled();
  });

  it('forwards the SIGKILL signal on POSIX via a direct kill (no taskkill)', () => {
    setPlatform('linux');
    const child = makeChild(1234);

    killProcessTree(asChild(child), 'SIGKILL');

    expect(taskkillCalls()).toHaveLength(0);
    expect(child.kill).toHaveBeenCalledWith('SIGKILL');
  });

  it('falls back to a direct kill on Windows when the pid is missing', () => {
    setPlatform('win32');
    const child = makeChild();
    child.pid = undefined;

    killProcessTree(asChild(child));

    expect(taskkillCalls()).toHaveLength(0);
    expect(child.kill).toHaveBeenCalledTimes(1);
  });

  it('falls back to a direct kill when the taskkill process errors', () => {
    setPlatform('win32');
    const child = makeChild(1234);
    // The taskkill fake child emits 'error' (e.g. taskkill not found).
    const killer = makeChild(999);
    spawnMock.mockImplementationOnce(() => killer);

    killProcessTree(asChild(child));

    expect(taskkillCalls()).toHaveLength(1);
    killer.emit('error', new Error('spawn taskkill ENOENT'));
    expect(child.kill).toHaveBeenCalledTimes(1);
  });
});

describe('Sidecar teardown tree-kill', () => {
  it('restart() tree-kills the old child on Windows', () => {
    setPlatform('win32');
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.start();
    const first = lastChild();
    first.pid = 4321;

    sc.restart();

    const tk = taskkillCalls();
    expect(tk).toHaveLength(1);
    expect(tk[0].args).toEqual(['/PID', '4321', '/T', '/F']);
    // A fresh sidecar was still spawned (restart proceeds).
    expect(sc.running).toBe(true);
    // On Windows the tree-kill replaces the direct child.kill().
    expect(first.kill).not.toHaveBeenCalled();
  });

  it('stop() tree-kills the child on Windows (app-quit teardown)', async () => {
    setPlatform('win32');
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.start();
    const child = lastChild();
    child.pid = 7777;

    const stopPromise = sc.stop();
    // killProcessTree ran synchronously inside stop().
    const tk = taskkillCalls();
    expect(tk).toHaveLength(1);
    expect(tk[0].args).toEqual(['/PID', '7777', '/T', '/F']);
    // Let stop() resolve (taskkill would cause the child to exit).
    child.fakeExit(0);
    await stopPromise;
    expect(child.kill).not.toHaveBeenCalled();
  });

  it('restart() still uses a direct kill on POSIX', () => {
    setPlatform('linux');
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.start();
    const first = lastChild();

    sc.restart();

    expect(taskkillCalls()).toHaveLength(0);
    expect(first.kill).toHaveBeenCalledTimes(1);
    expect(sc.running).toBe(true);
  });
});
