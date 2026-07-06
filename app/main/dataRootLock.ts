// dataRootLock.ts — pure DATA-ROOT single-holder lock DECISION logic (WU-S1 +
// WU-S1-FIX).
//
// WHY this exists: `app.requestSingleInstanceLock()` (wired thin in main.ts) only
// mutually-excludes two launches of the SAME app copy (its lock lives in that
// copy's userData). But the DATA ROOT is RELOCATABLE (data-dir.txt) — two
// DIFFERENT Reframe installs can be pointed at the SAME data folder, and a second
// bootstrap/sidecar against that shared tree would race the first over the pip
// env build + library.db. So before spawning bootstrap/sidecar, main acquires a
// lockfile IN the resolved DATA_ROOT holding the owner's identity; a second copy
// that finds a LIVE holder must NOT spawn — it surfaces a loud "already using this
// data folder" message and starts aborted (no silent second bootstrap).
//
// WU-S1-FIX hardens three review findings:
//   * ATOMIC acquire (MEDIUM): the acquire is no longer a read->decide->write
//     TOCTOU. It exclusive-CREATES the lockfile (`createLock`, fs flag 'wx'); only
//     on EEXIST does it read+decide, and a stale holder is reclaimed (remove) then
//     re-created exclusively. Every held outcome is confirmed by READING THE RECORD
//     BACK and proving it is ours — so a copy that lost a write race refuses.
//   * CORROBORATED liveness (MEDIUM): pid-liveness alone falsely reads a REUSED pid
//     as a live holder (wedging the user out of their own folder). The record now
//     carries a per-BOOT id; a holder counts as LIVE only when its pid is alive AND
//     the boot id still matches — a pid reused after a reboot no longer corroborates.
//   * HOST guard (LOW): the record carries a HOST id. A holder on a DIFFERENT host
//     (a relocated/network data root) is NON-reclaimable — we cannot probe its
//     liveness, so we BLOCK rather than steal it.
//
// This module is the ELECTRON-FREE, fully-unit-tested decision core (the pure part
// held to 100% even though main/ is ungated): serialise/parse the lock record,
// decide acquire vs blocked vs stale-reclaim given an injected boot/liveness probe,
// and orchestrate the atomic acquire over an injected IO seam. The concrete
// FILESYSTEM/process seam (lockfile path, exclusive create, `process.kill(pid,0)`
// liveness, the boot id, the host id) is Electron-free wiring in dataRootLockIo.ts
// (tested there, mirroring dataRootIo.ts). Mirrors the dataRoot.ts / dataRootIo.ts
// (pure / IO) split.

/** The lockfile name; lives at the ROOT of the resolved DATA_ROOT. */
export const DATA_ROOT_LOCK_FILE = '.reframe-instance.lock';

/**
 * The IDENTITY of an acquiring process — everything needed to prove a lock record
 * is OURS and to corroborate another holder's liveness:
 *   - `pid`  : OS process id (necessary but NOT sufficient — pids are reused).
 *   - `boot` : a per-BOOT id (see {@link BootProbe}); a lock acquired on a previous
 *              boot no longer matches after a reboot, so a reused pid is not
 *              mistaken for the original holder.
 *   - `host` : the machine id; a holder on a DIFFERENT host is non-reclaimable.
 */
export interface LockOwner {
  readonly pid: number;
  readonly boot: number;
  readonly host: string;
}

/** The persisted lock record: the holder's identity plus its acquisition time. */
export interface LockRecord {
  /** OS process id of the holder. */
  readonly pid: number;
  /** Acquisition time (`Date.now()` ms epoch) — informational (staleness is by liveness). */
  readonly time: number;
  /** Per-boot id at acquisition — corroborates pid liveness (survives only same-boot). */
  readonly boot: number;
  /** Host id of the holder — a different-host holder is non-reclaimable. */
  readonly host: string;
}

/** Outcome of an acquire attempt. */
export interface LockDecision {
  /** True when the caller MAY hold the lock (it was free, already ours, or a dead holder was reclaimed). */
  readonly ok: boolean;
  /** The pid found in the existing lock record (whoever it was), or null when the lock was free. */
  readonly heldBy: number | null;
  /** True only when an existing lock whose holder is DEAD/reused was reclaimed (crash recovery). */
  readonly stale: boolean;
}

/**
 * OS boot/liveness probe: returns the holder pid's CURRENT per-boot id when the
 * pid is ALIVE, or `null` when it is not. Because a boot id is machine-global for a
 * given boot, "pid alive AND the returned boot id === the record's boot id" is true
 * exactly when the ORIGINAL holder is still running (within one boot a live pid is
 * unique). A pid reused after a reboot returns the NEW boot id, which no longer
 * matches — so the stale lock is reclaimed. Wired in dataRootLockIo.ts as
 * `isPidAlive(pid) ? BOOT_ID : null`.
 */
export type BootProbe = (pid: number) => number | null;

/** The filesystem seam {@link acquireDataRootLock} / {@link releaseDataRootLock} need. */
export interface LockIo {
  /**
   * ATOMICALLY create the lockfile with `body` (fs flag 'wx'). Returns true when we
   * created it (we now hold it), false when it ALREADY existed (EEXIST). Any other
   * IO error must throw (fail loud — a permission failure is not a silent no-lock).
   */
  createLock: (body: string) => boolean;
  /** Read the lockfile's raw contents, or undefined when absent/unreadable. */
  readLock: () => string | undefined;
  /** Overwrite the lockfile with the serialised lock record (creating the dir if needed). */
  writeLock: (body: string) => void;
  /** Delete the lockfile (best-effort; never throws for the caller). */
  removeLock: () => void;
}

/** Serialise a lock record to the on-disk body (stable JSON: pid + time + boot + host). */
export function serializeLock(record: LockRecord): string {
  return JSON.stringify({
    pid: record.pid,
    time: record.time,
    boot: record.boot,
    host: record.host,
  });
}

/** True for a usable OS pid: a finite, positive integer. */
function isValidPid(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

/** True for a finite number (used for `time` + `boot`). */
function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Parse a lockfile body into a {@link LockRecord}, or null when the body is absent,
 * not JSON, or missing/!valid `pid`/`time`/`boot`/`host`. A malformed lock is
 * treated as ABSENT (reclaimable) — that is documented lockfile crash-recovery, NOT
 * a silent fallback of a real feature: a corrupt lock must never wedge the app out
 * of its own data folder forever.
 */
export function parseLock(raw: string | undefined): LockRecord | null {
  if (typeof raw !== 'string' || raw.trim() === '') return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const { pid, time, boot, host } = parsed as {
    pid?: unknown;
    time?: unknown;
    boot?: unknown;
    host?: unknown;
  };
  if (!isValidPid(pid)) return null;
  if (!isFiniteNumber(time)) return null;
  if (!isFiniteNumber(boot)) return null;
  if (typeof host !== 'string' || host === '') return null;
  return { pid, time, boot, host };
}

/**
 * True when `record` was written by US — same pid AND same boot AND same host.
 * pid alone is insufficient (reused across boots), so the full identity is checked;
 * this is what makes a re-entrant refresh and a safe release recognise our own lock.
 */
function isSameOwner(record: LockRecord, owner: LockOwner): boolean {
  return record.pid === owner.pid && record.boot === owner.boot && record.host === owner.host;
}

/**
 * Decide, given the CURRENT lock record (already read + parsed) and OUR identity,
 * whether we may hold the lock:
 *
 *   - no lock (null)                 -> ok, heldBy null, not stale (free)
 *   - the lock is OURS               -> ok, heldBy us,   not stale (re-entrant refresh)
 *   - a DIFFERENT-HOST holder        -> BLOCKED, heldBy that pid, not stale (non-reclaimable)
 *   - a LIVE same-host holder        -> BLOCKED, heldBy that pid, not stale
 *   - a DEAD/reused-pid holder       -> ok, heldBy that pid, STALE (reclaimed after crash/reboot)
 *
 * "LIVE" requires BOTH the pid alive AND the boot id still matching (see
 * {@link BootProbe}) — corroborated liveness so a reused pid is not a false holder.
 * Pure — no IO (the boot/liveness probe is injected).
 */
export function decideLock(
  current: LockRecord | null,
  owner: LockOwner,
  probe: BootProbe,
): LockDecision {
  if (current === null) {
    return { ok: true, heldBy: null, stale: false };
  }
  if (isSameOwner(current, owner)) {
    return { ok: true, heldBy: current.pid, stale: false };
  }
  if (current.host !== owner.host) {
    // A holder on another machine (relocated/network root) — we cannot probe its
    // liveness, so never steal it. Block loudly.
    return { ok: false, heldBy: current.pid, stale: false };
  }
  const liveBoot = probe(current.pid);
  if (liveBoot !== null && liveBoot === current.boot) {
    return { ok: false, heldBy: current.pid, stale: false };
  }
  return { ok: true, heldBy: current.pid, stale: true };
}

/**
 * True when the lockfile is still OURS (full identity match), so releasing it is
 * safe. Guards against a released lock deleting a DIFFERENT live holder's record
 * (e.g. on the aborted path where we never acquired — the file holds the other
 * process's record, so we must leave it be).
 */
export function shouldReleaseLock(current: LockRecord | null, owner: LockOwner): boolean {
  return current !== null && isSameOwner(current, owner);
}

/**
 * READ-BACK verify: after we (exclusive-)create or overwrite the lockfile, prove the
 * on-disk record is OURS before treating the lock as held. This closes the residual
 * write race — if a concurrent copy overwrote between our write and this read, the
 * record is NOT ours, so we REFUSE (blocked) instead of two copies both believing
 * they hold the same folder.
 */
function confirmOwned(io: LockIo, owner: LockOwner, held: LockDecision): LockDecision {
  const readback = parseLock(io.readLock());
  if (readback !== null && isSameOwner(readback, owner)) {
    return held;
  }
  return { ok: false, heldBy: readback === null ? null : readback.pid, stale: false };
}

/**
 * ATOMICALLY acquire the DATA-ROOT lock for `owner`, returning the decision so the
 * caller can gate spawning bootstrap/the sidecar (ok) or surface the contention
 * message + start aborted (!ok):
 *
 *   1. exclusive-CREATE (fs 'wx'). Wins outright when the lock is FREE.
 *   2. on EEXIST: read + {@link decideLock}. A LIVE/different-host holder BLOCKS with
 *      no write. A holder that is OURS is refreshed in place. A STALE holder is
 *      RECLAIMED (remove) then re-created EXCLUSIVELY so two racers can't both win.
 *   3. every held path is {@link confirmOwned} (read-back verified) before it counts.
 */
export function acquireDataRootLock(
  io: LockIo,
  owner: LockOwner,
  now: number,
  probe: BootProbe,
): LockDecision {
  const body = serializeLock({ pid: owner.pid, time: now, boot: owner.boot, host: owner.host });

  // 1. FAST PATH — exclusive-create wins outright when the lock is FREE (no
  //    read->decide->write TOCTOU window).
  if (io.createLock(body)) {
    return confirmOwned(io, owner, { ok: true, heldBy: null, stale: false });
  }

  // 2. The lock already exists — read the current record + decide against it.
  const decision = decideLock(parseLock(io.readLock()), owner, probe);
  if (!decision.ok) {
    return decision; // LIVE (or different-host) holder — NEVER write; caller surfaces busy.
  }
  if (decision.stale) {
    // Dead/reboot-reused holder (same host): RECLAIM then RE-CREATE exclusively. If a
    // racer re-created between our remove + create, createLock returns false and
    // confirmOwned reads back THEIR record (not ours) -> blocked.
    io.removeLock();
    io.createLock(body);
    return confirmOwned(io, owner, decision);
  }
  // Already OURS (re-entrant refresh) — rewrite our record, then verify.
  io.writeLock(body);
  return confirmOwned(io, owner, decision);
}

/**
 * Release the lock on quit — but ONLY when it is still ours (see
 * {@link shouldReleaseLock}), so we never delete another live instance's lock.
 */
export function releaseDataRootLock(io: LockIo, owner: LockOwner): void {
  if (shouldReleaseLock(parseLock(io.readLock()), owner)) {
    io.removeLock();
  }
}
