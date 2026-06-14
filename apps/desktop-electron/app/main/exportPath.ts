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

/**
 * Resolve a prefixed media id (`<prefix><absolute path>`) to the file path,
 * BUT only when that path is `root` itself or strictly inside `root`. Returns
 * null when the id lacks the prefix, or the resolved path escapes the root
 * (parent-traversal, sibling dir sharing the prefix string, or any other
 * location). `root` should already be a canonical absolute path.
 */
export function resolveScopedMediaPath(
  id: string,
  prefix: string,
  root: string,
): string | null {
  if (!id.startsWith(prefix)) return null;
  const requested = resolvePath(id.slice(prefix.length));
  return requested === root || requested.startsWith(root + sep) ? requested : null;
}
