// exportPath.test.ts — the pure scoped-path resolver behind the `short:` and
// `dub:` mstream resolver branches (WU-MAIN-IPC §6 / C10). Pure (no Electron),
// runs in node env. The traversal guard is the security-critical bit: a
// `short:`/`dub:` id may only resolve to a path INSIDE the declared root.
import { describe, it, expect } from 'vitest';
import { resolve as resolvePath, sep } from 'node:path';
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
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

  // WU-3 (ux-qol): the `thumb:` branch serves library posters under
  // DATA_ROOT/thumbnails. It is prefix-agnostic so it reuses this exact helper —
  // the security boundary is identical to short:/dub: (a poster id may only ever
  // resolve to a path INSIDE the thumbnails root).
  describe('thumb: branch (library posters)', () => {
    const thumbsRoot = resolvePath('/tmp/media-studio/thumbnails');

    it('resolves a poster strictly inside the thumbnails root', () => {
      const inside = resolvePath(thumbsRoot, 'vid1.jpg');
      expect(resolveScopedMediaPath(`thumb:${inside}`, 'thumb:', thumbsRoot)).toBe(inside);
    });

    it('allows the thumbnails root itself', () => {
      expect(resolveScopedMediaPath(`thumb:${thumbsRoot}`, 'thumb:', thumbsRoot)).toBe(thumbsRoot);
    });

    it('returns null for a parent-traversal escape out of the thumbnails root', () => {
      const escape = `${thumbsRoot}${sep}..${sep}escape.jpg`;
      expect(resolveScopedMediaPath(`thumb:${escape}`, 'thumb:', thumbsRoot)).toBeNull();
    });

    it('returns null for a sibling dir sharing the thumbnails prefix string', () => {
      const sibling = `${thumbsRoot}-evil${sep}vid1.jpg`;
      expect(resolveScopedMediaPath(`thumb:${sibling}`, 'thumb:', thumbsRoot)).toBeNull();
    });

    it('returns null for an absolute path elsewhere on disk', () => {
      const elsewhere = resolvePath('/etc/passwd');
      expect(resolveScopedMediaPath(`thumb:${elsewhere}`, 'thumb:', thumbsRoot)).toBeNull();
    });

    it('returns null for a missing-prefix id', () => {
      const inside = resolvePath(thumbsRoot, 'vid1.jpg');
      expect(resolveScopedMediaPath(inside, 'thumb:', thumbsRoot)).toBeNull();
    });
  });

  // F3c: realpath/symlink containment re-check. A lexical containment guard alone
  // is bypassable: a file INSIDE the root can be a symlink pointing OUTSIDE it
  // (the privileged media scheme would then leak arbitrary disk). The resolver
  // canonicalises with realpath and re-checks containment, fail-closed.
  describe('symlink / realpath containment (F3c)', () => {
    it('allows a real (non-symlink) file inside the canonical root', () => {
      const base = realpathSync(mkdtempSync(join(tmpdir(), 'mstream-rp-')));
      const root = join(base, 'exports');
      mkdirSync(root);
      const real = join(root, 'clip.mp4');
      writeFileSync(real, 'x');
      expect(resolveScopedMediaPath(`short:${real}`, 'short:', root)).toBe(real);
    });

    it('rejects a symlink INSIDE the root that escapes to a sibling outside it', () => {
      const base = realpathSync(mkdtempSync(join(tmpdir(), 'mstream-rp-')));
      const root = join(base, 'exports');
      mkdirSync(root);
      const secret = join(base, 'secret.mp4');
      writeFileSync(secret, 'top-secret');
      const link = join(root, 'leak.mp4');
      try {
        symlinkSync(secret, link);
      } catch {
        // Windows without symlink privilege: skip (the guard is still exercised
        // by the missing-target case below and on CI/Linux).
        return;
      }
      // Lexically `link` is inside root, but its realpath is the outside secret.
      expect(resolveScopedMediaPath(`short:${link}`, 'short:', root)).toBeNull();
    });

    it('passes a lexically-contained path that does not exist (realpath check only fires when present)', () => {
      // A non-existent-but-contained path stays allowed lexically (the protocol
      // handler then 404s the missing file). The realpath escape-check only
      // engages for paths that actually resolve on disk, so it cannot be used to
      // probe file existence and never breaks the not-yet-written-export case.
      const base = realpathSync(mkdtempSync(join(tmpdir(), 'mstream-rp-')));
      const root = join(base, 'exports');
      mkdirSync(root);
      const ghost = join(root, 'does-not-exist.mp4');
      expect(resolveScopedMediaPath(`short:${ghost}`, 'short:', root)).toBe(ghost);
    });

    it('rejects a symlinked DIRECTORY inside the root that escapes (segment-level symlink)', () => {
      const base = realpathSync(mkdtempSync(join(tmpdir(), 'mstream-rp-')));
      const root = join(base, 'exports');
      mkdirSync(root);
      const outsideDir = join(base, 'outside');
      mkdirSync(outsideDir);
      writeFileSync(join(outsideDir, 'f.mp4'), 'x');
      const linkDir = join(root, 'sub');
      try {
        symlinkSync(outsideDir, linkDir, 'dir');
      } catch {
        return; // no symlink privilege -> skip
      }
      // root/sub/f.mp4 is lexically inside root but realpath escapes via the dir symlink.
      expect(resolveScopedMediaPath(`short:${join(linkDir, 'f.mp4')}`, 'short:', root)).toBeNull();
    });

    it('allows the root itself when it exists on disk', () => {
      const base = realpathSync(mkdtempSync(join(tmpdir(), 'mstream-rp-')));
      const root = join(base, 'exports');
      mkdirSync(root);
      expect(resolveScopedMediaPath(`short:${root}`, 'short:', root)).toBe(root);
    });
  });
});
