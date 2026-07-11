"""First-run runtime setup — stage 2 of the two-stage install (CONTRACTS.md A7/T5).

Stage 1 (the slim installer / portable zip) ships: Electron app + embeddable
CPython 3.12 + ffmpeg/ffprobe + the pre-built Remotion bundle + this sidecar
source. NO torch, NO heavy wheels, NO models.

Stage 2 (THIS script, run on first launch — by the supervisor or by hand):

  1. **sidecar env** — embeddable CPython has NO ensurepip/venv (A7), so:
     get-pip.py (staged offline copy preferred, else downloaded) installs a
     PINNED pip straight into ``%APPDATA%/media-studio/envs/sidecar`` via
     ``--target``, then ``pip install --target ... -r requirements-sidecar.txt``
     (every line pinned; validated BEFORE pip runs).
  2. **activation** — rewrites the embeddable ``python312._pth`` so the env dir
     + this sidecar source are on ``sys.path`` (the ``._pth``/PYTHONPATH
     activation named by A7), and ``import site`` is enabled.
  3. **models/tools** — delegates downloads to the U4 asset manager
     (``assets.ensure`` semantics, in-process with a console progress sink):
     whisper, the Qwen GGUF, and the llama-server builds registered by
     ``media_studio.tools_resolver``.
  4. **tool archives** — extracts the downloaded llama-server zips into
     ``<root>/tools/...`` (zip-slip-guarded, exe hoisted to the dir root) and
     deletes the archives; the resolver + detect probes then find the exe.
  5. optional ``--chatterbox`` — builds the ISOLATED torch env from
     ``requirements-chatterbox.txt`` (A4: torch never enters the sidecar env).

A6 honored: subprocesses use argv LISTS and INHERIT stdio (no PIPE exists that
could fill and freeze — lesson 2); failures raise and exit non-zero with a
``FAILED:`` line; everything pinned. Pure-logic parts (requirements parsing,
``._pth`` rendering, argv building, zip extraction) are plain functions with
injectable seams — tested with NO real pip/network (tests/test_runtime_setup.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess  # noqa: S404 - argv-list subprocess only, never shell=True
import sys
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# bootstrap runs BY FILE PATH from the packaged resources dir; make the sidecar
# source importable (media_studio is pure stdlib at import time).
_SIDECAR_DIR = Path(__file__).resolve().parent.parent
if str(_SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR_DIR))

from media_studio.assets.manager import (  # noqa: E402
    ENV_SENTINEL,
    GET_PIP_SHA256,
    GET_PIP_URL,
    HASHED_LOCK_PIP_ARGS,
    PINNED_PIP,
    AssetError,
    validate_hashed_lock,
)
from media_studio.pathsafe import ensure_within  # noqa: E402
from media_studio.settings_store import SettingsStore, default_config_dir  # noqa: E402

HERE = Path(__file__).resolve().parent
SIDECAR_REQUIREMENTS = HERE / "requirements-sidecar.txt"
CHATTERBOX_REQUIREMENTS = HERE / "requirements-chatterbox.txt"

SIDECAR_ENV_NAME = "sidecar"
CHATTERBOX_ENV_NAME = "chatterbox"

# Dedicated Python 3.14 for the ISOLATED chatterbox env (A4): chatterbox-tts
# 0.1.7 only accepts torch>=2.9.0 (we pin 2.10.0) on python_version>="3.14",
# while the sidecar env is LOCKED to py3.12 (kokoro-onnx needs <3.14). A second
# embeddable is staged at build prep (build/python-embed-setup.ps1 ->
# build/python-embed-314) and shipped to <resources>/python-chatterbox.
CHATTERBOX_PYTHON_VERSION = "3.14.0"  # human verifies the exact patch on first GPU install
#: the electron-builder.yml extraResources ``to:`` target (mirrors
#: media_studio.features.tts.chatterbox.CHATTERBOX_PYTHON_SUBDIR — keep in sync).
CHATTERBOX_EMBED_DIRNAME = "python-chatterbox"

#: options a requirements file may carry besides pinned requirement lines
ALLOWED_REQ_OPTIONS: tuple[str, ...] = ("--extra-index-url", "--index-url")

# Subprocess runner seam: (argv, extra_env) -> returncode. Stdio is INHERITED
# (stdout/stderr flow to the console/log) — no PIPE, nothing to drain (A6.2).
RunStep = Callable[[Sequence[str], dict[str, str] | None], int]
# URL opener seam for the get-pip fallback download.
UrlOpen = Callable[[str], Any]


class BootstrapError(RuntimeError):
    """A typed first-run setup failure (exit non-zero with a FAILED line)."""


def _log(message: str) -> None:
    """Progress lines go to stderr (stdout stays clean, mirroring the sidecar)."""
    print(f"[bootstrap] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# pure logic: requirements parsing (pinned-list validation)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Requirements:
    """A validated requirements file: pinned specs + allowed option lines."""

    pins: tuple[str, ...]
    options: tuple[str, ...]


def parse_requirements(text: str) -> Requirements:
    """Parse + VALIDATE a requirements file body (pure function).

    Rules (A6 lesson 5 — first-run pip must not resolve loose from PyPI):
      * blank lines and ``#`` comments are dropped (inline `` #`` too);
      * option lines must be one of :data:`ALLOWED_REQ_OPTIONS`;
      * every requirement line must be PINNED (``pkg==version``);
      * an empty pin list is an error (a typo'd file must not no-op).
    """
    pins: list[str] = []
    options: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " #" in line:
            line = line.split(" #", 1)[0].strip()
        if line.startswith("-"):
            if not any(line.startswith(opt) for opt in ALLOWED_REQ_OPTIONS):
                raise BootstrapError(f"unsupported requirements option: {line!r}")
            options.append(line)
            continue
        if "==" not in line:
            raise BootstrapError(f"requirement not pinned (use pkg==version): {line!r}")
        pins.append(line)
    if not pins:
        raise BootstrapError("requirements file contains no pinned requirements")
    return Requirements(tuple(pins), tuple(options))


def load_requirements(path: Path | str) -> Requirements:
    """Read + validate a requirements file from disk."""
    p = Path(path)
    if not p.is_file():
        raise BootstrapError(f"requirements file not found: {p}")
    return parse_requirements(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# pure logic: ._pth activation rendering (A7)
# --------------------------------------------------------------------------- #
def render_pth(
    env_dir: Path | str,
    sidecar_src: Path | str | None = None,
    *,
    zip_name: str = "python312.zip",
) -> str:
    """The full ``python3XX._pth`` body activating the first-run env (pure).

    Order matters: stdlib zip, the embed dir itself, the pip --target env, the
    sidecar source (so ``-m media_studio`` works), then ``import site``
    UNCOMMENTED — the embeddable default comments it out, which breaks pip.
    """
    lines = [zip_name, ".", str(env_dir)]
    if sidecar_src is not None:
        lines.append(str(sidecar_src))
    lines.append("import site")
    return "\n".join(lines) + "\n"


def find_pth_file(embed_dir: Path | str) -> Path | None:
    """The embeddable interpreter's ``python3*._pth`` (None for a non-embed dir)."""
    hits = sorted(Path(embed_dir).glob("python3*._pth"))
    return hits[0] if hits else None


def write_pth(
    embed_dir: Path | str,
    env_dir: Path | str,
    sidecar_src: Path | str | None = None,
) -> Path | None:
    """Rewrite the embed dir's ``._pth`` with the activation body.

    Returns the written path, or ``None`` when ``embed_dir`` holds no ``._pth``
    (a full CPython / dev venv — nothing to activate, PYTHONPATH not needed
    because the env is only for the embeddable runtime).
    """
    pth = find_pth_file(embed_dir)
    if pth is None:
        return None
    zip_name = pth.stem + ".zip"  # python312._pth -> python312.zip
    pth.write_text(render_pth(env_dir, sidecar_src, zip_name=zip_name), encoding="utf-8")
    return pth


def activate_embed_pth(
    embed_dir: Path | str,
    env_dir: Path | str,
    sidecar_src: Path | str | None = None,
) -> Path | None:
    """GUARDED ``._pth`` activation — the runtime never depends on this write.

    The embeddable ``._pth`` lives in the INSTALL dir (beside ``python.exe``). On
    a read-only install location — e.g. ``C:\\Program Files`` — rewriting it
    raises :class:`PermissionError`/:class:`OSError`. That MUST NOT abort
    first-run setup: the env itself installs into the writable DATA ROOT, and the
    sidecar self-activates it from there at startup
    (:func:`media_studio.__main__._activate_sidecar_env`). So a failed ``._pth``
    write is a logged, NON-fatal degradation here — never the silent ``exit 1``
    that produced an empty data dir and made find-shorts/AI fail downstream.

    Returns the written ``._pth`` path, ``None`` when the dir holds no ``._pth``
    (a full CPython / dev venv), or ``None`` when the install dir is not writable.
    """
    try:
        return write_pth(embed_dir, env_dir, sidecar_src)
    except OSError as exc:
        _log(
            f"install dir not writable — skipping ._pth activation at {embed_dir} "
            f"({exc}); the sidecar will self-activate the env from the data dir "
            f"({env_dir}) instead"
        )
        return None


# --------------------------------------------------------------------------- #
# pure logic: pip step argv building (mirrors assets.manager's env installer)
# --------------------------------------------------------------------------- #
#: step-2 invokes pip through a ``python -c`` prelude that inserts the env dir
#: onto ``sys.path`` at RUNTIME before importing pip, instead of ``python -m
#: pip``. The embeddable interpreter runs in ISOLATED mode (it IGNORES
#: PYTHONPATH), and on a READ-ONLY install dir (e.g. ``C:\\Program Files``) the
#: ``._pth`` that would otherwise put the env dir on ``sys.path`` cannot be
#: rewritten — :func:`activate_embed_pth` logs + skips that write, NON-fatally.
#: With plain ``python -m pip`` that combination dies with "No module named pip"
#: (the read-only-install first-run trap). The prelude depends on NEITHER the
#: ``._pth`` NOR PYTHONPATH, so step 2 imports step 1's pip whether or not the
#: install dir was writable. The pip args follow as REAL argv tokens (``python
#: -c PRELUDE install --target ... -r ...`` — the prelude re-exposes them via
#: ``sys.argv``), so each stays individually inspectable.
_STEP2_PIP_PRELUDE = (
    "import runpy, sys; "
    "sys.path.insert(0, {env!r}); "
    "sys.argv = ['pip', *sys.argv[1:]]; "
    "runpy.run_module('pip', run_name='__main__')"
)


def build_pip_steps(
    python_exe: Path | str,
    get_pip: Path | str,
    env_dir: Path | str,
    req_file: Path | str,
    *,
    pip_pin: str = PINNED_PIP,
    lock_file: Path | str | None = None,
) -> list[dict[str, Any]]:
    """The two argv steps installing a pinned ``pip --target`` env (pure; A7).

      1. ``python get-pip.py <pip pin> --target <env>`` — embeddable CPython has
         no ensurepip; get-pip forwards its args to the pip it bootstraps.
      2. ``python -c <prelude> install --target <env> -r <requirements>`` — the
         :data:`_STEP2_PIP_PRELUDE` prelude inserts ``<env>`` onto ``sys.path``
         at runtime, then runs pip with the trailing argv, so step 1's pip is
         importable EVEN when the ``._pth`` could not be rewritten (a read-only
         install dir). ``PYTHONPATH=<env>`` is still set for a non-embeddable /
         non-isolated python. Index options (``--extra-index-url``) live INSIDE
         the requirements file — pip reads them from there, no CLI plumbing.
         When ``lock_file`` is given (WU C4)
         step 2 installs the fully-hashed lock instead, adding
         :data:`HASHED_LOCK_PIP_ARGS` (``--require-hashes --only-binary=:all:
         --no-deps``) so every wheel over the FULL transitive closure is
         hash-verified before pip unpacks it — closing the gap where the
         top-level ``req_file`` pins still let transitives resolve unhashed.

    argv LISTS only (A6 lesson 4); paths with spaces stay single elements.
    """
    env_dir_s = str(env_dir)
    install_source = str(lock_file) if lock_file is not None else str(req_file)
    hash_args = list(HASHED_LOCK_PIP_ARGS) if lock_file is not None else []
    return [
        {
            "argv": [
                str(python_exe),
                str(get_pip),
                pip_pin,
                "--target",
                env_dir_s,
                "--no-warn-script-location",
            ],
            "env": {},
        },
        {
            "argv": [
                str(python_exe),
                "-c",
                _STEP2_PIP_PRELUDE.format(env=env_dir_s),
                "install",
                "--target",
                env_dir_s,
                *hash_args,
                "--no-warn-script-location",
                "-r",
                install_source,
            ],
            "env": {"PYTHONPATH": env_dir_s},
        },
    ]


def _default_run_step(argv: Sequence[str], extra_env: dict[str, str] | None = None) -> int:
    """Run one step with INHERITED stdio (no PIPE to drain — A6 lesson 2)."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(list(argv), env=env)  # noqa: S603 - argv list, no shell
    return proc.returncode


def run_steps(steps: Sequence[dict[str, Any]], *, run_step: RunStep = _default_run_step) -> None:
    """Execute pip steps sequentially; a non-zero exit raises (A6 lesson 3)."""
    for index, step in enumerate(steps, start=1):
        _log(f"step {index}/{len(steps)}: {' '.join(step['argv'])}")
        code = run_step(step["argv"], step.get("env") or None)
        if code != 0:
            raise BootstrapError(f"setup step {index} failed (exit {code}): {' '.join(step['argv'])}")


# --------------------------------------------------------------------------- #
# get-pip.py (staged offline copy preferred; stdlib download fallback)
# --------------------------------------------------------------------------- #
def ensure_get_pip(
    root: Path,
    embed_dir: Path | None = None,
    *,
    urlopen: UrlOpen = urllib.request.urlopen,
    get_pip_sha256: str = GET_PIP_SHA256,
    settings: dict[str, Any] | None = None,
) -> Path:
    """Locate (or fetch) get-pip.py, sha256-VERIFIED before it is ever run (F3c).

    Order: the staged copy beside the embeddable python (python-embed-setup.ps1
    puts one there so first run can work offline) -> a previously cached copy
    under ``<root>/tools/`` -> download via stdlib urllib (httpx is not
    installed yet at this point — the sidecar env is what we're building).

    get-pip.py is downloaded-then-EXECUTED (:func:`build_pip_steps` step 1), so a
    tampered/MITM'd script would run with the interpreter's privileges. Every
    return path is therefore checked against ``get_pip_sha256`` (the manager's
    pinned :data:`GET_PIP_SHA256`; injectable so tests use small fixtures):
      * the download is verified BEFORE ``write_bytes`` — tampered bytes never
        touch disk (no write-before-verify);
      * the staged AND the cached copies are re-verified ON READ — a poisoned
        ``<root>/tools/get-pip.py`` (bootstrap and the manager share it) is
        rejected loudly instead of silently trusted+executed.
    A mismatch raises the typed :class:`BootstrapError` (fail loud).

    When ``settings`` is supplied (the packaged first-run path threads the
    persisted store), the DOWNLOAD path is offline-consent-gated first — a user
    with ``offline=true`` gets a typed refusal, never a silent egress. Using a
    staged/cached local copy stays allowed offline (no network). ``settings`` is
    left ``None`` by the pure-logic callers/tests so the guard is opt-in and no
    real config is read where it isn't wanted.
    """

    def _verify(data: bytes) -> None:
        actual = hashlib.sha256(data).hexdigest()
        if actual != get_pip_sha256:
            raise BootstrapError(f"get-pip.py sha256 mismatch: expected {get_pip_sha256}, got {actual}")

    if embed_dir is not None:
        staged = Path(embed_dir) / "get-pip.py"
        if staged.is_file():
            _verify(staged.read_bytes())
            return staged
    cached = Path(ensure_within(root, "tools", "get-pip.py"))
    if cached.is_file():
        _verify(cached.read_bytes())
        return cached
    if settings is not None:  # offline-consent gate — refuse egress before any I/O
        from media_studio.features.offline import guard_network

        guard_network(settings, "downloading get-pip.py")
    _log(f"downloading get-pip.py from {GET_PIP_URL}")
    cached.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(GET_PIP_URL) as resp:  # noqa: S310 - pinned https URL
            data = resp.read()
    except Exception as exc:  # noqa: BLE001 - surface as a typed failure
        raise BootstrapError(f"could not download get-pip.py: {exc}") from exc
    _verify(data)  # verify-before-persist: tampered bytes are never written/run
    cached.write_bytes(data)
    return cached


# --------------------------------------------------------------------------- #
# dedicated py3.14 interpreter resolution (chatterbox env)
# --------------------------------------------------------------------------- #
def chatterbox_python_exe(resources_dir: Path | str | None = None) -> Path | None:
    """Locate the dedicated py3.14 embeddable's ``python.exe``, or ``None``.

    The py3.12 sidecar embed ships at ``<resources>/python/`` and the py3.14
    chatterbox embed at the sibling ``<resources>/python-chatterbox/`` (the
    ``electron-builder.yml`` ``to:`` targets). The resources root defaults to
    the RUNNING interpreter's grandparent (``Path(sys.executable).parent.parent``
    — the embed dir's parent), so a packaged first run finds the sibling without
    any extra wiring. Returns ``None`` when the second embed is not staged (a
    dev box) — the caller then falls back to the host interpreter (honest
    degradation: pip cannot resolve torch 2.10 under py3.12, so it fails loudly).
    """
    base = Path(resources_dir) if resources_dir is not None else Path(sys.executable).parent.parent
    candidate = base / CHATTERBOX_EMBED_DIRNAME / "python.exe"
    return candidate if candidate.is_file() else None


# --------------------------------------------------------------------------- #
# env install (sidecar / chatterbox)
# --------------------------------------------------------------------------- #
def write_env_sentinel(env_dir: Path, name: str, reqs: Requirements) -> Path:
    """Write the same success sentinel the U4 env installer writes, so the
    asset manager's installed-detection agrees with a bootstrap-built env."""
    sentinel = Path(ensure_within(env_dir, ENV_SENTINEL))
    sentinel.write_text(
        json.dumps({"name": name, "requirements": list(reqs.pins)}, indent=2),
        encoding="utf-8",
    )
    return sentinel


def hashed_lock_path(req_file: Path | str) -> Path:
    """The sibling fully-hashed lock for a requirements file (WU C4).

    ``requirements-sidecar.txt`` -> ``requirements-sidecar.lock.txt``. Its
    CONTENT is an F1 build-prep artifact (real hashes need PyPI + the cu128 torch
    index), staged offline like the ffmpeg binary — not committed to the tree.
    """
    p = Path(req_file)
    return p.with_name(f"{p.stem}.lock.txt")


def resolve_active_lock(req_file: Path | str, lock_file: Path | str | None) -> Path | None:
    """Pick the hashed lock to install from — verify-before-exec, NEVER silent.

    Explicit ``lock_file`` overrides; otherwise the sibling
    :func:`hashed_lock_path` is used when staged. A present lock is validated
    (fail LOUD on any unhashed/unpinned line); a DECLARED-but-UNSTAGED lock logs
    a LOUD line and returns ``None`` so the caller falls back to the pinned
    ``req_file`` (top-level pins; transitives unhashed — the pre-C4 behaviour),
    rather than silently skipping the env.
    """
    candidate = Path(lock_file) if lock_file is not None else hashed_lock_path(req_file)
    if not candidate.is_file():
        _log(
            f"hashed lock not staged (F1 build-prep): {candidate} — installing from "
            f"pinned {Path(req_file).name} (top-level pins; transitives resolve UNHASHED)"
        )
        return None
    try:
        validate_hashed_lock(candidate.read_text(encoding="utf-8"))  # fail loud on a bad lock
    except AssetError as exc:  # normalize into bootstrap's typed failure contract
        raise BootstrapError(f"invalid hashed lock {candidate}: {exc}") from exc
    _log(f"hashed lock staged: {candidate} — pip will hash-verify every wheel before exec")
    return candidate


def install_env(
    *,
    python_exe: Path | str,
    root: Path,
    env_name: str,
    req_file: Path,
    embed_dir: Path | None = None,
    run_step: RunStep = _default_run_step,
    urlopen: UrlOpen = urllib.request.urlopen,
    lock_file: Path | str | None = None,
    get_pip_sha256: str = GET_PIP_SHA256,
    settings: dict[str, Any] | None = None,
) -> Path:
    """Build ``<root>/envs/<env_name>`` from a PINNED requirements file.

    When a sibling fully-hashed lock is staged (WU C4; F1 build-prep), the env
    installs from IT with ``--require-hashes`` so every wheel over the full
    transitive closure is hash-verified before exec; otherwise it falls back
    LOUDLY to the top-level pins in ``req_file``. get-pip.py is sha256-verified
    (``get_pip_sha256``) before it is executed (F3c); ``settings`` (when given)
    offline-consent-gates a get-pip.py DOWNLOAD.
    """
    reqs = load_requirements(req_file)  # validate BEFORE any subprocess runs
    active_lock = resolve_active_lock(req_file, lock_file)
    env_dir = Path(ensure_within(root, "envs", env_name))
    env_dir.mkdir(parents=True, exist_ok=True)
    get_pip = ensure_get_pip(root, embed_dir, urlopen=urlopen, get_pip_sha256=get_pip_sha256, settings=settings)
    steps = build_pip_steps(python_exe, get_pip, env_dir, req_file, lock_file=active_lock)
    run_steps(steps, run_step=run_step)
    write_env_sentinel(env_dir, f"{env_name}-env", reqs)
    _log(f"env ready: {env_dir} ({len(reqs.pins)} pinned packages)")
    return env_dir


# --------------------------------------------------------------------------- #
# asset downloads (delegated to the U4 manager — A7 "delegates to assets.ensure")
# --------------------------------------------------------------------------- #
class _ConsoleJobCtx:
    """A minimal job-context shim for AssetManager.ensure outside the RPC loop."""

    cancelled = False

    @staticmethod
    def progress(pct: float, message: str) -> None:
        _log(f"assets {pct:5.1f}%  {message}")

    @staticmethod
    def raise_if_cancelled() -> None:
        return None


def default_first_run_assets() -> list[str]:
    """The core asset set first run installs (models + llama-server builds).

    Includes the vendored Light-ASD / S3FD active-speaker weights: they were
    registered on-demand but never in the first-run set, so a fresh install had
    no way to run the multi-speaker reframe engine and silently fell back to a
    single-speaker/centre crop. Provisioning them up front (sha256-pinned, ~90MB)
    keeps the engine's on-demand path honest — present, or a loud failure.
    """
    from media_studio import tools_resolver
    from media_studio.assets import manifest

    return [
        manifest.WHISPER_ASSET_NAME,
        manifest.QWEN_ASSET_NAME,
        tools_resolver.LLAMA_CUDA_ASSET,
        tools_resolver.LLAMA_CUDART_ASSET,
        tools_resolver.LLAMA_CPU_ASSET,
        manifest.LIGHTASD_S3FD_ASSET_NAME,
        manifest.LIGHTASD_ASD_ASSET_NAME,
        # v1.2.0 WU1: the YuNet face-detection ONNX for the claudeshorts reframe
        # engine. Provisioned up front (sha256-pinned, ~0.23MB) so the engine's
        # detector is present or fails LOUD — never a silent centre crop.
        manifest.YUNET_ASSET_NAME,
    ]


def core_first_run_assets() -> list[str]:
    """The CORE-ONLY marker set — the always-on face/ASD weights (WU C3).

    These are the ONLY downloaded assets the :data:`FIRST_RUN_COMPLETE_MARKER`
    attests, alongside the structural env + bundled ffmpeg: the YuNet subject
    tracker and the S3FD / LR-ASD active-speaker weights that make the reframe
    engine follow a real speaker instead of silently centre-cropping (the
    no-silent-fallback floor).

    Everything else a first run may pull — the Whisper / Qwen GGUFs, the
    llama-server builds, TTS voices, and the on-demand ViNet-S saliency /
    TransNetV2 scene-cut weights — is FETCHED AT POINT-OF-USE and lives OUTSIDE
    the marker. So a Minimum / Custom install that skips them opens PROVISIONED
    (no re-bootstrap loop, never "setup incomplete"); a missing on-demand model
    surfaces as a loud "Needs download" at its own feature, never a silent
    degrade. Mirrors ``firstRunGate.ts`` ``CORE_FIRST_RUN_ASSETS`` (kept in sync).
    """
    from media_studio.assets import manifest

    return [
        manifest.YUNET_ASSET_NAME,
        manifest.LIGHTASD_S3FD_ASSET_NAME,
        manifest.LIGHTASD_ASD_ASSET_NAME,
    ]


def ensure_assets(names: Sequence[str], root: Path, *, manager: Any | None = None) -> None:
    """Run the U4 download/install machinery in-process (httpx must be importable
    by now — the sidecar env is installed + site-dir'd before this runs).

    The default manager is wired with the PERSISTED settings (``SettingsStore``),
    NOT a blind ``{}``. bootstrap genuinely re-runs on an established install (the
    silent WU-S2 re-bootstrap on requirements-fingerprint drift, and the
    "Retry setup"/repair flow), so a settings-blind manager here would (a) BYPASS
    the ``offline`` consent gate — ``manager.ensure`` calls
    ``guard_network(self._settings())`` before any egress, which with ``{}`` never
    sees a user's ``offline=true`` — and (b) miss the custom-path detect probes
    (``ggufPath``/``modelsDir``/``llamaServerPath``), re-downloading models the
    user already has elsewhere. Threading the real store closes both gaps.
    """
    if manager is None:
        from media_studio.assets.manager import AssetManager

        manager = AssetManager(root=root, settings_provider=SettingsStore().get)
    manager.ensure(list(names), _ConsoleJobCtx())


def activate_env_in_process(env_dir: Path) -> None:
    """Make the freshly installed env importable in THIS process (for step 3)."""
    import site

    site.addsitedir(str(env_dir))


# --------------------------------------------------------------------------- #
# fail-loud provisioning verification + first-run-complete marker
# --------------------------------------------------------------------------- #
#: written at ``<root>/`` ONLY after the CORE-ONLY first run succeeds — the pip
#: env + bundled ffmpeg + the always-on face/ASD weights
#: (:func:`core_first_run_assets`), NOT "every model + weights" (WU C3). Its
#: presence is the honest "the reframe floor is provisioned" signal the Electron
#: supervisor gates re-runs on — distinct from the per-env sentinel
#: (``.media-studio-env.json``), which only means "the pip env is installed".
#: A run that installs the env but then fails on a CORE face/ASD weight leaves NO
#: marker, so the next launch retries instead of silently centre-cropping. But an
#: on-demand model (GGUFs / TTS voices / ViNet-S saliency / TransNetV2) that fails
#: or is skipped does NOT block the marker — those live OUTSIDE it and are fetched
#: at point-of-use, so a Minimum/Custom install opens provisioned (no re-bootstrap
#: loop) rather than perpetually "un-provisioned".
FIRST_RUN_COMPLETE_MARKER = ".first-run-complete.json"


def first_run_complete_path(root: Path | str) -> Path:
    """The first-run-complete marker path under ``root`` (confined sink)."""
    return Path(ensure_within(root, FIRST_RUN_COMPLETE_MARKER))


def _default_asset_manager(root: Path) -> Any:
    """Construct the real :class:`AssetManager` (lazy import — httpx et al. only
    exist once the sidecar env is installed + site-dir'd).

    Wired with the PERSISTED settings (``SettingsStore``) so the
    :func:`verify_provisioned` detect probes honour a user's custom model paths
    (``ggufPath``/``modelsDir``/…) on re-bootstrap/repair, same as the RPC path —
    never the settings-blind ``{}`` that a bare ``AssetManager(root=root)`` gets.
    """
    from media_studio.assets.manager import AssetManager

    return AssetManager(root=root, settings_provider=SettingsStore().get)


def verify_provisioned(
    names: Sequence[str],
    root: Path,
    *,
    manager: Any | None = None,
) -> None:
    """FAIL LOUD if any expected asset did not actually land on disk.

    ``ensure_assets`` already raises when a download fails, but this is the
    explicit no-silent-fallback gate: a bootstrap must NOT print
    ``SUCCESS`` (nor write the completion marker) while a model or the S3FD /
    LR-ASD weights are missing — that is exactly the half-provisioned state that
    left the app silently centre-cropping. Any unregistered or not-installed
    asset raises a :class:`BootstrapError` naming EVERY offender.
    """
    from media_studio.assets import manifest

    mgr = manager if manager is not None else _default_asset_manager(root)
    missing: list[str] = []
    for name in names:
        entry = manifest.get_asset(name)
        if entry is None or mgr.installed_path(entry) is None:
            missing.append(name)
    if missing:
        raise BootstrapError(
            "first-run provisioning incomplete — these assets did not install: "
            f"{', '.join(missing)} | fix: relaunch to retry the download (check "
            "network + free disk space); the app will not run half-provisioned"
        )


def write_first_run_complete(root: Path | str, names: Sequence[str]) -> Path:
    """Write the first-run-complete marker recording the provisioned asset set."""
    marker = first_run_complete_path(root)
    marker.write_text(
        json.dumps({"assets": list(names)}, indent=2),
        encoding="utf-8",
    )
    return marker


# --------------------------------------------------------------------------- #
# tool-archive extraction (llama-server zips -> tools/<dir>/)
# --------------------------------------------------------------------------- #
def _safe_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Reject zip-slip member names (absolute paths / ``..`` escapes)."""
    members = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts or (len(name) > 1 and name[1] == ":"):
            raise BootstrapError(f"unsafe zip member path: {info.filename!r}")
        members.append(info)
    return members


def extract_archive(zip_path: Path, target: Path) -> None:
    """Extract a tool zip into ``target`` (zip-slip-guarded)."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = _safe_members(zf)
        zf.extractall(target, members=members)  # noqa: S202 - members validated above


def flatten_tool_dir(target: Path, marker: str) -> None:
    """Hoist a nested release layout so ``marker`` sits at the dir root.

    ggml-org zips have shipped both flat layouts and ``build/bin/`` nesting;
    the resolver expects ``<target>/<marker>``. Idempotent; a missing marker is
    left alone (e.g. the cudart zip carries only DLLs, already flat).
    """
    if (target / marker).exists():
        return
    hits = sorted(target.rglob(marker))
    if not hits:
        return
    src_dir = hits[0].parent
    for item in list(src_dir.iterdir()):
        dest = target / item.name
        if dest.exists():
            continue
        shutil.move(str(item), str(dest))


def extract_tool_archives(
    root: Path,
    *,
    archives: Sequence[Any] | None = None,
    remove_zip: bool = True,
) -> list[str]:
    """Extract every downloaded tool archive registered in the manifest.

    Consumes :data:`media_studio.tools_resolver.TOOL_ARCHIVES`. A zip that was
    never downloaded (asset not ensured) is skipped silently — extraction is
    re-runnable (``--tools-only`` after a UI-driven assets.ensure works too).
    """
    from media_studio import tools_resolver
    from media_studio.assets import manifest

    done: list[str] = []
    cleared: set[Path] = set()
    for arch in archives if archives is not None else tools_resolver.TOOL_ARCHIVES:
        entry = manifest.get_asset(arch.asset)
        if entry is None or not entry.dest:
            continue
        zip_path = Path(entry.dest)
        if not zip_path.is_absolute():
            zip_path = Path(ensure_within(root, entry.dest))
        if not zip_path.is_file():
            continue
        target = Path(ensure_within(root, arch.extract_to))
        # Clear a stale build ONCE per target on a LLAMA_RELEASE_TAG bump so a new
        # nested layout can't inherit an old exe (the version-aware detect gate
        # keys off RELEASE_TAG_MARKER; without a wipe an old marker/exe lingers and
        # assets.ensure never re-provisions). Guard by `cleared` so a SECOND archive
        # extracting INTO the same dir (the cudart zip lands in the CUDA build dir)
        # does NOT wipe what a prior archive just populated.
        if target not in cleared:
            if target.exists():
                shutil.rmtree(target)
            cleared.add(target)
        _log(f"extracting {arch.asset} -> {target}")
        extract_archive(zip_path, target)
        flatten_tool_dir(target, tools_resolver.LLAMA_EXE)
        (target / tools_resolver.RELEASE_TAG_MARKER).write_text(tools_resolver.LLAMA_RELEASE_TAG, encoding="utf-8")
        if remove_zip:
            zip_path.unlink()
        done.append(arch.asset)
    return done


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap",
        description="media-studio first-run runtime setup (CONTRACTS.md A7/T5)",
    )
    parser.add_argument("--root", help="assets root (default: %%APPDATA%%/media-studio)")
    parser.add_argument(
        "--python",
        help="the embeddable python.exe to install for (default: this interpreter)",
    )
    parser.add_argument(
        "--chatterbox-python",
        help=(
            "the dedicated py3.14 embeddable for the --chatterbox env "
            "(default: auto-resolve <resources>/python-chatterbox, else host)"
        ),
    )
    parser.add_argument(
        "--requirements",
        help=f"override the sidecar requirements file (default: {SIDECAR_REQUIREMENTS.name})",
    )
    parser.add_argument(
        "--assets",
        nargs="*",
        help="asset names to ensure (default: the core first-run set)",
    )
    parser.add_argument("--skip-env", action="store_true", help="skip the sidecar env install")
    parser.add_argument("--skip-assets", action="store_true", help="skip model/tool downloads")
    parser.add_argument(
        "--tools-only",
        action="store_true",
        help="only extract already-downloaded tool archives, then exit",
    )
    parser.add_argument(
        "--chatterbox",
        action="store_true",
        help="also build the isolated chatterbox (torch) env",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the planned steps and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = Path(args.root) if args.root else default_config_dir()
    python_exe = Path(args.python) if args.python else Path(sys.executable)
    embed_dir = python_exe.parent
    req_file = Path(args.requirements) if args.requirements else SIDECAR_REQUIREMENTS

    try:
        if args.dry_run:
            reqs = load_requirements(req_file)
            env_dir = root / "envs" / SIDECAR_ENV_NAME
            get_pip = root / "tools" / "get-pip.py"
            for step in build_pip_steps(python_exe, get_pip, env_dir, req_file):
                _log(f"DRY-RUN argv: {step['argv']}")
            _log(f"DRY-RUN pins: {', '.join(reqs.pins)}")
            _log(f"DRY-RUN assets: {', '.join(args.assets or default_first_run_assets())}")
            chatter_py = Path(args.chatterbox_python) if args.chatterbox_python else chatterbox_python_exe()
            _log(f"DRY-RUN chatterbox python: {chatter_py if chatter_py is not None else '<host fallback>'}")
            print("SUCCESS:bootstrap dry-run")
            return 0

        if args.tools_only:
            extracted = extract_tool_archives(root)
            print(f"SUCCESS:bootstrap tools-only ({', '.join(extracted) or 'nothing to extract'})")
            return 0

        # The persisted store offline-consent-gates a get-pip.py DOWNLOAD (the
        # multi-GB model/asset downloads are gated inside the manager, wired via
        # ensure_assets). Read once and thread into every env install below.
        settings = SettingsStore().get()

        env_dir = Path(ensure_within(root, "envs", SIDECAR_ENV_NAME))
        if not args.skip_env:
            # Activate the ._pth BEFORE the pip steps so the embeddable's later
            # self-activation and any non-prelude tooling see the env dir. Step 2
            # itself no longer depends on the ._pth: it runs pip through the
            # runtime sys.path prelude (build_pip_steps), so first-run survives a
            # read-only install dir where the ._pth write is skipped — the case
            # that used to die 'No module named pip' under the embeddable's
            # ISOLATED mode. The chatterbox env install then reuses this same pip.
            env_dir.mkdir(parents=True, exist_ok=True)
            # GUARDED: a read-only install dir (Program Files) cannot take the
            # ._pth write — that is logged + skipped, NOT fatal. The env installs
            # into the writable data root and the sidecar self-activates it there.
            activate_embed_pth(embed_dir, env_dir, _SIDECAR_DIR)
            env_dir = install_env(
                python_exe=python_exe,
                root=root,
                env_name=SIDECAR_ENV_NAME,
                req_file=req_file,
                embed_dir=embed_dir,
                settings=settings,
            )

        asset_names: list[str] = []
        core_names: list[str] = []
        if not args.skip_assets:
            asset_names = list(args.assets or default_first_run_assets())
            # step 3 needs httpx from the just-installed env in THIS process.
            activate_env_in_process(env_dir)
            ensure_assets(asset_names, root)
            extract_tool_archives(root)
            # CORE-ONLY marker gate (WU C3): NO SILENT FALLBACK for the always-on
            # face/ASD weights — prove the CORE subset that was part of THIS run
            # actually landed (a missing tracker/ASD weight is the silent
            # centre-crop trap) before we ever claim success. On-demand models
            # (GGUFs / TTS voices / ViNet-S saliency / TransNetV2) may fail or be
            # skipped WITHOUT blocking the marker — ensure already logged each
            # skip loudly and they are fetched at point-of-use, so a Minimum/
            # Custom install opens provisioned instead of looping bootstrap.
            core_names = [n for n in asset_names if n in core_first_run_assets()]
            verify_provisioned(core_names, root)

        if args.chatterbox:
            # The chatterbox env installs with the DEDICATED py3.14 interpreter
            # (the only one torch 2.10 resolves under): explicit override ->
            # auto-resolved <resources>/python-chatterbox -> host fallback. Its
            # embed dir is the py3.14 dir (get-pip.py is staged beside it); the
            # host fallback reuses the sidecar embed dir. A host fallback fails
            # loudly at pip-resolve time (py3.12 cannot install torch 2.10) — by
            # design, never a silent wrong-version install.
            chatter_py = Path(args.chatterbox_python) if args.chatterbox_python else chatterbox_python_exe()
            if chatter_py is not None:
                chatter_embed: Path = Path(chatter_py).parent
            else:
                chatter_py, chatter_embed = python_exe, embed_dir
            install_env(
                python_exe=chatter_py,
                root=root,
                env_name=CHATTERBOX_ENV_NAME,
                req_file=CHATTERBOX_REQUIREMENTS,
                embed_dir=chatter_embed,
                settings=settings,
            )

        # A CORE-complete run (env + the always-on face/ASD weights) is a
        # completed first run (WU C3): the marker records the CORE set it
        # attests, not the on-demand extras. Partial invocations (--skip-env /
        # --skip-assets, used for manual repair) must NOT write the marker, or
        # the supervisor would skip a real re-run.
        if not args.skip_env and not args.skip_assets:
            write_first_run_complete(root, core_names)

        print("SUCCESS:bootstrap first-run setup complete")
        return 0
    except BootstrapError as exc:
        print(f"FAILED:bootstrap {exc}")
        return 1
    except KeyboardInterrupt:
        print("FAILED:bootstrap interrupted")
        return 130
    # FAIL LOUD + ACTIONABLE: an unexpected setup failure (e.g. a PermissionError
    # writing the data dir, a disk-full OSError) must NOT escape as a bare
    # traceback / silent exit 1 that leaves an EMPTY data dir — the exact
    # real-machine failure (Program Files install -> unguarded ._pth write ->
    # exit 1 -> find-shorts/AI fail silently). Every path here prints a single
    # terminal FAILED: line naming WHAT failed, WHERE (the data root), and HOW to
    # fix it; the Electron supervisor relays that line to the UI error channel.
    except PermissionError as exc:
        print(
            f"FAILED:bootstrap permission denied during first-run setup: {exc} | "
            f"data root={root} | fix: pick a writable data folder in Settings "
            f"(or set MEDIA_STUDIO_CONFIG_DIR) and relaunch — the runtime never "
            f"needs to write the install dir"
        )
        return 1
    except OSError as exc:
        print(
            f"FAILED:bootstrap I/O error during first-run setup: {exc} | "
            f"data root={root} | fix: ensure the data folder exists, is writable, "
            f"and has free disk space, then relaunch"
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - last-resort: never a silent traceback
        print(
            f"FAILED:bootstrap unexpected first-run setup error: "
            f"{type(exc).__name__}: {exc} | data root={root} | "
            f"fix: retry the launch; if it persists, reinstall to a writable "
            f"location and report this message"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
