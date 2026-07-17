"""ReframeEngine — the short-maker's vertical-reframe stage (CONTRACTS.md §4/A4).

P2 (ADDENDUM A4): there are now TWO implementations behind one interface —
**verthor** (this module's adapter, the default) and **claudeshorts**
(:mod:`.reframe_claudeshorts`, in-sidecar MediaPipe/OpenCV crop + one ffmpeg
pass). This module additionally owns the ENGINE REGISTRY (:data:`ENGINES`),
:func:`get_engine`, and the AUTOMATIC fallback: when **auto** is selected and
WSL/verthor is unavailable (``wsl.exe`` not on PATH, probed via
``shutil.which`` — never a subprocess — or the script is missing) ``get_engine``
returns the claudeshorts engine together with a typed notice (surfaced in job
progress). An EXPLICIT ``verthor`` request, by contrast, raises
:class:`ReframeError` when WSL is absent — explicit engine choices fail loudly
rather than being silently substituted.

The verthor adapter: verthor (a mediapipe-based auto-reframer) runs inside its
own **WSL2** environment, so we invoke it as a Windows-host subprocess that
enters WSL:

    ["wsl", "--exec", "bash", <script_path_in_wsl>, <in>, <out>, <aspect>, <w>, <h>]

``--exec`` is load-bearing: without it, ``wsl.exe`` space-joins the argument
tail and runs it through the WSL DEFAULT SHELL (``$SHELL -c``), so shell
metacharacters in the translated media paths would be interpreted inside WSL
and paths with spaces would word-split (CodeQL #1752,
``py/command-line-injection``). With ``--exec`` the command is exec'd with this
verbatim argv — no inner shell ever re-parses the arguments.

THE GOTCHA (proven, see §4): NEVER pipe the verthor script into bash via
``tr | bash`` over **stdin**. mediapipe inside verthor reads from stdin and
corrupts a script delivered that way. The script MUST be passed as an *argv*
element (``wsl --exec bash <script> ...``) so it is read FROM A FILE, leaving
stdin free.

Everything here is pure argv construction + a thin, injectable ``runner`` seam so
the whole module is unit-testable with no WSL, no mediapipe, and no real verthor.
Output is 1080x1920 h264 (vertical 9:16) per the contract.

CONTRACTS.md §4/§6: argv-list subprocess only (never ``shell=True``, never an
inner WSL shell — ``--exec``); paths with spaces stay intact because each is its
own argv element and nothing re-joins them; logs go to stderr.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Any

from ..util import get_logger
from . import aspect as _aspect
from .reframe_claudeshorts import ClaudeShortsReframeEngine
from .reframe_multispeaker import MultiSpeakerReframeEngine

_log = get_logger("media_studio.reframe")

# Contract: vertical 9:16 output at exactly this resolution, h264.
DEFAULT_ASPECT = "9:16"
OUT_WIDTH = 1080
OUT_HEIGHT = 1920

# CONTRACT-NOTE: §4 names "verthor" and "wsl --exec bash <script>" but does not
# pin the script's on-disk location. We resolve it (settings -> env -> bundled
# default) the same way ffmpeg.py resolves its binary, and translate it (plus the
# media paths) to a WSL path so `wsl --exec bash` can read the file. The bundled default is
# the package's own scripts/verthor_reframe.sh (matches build_reframe_argv's
# argv contract; Phase-0 fix — the old /opt/verthor placeholder existed nowhere).
# Override via settings.verthorScript / env.


def _bundled_script_default() -> str:
    """WSL path of the packaged verthor_reframe.sh (lazy; pure string math)."""
    here = Path(__file__).resolve().parent.parent  # media_studio/
    return to_wsl_path(str(here / "scripts" / "verthor_reframe.sh"))


_DEFAULT_VERTHOR_SCRIPT = "__BUNDLED__"  # sentinel resolved in resolve_script()

# Injectable ``subprocess.Popen``-shaped seam (mocked in tests): it receives the
# argv LIST (never a shell string) and returns a Popen-like process. Popen (not
# the old blocking ``subprocess.run``) is what makes cooperative cancellation
# possible — mirrors ``ffmpeg.run`` / ``caption_remotion``'s popen seam.
PopenFn = Callable[..., Any]
# A cooperative cancel probe: returns True once cancellation is requested. Mirrors
# the sibling engines' + ``transcribe``'s ``should_cancel`` seam (wired from the
# job as ``lambda: job_ctx.cancelled``).
CancelProbe = Callable[[], bool]
# A progress sink: (pct 0..100, message) -> None. Accepted for stage-seam
# uniformity with the sibling engines; verthor streams no Python-side progress.
ProgressCb = Callable[[float, str], None]
# Injectable ``shutil.which``-shaped seam for the WSL presence probe.
WhichFn = Callable[[str], str | None]

# How often the reframe subprocess is polled for cooperative cancellation while
# verthor runs (seconds). ``proc.communicate(timeout=...)`` drains stdout+stderr
# each poll so a chatty verthor can never fill the OS pipe buffer and deadlock.
_CANCEL_POLL_SEC = 0.25
# Grace period after ``terminate()`` before escalating to a hard ``kill()``.
_TERMINATE_TIMEOUT_SEC = 5.0


class ReframeError(RuntimeError):
    """Raised when the verthor reframe subprocess fails."""


# --------------------------------------------------------------------------- #
# aspect handling
# --------------------------------------------------------------------------- #
def _parse_aspect(aspect: str) -> tuple[int, int]:
    """Parse a ``"W:H"`` aspect string into an ``(w, h)`` int tuple.

    Thin alias over the shared :func:`media_studio.features.aspect.parse_aspect`
    registry (kept for the engine's local/public name and existing call sites).
    """
    return _aspect.parse_aspect(aspect)


def output_dimensions(aspect: str = DEFAULT_ASPECT) -> tuple[int, int]:
    """Return the (width, height) the reframe should produce for ``aspect``.

    Delegates to the shared aspect registry (WU R3): the three curated social
    aspects resolve to their 1080-wide dimensions (9:16 -> 1080x1920,
    1:1 -> 1080x1080, 4:5 -> 1080x1350); any other positive ratio falls back to
    the original "fit the long edge to 1920, even" math.
    """
    return _aspect.output_dimensions(aspect)


# --------------------------------------------------------------------------- #
# path translation (Windows host -> WSL)
# --------------------------------------------------------------------------- #
def to_wsl_path(path: str) -> str:
    """Translate a Windows path to its ``/mnt/<drive>/...`` WSL equivalent.

    ``C:\\Users\\me\\v.mp4`` -> ``/mnt/c/Users/me/v.mp4``. A path that already
    looks POSIX (starts with ``/``) is returned unchanged, and a relative path is
    just slash-normalized. Spaces are preserved verbatim — quoting is the argv
    layer's job, not ours.
    """
    s = str(path)
    if not s:
        return s
    # Already a POSIX/WSL path.
    if s.startswith("/"):
        return s
    win = PureWindowsPath(s)
    drive = win.drive  # e.g. "C:"
    if drive and len(drive) >= 2 and drive[1] == ":":
        letter = drive[0].lower()
        # Parts after the drive+root; join with forward slashes.
        rel = win.parts[1:] if win.is_absolute() else win.parts
        rel_str = "/".join(rel)
        return f"/mnt/{letter}/{rel_str}" if rel_str else f"/mnt/{letter}"
    # No drive letter — treat as a relative path, normalizing Windows-style
    # separators to POSIX on ANY host (PurePath on a POSIX host keeps "\" verbatim).
    return PureWindowsPath(s).as_posix()


# --------------------------------------------------------------------------- #
# script resolution
# --------------------------------------------------------------------------- #
def resolve_script(settings: dict[str, Any] | None = None) -> str:
    """Resolve the verthor reframe script path AS A WSL PATH.

    Order: ``settings.verthorScript`` -> env ``MEDIA_STUDIO_VERTHOR_SCRIPT`` ->
    the bundled default. The result is always translated to a WSL path so
    ``wsl --exec bash <script>`` can open the file. The script is read FROM A
    FILE — it is never piped through stdin (the proven mediapipe-corruption
    gotcha).
    """
    settings = settings or {}
    raw = settings.get("verthorScript") or os.environ.get("MEDIA_STUDIO_VERTHOR_SCRIPT") or _DEFAULT_VERTHOR_SCRIPT
    if raw == "__BUNDLED__":
        return _bundled_script_default()
    return to_wsl_path(str(raw))


# --------------------------------------------------------------------------- #
# argv builder (pure function — fully unit-testable, no subprocess)
# --------------------------------------------------------------------------- #
def build_reframe_argv(
    in_path: str,
    out_path: str,
    aspect: str = DEFAULT_ASPECT,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """Build the ``wsl --exec bash <script> ...`` argv for a verthor reframe.

    Shape (§4): ``["wsl", "--exec", "bash", <script>, <in>, <out>, <aspect>, <w>, <h>]``.

    - ``--exec`` makes ``wsl.exe`` exec the command with this VERBATIM argv.
      Without it, wsl space-joins the tail and runs it through the WSL default
      shell (``$SHELL -c``) — metacharacters in the translated media paths would
      be shell-interpreted inside WSL and spaces would word-split (CodeQL #1752,
      ``py/command-line-injection``).
    - The script is ``bash``'s positional file argument, i.e. read FROM A FILE.
      There is no ``-c``, no ``tr``, no ``|``, and nothing goes to bash's stdin —
      that is the whole point of the contract gotcha.
    - Media paths are translated to ``/mnt/...`` WSL paths and kept as single
      argv elements, so paths with spaces survive (no ``shell=True``, no inner
      shell).
    - Width/height are passed so the script targets 1080x1920 (h264) for 9:16.
    """
    width, height = output_dimensions(aspect)
    script = resolve_script(settings)
    return [
        "wsl",
        "--exec",
        "bash",
        script,
        to_wsl_path(in_path),
        to_wsl_path(out_path),
        aspect,
        str(width),
        str(height),
    ]


# --------------------------------------------------------------------------- #
# cooperative-cancel subprocess helpers (mirror ffmpeg.run / ffmpeg._terminate)
# --------------------------------------------------------------------------- #
def _terminate(proc: Any) -> None:
    """Cooperatively stop a subprocess: terminate, then kill if it lingers.

    Mirrors :func:`media_studio.ffmpeg._terminate` — the escalation the sibling
    cancellable stages already rely on. Every step is defensive so tearing down an
    already-dead child never raises.
    """
    with contextlib.suppress(Exception):
        proc.terminate()
    try:
        proc.wait(timeout=_TERMINATE_TIMEOUT_SEC)
    except Exception:  # noqa: BLE001 - a lingering/ignoring child -> hard kill
        with contextlib.suppress(Exception):
            proc.kill()


def _drain_stderr(proc: Any) -> str:
    """Best-effort collect a (terminated) child's stderr; never raises.

    Used on the cancel path after :func:`_terminate` so the ``ReframeError`` still
    carries whatever verthor managed to log before it was killed.
    """
    try:
        _stdout, stderr = proc.communicate(timeout=_TERMINATE_TIMEOUT_SEC)
        return stderr or ""
    except Exception:  # noqa: BLE001 - draining a dead child must never raise
        return ""


def _await_verthor(proc: Any, should_cancel: CancelProbe | None) -> str:
    """Drive the verthor subprocess to completion, polling ``should_cancel``.

    ``proc.communicate(timeout=...)`` drains stdout+stderr continuously so a chatty
    verthor can never fill the OS pipe buffer and BLOCK (the exact hazard
    :func:`ffmpeg.run` guards against), while ``should_cancel`` is checked between
    polls. On cancel the child is terminated at once (verthor's GPU work stops
    instead of burning until the 30-min watchdog); the terminated child's non-zero
    exit is surfaced as a :class:`ReframeError` by the caller — matching the
    sibling engines' cancel-as-failure contract. Returns the process stderr.
    """
    while True:
        if should_cancel is not None and should_cancel():
            _terminate(proc)
            return _drain_stderr(proc)
        try:
            _stdout, stderr = proc.communicate(timeout=_CANCEL_POLL_SEC)
        except subprocess.TimeoutExpired:
            continue
        return stderr or ""


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #
class ReframeEngine:
    """Vertical auto-reframe via the verthor (WSL2) adapter — the sole impl.

    ``settings`` may carry ``verthorScript`` (override the script path). ``popen``
    is the injectable subprocess seam: it receives the argv LIST and must NOT use
    ``shell=True``. Tests pass a fake Popen and assert the call shape; production
    uses ``subprocess.Popen`` so the run is cancellable (was a blocking
    ``subprocess.run`` — a NO-OP for cancel that burned GPU to the watchdog).
    """

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        popen: PopenFn | None = None,
    ) -> None:
        self._settings = settings or {}
        # Resolve the default at call time (not def time) so a test that
        # monkeypatches ``reframe.subprocess.Popen`` is honoured and no real wsl
        # is ever spawned by default.
        self._popen = popen if popen is not None else subprocess.Popen

    def reframe(
        self,
        in_path: str,
        out_path: str,
        aspect: str = DEFAULT_ASPECT,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
        on_notice: Callable[[dict[str, str]], None] | None = None,
    ) -> str:
        """Reframe ``in_path`` to vertical and write ``out_path``; return it.

        Invokes verthor under WSL as ``wsl --exec bash <script> <args>``
        (``--exec`` = no WSL default shell, args reach bash verbatim; script read
        FROM A FILE, never piped via ``tr|bash`` on stdin). Output is 1080x1920
        h264 for the default 9:16 aspect. Raises :class:`ReframeError` on a
        non-zero exit code.

        ``should_cancel`` (wired from the job as ``lambda: job_ctx.cancelled``) is
        polled while verthor runs; when it fires the child is terminated so the
        reframe stops promptly instead of burning GPU to the 30-min watchdog. This
        matches how the sibling engines (claudeshorts / multi-speaker) and
        ``ffmpeg.run`` already cancel.

        ``on_progress`` / ``on_notice`` are accepted for stage-seam uniformity with
        the in-sidecar engines (so :func:`shortmaker._lazy_reframe` can thread them
        to whichever engine is resolved). verthor runs subject tracking INSIDE WSL,
        so it emits no Python-side progress or speaker-tracking-degrade notice —
        those parameters are intentionally not invoked here.
        """
        _ = on_notice  # verthor degrades inside WSL; no Python-side notice to emit
        _ = on_progress  # verthor streams no Python-side progress (runs in WSL)
        argv = build_reframe_argv(in_path, out_path, aspect, self._settings)
        if not isinstance(argv, list):  # defensive: never a shell string
            raise TypeError("reframe argv must be a list of strings")

        _log.info("reframe: running verthor adapter (aspect=%s)", aspect)
        proc = self._popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stderr = _await_verthor(proc, should_cancel)
        code = proc.returncode
        if code:
            detail = (stderr or "").strip() or "no stderr"
            raise ReframeError(f"verthor reframe failed (exit {code}): {detail}")
        return out_path


# --------------------------------------------------------------------------- #
# P2 / A4 + P3: engine registry + default (claudeshorts, no-WSL)
# --------------------------------------------------------------------------- #
# Engine names are part of the UI contract (ShortMaker's auto/verthor/
# claudeshorts override). "auto" is a SELECTOR, not an engine — P3 makes it
# resolve to the in-sidecar **claudeshorts** engine so the pipeline needs NO WSL
# by default; **verthor** (WSL2) is now an EXPLICIT opt-in only.
ENGINE_AUTO = "auto"
ENGINE_VERTHOR = "verthor"
ENGINE_CLAUDESHORTS = "claudeshorts"
# R1 (V1.1): the flagship hybrid multi-speaker director (EXPLICIT opt-in only —
# "auto" stays claudeshorts so the P3 no-WSL default contract is untouched).
ENGINE_MULTISPEAKER = "reframe_multispeaker"

# A4 + R1: the ReframeEngine implementations.
ENGINES: dict[str, Any] = {
    ENGINE_VERTHOR: ReframeEngine,
    ENGINE_CLAUDESHORTS: ClaudeShortsReframeEngine,
    ENGINE_MULTISPEAKER: MultiSpeakerReframeEngine,
}


def wsl_available(*, which: WhichFn = shutil.which) -> bool:
    """Probe whether WSL is present on this host — a pure PATH lookup.

    Uses ``shutil.which("wsl")`` (NOT ``wsl --status``): a presence probe must
    never spawn a subprocess, because a half-installed WSL can make
    ``wsl --status`` hang and that would block the job thread. ``which`` is the
    injectable seam (tests pass a fake that returns a path / ``None``). On a
    Windows box with no WSL feature installed, ``wsl.exe`` is absent from PATH
    and this returns ``False`` — the auto-engine fallback's gate.
    """
    return which("wsl") is not None


def _script_host_path(settings: dict[str, Any] | None = None) -> str:
    """The verthor script's HOST-side path (pre-WSL-translation).

    Mirrors :func:`resolve_script`'s order (settings -> env -> bundled) but
    keeps the Windows path so existence can be checked from the host.
    """
    settings = settings or {}
    raw = settings.get("verthorScript") or os.environ.get("MEDIA_STUDIO_VERTHOR_SCRIPT") or _DEFAULT_VERTHOR_SCRIPT
    if raw == "__BUNDLED__":
        here = Path(__file__).resolve().parent.parent  # media_studio/
        return str(here / "scripts" / "verthor_reframe.sh")
    return str(raw)


def script_present(settings: dict[str, Any] | None = None) -> bool:
    """True when the configured verthor script exists (host-checkable paths).

    A POSIX-style path (lives inside WSL) cannot be stat'ed from Windows, so it
    counts as present here — the :func:`wsl_available` probe is the gate for
    that case.
    """
    host = _script_host_path(settings)
    if host.startswith("/"):
        return True
    return Path(host).is_file()


def verthor_unavailable_reason(
    settings: dict[str, Any] | None = None,
    *,
    which: WhichFn = shutil.which,
) -> str | None:
    """``None`` when verthor is usable, else a human reason (script/WSL).

    WSL presence is the pure-PATH :func:`wsl_available` probe (no subprocess).
    """
    settings = settings or {}
    if not script_present(settings):
        return f"verthor script not found at {_script_host_path(settings)}"
    if not wsl_available(which=which):
        return "WSL not found on PATH (wsl.exe missing — WSL not installed?)"
    return None


def resolve_engine_name(
    name: str | None,
    settings: dict[str, Any] | None = None,
    *,
    which: WhichFn = shutil.which,
) -> tuple[str, dict[str, str] | None]:
    """Resolve a requested engine name to ``(concrete_name, notice|None)``.

    P3 DEFAULT FLIP: the in-sidecar **claudeshorts** engine is now the default,
    so the pipeline needs NO WSL out of the box. ``verthor`` (WSL2) is an
    EXPLICIT opt-in only.

    - ``"auto"`` (and ``None``/blank -> auto): **claudeshorts**, no WSL probe,
      no notice — the no-WSL default.
    - ``"claudeshorts"``: returned as-is, no probing, no notice.
    - ``"verthor"`` (EXPLICIT): verthor when available, else **raise**
      :class:`ReframeError`. An explicit engine request must NOT be silently
      substituted — choosing the WSL engine on a host without WSL fails loudly.
    - anything else: ``ValueError`` (unknown engines fail loudly, A6 #3).
    """
    requested = str(name or ENGINE_AUTO).strip().lower() or ENGINE_AUTO
    if requested in (ENGINE_AUTO, ENGINE_CLAUDESHORTS):
        # auto + claudeshorts both resolve to the no-WSL default engine.
        return ENGINE_CLAUDESHORTS, None
    if requested == ENGINE_MULTISPEAKER:
        # R1 EXPLICIT opt-in: resolve to itself with no probe here — the engine's
        # own reframe() applies the availability contract (raises a typed
        # MultiSpeakerUnavailableError / OfflineError when the host can't run it).
        return ENGINE_MULTISPEAKER, None
    if requested != ENGINE_VERTHOR:
        raise ValueError(f"unknown reframe engine: {name!r}")
    reason = verthor_unavailable_reason(settings, which=which)
    if reason is not None:
        # Explicit verthor: fail loudly, never silently fall back.
        raise ReframeError(f"verthor reframe engine requested but unavailable: {reason}")
    return ENGINE_VERTHOR, None


def get_engine(
    name: str | None,
    settings: dict[str, Any] | None = None,
    *,
    which: WhichFn = shutil.which,
) -> tuple[Any, dict[str, str] | None]:
    """Build the reframe engine for ``name`` -> ``(engine, notice|None)``.

    The engine is a fresh instance of the resolved :data:`ENGINES` class,
    constructed with ``settings``. ``notice`` is always ``None`` since P3 (the
    default ``auto`` resolves straight to claudeshorts with no WSL probe and so
    no fallback notice); the tuple shape is kept for callers. An explicit
    ``verthor`` request with WSL absent raises :class:`ReframeError`.
    """
    settings = settings or {}
    resolved, notice = resolve_engine_name(name, settings, which=which)
    return ENGINES[resolved](settings), notice
