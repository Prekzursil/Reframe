# RPC Contract v2 — migration plan (123 methods, no big-bang)

Companion to [`rpc-contract-v2.md`](./rpc-contract-v2.md). This is the incremental,
parity-tested, CI-gated path from "5-method POC" to "all ~123 methods generated",
with the 100%-coverage gate green at **every** commit.

## Guiding invariants

1. **Additive first, swap second.** Every method's contract is declared and
   parity-proven *before* any hand-written surface is deleted. The generated code
   sits beside the hand code until a parity test says they're identical.
2. **One parity net under every swap.** No hand surface is retired until a test
   asserts `generated == hand` for the methods involved. If a swap regresses, revert
   one thin import — the hand code is one `git revert` away.
3. **Coverage-neutral swaps.** A swap *removes* hand-written (covered) lines and
   *routes through* already-tested generated/validator code (generated is
   coverage-excluded; the validator is 100%-tested in the contract package). Removed
   and added balance in the **same commit**, so the aggregate never dips below 100%.
4. **The drift gate is always on.** `contract.generate --check` runs in the existing
   pytest gate from day one (this PR), so a spec edit without a regenerate fails CI.

## Wave 0 — foundation (this PR) ✅

Contract package (`sidecar/contract/`), generator, the 5-method POC, the drift gate,
and the parity harness (Python + TS). Nothing wired in; nothing removed.

## Wave 1 — declare all 123 methods (pure addition, zero behavior change)

Transcribe every method into `contract/spec.py` and every shared type in
`schemas.ts` (~40-60 data models) into contract dataclasses. Regenerate. **No wiring
— the generated outputs are still only consumed by tests.**

Turn the POC parity tests into **parameterized suites over all methods**:

- **Registration parity** — every declared method ∈ the live `register_all` registry
  (and, reverse, every registered non-builtin method is declared → catches methods
  the contract missed).
- **keyBridge parity** — generated `needsKeyInjection` == the current keyBridge
  verdict for **all** methods.
- **Client wire parity** — for every method, generated wrapper wire == hand
  `client.*` wire (the POC pattern, parameterized).
- **Schema parity** — generated interface fields == the hand `schemas.ts` interface
  fields (field name + optionality), per type.

**This wave is where the payoff lands:** every parity mismatch it surfaces is a
**real, pre-existing drift bug** (a keyBridge omission, a TS/Python field
divergence, a stale type). Each is triaged and fixed in the hand code (or the
contract, whichever is wrong) — the suite going green *is* the reconciliation.

CI stays green throughout because nothing is wired in; the only new failures are
the drift bugs you *want* surfaced, fixed one at a time.

### Generator extensions Wave 1 needs (scoped now so they're not a surprise)

- **Richer type support in `schema.py`**: `Literal[...]` → JSON `enum` + TS union
  (`SubtitleFormat = 'srt'|'ass'|'vtt'`, `NleFps = 24|25|30|60`), intersection
  results (`JobHandle & {…}`), and a couple of nested generics. ~1-2 days.
- **A wrapper arg-DSL (or per-method override) for ~10-15 bespoke wrappers**: the
  hand client has conditional param shaping (e.g. `transcribe.start`'s
  `...(language ? {language} : {})`, `director.apply`'s reviewed-op forwarding,
  `subtitles.translate`'s optional `opts`). The generator gets either (a) a small
  declarative "optional-spread" arg mode, or (b) a documented per-method override
  file the generator imports verbatim. Budget the override hatch for the long tail.

## Wave 2 — flip the authorities (thin swaps, one surface at a time)

Each sub-step is its own small PR behind the Wave 1 parity nets.

| Step | Swap | Coverage effect |
|---|---|---|
| 2a | **keyBridge**: replace the hand `INJECT_PREFIXES`/`INJECT_METHODS` with `import { needsKeyInjection } from '…/generated'`; delete the hand allowlist | removes covered hand lines; adds an excluded import → neutral |
| 2b | **client.ts**: re-export the generated wrappers (group by group), delete the hand wrappers as each group's parity is green | removes covered hand wrappers; generated is excluded → neutral/positive |
| 2c | **schemas.ts**: re-export types from `schemas.generated.ts`; delete the hand duplicates | pure-type file (0 statements) → no coverage effect |
| 2d | **Python params**: wire `registry.validate_request(method, params)` into `protocol.dispatch` *before* the handler (adapter: `except ContractValidationError: raise RpcError(…INVALID_PARAMS)`); delete the now-redundant `_require_str`/`_require_number` from each migrated handler | removes covered manual checks; the validator is already 100%-tested → neutral |
| 2e | **Settings**: build `DEFAULT_SETTINGS` from the `Settings` model + type the reads (incl. `shortmaker.py`'s `settings` param) so a `settings.get("silenceTrimm")` typo is a type error | removes untyped-dict lines; adds typed model (tested) → neutral |

When Wave 2 completes, the contract package's runtime pieces (`registry.py`,
`validate.py`) move *into* `media_studio` (they're now load-bearing) — at which point
they enter the `--cov=media_studio` root but are **already 100%-covered** by the
contract tests that move with them, and they **replace** the hand-written covered
code they supersede. Net coverage: neutral.

## Wave 3 — retire the stale prose

Point `CONTRACTS.md` at `contract.schema.json` as the machine authority and
(optionally) generate a human-readable method reference from it. `CONTRACTS.md`
stops being a hand-maintained source and becomes a generated/derived view.

## Keeping the 100% gate green — the mechanical rule

For every swap commit: **delete the hand lines in the same commit that routes through
the generated/validator path.** Because the replacement path is either
coverage-excluded (generated) or already-100%-tested (validator/registry), the
aggregate `covered/total` ratio is preserved. If a swap would strand an uncovered
line, that line was dead (delete it) or the replacement lacks a test (add it to the
contract package's suite, where it belongs) — never lower a threshold.

## Rollback & risk

- **Wave 1 is risk-free** (pure addition; only surfaces existing bugs).
- **Wave 2 steps are single-import reverts.** Each is guarded by a parity test; a
  regression reverts one swap and the hand code returns from git history.
- The **drift gate** prevents the *reintroduction* of drift for every migrated
  method from the moment it's declared.

## Honest effort estimate

| Wave | Work | Estimate |
|---|---|---|
| 0 | POC (this PR) | done |
| 1 | Transcribe 123 methods + ~50 data models; extend `schema.py` (enums/unions/intersections) + the wrapper override hatch; parameterize the parity suites; **reconcile every real drift the suites surface** | **~3-5 eng-days** (the long pole; mostly mechanical transcription, but the drift reconciliation carries the real, valuable surprises) |
| 2 | Flip keyBridge (~½d), client.ts (~1-2d), schemas.ts (~½d), Python dispatch validation + remove `_require_*` (~1-2d), Settings model (~1-2d) | **~1 eng-week** |
| 3 | Docs/authority retire | **~½ eng-day** |
| — | **Total** | **~2-3 focused engineer-weeks** |

Risk is **low** (every step additive-then-thin-swap, parity-gated, coverage-neutral);
cost is dominated by careful transcription and reconciling the genuine drift the
parity suite exposes — which is precisely the debt this keystone is meant to pay
down.
