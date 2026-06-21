# WIRING-U4 — Assets: download + runtime-setup manager

U4 lane files (already written, nothing below edits them):

- `sidecar/media_studio/assets/__init__.py` / `manifest.py` / `manager.py` / `rpc.py`
- `sidecar/tests/test_assets.py`
- `app/renderer/src/features/Assets.tsx` (+ `Assets.test.tsx`)

The snippets below are the ONLY changes U4 needs in shared files. Apply exactly.

---

## 1. `sidecar/media_studio/handlers.py` — register the assets.* methods

At the end of `register_all(...)` (after the existing `reg(...)` calls, before the
final `log.info`), add:

```python
    # assets.* (A2): registered via the assets package's own register() so the
    # manager binds to the services' data dir + settings (U4).
    from .assets import rpc as _assets_rpc  # local import keeps handlers import-light

    _assets_rpc.register(
        root=svc.data_dir,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )
```

Notes:
- `register_fn=reg` keeps test injection working (`register_all(register=fake)`
  routes assets.* through the same fake registrar).
- `settings_provider` powers the Qwen existing-path detection
  (`settings.ggufPath` / `settings.modelsDir`) — pass it, don't drop it.
- Methods registered: `assets.list`, `assets.ensure`, `assets.cancel`.
  CONTRACT-NOTE: `assets.cancel` is a thin alias over `job.cancel` (same
  params/semantics) added per the U4 brief; A2's frozen `assets.list`/`assets.ensure`
  are unchanged.

## 2. `sidecar/media_studio/__main__.py` — pre-import natives (A6 lesson 1)

**No change needed for U4.** The assets subsystem uses only `httpx`,
`huggingface_hub` (lazy, pure Python) and `subprocess` — no native C-extension
is imported inside its job bodies, so `_preimport_native_modules` needs no new
entries from this unit.

## 3. `sidecar/pyproject.toml` — package list (owner: wiring/conformance)

`[tool.setuptools] packages` must gain the new subpackage:

```toml
packages = [
  "media_studio",
  "media_studio.models",
  "media_studio.features",
  "media_studio.assets",
]
```

No new dependency is required: `httpx` is already declared, and
`huggingface_hub` is a transitive dependency of `faster-whisper` (only the
real HF download path imports it, lazily).

## 4. `app/renderer/src/views/Workspace.tsx` (or `App.tsx`) — Assets panel tab

The Assets panel is app-global (not per-video), so it fits either an App-level
surface or a Workspace tab. If exposed as a Workspace tab, follow the existing
`lazyPanel` pattern:

```tsx
const Assets = lazyPanel<Record<string, never>>('../features/Assets', 'Assets');

// in WORKSPACE_TABS:
  { id: 'assets', label: 'Assets' },

// in the tab-body switch:
  {active === 'assets' && <Assets />}
```

`<Assets />` takes no required props (an optional `api` prop exists for tests
only). It consumes the frozen bridge surface: `window.api.rpc`,
`window.api.onProgress`, `window.api.onJobDone` — all already exposed by
`preload.ts`; **no preload/main/ipc changes needed**.

## 5. Job-system contact points (for U5's refactor awareness)

- `assets.ensure` uses the standard long-job shape: handler calls
  `ctx.jobs.start(body)` and returns `{jobId}`; the body raises on failure
  (surfaces via the `job.done` error payload `{error:{message,type}}`) and
  raises `jobs.JobCancelled` on cooperative cancel (partial downloads keep
  their `.part` file so the next ensure resumes via HTTP Range).
- If U5 adds `job.list` metadata (`JobInfo.feature/label`), the assets job's
  natural values are `feature="assets"`, `label="Install <names>"` — wire as
  U5's API allows.
