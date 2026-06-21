# WIRING-T5 — Packaging: two-stage Windows installer + runtime setup

T5 lane files (already written; nothing below edits them):

- `electron-builder.yml` (repo root)
- `build/check-python.ps1` · `build/python-embed-setup.ps1` · `build/make-portable.ps1`
- `build/wsl-verthor-bootstrap.ps1` + `build/wsl-verthor-bootstrap.sh`
- `sidecar/runtime_setup/__init__.py` · `bootstrap.py` · `requirements-sidecar.txt` · `requirements-chatterbox.txt`
- `sidecar/media_studio/tools_resolver.py` · `sidecar/tests/test_tools_resolver.py` · `sidecar/tests/test_runtime_setup.py`

`installer.nsh` was deliberately NOT created: first-run setup is app-driven
(supervisor spawns `bootstrap.py`), not installer-driven — no custom NSIS logic
is needed and the default NSIS flow stays lean (§0: no platform creep).

T5 adds **no RPC methods** (A2 untouched) and **no native modules in job
bodies** (stdlib zipfile/urllib only) — **no `_preimport_native_modules`
additions from this unit** (T2's onnxruntime/kokoro_onnx notes are theirs).

---

## 1. `sidecar/media_studio/handlers.py` — import for asset registration

`tools_resolver` registers the llama-server tool assets (CUDA + cudart + CPU,
pinned ggml-org release URLs) at import. Import it once in `register_all`,
beside T4a's identical request:

```python
    # T5: import for side effect — registers the llama-server tool assets
    # (U4 manifest) and exposes the resolve_tool() chains.
    from . import tools_resolver  # noqa: F401
```

## 2. `app/main/main.ts` (supervisor) — packaged-mode env + first-run

In a PACKAGED build (`app.isPackaged`), inject into the sidecar spawn env
(dev builds need none of this — every chain has a dev fallback). This block
EXTENDS WIRING-T4A §3 (same `env` object, one place):

```ts
import { join } from 'node:path';
import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';

const res = process.resourcesPath;
const env: NodeJS.ProcessEnv = { ...process.env };
if (app.isPackaged) {
  env.MEDIA_STUDIO_PYTHON = join(res, 'python', 'python.exe');        // sidecar.ts resolvePython()
  env.MEDIA_STUDIO_SIDECAR_DIR = join(res, 'sidecar');                // sidecar.ts defaultSidecarDir()
  env.MEDIA_STUDIO_FFMPEG = join(res, 'bin', 'ffmpeg.exe');           // ffmpeg.py env link
  env.MEDIA_STUDIO_FFPROBE = join(res, 'bin', 'ffprobe.exe');
  // T4a trio (WIRING-T4A §3): MEDIA_STUDIO_NODE_EXE = process.execPath;
  // MEDIA_STUDIO_RENDER_JS = join(res,'render-cli','dist','render.js');
  // MEDIA_STUDIO_REMOTION_BUNDLE = join(res,'render-cli','out','remotion-bundle');
  // (tools_resolver's "node-runner" chain reads the SAME names — inject once.)
}
```

**First-run trigger** (before `sidecar.start()`): the sidecar env sentinel is
`%APPDATA%/media-studio/envs/sidecar/.media-studio-env.json`. When absent in a
packaged build, run stage 2 and wait for it (surface progress however the UI
prefers — stderr lines are `[bootstrap] ...`):

```ts
const sentinel = join(app.getPath('appData'), 'media-studio', 'envs', 'sidecar', '.media-studio-env.json');
if (app.isPackaged && !existsSync(sentinel)) {
  const boot = spawn(env.MEDIA_STUDIO_PYTHON!,
    [join(res, 'sidecar', 'runtime_setup', 'bootstrap.py')],
    { stdio: ['ignore', 'inherit', 'inherit'], windowsHide: true });  // inherit = nothing to drain (A6.2)
  await new Promise((r) => boot.on('exit', r));                       // exit 0 => "SUCCESS:bootstrap ..."
}
```

`bootstrap.py` flags, if the UI wants stages: `--skip-assets` (env only, fast),
`--tools-only` (extract already-downloaded llama zips), `--chatterbox`
(isolated torch env), `--dry-run`.

## 3. `models/runner.py` (T3 owner) — adopt the llama-server chain

`ModelRunner` still hardcodes `DEFAULT_LLAMA_SERVER = "D:/tools/llama-cpp-cuda/llama-server.exe"`.
PLAN-P2 T5: a fresh machine has no `D:\tools` — resolve through the chain
(settings -> env -> `%APPDATA%` tool dirs -> dev path) instead. Minimal change
inside `start_server` (keeps the injected `server_path` test seam intact):

```python
from .. import tools_resolver
# in start_server(), where argv is built:
server_path = self._server_path
if server_path == DEFAULT_LLAMA_SERVER:  # untouched default -> use the chain
    server_path = tools_resolver.resolve_llama_server(self._settings) or server_path
argv = build_server_argv(path, server_path=server_path, host=self._host, port=self._port)
```

New settings key (ffmpegPath-style convention, not frozen): `llamaServerPath`.
Env override: `MEDIA_STUDIO_LLAMA_SERVER`.

## 4. T4b note — WSL presence probe

The reframe fallback should use `tools_resolver.wsl_available()` (PATH-only,
never spawns — safe on job threads) as its "WSL absent -> claude-shorts +
typed notice" probe. End users provision verthor with
`build/wsl-verthor-bootstrap.ps1 [-Install -RepoUrl <url>]` (exit 2 =
"fallback active", by design).

## 5. `sidecar/pyproject.toml` (wiring owner) — optional

No change REQUIRED: tests import `runtime_setup` via the pytest rootdir
(`sidecar/` is on `sys.path` because `tests/` is a package), and the packaged
app runs `bootstrap.py` BY FILE PATH. If the wiring agent prefers
`python -m runtime_setup.bootstrap` to work from an installed wheel, add
`"runtime_setup"` to `[tool.setuptools] packages`.

## 6. Build pipeline (human-run; order matters)

```text
1. build\check-python.ps1                          # CI gate: dev python pinned 3.12
2. build\python-embed-setup.ps1 -WithFfmpeg        # NETWORK: stages build/python-embed + build/ffmpeg
3. cd app && npm run render-cli:install            # WIRING-T4A §2 script hooks
4. cd app && npm run build && npm run render-cli:bundle
5. cd app && npx electron-builder --config ..\electron-builder.yml --win
6. build\make-portable.ps1                         # slim assertions + portable zip
```

`make-portable.ps1` FAILS the build on: model weights/torch/envs inside the
artifact, missing staged resources (python/ffmpeg/sidecar/render-cli), or
unpacked size > 700 MB.

## 7. Asset + pin notes (human verification, sha fill-ins)

- **llama-server URLs** (tools_resolver.py): pinned to ggml-org/llama.cpp tag
  `b5192` (`llama-…-bin-win-cuda-cu12.4-x64.zip`, `cudart-llama-bin-win-cu12.4-x64.zip`,
  `llama-…-bin-win-cpu-x64.zip`). CONTRACT-NOTE: verify the exact asset names on
  the release page at first download and fill in each entry's `sha256`
  (downloads were impossible in the build session). The zips land in
  `tools/downloads/`; `bootstrap.py` (or `--tools-only`) extracts + deletes
  them; the entries' `detect` probes then report installed from the extracted
  exe (or the `D:/tools` dev copy).
- **requirements-sidecar.txt** pins mirror `sidecar/.venv` exactly (verified
  against its dist-info); `kokoro-onnx==0.4.9` is the T5-chosen pin (not in the
  dev venv yet) — bump in lockstep with T2 if their engine needs another.
- **requirements-chatterbox.txt** pin ORDER mirrors T2's
  `tts/chatterbox.py CHATTERBOX_REQUIREMENTS` tuple — the env sentinel compares
  the list, so keep both in sync. Two install paths for the SAME env:
  `bootstrap.py --chatterbox` (index option read from the file — works as-is)
  or U4's `assets.ensure(["chatterbox-env"])` (needs
  `PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124` in the sidecar
  env — T2's note; the supervisor can export it alongside §2's block).
- **Embeddable CPython** pinned `3.12.10` (the last 3.12 with Windows
  binaries); **ffmpeg** pinned `gyan.dev 7.1.1 essentials`. Both scripts print
  the sha256 on first download — paste into the `-Expected*Sha256` defaults.

## 8. Settings keys introduced (CONTRACT-NOTE, ffmpegPath-style convention)

`llamaServerPath` (new, T5) · `nodeExePath` (SHARED with T4a — tools_resolver
and caption_remotion read the same key + the same `MEDIA_STUDIO_NODE_EXE` env).
