// Tests for the packaged first-run gate helpers (WIRING-T5 §2 provisioning
// hardening). These pin the decision logic that closes the half-provisioned
// silent-app trap: the supervisor runs bootstrap until a FULL provision marker
// exists, and never bricks a previously-working install on a re-provision fail.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import {
  CORE_FIRST_RUN_ASSETS,
  classifyFirstRun,
  FIRST_RUN_COMPLETE_MARKER,
  FIRST_RUN_REQUIREMENTS_FINGERPRINT_FILE,
  fingerprintInSync,
  firstRunReadinessRollup,
  hashedLockFilename,
  isCoreFirstRunAsset,
  isProfileFirstRunComplete,
  needsFirstRunSetup,
  normalizeRequirements,
  requirementsFingerprint,
  shouldBackfillFingerprint,
  shouldStartSidecarAfterFailedFirstRun,
} from './firstRunGate';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const BOOTSTRAP_PY = resolve(REPO_ROOT, 'sidecar', 'runtime_setup', 'bootstrap.py');

describe('FIRST_RUN_COMPLETE_MARKER', () => {
  it('stays byte-identical to bootstrap.py FIRST_RUN_COMPLETE_MARKER', () => {
    // The supervisor reads the exact file bootstrap.py writes; a drift here
    // would make the gate check the wrong path and never see completion.
    const src = readFileSync(BOOTSTRAP_PY, 'utf8');
    const match = src.match(/FIRST_RUN_COMPLETE_MARKER\s*=\s*"([^"]+)"/);
    expect(match?.[1]).toBe(FIRST_RUN_COMPLETE_MARKER);
  });
});

describe('CORE_FIRST_RUN_ASSETS — the marker means CORE-ONLY (WU C3)', () => {
  // SEMANTIC contract: the FIRST_RUN_COMPLETE marker attests env + ffmpeg + the
  // always-on face/ASD weights, NOT "every model + weights". These assertions
  // pin that bootstrap.py gates the marker on exactly the face/ASD weights and
  // EXCLUDES the on-demand GGUFs — the flip from the old env+every-model gate.
  const src = readFileSync(BOOTSTRAP_PY, 'utf8');
  const coreFn = src.match(/def core_first_run_assets\(\)[\s\S]*?\n    return \[([\s\S]*?)\]/);
  const coreBody = coreFn?.[1] ?? '';

  it('is exactly the always-on YuNet + S3FD + LR-ASD weights', () => {
    expect([...CORE_FIRST_RUN_ASSETS]).toEqual([
      'yunet-face-detection',
      'lightasd-s3fd',
      'lightasd-asd',
    ]);
  });

  it("bootstrap.py's CORE set gates on the face/ASD weights, not every model", () => {
    // The marker is written after verify_provisioned over core_first_run_assets()
    // — which references the face/ASD manifest constants and NONE of the GGUFs.
    expect(coreBody).toContain('YUNET_ASSET_NAME');
    expect(coreBody).toContain('LIGHTASD_S3FD_ASSET_NAME');
    expect(coreBody).toContain('LIGHTASD_ASD_ASSET_NAME');
    // on-demand GGUFs must NOT gate the marker (they live OUTSIDE it).
    expect(coreBody).not.toContain('QWEN_ASSET_NAME');
    expect(coreBody).not.toContain('WHISPER_ASSET_NAME');
  });

  it('gates the marker on the CORE subset of the run, not the full ensured set', () => {
    // The write-condition narrows verification to core_first_run_assets(): a
    // failed on-demand model can no longer block the marker (the old bug).
    expect(src).toMatch(/core_names\s*=\s*\[\s*n\s+for\s+n\s+in\s+asset_names\s+if\s+n\s+in\s+core_first_run_assets\(\)\s*\]/);
    expect(src).toContain('verify_provisioned(core_names, root)');
    expect(src).toContain('write_first_run_complete(root, core_names)');
  });
});

describe('isCoreFirstRunAsset', () => {
  it('is true for the always-on face/ASD weights', () => {
    expect(isCoreFirstRunAsset('yunet-face-detection')).toBe(true);
    expect(isCoreFirstRunAsset('lightasd-asd')).toBe(true);
  });

  it('is false for on-demand GGUFs / voices / saliency', () => {
    expect(isCoreFirstRunAsset('qwen3-4b-gguf')).toBe(false);
    expect(isCoreFirstRunAsset('vinet-s-saliency')).toBe(false);
  });
});

describe('firstRunReadinessRollup — point-of-use per-asset readiness', () => {
  it('marks a missing on-demand asset needs-download, not setup-incomplete', () => {
    const rollup = firstRunReadinessRollup(
      ['yunet-face-detection', 'qwen3-4b-gguf'],
      ['yunet-face-detection'],
    );
    expect(rollup).toEqual([
      { asset: 'yunet-face-detection', present: true, kind: 'core', status: 'ready' },
      { asset: 'qwen3-4b-gguf', present: false, kind: 'on-demand', status: 'needs-download' },
    ]);
  });

  it('marks a missing CORE weight needs-download (the reframe floor)', () => {
    const [item] = firstRunReadinessRollup(['lightasd-asd'], []);
    expect(item).toEqual({
      asset: 'lightasd-asd',
      present: false,
      kind: 'core',
      status: 'needs-download',
    });
  });

  it('is empty for an empty asset list', () => {
    expect(firstRunReadinessRollup([], ['yunet-face-detection'])).toEqual([]);
  });
});

describe('isProfileFirstRunComplete — per-profile completion signal', () => {
  it('a Minimum install (no core pledged) is provisioned once the env exists', () => {
    // The core of the WU: a Minimum/Custom profile with NO optional models is
    // considered PROVISIONED — it must not perpetually re-run bootstrap.
    expect(isProfileFirstRunComplete(true, [], [])).toBe(true);
  });

  it('is NOT complete before the env is built, even with weights present', () => {
    expect(isProfileFirstRunComplete(false, CORE_FIRST_RUN_ASSETS, [])).toBe(false);
  });

  it('a Default install needs every pledged CORE face/ASD weight present', () => {
    expect(isProfileFirstRunComplete(true, CORE_FIRST_RUN_ASSETS, CORE_FIRST_RUN_ASSETS)).toBe(
      true,
    );
    // one weight missing -> not complete (leaves no marker -> retry).
    expect(
      isProfileFirstRunComplete(true, ['yunet-face-detection', 'lightasd-s3fd'], CORE_FIRST_RUN_ASSETS),
    ).toBe(false);
  });

  it('ignores on-demand names in the pledged set (they never gate completion)', () => {
    // A missing on-demand GGUF does not hold up completion.
    expect(
      isProfileFirstRunComplete(true, ['yunet-face-detection', 'lightasd-s3fd', 'lightasd-asd'], [
        ...CORE_FIRST_RUN_ASSETS,
        'qwen3-4b-gguf',
      ]),
    ).toBe(true);
  });
});

describe('needsFirstRunSetup', () => {
  it('runs bootstrap on a packaged build with no completion marker', () => {
    expect(needsFirstRunSetup(true, false)).toBe(true);
  });

  it('skips bootstrap once the full-provision marker exists', () => {
    expect(needsFirstRunSetup(true, true)).toBe(false);
  });

  it('never runs bootstrap in dev (unpackaged), marker or not', () => {
    expect(needsFirstRunSetup(false, false)).toBe(false);
    expect(needsFirstRunSetup(false, true)).toBe(false);
  });

  it('re-runs bootstrap when the marker exists but the fingerprint drifted (WU-S2)', () => {
    // The insurance path: an auto-update changed the sidecar requirements, so the
    // persisted fingerprint no longer matches -> re-provision instead of stale.
    expect(needsFirstRunSetup(true, true, false)).toBe(true);
  });

  it('stays skipped when the marker exists and the fingerprint is in sync', () => {
    expect(needsFirstRunSetup(true, true, true)).toBe(false);
  });

  it('ignores a fingerprint drift in dev (unpackaged never bootstraps)', () => {
    expect(needsFirstRunSetup(false, true, false)).toBe(false);
  });
});

describe('normalizeRequirements — the dependency-set signal (WU-S2)', () => {
  it('drops blank lines and full-line + inline comments, then sorts', () => {
    expect(
      normalizeRequirements('# header\n\nnumpy==2.5.0\nhttpx==0.28.1  # pinned\n   \n'),
    ).toEqual(['httpx==0.28.1', 'numpy==2.5.0']);
  });

  it('is order-independent (reordering the file does not change the set)', () => {
    expect(normalizeRequirements('b==2\na==1')).toEqual(normalizeRequirements('a==1\nb==2'));
  });
});

describe('requirementsFingerprint — stable version hash (WU-S2)', () => {
  const base = 'numpy==2.5.0\nhttpx==0.28.1\n';

  it('is a 64-char sha256 hex digest', () => {
    expect(requirementsFingerprint(base)).toMatch(/^[0-9a-f]{64}$/);
  });

  it('is deterministic for the same requirements', () => {
    expect(requirementsFingerprint(base)).toBe(requirementsFingerprint(base));
  });

  it('is insensitive to comment / whitespace / reorder churn', () => {
    const churned = '# a note\nhttpx==0.28.1   # inline\nnumpy==2.5.0\n\n';
    expect(requirementsFingerprint(churned)).toBe(requirementsFingerprint(base));
  });

  it('CHANGES when a pin is bumped (the drift trigger)', () => {
    expect(requirementsFingerprint('numpy==2.5.1\nhttpx==0.28.1\n')).not.toBe(
      requirementsFingerprint(base),
    );
  });

  it('CHANGES when a dependency is added', () => {
    expect(requirementsFingerprint(`${base}av==17.1.0\n`)).not.toBe(requirementsFingerprint(base));
  });
});

describe('hashedLockFilename — the active install source (WU-S2-FIX)', () => {
  it('maps the loose sidecar requirements to its sibling hashed lock', () => {
    // The packaged env installs from the lock (`pip --require-hashes`) when it is
    // staged, so the drift fingerprint must hash THAT, not the loose .txt.
    expect(hashedLockFilename('requirements-sidecar.txt')).toBe('requirements-sidecar.lock.txt');
  });

  it('is the TS mirror of bootstrap.py hashed_lock_path', () => {
    // Cross-file parity: bootstrap.py derives the lock via
    // `p.with_name(f"{p.stem}.lock.txt")`. A drift here would fingerprint a
    // different file than the env is actually installed from.
    const src = readFileSync(BOOTSTRAP_PY, 'utf8');
    expect(src).toContain('p.with_name(f"{p.stem}.lock.txt")');
  });

  it('drops only the FINAL extension before appending .lock.txt (mirrors Path.stem)', () => {
    expect(hashedLockFilename('requirements-chatterbox.txt')).toBe(
      'requirements-chatterbox.lock.txt',
    );
  });

  it('handles a filename with no extension (stem is the whole name)', () => {
    expect(hashedLockFilename('requirements')).toBe('requirements.lock.txt');
  });
});

describe('fingerprintInSync — persisted vs shipped (WU-S2)', () => {
  it('is in sync when the persisted fingerprint equals the shipped one', () => {
    expect(fingerprintInSync('abc', 'abc')).toBe(true);
  });

  it('is OUT of sync when they differ (an update changed the env)', () => {
    expect(fingerprintInSync('old', 'new')).toBe(false);
  });

  it('treats a missing (null) persisted fingerprint as in sync (legacy marker)', () => {
    // A pre-feature install must NOT be forced into a surprise re-bootstrap.
    expect(fingerprintInSync(null, 'new')).toBe(true);
  });
});

describe('shouldBackfillFingerprint — arm drift-detection for legacy installs (WU-S2)', () => {
  it('backfills when a marker exists but no fingerprint was persisted', () => {
    expect(shouldBackfillFingerprint(true, null)).toBe(true);
  });

  it('does not backfill when a fingerprint is already persisted', () => {
    expect(shouldBackfillFingerprint(true, 'abc')).toBe(false);
  });

  it('does not backfill with no marker (first-ever bootstrap writes it on success)', () => {
    expect(shouldBackfillFingerprint(false, null)).toBe(false);
  });
});

describe('classifyFirstRun — the single first-run decision point (WU-S2)', () => {
  it('is `none` in dev regardless of marker / fingerprint state', () => {
    expect(classifyFirstRun(false, false, false)).toBe('none');
    expect(classifyFirstRun(false, true, false)).toBe('none');
  });

  it('is `first-ever` (interactive) on a packaged build with no marker', () => {
    expect(classifyFirstRun(true, false, true)).toBe('first-ever');
    // the fingerprint is irrelevant with no marker — nothing is provisioned yet.
    expect(classifyFirstRun(true, false, false)).toBe('first-ever');
  });

  it('is `re-bootstrap` (silent) when the marker exists but the fingerprint drifted', () => {
    expect(classifyFirstRun(true, true, false)).toBe('re-bootstrap');
  });

  it('is `none` when the marker exists and the fingerprint is in sync', () => {
    expect(classifyFirstRun(true, true, true)).toBe('none');
  });
});

describe('FIRST_RUN_REQUIREMENTS_FINGERPRINT_FILE', () => {
  it('is a hidden sibling of the completion marker at the data root', () => {
    expect(FIRST_RUN_REQUIREMENTS_FINGERPRINT_FILE).toBe('.first-run-requirements.json');
    // sibling of, but DISTINCT from, the CORE-floor marker.
    expect(FIRST_RUN_REQUIREMENTS_FINGERPRINT_FILE).not.toBe(FIRST_RUN_COMPLETE_MARKER);
  });
});

describe('shouldStartSidecarAfterFailedFirstRun', () => {
  it('starts the existing env degraded when a prior env sentinel exists', () => {
    expect(shouldStartSidecarAfterFailedFirstRun(true)).toBe(true);
  });

  it('stays down on a truly empty first run (nothing installed to start)', () => {
    expect(shouldStartSidecarAfterFailedFirstRun(false)).toBe(false);
  });
});
