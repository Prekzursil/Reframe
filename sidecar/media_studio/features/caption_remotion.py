"""RemotionCaptionEngine — premium animated captions (CaptionEngine impl #2, A4).

The default CaptionEngine is libass/ffmpeg (:mod:`.caption`). This module is the
**remotion** implementation: it spawns the pre-built render CLI
(``app/render-cli/dist/render.js``) as a subprocess of the node runner — the
**Electron exe with ``ELECTRON_RUN_AS_NODE=1``** (A4) — passing a JSON job file
describing the render. Compositions are PRE-BUNDLED at app-build time
(``app/render-cli/src/bundle.ts``); nothing is bundled at runtime.

Resolution chains (first hit wins; mirrors ffmpeg.py / models/runner.py):

* node-runner exe: env ``MEDIA_STUDIO_NODE_EXE`` -> ``settings["nodeExePath"]``
  -> dev fallback ``app/node_modules/electron/dist/electron(.exe)``. In the
  packaged app the supervisor injects the env var (= the app's own Electron
  exe), exactly like the llama-server chain.
* render.js:  env ``MEDIA_STUDIO_RENDER_JS`` -> ``settings["renderJsPath"]``
  -> dev fallback ``app/render-cli/dist/render.js``.
* bundle dir: env ``MEDIA_STUDIO_REMOTION_BUNDLE`` ->
  ``settings["remotionBundleDir"]`` -> dev fallback
  ``app/render-cli/out/remotion-bundle``.
* Chrome Headless Shell: env ``MEDIA_STUDIO_CHROME_HEADLESS_SHELL`` ->
  ``settings["chromeHeadlessShellPath"]`` -> the U4-managed asset (extracted on
  first use from the pinned zip) -> ``None`` (the renderer resolves its own
  browser).

A6 lessons honored: argv lists only (never ``shell=True``); BOTH subprocess
pipes are drained (stderr on a joined daemon thread — the proven 29-min-freeze
pattern from :func:`media_studio.ffmpeg.run`); failures raise
:class:`RemotionCaptionError` so job bodies surface them via the job.done error
payload; the Chrome Headless Shell asset entry is PINNED. No new native module
is imported here (stdlib subprocess/zipfile only) — nothing to pre-import in
``__main__``.

CONTRACT-NOTE: A2/A3 freeze no settings field names for this engine; the keys
``nodeExePath`` / ``renderJsPath`` / ``remotionBundleDir`` /
``chromeHeadlessShellPath`` follow the existing ``ffmpegPath`` naming
convention and are documented here + in WIRING-T4A.md.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
import threading
import zipfile
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..assets.manifest import AssetEntry, register_asset
from ..settings_store import default_config_dir
from ..util import get_logger
from . import emphasis as _emphasis
from .caption import CueLike, rebase_cue_time

log = get_logger("media_studio.caption_remotion")

# --------------------------------------------------------------------------- #
# the style registry (T4b's ShortMaker picker imports this list)
# --------------------------------------------------------------------------- #
#: Premium caption styles rendered by vendor/remotion-captions (keep in sync
#: with the keys of TEMPLATES in vendor/remotion-captions/src/templates.ts and
#: the remotion-engine ids in app/renderer/src/lib/captionTemplates.ts — the
#: three-way mirror conformance-tested by
#: app/renderer/src/lib/captionTemplates.conformance.test.ts). Order matches the
#: registry insertion order. The four originals (bold/bounce/clean/karaoke) stay
#: valid for backward compat (P4 §4).
STYLES: list[str] = [
    "bold",
    "karaoke",
    "clean",
    "bounce",
    "hormozi",
    "neon",
    "tiktok",
    "gradient",
    "impact",
    "mrbeast",
    "pop",
    "serif",
    "fire",
    "subtitle",
]

#: The engine's name in the CaptionEngine registry (A4: libass | remotion).
ENGINE_NAME = "remotion"

#: Composition id registered in vendor/remotion-captions/src/Root.tsx.
COMPOSITION_ID = "CaptionedClip"

# Environment override names (first link of each resolution chain).
ENV_NODE_EXE = "MEDIA_STUDIO_NODE_EXE"
ENV_RENDER_JS = "MEDIA_STUDIO_RENDER_JS"
ENV_BUNDLE_DIR = "MEDIA_STUDIO_REMOTION_BUNDLE"
ENV_CHROME = "MEDIA_STUDIO_CHROME_HEADLESS_SHELL"

# Settings keys (CONTRACT-NOTE above: ffmpegPath-style convention, not frozen).
SETTING_NODE_EXE = "nodeExePath"
SETTING_RENDER_JS = "renderJsPath"
SETTING_BUNDLE_DIR = "remotionBundleDir"
SETTING_CHROME = "chromeHeadlessShellPath"

# stdout protocol printed by app/render-cli/src/render.ts.
RENDER_OK_PREFIX = "RENDER_OK "
RENDER_PROGRESS_PREFIX = "RENDER_PROGRESS "

#: stderr substrings signalling a TRANSIENT headless-Chromium / compositor death
#: (the render CLI dies mid-batch under sustained load). render.ts already retries
#: in-process with a fresh browser; this is the belt-and-suspenders SUBPROCESS
#: retry — if the whole CLI still exits non-zero with one of these, spawn it once
#: more (a brand-new process => brand-new browser). Matched case-insensitively.
#: Keep in sync with TRANSIENT_SIGNATURES in app/render-cli/src/retry.ts.
TRANSIENT_SIGNATURES: tuple[str, ...] = (
    "request closed",
    "could not extract frame from compositor",
    "target closed",
    "navigation failed",
    "session closed",
    "protocol error",
    "websocket is not open",
)

#: Subprocess-level attempts: 1 initial + 1 retry (render.ts owns the finer
#: in-process retry budget; this only catches a CLI process that died whole).
MAX_SUBPROCESS_ATTEMPTS = 2


def is_transient_compositor_failure(stderr_tail: Sequence[str]) -> bool:
    """True when the stderr tail carries a known transient-compositor signature.

    Drives the one-shot subprocess retry: a transient browser/compositor death is
    worth re-spawning (fresh process); any other failure is surfaced immediately.
    """
    haystack = "\n".join(stderr_tail).lower()
    return any(sig in haystack for sig in TRANSIENT_SIGNATURES)


_EXE = ".exe" if os.name == "nt" else ""

# Repo root in a dev checkout: features/ -> media_studio/ -> sidecar/ -> root.
_DEV_ROOT = Path(__file__).resolve().parents[3]

# Injectable popen seam (mirrors ffmpeg.run / models.runner).
PopenLike = Callable[..., Any]
ProgressCb = Callable[[float, str], None]
CancelProbe = Callable[[], bool]


class RemotionCaptionError(RuntimeError):
    """Raised when the remotion render cannot be prepared or fails.

    Job bodies let this propagate, so failures surface through the job.done
    error payload (A6 lesson 3) exactly like CaptionError does for libass.
    """


# --------------------------------------------------------------------------- #
# Chrome Headless Shell asset (U4 manifest — PINNED per A6 lesson 5)
# --------------------------------------------------------------------------- #
CHROME_HEADLESS_SHELL_ASSET = "chrome-headless-shell-win64"
#: Chrome for Testing pinned build. CONTRACT-NOTE: A6 lesson 5 demands a pinned
#: URL; 123.0.6312.86 is the Chrome Headless Shell major Remotion 4.0.x targets.
#: The human verifies on first download (and fills sha256) — render.ts treats
#: the browser as optional, so a version drift degrades to Remotion resolving
#: its own browser rather than a broken render.
CHROME_HEADLESS_SHELL_VERSION = "123.0.6312.86"
CHROME_HEADLESS_SHELL_URL = (
    "https://storage.googleapis.com/chrome-for-testing-public/"
    f"{CHROME_HEADLESS_SHELL_VERSION}/win64/chrome-headless-shell-win64.zip"
)
CHROME_HEADLESS_SHELL_SIZE_MB = 80
#: Where the pinned zip lands under the assets root (%APPDATA%/media-studio).
CHROME_HEADLESS_SHELL_ZIP_DEST = "tools/chrome-headless-shell-win64.zip"
#: Where the zip is extracted (first engine use). The zip's top-level folder is
#: "chrome-headless-shell-win64", so the exe ends up at
#: <root>/tools/chrome-headless-shell-win64/chrome-headless-shell.exe.
CHROME_HEADLESS_SHELL_EXTRACT_DIR = "tools"
CHROME_HEADLESS_SHELL_EXE_REL = f"tools/chrome-headless-shell-win64/chrome-headless-shell{_EXE}"


def detect_chrome_headless_shell(settings: dict[str, Any]) -> str | None:
    """Existing-copy probe for the asset manager (counts as installed)."""
    settings = settings or {}
    explicit = settings.get(SETTING_CHROME)
    if explicit and Path(str(explicit)).is_file():
        return str(Path(str(explicit)))
    extracted = default_config_dir() / CHROME_HEADLESS_SHELL_EXE_REL
    if extracted.is_file():
        return str(extracted)
    return None


def register_assets() -> AssetEntry:
    """Register the Chrome Headless Shell zip in the U4 manifest (idempotent)."""
    return register_asset(
        AssetEntry(
            name=CHROME_HEADLESS_SHELL_ASSET,
            kind="tool",
            size_mb=CHROME_HEADLESS_SHELL_SIZE_MB,
            dest=CHROME_HEADLESS_SHELL_ZIP_DEST,
            label="Chrome Headless Shell (Remotion caption renders)",
            installer="download",
            url=CHROME_HEADLESS_SHELL_URL,
            detect=detect_chrome_headless_shell,
        )
    )


register_assets()


def ensure_chrome_extracted(zip_path: Path, extract_root: Path) -> Path | None:
    """Extract the headless-shell zip if needed; return the exe path or None.

    The U4 manager downloads single files (no unzip step), so the ENGINE owns
    extraction — stdlib :mod:`zipfile`, first use only. Zip-slip is guarded by
    rejecting member paths that escape ``extract_root``.
    """
    exe = extract_root / Path(CHROME_HEADLESS_SHELL_EXE_REL).relative_to(CHROME_HEADLESS_SHELL_EXTRACT_DIR)
    if exe.is_file():
        return exe
    if not zip_path.is_file():
        return None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            root = extract_root.resolve()
            for member in zf.namelist():
                target = (root / member).resolve()
                if not str(target).startswith(str(root)):
                    raise RemotionCaptionError(f"unsafe zip member path in {zip_path.name}: {member!r}")
            zf.extractall(root)
    except (OSError, zipfile.BadZipFile) as exc:
        log.warning("chrome-headless-shell extraction failed: %s", exc)
        return None
    return exe if exe.is_file() else None


# --------------------------------------------------------------------------- #
# resolution chains (pure-ish: filesystem probes only, fully injectable)
# --------------------------------------------------------------------------- #
def resolve_node_exe(
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    dev_root: Path | None = None,
) -> str:
    """Resolve the node-runner exe: env -> settings -> dev electron (A4 chain).

    1. ``MEDIA_STUDIO_NODE_EXE`` env var (the supervisor injects the packaged
       Electron exe here — ``process.execPath`` — like the llama-server chain);
    2. ``settings["nodeExePath"]``;
    3. dev fallback: ``app/node_modules/electron/dist/electron(.exe)``.

    Raises :class:`RemotionCaptionError` when nothing resolves to a real file.
    """
    settings = settings or {}
    env = env if env is not None else os.environ
    root = dev_root if dev_root is not None else _DEV_ROOT

    env_val = env.get(ENV_NODE_EXE)
    if env_val and Path(env_val).is_file():
        return str(Path(env_val))

    setting_val = settings.get(SETTING_NODE_EXE)
    if setting_val and Path(str(setting_val)).is_file():
        return str(Path(str(setting_val)))

    for candidate in (
        root / "app" / "node_modules" / "electron" / "dist" / f"electron{_EXE}",
        root / "app" / "node_modules" / "electron" / "dist" / "electron",
    ):
        if candidate.is_file():
            return str(candidate)

    raise RemotionCaptionError(
        "node runner not found: set the MEDIA_STUDIO_NODE_EXE env var, "
        f"settings.{SETTING_NODE_EXE}, or install app/node_modules (dev electron)"
    )


def resolve_render_js(
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    dev_root: Path | None = None,
) -> str:
    """Resolve render.js: env -> settings -> dev ``app/render-cli/dist/render.js``."""
    settings = settings or {}
    env = env if env is not None else os.environ
    root = dev_root if dev_root is not None else _DEV_ROOT

    env_val = env.get(ENV_RENDER_JS)
    if env_val and Path(env_val).is_file():
        return str(Path(env_val))

    setting_val = settings.get(SETTING_RENDER_JS)
    if setting_val and Path(str(setting_val)).is_file():
        return str(Path(str(setting_val)))

    dev = root / "app" / "render-cli" / "dist" / "render.js"
    if dev.is_file():
        return str(dev)

    raise RemotionCaptionError(
        "render.js not found: set MEDIA_STUDIO_RENDER_JS, "
        f"settings.{SETTING_RENDER_JS}, or build app/render-cli (npm run build)"
    )


def resolve_bundle_dir(
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    dev_root: Path | None = None,
) -> str:
    """Resolve the pre-built bundle dir: env -> settings -> dev out/remotion-bundle."""
    settings = settings or {}
    env = env if env is not None else os.environ
    root = dev_root if dev_root is not None else _DEV_ROOT

    env_val = env.get(ENV_BUNDLE_DIR)
    if env_val and Path(env_val).is_dir():
        return str(Path(env_val))

    setting_val = settings.get(SETTING_BUNDLE_DIR)
    if setting_val and Path(str(setting_val)).is_dir():
        return str(Path(str(setting_val)))

    dev = root / "app" / "render-cli" / "out" / "remotion-bundle"
    if dev.is_dir():
        return str(dev)

    raise RemotionCaptionError(
        "remotion bundle not found: set MEDIA_STUDIO_REMOTION_BUNDLE, "
        f"settings.{SETTING_BUNDLE_DIR}, or run the render-cli bundle step "
        "(npm run bundle in app/render-cli)"
    )


def resolve_chromium(
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    assets_root: Path | None = None,
) -> str | None:
    """Resolve Chrome Headless Shell (OPTIONAL — None lets Remotion self-resolve).

    env -> settings -> the U4-managed asset (extracting the pinned zip on first
    use). Never raises: a missing browser is a soft miss by design.
    """
    settings = settings or {}
    env = env if env is not None else os.environ
    root = assets_root if assets_root is not None else default_config_dir()

    env_val = env.get(ENV_CHROME)
    if env_val and Path(env_val).is_file():
        return str(Path(env_val))

    setting_val = settings.get(SETTING_CHROME)
    if setting_val and Path(str(setting_val)).is_file():
        return str(Path(str(setting_val)))

    exe = ensure_chrome_extracted(
        root / CHROME_HEADLESS_SHELL_ZIP_DEST,
        root / CHROME_HEADLESS_SHELL_EXTRACT_DIR,
    )
    return str(exe) if exe is not None else None


# --------------------------------------------------------------------------- #
# pure builders: job file payload, argv, spawn env
# --------------------------------------------------------------------------- #
def build_job(
    clip_path: str,
    cues: Sequence[CueLike],
    out_path: str,
    *,
    bundle_dir: str,
    style: str = "bold",
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
    total_sec: float = 0.0,
    chromium_executable: str | None = None,
    hook_title: str | None = None,
) -> dict[str, Any]:
    """Build the render job payload render.ts consumes.

    Shape (frozen by the T4a unit contract):
    ``{bundleDir, composition, inputProps, outPath[, chromiumExecutable]}``
    with ``inputProps = {videoSrc, cues, style, width, height,
    durationInSeconds}``.

    Cue times are **re-based to clip-local t=0** (subtract ``source_start``,
    §4) here in Python — the composition receives ready-to-render contract
    Cues (seconds; the TS side converts to ms). Cues entirely before the clip
    are dropped. Text needs NO escaping: it travels as JSON and renders as
    React text content (never HTML), so there is no ASS-style injection
    surface.

    P3-A: when ``hook_title`` is a non-empty string, it is added to
    ``inputProps`` as ``hookTitle`` (a top-anchored headline slot in the
    vendored composition). It is OMITTED otherwise so the default job shape is
    byte-identical to the pre-P3 contract (the composition's zod schema applies
    its own default), exactly like ``chromiumExecutable``.
    """
    if style not in STYLES:
        raise RemotionCaptionError(f"unknown caption style {style!r} (expected one of {STYLES})")

    rebased: list[dict[str, Any]] = []
    for cue in cues:
        start = rebase_cue_time(cue.get("start", 0.0), source_start)
        end = rebase_cue_time(cue.get("end", 0.0), source_start)
        if end <= start:
            continue  # entirely before the clip (or zero-length after re-base)
        out_cue: dict[str, Any] = {
            "index": int(cue.get("index", len(rebased))),
            "start": start,
            "end": end,
            "text": str(cue.get("text", "") or ""),
        }
        # P4 §8a: carry the deterministic emphasis spans + trailing emoji through
        # to the composition when they were annotated upstream (omitted otherwise
        # so the default job shape stays byte-identical to the frozen contract —
        # the composition's zod schema defaults them). Spans are char offsets into
        # ``text`` ({start,end,kind}); the emoji is a single trailing glyph.
        spans = _emphasis.normalize_spans(cue.get("emphasis"))
        if spans:
            out_cue["emphasis"] = spans
        emoji = str(cue.get("emoji", "") or "")
        if emoji:
            out_cue["emoji"] = emoji
        rebased.append(out_cue)

    duration = float(total_sec)
    if duration <= 0.0:
        # No probed duration: size the render to the last caption (min 1s).
        duration = max((c["end"] for c in rebased), default=1.0)
        duration = max(duration, 1.0)

    job: dict[str, Any] = {
        "bundleDir": str(bundle_dir),
        "composition": COMPOSITION_ID,
        "inputProps": {
            "videoSrc": str(clip_path),
            "cues": rebased,
            "style": style,
            "width": int(width),
            "height": int(height),
            "durationInSeconds": duration,
        },
        "outPath": str(out_path),
    }
    # P3-A: a non-empty hook headline rides inputProps (omitted otherwise so the
    # default job shape stays byte-identical to the frozen T4a contract).
    title = str(hook_title or "").strip()
    if title:
        job["inputProps"]["hookTitle"] = title
    if chromium_executable:
        job["chromiumExecutable"] = str(chromium_executable)
    return job


def build_argv(node_exe: str, render_js: str, job_path: str) -> list[str]:
    """argv list (never a shell string): ``[exe, render.js, job.json]``."""
    return [str(node_exe), str(render_js), str(job_path)]


def build_spawn_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Spawn environment: inherit + ``ELECTRON_RUN_AS_NODE=1`` (A4).

    Harmless for a plain node.exe runner; required for the Electron exe to
    behave as Node.
    """
    env = dict(base_env if base_env is not None else os.environ)
    env["ELECTRON_RUN_AS_NODE"] = "1"
    return env


def parse_render_ok(line: str) -> str | None:
    """Extract the output path from a ``RENDER_OK <path>`` stdout line.

    The path is everything after the prefix (it may contain spaces).
    """
    stripped = line.strip()
    if not stripped.startswith(RENDER_OK_PREFIX):
        return None
    rest = stripped[len(RENDER_OK_PREFIX) :].strip()
    return rest or None


def parse_render_progress(line: str) -> float | None:
    """Extract the pct from a ``RENDER_PROGRESS <0-100>`` stdout line."""
    stripped = line.strip()
    if not stripped.startswith(RENDER_PROGRESS_PREFIX):
        return None
    rest = stripped[len(RENDER_PROGRESS_PREFIX) :].strip()
    try:
        return max(0.0, min(100.0, float(rest)))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# the drained-pipes subprocess runner (A6 lesson 2)
# --------------------------------------------------------------------------- #
def run_render(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
    popen: PopenLike = subprocess.Popen,
) -> tuple[int, str | None, list[str]]:
    """Run the render CLI, draining BOTH pipes; return (code, ok_path, stderr_tail).

    * stdout is consumed line-by-line on the calling thread: ``RENDER_PROGRESS``
      lines feed ``on_progress``; the ``RENDER_OK <path>`` line is captured.
    * stderr is drained on a daemon thread (the ffmpeg.run pattern — an
      unread PIPE deadlocks the child once the ~64KB buffer fills; proven
      29-minute freeze) keeping a bounded tail for error reporting. The drain
      thread is JOINED before returning so the tail is complete.
    * ``should_cancel`` is polled per stdout line; cancellation terminates the
      child cooperatively.
    """
    if isinstance(argv, str):  # guard: never accept a shell string
        raise TypeError("argv must be a list of strings, not a shell string")

    proc = popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=dict(env) if env is not None else None,
    )

    stderr_tail: deque[str] = deque(maxlen=40)
    drain_thread: threading.Thread | None = None
    stderr = getattr(proc, "stderr", None)
    if stderr is not None and hasattr(stderr, "__iter__"):

        def _drain() -> None:
            try:
                for line in stderr:
                    seg = line.rstrip("\n").strip()
                    if seg:
                        stderr_tail.append(seg)
            except Exception:  # noqa: BLE001 - drain must never raise
                pass

        drain_thread = threading.Thread(target=_drain, daemon=True, name="remotion-stderr")
        drain_thread.start()

    ok_path: str | None = None
    stdout = getattr(proc, "stdout", None)
    if stdout is not None:
        for raw in stdout:
            if should_cancel is not None and should_cancel():
                _terminate(proc)
                break
            pct = parse_render_progress(raw)
            if pct is not None:
                if on_progress is not None:
                    on_progress(pct, f"rendering captions {pct:.0f}%")
                continue
            parsed = parse_render_ok(raw)
            if parsed is not None:
                ok_path = parsed

    code = proc.wait()
    if drain_thread is not None:
        drain_thread.join(timeout=5)
    if code != 0 and stderr_tail:
        log.error(
            "render-cli exited %s; stderr tail: %s",
            code,
            " | ".join(list(stderr_tail)[-8:]),
        )
    return code, ok_path, list(stderr_tail)


def _terminate(proc: Any) -> None:
    """Cooperatively stop a subprocess: terminate, then kill if it lingers."""
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# RemotionCaptionEngine (A4 CaptionEngine interface, impl "remotion")
# --------------------------------------------------------------------------- #
class RemotionCaptionEngine:
    """CaptionEngine impl #2 (A4): premium animated captions via Remotion.

    Mirrors :class:`media_studio.features.caption.CaptionEngine`'s surface plus
    the A4 ``style`` parameter. All heavy seams are injected: ``popen`` (the
    subprocess), ``env`` (resolution env), ``dev_root`` / ``assets_root``
    (filesystem probe bases) — tests drive the full flow with no real process.
    """

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        popen: PopenLike = subprocess.Popen,
        env: Mapping[str, str] | None = None,
        dev_root: Path | None = None,
        assets_root: Path | None = None,
    ) -> None:
        self._settings = dict(settings or {})
        self._popen = popen
        self._env = env
        self._dev_root = dev_root
        self._assets_root = assets_root

    # -- resolution (the documented chains, bound to this engine's seams) ----
    def resolve_runtime(self) -> tuple[str, str, str, str | None]:
        """(node_exe, render_js, bundle_dir, chromium_or_None) for this engine."""
        node_exe = resolve_node_exe(self._settings, env=self._env, dev_root=self._dev_root)
        render_js = resolve_render_js(self._settings, env=self._env, dev_root=self._dev_root)
        bundle_dir = resolve_bundle_dir(self._settings, env=self._env, dev_root=self._dev_root)
        chromium = resolve_chromium(self._settings, env=self._env, assets_root=self._assets_root)
        return node_exe, render_js, bundle_dir, chromium

    def render(
        self,
        clip_path: str,
        cues: Sequence[CueLike],
        out_path: str,
        style: str = "bold",
        burn: bool = True,
        width: int = 1080,
        height: int = 1920,
        source_start: float = 0.0,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
        total_sec: float = 0.0,
        hook_title: str | None = None,
    ) -> str:
        """Render ``cues`` onto ``clip_path`` -> ``out_path``; return ``out_path``.

        Steps: resolve the runtime (chains above) -> write the JSON job file ->
        spawn ``[exe, render.js, job.json]`` with ``ELECTRON_RUN_AS_NODE=1`` and
        both pipes drained -> require exit 0 AND a ``RENDER_OK`` line.

        Raises :class:`RemotionCaptionError` on any failure (the job body lets
        it propagate -> job.done error payload, A6 lesson 3).

        CONTRACT-NOTE: ``burn`` exists for §4 interface parity; Remotion always
        produces a new burned-in video (there is no soft-mux variant), so
        ``burn=False`` is rejected rather than silently mis-served.
        """
        if not burn:
            raise RemotionCaptionError(
                "the remotion CaptionEngine only burns captions (use the libass engine for soft-mux)"
            )

        node_exe, render_js, bundle_dir, chromium = self.resolve_runtime()

        job = build_job(
            clip_path,
            cues,
            out_path,
            bundle_dir=bundle_dir,
            style=style,
            width=width,
            height=height,
            source_start=source_start,
            total_sec=total_sec,
            chromium_executable=chromium,
            hook_title=hook_title,
        )

        fd, job_path = tempfile.mkstemp(suffix=".json", prefix="media_studio_remotion_job_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                json.dump(job, fh)

            argv = build_argv(node_exe, render_js, job_path)
            spawn_env = build_spawn_env(self._env)

            code = -1
            ok_path: str | None = None
            stderr_tail: list[str] = []
            for attempt in range(1, MAX_SUBPROCESS_ATTEMPTS + 1):
                code, ok_path, stderr_tail = run_render(
                    argv,
                    env=spawn_env,
                    on_progress=on_progress,
                    should_cancel=should_cancel,
                    popen=self._popen,
                )
                if code == 0 and ok_path is not None:
                    return out_path
                # A cooperative cancel ends the loop immediately — never retry a
                # user-requested cancellation.
                if should_cancel is not None and should_cancel():
                    break
                # Belt-and-suspenders: re-spawn ONCE (fresh process => fresh
                # browser) only on a transient compositor death and only if we
                # have an attempt left.
                if attempt < MAX_SUBPROCESS_ATTEMPTS and is_transient_compositor_failure(stderr_tail):
                    log.warning(
                        "remotion render-cli hit a transient compositor failure "
                        "(attempt %s/%s); re-spawning a fresh process",
                        attempt,
                        MAX_SUBPROCESS_ATTEMPTS,
                    )
                    continue
                break

            tail = " | ".join(stderr_tail[-5:]) if stderr_tail else "(no stderr)"
            raise RemotionCaptionError(
                f"remotion render failed (exit {code}, "
                f"RENDER_OK {'missing' if ok_path is None else 'present'}) "
                f"for {out_path}: {tail}"
            )
        finally:
            # Best-effort cleanup; never mask a RemotionCaptionError.
            with contextlib.suppress(OSError):
                os.unlink(job_path)


__all__ = [
    "STYLES",
    "ENGINE_NAME",
    "COMPOSITION_ID",
    "ENV_NODE_EXE",
    "ENV_RENDER_JS",
    "ENV_BUNDLE_DIR",
    "ENV_CHROME",
    "SETTING_NODE_EXE",
    "SETTING_RENDER_JS",
    "SETTING_BUNDLE_DIR",
    "SETTING_CHROME",
    "CHROME_HEADLESS_SHELL_ASSET",
    "CHROME_HEADLESS_SHELL_URL",
    "RemotionCaptionEngine",
    "RemotionCaptionError",
    "build_argv",
    "build_job",
    "build_spawn_env",
    "detect_chrome_headless_shell",
    "ensure_chrome_extracted",
    "is_transient_compositor_failure",
    "parse_render_ok",
    "parse_render_progress",
    "MAX_SUBPROCESS_ATTEMPTS",
    "TRANSIENT_SIGNATURES",
    "register_assets",
    "resolve_bundle_dir",
    "resolve_chromium",
    "resolve_node_exe",
    "resolve_render_js",
    "run_render",
]
