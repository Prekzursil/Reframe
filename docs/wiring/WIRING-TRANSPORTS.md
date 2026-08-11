# Renderer to sidecar: the seven RPC transports, measured — and a proposal

Measured 2026-08-11 against `81a04965`. This document exists because W62 shipped a
headline overclaim (`client.ts` asserted "every method here has a REAL caller" directly
above an object with none) and the investigation found the overclaim was a symptom: the
renderer reaches the sidecar through **seven** different transports, and the typed client
is not the dominant one. Nothing here is a decision — it is the measurement plus options,
so the owner can pick.

Everything below was produced by two throwaway detectors whose full source is quoted in
§2. They were run from the worktree root; the numbers are reproducible.

---

## 1. Headline

| | measured |
|---|---|
| typed wrapper methods in `client.ts` (40 groups) | **140** |
| production-reachable | **73** (64 direct + 9 via slice injection) |
| NOT production-reachable (reached only by their own tests) | **67** |
| wrappers with literally no caller anywhere | **0** |
| groups with zero production reach | **16 of 40** (43 methods) |
| distinct RPC transports in production use | **7** |
| the LARGEST transport by call sites | not the typed client — it is `bridge.rpc('literal')`, **70 sites in 18 files** vs the typed client's 53 |

**The 48% figure is the story.** 67 of 140 typed wrappers (48%) exist only to be
unit-tested. They are not "unused code" in the usual sense — every one of them is
exercised, asserted on, and counted toward the 100% coverage gate, while the feature it
describes talks to the sidecar through a different transport entirely. That is coverage
measuring the wrapper layer rather than the app.

### Corrections to the numbers this lane was briefed with

The briefing said 140 / 65 reachable / 75 test-only / 8 fully dead groups. Re-measured
independently:

| claim | briefed | measured | verdict |
|---|---|---|---|
| total wrapper methods | 140 | **140** | CONFIRMED |
| production-reachable | 65 | **73** | REFUTED (+8) |
| reachable only from tests | 75 | **67** | REFUTED (-8) |
| fully dead groups | 8 | **16** | REFUTED (undercount, 2x) |

The 65/75 split is exactly what my own **first** detector produced before it was
corrected — both it and the briefed detector matched only `.<group>.<method>` and were
therefore blind to slice injection (§4, T3), which is how `savePresets` (4 methods),
`paths` (1) and 3 of `library`'s reach production. The 8 groups named in the briefing
(`audiomix`, `diarize`, `feedback`, `media`, `speed`, `timeline`, `tracksAudio`, `tts`)
are all genuinely dead — they are a **subset** of the 16. The 8 the briefing missed are
`broll`, `index`, `project`, `recipes`, `stabilize`, `thumbnail`, `tracks`, `transcribe`.

Fully dead groups, with method counts: `tracks` (7), `broll` (7), `tracksAudio` (4),
`recipes` (4), `tts` (3), `index` (3), `project` (3), `audiomix` (2), `feedback` (2),
`media` (2), `diarize` (1), `speed` (1), `stabilize` (1), `thumbnail` (1), `timeline` (1),
`transcribe` (1) = 43 methods. The remaining 24 not-reachable methods sit in groups that
are otherwise live (e.g. 9 of `library`'s 13, 4 of `subtitles`' 5).

---

## 2. The detector, and how it was controlled

`.quality/_scratch_wrapper_reach.py` and `.quality/_scratch_transports.py` are scratch and
are NOT committed, so this section states the algorithm and its controls precisely enough
to rebuild rather than pretending to quote source that is not here. Both refuse to print a
citable number unless their controls pass:

* **positive control** — `client.library.list` must be seen as production-reachable
  (it is: `App.tsx:358`, `features/BatchQueue.tsx:126`);
* **negative control** — `client.tracksAudio` must be absent from production entirely;
* **test-side control** — `client.tracksAudio.list` must be found in a test
  (`lib/rpc.test.ts:456-481`). This is the one that matters: it proves the matcher CAN
  fire on the string it reports as absent from production, so the zero is a real absence
  and not a broken probe;
* **coverage control** — the slice tier must be non-empty, and every resolved slice
  receiver must yield at least one method.

### Four refutations the detector went through

Each earlier version produced a confident, wrong number. They are recorded because each
one is a distinct false-negative shape, and three of them are the same shape the briefed
detector still has.

1. **v1 matched only `.<group>.<method>`.** Reported 65/75 and called `paths`,
   `savePresets`, `recipes` fully dead. REFUTED by `views/Settings.tsx:136,187,188`, which
   pass the whole slice as a prop (`rpc={client.savePresets}`); the child then calls
   `rpc.upsert()`, a string this matcher can never see.
2. **v2 added slice detection but credited a slice group with ALL its methods.** REFUTED:
   `client.library` (13 methods) goes to `ManagedStoreMeter`, whose prop type
   `ManagedStoreRpc` (`components/ManagedStoreMeter.tsx:26-33`) declares exactly 3. v3
   resolves each receiver and counts only what it calls.
3. **v3's receiver scan required `rpc.` adjacency.** Reported `paths` as dead with a
   resolved receiver — a self-contradiction that tripped the "receiver resolved but 0
   methods matched" control. Cause: `components/PathsPanel.tsx:125-126` breaks the chain
   across lines (`rpc`newline`.describe()`).
4. **v5 over-tightened to require a literal `client.` receiver.** Swung DIRECT from 64 to
   35. REFUTED: `features/ProvidersKeys.tsx:279` binds `const api = rpcClient ?? client`
   and then calls `api.providers.list()` (`:304`) — genuinely the typed client under an
   alias. v6 resolves per-file aliases instead.

Comment stripping was added in v2 and changed a verdict in both directions: it removed a
v1 false POSITIVE (`project` was "reached" only from a `//` comment) and it initially
caused the `paths` false negative in item 3 by deleting a doc line that happened to be the
only adjacent `rpc.describe()`.

### The convergence check

The final detector computes production reach two mechanically different ways — once with a
per-file alias-bound receiver set (`client` plus anything bound to it), once
receiver-blind (`.g.m` anywhere) — and prints the gap. **The gap is 0.** Two matchers
that fail differently agree on all 140 methods, which is the strongest evidence here that
64/9/73/67 is right. A non-zero gap would have meant some `.g.m` was riding an object that
is not the typed client.

> UNVERIFIED: the detector classifies a file as a test by `.test.`/`.spec.` in its name or
> an `__tests__`/`e2e` path segment. If a production file is named that way, or a test is
> not, its methods are misfiled. Settling experiment: cross-check the 237/267 prod/test
> split against `vitest --reporter=json` list output, which enumerates the files vitest
> actually treats as tests; a set difference of 0 settles it.

---

## 3. Why the typed wrappers cannot serve a `features/` panel as-is

This is the mechanical reason the renderer grew a second transport, and it is worth
stating precisely because the honest version points at the fix.

A `features/` panel takes an **injectable bridge**:

```ts
// app/renderer/src/features/Dub.tsx:193-200
export interface DubProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}
export function Dub({ videoId, api }: DubProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);
```

The typed client reads the bridge from a **module-level accessor with no parameter**:

```ts
// app/renderer/src/lib/rpc/client.ts:99-106
function bridge(): MediaApi {
  const api = (globalThis as { window?: { api?: MediaApi } }).window?.api;
  if (!api) {
    throw new Error('window.api bridge is not available (preload not loaded)');
  }
  return api;
}
```

Every wrapper closes over that function. So `client.tracksAudio.list(videoId)` resolves
`window.api` at call time and there is no seam to substitute: a test rendering
`<Dub api={fake} />` would have its fake **silently ignored**, and in a JSDOM environment
with no preload it would instead throw at `client.ts:103`. Swapping Dub's
`bridge.rpc('tracks.audio.list', …)` (`Dub.tsx:252`) for `client.tracksAudio.list(videoId)`
would therefore break the injection seam that 18 `features/` files are built around. That
constraint is real and the panels were right to route around it.

**But "the wrappers cannot be injected" is not the same claim as "typing cannot be
injected", and the codebase already disproves the second.** Seven files inject the typed
client itself:

```ts
// app/renderer/src/features/ProvidersKeys.tsx:97, :279
rpcClient?: Pick<typeof client, 'providers'> & { … };
const api = rpcClient ?? client;
// …then, :304
Promise.resolve(api.providers.list()),
```

`Pick<typeof client, 'providers'>` gives the panel full wrapper typing AND a substitution
point, with no wire change. That pattern is the one live proof that the trade-off the
`features/` panels made — testability bought with untyped method strings — was not
actually forced.

---

## 4. The seven transports, with production call-site counts

Counts are production only (`client.ts` and `*.test.*` excluded), comments stripped, and
each row's regex was first proven to fire on the named anchor file.

| # | transport | shape | sites | files | typed? | injectable? |
|---|---|---|---|---|---|---|
| T1 | typed wrapper | `client.g.m(…)` | 53 | 14 | yes | no |
| T2 | whole-client injection | `rpcClient ?? client`, then `api.g.m(…)` | 7 | 7 | yes | **yes** |
| T3 | slice injection | `<Panel rpc={client.g} />`, child calls `rpc.m()` | 5 | 3 | yes | **yes** |
| T4 | free module function | `rpc('settings.set', …)` | 10 | 5 | no | no |
| T5 | descriptor object | `{ method: 'transcribe.start', params, label }` | 17 | 2 | no | n/a (data) |
| T6 | constant map | `bridge.rpc(BROLL_METHODS.status)` | 4 | 1 | partly | yes |
| T7 | injectable bridge | `bridge.rpc('tracks.audio.list', …)` | **70** | **18** | no | **yes** |

Notes that matter for the decision:

* **T7 is the biggest surface in the app** (70 sites, 18 files, 53 distinct wire methods) —
  larger than the typed client it was supposed to be a fallback for.
* **T4's 10 sites are misleading**: 5 of them are inside
  `lib/rpc/generated/client.generated.ts` (the generated wrappers' own bodies), so app-level
  T4 is 5 sites in 4 files (`App.tsx` x2, `views/Edit.tsx`, `components/useJob.ts`,
  `features/lineageActionsClient.ts`) — all of them `settings.set` or job polling.
* **T5 is not a call transport at all** — `features/repurposeTemplates.ts` and
  `features/Recipes.tsx` store `{method, params, label}` rows and a generic runner
  executes them. It is a data format, and it is the one place where a method string is
  legitimately a value. Any migration must leave T5 alone or give it a typed descriptor.
* **T6 is the best of the string-based options.** `BROLL_METHODS`
  (`client.ts:247`) is a single constant map that BOTH the wrappers and `BrollPanel.tsx`
  read, so a panel cannot invent a string and the wrapper/panel pair cannot drift. It gets
  injectability without free-text. It is also, notably, the group whose wrappers are
  100% dead (7/7) while its panel is fully live — the clearest single illustration of the
  split.

### An eighth surface exists and is not in the table

`lib/rpc/generated/client.generated.ts` is `@generated by sidecar/contract/generate.py`
from the frozen contract, carries a `contract-source-sha256`, and is proven wire-identical
to the hand-written client by `lib/rpc/generated/parity.test.ts` ("same method name + same
params object, so the generated client can replace the hand-written wrappers with zero
wire change"). It has **zero** production callers and covers a 6-method POC slice.
`features/LipSync.tsx:300-301` records why it was passed over: *"`clientGenerated` calls
the non-injectable module-level `rpc()`, so it cannot take the `api?` test bridge every
panel in `features/` is built around"* — i.e. it inherited T1's exact defect.

---

## 5. Options

Ranked by what they cost against what they close. No option deletes the 67 wrappers; see
§6.

### Option A — make the generated client injectable, then converge on it (recommended)

Change `contract/generate.py` so each generated group is a factory over an injected
transport rather than a closure over the module-level `rpc`:

```ts
export const makeClient = (t: Transport) => ({ tracksAudio: { list: (videoId: string) => t.rpc('tracks.audio.list', { videoId }) }, … });
export const client = makeClient(defaultTransport);   // app default, unchanged
```

* **Closes:** the T1-vs-T7 fork at its root. A panel takes `api?: Pick<Client,'tracksAudio'>`
  and gets typing plus injection, which is what both camps actually wanted.
* **Cost:** one generator change plus a regenerate; `parity.test.ts` already exists as the
  both-states check that the wire did not move. The hand-written `client.ts` stays as-is
  during the transition (`makeClient(defaultTransport)` is byte-compatible at every call
  site), so this is additive and reversible.
* **Risk:** the generated slice is currently 6 methods against 140. Expanding it is
  contract work in `sidecar/contract/`, and it is UNVERIFIED whether the contract covers
  all 140 wire methods. Settling experiment: run `python -m contract.generate` from
  `sidecar/` and diff the generated method set against the 140 parsed from `client.ts`;
  the difference is the exact backlog.

### Option B — adopt T2/T3 by hand, no generator change

Convert `features/` panels from `api?: MediaStudioApi` + `bridge.rpc('literal')` to
`rpcClient?: Pick<typeof client, 'g'>` + `api.g.m()`, following `ProvidersKeys.tsx`.

* **Closes:** the same fork, using a pattern already live in 7 files.
* **Cost, measured:** 70 call sites across 18 production files, and the test side is the
  real bill — 6 test files hold **252** fake entries keyed by wire-method string
  (`ShortMaker.test.tsx` alone has 118, `SemanticSearch.test.tsx` 84). Every one becomes a
  slice fake. Under a 100% coverage gate that is a large, mechanical, high-conflict diff.
* **Risk:** it is hand-written, so client and sidecar can drift again — exactly what
  produced the 67.

### Option C — freeze and document (do nothing structural)

Keep both transports, and add a lint rule that a NEW `features/` panel must use T2/T3, so
the 67 stops growing.

* **Closes:** growth only. The 67 stay.
* **Cost:** near zero.
* **Risk:** the misleading-coverage problem persists — wrappers keep being 100%-covered
  and unused.

### Option D — delete the unreached wrappers

**Do not do this**, and it is listed only to record why. The 67 are the typed description
of a wire surface the app genuinely uses; deleting them removes the types while leaving
the calls (as untyped strings in T7). It would also drop 67 methods' worth of tests, which
under a `--cov-fail-under=100` gate is a coverage change that looks like an improvement
and is a regression in what is actually checked.

### Recommendation

**A, with C as the immediate step.** C costs nothing and stops the bleed today; A is the
only option that removes the reason the fork exists rather than paying to cross it. B is A
without the generator, i.e. the same 70-site bill with the drift risk left in.

This recommendation rests on one UNVERIFIED premise — that the frozen contract can
describe all 140 methods — and inherits that tag: **RECOMMENDATION (UNVERIFIED premise:
contract coverage of the full 140).** The settling experiment is in Option A above and is
a single command.

---

## 6. Explicitly not proposed

* **No wrapper deletions.** See Option D.
* **No change to T5.** The descriptor rows in `repurposeTemplates.ts` / `Recipes.tsx` are
  data and a generic runner consumes them; they are the legitimate use of a method string.
* **Nothing in `features/Dub.tsx` or `features/Dub.test.tsx`.** They hold 9 and 20 of the
  sites counted above and are in open PR #407; this lane did not touch them, and the two
  copies of the corrected `replace`/`strip` wording that live there are reported as
  BLOCKED-ON-PR rather than edited.

---

## 7. Rebuilding the detector

Enough to re-derive every number above.

**Parse.** Read `client.ts`; between `export const client = {` and `} as const;`, a group
is `^  (\w+): \{$` and a method is `^    (\w+)\s*:\s*[(<]`. Yields 40 groups / 140 methods.

**Scan.** All `app/**/*.ts{,x}` except `node_modules`, `dist` and `client.ts` itself
(504 files). Strip `/* */` and `//` comments first — this is load-bearing in both
directions (§2). Split test vs production on `.test.`/`.spec.` in the filename or an
`__tests__`/`e2e` path segment (237 prod / 267 test).

**Classify each method**, first tier that matches:

1. `DIRECT` — some production file matches `\b(RECV)\s*\.\s*group\s*\.\s*method\b`, where
   `RECV` is that file's alias set: `client` plus every identifier bound to it by
   `const X = Y ?? client`, `const X = useMemo(() => Y ?? client…)`, `const X = client`, or
   a default parameter `X = client`. Per-file aliasing is what separates
   `ProvidersKeys.tsx`'s `api` (bound to `client`) from `Dub.tsx`'s `api` (bound to the
   preload bridge) and from `VideoTimeline.tsx`'s own local `client`.
2. `SLICE` — the group is passed whole (`\bclient\.group\b(?!\s*\.)`) to a receiver, and
   that receiver's own source calls `\bprop\s*\.\s*(\w+)\(` — note `\s*`, the chain breaks
   across lines. The five receivers are `ManagedStoreMeter.tsx`, `PathsPanel.tsx`,
   `SavePresetsControls.tsx`, `CaptionPreferences.tsx`, `useShortThumbnail.ts`.
3. `TEST` — a test file matches the method.
4. `NONE`.

**Then assert the four controls in §2, and the convergence check**: recompute tier 1
receiver-blind (`\.group\.method\b`, no alias set) and require the two results to be
identical. They are.

---

*Detectors: `.quality/_scratch_wrapper_reach.py`, `.quality/_scratch_transports.py`,
`.quality/_scratch_blast.py` — scratch, deleted before commit. Rebuild from §7.*
