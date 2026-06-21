"""Asset download + runtime-setup manager (PLAN-P2 U4 / CONTRACTS.md A2/A3/A7).

Implements:
  * ``assets.list`` — wire ``AssetInfo`` view of the manifest; ``installed`` is
    derived from the filesystem (dest exists / size plausible / env sentinel /
    HF cache snapshot / settings-driven detect probe).
  * ``assets.ensure`` — a long JOB (jobId + job.progress + job.done): disk
    preflight, httpx streaming download with **Range resume**, atomic
    temp(.part)+rename, optional sha256 verification, an ``hf`` installer
    (huggingface_hub snapshot into HF_HOME), and an ``env`` installer that
    bootstraps ``%APPDATA%/media-studio/envs/<name>`` via get-pip + ``pip
    --target`` with a PINNED requirements list (A7: embeddable CPython has no
    ensurepip/venv).

Heavy/network seams (httpx client, huggingface_hub, subprocess runner, disk
usage) are all injectable so tests never touch the network or spawn processes.
A6 lessons honored: argv lists only (never shell), every subprocess pipe is
drained (``subprocess.run`` -> ``communicate`` internally), failures surface as
exceptions the job framework converts into the ``job.done`` error payload, and
nothing here imports torch or any native module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess  # noqa: S404 - argv-list subprocess only, never shell=True
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..jobs import JobCancelled
from ..settings_store import default_config_dir
from ..util import clamp, get_logger
from . import manifest
from .manifest import AssetEntry

log = get_logger("media_studio.assets.manager")

MB = 1024 * 1024
#: streaming chunk size for downloads
CHUNK_SIZE = 1 * MB
#: extra free space demanded beyond the asset's own size (working headroom)
DISK_MARGIN_MB = 256
#: an existing dest file smaller than this fraction of the declared sizeMB is
#: treated as NOT installed (a truncated/garbage leftover, not the artifact).
MIN_SIZE_FRACTION = 0.5

# A7 env bootstrap pins. get-pip.py itself is a bootstrap script (not versioned
# by URL); the pip it installs IS pinned via the requirement argument below.
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
GET_PIP_SIZE_MB = 4
PINNED_PIP = "pip==25.2"
#: success sentinel written into an env dir after a full install
ENV_SENTINEL = ".media-studio-env.json"

# (frac 0..1, message) -> None — per-asset progress callback.
FracCb = Callable[[float, str], None]
# Cooperative cancel probe.
CancelProbe = Callable[[], bool]
# Subprocess runner seam: (argv, extra_env) -> (returncode, combined output).
RunCmd = Callable[[Sequence[str], dict[str, str] | None], tuple[int, str]]
# HF snapshot seam: (repo_id, revision) -> downloaded path (str).
HfFetch = Callable[[str, str | None], str]


class AssetError(RuntimeError):
    """A typed asset failure; surfaces via the job.done error payload (A6.3)."""


# --------------------------------------------------------------------------- #
# pure helpers (fully unit-testable, no I/O beyond what's passed in)
# --------------------------------------------------------------------------- #
def part_path(dest: Path) -> Path:
    """The resumable temp file beside ``dest`` (atomic temp+rename target)."""
    return dest.with_name(dest.name + ".part")


def resume_offset(part: Path) -> int:
    """Bytes already present in a partial download (0 when absent)."""
    try:
        return part.stat().st_size
    except OSError:
        return 0


def resume_headers(offset: int) -> dict[str, str]:
    """The Range header resuming from ``offset`` ({} for a fresh download)."""
    if offset > 0:
        return {"Range": f"bytes={offset}-"}
    return {}


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup that works on plain dicts and httpx.Headers."""
    getter = getattr(headers, "get", None)
    if getter is not None:
        direct = getter(name) or getter(name.lower()) or getter(name.title())
        if direct:
            return str(direct)
    for key in headers:
        if str(key).lower() == name.lower():
            return str(headers[key])
    return None


_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")


def parse_total_bytes(status_code: int, headers: Mapping[str, str], offset: int) -> int | None:
    """Total artifact size implied by the response (for progress math).

    206 -> the ``Content-Range: bytes a-b/total`` total (or offset +
    Content-Length when total is ``*``); 200 -> Content-Length. ``None`` when
    the server reports nothing usable.
    """
    if status_code == 206:
        cr = _header(headers, "Content-Range") or ""
        m = _CONTENT_RANGE_RE.match(cr)
        if m and m.group(3) != "*":
            return int(m.group(3))
        cl = _header(headers, "Content-Length")
        if cl and cl.isdigit():
            return offset + int(cl)
        return None
    cl = _header(headers, "Content-Length")
    if cl and cl.isdigit():
        return int(cl)
    return None


def preflight_disk(
    target_dir: Path | str,
    size_mb: float,
    *,
    usage: Callable[[str], Any] = shutil.disk_usage,
    margin_mb: float = DISK_MARGIN_MB,
) -> None:
    """Raise :class:`AssetError` when the target volume lacks room (U4 brief).

    Walks up to the nearest EXISTING ancestor (the dest dir may not exist yet)
    before asking ``usage`` (``shutil.disk_usage``-shaped, injectable in tests).
    """
    probe = Path(target_dir)
    while not probe.exists():
        parent = probe.parent
        if parent == probe:  # filesystem root without the drive mounted
            break
        probe = parent
    free = int(usage(str(probe)).free)
    need = int((float(size_mb) + float(margin_mb)) * MB)
    if free < need:
        raise AssetError(
            f"insufficient disk space at {target_dir}: "
            f"need ~{need // MB} MB (asset {int(size_mb)} MB + margin), "
            f"free {free // MB} MB"
        )


def file_size_ok(path: Path, size_mb: float) -> bool:
    """Is an existing dest file plausibly the whole artifact? (installed check)"""
    try:
        actual = path.stat().st_size
    except OSError:
        return False
    if actual <= 0:
        return False
    if size_mb and size_mb > 0:
        return actual >= int(float(size_mb) * MB * MIN_SIZE_FRACTION)
    return True


def sha256_file(path: Path) -> str:
    """Hex sha256 of a file (streamed)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def build_env_install_argvs(
    python_exe: str,
    get_pip_path: Path | str,
    env_dir: Path | str,
    requirements: Sequence[str],
    *,
    pip_pin: str = PINNED_PIP,
) -> list[dict[str, Any]]:
    """The argv steps that bootstrap a ``pip --target`` env (A7; pure function).

    Embeddable CPython has NO ensurepip/venv, so:
      1. ``python get-pip.py <pip pin> --target <env>`` — installs a PINNED pip
         *into the env dir itself* (get-pip forwards its args to pip).
      2. ``python -m pip install --target <env> <pinned reqs...>`` with
         ``PYTHONPATH=<env>`` so step 1's pip is importable.

    Returns ``[{"argv": [...], "env": {...extra env vars...}}, ...]`` — argv
    LISTS only (A6 lesson 4: never a shell string; paths with spaces are safe).
    """
    env_dir_s = str(env_dir)
    step1 = {
        "argv": [
            str(python_exe),
            str(get_pip_path),
            pip_pin,
            "--target",
            env_dir_s,
            "--no-warn-script-location",
        ],
        "env": {},
    }
    step2 = {
        "argv": [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--target",
            env_dir_s,
            "--no-warn-script-location",
            *[str(r) for r in requirements],
        ],
        "env": {"PYTHONPATH": env_dir_s},
    }
    return [step1, step2]


def env_sentinel_path(env_dir: Path) -> Path:
    """The success sentinel inside an installed env dir."""
    return env_dir / ENV_SENTINEL


def hf_cache_dir(env_vars: Mapping[str, str] | None = None) -> Path:
    """The huggingface_hub cache dir (HF_HUB_CACHE -> HF_HOME/hub -> ~/.cache)."""
    env = env_vars if env_vars is not None else os.environ
    for key in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        value = env.get(key)
        if value:
            return Path(value)
    hf_home = env.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path(os.path.expanduser("~")) / ".cache" / "huggingface" / "hub"


def hf_repo_dir(repo_id: str, env_vars: Mapping[str, str] | None = None) -> Path:
    """The cache folder huggingface_hub uses for ``repo_id`` (models--org--name)."""
    return hf_cache_dir(env_vars) / ("models--" + repo_id.replace("/", "--"))


def hf_snapshot_present(repo_dir: Path) -> bool:
    """True when the repo cache holds at least one non-empty snapshot."""
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return False
    return any(snap.is_dir() and any(snap.iterdir()) for snap in snapshots.iterdir())


# --------------------------------------------------------------------------- #
# default seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_http_client() -> Any:
    """A streaming httpx client (lazy import keeps module import light)."""
    import httpx  # noqa: PLC0415 - lazy: only the real download path needs it

    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0))


def _default_run_cmd(argv: Sequence[str], extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run a subprocess with argv LISTS and fully-drained pipes (A6 lessons 2/4).

    ``subprocess.run`` uses ``communicate()`` internally, so stdout/stderr are
    drained continuously — a chatty pip can never fill a pipe and freeze us
    (the proven 29-min Popen-PIPE freeze). stderr is merged into stdout so the
    failure tail lands in one place for the error payload.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(  # noqa: S603 - argv list, shell never
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout or ""


def _default_hf_fetch(repo_id: str, revision: str | None) -> str:
    """Snapshot a HF repo into the standard cache (lazy huggingface_hub import).

    huggingface_hub is pure Python (already a faster-whisper transitive dep) —
    no native pre-import concern (A6 lesson 1 does not apply).
    """
    from huggingface_hub import snapshot_download  # noqa: PLC0415 - lazy seam

    return str(snapshot_download(repo_id=repo_id, revision=revision))


# --------------------------------------------------------------------------- #
# the manager
# --------------------------------------------------------------------------- #
class AssetManager:
    """List + ensure the manifest's assets on disk (the ``assets.*`` backend).

    ``root`` defaults to the per-user config dir (``%APPDATA%/media-studio``);
    relative entry dests resolve under it (``models/...``, ``envs/...``). All
    heavy seams are constructor-injectable for tests.
    """

    def __init__(
        self,
        *,
        root: str | os.PathLike | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        http_factory: Callable[[], Any] | None = None,
        run_cmd: RunCmd | None = None,
        hf_fetch: HfFetch | None = None,
        python_exe: str | None = None,
        chatterbox_python: Callable[[], str | None] | None = None,
        usage: Callable[[str], Any] | None = None,
        env_vars: Mapping[str, str] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else default_config_dir()
        self._settings_provider = settings_provider
        self._http_factory = http_factory or _default_http_client
        self._run_cmd: RunCmd = run_cmd or _default_run_cmd
        self._hf_fetch: HfFetch = hf_fetch or _default_hf_fetch
        self._python_exe = python_exe or sys.executable
        # Resolver for the dedicated py3.14 chatterbox interpreter; bound lazily
        # in _install_env (to chatterbox.default_chatterbox_python) to avoid an
        # import cycle (chatterbox imports assets.manifest). Tests inject a fake.
        self._chatterbox_python = chatterbox_python
        self._usage = usage or shutil.disk_usage
        self._env_vars = env_vars

    # -- resolution / installed state ---------------------------------------
    def resolve_dest(self, entry: AssetEntry) -> Path:
        """Absolute on-disk destination for ``entry``."""
        if entry.installer == "hf":
            return hf_repo_dir(entry.hf_repo or "", self._env_vars)
        dest = Path(entry.dest)
        return dest if dest.is_absolute() else self.root / dest

    def _settings(self) -> dict[str, Any]:
        if self._settings_provider is None:
            return {}
        try:
            return self._settings_provider() or {}
        except Exception:  # noqa: BLE001 - detection must never crash a list
            log.warning("settings provider failed; detect probes get {}")
            return {}

    def installed_path(self, entry: AssetEntry) -> str | None:
        """The existing install location, or ``None`` when not installed.

        Order: the entry's settings-driven ``detect`` probe (an existing copy
        anywhere counts) -> installer-specific dest check (HF cache snapshot /
        env sentinel match / file exists with a plausible size).
        """
        if entry.detect is not None:
            found = entry.detect(self._settings())
            if found and Path(found).is_file():
                return str(found)
        dest = self.resolve_dest(entry)
        if entry.installer == "hf":
            return str(dest) if hf_snapshot_present(dest) else None
        if entry.installer == "env":
            return str(dest) if self._env_installed(entry, dest) else None
        if dest.is_file() and file_size_ok(dest, entry.size_mb):
            return str(dest)
        return None

    def _env_installed(self, entry: AssetEntry, env_dir: Path) -> bool:
        """An env is installed when its sentinel matches the CURRENT pins."""
        sentinel = env_sentinel_path(env_dir)
        if not sentinel.is_file():
            return False
        try:
            data = json.loads(sentinel.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        return list(data.get("requirements") or []) == list(entry.requirements)

    def info(self, entry: AssetEntry) -> dict[str, Any]:
        """The wire ``AssetInfo`` (A3): {name, kind, sizeMB, installed, dest}."""
        found = self.installed_path(entry)
        return {
            "name": entry.name,
            "kind": entry.kind,
            "sizeMB": entry.size_mb,
            "installed": found is not None,
            "dest": found if found is not None else str(self.resolve_dest(entry)),
        }

    def list_assets(self) -> list[dict[str, Any]]:
        """``assets.list`` payload body: every manifest entry as AssetInfo."""
        return [self.info(entry) for entry in manifest.all_assets()]

    # -- ensure (the long job body) ------------------------------------------
    def ensure(self, names: Sequence[str], job_ctx: Any) -> dict[str, Any]:
        """Install every named asset that's missing; the ``assets.ensure`` job body.

        Preflights disk for ALL pending work FIRST (fail before any bytes
        move), then installs sequentially with size-weighted aggregate
        progress. Failures raise (-> job.done error payload, A6 lesson 3);
        cancellation raises :class:`JobCancelled` (partial downloads keep
        their ``.part`` for a later resume).

        CONTRACT-NOTE: A2 leaves assets.ensure's job.done.result unspecified;
        we return ``{installed:[name], assets:[AssetInfo]}`` so the panel can
        refresh its list straight from the done payload.
        """
        entries: list[AssetEntry] = []
        for name in names:
            entry = manifest.get_asset(str(name))
            if entry is None:
                raise AssetError(f"unknown asset: {name}")
            entries.append(entry)

        todo = [e for e in entries if self.installed_path(e) is None]

        # Offline gate: downloading a missing asset needs the network. Refuse
        # (typed) when offline AND there is anything to fetch; an all-installed
        # ensure is a no-op that stays allowed offline. Done before any bytes.
        if todo:
            from ..features.offline import guard_network  # noqa: PLC0415 - avoid cycle

            guard_network(self._settings(), "downloading assets")

        for entry in todo:
            dest = self.resolve_dest(entry)
            target_dir = dest if entry.installer in ("hf", "env") else dest.parent
            preflight_disk(target_dir, entry.size_mb, usage=self._usage)

        total_weight = sum(max(float(e.size_mb), 1.0) for e in todo) or 1.0
        done_weight = 0.0
        job_ctx.progress(0.0, "starting" if todo else "all assets already installed")

        for entry in todo:
            job_ctx.raise_if_cancelled()
            weight = max(float(entry.size_mb), 1.0)

            def on_frac(
                frac: float,
                message: str = "",
                _base: float = done_weight,
                _w: float = weight,
                _name: str = entry.name,
            ) -> None:
                pct = (_base + clamp(frac, 0.0, 1.0) * _w) / total_weight * 100.0
                job_ctx.progress(pct, message or f"installing {_name}")

            self._install(entry, on_frac=on_frac, should_cancel=lambda: job_ctx.cancelled)
            done_weight += weight

        job_ctx.progress(100.0, "done")
        return {"installed": [e.name for e in entries], "assets": self.list_assets()}

    # -- installers -----------------------------------------------------------
    def _install(self, entry: AssetEntry, *, on_frac: FracCb, should_cancel: CancelProbe) -> None:
        log.info("installing asset %s via %s", entry.name, entry.installer)
        if entry.installer == "download":
            self._download_file(
                str(entry.url),
                self.resolve_dest(entry),
                size_mb=entry.size_mb,
                sha256=entry.sha256,
                on_frac=on_frac,
                should_cancel=should_cancel,
                label=entry.name,
            )
        elif entry.installer == "hf":
            self._install_hf(entry, on_frac=on_frac, should_cancel=should_cancel)
        elif entry.installer == "env":
            self._install_env(entry, on_frac=on_frac, should_cancel=should_cancel)
        else:  # pragma: no cover - manifest validation forbids this
            raise AssetError(f"unknown installer for {entry.name}: {entry.installer}")

    def _download_file(
        self,
        url: str,
        dest: Path,
        *,
        size_mb: float = 0,
        sha256: str | None = None,
        on_frac: FracCb | None = None,
        should_cancel: CancelProbe | None = None,
        label: str = "",
    ) -> None:
        """httpx streaming download: Range resume + atomic .part+rename + sha."""
        name = label or dest.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = part_path(dest)
        offset = resume_offset(part)
        headers = resume_headers(offset)
        if offset:
            log.info("resuming %s from byte %d", name, offset)

        with self._http_factory() as client, client.stream("GET", url, headers=headers) as resp:
            status = int(resp.status_code)
            if status == 416 and offset > 0:
                # Range past EOF: the .part already holds the full body.
                self._finalize(part, dest, sha256, name)
                if on_frac:
                    on_frac(1.0, f"{name}: already downloaded")
                return
            if status == 206 and offset > 0:
                mode = "ab"
            elif status == 200:
                # Server ignored (or never saw) the Range: restart cleanly.
                mode, offset = "wb", 0
            else:
                raise AssetError(f"download failed for {name}: HTTP {status}")

            total = parse_total_bytes(status, resp.headers, offset)
            if total is None and size_mb:
                total = int(float(size_mb) * MB)
            done = offset
            with open(part, mode) as fh:
                for chunk in resp.iter_bytes(CHUNK_SIZE):
                    if should_cancel is not None and should_cancel():
                        # Keep the .part so the next ensure RESUMES (U4).
                        log.info("download of %s cancelled at byte %d", name, done)
                        raise JobCancelled(name)
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    if on_frac and total:
                        on_frac(
                            min(done / total, 0.99),
                            f"{name}: {done // MB}/{total // MB} MB",
                        )

        self._finalize(part, dest, sha256, name)
        if on_frac:
            on_frac(1.0, f"{name}: downloaded")

    def _finalize(self, part: Path, dest: Path, sha256: str | None, name: str) -> None:
        """Verify (when pinned) then atomically rename .part -> dest."""
        if not part.is_file():
            raise AssetError(f"download produced no data for {name}")
        if sha256:
            actual = sha256_file(part)
            if actual.lower() != sha256.lower():
                part.unlink(missing_ok=True)  # corrupt: force a clean restart
                raise AssetError(f"sha256 mismatch for {name}: expected {sha256}, got {actual}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, dest)

    def _install_hf(self, entry: AssetEntry, *, on_frac: FracCb, should_cancel: CancelProbe) -> None:
        """Snapshot a HF repo into the standard cache (whisper's resolver path).

        CONTRACT-NOTE: huggingface_hub manages its own resume/temp files inside
        the cache; we delegate rather than re-implement. Progress is coarse
        (start/end) — snapshot_download exposes no chunk callback.
        """
        if should_cancel():
            raise JobCancelled(entry.name)
        on_frac(0.01, f"{entry.name}: downloading from Hugging Face")
        try:
            path = self._hf_fetch(str(entry.hf_repo), entry.hf_revision)
        except Exception as exc:  # noqa: BLE001 - surface as a typed asset failure
            raise AssetError(f"hf download failed for {entry.name}: {exc}") from exc
        log.info("hf snapshot for %s at %s", entry.name, path)
        on_frac(1.0, f"{entry.name}: downloaded")

    def _resolve_env_python(self, entry: AssetEntry) -> str:
        """The interpreter that installs ``entry`` (A7+ per-entry selection).

        ``python_kind="chatterbox"`` routes to the dedicated py3.14 embeddable
        (the only interpreter ``torch==2.10`` resolves under); anything else —
        and a chatterbox entry on a box where that embed is not staged — falls
        back to the manager-wide host python (an honest degradation: pip then
        fails to resolve torch 2.10 under py3.12 and the env never registers).
        """
        if entry.python_kind == "chatterbox":
            resolver = self._chatterbox_python
            if resolver is None:
                from ..features.tts.chatterbox import default_chatterbox_python  # noqa: PLC0415 - avoid cycle

                resolver = default_chatterbox_python
            return resolver() or self._python_exe
        return self._python_exe

    def _install_env(self, entry: AssetEntry, *, on_frac: FracCb, should_cancel: CancelProbe) -> None:
        """Bootstrap a ``pip --target`` env under the assets root (A7).

        get-pip.py is fetched once (cached under ``<root>/tools/``), then the
        two pinned argv steps from :func:`build_env_install_argvs` run through
        the drained-subprocess seam. A success sentinel records the pins so
        ``installed`` flips false again if the requirements change. The
        interpreter is chosen per-entry via :meth:`_resolve_env_python` so the
        chatterbox env installs with its dedicated py3.14 embeddable.
        """
        env_dir = self.resolve_dest(entry)
        env_dir.mkdir(parents=True, exist_ok=True)
        python_exe = self._resolve_env_python(entry)
        get_pip = self.root / "tools" / "get-pip.py"
        if not get_pip.is_file():
            on_frac(0.01, f"{entry.name}: fetching get-pip.py")
            self._download_file(
                GET_PIP_URL,
                get_pip,
                size_mb=GET_PIP_SIZE_MB,
                should_cancel=should_cancel,
                label="get-pip.py",
            )
        steps = build_env_install_argvs(python_exe, get_pip, env_dir, entry.requirements)
        for index, step in enumerate(steps):
            if should_cancel():
                raise JobCancelled(entry.name)
            on_frac(
                0.05 + 0.9 * (index / len(steps)),
                f"{entry.name}: env setup step {index + 1}/{len(steps)}",
            )
            returncode, output = self._run_cmd(step["argv"], step["env"] or None)
            if returncode != 0:
                tail = "\n".join((output or "").splitlines()[-15:])
                raise AssetError(f"env install failed for {entry.name} (step {index + 1}, exit {returncode}): {tail}")
        sentinel = env_sentinel_path(env_dir)
        sentinel.write_text(
            json.dumps(
                {"name": entry.name, "requirements": list(entry.requirements)},
                indent=2,
            ),
            encoding="utf-8",
        )
        on_frac(1.0, f"{entry.name}: env ready")
