import * as os from 'node:os';
import * as path from 'node:path';
import { describe, expect, it } from 'vitest';
import { PathTraversalError, ensureWithinBase } from './jobPath';

// The render-CLI reads a JSON job file whose path arrives as `process.argv[2]`
// (see render.ts readJob) — an attacker-influenceable input for CodeQL's
// `js/path-injection`. `ensureWithinBase` is the confine-to-base sanitizer that
// canonicalises the path and proves it stays inside `os.tmpdir()` (where the
// Python side writes it via `tempfile.mkstemp`). These tests pin that barrier.
describe('ensureWithinBase', () => {
  const base = os.tmpdir();
  const baseReal = path.resolve(base);

  it('accepts a valid job path inside the system temp dir', () => {
    const jobPath = path.join(base, 'media_studio_remotion_job_abc123.json');
    expect(ensureWithinBase(jobPath)).toBe(path.resolve(jobPath));
  });

  it('accepts the base directory itself', () => {
    expect(ensureWithinBase(base)).toBe(baseReal);
  });

  it('rejects a path outside the base directory', () => {
    const outside = path.resolve(baseReal, '..', 'not-the-temp-dir', 'job.json');
    expect(() => ensureWithinBase(outside)).toThrow(PathTraversalError);
  });

  it('rejects parent-directory traversal that escapes the base', () => {
    // path.join collapses the `..` segments, so the ONLY thing that rejects this
    // is the resolve + startsWith confinement (not a literal `..` string match).
    const escaping = path.join(base, '..', '..', 'etc', 'passwd');
    expect(() => ensureWithinBase(escaping)).toThrow(/escapes allowed base/);
  });

  it('rejects a prefix-sibling directory (Temp2 must not match Temp)', () => {
    const sibling = `${baseReal}2${path.sep}job.json`;
    expect(() => ensureWithinBase(sibling)).toThrow(PathTraversalError);
  });

  it('confines against an explicit base argument', () => {
    const customBase = path.join(base, 'reframe-jobs');
    const inside = path.join(customBase, 'job.json');
    expect(ensureWithinBase(inside, customBase)).toBe(path.resolve(inside));
    expect(() => ensureWithinBase(path.join(base, 'other.json'), customBase)).toThrow(
      PathTraversalError,
    );
  });
});
