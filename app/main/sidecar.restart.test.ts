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

  it('restart() rejects in-flight calls immediately with a restart reason', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.start();

    // A request is in flight on child1 (never answered) at the moment restart()
    // is called: it must reject SYNCHRONOUSLY, not linger until the 60s timeout.
    const pending = sc.request('ping');
    let message = '';
    pending.catch((e: Error) => {
      message = e.message;
    });

    sc.restart();

    // No vi.advanceTimersByTime: the rejection is immediate (rejectAllPending),
    // NOT a consequence of the 60s REQUEST_TIMEOUT_MS firing.
    return Promise.resolve().then(() => {
      expect(message).toBe('sidecar restarting');
      expect(sc.running).toBe(true); // the replacement child is live
    });
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

  it('restart() race: a LATE exit from the killed child1 must not orphan child2 or spawn child3', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.on('error', () => undefined);

    sc.start();
    const child1 = lastChild();
    expect(sc.running).toBe(true);

    // restart() kills child1 and spawns child2. The mocked kill is synchronous
    // but real `kill()` is async: the 'exit' event for child1 can fire LATER,
    // after child2 is already live. Simulate that by NOT auto-emitting on kill
    // and firing child1's exit explicitly AFTER the restart returns.
    sc.restart();
    const child2 = lastChild();
    expect(child2).not.toBe(child1);
    expect(spawnMock).toHaveBeenCalledTimes(2);

    // A request now goes to child2; capture its in-flight pending call.
    const pending = sc.request('ping');
    let rejected = false;
    pending.catch(() => {
      rejected = true;
    });
    expect(child2.stdin.write).toHaveBeenCalledTimes(1);

    // child1's exit fires LATE (after child2 spawned). It must be ignored:
    // no child3 spawn, child2 still the live child, child2's request not rejected.
    child1.fakeExit(1);
    flushBackoff();

    expect(spawnMock).toHaveBeenCalledTimes(2); // NO child3
    expect(sc.running).toBe(true); // child2 still alive (this.child not nulled)
    return Promise.resolve().then(() => {
      expect(rejected).toBe(false); // child2's in-flight call NOT rejected
    });
  });

  it("a LIVE child exit with a null code formats the rejection as 'code null'", () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.on('error', () => undefined);
    sc.on('exit', () => undefined);

    sc.start();
    const child = lastChild();
    const pending = sc.request('ping');
    let message = '';
    pending.catch((e: Error) => {
      message = e.message;
    });

    // A signal-kill yields code=null; the rejection must coalesce to 'code null'.
    child.fakeExit(null);

    return Promise.resolve().then(() => {
      expect(message).toBe('sidecar exited (code null)');
    });
  });

  it('restart() tolerates a kill() that throws (process already gone)', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);

    sc.start();
    const child = lastChild();
    child.kill.mockImplementationOnce(() => {
      throw new Error('ESRCH: already gone');
    });

    // restart() must swallow the kill() throw and still spawn a fresh child.
    const result = sc.restart();

    expect(result).toEqual({ ok: true });
    expect(spawnMock).toHaveBeenCalledTimes(2);
    expect(sc.running).toBe(true);
  });

  it("a spawn 'error' on the LIVE child rejects pending calls and auto-restarts", () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    const restarts: number[] = [];
    sc.on('status', () => undefined);
    sc.on('error', () => undefined);
    sc.on('log', () => undefined);
    sc.on('restart', (n: number) => restarts.push(n));

    sc.start();
    const child = lastChild();
    const pending = sc.request('ping');
    let rejected = false;
    pending.catch(() => {
      rejected = true;
    });

    // The current child errors (the guard's false-branch: this.child === child),
    // so the supervisor must reject in-flight calls, drop the child and restart.
    child.emit('error', new Error('boom'));

    expect(sc.running).toBe(false);
    expect(restarts).toEqual([1]);
    flushBackoff();
    expect(spawnMock).toHaveBeenCalledTimes(2); // auto-restart spawned a fresh child
    return Promise.resolve().then(() => {
      expect(rejected).toBe(true);
    });
  });

  it('restart() race: a LATE spawn error from the killed child1 must not orphan child2', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    sc.on('error', () => undefined);
    sc.on('log', () => undefined);

    sc.start();
    const child1 = lastChild();

    sc.restart();
    const child2 = lastChild();
    expect(spawnMock).toHaveBeenCalledTimes(2);

    const pending = sc.request('ping');
    let rejected = false;
    pending.catch(() => {
      rejected = true;
    });

    // A late 'error' from the replaced child1 must be guarded the same way.
    child1.emit('error', new Error('late spawn error from child1'));
    flushBackoff();

    expect(spawnMock).toHaveBeenCalledTimes(2);
    expect(sc.running).toBe(true);
    expect(child2.stdin.write).toHaveBeenCalledTimes(1);
    return Promise.resolve().then(() => {
      expect(rejected).toBe(false);
    });
  });

  it('restart() detaches the old child stdout so its buffered output cannot misroute', () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);

    sc.start();
    const child1 = lastChild();
    sc.restart();
    const child2 = lastChild();

    // A request is in flight on child2 (id=1). If child1's stdout listeners were
    // NOT removed on replacement, a late chunk from child1 carrying id=1 would
    // resolve/settle child2's pending call from the WRONG process.
    const pending = sc.request<unknown>('ping');
    let settled = false;
    void pending.then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      },
    );

    // child1 emits a stray response for id=1 AFTER being replaced.
    child1.stdout.emit('data', `${JSON.stringify({ jsonrpc: '2.0', id: 1, result: 'stale' })}\n`);

    // child1's listeners were detached: the stale line is dropped, child2's
    // pending call stays unsettled (it belongs to child2's stdout).
    expect(child2.stdout.listenerCount('data')).toBe(1);
    return Promise.resolve().then(() => {
      expect(settled).toBe(false);
    });
  });
});
