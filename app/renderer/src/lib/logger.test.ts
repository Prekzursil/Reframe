import { afterEach, describe, expect, it, vi } from 'vitest';
import { logWarn } from './logger';

describe('logger.logWarn', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('routes a warning (with details) through console.warn', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const err = new Error('boom');
    logWarn('feedback.record failed (ignored)', err);
    expect(warn).toHaveBeenCalledWith('feedback.record failed (ignored)', err);
  });

  it('logs a bare message with no details', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    logWarn('just a message');
    expect(warn).toHaveBeenCalledWith('just a message');
  });
});
