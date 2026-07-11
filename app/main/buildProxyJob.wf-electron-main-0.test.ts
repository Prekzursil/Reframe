// buildProxyJob.wf-electron-main-0.test.ts — the WU B3 proxy-build bridge extracted
// from main.ts into sidecar.ts so its job/exit lifecycle is unit-testable with the
// same fully-mocked fake-child harness the supervisor tests use. Headline invariant
// (the fix): a sidecar crash MID-BUILD rejects the build promise immediately instead
// of leaving it hung until the 60s request timeout (PlaybackProxy inflight wedge).
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// ---- spawn mock (mirrors sidecar.restart.test.ts) --------------------------

interface FakeChild extends EventEmitter {
  stdin: { write: ReturnType<typeof vi.fn> };
  stdout: EventEmitter & { setEncoding: ReturnType<typeof vi.fn> };
  stderr: EventEmitter & { setEncoding: ReturnType<typeof vi.fn> };
  kill: ReturnType<typeof vi.fn>;
  exitCode: number | null;
  killed: boolean;
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
  const kill = vi.fn(() => {
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

import { buildProxyJob, Sidecar } from './sidecar';

beforeEach(() => {
  spawnMock.mockReset();
  spawnMock.mockImplementation(() => makeChild());
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function lastChild(): FakeChild {
  return spawnMock.mock.results.at(-1)!.value as FakeChild;
}

/** Feed the `media.proxy.start` quick-ack `{jobId}` response for request id=1. */
function ackJob(child: FakeChild, jobId: string): void {
  child.stdout.emit('data', `${JSON.stringify({ jsonrpc: '2.0', id: 1, result: { jobId } })}\n`);
}

/** Emit a `job.done` notification carrying `result` for `jobId`. */
function emitDone(child: FakeChild, jobId: string, result: unknown): void {
  child.stdout.emit(
    'data',
    `${JSON.stringify({ jsonrpc: '2.0', method: 'job.done', params: { jobId, result } })}\n`,
  );
}

/** Build a started Sidecar with all non-'error' lifecycle events swallowed. */
function startedSidecar(): { sc: Sidecar; child: FakeChild } {
  const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
  sc.on('status', () => undefined);
  sc.on('error', () => undefined);
  sc.on('restart', () => undefined);
  sc.on('log', () => undefined);
  sc.start();
  return { sc, child: lastChild() };
}

describe('buildProxyJob', () => {
  it('resolves with the built proxy path when job.done carries a path', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve(); // let sc.request resolve and register onDone/onExit
    emitDone(child, 'j1', { path: '/proxy/v1.mp4' });
    await expect(p).resolves.toBe('/proxy/v1.mp4');
  });

  it('ignores a job.done for a DIFFERENT jobId, then settles on the matching one', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve();
    // A done for an unrelated job must NOT settle this build (the jobId guard).
    emitDone(child, 'other-job', { path: '/proxy/other.mp4' });
    let settled = false;
    void p.then(
      () => {
        settled = true;
      },
      () => {
        settled = true;
      },
    );
    await Promise.resolve();
    expect(settled).toBe(false);
    // The matching done now resolves it.
    emitDone(child, 'j1', { path: '/proxy/v1.mp4' });
    await expect(p).resolves.toBe('/proxy/v1.mp4');
  });

  it('rejects LOUDLY with the error message when job.done carries an error', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve();
    emitDone(child, 'j1', { error: { message: 'transcode failed: bad codec' } });
    await expect(p).rejects.toThrow('transcode failed: bad codec');
  });

  it('rejects with a generic message when the error payload has no message', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve();
    emitDone(child, 'j1', { error: {} });
    await expect(p).rejects.toThrow('proxy build failed for v1');
  });

  it('rejects when job.done finishes without a path', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve();
    emitDone(child, 'j1', undefined); // result absent -> no path
    await expect(p).rejects.toThrow('proxy build for v1 returned no path');
  });

  it('rejects when job.done carries an empty-string path', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve();
    emitDone(child, 'j1', { path: '' });
    await expect(p).rejects.toThrow('proxy build for v1 returned no path');
  });

  it('THE FIX: a sidecar crash MID-BUILD rejects immediately (no 60s hang)', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve(); // onDone/onExit now registered

    // The sidecar process dies before any job.done arrives. Timers are FAKE and we
    // never advance them, so a rejection can ONLY come from the 'exit' listener —
    // if the fix were absent (no onExit) this await would hang out to the test
    // timeout. Its prompt rejection proves the build settles immediately.
    child.fakeExit(137);

    await expect(p).rejects.toThrow('sidecar exited (code 137) during proxy build for v1');
  });

  it('formats a null exit code as "code null" on a crash mid-build', async () => {
    const { sc, child } = startedSidecar();
    const p = buildProxyJob(sc, 'v1');
    ackJob(child, 'j1');
    await Promise.resolve();
    child.fakeExit(null); // signal-kill -> code null
    await expect(p).rejects.toThrow('sidecar exited (code null) during proxy build for v1');
  });

  it('rejects the outer promise when media.proxy.start itself fails', async () => {
    const sc = new Sidecar({ python: 'py', pythonArgs: [], cwd: '/x' });
    sc.on('status', () => undefined);
    // Not started -> sc.request rejects synchronously ('sidecar is not running').
    await expect(buildProxyJob(sc, 'v1')).rejects.toThrow('sidecar is not running');
  });
});
