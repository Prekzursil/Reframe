# Reframe — "UX / QoL" Bundle — DESIGN

Branch: `feat/ux-qol-design` (off `origin/main`). DESIGN + PLAN docs only — **no feature code in this branch.**

## 0. Scope (what this bundle covers)

Five quality-of-life capabilities, all wiring on the shipped Hub substrate:

1. **Save locations** — where projects / exports / data live, and making them configurable + visible.
2. **Resume / pick-up** — reopen the last project on launch, and continue (re-dispatch) an in-progress job after a restart.
3. **Save options** — autosave, export formats, and named presets for the save/export choices.
4. **Availability indicators** — badges showing which models / features / providers are ready vs need a download / key / consent.
5. **UI preview thumbnails** — generate, store and render poster frames for library videos and project clips.

**Explicitly OUT of scope (separate bundle):** AI best-frame thumbnail *selection*. This bundle covers only the UI rendering + storage of thumbnails; frame *choice* stays the dumb "poster at offset" path that `shorts.thumbnail` already ships.

---

## 1. Real-code seam map (cited)

Every capability below reuses already-shipped seams. Citations are `path:line` in this repo at `origin/main`.

### Composition root / RPC site
- The ONE registration site is `register_all` — `sidecar/media_studio/handlers.py:1982`, which calls `protocol.register(name, handler)` for ~30 methods and delegates to feature modules' own `register()` (`handlers.py:2072-2237`). Every new `*.*` handler MUST land here.
- `protocol.register` raises on a duplicate name (`sidecar/media_studio/protocol.py:79-91`) — a double-wire fails loudly at startup.
- Built-ins already present: `job.list` (JobInfo list) + `job.retry` (re-dispatch the stored request as a NEW job) + `job.cancel` / `job.status` (`protocol.py:13-14`).

### Save locations (LARGELY SHIPPED — main-process IPC, NOT sidecar RPC)
- `Services` derives **all** on-disk locations from ONE data dir: `data_dir`, `projects_dir = base/"projects"`, `exports_dir = base/"exports"`, `settings.json`, `library.json` (`handlers.py:143-148`). Per-feature out-dirs all hang off `exports_dir` (e.g. `shorts-<vid>`, `stabilized`, `audiomix`, `trimmed`, `dubs` — `handlers.py:1351,2119,2164-2182`).
- The data root is **relocatable** via `MEDIA_STUDIO_CONFIG_DIR` (env) → `data-dir.txt` marker → `<exeDir>/data` → `%APPDATA%/media-studio`, resolved by the pure `chooseDataRoot` / `resolveDataRootFrom` (`app/main/dataRoot.ts:58-110`).
- The user-facing "Change data folder" flow already exists as 3 main-process IPC channels: `dataFolder.get` / `dataFolder.pick` (native dir picker) / `dataFolder.set` (writes the marker, restart-applies) — `app/main/dataFolderIpc.ts:97-108`. The marker write is fail-soft (`dataFolderIpc.ts:78-90`).
- `settings_store.py:34-40` documents the deliberate decision: there is **no per-key `outputDir`** — ONE root relocates everything (`default_config_dir()` at `settings_store.py:88-103`).
- Scoped-media security: `resolveScopedMediaPath` traversal-guards the `short:` / `dub:` resolvers so the privileged `mstream://` scheme cannot read arbitrary disk (`app/main/exportPath.ts:20-24`). Any new served path (project thumbnails) MUST reuse this guard.

### Resume / pick-up
- Projects already persist: one manifest per video at `projects_dir/<videoId>.json` (`handlers.py:204-218`); `project.open` lazily creates one (`handlers.py:265-274`); `Project.open` / `.save` are atomic (`library.py:223-253`).
- The library index persists videos (`library.py:120-189`), each with `hasTranscript` (`library.py:116`).
- **Jobs do NOT persist.** `JobRegistry` holds jobs in an in-memory `self._jobs` dict; `record_request` / `get_request` store the originating `{method, params}` **in memory only** (`jobs.py:270-300`) — there is zero file I/O in `jobs.py`. After a process restart `job.list` is empty and `job.retry` has nothing to re-dispatch. **This is the central capability gap for "continue an in-progress job after restart."**
- Renderer: `App` always starts at `route = {name:'library'}` (`app/renderer/src/App.tsx:77`); it hydrates the quality toggle from `settings.get` (`App.tsx:84-99`) but never restores the last-opened video. `handleReexport` already shows the pattern for "resolve a video id via `library.list`, then navigate" (`App.tsx:136-148`).

### Save options (autosave / formats / presets)
- Settings are a single merged JSON doc; `settings.set` blindly merges any keys (`settings_store.py:167-182`), and `DEFAULT_SETTINGS` lists keys for first-launch discoverability (`settings_store.py:41-80`). New QoL keys are pure additive merges — no schema migration needed.
- Export formats already exist per feature: subtitles `subtitles.export({format})` (`handlers.py:763-774`), NLE `nle.export({format:edl|csv, fps})` (`handlers.py:1472-1494`), package `package.export` (`handlers.py:1499-1533`). There is **no shared "export preset"** concept and **no autosave** today — `project.save` is caller-driven (`handlers.py:276-287`).
- A preset precedent exists for *routing*: `providers.applyPreset` resolves a named preset and persists it (`handlers.py:483-501`); the shortmaker has UI-side presets (`app/renderer/src/features/shortMakerPresets.ts`).

### Availability indicators
- **Models:** `assets.list` returns `AssetInfo {name, kind, sizeMB, installed, dest}` (`sidecar/media_studio/assets/manager.py:392-402`); `assets.ensure` downloads (`assets/rpc.py:40-63`); registered at `handlers.py:2233`. `installed_path` is the real probe (`manager.py:360-375`). Renderer `Assets.tsx` already renders install state + per-asset / install-all (`app/renderer/src/features/Assets.tsx:13-39`); `ModelCard.tsx` already renders a will-it-run badge (via the `VerdictBadge` component) + Installed/Download button (`app/renderer/src/components/ModelCard.tsx:18-107`).
- **Features (tiers):** `system.advisor` returns per-component `present`/`verdict` + runnable tiers (`handlers.py:1152-1173`, wire shape `_advisor_report_to_wire` at `handlers.py:1902-1928`); `asr.engines` returns `[{id,label,installed}]` (`handlers.py:1175-1194`). `_models_present_map` (`handlers.py:1305-1327`) is the per-component installed probe.
- **Providers:** `providers.list` (redacted keys, `handlers.py:330-338`), `providers.usage` (live + cached + stale-flagged, `handlers.py:436-478`), per-provider `consent.perProvider[].{text,frames}` (`handlers.py:414-434`). `routing.perFunction` says which provider each function prefers (`handlers.py:553-573`).
- **Gap:** the three readiness sources (assets / advisor / providers) are surfaced by **three separate panels**; there is no single roll-up "is X ready, and if not, what's the one action to make it ready?" view.

### UI preview thumbnails
- **Clip thumbnails: shipped.** `shorts.thumbnail({path}) -> {thumbnailPath}` ffmpeg-extracts `<clip>.thumb.jpg` idempotently (`sidecar/media_studio/features/shorts.py:16-17,102-103,183`); ShortInfo already carries `thumbnailPath` (`shorts.py:31,267`). Renderer `useShortThumbnail` generates on demand + serves via the `short:` mstream resolver (`app/renderer/src/components/useShortThumbnail.ts:28-73`).
- **Gap: library-video thumbnails do NOT exist.** A `Video` is `{id, path, title, addedAt, durationSec, hasTranscript}` (`library.py:108-117`) — **no `thumbnailPath`**. The library home renders cards (`library-cards.css`) with no poster; there is no RPC to extract a poster for a *source* video (only for an exported *clip*).

### AI / Hub envelope (only the resume-job + budget-touching parts)
- `plan_ai_job` (PURE) / `run_ai_job` (cache-first, degrade-aware) ride the ONE job bus (`sidecar/media_studio/models/ai_job.py:204-308`). `Services._run_ai_job` plans + enforces the budget-ack gate + runs (`handlers.py:1617-1691`); `ai.planJob` is the pre-flight returning `{route,costEst,cacheHit,willEgress,budget,preview,cacheKey}` (`handlers.py:1693-1718`).
- The budget-ack gate fires only when `confirmCloudBudget` is on AND `route.willEgress` (`handlers.py:1672-1691`). **Implication for resume:** any resumed AI job that would egress must re-run `ai.planJob` and re-acknowledge — a stale `cacheKey` from before restart must NOT be silently trusted.
- Rotation pool: `provider.get_provider` / `build_pool_provider` (`sidecar/media_studio/models/provider.py`), built from RAW keys via `settings.get_raw()` (`handlers.py:584,1599`).

---

## 2. User value + MVP cut

| # | Capability | User value | MVP (this bundle) | Deferred |
|---|------------|-----------|-------------------|----------|
| 1 | Save locations | "I can see where my stuff lives and put it on a big drive." | Surface the resolved data root + sub-dirs (read-only display) via a new `paths.describe` RPC; the existing `dataFolder.*` IPC already changes the root. Add an "Open folder" affordance. | Per-feature output redirection (deliberately rejected by `settings_store.py:34-40`). |
| 2 | Resume / pick-up | "Reopen where I was; finish the job the crash interrupted." | (a) Restore last-opened video on launch via a `lastOpenedVideoId` setting. (b) **Persist job records to disk** so `job.list` survives restart and `job.retry` can re-dispatch an interrupted job. | Live mid-job checkpoint/resume (re-runs the whole job, not mid-stream). |
| 3 | Save options | "Autosave my edits; remember my export format." | (a) `autosave` setting → project auto-persist debounce in the workspace. (b) `exportDefaults` settings block (subtitle fmt, nle fmt/fps). (c) Named `savePresets` via new `savePresets.*` RPC (mirrors `providers.applyPreset`). | Cloud sync; versioned project history. |
| 4 | Availability indicators | "One place that tells me what's ready and the one button to fix it." | A new `readiness.summary` RPC that rolls up assets + advisor + providers into `[{capability, status, blockedBy, action}]`; a renderer `ReadinessBadge` reused across panels. | Auto-remediation (one-click fix actions chain). |
| 5 | Preview thumbnails | "See a poster on every video + clip card." | (a) NEW `library.thumbnail({videoId}) -> {thumbnailPath}` reusing the shorts ffmpeg poster path; persist `thumbnailPath` onto the Video. (b) A renderer `useVideoThumbnail` mirroring `useShortThumbnail`, served via a traversal-guarded resolver. | AI best-frame selection (separate bundle). |

**MVP altitude:** capabilities 1, 4, 5(a) are mostly *surfacing* existing data (cheap, high-value). Capability 2(b) (job persistence) is the only genuinely new substrate and is the highest-risk item — it gets the most design attention below.

---

## 3. Architecture — reuse vs NEW

### 3.1 Save locations (REUSE almost entirely)
- **REUSE:** `dataFolder.get/pick/set` IPC (`dataFolderIpc.ts`), `chooseDataRoot` (`dataRoot.ts`), `Services.{data_dir,projects_dir,exports_dir}` (`handlers.py:143-148`).
- **NEW (small):** one sidecar RPC `paths.describe()` → `{dataDir, projectsDir, exportsDir, settingsPath, libraryPath, subDirs:{shorts,dubs,...}}` so the renderer can *show* the layout (today it can only get the root via `dataFolder.get`). Read-only; derives from `Services` fields. Registered in `register_all`.
- **NEW (renderer):** a `PathsPanel` (or a section in an existing Settings panel) wiring `dataFolder.*` + `paths.describe` + a shell "open folder" (reuse the existing `shellIpc` pattern referenced by `dataFolderIpc.ts`).

### 3.2 Resume / pick-up (NEW substrate: job persistence)
- **Resume project (REUSE + tiny NEW):** persist `lastOpenedVideoId` via `settings.set` on `openVideo` (`App.tsx:109-111`); on launch read it in the existing `settings.get` effect (`App.tsx:84-99`), resolve via `library.list` (same pattern as `handleReexport`, `App.tsx:136-148`), navigate to workspace. Pure settings + renderer state — **no new RPC.**
- **Resume job (NEW — the load-bearing piece):**
  - Add a **`JobStore`** (NEW module `sidecar/media_studio/job_store.py`) that the `JobRegistry` writes through: on `create` / `record_request` / status transitions it appends/updates a JSON-lines (or per-job JSON) record under `data_dir/jobs/` with `{jobId, feature, label, videoId, method, params, status, pct, startedAt, finishedAt}`. Reuses the atomic `_write_json` pattern (`library.py:74-79`).
  - On sidecar startup, `JobRegistry` **rehydrates** records: any job left in `running`/`queued` at last shutdown is marked `interrupted` (a NEW terminal-ish status) — it is NOT auto-restarted (that would silently re-spend a cloud budget). Its stored `{method, params}` remains available to `job.retry`.
  - `job.list` then includes interrupted jobs after restart; the user clicks "Resume" → `job.retry` (existing built-in, `protocol.py:13`) re-dispatches the stored request as a NEW job.
  - **JobQueue rendering path for `interrupted` (a11y-critical — without this the Resume button never appears).** `JobQueue.tsx` gates ALL per-job actions on the outer predicate `canCancel(job) || canRetry(job)` (`app/renderer/src/components/JobQueue.tsx:163`), and `canRetry` matches **only** `status === 'error'` (`JobQueue.tsx:25-27`). An `interrupted` job matches neither, so today it would render no action button at all. The two exact change points are:
    1. **NEW predicate** `canResume(job): boolean` in `JobQueue.tsx` returning `job.status === 'interrupted'` (a sibling of `canCancel`/`canRetry`, kept separate so the Resume affordance is distinct from Retry — see copy below). It MUST stay a separate predicate rather than folding `interrupted` into `canRetry`, because the two buttons carry different labels/tooltips.
    2. **Extend the outer action-gate** at `JobQueue.tsx:163` to `canCancel(job) || canRetry(job) || canResume(job)`, and add a third conditional button inside the `jobqueue__actions` block (alongside Cancel/Retry) that renders when `canResume(job)` and calls the existing `handleRetry(job.jobId)` (`JobQueue.tsx:108-118`) — Resume reuses the `job.retry` re-dispatch; only the label/tooltip differ.
    The `interrupted` status string already renders correctly in the status pill (`JobQueue.tsx:150-152` renders `job.status` as **text**, not color-only) and the `JobInfo` status union (`lib/rpc`) MUST be widened to include `'interrupted'`.
  - **Injectability:** `JobStore` is injected into `JobRegistry.__init__` (default = real disk store under `data_dir/jobs`; tests inject an in-memory fake), preserving the existing test pattern (every `Services` collaborator is injected — `handlers.py:121-180`).
- **Why not mid-job checkpointing:** jobs are opaque `(JobContext)->result` bodies (`jobs.py:304-326`); there is no general resumable checkpoint. Re-dispatch from the stored request is the honest, contract-safe resume. **Named gap** (§5).

### 3.3 Save options (REUSE patterns; NEW keys + one RPC)
- **Autosave (REUSE):** additive `autosave:{enabled,debounceMs}` settings block; the *workspace renderer* debounces `project.save` (`handlers.py:276-287`) on edit — **no sidecar change** beyond the default key in `DEFAULT_SETTINGS`.
- **Export defaults (REUSE):** additive `exportDefaults:{subtitleFormat, nleFormat, nleFps}` in `DEFAULT_SETTINGS`; the export handlers already accept these per-call (`handlers.py:763,1472`) — renderer passes the stored defaults. No handler change required, but the export handlers MAY fall back to `settings.exportDefaults` when a param is omitted (small, optional).
- **Save presets (NEW RPC, mirrors routing presets):** `savePresets.list/apply/upsert/remove` storing a named `{autosave, exportDefaults}` bundle under a `savePresets` settings key. Mirrors `providers.applyPreset` exactly (`handlers.py:483-501`) — same persist-to-settings shape, registered in `register_all`.

### 3.4 Availability indicators (NEW roll-up RPC over existing data)
- **NEW RPC `readiness.summary()`** → `{items:[{capability, status:"ready"|"needsDownload"|"needsKey"|"needsConsent"|"unavailable", blockedBy, sizeMB?, action:{kind:"assets.ensure"|"openProviders"|"setConsent", payload}}]}`.
  - Source 1 (models/features): `_models_present_map` + `system.advisor` component verdicts (`handlers.py:1152-1327`).
  - Source 2 (assets sizes/installed): `assets.list` via the same `AssetManager` (`manager.py:402`).
  - Source 3 (providers/keys/consent): `providers.list` + `consent` + `routing.perFunction` (`handlers.py:330-434,553-573`).
  - Honors Offline mode (a missing weight that needs a download counts unavailable — same rule as `system.advisor`).
- **REUSE renderer:** `Assets.tsx` ensure flow + the `verdict-badge` status-pill conventions; new shared `ReadinessBadge` component consumed by the library home + model panel.
- **`ReadinessBadge` accessibility contract (a11y-critical — follow the `VerdictBadge` *component*, not loose CSS classes):** the real reusable status-pill primitive is `VerdictBadge.tsx` (`app/renderer/src/components/VerdictBadge.tsx:19-31`), which renders a **text label** (`verdictLabel`, `advisorMeta.ts:38-40`), `role="status"`, a status-modifier `data-*` attribute, and a descriptive `title` hint — so the status is conveyed by *text + role*, never hue alone. `ReadinessBadge` MUST mirror this exactly and MUST NOT reduce to color-only class reuse (that would fail WCAG 1.4.1 use-of-color and drop status semantics). Concretely:
  - Render a **visible text label per status** (e.g. `ready → "Ready"`, `needsDownload → "Needs download"`, `needsKey → "Needs key"`, `needsConsent → "Needs consent"`, `unavailable → "Unavailable"`) — color is decorative reinforcement, never the sole carrier.
  - Set `role="status"` so assistive tech announces it as a live status (same as `VerdictBadge.tsx:25`).
  - Carry a `data-readiness="<status>"` attribute and a `title` that names the blocker + the fix action (mirrors `VerdictBadge`'s `data-verdict` + `title`).
  - Reuse only the *pill geometry* CSS conventions (the `verdict-badge` base look), not its verdict-specific color map; add a parallel readiness-status label/class/hint map in a pure `readinessMeta.ts` helper (mirroring `advisorMeta.ts:17-50`) so the label/class/hint logic is test-pinned once and the component stays a thin render shell.
- **Roll-up action affordance (a11y):** each item's `action` (`assets.ensure` / `openProviders` / `setConsent`) MUST render as a real `<button>` with an accessible name tying the action to its capability (e.g. `aria-label="Download {capability} model"` / `"Add a provider key"` / `"Grant consent for {provider}"`), never an icon-only control. The badge conveys *state*; the button conveys *the one fix action*.
- **Empty / loading states:** while `readiness.summary` is in flight, reuse JobQueue's existing skeleton/empty conventions (`jobqueue__empty`, the progress bar pattern, `JobQueue.tsx:142-162`) for visual consistency rather than inventing new ones.

### 3.5 Preview thumbnails (REUSE the shorts poster engine)
- **NEW RPC `library.thumbnail({videoId}) -> {thumbnailPath}`** — extracts a poster from the *source* video (not a clip) by **reusing `shorts.build_thumbnail_argv` / `thumbnail_path`** (`shorts.py:102,183`) against the resolved source path (`handlers.py:197-202`); persists `thumbnailPath` onto the Library Video and returns it. Idempotent (poster file is cached next to nothing user-owned → store under `data_dir/thumbnails/<videoId>.jpg`, inside the data root so the resolver can serve it).
- **NEW (Video schema):** add optional `thumbnailPath` to `library._normalize` (`library.py:108-117`) — additive, backfilled to `""`; no migration.
- **NEW (resolver):** a `thumb:` id branch for `mstream://` reusing `resolveScopedMediaPath` (`exportPath.ts:20`) rooted at `data_dir/thumbnails`. (Clips keep the existing `short:` resolver.)
- **REUSE renderer:** new `useVideoThumbnail` hook = a near-clone of `useShortThumbnail` (`useShortThumbnail.ts:41-73`) pointed at `library.thumbnail` + the `thumb:` URL. It MUST inherit `useShortThumbnail`'s proven graceful-degradation: a missing/failed poster falls back to the ▶ glyph and **never blocks the card** (`useShortThumbnail.ts:28-39` catch path), so a thumbnail-generation failure degrades silently instead of breaking the gallery. While generation is pending, show the same placeholder rather than a layout-shifting blank.

---

## 4. RPC + renderer + storage surface

### 4.1 New sidecar RPC handlers (all wired in `register_all`, `handlers.py:1982`)
| Method | Shape | Job? | Reuses |
|--------|-------|------|--------|
| `paths.describe` | `() -> {dataDir, projectsDir, exportsDir, settingsPath, libraryPath, subDirs}` | direct | `Services` fields |
| `library.thumbnail` | `({videoId}) -> {thumbnailPath}` | direct (fast ffmpeg) | `shorts.build_thumbnail_argv`, `_resolve_video_path`, `library.set_*` |
| `readiness.summary` | `() -> {items:[ReadinessItem]}` | direct | `_models_present_map`, `assets.list`, `providers.list`, `consent` |
| `savePresets.list` | `() -> {presets, active}` | direct | settings doc |
| `savePresets.apply` | `({name}) -> {active, savePreset}` | direct | mirrors `providers.applyPreset` |
| `savePresets.upsert` | `({name, autosave?, exportDefaults?}) -> {presets}` | direct | settings merge |
| `savePresets.remove` | `({name}) -> {presets}` | direct | settings merge |
| `jobs.history` *(optional)* | `({limit?}) -> {jobs}` incl. interrupted | direct | `JobRegistry.list_info` after rehydrate |

`job.list` / `job.retry` / `job.cancel` are **existing built-ins** (`protocol.py:13-14`) — resume reuses them; only the persistence-backed rehydrate is new. No new job-control RPC needed beyond the optional `jobs.history`.

**Renderer type change for resume:** the `JobInfo` status union in `lib/rpc` MUST be widened to add `'interrupted'` (today: `queued`/`running`/`error`/done states). This unblocks the new `canResume` predicate (§3.2) and lets the status pill render the `interrupted` label as text (`JobQueue.tsx:150-152`). It is purely additive — no existing status is removed or renamed.

### 4.2 Main-process IPC (REUSE; no new channels required)
- `dataFolder.get/pick/set` (`dataFolderIpc.ts`) — already cover changing the data root.
- One **NEW** optional channel `paths.openFolder(path)` (shell-open, traversal-checked) if "Open folder" is in MVP; otherwise reuse the existing `shellIpc` channel referenced by `dataFolderIpc.ts:16`.

### 4.3 Renderer surface
- `useVideoThumbnail` hook (clone of `useShortThumbnail.ts`).
- `ReadinessBadge` shared component (mirrors the `VerdictBadge` primitive — text label + `role="status"` + `data-readiness` + `title`; reuses only the `verdict-badge` pill geometry, not the verdict color map — see §3.4). Backed by a pure `readinessMeta.ts` label/class/hint map.
- `PathsPanel` section (wires `paths.describe` + `dataFolder.*`). **a11y:** each path row is read-only but its "Open folder" control MUST be a real `<button>` with a per-row accessible name (e.g. `aria-label="Open {dirLabel} folder"`), keyboard-focusable in tab order; the path string itself is presented as selectable text, not an interactive-looking-but-inert element.
- `SavePresetsControls` (wires `savePresets.*`, mirrors `PresetPicker.tsx`).
- App-level: `lastOpenedVideoId` persist on `openVideo` + restore in the launch `settings.get` effect (`App.tsx:84-148`).
- JobQueue: render the `interrupted` status + a **Resume** button → `job.retry` (extend `JobQueue.tsx` per the §3.2 two change points: new `canResume` predicate + widen the `JobQueue.tsx:163` action-gate).
  - **Resume vs Retry — distinct affordance + user-facing copy (a11y/clarity-critical).** Both buttons re-dispatch via `job.retry`, but their UX intent differs (crash-recovery vs explicit failure-retry), so they MUST read differently and the Resume copy MUST set correct expectations about cost and progress:
    - **Button label:** `Resume` (distinct from the `Retry` label on `error` jobs). Accessible name MUST disambiguate by job, e.g. `aria-label="Resume {label}"` (Retry stays `aria-label="Retry {label}"`).
    - **Tooltip / microcopy (`title`):** convey full re-dispatch + budget re-prompt, e.g. *"Re-runs this interrupted job from the start (it restarts at 0%, not where it stopped). If it uses a cloud provider, you'll be asked to confirm the budget again before it runs."* This makes the §5 safety reality (full re-dispatch through `_run_ai_job` → `_enforce_cloud_budget_ack`, re-prompting on cloud egress) visible at the point of action so Resume is never a surprise spend.
    - Optionally surface a short inline note on the `interrupted` item (e.g. "Interrupted by restart — Resume to re-run from the start") so the status reads as crash-recovery, not generic failure. This note is **text**, reinforcing the already-text status pill (`JobQueue.tsx:150-152`).

### 4.4 Storage + settings keys (all additive — `settings.set` blind-merges, `settings_store.py:167-182`)
```
DEFAULT_SETTINGS additions:
  lastOpenedVideoId: ""
  autosave: { enabled: true, debounceMs: 1500 }
  exportDefaults: { subtitleFormat: "srt", nleFormat: "edl", nleFps: 30 }
  savePresets: { presets: {}, active: "" }
On-disk NEW dirs (under the ONE data root):
  data_dir/jobs/        # persisted job records (rehydrate source)
  data_dir/thumbnails/  # <videoId>.jpg posters
Library Video schema:  + thumbnailPath: ""  (library._normalize)
```
No secrets in any new payload. `paths.describe` returns only directory paths (no keys); `readiness.summary` returns booleans + redacted provider names (never keys — reuse `providers.list` which is already redacted, `handlers.py:330-338`).

---

## 5. Reversibility / safety + (AI parts) consent & budget

- **Save locations:** `dataFolder.set` only writes the marker; it **does not move files** (`dataFolderIpc.ts:5-13`) — a restart applies the new root; the old tree is untouched (fully reversible). `paths.describe` is read-only.
- **Resume project:** `lastOpenedVideoId` is a single settings key; restoring is best-effort and falls back to Library when the video is gone (same fallback as `handleReexport`, `App.tsx:144-148`). Reversible (clear the key).
- **Resume job (safety-critical):** rehydrated jobs are marked `interrupted` and **never auto-restarted** — the user must explicitly click Resume. This prevents a crash from silently re-spending a cloud budget. When a resumed job is an AI job that would egress, `job.retry` re-dispatches the original `{method, params}`, which flows back through `_run_ai_job` → `_enforce_cloud_budget_ack` (`handlers.py:1672-1691`): a stale pre-restart `confirmBudget` token will NOT match the freshly-planned `cacheKey`, so the user is correctly re-prompted to `ai.planJob` + re-acknowledge. **The budget/consent gate is preserved across resume by construction — no new bypass.**
- **Autosave:** debounced `project.save` writes are atomic (`library.py:74-79`); disabling autosave is a settings toggle. No destructive overwrite (manifest is the single source).
- **Thumbnails:** posters are derived artifacts under `data_dir/thumbnails`; deleting them is harmless (regenerated on demand, idempotent — same property as `shorts.thumbnail`). Served only through a traversal-guarded `thumb:` resolver rooted at `data_dir/thumbnails` (reuses `resolveScopedMediaPath`, `exportPath.ts:20`) — no arbitrary-disk read.
- **Availability indicators:** read-only roll-up; the only *actions* it surfaces (`assets.ensure`, open-providers, set-consent) are existing user-initiated flows with their own gates. `readiness.summary` itself triggers no download and opens no socket (it must build the asset manager + read settings only, like `system.advisor` — never call a provider).
- **Consent invariant:** `readiness.summary` reports provider/consent state by reading `consent.perProvider` (`handlers.py:414-434`) — it never grants consent and never lists a full key (reuses redacted `providers.list`).

---

## 6. Explicit capability gaps (no fabrication)

1. **No job persistence today.** `jobs.py` is 100% in-memory (`jobs.py:270-300`, no file I/O). The `JobStore` + rehydrate is genuinely new substrate and the riskiest piece. Until built, "continue a job after restart" is impossible.
2. **No mid-job resume.** Job bodies are opaque `(JobContext)->result` (`jobs.py:304-326`); resume = full re-dispatch, not mid-stream continuation. A long transcribe interrupted at 90% restarts from 0%. Documented limitation, not solved here.
3. **No source-video thumbnail RPC.** `shorts.thumbnail` only posters *exported clips* (`shorts.py`); library videos have no `thumbnailPath` field (`library.py:108-117`). New `library.thumbnail` + schema field required.
4. **No unified readiness view.** Readiness data is split across `assets.list`, `system.advisor`, `providers.list` (`handlers.py`); no single roll-up exists. `readiness.summary` is the new aggregator.
5. **No autosave / no shared export presets.** `project.save` is caller-driven (`handlers.py:276-287`); no `autosave` or `savePresets` concept exists (only *routing* presets, `handlers.py:483`). New keys + `savePresets.*` RPC.
6. **Deliberate non-goal preserved:** per-feature output redirection is rejected by design (`settings_store.py:34-40`) — this bundle does NOT add `outputDir` keys; it surfaces the ONE root instead. Changing that decision is out of scope.
7. **`thumb:` resolver does not exist yet.** Only `short:` / `dub:` branches are implemented (`exportPath.ts`, main.ts resolver). A new branch (small, reuses `resolveScopedMediaPath`) is required to serve library posters.

---

## 7. Build gates (for the eventual implementation branch — NOT this docs branch)
- Sidecar: `pytest --cov-branch --cov-fail-under=100` (heavy-ML bodies stay `# pragma: no cover` as elsewhere; the ffmpeg/job-store seams are injected + fully covered).
- Renderer: `vitest` with `thresholds: 100`.
- Lint/type: `ruff`, `oxlint`, `biome`, `basedpyright`, `tsc`.
- Never `--no-verify`; never `git add -A` — scoped adds only.
