// Tests for the packaged first-run gate helpers (WIRING-T5 §2 provisioning
// hardening). These pin the decision logic that closes the half-provisioned
// silent-app trap: the supervisor runs bootstrap until a FULL provision marker
// exists, and never bricks a previously-working install on a re-provision fail.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import {
  FIRST_RUN_COMPLETE_MARKER,
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
