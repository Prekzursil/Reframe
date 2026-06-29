// exportPath.ts — pure scoped-path resolver for the `mstream://` resolver's
// id-prefix branches (WU-MAIN-IPC §6 / C10).
//
// The `dub:` (P2/T2) and `short:` (P4 §6) id forms encode an ABSOLUTE path
// after the prefix. We must only ever stream a file that lives INSIDE a declared
// root directory — otherwise the privileged media scheme would become an
// arbitrary-disk read primitive. This helper does the prefix-strip + canonical
// resolve + traversal-guard, extracted so the security boundary is unit-tested
// without an Electron app. Behavior is identical to the original inline `dub:`
// branch in main.ts.
import { resolve as resolvePath, sep } from 'node:path';
import { realpathSync } from 'node:fs';

/** Is `p` the canonical `root` itself, or strictly inside it? (lexical) */
function isContained(p: string, root: string): boolean {
  return p === root || p.startsWith(root + sep);
}

/**
 * Resolve a prefixed media id (`<prefix><absolute path>`) to the file path,
 * BUT only when that path is `root` itself or strictly inside `root`. Returns
 * null when the id lacks the prefix, or the resolved path escapes the root
 * (parent-traversal, sibling dir sharing the prefix string, or any other
 * location). `root` should already be a canonical absolute path.
 *
 * F3c (security hardening): a lexical containment check alone is insufficient —
 * a file (or directory) that is LEXICALLY inside the root can be a SYMLINK whose
 * real target lives OUTSIDE it, turning the privileged `mstream:` scheme into an
 * arbitrary-disk read primitive. So when the requested path ACTUALLY EXISTS, we
 * canonicalise it with ``realpath`` (which dereferences every symlink segment)
 * AND the root, then re-check containment — fail-closed (any realpath error =>
 * deny). A path that does NOT yet exist stays allowed on the lexical check alone
 * (a not-yet-written export 404s downstream); since realpath only runs on present
 * paths, this guard can never be abused to probe file existence.
 */
export function resolveScopedMediaPath(id: string, prefix: string, root: string): string | null {
  if (!id.startsWith(prefix)) return null;
  const requested = resolvePath(id.slice(prefix.length));
  if (!isContained(requested, root)) return null;
  // Symlink/realpath containment re-check (only when the path resolves on disk).
  try {
    const realRoot = realpathSync(root);
    const realPath = realpathSync(requested);
    if (!isContained(realPath, realRoot)) return null;
  } catch (err) {
    // ENOENT: the path (or root) isn't on disk yet — keep the lexical verdict
    // (the protocol handler 404s a missing file). Any OTHER realpath failure is
    // treated as fail-closed (deny) since we could not prove containment.
    if ((err as NodeJS.ErrnoException).code !== 'ENOENT') return null;
  }
  return requested;
}
