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
  serializeLock,
  shouldReleaseLock,
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
 * A LockIo fake backed by an in-memory cell so acquire/release round-trip.
 * `createLock` is EXCLUSIVE: it fails (false) when a body already exists (EEXIST).
 */
function makeIo(initial?: string): LockIo & { body: string | undefined } {
  const state = { body: initial };
  return {
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
  };
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
    expect(
      decideLock({ pid: 100, time: 1, boot: 5000, host: 'hostA' }, OWNER, probe),
    ).toEqual({ ok: true, heldBy: 100, stale: false });
    expect(probe).not.toHaveBeenCalled();
  });

  it('DIFFERENT-host holder -> blocked, not stale (non-reclaimable, never probes)', () => {
    const probe = vi.fn(bootOf(5000));
    expect(
      decideLock({ pid: 200, time: 1, boot: 5000, host: 'hostB' }, OWNER, probe),
    ).toEqual({ ok: false, heldBy: 200, stale: false });
    expect(probe).not.toHaveBeenCalled();
  });

  it('LIVE same-host holder (pid alive AND boot matches) -> blocked, not stale', () => {
    expect(
      decideLock({ pid: 200, time: 1, boot: 5000, host: 'hostA' }, OWNER, bootOf(5000)),
    ).toEqual({ ok: false, heldBy: 200, stale: false });
  });

  it('DEAD holder (probe null) -> ok (reclaim), heldBy that pid, stale', () => {
    expect(
      decideLock({ pid: 200, time: 1, boot: 5000, host: 'hostA' }, OWNER, dead),
    ).toEqual({ ok: true, heldBy: 200, stale: true });
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
    expect(io.writeLock).toHaveBeenCalledWith(
      '{"pid":100,"time":5000,"boot":5000,"host":"hostA"}',
    );
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

  it('STALE holder -> reclaims (remove) + re-creates exclusively, verifies ours', () => {
    const io = makeIo('{"pid":200,"time":1,"boot":5000,"host":"hostA"}');
    const decision = acquireDataRootLock(io, OWNER, 5000, dead);
    expect(decision).toEqual({ ok: true, heldBy: 200, stale: true });
    expect(io.removeLock).toHaveBeenCalledTimes(1);
    expect(parseLock(io.body)).toEqual({ pid: 100, time: 5000, boot: 5000, host: 'hostA' });
  });

  it('STALE but LOST the reclaim race -> read-back is the racer, refuse (blocked)', () => {
    // A racer re-created the lock between our remove + create: createLock is EEXIST
    // on BOTH attempts, and the read-back returns the racer's LIVE record.
    const stale = '{"pid":200,"time":1,"boot":5000,"host":"hostA"}';
    const racer = '{"pid":300,"time":9,"boot":5000,"host":"hostA"}';
    const io: LockIo = {
      createLock: vi.fn(() => false),
      readLock: vi.fn().mockReturnValueOnce(stale).mockReturnValue(racer),
      writeLock: vi.fn(),
      removeLock: vi.fn(),
    };
    const decision = acquireDataRootLock(io, OWNER, 5000, dead);
    expect(decision).toEqual({ ok: false, heldBy: 300, stale: false });
    expect(io.removeLock).toHaveBeenCalledTimes(1);
    expect(io.writeLock).not.toHaveBeenCalled();
  });

  it('read-back MISSING after create -> refuse (blocked, heldBy null)', () => {
    // createLock claimed success but the record is gone on read-back (a concurrent
    // copy deleted it): we must NOT treat the lock as held.
    const io: LockIo = {
      createLock: vi.fn(() => true),
      readLock: vi.fn(() => undefined),
      writeLock: vi.fn(),
      removeLock: vi.fn(),
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
