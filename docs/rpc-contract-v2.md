# RPC Contract v2 — schema-first, generated (v1.5 KEYSTONE)

Status: **design + proof-of-concept** (this PR). Not merged; not yet load-bearing.
Migration plan: [`rpc-contract-v2-migration.md`](./rpc-contract-v2-migration.md).

## 1. The problem — one contract, hand-mirrored in 7 places that drift

Reframe's JSON-RPC contract (~123 methods) has **no single source of truth**. The
same method name, its params, its result, and its "needs a provider key" flag are
re-typed by hand across at least seven surfaces, and nothing keeps them in sync:

| # | Surface (file) | What it hand-maintains | Failure mode when it drifts |
|---|---|---|---|
| 1 | `app/renderer/src/lib/rpc/client.ts` | 123 hand-written `rpc('name', {...})` call sites | a renamed/retyped method compiles but calls a dead wire name |
| 2 | `sidecar/media_studio/handlers/composition.py` | ~120 `reg("name", handler)` registrations | a method exists on one side only; no cross-check |
| 3 | `CONTRACTS.md` | ~40 methods, marked "FROZEN" | **already stale** — describes 40 of 123; §0 even says "no keystore / no consent" while both now exist |
| 4 | `app/renderer/src/lib/rpc/schemas.ts` | 1235 hand-maintained lines of TS types | a field renamed on the Python side silently diverges from TS |
| 5 | `app/main/keyBridge.ts:61-88` | the `needsKeyInjection` allowlist (4 prefixes + 10 exact names) | **silent key omission** — a new provider-calling method not added here gets no key → cloud silently degrades to local |
| 6 | `sidecar/media_studio/settings_store.py` | `DEFAULT_SETTINGS: dict[str, Any]` + every `settings.get("k")` read | untyped: a wrong key returns `None` with zero signal |
| 7 | `sidecar/media_studio/features/shortmaker.py` | `settings: dict[str, Any]`, e.g. `settings.get("silenceTrimm")` | a typo returns `None` → the feature silently no-ops |

The through-line: **the contract is data, but it is expressed as hand-copied code
in six languages/locations.** Every one of the seven is a place a human must
remember to edit in lock-step. That is the definition of drift-prone.

## 2. The decision — a stdlib-typed Python contract module, JSON Schema as interchange

**One source of truth: a typed Python module (`sidecar/contract/spec.py`) built
from `dataclasses`.** It declares, in one place per method: the wire name, the
params model, the result type, the `needs_key` flag, and the job/direct kind; plus
the shared data models (`Video`, `Settings`, …) as dataclasses. A generator
(`sidecar/contract/generate.py`) emits **every** other representation from it.

The neutral interchange artifact is **JSON Schema** (draft-2020-12 subset), emitted
by introspecting the dataclasses. The Python side validates params against it; the
TypeScript side is rendered from the same field walk.

### Why this format (and not the alternatives)

| Option | Verdict | Reason |
|---|---|---|
| **Typed Python module (dataclasses) → JSON Schema** ✅ chosen | | Python is the **authoritative runtime** — params cross a trust boundary (stdio JSON) and *must* be validated there; co-locating the contract in that language keeps it honest. It adds **zero runtime dependency**, honoring the repo's explicit lean ethos (`CONTRACTS.md §7`: "stdlib JSON-RPC, no FastAPI"; the sidecar deps are ML-only). dataclasses give typed authoring + basedpyright checking for free; JSON Schema is the clean, standards-based bridge to TS. |
| pydantic v2 module | rejected (for *this* repo) | Ergonomically the nicest and the obvious "typed model + JSON Schema" answer, **but** it is a new runtime dependency the sidecar deliberately avoids, it must pass the `osv-scanner` lockfile gate and the 100%-coverage gate, and it buys little the stdlib walk doesn't already give for a contract this shape. Documented as the drop-in upgrade if the team later accepts the dependency (it would replace `schema.py` + `validate.py`). |
| JSON/YAML-first (author raw JSON Schema) | rejected | Language-neutral but you hand-author verbose JSON Schema with no type-checker on the *authoring* surface — trades one un-checked source for another. |
| TS-first (zod / TypeBox → JSON Schema → Python) | rejected | Inverts the dependency: it makes the **renderer** the source of truth for a contract the **Python** side must validate, and forces a Node build step to regenerate the Python validators. Wrong trust-direction. |

**Dependency direction is one-way:** `contract/` never imports `media_studio`. The
runtime is the *consumer* of the generated artifacts, so the contract can be
type-checked and generated in isolation (and the parity tests compare the two).

## 3. Architecture

```
                sidecar/contract/spec.py         ← THE SINGLE SOURCE OF TRUTH
                 (dataclasses + METHODS registry)
                              │
                sidecar/contract/generate.py      ← the generator (stdlib only)
                              │
        ┌─────────────────────┼───────────────────────────────┐
        ▼                     ▼                                 ▼
 contract.schema.json   app/.../generated/*.ts          (Python runtime loader:
 (canonical machine     ├ schemas.generated.ts           contract/registry.py +
  contract — JSON        │   §3 interfaces + MethodName   contract/validate.py,
  Schemas + needs-key    ├ client.generated.ts           hand-written & stable,
  set + settings)        │   typed rpc() wrappers         load the JSON)
                         └ needsKeyInjection.generated.ts
                             the key-injection Set + predicate
```

The generator emits all six artifacts the KEYSTONE calls for:

- **(a) Python validators + registration** — `contract/validate.py` validates any
  request against `PARAMS_SCHEMA[method]`; `contract/registry.py` exposes
  `validate_request(method, params)` (the dispatch seam) + `needs_key(method)`.
- **(b) TS `client.ts` typed wrappers** — `client.generated.ts` (thin typed shims
  over the existing `rpc()` runtime; identical wire, better types).
- **(c) `schemas.ts`** — `schemas.generated.ts` interfaces.
- **(d) a `MethodName` union** — in `schemas.generated.ts`.
- **(e) the `needsKeyInjection` set** — `needsKeyInjection.generated.ts` (+ the
  Python `NEEDS_KEY_INJECTION` in the JSON).
- **(f) a typed `Settings` model both sides assert** — the `Settings` dataclass →
  `SETTINGS_SCHEMA` (Python `validate_settings`) + the `Settings` TS interface.

### The drift gate (how "generated" becomes enforceable)

`python -m contract.generate --check` fails if the committed artifacts are stale.
It runs **inside the existing `quality` gate** as a pytest test
(`test_generated_artifacts_are_current`) — **no new CI step**, so the
`charter_check.py` gate↔workflow consistency stays intact. The check is:

- **JSON artifact**: compared **byte-for-byte** (no formatter touches sidecar JSON,
  so regeneration is deterministic). Catches *any* spec change.
- **TS artifacts**: each carries a `contract-source-sha256` header equal to the hash
  of the canonical contract; the check asserts it equals the current spec's hash.
  This proves the TS was generated from the *current* spec **without** coupling to
  Biome's byte output (Biome may reflow freely; the hash line survives).

Result: a spec edit that isn't accompanied by a regenerate **fails CI**. Drift
becomes impossible rather than merely discouraged.

## 4. How this retires each of the 7 findings

| # | Finding | Retired by |
|---|---|---|
| 1 | `client.ts` 123 hand call sites | generated `client.generated.ts` wrappers — wire shape is emitted, not typed by hand. **Proven at parity** with the current `client.ts` (see §5). |
| 2 | `composition.py` ~120 `reg()` | `registry.method_names()` is the authority; the parity test asserts every declared method is actually registered, and (in migration) registration is driven from the contract. |
| 3 | `CONTRACTS.md` stale | the machine `contract.schema.json` replaces prose as the source of truth; docs are generated/derived, never the authority. |
| 4 | `schemas.ts` 1235 hand lines | generated `schemas.generated.ts` — interfaces emitted from the same dataclasses that drive Python. |
| 5 | `keyBridge.ts` allowlist → silent key omission | `needsKeyInjection` is **generated** from each method's declared `needs_key`. A key-consuming method can't be forgotten: it declares its own flag, and a parity test (in migration) enforces "handler touches keys ⟺ `needs_key=True`". The POC proves the generated set equals the current keyBridge verdict. |
| 6 | untyped `DEFAULT_SETTINGS` / `settings.get("k")` | the typed `Settings` model + `validate_settings`; both sides assert it. The parity test validates a real `settings.get()` payload against the generated schema. |
| 7 | `shortmaker.py` `settings.get("silenceTrimm")` typo | the same typed `Settings` — it **declares** `silenceTrim`/`removeFillers`/`hookTitle`/`stabilize`/`captionSpeakerLabels` (previously only stringly-accessed), so a typo is a compile/type error, not a silent `None`. |

## 5. The POC — what it proves, and the evidence

Five representative methods span every drift surface:

| Method | Why it's in the slice |
|---|---|
| `ping` | no params, protocol built-in (baseline) |
| `library.add` | a required `{path}` param + a data-model (`Video`) result |
| `settings.get` / `settings.set` | the typed `Settings` surface (findings #6/#7) |
| `shortmaker.select` | key-injection **by prefix family** (`shortmaker.`) + a job + settings-reading (the `silenceTrimm` site) |
| `providers.revealKey` | key-injection **by exact allowlist** (not a prefix) — proves both classifier paths |

### Parity evidence (all runnable in CI's `quality` gate)

- **TS wire parity** (`renderer/src/lib/rpc/generated/parity.test.ts`, vitest): for
  each method, the generated wrapper and the **existing** hand-written `client.*`
  wrapper are called with identical args; the test asserts they invoke `rpc()` with
  **byte-identical `(method, params)`**. The generated client is a drop-in.
- **keyBridge parity** (`app/main/keyBridge.contractParity.test.ts`, vitest):
  imports the **real** `keyBridge.needsKeyInjection` and the generated set and
  asserts they agree for the slice, and that every generated key-method is
  key-needing per keyBridge.
- **Python parity** (`sidecar/tests/test_contract_parity.py`, pytest, 29 assertions):
  every declared method is really registered (`register_all` live registry); the
  generated validators accept valid params and reject invalid ones exactly like the
  hand-written `_require_str`/`_require_number` (incl. `bool`-is-not-`int`); the
  `Settings` defaults match `DEFAULT_SETTINGS` and validate a real `settings.get()`;
  the newly-declared keys are modeled but were previously undeclared; and the
  generated artifacts are current (drift gate).

> The POC already caught a real drift: the contract's `defaultTargetJobSize` default
> was `5` while `DEFAULT_SETTINGS` uses `budget.DEFAULT_TARGET_JOB_SIZE = 8`. The
> parity test failed until it was reconciled — exactly the class of bug this
> retires.

### Additive, not a rip-out

Nothing existing is removed. `client.ts`, `keyBridge.ts`, `schemas.ts`,
`composition.py`, and `settings_store.py` are untouched. The contract package and
its generated outputs sit **beside** them and are proven equivalent. Wiring them in
is the migration (§ next doc), done method-by-method behind parity tests.

## 6. Cost / footprint

- **New runtime deps:** none (stdlib only) → the `osv-scanner` gate is untouched.
- **Coverage:** the generator + spec live outside the `--cov=media_studio` root (a
  build tool, not shipped in the package); the generated TS is coverage-excluded
  (verified by regeneration + parity, mirroring how the repo already excludes
  barrels). No 100%-coverage burden is added or waived on hand-written code.
- **Config touched (2 lines, documented):** `pyproject.toml` adds `sidecar/contract`
  to the basedpyright `include` (so the contract is type-gated); `vitest.config.ts`
  adds `renderer/src/lib/rpc/generated/**` to `coverage.exclude`.
