# Reframe — "UX / QoL" Bundle — PLAN

Branch: `feat/ux-qol-design` (off `origin/main`). **DESIGN + PLAN docs only — no feature code in this branch.** The eventual implementation lands on a separate branch `feat/ux-qol` off fresh `origin/main`.

Companion: [`DESIGN.md`](./DESIGN.md) (committed `86e480a`). This PLAN decomposes that design into falsifiable Work Units. Every WU cites real code (`path:line`, verified against this checkout at `feat/ux-qol-design`). No fabrication; capability gaps are named per §5.

---

## 0. Ground rules for the build (apply to EVERY WU)

- **TDD, 100% line+branch.** Write the test first, watch it fail, then implement. Sidecar gate: `pytest --cov-branch --cov-fail-under=100`. Renderer gate: `vitest run --coverage` (thresholds 100/100/100/100 already enforced — `app/vitest.config.ts:44-49`).
- **Fakes at the seams.** ffmpeg (thumbnails), the model/provider pool, OCR, and the job-store disk are all injected; tests use in-memory/fake doubles. NEVER spawn real ffmpeg / open a real socket / hit a real provider in a unit test. Heavy-ML bodies stay `# pragma: no cover` (existing convention).
- **The ONE RPC site.** Every new `*.*` handler is wired in `register_all` (`sidecar/media_studio/handlers.py:1982`); a duplicate name raises at import (`protocol.py:79-91`, verified) so a double-wire fails loudly.
- **Additive only.** `settings.set` blind-merges (`settings_store.py:167-182`); the `Video` schema field and the new status are additive. No migration.
- **Reuse the Hub envelope where AI is touched.** Resumed AI jobs re-flow through `Services._run_ai_job` → `_enforce_cloud_budget_ack` (`handlers.py:1672-1691`); a stale pre-restart `cacheKey` cannot match a freshly-planned one, so budget/consent re-prompt by construction. No new bypass.
- **Scoped commits.** Never `git add -A`; add only the files a WU touches. Never `--no-verify`. Never `git push --force` without explicit approval.
- **Per-WU gate commands** are listed under each WU; the bundle-level gate is §"Gate commands (bundle-level)".

---

## 1. Work-Unit overview

| WU | Title | Layer | New substrate? | Depends on |
|----|-------|-------|----------------|------------|
| **WU-0** | Settings defaults + types scaffold | sidecar + renderer types | no (additive keys) | — |
| **WU-1** | `paths.describe` RPC | sidecar RPC | no | WU-0 |
| **WU-2** | `library.thumbnail` RPC + `Video.thumbnailPath` | sidecar RPC + schema | RPC + schema field | WU-0 |
| **WU-3** | `thumb:` mstream resolver branch | main process | new resolver branch | WU-2 (shape only) |
| **WU-4** | `useVideoThumbnail` hook | renderer | no | WU-2, WU-3 (URL shape) |
| **WU-5** | `JobStore` + atomic disk persistence | sidecar | **YES — the load-bearing piece** | WU-0 |
| **WU-6** | `JobRegistry` write-through + rehydrate + `INTERRUPTED` status | sidecar | extends jobs.py | WU-5 |
| **WU-7** | `JobInfo` status widening + `canResume` + Resume button | renderer | no | WU-6 (status name) |
| **WU-8** | `readiness.summary` RPC + `readinessMeta.ts` | sidecar RPC + pure helper | RPC + pure map | WU-0 |
| **WU-9** | `ReadinessBadge` component | renderer | no | WU-8 |
| **WU-10** | `savePresets.*` RPC | sidecar RPC | no (mirrors applyPreset) | WU-0 |
| **WU-11** | `SavePresetsControls` + export-defaults wiring | renderer | no | WU-10, WU-0 |
| **WU-12** | `PathsPanel` renderer | renderer | no | WU-1 |
| **WU-13** | App `lastOpenedVideoId` persist + restore | renderer | no | WU-0 |
| **WU-14** | Wire badges/thumbnails into library + model panels | renderer integration | no | WU-4, WU-9 |

14 build WUs + 1 scaffold (WU-0). WU-5/WU-6/WU-7 are the resume spine and carry the most risk.

---

## 2. Work Units (detailed)

### WU-0 — Settings defaults + shared type scaffold

**Goal:** Land the additive settings keys and the renderer type changes that downstream WUs depend on, in one small foundation WU so parallel WUs don't race the same files.

**Files:**
- `sidecar/media_studio/settings_store.py` — extend `DEFAULT_SETTINGS` (currently `settings_store.py:41-80`) with: `lastOpenedVideoId: ""`, `autosave: {enabled: True, debounceMs: 1500}`, `exportDefaults: {subtitleFormat: "srt", nleFormat: "edl", nleFps: 30}`, `savePresets: {presets: {}, active: ""}`.
- `app/renderer/src/lib/rpc.ts` — add the matching TS shapes (`AutosaveSettings`, `ExportDefaults`, `SavePresetsBlock`) as additive interfaces near the existing settings types. (The `JobInfo` status widening is deferred to WU-7 to keep this WU dependency-free.)
- Tests: `sidecar/tests/test_settings_store.py` (extend existing), `app/renderer/src/lib/rpc.test.ts` (if present; else a focused type-shape test).

**Test strategy:** Assert `DEFAULT_SETTINGS` contains the four new keys with exact default values; assert `settings.set({autosave:{enabled:False}})` round-trips through the blind-merge (`settings_store.py:167-182`) without clobbering siblings. No fakes needed (pure dict logic).

**Falsifiable acceptance:**
- `DEFAULT_SETTINGS["exportDefaults"] == {"subtitleFormat":"srt","nleFormat":"edl","nleFps":30}` exactly.
- A merge of `{"savePresets":{"active":"x"}}` leaves `presets` untouched (deep-merge or documented shallow-merge — pin whichever `settings.set` actually does; `settings_store.py:167-182` is the source of truth — TEST the real behavior, do not assume deep).
- Coverage 100% on the new lines.

**Gate:** `cd sidecar && pytest --cov-branch --cov-fail-under=100 tests/test_settings_store.py` + `cd app && npx vitest run --coverage`.

---

### WU-1 — `paths.describe` RPC (read-only layout)

**Goal:** A direct (non-job) sidecar RPC returning the resolved data layout so the renderer can SHOW where everything lives (today it can only fetch the root via `dataFolder.get`).

**Files:**
- `sidecar/media_studio/handlers.py` — add `Services.paths_describe(self, params, ctx) -> {dataDir, projectsDir, exportsDir, settingsPath, libraryPath, subDirs}`; derive purely from `Services.{data_dir, projects_dir, exports_dir}` (`handlers.py:143-148`) + the per-feature sub-dir names already used (`shorts-*`, `dubs`, `stabilized`, `audiomix`, `trimmed` — `handlers.py:1351,2119,2164-2182`). Register in `register_all` (`handlers.py:1982`).
- Tests: `sidecar/tests/test_handlers_paths.py` (new).

**Test strategy:** Construct `Services` with a tmp data dir (existing `Services` construction pattern, `handlers.py:121-180`); call the handler; assert all paths are children of `data_dir`. No I/O beyond path joins (pure). No fakes.

**Falsifiable acceptance:**
- `result["projectsDir"]` == `os.path.join(result["dataDir"], "projects")` and equals `Services.projects_dir`.
- `result["subDirs"]` keys cover at least `{shorts, dubs, stabilized, audiomix, trimmed}`.
- Response contains **no** key/secret strings (assert none of the values look like a token; assert `providers`/`keys` absent).
- Calling it twice is identical and writes nothing to disk (mtime of data dir unchanged).
- 100% line+branch on the handler.

**Gate:** `cd sidecar && pytest --cov-branch --cov-fail-under=100 tests/test_handlers_paths.py tests/test_handlers.py`.

---

### WU-2 — `library.thumbnail` RPC + `Video.thumbnailPath`

**Goal:** Extract a poster from a SOURCE library video (not a clip) by reusing the shorts ffmpeg poster engine; persist `thumbnailPath` onto the Video; return it. Idempotent.

**Files:**
- `sidecar/media_studio/handlers.py` — add `Services.library_thumbnail(self, params, ctx) -> {thumbnailPath}`: resolve the source path via the existing `_resolve_video_path` pattern (`handlers.py:197-202`); compute the output `data_dir/thumbnails/<videoId>.jpg`; if it exists, return it; else build argv via `shorts.build_thumbnail_argv` (`shorts.py:183`) and run through the **injected ffmpeg runner** (the same seam `shorts.thumbnail` uses — do NOT call `subprocess` directly here; reuse the injected runner so tests fake it). Persist `thumbnailPath` onto the Library Video. Register in `register_all`.
- `sidecar/media_studio/library.py` — extend `_normalize` (`library.py:108-117`) to carry optional `thumbnailPath` (default `""`); add a setter mirroring the existing `set_*` helpers used by `handlers.py`.
- Tests: `sidecar/tests/test_handlers_library_thumbnail.py` (new), extend `sidecar/tests/test_library.py`.

**Test strategy:**
- **Fake the ffmpeg runner** (inject a fake that "creates" the output file by touching it / records the argv) — assert the argv equals `build_thumbnail_argv(sourcePath, out, settings)` and that the output path is `data_dir/thumbnails/<videoId>.jpg`.
- Idempotence: pre-create the poster file → assert the runner is NOT invoked and the existing path is returned.
- Missing video id → structured error (mirror `_resolve_video_path` failure).
- `_normalize` backfills `thumbnailPath: ""` for an old Video record with no field.

**Falsifiable acceptance:**
- First call invokes the fake runner exactly once with argv == `build_thumbnail_argv(...)`; second call invokes it zero times and returns the same path (idempotent).
- The returned path is strictly under `data_dir/thumbnails/` (string-prefix assertion).
- A Library Video JSON lacking `thumbnailPath` loads as `""` (no KeyError).
- The persisted Video now carries the poster path (re-list shows it).
- 100% line+branch (the heavy real-ffmpeg body, if any, stays behind the injected seam — no `# pragma` needed because the seam is faked).

**Gate:** `cd sidecar && pytest --cov-branch --cov-fail-under=100 tests/test_handlers_library_thumbnail.py tests/test_library.py`.

---

### WU-3 — `thumb:` mstream resolver branch (main process)

**Goal:** Serve library posters through a traversal-guarded `thumb:` id branch so `<img src>` can load them in the sandbox (raw fs paths can't load).

**Files:**
- `app/main/main.ts` — add a `thumb:` branch in `registerMediaProtocol(...)` alongside the verified `dub:` (`main.ts:436-439`) and `short:` (`main.ts:457-459`) branches: derive `const thumbnailsRoot = resolvePath(DATA_ROOT, 'thumbnails')` (mirrors the exports/dubs derivation exactly — both use `DATA_ROOT`, verified `main.ts:437,458`) and call `resolveScopedMediaPath(videoId, 'thumb:', thumbnailsRoot)` (`exportPath.ts:20`).
- `app/main/exportPath.ts` — **no change** (the helper is prefix-agnostic, verified `exportPath.ts:20-24`); the `thumb:` form encodes an absolute path after the prefix, identical to `short:`/`dub:`.
- Tests: extend `app/main/exportPath.test.ts` and `app/main/mediaProtocol.test.ts` (both exist).

**Test strategy (pure, no Electron):**
- `resolveScopedMediaPath('thumb:' + insideAbs, 'thumb:', root)` returns the path when inside root; returns `null` for a parent-traversal (`thumb:<root>/../escape.jpg`), for a sibling dir sharing the prefix string, and for a missing-prefix id. (These mirror the existing `short:`/`dub:` traversal tests.)

**Falsifiable acceptance:**
- An id pointing strictly inside `data_dir/thumbnails` resolves; ANY path outside returns `null` (the security boundary is the falsifiable claim).
- The `thumb:` root is derived from `DATA_ROOT` (same source as `short:`/`dub:`) — assert the join in a unit test of the branch's root derivation (extract the derivation if needed to keep it testable without Electron, mirroring how `exportPath.ts` was extracted).
- 100% line+branch on the new branch.

**Gate:** `cd app && npx vitest run --coverage app/main/exportPath.test.ts app/main/mediaProtocol.test.ts`.

---

### WU-4 — `useVideoThumbnail` hook (renderer)

**Goal:** A near-clone of `useShortThumbnail` (`useShortThumbnail.ts:41-73`, verified) pointed at `library.thumbnail` + the `thumb:` URL, inheriting the proven graceful-degradation (missing poster → ▶ glyph, never blocks the card).

**Files:**
- `app/renderer/src/components/useVideoThumbnail.ts` (new) — a `thumbnailSrc`-style pure URL helper (`thumb:` form) + the `useVideoThumbnail(rpc, videoId, thumbnailPath)` hook. Reuse the exact lifecycle of `useShortThumbnail`: existing path wins (no RPC), else call once (idempotent server-side), best-effort catch leaves `""`.
- `app/renderer/src/lib/rpc.ts` — add `library.thumbnail` to the typed client surface.
- Tests: `app/renderer/src/components/useVideoThumbnail.test.tsx` (new), mirroring `useShortThumbnail`'s test if present.

**Test strategy:** Pure helper tested directly. Hook tested with a fake `rpc` (resolves / rejects / returns empty). Assert: existing `thumbnailPath` short-circuits (rpc NOT called); empty path + null rpc → `""`; rpc reject → `""` (graceful); rpc resolve → the `thumb:` URL. No real network.

**Falsifiable acceptance:**
- Given a non-empty `thumbnailPath`, the fake rpc is called **zero** times and the rendered URL is the `thumb:` form of that path.
- Given an empty path and a rejecting rpc, the hook returns `""` and does not throw (the gallery never breaks — the §3.5 invariant).
- The pending state never produces a layout-shifting blank (returns the placeholder URL until resolved).
- 100% line+branch.

**Gate:** `cd app && npx vitest run --coverage app/renderer/src/components/useVideoThumbnail.test.tsx`.

---

### WU-5 — `JobStore` + atomic disk persistence (NEW SUBSTRATE)

**Goal:** A standalone, injectable store that persists job records to `data_dir/jobs/` using the atomic write pattern (`library.py:74-79`). This is the only genuinely new substrate (the §6.1 named gap: `jobs.py` is 100% in-memory, verified — no file I/O in `jobs.py:270-300`).

**Files:**
- `sidecar/media_studio/job_store.py` (new) — `JobStore` protocol + `DiskJobStore(root: Path)` (atomic per-job JSON under `root/<jobId>.json`) + `InMemoryJobStore` (test double). Methods: `write(record: dict)`, `load_all() -> list[dict]`, `delete(job_id)`. Record shape: `{jobId, feature, label, videoId, method, params, status, pct, startedAt, finishedAt}`.
- Tests: `sidecar/tests/test_job_store.py` (new).

**Test strategy:** Use a real tmp dir for `DiskJobStore` (filesystem is the unit under test here — that's legitimate, no ffmpeg/network). Assert atomic write (no partial file on crash-sim: write to temp + rename), round-trip `write` → `load_all`, `delete` removes the file, `load_all` on a missing/empty dir returns `[]`, a corrupt/garbage JSON file is skipped (not fatal). `InMemoryJobStore` parity-tested against the same contract.

**Falsifiable acceptance:**
- `write(r)` then `load_all()` returns a record equal to `r` (field-for-field).
- A second `write` with the same `jobId` updates, not duplicates (one file).
- A corrupt file in `root` is skipped and the rest load (a partial-write crash never bricks startup — falsifiable resilience claim).
- `load_all()` on a non-existent root returns `[]` (no crash on first run).
- 100% line+branch (the rename-atomicity path included).

**Gate:** `cd sidecar && pytest --cov-branch --cov-fail-under=100 tests/test_job_store.py`.

---

### WU-6 — `JobRegistry` write-through + rehydrate + `INTERRUPTED` status

**Goal:** Wire `JobStore` into `JobRegistry` (write-through on create / `record_request` / status transitions); on startup, rehydrate records and mark any `running`/`queued` (PENDING) job as a NEW terminal-ish `INTERRUPTED` status — NOT auto-restarted (§5 safety: no silent re-spend).

**Files:**
- `sidecar/media_studio/jobs.py`:
  - Add `INTERRUPTED = "interrupted"` to `JobStatus` (`jobs.py:46-64`). **CONTRACT-NOTE update required:** the enum's existing docstring (`jobs.py:53-60`, verified) pins the wire status set to exactly five values and the `Job.info()` mapping (`jobs.py:166`). Adding a sixth member MUST update that contract-note AND any P1 `job.status` test that asserts the value-set is exactly five (search `test_jobs*.py` for that assertion — it is a real pin per the docstring). `Job.info()` (`jobs.py:159-171`) needs no mapping change (INTERRUPTED is a real value, unlike PENDING→"queued").
  - Inject `JobStore` into `JobRegistry.__init__` (`jobs.py:192-212`, verified signature) with default `= None` → a no-op/in-memory store so all existing `JobRegistry(...)` callers keep working (the existing every-collaborator-injected pattern, `handlers.py:121-180`).
  - Write-through in `create` (`jobs.py:220-245`), `record_request` (`jobs.py:270-292`), and the status-transition points.
  - `rehydrate()`: load records, recreate `Job` shells with stored `request`, map any non-terminal stored status to `INTERRUPTED`. Its `{method, params}` stays available to the existing built-in `job.retry` (`protocol.py:13`, verified).
- `sidecar/media_studio/handlers.py` — construct the registry with a `DiskJobStore` rooted at `data_dir/jobs` (default real store) and call `rehydrate()` at sidecar startup.
- Tests: extend `sidecar/tests/test_jobs.py` (+ a new `test_jobs_persistence.py`).

**Test strategy:** Inject `InMemoryJobStore` (from WU-5). Assert write-through fires on each lifecycle event. Simulate restart: build registry A, create/run jobs, then build registry B sharing the same store → `rehydrate()` marks the non-terminal ones `interrupted`, terminal ones keep their status. Assert a rehydrated job's `request` survives so `job.retry` re-dispatches it (re-dispatch flows back through the dispatch layer — `protocol.py` records the new job, verified `protocol.py:11-14`). NO real ffmpeg/model — job handlers are fakes.

**Falsifiable acceptance:**
- After "restart", a job that was `running` reads `interrupted`; a job that was `done` stays `done` (the rule is falsifiable per-status).
- An `interrupted` job is **never** auto-spawned on rehydrate (assert the pool's run-count stays 0 after rehydrate with no explicit start — the §5 no-silent-spend invariant).
- `job.retry` on a rehydrated `interrupted` job creates a NEW job from the stored `{method, params}`.
- Existing `JobRegistry(...)` callers (no store arg) still pass every prior `test_jobs.py` test (back-compat).
- The P1 `job.status` value-set test is updated to six and passes; the enum docstring contract-note is updated.
- 100% line+branch.

**Gate:** `cd sidecar && pytest --cov-branch --cov-fail-under=100 tests/test_jobs.py tests/test_jobs_persistence.py tests/test_handlers.py`.

---

### WU-7 — `JobInfo` status widening + `canResume` + Resume button (renderer)

**Goal:** Surface `interrupted` jobs with a distinct **Resume** affordance that re-dispatches via `job.retry`, with copy that sets correct cost/progress expectations (§4.3).

**Files:**
- `app/renderer/src/lib/rpc.ts` — widen the `JobInfo.status` union (`rpc.ts:413`, verified: `'queued'|'running'|'done'|'error'|'cancelled'`) to add `'interrupted'`. Purely additive.
- `app/renderer/src/components/JobQueue.tsx`:
  - NEW pure predicate `canResume(job): boolean` → `job.status === 'interrupted'` (sibling of verified `canCancel` `JobQueue.tsx:20-22` and `canRetry` `:25-27`; kept SEPARATE so the button labels differ).
  - Extend the action-gate at `JobQueue.tsx:163` (verified `canCancel(job) || canRetry(job)`) to `... || canResume(job)`.
  - Add a third conditional `<button>` in `jobqueue__actions` that renders when `canResume(job)`, calls the existing `handleRetry(job.jobId)` (`JobQueue.tsx:108-118`, verified), label `Resume`, `aria-label="Resume {label}"`, `title` = the §4.3 microcopy ("Re-runs this interrupted job from the start (restarts at 0%)… you'll be asked to confirm the budget again before it runs.").
  - The status pill already renders `job.status` as TEXT (`JobQueue.tsx:150-152`, verified) — `interrupted` renders correctly with no change; add the status-modifier CSS class value `interrupted`.
- Tests: extend `app/renderer/src/components/JobQueue.test.tsx`.

**Test strategy:** Render a job with `status:'interrupted'` → assert exactly one Resume button (no Cancel, no Retry); assert its `aria-label` and `title`. Render `error` → Retry only (no Resume). Render `running` → Cancel only. Click Resume → fake `rpc('job.retry', {jobId})` called once. Pure predicate `canResume` unit-tested over all six statuses.

**Falsifiable acceptance:**
- `canResume` is true ONLY for `'interrupted'` (table-test all six statuses).
- An `interrupted` job renders a Resume button and NO Retry/Cancel button (the §3.2 a11y bug — without the gate change it would render zero buttons).
- Resume and Retry have distinct accessible names (`Resume {label}` vs `Retry {label}`).
- Clicking Resume invokes `job.retry` with the job's id.
- 100% line+branch (the new button + predicate + gate branch).

**Gate:** `cd app && npx vitest run --coverage app/renderer/src/components/JobQueue.test.tsx`.

---

### WU-8 — `readiness.summary` RPC + `readinessMeta.ts` (pure helper)

**Goal:** A direct RPC rolling up the three readiness sources (assets / advisor / providers) into `[{capability, status, blockedBy, action}]`. Read-only — triggers no download, opens no socket (§5).

**Files:**
- `sidecar/media_studio/handlers.py` — add `Services.readiness_summary(self, params, ctx) -> {items:[ReadinessItem]}`. Sources (all verified):
  - models/features: `_models_present_map` (`handlers.py:1305-1327`) + `system.advisor` component verdicts (`handlers.py:1152-1173`).
  - assets sizes/installed: `assets.list` via the same `AssetManager` (`manager.py:392-402`).
  - providers/keys/consent: `providers.list` (redacted, `handlers.py:330-338`) + `consent.perProvider` (`handlers.py:414-434`) + `routing.perFunction` (`handlers.py:553-573`).
  - Honor Offline mode (a missing weight needing a download counts `unavailable` — same rule `system.advisor` uses). Register in `register_all`.
- `app/renderer/src/components/readinessMeta.ts` (new) — pure label/class/hint map per status (mirrors `advisorMeta.ts:17-50`, verified): `ready→"Ready"`, `needsDownload→"Needs download"`, `needsKey→"Needs key"`, `needsConsent→"Needs consent"`, `unavailable→"Unavailable"`.
- Tests: `sidecar/tests/test_handlers_readiness.py` (new), `app/renderer/src/components/readinessMeta.test.ts` (new).

**Test strategy:** Build `Services` with FAKE asset manager + fake settings (no provider call ever made — assert the provider client is never invoked, the §5 "never call a provider" invariant). Drive each status: no weight + online → `needsDownload`; no key for a cloud-routed function → `needsKey`; consent off → `needsConsent`; offline + missing weight → `unavailable`; all present → `ready`. `readinessMeta` unit-tested over all five statuses.

**Falsifiable acceptance:**
- Each input scenario yields exactly the expected `status` + `blockedBy` + `action.kind` (table-test).
- The response contains **no** full key string (assert redaction; reuse `providers.list` which is already redacted, `handlers.py:330-338`).
- `readiness.summary` performs **zero** network/provider calls and triggers no `assets.ensure` (assert the fakes' call-counts are 0 — the read-only invariant).
- `readinessMeta(status)` returns the exact label for all five statuses; an unknown status falls back safely (defensive branch tested).
- 100% line+branch.

**Gate:** `cd sidecar && pytest --cov-branch --cov-fail-under=100 tests/test_handlers_readiness.py` + `cd app && npx vitest run --coverage app/renderer/src/components/readinessMeta.test.ts`.

---

### WU-9 — `ReadinessBadge` component (renderer)

**Goal:** A shared status pill mirroring the `VerdictBadge` PRIMITIVE (verified `VerdictBadge.tsx:19-31`): text label + `role="status"` + `data-readiness` + `title` — status by text+role, never hue alone (WCAG 1.4.1). Plus the per-item action `<button>` with a capability-tied accessible name.

**Files:**
- `app/renderer/src/components/ReadinessBadge.tsx` (new) — thin render shell over `readinessMeta.ts` (WU-8). Renders the visible label, `role="status"`, `data-readiness="<status>"`, a `title` naming blocker+fix. Reuses ONLY the `verdict-badge` pill geometry CSS (NOT its verdict color map); a parallel readiness class from `readinessMeta`.
- An action `<button>` (or accept an `action` render prop): `assets.ensure` → `aria-label="Download {capability} model"`, `openProviders` → `"Add a provider key"`, `setConsent` → `"Grant consent for {provider}"`. Never icon-only.
- Tests: `app/renderer/src/components/ReadinessBadge.test.tsx` (new).

**Test strategy:** Render each status → assert the visible TEXT label is present (not color-only), `role="status"`, `data-readiness` matches, `title` non-empty. Render each action kind → assert the exact `aria-label`. Assert the badge is a `<span role="status">` and the action is a real `<button>`.

**Falsifiable acceptance:**
- Every status renders a non-empty visible text label (query by text, not by class) — the use-of-color guard.
- `role="status"` and `data-readiness="<status>"` present for all five statuses.
- Each action kind renders a `<button>` with the capability-specific accessible name (no icon-only control passes — query `getByRole('button', {name})`).
- 100% line+branch (all five statuses + all three action kinds branched).

**Gate:** `cd app && npx vitest run --coverage app/renderer/src/components/ReadinessBadge.test.tsx`.

---

### WU-10 — `savePresets.*` RPC (sidecar)

**Goal:** `savePresets.list/apply/upsert/remove` storing a named `{autosave, exportDefaults}` bundle under the `savePresets` settings key — mirrors `providers.applyPreset` exactly (verified `handlers.py:483-501`: resolve → persist to settings).

**Files:**
- `sidecar/media_studio/handlers.py` — four handlers persisting to the `savePresets` settings block via `settings.set` (blind-merge, `settings_store.py:167-182`). `list → {presets, active}`; `apply({name}) → {active, savePreset}` (sets `active`); `upsert({name, autosave?, exportDefaults?}) → {presets}`; `remove({name}) → {presets}`. Register all four in `register_all`.
- Tests: `sidecar/tests/test_handlers_save_presets.py` (new).

**Test strategy:** Fake settings store; round-trip upsert → list → apply → remove. Assert `apply` on a missing name errors (structured `_invalid`, mirroring `providers_apply_preset`'s `ValueError → _invalid`, `handlers.py:494-496`). Assert `remove` of the active preset clears `active`. No I/O beyond the settings doc.

**Falsifiable acceptance:**
- `upsert("a", autosave=X)` then `list()` returns `presets["a"].autosave == X`.
- `apply("a")` sets `active == "a"`; `apply("missing")` raises a structured error (not a crash).
- `remove("a")` drops it from `presets`; removing the active one resets `active` to `""`.
- Sibling settings keys are untouched (blind-merge invariant).
- 100% line+branch (incl. the missing-name and remove-active branches).

**Gate:** `cd sidecar && pytest --cov-branch --cov-fail-under=100 tests/test_handlers_save_presets.py`.

---

### WU-11 — `SavePresetsControls` + export-defaults wiring (renderer)

**Goal:** A renderer control set wiring `savePresets.*` (mirrors `PresetPicker.tsx`, verified to exist) + reading `exportDefaults`/`autosave` from settings to pre-fill export dialogs.

**Files:**
- `app/renderer/src/components/SavePresetsControls.tsx` (new) — list/apply/upsert/remove via the typed client; pattern from `PresetPicker.tsx`.
- `app/renderer/src/lib/rpc.ts` — add `savePresets.*` to the client surface.
- Export call sites — pass stored `exportDefaults` (subtitle fmt, nle fmt/fps) as the default param (the handlers already accept them per-call: `subtitles.export` `handlers.py:763`, `nle.export` `handlers.py:1472`, verified). The sidecar fallback-to-`settings.exportDefaults` is OPTIONAL and out of MVP unless trivial.
- Autosave: debounce `project.save` (`handlers.py:276-287`, verified caller-driven) in the workspace renderer, gated on `autosave.enabled`. **No sidecar change** beyond the WU-0 default key.
- Tests: `app/renderer/src/components/SavePresetsControls.test.tsx` (new) + a focused autosave-debounce test (fake timers, fake rpc).

**Test strategy:** Fake rpc + fake timers. Assert list renders presets; apply calls `savePresets.apply`; upsert/remove call their methods. Autosave: an edit triggers ONE `project.save` after `debounceMs`; rapid edits coalesce to one; `autosave.enabled=false` triggers zero.

**Falsifiable acceptance:**
- With `autosave.enabled=true, debounceMs=1500`, N rapid edits → exactly ONE `project.save` after the debounce window (coalescing is the falsifiable claim).
- With `autosave.enabled=false`, edits trigger ZERO `project.save`.
- Export dialog pre-fills from `exportDefaults` (assert the default value shown).
- 100% line+branch.

**Gate:** `cd app && npx vitest run --coverage app/renderer/src/components/SavePresetsControls.test.tsx`.

---

### WU-12 — `PathsPanel` (renderer)

**Goal:** Show the data layout (`paths.describe`, WU-1) + the existing `dataFolder.*` change-root flow + an "Open folder" button. a11y: real `<button>` per row with a per-row accessible name; path string is selectable text, not inert-interactive.

**Files:**
- `app/renderer/src/components/PathsPanel.tsx` (new) — fetch `paths.describe`; render each dir row with `aria-label="Open {dirLabel} folder"`; wire `dataFolder.get/pick/set` (verified `dataFolderIpc.ts:97-108`) for changing the root; "Open folder" via the existing `shellIpc` channel (`registerShellIpc`, verified `main.ts` + `dataFolderIpc.ts:16`) — reuse, no new channel unless "open arbitrary path" needs one (then a NEW traversal-checked `paths.openFolder`; keep out of MVP if `shellIpc` covers it).
- Tests: `app/renderer/src/components/PathsPanel.test.tsx` (new).

**Test strategy:** Fake rpc returning a `paths.describe` payload. Assert each dir row renders its path as text + an "Open folder" `<button>` with the row-specific accessible name. Assert "Change data folder" calls `dataFolder.pick` then `dataFolder.set`. Loading state covered.

**Falsifiable acceptance:**
- Each dir row exposes a button via `getByRole('button', {name:/Open .* folder/})` (no icon-only control).
- The path string is rendered as text (queryable), not as a button.
- Change-root calls `dataFolder.pick` → `dataFolder.set` in order.
- 100% line+branch.

**Gate:** `cd app && npx vitest run --coverage app/renderer/src/components/PathsPanel.test.tsx`.

---

### WU-13 — App `lastOpenedVideoId` persist + restore (renderer)

**Goal:** Persist the last-opened video on `openVideo` and restore it on launch — pure settings + renderer state, NO new RPC (§3.2).

**Files:**
- `app/renderer/src/App.tsx`:
  - On `openVideo` (`App.tsx:109-111`, verified), `settings.set({lastOpenedVideoId: id})`.
  - In the launch `settings.get` effect (`App.tsx:84-99`, verified — already hydrates the quality toggle), read `lastOpenedVideoId`, resolve via `library.list` (the exact pattern of `handleReexport`, `App.tsx:136-148`, verified), navigate to workspace. Fall back to Library when the video is gone (same fallback as `handleReexport`, `App.tsx:144-148`).
- Tests: extend `app/renderer/src/App.test.tsx` (if present; else new focused test).

**Test strategy:** Fake rpc. Launch with `lastOpenedVideoId` present + in `library.list` → navigates to workspace for that id. Present but absent from list → stays on Library (best-effort fallback). Empty key → stays on Library (default `route='library'`, `App.tsx:77`). `openVideo` persists the key.

**Falsifiable acceptance:**
- A valid `lastOpenedVideoId` → route becomes workspace for that id on launch.
- A stale id (not in `library.list`) → route stays Library, no crash (the fallback invariant).
- `openVideo(id)` triggers exactly one `settings.set({lastOpenedVideoId:id})`.
- 100% line+branch (restore-success, restore-fallback, empty-key branches).

**Gate:** `cd app && npx vitest run --coverage app/renderer/src/App.test.tsx`.

---

### WU-14 — Wire badges + thumbnails into library + model panels (integration)

**Goal:** Consume `useVideoThumbnail` on library cards and `ReadinessBadge` on the library home + model panel — the surfacing payoff.

**Files:**
- `app/renderer/src/features/` library home component (the one rendering `library-cards.css` cards, per design §1) — render the poster via `useVideoThumbnail` (WU-4) with the ▶ glyph fallback; render `ReadinessBadge` (WU-9) roll-up driven by `readiness.summary` (WU-8), reusing JobQueue's skeleton/empty conventions (`jobqueue__empty`, `JobQueue.tsx:142-162`, verified) while in flight.
- Model panel (`Assets.tsx` / `ModelCard.tsx`, verified to render install state, `Assets.tsx:13-39` / `ModelCard.tsx:18-107`) — add the `ReadinessBadge` roll-up where appropriate (reuse, don't duplicate the existing `VerdictBadge`).
- Tests: extend the relevant feature test files.

**Test strategy:** Fake rpc (`library.thumbnail`, `readiness.summary`). Assert a card renders the poster URL when available and the ▶ glyph when generation fails (graceful, inheriting WU-4). Assert the readiness roll-up renders one `ReadinessBadge` per item with its action button. Assert the in-flight skeleton shows before data resolves.

**Falsifiable acceptance:**
- A card with a resolvable thumbnail renders the `thumb:` `<img>`; a failing one renders the ▶ glyph (gallery never breaks).
- The readiness roll-up renders N badges for N `readiness.summary` items, each with its capability-tied action button.
- In-flight state renders the reused skeleton (no bespoke loader).
- 100% line+branch on the wiring.

**Gate:** `cd app && npx vitest run --coverage` (the affected feature test files).

---

## 3. Dependency graph

```
WU-0 (settings + types scaffold)
 ├─► WU-1 (paths.describe) ─────────────► WU-12 (PathsPanel)
 ├─► WU-2 (library.thumbnail+schema) ──► WU-3 (thumb: resolver) ──► WU-4 (useVideoThumbnail) ─┐
 ├─► WU-5 (JobStore) ──► WU-6 (registry write-through+rehydrate+INTERRUPTED) ──► WU-7 (canResume+Resume)
 ├─► WU-8 (readiness.summary + readinessMeta) ──► WU-9 (ReadinessBadge) ───────────────────────┤
 ├─► WU-10 (savePresets.*) ──► WU-11 (SavePresetsControls + autosave/export-defaults)          │
 └─► WU-13 (lastOpenedVideoId)                                                                  │
                                                                                               ▼
                                                          WU-14 (wire thumbnails + badges into panels)
```

Critical path (longest): `WU-0 → WU-5 → WU-6 → WU-7` (the resume spine) and `WU-0 → WU-2 → WU-3 → WU-4 → WU-14`. WU-14 is the only multi-parent join.

---

## 4. Parallelism notes

After WU-0 lands (it touches shared files — `settings_store.py`, `rpc.ts` — so it goes FIRST, alone, to avoid index contamination), the five feature tracks are **file-disjoint and parallelizable**:

- **Track A — Save locations:** WU-1 → WU-12.
- **Track B — Thumbnails:** WU-2 → WU-3 → WU-4 (→ WU-14).
- **Track C — Resume (highest risk):** WU-5 → WU-6 → WU-7. Sequence strictly; do NOT parallelize within (each extends the same `jobs.py`).
- **Track D — Readiness:** WU-8 → WU-9 (→ WU-14).
- **Track E — Save options:** WU-10 → WU-11; WU-13 is independent and can run any time after WU-0.

**Shared-file hazards (one owner each):**
- `handlers.py` (`register_all`) is touched by WU-1/2/6/8/10 — they each add a handler + one `register(...)` line. To avoid the shared-worktree index contamination noted in prior lessons: if running parallel agents, give each its OWN worktree, OR mandate scoped adds (`git add <specific files>`; `git diff --cached --name-only` before every commit) and serialize the `register_all` edits. **Recommend serializing the `handlers.py` edits** (the register block is a single one-owner hotspot).
- `rpc.ts` is touched by WU-0/4/7/11 — additive client surface; same scoped-add discipline.
- WU-14 is the integration join — run it LAST, after WU-4 and WU-9 (and ideally WU-8) are merged.

**WU-0 and WU-14 are serialization points** (first and last); everything between fans out into 5 tracks.

---

## 5. Risk register (falsifiable mitigations)

| Risk | WU | Mitigation (testable) |
|------|----|----|
| Job persistence is new substrate — could corrupt startup | WU-5/6 | Corrupt-file-skip test + `load_all([])` on empty dir + atomic rename test. A bad record never bricks rehydrate. |
| Resumed AI job silently re-spends cloud budget | WU-6/7 | Rehydrated jobs are `interrupted`, NEVER auto-spawned (assert run-count 0). `job.retry` re-flows through `_enforce_cloud_budget_ack` (`handlers.py:1672-1691`); stale `cacheKey` ≠ fresh → re-prompt. Resume copy states the re-prompt up front. |
| `thumb:` becomes an arbitrary-disk read | WU-3 | Reuse `resolveScopedMediaPath` (`exportPath.ts:20`); traversal tests assert ANY path outside `data_dir/thumbnails` → `null`. |
| Adding `INTERRUPTED` breaks the P1 `job.status` value-set pin | WU-6 | The enum docstring (`jobs.py:53-60`) pins five values; update the contract-note + the test asserting exactly-five. Falsifiable: the updated test passes at six. |
| `ReadinessBadge` regresses to color-only (WCAG 1.4.1) | WU-9 | Query by visible TEXT label, not class; assert `role="status"` + `data-readiness`. |
| `readiness.summary` accidentally calls a provider / triggers a download | WU-8 | Assert fakes' provider/ensure call-counts are 0 (read-only invariant). |
| Parallel agents contaminate `handlers.py`/`rpc.ts` index | all | Serialize `register_all` edits OR isolated worktrees + scoped adds; never `git add -A`. |

---

## 6. Capability gaps carried from DESIGN §6 (no fabrication)

1. **No job persistence today** (`jobs.py:270-300`, verified zero file I/O) — WU-5/6 is the genuinely new substrate.
2. **No mid-job resume** — job bodies are opaque `(JobContext)->result` (`jobs.py:304-326`); Resume = full re-dispatch (a 90% transcribe restarts at 0%). Documented limitation; the Resume copy (WU-7) makes it visible. NOT solved here.
3. **No source-video thumbnail** before WU-2 (`Video` has no `thumbnailPath`, `library.py:108-117`).
4. **No unified readiness view** before WU-8 (split across `assets.list` / `system.advisor` / `providers.list`).
5. **No autosave / shared export presets** before WU-10/11 (`project.save` caller-driven, `handlers.py:276-287`; only routing presets exist, `handlers.py:483`).
6. **Per-feature `outputDir` deliberately rejected** (`settings_store.py:34-40`) — OUT of scope; this bundle surfaces the ONE root only.
7. **No `thumb:` resolver branch** before WU-3 (only `short:`/`dub:` exist, `main.ts:436-459`).

---

## 7. Gate commands (bundle-level — for the eventual `feat/ux-qol` impl branch, NOT this docs branch)

Run from the impl branch before any commit/PR; never `--no-verify`, never `git add -A`:

- **Sidecar:** `cd sidecar && pytest --cov-branch --cov-fail-under=100`
- **Renderer:** `cd app && npx vitest run --coverage` (thresholds 100/100/100/100 enforced by `app/vitest.config.ts:44-49`)
- **Lint/type (sidecar):** `cd sidecar && ruff check . && basedpyright`
- **Lint/type (app):** `cd app && npx tsc --noEmit && npx oxlint && npx biome check .`
- **Scoped adds only:** `git add <specific files>`; verify with `git diff --cached --name-only` before each commit.

Heavy-ML / real-ffmpeg bodies stay `# pragma: no cover`; the ffmpeg / job-store / provider / OCR seams are injected and fully covered by fakes.
