// Conformance test for the `batch.*` client/sidecar wire surface.
//
// THE CONTRACT: a typed client must never advertise an RPC method the backend
// cannot serve. `protocol.dispatch` raises METHOD_NOT_FOUND (-32601) for any
// method absent from the registry (sidecar/media_studio/protocol.py:182-184), so
// a `client.batch.*` wrapper with no matching `reg("batch.…")` in the sidecar is
// a latent trap: it type-checks, autocompletes, and fails only at runtime.
//
// It reads the REAL source files (not a copy) so adding a client wrapper without
// registering its handler fails the build. Mirrors the existing cross-boundary
// precedent in ../captionTemplates.conformance.test.ts. Runs in the default node
// environment (filesystem access, no jsdom).
//
// DIRECTION: the assertion is one-directional (client ⊆ sidecar) BY DESIGN. The
// sidecar legitimately may register a method the UI has no wrapper for yet; that
// is unfinished UI, not a lie. Only the reverse — the client promising what the
// backend cannot serve — is the defect class guarded here.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

// app/renderer/src/lib/rpc -> repo root is five levels up.
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..', '..', '..', '..');

const CLIENT_TS = resolve(HERE, 'client.ts');
const SIDECAR_BATCH_PY = resolve(REPO_ROOT, 'sidecar', 'media_studio', 'features', 'batch.py');

/**
 * Every `batch.*` method the typed client can put on the wire, parsed from the
 * `rpc('batch.…')` call literals in client.ts.
 */
function clientBatchMethods(): string[] {
  const src = readFileSync(CLIENT_TS, 'utf8');
  return [...src.matchAll(/\brpc\(\s*'(batch\.[A-Za-z0-9_]+)'/g)].map((m) => m[1]).sort();
}

/**
 * Every `batch.*` method the sidecar actually registers, parsed from the
 * `reg("batch.…", …)` calls in the batch feature's registration function.
 */
function sidecarBatchMethods(): string[] {
  const src = readFileSync(SIDECAR_BATCH_PY, 'utf8');
  return [...src.matchAll(/\breg\(\s*"(batch\.[A-Za-z0-9_]+)"/g)].map((m) => m[1]).sort();
}

describe('batch.* client/sidecar wire-surface conformance', () => {
  // Detector control (fail-closed): a regex that silently matches nothing would
  // make the real assertion below vacuously true. These two guards mean a broken
  // parser fails LOUDLY instead of certifying an empty set as conformant.
  it('parses a non-empty client surface (guards against a vacuous pass)', () => {
    expect(clientBatchMethods().length).toBeGreaterThan(0);
  });

  it('parses a non-empty sidecar surface (guards against a vacuous pass)', () => {
    expect(sidecarBatchMethods().length).toBeGreaterThan(0);
  });

  it('advertises no batch.* method the sidecar does not register', () => {
    const registered = new Set(sidecarBatchMethods());
    const unserveable = clientBatchMethods().filter((m) => !registered.has(m));
    expect(unserveable).toEqual([]);
  });
});
