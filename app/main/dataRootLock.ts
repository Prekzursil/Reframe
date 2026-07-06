// dataRootLock.ts — pure DATA-ROOT single-holder lock DECISION logic (WU-S1).
//
// WHY this exists: `app.requestSingleInstanceLock()` (wired thin in main.ts) only
// mutually-excludes two launches of the SAME app copy (its lock lives in that
// copy's userData). But the DATA ROOT is RELOCATABLE (data-dir.txt) — two
// DIFFERENT Reframe installs can be pointed at the SAME data folder, and a second
// bootstrap/sidecar against that shared tree would race the first over the pip
// env build + library.db. So before spawning bootstrap/sidecar, main acquires a
// lockfile IN the resolved DATA_ROOT holding the owner's pid; a second copy that
// finds a LIVE holder must NOT spawn — it surfaces a loud "already using this data
// folder" message and starts aborted (no silent second bootstrap).
//
// This module is the ELECTRON-FREE, fully-unit-tested decision core (the pure part
// held to 100% even though main/ is ungated): serialise/parse the lock record,
// decide acquire vs blocked vs stale-reclaim given an injected liveness probe, and
// decide release. The concrete FILESYSTEM seam (lockfile path, read/write/unlink,
// `process.kill(pid,0)` liveness) is thin wiring in main.ts — it injects `LockIo`
// + `isAlive` here. Mirrors the dataRoot.ts (pure) / dataRootIo.ts (IO) split.

/** The lockfile name; lives at the ROOT of the resolved DATA_ROOT. */
export const DATA_ROOT_LOCK_FILE = '.reframe-instance.lock';

/** The persisted lock record: who holds it (pid) and when it was acquired (ms epoch). */
export interface LockRecord {
  /** OS process id of the holder. */
  readonly pid: number;
  /** Acquisition time (`Date.now()` ms epoch) — informational (staleness is by pid liveness). */
  readonly time: number;
}

/** Outcome of an acquire attempt. */
export interface LockDecision {
  /** True when the caller MAY hold the lock (it was free, already ours, or a dead holder was reclaimed). */
  readonly ok: boolean;
  /** The pid found in the existing lock record (whoever it was), or null when the lock was free. */
  readonly heldBy: number | null;
  /** True only when an existing lock whose holder is DEAD was reclaimed (crash recovery). */
  readonly stale: boolean;
}

/** The filesystem seam {@link acquireDataRootLock} / {@link releaseDataRootLock} need. */
export interface LockIo {
  /** Read the lockfile's raw contents, or undefined when absent/unreadable. */
  readLock: () => string | undefined;
  /** Write the serialised lock record (creating the data root dir if needed). */
  writeLock: (body: string) => void;
  /** Delete the lockfile (best-effort; never throws for the caller). */
  removeLock: () => void;
}

/** Serialise a lock record to the on-disk body (stable JSON: pid + time). */
export function serializeLock(record: LockRecord): string {
  return JSON.stringify({ pid: record.pid, time: record.time });
}

/** True for a usable OS pid: a finite, positive integer. */
function isValidPid(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

/**
 * Parse a lockfile body into a {@link LockRecord}, or null when the body is
 * absent, not JSON, or missing/!valid `pid`/`time`. A malformed lock is treated
 * as ABSENT (reclaimable) — that is documented lockfile crash-recovery, NOT a
 * silent fallback of a real feature: a corrupt lock must never wedge the app out
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
  const { pid, time } = parsed as { pid?: unknown; time?: unknown };
  if (!isValidPid(pid)) return null;
  if (typeof time !== 'number' || !Number.isFinite(time)) return null;
  return { pid, time };
}

/**
 * Decide, given the CURRENT lock record (already read + parsed) and our pid,
 * whether we may hold the lock:
 *
 *   - no lock (null)            -> ok, heldBy null, not stale (free)
 *   - the lock is OURS          -> ok, heldBy us,   not stale (re-entrant refresh)
 *   - a LIVE other holder       -> BLOCKED, heldBy that pid, not stale
 *   - a DEAD holder             -> ok, heldBy that pid, STALE (reclaimed after crash)
 *
 * `isAlive(pid)` is the injected OS liveness probe (main.ts: `process.kill(pid,0)`).
 * Pure — no IO, no time dependency (staleness is by liveness, not a TTL).
 */
export function decideLock(
  current: LockRecord | null,
  pid: number,
  isAlive: (pid: number) => boolean,
): LockDecision {
  if (current === null) {
    return { ok: true, heldBy: null, stale: false };
  }
  if (current.pid === pid) {
    return { ok: true, heldBy: current.pid, stale: false };
  }
  if (isAlive(current.pid)) {
    return { ok: false, heldBy: current.pid, stale: false };
  }
  return { ok: true, heldBy: current.pid, stale: true };
}

/**
 * True when the lockfile is still OURS (its pid === our pid), so releasing it is
 * safe. Guards against a released lock deleting a DIFFERENT live holder's record
 * (e.g. on the aborted path where we never acquired — the file holds the other
 * process's pid, so we must leave it be).
 */
export function shouldReleaseLock(current: LockRecord | null, pid: number): boolean {
  return current !== null && current.pid === pid;
}

/**
 * Read the current lock, decide, and — when we may hold it — WRITE our record
 * (pid + `now`). Returns the decision so the caller can gate spawning bootstrap/
 * the sidecar (ok) or surface the contention message + start aborted (!ok).
 */
export function acquireDataRootLock(
  io: LockIo,
  pid: number,
  now: number,
  isAlive: (pid: number) => boolean,
): LockDecision {
  const current = parseLock(io.readLock());
  const decision = decideLock(current, pid, isAlive);
  if (decision.ok) {
    io.writeLock(serializeLock({ pid, time: now }));
  }
  return decision;
}

/**
 * Release the lock on quit — but ONLY when it is still ours (see
 * {@link shouldReleaseLock}), so we never delete another live instance's lock.
 */
export function releaseDataRootLock(io: LockIo, pid: number): void {
  if (shouldReleaseLock(parseLock(io.readLock()), pid)) {
    io.removeLock();
  }
}
