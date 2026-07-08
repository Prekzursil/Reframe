// rendererRecovery.test.ts — the pure decision/log helpers for main-process
// renderer crash + load-failure recovery (WU2 resilience). main.ts owns the
// Electron event wiring (a coverage-excluded IO seam); every DECISION + log
// string lives in rendererRecovery.ts, unit-tested to 100% here.
import { describe, it, expect } from 'vitest';
import {
  MAX_RENDERER_RELOADS,
  decideDidFailLoad,
  decideRenderProcessGone,
  describeUncaughtException,
  describeUnhandledRejection,
} from './rendererRecovery';

describe('decideRenderProcessGone', () => {
  it('does NOT reload a clean, intentional renderer exit', () => {
    const d = decideRenderProcessGone({ reason: 'clean-exit', exitCode: 0 }, 0);
    expect(d.reload).toBe(false);
    expect(d.log).toContain('no reload');
  });

  it('reloads once on a genuine crash while under the reload cap', () => {
    const d = decideRenderProcessGone({ reason: 'crashed', exitCode: 133 }, 0);
    expect(d.reload).toBe(true);
    expect(d.log).toContain('crashed');
    expect(d.log).toContain(`1/${MAX_RENDERER_RELOADS}`);
  });

  it('reloads on an OOM crash too (any non-clean reason)', () => {
    const d = decideRenderProcessGone({ reason: 'oom', exitCode: 0 }, MAX_RENDERER_RELOADS - 1);
    expect(d.reload).toBe(true);
  });

  it('stops reloading once the cap is reached (no reload storm)', () => {
    const d = decideRenderProcessGone({ reason: 'crashed', exitCode: 1 }, MAX_RENDERER_RELOADS);
    expect(d.reload).toBe(false);
    expect(d.log).toContain('reload limit');
  });
});

describe('decideDidFailLoad', () => {
  it('reloads a main-frame load failure with a real error code, under the cap', () => {
    const d = decideDidFailLoad(
      {
        errorCode: -6,
        errorDescription: 'ERR_FILE_NOT_FOUND',
        validatedURL: 'file:///index.html',
        isMainFrame: true,
      },
      0,
    );
    expect(d.reload).toBe(true);
    expect(d.log).toContain('reloading');
    expect(d.log).toContain('ERR_FILE_NOT_FOUND');
  });

  it('ignores the benign ERR_ABORTED (-3) superseded navigation', () => {
    const d = decideDidFailLoad(
      { errorCode: -3, errorDescription: 'ERR_ABORTED', validatedURL: 'x', isMainFrame: true },
      0,
    );
    expect(d.reload).toBe(false);
    expect(d.log).toContain('ignoring');
  });

  it('ignores a subframe load failure', () => {
    const d = decideDidFailLoad(
      {
        errorCode: -6,
        errorDescription: 'ERR_FILE_NOT_FOUND',
        validatedURL: 'x',
        isMainFrame: false,
      },
      0,
    );
    expect(d.reload).toBe(false);
  });

  it('stops reloading once the cap is reached', () => {
    const d = decideDidFailLoad(
      {
        errorCode: -6,
        errorDescription: 'ERR_FILE_NOT_FOUND',
        validatedURL: 'x',
        isMainFrame: true,
      },
      MAX_RENDERER_RELOADS,
    );
    expect(d.reload).toBe(false);
    expect(d.log).toContain('reload limit');
  });
});

describe('describeUncaughtException', () => {
  it('prefers the stack for an Error', () => {
    const err = new Error('kaboom');
    expect(describeUncaughtException(err)).toContain(err.stack as string);
    expect(describeUncaughtException(err)).toContain('kept alive');
  });

  it('falls back to the message when an Error has no stack', () => {
    const err = Object.assign(new Error('no-stack'), { stack: undefined });
    expect(describeUncaughtException(err)).toContain('no-stack');
  });

  it('stringifies a non-Error thrown value', () => {
    expect(describeUncaughtException('plain string')).toContain('plain string');
  });
});

describe('describeUnhandledRejection', () => {
  it('prefers the stack for an Error reason', () => {
    const err = new Error('rejected');
    expect(describeUnhandledRejection(err)).toContain(err.stack as string);
    expect(describeUnhandledRejection(err)).toContain('kept alive');
  });

  it('falls back to the message when an Error reason has no stack', () => {
    const err = Object.assign(new Error('no-stack-reason'), { stack: undefined });
    expect(describeUnhandledRejection(err)).toContain('no-stack-reason');
  });

  it('stringifies a non-Error rejection reason', () => {
    expect(describeUnhandledRejection(42)).toContain('42');
  });
});
