// Tests for dataRootLock — the pure DATA-ROOT single-holder lock decision core
// (WU-S1 + WU-S1-FIX). Every branch is exercised: serialise round-trip, parse
// (absent / blank / non-JSON / non-object / bad-pid / bad-time / bad-boot / bad-host
// / valid), decide (free / ours / different-host-blocked / live-blocked /
// dead-reclaim / reused-pid-reclaim), shouldRelease (none / ours / other-pid /
// other-boot / other-host), the ATOMIC acquire (free-fast-create / ours-refresh /
// live-blocked / different-host-blocked / stale-reclaim / lost-reclaim-race /
// read-back-verify-refuses), and release (ours / other / none). The module is
// Electron-free, so the IO seam + boot/liveness probe are plain injected fakes.
import { describe, expect, it, vi } from 'vitest';
import {
  acquireDataRootLock,
  type BootProbe,
  DATA_ROOT_LOCK_FILE,
  decideLock,
  type LockIo,
  type LockOwner,
  type LockRecord,
  parseLock,
  releaseDataRootLock,
  releaseDataRootLockAfter,
  serializeLock,
  shouldReleaseLock,
  staleSidelineSuffix,
} from './dataRootLock';

/** Our identity throughout: pid 100, boot id 5000, host "hostA". */
const OWNER: LockOwner = { pid: 100, boot: 5000, host: 'hostA' };

/** A boot/liveness probe that reports a live pid with the given boot id. */
const bootOf =
  (bootId: number): BootProbe =>
  () =>
    bootId;
/** A probe that reports every pid as DEAD (no live boot id). */
const dead: BootProbe = () => null;

/**
 * A LockIo fake backed by an in-memory "volume" so acquire/release round-trip.
 * `createLock` is EXCLUSIVE: it fails (false) when a body already exists (EEXIST).
 * `reclaimLock` models the seam's create-exclusive sideline move: the sideline name
 * can be claimed exactly ONCE, so a second racer targeting the SAME dead record
 * loses (this is what makes the stale reclaim single-winner).
 */
function makeVolume(initial?: string): {
  io: LockIo & { body: string | undefined };
  sidelines: Set<string>;
} {
  const state = { body: initial };
  const sidelines = new Set<string>();
  const io = {
    get body() {
      return state.body;
    },
    createLock: vi.fn((body: string) => {
      if (state.body !== undefined) return false; // EEXIST
      state.body = body;
      return true;
    }),
    readLock: vi.fn(() => state.body),
    writeLock: vi.fn((body: string) => {
      state.body = body;
    }),
    removeLock: vi.fn(() => {
      state.body = undefined;
    }),
    reclaimLock: vi.fn((suffix: string) => {
      if (sidelines.has(suffix)) return false; // EEXIST — another racer won
      if (state.body === undefined) return false; // nothing to move aside
      sidelines.add(suffix);
      state.body = undefined; // moved aside: the lock path is free for 'wx'
      return true;
    }),
  };
  return { io, sidelines };
}

/** The common case: just the fake IO. */
function makeIo(initial?: string): LockIo & { body: string | undefined } {
  return makeVolume(initial).io;
}

const ourRecord = (): string =>
  serializeLock({ pid: OWNER.pid, time: 1, boot: OWNER.boot, host: OWNER.host });

describe('DATA_ROOT_LOCK_FILE', () => {
  it('is a hidden dotfile name for the data root', () => {
    expect(DATA_ROOT_LOCK_FILE).toBe('.reframe-instance.lock');
  });
});

describe('serializeLock / parseLock round-trip', () => {
  it('serialises pid + time + boot + host to stable JSON and parses back', () => {
    const record: LockRecord = { pid: 4321, time: 1_700_000_000_000, boot: 5000, host: 'hostA' };
    const body = serializeLock(record);
    expect(body).toBe('{"pid":4321,"time":1700000000000,"boot":5000,"host":"hostA"}');
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
    expect(parseLock('{"pid":1.5,"time":1,"boot":2,"host":"h"}')).toBeNull();
  });

  it('non-positive pid -> null', () => {
    expect(parseLock('{"pid":0,"time":1,"boot":2,"host":"h"}')).toBeNull();
  });

  it('non-number pid -> null', () => {
    expect(parseLock('{"pid":"123","time":1,"boot":2,"host":"h"}')).toBeNull();
  });

  it('missing/invalid time (non-finite) -> null', () => {
    expect(parseLock('{"pid":123,"boot":2,"host":"h"}')).toBeNull();
  });

  it('non-number time -> null', () => {
    expect(parseLock('{"pid":123,"time":"x","boot":2,"host":"h"}')).toBeNull();
  });

  it('missing/invalid boot (non-finite) -> null', () => {
    expect(parseLock('{"pid":123,"time":1,"host":"h"}')).toBeNull();
  });

  it('non-number boot -> null', () => {
    expect(parseLock('{"pid":123,"time":1,"boot":"x","host":"h"}')).toBeNull();
  });

  it('missing host -> null', () => {
    expect(parseLock('{"pid":123,"time":1,"boot":2}')).toBeNull();
  });

  it('empty-string host -> null', () => {
    expect(parseLock('{"pid":123,"time":1,"boot":2,"host":""}')).toBeNull();
  });

  it('non-string host -> null', () => {
    expect(parseLock('{"pid":123,"time":1,"boot":2,"host":5}')).toBeNull();
  });
});

describe('decideLock', () => {
  it('free (no current lock) -> ok, heldBy null, not stale', () => {
    expect(decideLock(null, OWNER, bootOf(5000))).toEqual({
      ok: true,
      heldBy: null,
      stale: false,
    });
  });

  it('lock is OURS -> ok, heldBy us, not stale (never probes liveness)', () => {
    const probe = vi.fn(bootOf(1));
    expect(decideLock({ pid: 100, time: 1, boot: 5000, host: 'hostA' }, OWNER, probe)).toEqual({
      ok: true,
      heldBy: 100,
      stale: false,
    });
    expect(probe).not.toHaveBeenCalled();
  });

  it('DIFFERENT-host holder -> blocked, not stale (non-reclaimable, never probes)', () => {
    const probe = vi.fn(bootOf(5000));
    expect(decideLock({ pid: 200, time: 1, boot: 5000, host: 'hostB' }, OWNER, probe)).toEqual({
      ok: false,
      heldBy: 200,
      stale: false,
    });
    expect(probe).not.toHaveBeenCalled();
  });

  it('LIVE same-host holder (pid alive AND boot matches) -> blocked, not stale', () => {
    expect(
      decideLock({ pid: 200, time: 1, boot: 5000, host: 'hostA' }, OWNER, bootOf(5000)),
    ).toEqual({ ok: false, heldBy: 200, stale: false });
  });

  it('DEAD holder (probe null) -> ok (reclaim), heldBy that pid, stale', () => {
    expect(decideLock({ pid: 200, time: 1, boot: 5000, host: 'hostA' }, OWNER, dead)).toEqual({
      ok: true,
      heldBy: 200,
      stale: true,
    });
  });

  it('REUSED pid (alive but boot id differs) -> ok (reclaim), stale', () => {
    // pid 200 is alive, but on a DIFFERENT boot (9999) than the record (5000):
    // a reused pid after a reboot must NOT count as the original live holder.
    expect(
      decideLock({ pid: 200, time: 1, boot: 5000, host: 'hostA' }, OWNER, bootOf(9999)),
    ).toEqual({ ok: true, heldBy: 200, stale: true });
  });
});

describe('shouldReleaseLock', () => {
  it('no current lock -> false', () => {
    expect(shouldReleaseLock(null, OWNER)).toBe(false);
  });

  it('lock is ours (pid + boot + host match) -> true', () => {
    expect(shouldReleaseLock({ pid: 100, time: 1, boot: 5000, host: 'hostA' }, OWNER)).toBe(true);
  });

  it('another pid -> false', () => {
    expect(shouldReleaseLock({ pid: 200, time: 1, boot: 5000, host: 'hostA' }, OWNER)).toBe(false);
  });

  it('same pid but a different boot (a stale prior-boot lock) -> false', () => {
    expect(shouldReleaseLock({ pid: 100, time: 1, boot: 1, host: 'hostA' }, OWNER)).toBe(false);
  });

  it('same pid but a different host -> false', () => {
    expect(shouldReleaseLock({ pid: 100, time: 1, boot: 5000, host: 'hostB' }, OWNER)).toBe(false);
  });
});

describe('staleSidelineSuffix', () => {
  it('is keyed to the VICTIM record (pid + boot), not to the reclaimer', () => {
    expect(staleSidelineSuffix({ pid: 200, time: 1, boot: 5000, host: 'hostA' })).toBe(
      '.stale-200-5000',
    );
  });

  it('two racers reclaiming the SAME dead record derive the SAME sideline name', () => {
    // That identity is what lets the IO seam elect exactly one winner (create-excl).
    const victim: LockRecord = { pid: 42, time: 7, boot: 900, host: 'hostA' };
    expect(staleSidelineSuffix(victim)).toBe(staleSidelineSuffix({ ...victim, time: 999 }));
  });

  it('a DIFFERENT dead record gets a different sideline name', () => {
    expect(staleSidelineSuffix({ pid: 200, time: 1, boot: 5000, host: 'hostA' })).not.toBe(
      staleSidelineSuffix({ pid: 200, time: 1, boot: 6000, host: 'hostA' }),
    );
  });
});

describe('acquireDataRootLock', () => {
  it('FREE: exclusive-creates + read-back verifies our record', () => {
    const io = makeIo(undefined);
    const decision = acquireDataRootLock(io, OWNER, 1234, dead);
    expect(decision).toEqual({ ok: true, heldBy: null, stale: false });
    expect(io.createLock).toHaveBeenCalledWith(
      '{"pid":100,"time":1234,"boot":5000,"host":"hostA"}',
    );
    expect(io.writeLock).not.toHaveBeenCalled();
    expect(parseLock(io.body)).toEqual({ pid: 100, time: 1234, boot: 5000, host: 'hostA' });
  });

  it('OURS: re-entrant refresh overwrites in place (create EEXIST -> writeLock)', () => {
    const io = makeIo(ourRecord());
    const decision = acquireDataRootLock(io, OWNER, 5000, bootOf(1));
    expect(decision).toEqual({ ok: true, heldBy: 100, stale: false });
    expect(io.writeLock).toHaveBeenCalledWith('{"pid":100,"time":5000,"boot":5000,"host":"hostA"}');
    expect(parseLock(io.body)).toEqual({ pid: 100, time: 5000, boot: 5000, host: 'hostA' });
  });

  it('LIVE other holder -> blocked, never writes or removes', () => {
    const io = makeIo('{"pid":200,"time":1,"boot":5000,"host":"hostA"}');
    const decision = acquireDataRootLock(io, OWNER, 5000, bootOf(5000));
    expect(decision).toEqual({ ok: false, heldBy: 200, stale: false });
    expect(io.writeLock).not.toHaveBeenCalled();
    expect(io.removeLock).not.toHaveBeenCalled();
    expect(io.body).toBe('{"pid":200,"time":1,"boot":5000,"host":"hostA"}');
  });

  it('DIFFERENT-host holder -> blocked, untouched', () => {
    const io = makeIo('{"pid":200,"time":1,"boot":5000,"host":"hostB"}');
    const decision = acquireDataRootLock(io, OWNER, 5000, bootOf(5000));
    expect(decision).toEqual({ ok: false, heldBy: 200, stale: false });
    expect(io.removeLock).not.toHaveBeenCalled();
  });

  it('STALE holder -> reclaims by SIDELINE MOVE (never a bare unlink) + re-creates', () => {
    const { io, sidelines } = makeVolume('{"pid":200,"time":1,"boot":5000,"host":"hostA"}');
    const decision = acquireDataRootLock(io, OWNER, 5000, dead);
    expect(decision).toEqual({ ok: true, heldBy: 200, stale: true });
    // The dead record was moved aside under a name keyed to the VICTIM's identity…
    expect(io.reclaimLock).toHaveBeenCalledWith('.stale-200-5000');
    expect([...sidelines]).toEqual(['.stale-200-5000']);
    // …and NEVER deleted outright (a bare unlink can also destroy a RACER's lock).
    expect(io.removeLock).not.toHaveBeenCalled();
    expect(parseLock(io.body)).toEqual({ pid: 100, time: 5000, boot: 5000, host: 'hostA' });
  });

  it('STALE but LOST the sideline race -> creates NOTHING and refuses (blocked)', () => {
    // Another racer already moved the same dead record aside, so our reclaim is
    // EEXIST. We must not create a lock at all: the read-back returns THEIR record.
    const stale = '{"pid":200,"time":1,"boot":5000,"host":"hostA"}';
    const racer = '{"pid":300,"time":9,"boot":5000,"host":"hostA"}';
    const io: LockIo = {
      createLock: vi.fn(() => false),
      readLock: vi.fn().mockReturnValueOnce(stale).mockReturnValue(racer),
      writeLock: vi.fn(),
      removeLock: vi.fn(),
      reclaimLock: vi.fn(() => false),
    };
    const decision = acquireDataRootLock(io, OWNER, 5000, dead);
    expect(decision).toEqual({ ok: false, heldBy: 300, stale: false });
    expect(io.reclaimLock).toHaveBeenCalledTimes(1);
    expect(io.createLock).toHaveBeenCalledTimes(1); // only the opening fast-path try
    expect(io.writeLock).not.toHaveBeenCalled();
    expect(io.removeLock).not.toHaveBeenCalled();
  });

  it('the lock VANISHES between our failed create and our read -> refresh + verify', () => {
    // createLock said EEXIST but the record is gone by the time we read it (the
    // holder released in that window). decideLock sees "free"; we write + verify.
    const io = makeIo(undefined);
    vi.mocked(io.createLock).mockImplementationOnce(() => false);
    const decision = acquireDataRootLock(io, OWNER, 7, dead);
    expect(decision).toEqual({ ok: true, heldBy: null, stale: false });
    expect(io.writeLock).toHaveBeenCalledTimes(1);
    expect(io.reclaimLock).not.toHaveBeenCalled();
    expect(parseLock(io.body)).toEqual({ pid: 100, time: 7, boot: 5000, host: 'hostA' });
  });

  it('TOCTOU REGRESSION: two copies racing a STALE lock -> exactly ONE owns it', () => {
    // THE BUG the sideline move closes. Both copies read the SAME dead record and
    // both decide "stale". Under the old read-unlink-create reclaim, the SECOND
    // copy's unconditional `removeLock()` deleted the FIRST copy's freshly-created
    // record, then created its own — and each passed its own read-back, so BOTH
    // believed they owned the data root and both spawned a sidecar against it.
    const STALE = '{"pid":200,"time":1,"boot":5000,"host":"hostA"}';
    const { io, sidelines } = makeVolume(STALE);
    const copyA: LockOwner = { pid: 100, boot: 5000, host: 'hostA' };
    const copyB: LockOwner = { pid: 101, boot: 5000, host: 'hostA' };

    // Copy A completes its whole acquire first.
    const a = acquireDataRootLock(io, copyA, 10, dead);

    // Copy B decided from the STALE record it read BEFORE A ran (the racy read),
    // and only now performs its reclaim/create against the CURRENT volume.
    const bIo: LockIo = { ...io, readLock: vi.fn(() => io.body) };
    vi.mocked(bIo.readLock).mockReturnValueOnce(STALE);
    const b = acquireDataRootLock(bIo, copyB, 11, dead);

    expect(a.ok).toBe(true);
    expect(b.ok).toBe(false); // B is REFUSED — it must not spawn a second sidecar
    expect([a.ok, b.ok].filter(Boolean)).toHaveLength(1);
    // A's record still owns the folder; B's identity never reached the lockfile.
    expect(parseLock(io.body)).toEqual({ pid: 100, time: 10, boot: 5000, host: 'hostA' });
    // Both racers targeted the SAME victim-keyed sideline; only one could claim it.
    expect([...sidelines]).toEqual(['.stale-200-5000']);
  });

  it('read-back MISSING after create -> refuse (blocked, heldBy null)', () => {
    // createLock claimed success but the record is gone on read-back (a concurrent
    // copy deleted it): we must NOT treat the lock as held.
    const io: LockIo = {
      createLock: vi.fn(() => true),
      readLock: vi.fn(() => undefined),
      writeLock: vi.fn(),
      removeLock: vi.fn(),
      reclaimLock: vi.fn(() => false),
    };
    expect(acquireDataRootLock(io, OWNER, 1, dead)).toEqual({
      ok: false,
      heldBy: null,
      stale: false,
    });
  });

  it('read-back is ANOTHER owner after create -> refuse (blocked, heldBy that pid)', () => {
    // A concurrent copy overwrote our record between our create + read-back.
    const io: LockIo = {
      createLock: vi.fn(() => true),
      readLock: vi.fn(() => '{"pid":200,"time":1,"boot":5000,"host":"hostB"}'),
      writeLock: vi.fn(),
      removeLock: vi.fn(),
      reclaimLock: vi.fn(() => false),
    };
    expect(acquireDataRootLock(io, OWNER, 1, dead)).toEqual({
      ok: false,
      heldBy: 200,
      stale: false,
    });
  });
});

describe('releaseDataRootLock', () => {
  it('removes the lock when it is still ours', () => {
    const io = makeIo(ourRecord());
    releaseDataRootLock(io, OWNER);
    expect(io.removeLock).toHaveBeenCalledTimes(1);
    expect(io.body).toBeUndefined();
  });

  it('leaves a DIFFERENT holder’s lock untouched', () => {
    const io = makeIo('{"pid":200,"time":1,"boot":5000,"host":"hostA"}');
    releaseDataRootLock(io, OWNER);
    expect(io.removeLock).not.toHaveBeenCalled();
    expect(io.body).toBe('{"pid":200,"time":1,"boot":5000,"host":"hostA"}');
  });

  it('no-ops when there is no lock to release', () => {
    const io = makeIo(undefined);
    releaseDataRootLock(io, OWNER);
    expect(io.removeLock).not.toHaveBeenCalled();
  });
});

// --------------------------------------------------------------------------- #
// T8: the lock used to be released FIRST in will-quit, while the bootstrap/sidecar
// process tree was still being torn down — so a new instance could acquire the
// folder and start a SECOND sidecar against a live environment (racing library.db
// and the pip env). The release must be strictly LAST.
// --------------------------------------------------------------------------- #
describe('releaseDataRootLockAfter — release LAST, never before the tree is gone', () => {
  it('does NOT release while teardown is still pending, then releases once it settles', async () => {
    const io = makeIo(ourRecord());
    let finishTeardown = (): void => {};
    const teardown = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishTeardown = resolve;
        }),
    );

    const pending = releaseDataRootLockAfter(teardown, io, OWNER);
    await Promise.resolve();
    // The process tree has NOT exited yet — the lock MUST still be held.
    expect(io.removeLock).not.toHaveBeenCalled();
    expect(io.body).toBe(ourRecord());

    finishTeardown();
    await pending;

    expect(io.removeLock).toHaveBeenCalledTimes(1);
    expect(io.body).toBeUndefined();
  });

  it('still releases when teardown REJECTS (a wedged sidecar must not leak the lock)', async () => {
    const io = makeIo(ourRecord());
    await expect(
      releaseDataRootLockAfter(() => Promise.reject(new Error('kill failed')), io, OWNER),
    ).resolves.toBeUndefined();
    expect(io.removeLock).toHaveBeenCalledTimes(1);
  });

  it('still honours the ownership guard — a DIFFERENT holder’s lock is left alone', async () => {
    const io = makeIo('{"pid":200,"time":1,"boot":5000,"host":"hostA"}');
    await releaseDataRootLockAfter(() => Promise.resolve(), io, OWNER);
    expect(io.removeLock).not.toHaveBeenCalled();
  });
});
