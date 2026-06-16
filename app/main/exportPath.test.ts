// exportPath.test.ts — the pure scoped-path resolver behind the `short:` and
// `dub:` mstream resolver branches (WU-MAIN-IPC §6 / C10). Pure (no Electron),
// runs in node env. The traversal guard is the security-critical bit: a
// `short:`/`dub:` id may only resolve to a path INSIDE the declared root.
import { describe, it, expect } from 'vitest';
import { resolve as resolvePath, sep } from 'node:path';
import { resolveScopedMediaPath } from './exportPath';

const ROOT = resolvePath('/tmp/media-studio/exports');

describe('resolveScopedMediaPath', () => {
  it('returns null when the id lacks the prefix', () => {
    expect(resolveScopedMediaPath('abc123', 'short:', ROOT)).toBeNull();
    expect(resolveScopedMediaPath('dub:/x', 'short:', ROOT)).toBeNull();
  });

  it('resolves a path inside the root', () => {
    const inside = resolvePath(ROOT, 'shorts-vid1', 'clip.mp4');
    expect(resolveScopedMediaPath(`short:${inside}`, 'short:', ROOT)).toBe(inside);
  });

  it('allows the root itself', () => {
    expect(resolveScopedMediaPath(`short:${ROOT}`, 'short:', ROOT)).toBe(ROOT);
  });

  it('rejects a parent-traversal escape (../) out of the root', () => {
    const escape = `${ROOT}${sep}..${sep}secret.mp4`;
    expect(resolveScopedMediaPath(`short:${escape}`, 'short:', ROOT)).toBeNull();
  });

  it('rejects a sibling directory that shares the root prefix string', () => {
    // `exports-evil` starts with `exports` but is NOT inside `exports/`.
    const sibling = `${ROOT}-evil${sep}clip.mp4`;
    expect(resolveScopedMediaPath(`short:${sibling}`, 'short:', ROOT)).toBeNull();
  });

  it('rejects an absolute path elsewhere on disk', () => {
    const elsewhere = resolvePath('/etc/passwd');
    expect(resolveScopedMediaPath(`short:${elsewhere}`, 'short:', ROOT)).toBeNull();
  });

  it('works for an arbitrary prefix (the dub: branch shares this helper)', () => {
    const dubsRoot = resolvePath('/tmp/media-studio/dubs');
    const inside = resolvePath(dubsRoot, 'v.wav');
    expect(resolveScopedMediaPath(`dub:${inside}`, 'dub:', dubsRoot)).toBe(inside);
    expect(resolveScopedMediaPath(`dub:${resolvePath('/x.wav')}`, 'dub:', dubsRoot)).toBeNull();
  });
});
