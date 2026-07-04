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
  FIRST_RUN_COMPLETE_MARKER,
  firstRunReadinessRollup,
  isCoreFirstRunAsset,
  isProfileFirstRunComplete,
  needsFirstRunSetup,
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
});

describe('shouldStartSidecarAfterFailedFirstRun', () => {
  it('starts the existing env degraded when a prior env sentinel exists', () => {
    expect(shouldStartSidecarAfterFailedFirstRun(true)).toBe(true);
  });

  it('stays down on a truly empty first run (nothing installed to start)', () => {
    expect(shouldStartSidecarAfterFailedFirstRun(false)).toBe(false);
  });
});
