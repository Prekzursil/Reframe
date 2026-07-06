// Tests for dataRootLock — the pure DATA-ROOT single-holder lock decision core
// (WU-S1). Every branch is exercised: serialise round-trip, parse (absent / blank
// / non-JSON / non-object / bad-pid / bad-time / valid), decide (free / ours /
// live-other / dead-reclaim), shouldRelease (none / ours / other), and the
// acquire/release orchestration over an injected LockIo (write-on-ok, no-write-on-
// blocked, remove-only-when-ours). The module is Electron-free, so no mocks of
// node:fs are needed — the IO seam + liveness probe are plain injected fakes.
import { describe, expect, it, vi } from 'vitest';
import {
  acquireDataRootLock,
  DATA_ROOT_LOCK_FILE,
  decideLock,
  type LockIo,
  type LockRecord,
  parseLock,
  releaseDataRootLock,
  serializeLock,
  shouldReleaseLock,
} from './dataRootLock';

const alwaysAlive = (): boolean => true;
const alwaysDead = (): boolean => false;

/** A LockIo fake backed by an in-memory cell so acquire/release round-trip. */
function makeIo(initial: string | undefined): LockIo & { body: string | undefined } {
  const state = { body: initial };
  return {
    get body() {
      return state.body;
    },
    readLock: vi.fn(() => state.body),
    writeLock: vi.fn((body: string) => {
      state.body = body;
    }),
    removeLock: vi.fn(() => {
      state.body = undefined;
    }),
  };
}

describe('DATA_ROOT_LOCK_FILE', () => {
  it('is a hidden dotfile name for the data root', () => {
    expect(DATA_ROOT_LOCK_FILE).toBe('.reframe-instance.lock');
  });
});

describe('serializeLock / parseLock round-trip', () => {
  it('serialises pid + time to stable JSON and parses back', () => {
    const record: LockRecord = { pid: 4321, time: 1_700_000_000_000 };
    const body = serializeLock(record);
    expect(body).toBe('{"pid":4321,"time":1700000000000}');
    expect(parseLock(body)).toEqual(record);
  });
});

describe('parseLock rejects', () => {
  it('undefined -> null', () => {
    expect(parseLock(undefined)).toBeNull();
  });

  it('blank / whitespace-only -> null', () => {
    expect(parseLock('   ')).toBeNull();
  });

  it('non-JSON text -> null', () => {
    expect(parseLock('not json {')).toBeNull();
  });

  it('JSON that is not an object (array) -> null', () => {
    expect(parseLock('[1,2,3]')).toBeNull();
  });

  it('JSON null literal -> null', () => {
    expect(parseLock('null')).toBeNull();
  });

  it('missing/invalid pid (non-integer) -> null', () => {
    expect(parseLock('{"pid":1.5,"time":1}')).toBeNull();
  });

  it('non-positive pid -> null', () => {
    expect(parseLock('{"pid":0,"time":1}')).toBeNull();
  });

  it('non-number pid -> null', () => {
    expect(parseLock('{"pid":"123","time":1}')).toBeNull();
  });

  it('missing/invalid time (non-finite) -> null', () => {
    expect(parseLock('{"pid":123}')).toBeNull();
  });

  it('non-number time -> null', () => {
    expect(parseLock('{"pid":123,"time":"x"}')).toBeNull();
  });
});

describe('decideLock', () => {
  it('free (no current lock) -> ok, heldBy null, not stale', () => {
    expect(decideLock(null, 100, alwaysAlive)).toEqual({ ok: true, heldBy: null, stale: false });
  });

  it('lock is OURS -> ok, heldBy us, not stale (never probes liveness)', () => {
    const isAlive = vi.fn(alwaysDead);
    expect(decideLock({ pid: 100, time: 1 }, 100, isAlive)).toEqual({
      ok: true,
      heldBy: 100,
      stale: false,
    });
    expect(isAlive).not.toHaveBeenCalled();
  });

  it('LIVE other holder -> blocked, heldBy that pid, not stale', () => {
    expect(decideLock({ pid: 200, time: 1 }, 100, alwaysAlive)).toEqual({
      ok: false,
      heldBy: 200,
      stale: false,
    });
  });

  it('DEAD holder -> ok (reclaim), heldBy that pid, stale', () => {
    expect(decideLock({ pid: 200, time: 1 }, 100, alwaysDead)).toEqual({
      ok: true,
      heldBy: 200,
      stale: true,
    });
  });
});

describe('shouldReleaseLock', () => {
  it('no current lock -> false', () => {
    expect(shouldReleaseLock(null, 100)).toBe(false);
  });

  it('lock is ours -> true', () => {
    expect(shouldReleaseLock({ pid: 100, time: 1 }, 100)).toBe(true);
  });

  it('lock is another process -> false', () => {
    expect(shouldReleaseLock({ pid: 200, time: 1 }, 100)).toBe(false);
  });
});

describe('acquireDataRootLock', () => {
  it('writes our record when the lock is free', () => {
    const io = makeIo(undefined);
    const decision = acquireDataRootLock(io, 777, 1234, alwaysAlive);
    expect(decision).toEqual({ ok: true, heldBy: null, stale: false });
    expect(io.writeLock).toHaveBeenCalledWith('{"pid":777,"time":1234}');
    expect(parseLock(io.body)).toEqual({ pid: 777, time: 1234 });
  });

  it('reclaims + overwrites a DEAD holder (stale)', () => {
    const io = makeIo('{"pid":200,"time":1}');
    const decision = acquireDataRootLock(io, 777, 5000, alwaysDead);
    expect(decision).toEqual({ ok: true, heldBy: 200, stale: true });
    expect(parseLock(io.body)).toEqual({ pid: 777, time: 5000 });
  });

  it('does NOT write when a LIVE other holder blocks acquisition', () => {
    const io = makeIo('{"pid":200,"time":1}');
    const decision = acquireDataRootLock(io, 777, 5000, alwaysAlive);
    expect(decision).toEqual({ ok: false, heldBy: 200, stale: false });
    expect(io.writeLock).not.toHaveBeenCalled();
    expect(io.body).toBe('{"pid":200,"time":1}');
  });
});

describe('releaseDataRootLock', () => {
  it('removes the lock when it is still ours', () => {
    const io = makeIo('{"pid":777,"time":1}');
    releaseDataRootLock(io, 777);
    expect(io.removeLock).toHaveBeenCalledTimes(1);
    expect(io.body).toBeUndefined();
  });

  it('leaves a DIFFERENT holder’s lock untouched', () => {
    const io = makeIo('{"pid":200,"time":1}');
    releaseDataRootLock(io, 777);
    expect(io.removeLock).not.toHaveBeenCalled();
    expect(io.body).toBe('{"pid":200,"time":1}');
  });

  it('no-ops when there is no lock to release', () => {
    const io = makeIo(undefined);
    releaseDataRootLock(io, 777);
    expect(io.removeLock).not.toHaveBeenCalled();
  });
});
