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
    GET_PIP_URL,
    PINNED_PIP,
)
from media_studio.settings_store import default_config_dir  # noqa: E402

HERE = Path(__file__).resolve().parent
SIDECAR_REQUIREMENTS = HERE / "requirements-sidecar.txt"
CHATTERBOX_REQUIREMENTS = HERE / "requirements-chatterbox.txt"

SIDECAR_ENV_NAME = "sidecar"
CHATTERBOX_ENV_NAME = "chatterbox"

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


# --------------------------------------------------------------------------- #
# pure logic: pip step argv building (mirrors assets.manager's env installer)
# --------------------------------------------------------------------------- #
def build_pip_steps(
    python_exe: Path | str,
    get_pip: Path | str,
    env_dir: Path | str,
    req_file: Path | str,
    *,
    pip_pin: str = PINNED_PIP,
) -> list[dict[str, Any]]:
    """The two argv steps installing a pinned ``pip --target`` env (pure; A7).

      1. ``python get-pip.py <pip pin> --target <env>`` — embeddable CPython has
         no ensurepip; get-pip forwards its args to the pip it bootstraps.
      2. ``python -m pip install --target <env> -r <req file>`` with
         ``PYTHONPATH=<env>`` so step 1's pip is importable. Index options
         (``--extra-index-url``) live INSIDE the requirements file — pip reads
         them from there, no CLI plumbing.

    argv LISTS only (A6 lesson 4); paths with spaces stay single elements.
    """
    env_dir_s = str(env_dir)
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
                "-m",
                "pip",
                "install",
                "--target",
                env_dir_s,
                "--no-warn-script-location",
                "-r",
                str(req_file),
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
) -> Path:
    """Locate (or fetch) get-pip.py.

    Order: the staged copy beside the embeddable python (python-embed-setup.ps1
    puts one there so first run can work offline) -> a previously cached copy
    under ``<root>/tools/`` -> download via stdlib urllib (httpx is not
    installed yet at this point — the sidecar env is what we're building).
    """
    if embed_dir is not None:
        staged = Path(embed_dir) / "get-pip.py"
        if staged.is_file():
            return staged
    cached = root / "tools" / "get-pip.py"
    if cached.is_file():
        return cached
    _log(f"downloading get-pip.py from {GET_PIP_URL}")
    cached.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(GET_PIP_URL) as resp:  # noqa: S310 - pinned https URL
            data = resp.read()
    except Exception as exc:  # noqa: BLE001 - surface as a typed failure
        raise BootstrapError(f"could not download get-pip.py: {exc}") from exc
    cached.write_bytes(data)
    return cached


# --------------------------------------------------------------------------- #
# env install (sidecar / chatterbox)
# --------------------------------------------------------------------------- #
def write_env_sentinel(env_dir: Path, name: str, reqs: Requirements) -> Path:
    """Write the same success sentinel the U4 env installer writes, so the
    asset manager's installed-detection agrees with a bootstrap-built env."""
    sentinel = env_dir / ENV_SENTINEL
    sentinel.write_text(
        json.dumps({"name": name, "requirements": list(reqs.pins)}, indent=2),
        encoding="utf-8",
    )
    return sentinel


def install_env(
    *,
    python_exe: Path | str,
    root: Path,
    env_name: str,
    req_file: Path,
    embed_dir: Path | None = None,
    run_step: RunStep = _default_run_step,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> Path:
    """Build ``<root>/envs/<env_name>`` from a PINNED requirements file."""
    reqs = load_requirements(req_file)  # validate BEFORE any subprocess runs
    env_dir = root / "envs" / env_name
    env_dir.mkdir(parents=True, exist_ok=True)
    get_pip = ensure_get_pip(root, embed_dir, urlopen=urlopen)
    steps = build_pip_steps(python_exe, get_pip, env_dir, req_file)
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
    """The core asset set first run installs (models + llama-server builds)."""
    from media_studio import tools_resolver
    from media_studio.assets import manifest

    return [
        manifest.WHISPER_ASSET_NAME,
        manifest.QWEN_ASSET_NAME,
        tools_resolver.LLAMA_CUDA_ASSET,
        tools_resolver.LLAMA_CUDART_ASSET,
        tools_resolver.LLAMA_CPU_ASSET,
    ]


def ensure_assets(names: Sequence[str], root: Path, *, manager: Any | None = None) -> None:
    """Run the U4 download/install machinery in-process (httpx must be importable
    by now — the sidecar env is installed + site-dir'd before this runs)."""
    if manager is None:
        from media_studio.assets.manager import AssetManager

        manager = AssetManager(root=root)
    manager.ensure(list(names), _ConsoleJobCtx())


def activate_env_in_process(env_dir: Path) -> None:
    """Make the freshly installed env importable in THIS process (for step 3)."""
    import site

    site.addsitedir(str(env_dir))


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
    for arch in archives if archives is not None else tools_resolver.TOOL_ARCHIVES:
        entry = manifest.get_asset(arch.asset)
        if entry is None or not entry.dest:
            continue
        zip_path = Path(entry.dest)
        if not zip_path.is_absolute():
            zip_path = root / zip_path
        if not zip_path.is_file():
            continue
        target = root / arch.extract_to
        _log(f"extracting {arch.asset} -> {target}")
        extract_archive(zip_path, target)
        flatten_tool_dir(target, tools_resolver.LLAMA_EXE)
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
            print("SUCCESS:bootstrap dry-run")
            return 0

        if args.tools_only:
            extracted = extract_tool_archives(root)
            print(f"SUCCESS:bootstrap tools-only ({', '.join(extracted) or 'nothing to extract'})")
            return 0

        env_dir = root / "envs" / SIDECAR_ENV_NAME
        if not args.skip_env:
            # Activate the ._pth BEFORE the pip steps. The embeddable ._pth runs
            # python in ISOLATED mode (it IGNORES PYTHONPATH), so pip-install
            # step 2 (`python -m pip ...`) can only import the pip that step 1
            # installs into env_dir once env_dir + `import site` are already on
            # the ._pth. get-pip.py (step 1) is self-contained, so it needs no
            # ._pth. (Without this ordering, first-run dies: 'No module named
            # pip' — caught by the real-bundle bootstrap smoke, not the mocked
            # unit tests.) The chatterbox env install then reuses this same pip.
            env_dir.mkdir(parents=True, exist_ok=True)
            write_pth(embed_dir, env_dir, _SIDECAR_DIR)
            env_dir = install_env(
                python_exe=python_exe,
                root=root,
                env_name=SIDECAR_ENV_NAME,
                req_file=req_file,
                embed_dir=embed_dir,
            )

        if not args.skip_assets:
            # step 3 needs httpx from the just-installed env in THIS process.
            activate_env_in_process(env_dir)
            ensure_assets(args.assets or default_first_run_assets(), root)
            extract_tool_archives(root)

        if args.chatterbox:
            install_env(
                python_exe=python_exe,
                root=root,
                env_name=CHATTERBOX_ENV_NAME,
                req_file=CHATTERBOX_REQUIREMENTS,
                embed_dir=embed_dir,
            )

        print("SUCCESS:bootstrap first-run setup complete")
        return 0
    except BootstrapError as exc:
        print(f"FAILED:bootstrap {exc}")
        return 1
    except KeyboardInterrupt:
        print("FAILED:bootstrap interrupted")
        return 130


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
