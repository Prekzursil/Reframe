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
import random
import re
import shutil
import subprocess  # noqa: S404 - argv-list subprocess only, never shell=True
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..jobs import JobCancelled
from ..pathsafe import clean_for_log, ensure_within
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
# F3c (security hardening): get-pip.py is DOWNLOADED then EXECUTED. The URL serves
# whatever pypa publishes today, so we VERIFY the bytes against a pinned sha256
# BEFORE executing them — a compromised/MITM'd get-pip.py is rejected at the
# .part stage (sha mismatch in _finalize), never run. Pinned 2026-06-28
# (https://bootstrap.pypa.io/get-pip.py, 2,226,848 B). Refresh this when pypa
# rotates get-pip; the seam (AssetManager(get_pip_sha256=...)) lets ops/tests
# override without a code edit.
GET_PIP_SHA256 = "a341e1a43e38001c551a1508a73ff23636a11970b61d901d9a1cad2a18f57055"
#: success sentinel written into an env dir after a full install
ENV_SENTINEL = ".media-studio-env.json"

# WU C4 — verify-before-exec over the FULL transitive closure. Top-level pins
# alone still let pip resolve UNHASHED transitives from PyPI; a fully-hashed
# lockfile installed with these flags makes pip refuse any wheel whose bytes
# don't match a pinned --hash BEFORE it unpacks/runs it:
#   --require-hashes     every requirement must carry a --hash= (fail otherwise)
#   --only-binary=:all:  no source builds — an sdist has no verifiable wheel hash
#   --no-deps            the lock IS the closure; pip resolves nothing itself
HASHED_LOCK_PIP_ARGS: tuple[str, ...] = ("--require-hashes", "--only-binary=:all:", "--no-deps")
#: option lines a hashed lock may carry besides pinned+hashed requirements. The
#: cu128 torch index is a STILL-HASHED per-index exception: the custom index URL
#: is permitted, but every wheel it serves is hash-verified all the same.
LOCK_ALLOWED_OPTIONS: tuple[str, ...] = ("--extra-index-url", "--index-url")

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


class AssetIntegrityError(AssetError):
    """A sha256 mismatch on a downloaded artifact (WU C1).

    A distinct subclass so the retry loop treats it as DEFINITIVE (a wrong pin
    or corrupt source, not a transient network hiccup) — it is NEVER retried,
    it surfaces loudly at once.
    """


# WU C1 automatic-retry defaults. A transient transport drop mid-download is
# retried with exponential backoff + full jitter, reusing the ``.part`` so the
# next attempt RESUMES via a Range request instead of restarting. Definitive
# failures (HTTP status errors, sha mismatch, cancellation) are never retried.
DEFAULT_MAX_DOWNLOAD_RETRIES = 4
RETRY_BASE_SEC = 0.5
RETRY_CAP_SEC = 30.0
#: transport-level exceptions worth retrying (a dropped/half-read connection).
#: HTTP-status failures raise ``AssetError`` (definitive) and are NOT here.
DEFAULT_RETRY_ERRORS: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)


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


def download_speed_eta(
    done_bytes: float, remaining_bytes: float, elapsed_sec: float
) -> tuple[float | None, float | None]:
    """Live download speed (bytes/sec) + ETA (sec) for the progress payload (WU C1).

    ``done_bytes`` is the bytes transferred THIS session and ``elapsed_sec`` the
    time they took, so a resumed download reports the current run's speed, not an
    average diluted by the already-present ``.part``. Returns ``(None, None)``
    until there is a real sample (some bytes over some time); a zero remainder
    yields a ``0.0`` ETA (nothing left to fetch).
    """
    if elapsed_sec <= 0 or done_bytes <= 0:
        return None, None
    speed = done_bytes / elapsed_sec
    eta = remaining_bytes / speed if speed > 0 else None
    return speed, eta


def format_eta(seconds: float) -> str:
    """Human ``ETA`` string: ``45s`` / ``2m05s`` / ``1h02m`` (WU C1)."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m{total % 60:02d}s"
    return f"{total // 3600}h{(total % 3600) // 60:02d}m"


def format_bytes_progress(
    name: str,
    done_bytes: float,
    total_bytes: float,
    speed_bps: float | None,
    eta_sec: float | None,
) -> str:
    """The per-chunk progress message: ``name: 500/2500 MB · 12.5 MB/s · ETA 2m40s``.

    Speed / ETA segments are appended only when known (WU C1) — a server that
    hides Content-Length still gets a clean ``done/total MB`` line.
    """
    msg = f"{name}: {int(done_bytes) // MB}/{int(total_bytes) // MB} MB"
    if speed_bps is not None:
        msg += f" · {speed_bps / MB:.1f} MB/s"
    if eta_sec is not None:
        msg += f" · ETA {format_eta(eta_sec)}"
    return msg


def backoff_delay(attempt: int, *, base: float, cap: float, rng: Any) -> float:
    """Exponential-backoff-with-full-jitter delay for retry ``attempt`` (0-based).

    ``base * 2**attempt`` capped at ``cap``, then full-jitter randomized in
    ``[0, capped]`` via ``rng.uniform`` (WU C1) — jitter de-synchronizes retries
    so a flaky mirror isn't hammered in lockstep.
    """
    capped = min(base * (2**attempt), cap)
    return rng.uniform(0.0, capped)


def _lock_logical_lines(text: str) -> list[str]:
    """Join backslash line-continuations; drop blank + ``#`` comment lines.

    pip-compile ``--generate-hashes`` emits one requirement per logical block:
    ``pkg==ver \\`` then indented ``--hash=...`` continuation lines, then dropped
    ``# via`` comments. Reconstruct each block as a single logical line.
    """
    lines: list[str] = []
    buf = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            buf += stripped[:-1].strip() + " "
            continue
        buf += stripped
        lines.append(buf.strip())
        buf = ""
    if buf.strip():
        lines.append(buf.strip())
    return lines


def validate_hashed_lock(text: str) -> tuple[str, ...]:
    """Validate a fully-hashed lockfile body; return its pinned specs (WU C4).

    Every requirement must be PINNED (``pkg==version``) AND carry at least one
    ``--hash=`` so pip verifies its wheel's bytes before unpacking; option lines
    are limited to :data:`LOCK_ALLOWED_OPTIONS` (the still-hashed torch-index
    exception). An unhashed/unpinned requirement, an unknown option, or an empty
    lock raises :class:`AssetError` — the install fails LOUD rather than pulling
    an unverified transitive.
    """
    pins: list[str] = []
    for line in _lock_logical_lines(text):
        if line.startswith("-"):
            if not any(line.startswith(opt) for opt in LOCK_ALLOWED_OPTIONS):
                raise AssetError(f"unsupported lock option: {line!r}")
            continue
        spec = line.split()[0]
        if "==" not in spec:
            raise AssetError(f"lock requirement not pinned (use pkg==version): {spec!r}")
        if "--hash=" not in line:
            raise AssetError(f"lock requirement missing --hash= (unverified wheel): {spec!r}")
        pins.append(spec)
    if not pins:
        raise AssetError("hashed lock contains no pinned requirements")
    return tuple(pins)


def build_env_install_argvs(
    python_exe: str,
    get_pip_path: Path | str,
    env_dir: Path | str,
    requirements: Sequence[str],
    *,
    pip_pin: str = PINNED_PIP,
    lock_file: Path | str | None = None,
) -> list[dict[str, Any]]:
    """The argv steps that bootstrap a ``pip --target`` env (A7; pure function).

    Embeddable CPython has NO ensurepip/venv, so:
      1. ``python get-pip.py <pip pin> --target <env>`` — installs a PINNED pip
         *into the env dir itself* (get-pip forwards its args to pip).
      2. ``python -m pip install --target <env> ...`` with ``PYTHONPATH=<env>``
         so step 1's pip is importable. When ``lock_file`` is given (WU C4) this
         installs the fully-hashed lock with :data:`HASHED_LOCK_PIP_ARGS` —
         ``--require-hashes --only-binary=:all: --no-deps -r <lock>`` — so every
         wheel over the FULL transitive closure is hash-verified before exec; the
         inline ``requirements`` are then NOT placed on the argv (the lock is the
         sole, verified source). Without a lock, the inline pins install as before
         (top-level pins; transitives resolve unhashed).

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
    if lock_file is not None:
        install_tail = [*HASHED_LOCK_PIP_ARGS, "--no-warn-script-location", "-r", str(lock_file)]
    else:
        install_tail = ["--no-warn-script-location", *[str(r) for r in requirements]]
    step2 = {
        "argv": [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--target",
            env_dir_s,
            *install_tail,
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
    """The cache folder huggingface_hub uses for ``repo_id`` (models--org--name).

    Confined under the (env-derived) HF cache dir so a hostile ``HF_HOME`` /
    ``repo_id`` cannot escape it (and the resolved path is a sanitised sink).
    """
    return Path(ensure_within(hf_cache_dir(env_vars), "models--" + repo_id.replace("/", "--")))


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
        get_pip_sha256: str | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        rng: Any | None = None,
        max_download_retries: int = DEFAULT_MAX_DOWNLOAD_RETRIES,
        retry_base: float = RETRY_BASE_SEC,
        retry_cap: float = RETRY_CAP_SEC,
        retry_on: tuple[type[BaseException], ...] = DEFAULT_RETRY_ERRORS,
    ) -> None:
        self.root = Path(root) if root is not None else default_config_dir()
        # WU C1 seams: monotonic clock for download speed/ETA math, sleep + rng for
        # exponential-backoff-with-jitter retry. All injectable so tests are
        # deterministic and never touch the wall clock or real randomness.
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._rng = rng if rng is not None else random.SystemRandom()
        self._max_download_retries = max(0, int(max_download_retries))
        self._retry_base = float(retry_base)
        self._retry_cap = float(retry_cap)
        self._retry_on = retry_on
        # F3c: the sha256 get-pip.py must match BEFORE it's executed (verify-before
        # -exec). Injectable so tests use small fixtures; defaults to the pin above.
        self._get_pip_sha256 = get_pip_sha256 or GET_PIP_SHA256
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
        """Absolute on-disk destination for ``entry`` (relative dests confined under root).

        A relative ``dest`` is resolved + confined under the (env-derived) root
        via :func:`ensure_within`, blocking traversal out of the data root and
        making every downstream filesystem use a sanitised CodeQL sink.
        """
        if entry.installer == "hf":
            return hf_repo_dir(entry.hf_repo or "", self._env_vars)
        dest = Path(entry.dest)
        # Absolute dests are intentionally honoured as-is; a relative dest is
        # resolved + confined under root (the sanitised CodeQL sink).
        return dest if dest.is_absolute() else Path(ensure_within(self.root, entry.dest))

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

    # -- profile plan / explain surface (WU C1) ------------------------------
    def component(self, entry: AssetEntry) -> dict[str, Any]:
        """The ``assets.plan`` component view: AssetInfo + tier/label(what)/why.

        A SUPERSET of the frozen A3 ``AssetInfo`` (kept unchanged) that adds the
        WU C1 explain fields so a user sees WHAT each component is, WHY it exists,
        and its SIZE before committing to a multi-GB download.
        """
        found = self.installed_path(entry)
        return {
            "name": entry.name,
            "kind": entry.kind,
            "tier": entry.tier,
            "label": entry.label,
            "why": entry.why,
            "sizeMB": entry.size_mb,
            "installed": found is not None,
            "dest": found if found is not None else str(self.resolve_dest(entry)),
        }

    def plan(self, profile: str, custom: Sequence[str] | None = None) -> dict[str, Any]:
        """What a PROFILE would install: components + total + still-to-download size.

        ``totalMB`` is every component's size; ``toDownloadMB`` counts only the
        not-yet-installed ones (already-present components are free). An unknown
        profile / unknown custom name raises ``ValueError`` (surfaced loudly by
        the RPC layer) — never a silent empty plan.
        """
        names = manifest.resolve_profile(profile, custom)
        entries = [manifest.get_asset(name) for name in names]
        components = [self.component(entry) for entry in entries if entry is not None]
        total_mb = sum(float(c["sizeMB"]) for c in components)
        to_download_mb = sum(float(c["sizeMB"]) for c in components if not c["installed"])
        return {
            "profile": str(profile).lower(),
            "components": components,
            "totalMB": total_mb,
            "toDownloadMB": to_download_mb,
        }

    # -- ensure (the long job body) ------------------------------------------
    def ensure(self, names: Sequence[str], job_ctx: Any) -> dict[str, Any]:
        """Install every named asset that's missing; the ``assets.ensure`` job body.

        Preflights disk for ALL pending work FIRST (fail before any bytes
        move), then installs sequentially with size-weighted aggregate
        progress. Failures raise (-> job.done error payload, A6 lesson 3);
        cancellation raises :class:`JobCancelled` (partial downloads keep
        their ``.part`` for a later resume).

        CONTRACT-NOTE: A2 leaves assets.ensure's job.done.result unspecified;
        we return ``{installed:[name], failed:[{name,error}], assets:[AssetInfo]}``
        so the panel can refresh its list straight from the done payload and show
        which components were skipped (WU C1 graceful per-item failure).
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

        total_weight = sum(max(float(e.size_mb), 1.0) for e in todo) or 1.0
        done_weight = 0.0
        job_ctx.progress(0.0, "starting" if todo else "all assets already installed")

        # WU C1 graceful per-item failure: a single failing item is SKIPPED +
        # NOTED (never silently), the rest keep installing. Cancellation still
        # aborts the whole job (re-raised). If EVERY requested item is unusable
        # (nothing installed, none pre-existing) the failure surfaces as a job
        # error so the caller isn't told a bricked install "succeeded".
        failed: list[dict[str, str]] = []
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

            try:
                dest = self.resolve_dest(entry)
                target_dir = dest if entry.installer in ("hf", "env") else dest.parent
                preflight_disk(target_dir, entry.size_mb, usage=self._usage)
                self._install_with_retry(entry, on_frac=on_frac, should_cancel=lambda: job_ctx.cancelled)
            except JobCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - per-item skip: recorded + surfaced, never silent
                log.warning("asset install failed for %s: %s", clean_for_log(entry.name), exc)
                failed.append({"name": entry.name, "error": str(exc)})
            done_weight += weight

        failed_names = {f["name"] for f in failed}
        installed_names = [e.name for e in entries if e.name not in failed_names]
        if failed and not installed_names:
            # Nothing usable came out of this ensure -> a real job error (A6.3).
            raise AssetError("; ".join(f"{f['name']}: {f['error']}" for f in failed))

        job_ctx.progress(100.0, "done")
        return {"installed": installed_names, "failed": failed, "assets": self.list_assets()}

    def _install_with_retry(self, entry: AssetEntry, *, on_frac: FracCb, should_cancel: CancelProbe) -> None:
        """Install ``entry``, retrying TRANSIENT transport failures (WU C1).

        A dropped/half-read connection (``self._retry_on``) is retried with
        exponential backoff + full jitter; because the partial ``.part`` is left
        in place, each retry RESUMES via a Range request rather than restarting.
        Cancellation and integrity failures are DEFINITIVE — re-raised at once,
        never retried. After the retry budget is spent the last error propagates.
        """
        attempt = 0
        while True:
            try:
                self._install(entry, on_frac=on_frac, should_cancel=should_cancel)
                return
            except (JobCancelled, AssetIntegrityError):
                raise
            except self._retry_on as exc:
                if attempt >= self._max_download_retries:
                    raise
                delay = backoff_delay(attempt, base=self._retry_base, cap=self._retry_cap, rng=self._rng)
                log.warning(
                    "transient download failure for %s (attempt %d/%d): %s; retrying in %.2fs",
                    clean_for_log(entry.name),
                    attempt + 1,
                    self._max_download_retries,
                    exc,
                    delay,
                )
                self._sleep(delay)
                attempt += 1

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
            log.info("resuming %s from byte %d", clean_for_log(name), offset)

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
            # WU C1: measure THIS session's transfer (done - offset) against the
            # elapsed wall time for a live speed + ETA in the progress message.
            start = self._clock()
            with open(part, mode) as fh:
                for chunk in resp.iter_bytes(CHUNK_SIZE):
                    if should_cancel is not None and should_cancel():
                        # Keep the .part so the next ensure RESUMES (U4).
                        log.info("download of %s cancelled at byte %d", clean_for_log(name), done)
                        raise JobCancelled(name)
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    if on_frac and total:
                        speed, eta = download_speed_eta(done - offset, total - done, self._clock() - start)
                        on_frac(min(done / total, 0.99), format_bytes_progress(name, done, total, speed, eta))

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
                # AssetIntegrityError => the retry loop treats this as DEFINITIVE
                # (wrong pin / corrupt source), never a transient hiccup to retry.
                raise AssetIntegrityError(f"sha256 mismatch for {name}: expected {sha256}, got {actual}")
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

    def _resolve_env_lock(self, entry: AssetEntry) -> Path | None:
        """Resolve a declared fully-hashed lockfile for an env asset (WU C4).

        ``entry.lock_file`` names the hashed lock produced at F1 build-prep (like
        the ffmpeg binary, its CONTENT is staged offline — real hashes need PyPI
        + the cu128 torch index — not committed). Absolute, or relative to the
        assets root. Resolution is verify-before-exec and NEVER silent:

          * present + fully hashed -> the install runs ``--require-hashes`` from
            it (every wheel hash-checked before pip unpacks it);
          * present but NOT fully hashed -> :class:`AssetError` (fail loud);
          * DECLARED but UNSTAGED (dev box / lock not yet generated) -> a LOUD
            warning + ``None`` so the install falls back to the inline pins
            (top-level pins, unhashed transitives — the pre-C4 behaviour), rather
            than silently skipping the env;
          * not declared -> ``None`` (inline pins, unchanged).
        """
        if not entry.lock_file:
            return None
        candidate = Path(entry.lock_file)
        if not candidate.is_absolute():
            candidate = self.root / entry.lock_file
        if not candidate.is_file():
            log.warning(
                "hashed lock declared but not staged (F1 build-prep) for %s: %s — "
                "falling back to the pinned (unhashed-transitive) inline install",
                entry.name,
                candidate,
            )
            return None
        validate_hashed_lock(candidate.read_text(encoding="utf-8"))
        return candidate

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
        # F3c defense-in-depth: a cached get-pip.py under <root>/tools is EXECUTED
        # on the NEXT env install. The bootstrap only ever writes sha-verified
        # bytes, but an external tamper of that shared on-disk cache would slip an
        # unverified script past the download gate below. Re-verify the cached
        # bytes against the pinned sha256 and drop a poisoned copy so it is
        # refetched (verify-before-exec) instead of run.
        if get_pip.is_file() and hashlib.sha256(get_pip.read_bytes()).hexdigest() != self._get_pip_sha256:
            log.warning("cached get-pip.py failed sha256 re-verification; refetching")
            get_pip.unlink()
        if not get_pip.is_file():
            on_frac(0.01, f"{entry.name}: fetching get-pip.py")
            # F3c: verify-before-exec — _download_file rejects (sha mismatch) a
            # tampered get-pip.py at the .part stage, so a bad script is never run.
            self._download_file(
                GET_PIP_URL,
                get_pip,
                size_mb=GET_PIP_SIZE_MB,
                sha256=self._get_pip_sha256,
                should_cancel=should_cancel,
                label="get-pip.py",
            )
        lock_file = self._resolve_env_lock(entry)
        steps = build_env_install_argvs(python_exe, get_pip, env_dir, entry.requirements, lock_file=lock_file)
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
