# WIRING-T4A — Remotion premium captions (CaptionEngine impl #2)

Requests for the WIRING agent (T4a wrote ONLY: `vendor/remotion-captions/*`,
`app/render-cli/*`, `sidecar/media_studio/features/caption_remotion.py`,
`sidecar/tests/test_caption_remotion.py`, this file).

## 1. handlers.py — import the module (asset registration; NO new RPC methods)

T4a adds **no RPC methods** (A2 freezes the method list and contains no
caption-styles method). The module must still be imported once so its Chrome
Headless Shell asset lands in the U4 manifest. In `handlers.register_all` add:

```python
# T4a: imports for side effect — registers the chrome-headless-shell asset
# (U4 manifest) and exposes RemotionCaptionEngine/STYLES for shortmaker/T4b.
from .features import caption_remotion  # noqa: F401
```

No `__main__._preimport_native_modules` additions are needed — the engine uses
stdlib subprocess/zipfile only (A6 lesson 1: nothing new to pre-import).

## 2. app/package.json — build hooks (render-cli is its OWN package)

Do NOT merge render-cli's deps into app/package.json. Add script hooks that
delegate into the workspace (npm `--prefix` keeps it self-contained):

```json
"render-cli:install": "npm --prefix render-cli install",
"render-cli:bundle": "npm --prefix render-cli run bundle"
```

and run `render-cli:bundle` as part of the app build pipeline (e.g.
`"build": "tsc --noEmit && electron-vite build && npm run render-cli:bundle"`),
so compositions are PRE-BUNDLED at app-build time — `render.js` never bundles
at runtime (it does not even import `@remotion/bundler`).

## 3. main.ts (sidecar supervisor) — env injection for the packaged app

Mirror the llama-server chain: when spawning the python sidecar in a PACKAGED
build, inject (dev builds need nothing — the engine's dev fallbacks resolve
`app/node_modules/electron` / `app/render-cli/{dist,out}` from the repo):

```ts
env.MEDIA_STUDIO_NODE_EXE = process.execPath; // the app's own Electron exe
env.MEDIA_STUDIO_RENDER_JS = path.join(process.resourcesPath, "render-cli", "dist", "render.js");
env.MEDIA_STUDIO_REMOTION_BUNDLE = path.join(process.resourcesPath, "render-cli", "out", "remotion-bundle");
```

The engine spawns `[exe, render.js, job.json]` with `ELECTRON_RUN_AS_NODE=1`
set in the child env (A4) — no supervisor change needed for that part.

## 4. T5 packaging note (electron-builder)

`extraResources` must ship: `app/render-cli/dist/`, `app/render-cli/out/
remotion-bundle/`, and `app/render-cli/node_modules/` (at minimum
`@remotion/renderer` + its platform compositor package, `react`/`react-dom`/
`remotion`/`@remotion/captions`/`zod` are compiled into the bundle and are NOT
needed at runtime — but shipping the whole node_modules is the safe default).

## 5. T4b — the ShortMaker style picker

- Python: `from media_studio.features.caption_remotion import STYLES, RemotionCaptionEngine, ENGINE_NAME`
  (STYLES = `["bold", "bounce", "clean", "karaoke"]`).
- TS mirror: `CAPTION_STYLES` in `vendor/remotion-captions/src/types.ts`
  (keep the two lists in sync; renderer code should hardcode/import its own
  copy — A2 has no styles RPC).
- Engine registry: libass (`features.caption.CaptionEngine`, default) +
  remotion (`features.caption_remotion.RemotionCaptionEngine`); both share
  `render(clip_path, cues, out_path, ...)`, remotion adds `style=` and rejects
  `burn=False` (no soft-mux variant — fall back to libass for that).

## 6. Settings keys (CONTRACT-NOTE — ffmpegPath-style convention, not frozen)

`nodeExePath`, `renderJsPath`, `remotionBundleDir`, `chromeHeadlessShellPath`
are read by the engine's resolution chains (env override -> settings -> dev
fallback / managed asset). If the Settings UI grows fields for them, use these
exact names.

## 7. Asset note (human verification)

`chrome-headless-shell-win64` is registered pinned to Chrome for Testing
`123.0.6312.86` (win64 zip). On first download, verify the version matches
what `@remotion/renderer@4.0.422` expects (`npx remotion browser ensure`
prints it) and fill in the entry's `sha256`. The U4 manager downloads the zip;
the ENGINE extracts it on first use (stdlib zipfile, zip-slip guarded) — no
AssetManager change required. A wrong/missing browser degrades softly:
`render.ts` only passes `chromiumExecutable` when provided, otherwise Remotion
resolves its own browser.
