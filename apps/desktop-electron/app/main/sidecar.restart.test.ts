// sidecar.restart.test.ts — self-healing supervisor: the public restart() resets
// the crash-budget window (clearing the auto-restart give-up state) and respawns
// the process, and the supervisor emits 'status' (running|restarting|down) on
// transitions. child_process.spawn is fully mocked: each spawn returns a fake
// child whose streams/exit we drive synchronously. Runs in the default node env.
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// ---- spawn mock -------------------------------------------------------------

interface FakeChild extends EventEmitter {
  stdin: { write: ReturnType<typeof vi.fn> };
  stdout: EventEmitter & { setEncoding: ReturnType<typeof vi.fn> };
  stderr: EventEmitter & { setEncoding: ReturnType<typeof vi.fn> };
  kill: ReturnType<typeof vi.fn>;
  exitCode: number | null;
  killed: boolean;
  /** Test helper: simulate the process exiting with a code. */
  fakeExit(code: number | null): void;
}

function makeChild(): FakeChild {
  const child = new EventEmitter() as FakeChild;
  const stdout = Object.assign(new EventEmitter(), { setEncoding: vi.fn() });
  const stderr = Object.assign(new EventEmitter(), { setEncoding: vi.fn() });
  child.stdin = { write: vi.fn() };
  child.stdout = stdout;
  child.stderr = stderr;
  child.exitCode = null;
  child.killed = false;
  const kill = vi.fn();
  kill.mockImplementation(() => {
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

const spawnMock = vi.fn();

vi.mock('node:child_process', () => ({
  spawn: (...args: unknown[]) => {
    void args;
    return spawnMock();
  },
}));

// existsSync is touched by resolvePython/defaultSidecarDir — keep it deterministic.
vi.mock('node:fs', () => ({ existsSync: () => false }));

import { Sidecar } from './sidecar';

beforeEach(() => {
  spawnMock.mockReset();
  spawnMock.mockImplementation(() => makeChild());
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** Drain the small backoff timer that maybeRestart() schedules. */
function flushBackoff(): void {
  vi.advanceTimersByTime(2_000);
}

/** The most recently spawned fake child (typed). */
function lastChild(): FakeChild {
  return spawnMock.mock.results.at(-1)!.value as FakeChild;
}

describe('Sidecar.restart() — self-healing', () => {
  it('emits status:running on start and is reflected by `running`', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    const states: string[] = [];
    sc.on('status', (s: string) => states.push(s));

    sc.start();

    expect(spawnMock).toHaveBeenCalledTimes(1);
    expect(sc.running).toBe(true);
    expect(states).toEqual(['running']);
  });

  it('auto-restarts up to maxRestarts, then emits status:down + error (gives up)', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x', maxRestarts: 2 });
    const states: string[] = [];
    const errors: Error[] = [];
    sc.on('status', (s: string) => states.push(s));
    sc.on('error', (e: Error) => errors.push(e));

    sc.start(); // spawn #1, status running
    // Crash repeatedly: each exit schedules a backoff respawn until the budget
    // (2 within the window) is exhausted, then it gives up.
    for (let i = 0; i < 3; i += 1) {
      lastChild().fakeExit(1);
      flushBackoff();
    }

    expect(errors).toHaveLength(1);
    expect(errors[0].message).toContain('giving up auto-restart');
    expect(states).toContain('down');
    // After give-up the object is NOT alive but is still usable.
    expect(sc.running).toBe(false);
  });

  it('restart() works AFTER give-up: resets the window and respawns (status running)', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x', maxRestarts: 1 });
    const states: string[] = [];
    sc.on('status', (s: string) => states.push(s));
    sc.on('error', () => undefined); // swallow the give-up error for this test

    sc.start();
    // Exhaust the budget (maxRestarts:1 -> the 2nd crash gives up).
    lastChild().fakeExit(1);
    flushBackoff();
    lastChild().fakeExit(1);
    flushBackoff();
    expect(states).toContain('down');
    const spawnsBefore = spawnMock.mock.calls.length;

    // The whole point: restart() must work after give-up.
    const result = sc.restart();

    expect(result).toEqual({ ok: true });
    expect(sc.running).toBe(true);
    expect(spawnMock.mock.calls.length).toBe(spawnsBefore + 1);
    // restart() emitted restarting -> running (transition de-duped against down).
    expect(states.at(-1)).toBe('running');
    expect(states).toContain('restarting');
  });

  it('restart() RESETS the restart counter — auto-restart budget is full again', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x', maxRestarts: 2 });
    const errors: Error[] = [];
    sc.on('status', () => undefined);
    sc.on('error', (e: Error) => errors.push(e));

    sc.start();
    // Burn the full budget -> give up once.
    for (let i = 0; i < 3; i += 1) {
      lastChild().fakeExit(1);
      flushBackoff();
    }
    expect(errors).toHaveLength(1);

    // Manual restart resets restartTimestamps to [].
    sc.restart();
    expect(sc.running).toBe(true);

    // Because the window is cleared, the supervisor must auto-restart a FULL
    // fresh budget before giving up a SECOND time.
    for (let i = 0; i < 3; i += 1) {
      lastChild().fakeExit(1);
      flushBackoff();
    }
    expect(errors).toHaveLength(2); // a second give-up only happened after a new full budget
  });

  it('restart() while running tears down the old child and spawns a fresh one', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.start();
    const first = lastChild();
    expect(sc.running).toBe(true);

    sc.restart();

    expect(first.kill).toHaveBeenCalledTimes(1);
    expect(spawnMock).toHaveBeenCalledTimes(2);
    expect(sc.running).toBe(true);
  });
});
