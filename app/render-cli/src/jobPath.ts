/**
 * Path-confinement barrier for the render-CLI job file (js/path-injection).
 *
 * `readJob` in render.ts reads a JSON job file whose path arrives as
 * `process.argv[2]` — an attacker-influenceable input as far as static analysis
 * is concerned. The packaged Electron app writes that file with Python's
 * `tempfile.mkstemp(...)` (see sidecar/media_studio/features/caption_remotion.py),
 * i.e. into the system temp directory, which is exactly what Node's `os.tmpdir()`
 * returns for the same process tree. So the job path must be canonicalised and
 * PROVEN to stay inside `os.tmpdir()` before the read; callers use the RETURN
 * VALUE at the sink.
 *
 * This is the TypeScript analog of the sidecar's `pathsafe.ensure_within`.
 * CodeQL's `js/path-injection` recognises a barrier shaped as: a value
 * normalised by `path.resolve` that is then the receiver of a `String.startsWith`
 * check against a non-tainted base prefix, with the protected use on the True
 * branch. `ensureWithinBase` implements exactly that shape, so the taint is
 * neutralised here and every caller that uses the returned path is sanitised
 * interprocedurally. `path.relative` / `commonPath`-style checks are deliberately
 * avoided — `path.resolve` + `startsWith` is the shape the query models.
 */
import * as os from 'node:os';
import * as path from 'node:path';

export class PathTraversalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PathTraversalError';
  }
}

/**
 * Return the canonical (`path.resolve`d) form of `rawPath`, proven to live inside
 * `base` (default: the system temp dir). Throws {@link PathTraversalError} when
 * the resolved path escapes `base` — an absolute path on another root, `..`
 * traversal, or a prefix-sibling (`…/Temp2` must not match `…/Temp`).
 */
export function ensureWithinBase(rawPath: string, base: string = os.tmpdir()): string {
  const baseReal = path.resolve(base);
  const target = path.resolve(rawPath);
  // CodeQL js/path-injection barrier: the `path.resolve`-normalised `target` is
  // the DIRECT receiver of a `startsWith` check against the resolved base, with
  // the protected use (the return) on the True branch. Keeping `startsWith` as
  // the OUTER guard is what makes the barrier recognised. The second clause
  // admits the base dir itself (exact length) and a base that is a filesystem
  // root (already ends in a separator), while still rejecting the prefix-sibling
  // escape (the char right after the base must be the path separator).
  if (
    target.startsWith(baseReal) &&
    (baseReal.endsWith(path.sep) ||
      target.length === baseReal.length ||
      target[baseReal.length] === path.sep)
  ) {
    return target;
  }
  throw new PathTraversalError(`job path ${rawPath} escapes allowed base ${baseReal}`);
}
