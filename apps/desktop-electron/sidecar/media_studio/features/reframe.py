"""ReframeEngine — the short-maker's vertical-reframe stage (CONTRACTS.md §4/A4).

P2 (ADDENDUM A4): there are now TWO implementations behind one interface —
**verthor** (this module's adapter, the default) and **claudeshorts**
(:mod:`.reframe_claudeshorts`, in-sidecar MediaPipe/OpenCV crop + one ffmpeg
pass). This module additionally owns the ENGINE REGISTRY (:data:`ENGINES`),
:func:`get_engine`, and the AUTOMATIC fallback: when WSL/verthor is unavailable
(wsl probe fails or the script is missing) ``get_engine`` returns the
claudeshorts engine together with a typed notice (surfaced in job progress).

The verthor adapter: verthor (a mediapipe-based auto-reframer) runs inside its
own **WSL2** environment, so we invoke it as a Windows-host subprocess that
shells into WSL:

    ["wsl", "bash", <script_path_in_wsl>, <in>, <out>, <aspect>, <w>, <h>]

THE GOTCHA (proven, see §4): NEVER pipe the verthor script into bash via
``tr | bash`` over **stdin**. mediapipe inside verthor reads from stdin and
corrupts a script delivered that way. The script MUST be passed as an *argv*
element (``wsl bash <script> ...``) so it is read FROM A FILE, leaving stdin free.

Everything here is pure argv construction + a thin, injectable ``runner`` seam so
the whole module is unit-testable with no WSL, no mediapipe, and no real verthor.
Output is 1080x1920 h264 (vertical 9:16) per the contract.

CONTRACTS.md §4/§6: argv-list subprocess only (never ``shell=True``); paths with
spaces stay intact because each is its own argv element; logs go to stderr.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..util import get_logger
from .reframe_claudeshorts import ClaudeShortsReframeEngine

_log = get_logger("media_studio.reframe")

# Contract: vertical 9:16 output at exactly this resolution, h264.
DEFAULT_ASPECT = "9:16"
OUT_WIDTH = 1080
OUT_HEIGHT = 1920

# CONTRACT-NOTE: §4 names "verthor" and "wsl bash <script>" but does not pin the
# script's on-disk location. We resolve it (settings -> env -> bundled default)
# the same way ffmpeg.py resolves its binary, and translate it (plus the media
# paths) to a WSL path so `wsl bash` can read the file. The bundled default is
# the package's own scripts/verthor_reframe.sh (matches build_reframe_argv's
# argv contract; Phase-0 fix — the old /opt/verthor placeholder existed nowhere).
# Override via settings.verthorScript / env.


def _bundled_script_default() -> str:
    """WSL path of the packaged verthor_reframe.sh (lazy; pure string math)."""
    here = Path(__file__).resolve().parent.parent  # media_studio/
    return to_wsl_path(str(here / "scripts" / "verthor_reframe.sh"))


_DEFAULT_VERTHOR_SCRIPT = "__BUNDLED__"  # sentinel resolved in resolve_script()

# Injectable subprocess seam (mocked in tests).
Runner = Callable[..., Any]


class ReframeError(RuntimeError):
    """Raised when the verthor reframe subprocess fails."""


# --------------------------------------------------------------------------- #
# aspect handling
# --------------------------------------------------------------------------- #
def _parse_aspect(aspect: str) -> Tuple[int, int]:
    """Parse a ``"W:H"`` aspect string into an ``(w, h)`` int tuple.

    Accepts ``9:16`` (or ``9x16``). Raises ``ValueError`` for anything that is
    not two positive integers. Only the ratio is used; the contract pins the
    actual output to 1080x1920 for the canonical 9:16 case.
    """
    raw = str(aspect).strip().replace("x", ":")
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"aspect must be 'W:H', got {aspect!r}")
    try:
        w, h = int(parts[0]), int(parts[1])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"aspect must be two integers, got {aspect!r}") from exc
    if w <= 0 or h <= 0:
        raise ValueError(f"aspect components must be positive, got {aspect!r}")
    return w, h


def output_dimensions(aspect: str = DEFAULT_ASPECT) -> Tuple[int, int]:
    """Return the (width, height) the reframe should produce for ``aspect``.

    For the canonical 9:16 the contract fixes 1080x1920. For any other ratio we
    scale the longer side to 1920 and derive the other from the ratio (kept even
    so h264 is happy).
    """
    w, h = _parse_aspect(aspect)
    if (w, h) == (9, 16):
        return OUT_WIDTH, OUT_HEIGHT
    # Portrait-or-square: fix height to 1920 and derive width from the ratio.
    # Landscape: fix width to 1920 instead. Always round to an even number.
    if h >= w:
        height = OUT_HEIGHT
        width = int(round(OUT_HEIGHT * (w / h)))
    else:
        width = OUT_HEIGHT
        height = int(round(OUT_HEIGHT * (h / w)))
    return _even(width), _even(height)


def _even(n: int) -> int:
    """Round a dimension to the nearest even value (h264 requires even sizes)."""
    return n if n % 2 == 0 else n + 1


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
    # No drive letter — treat as a relative posix path.
    return PurePath(s).as_posix()


# --------------------------------------------------------------------------- #
# script resolution
# --------------------------------------------------------------------------- #
def resolve_script(settings: Optional[Dict[str, Any]] = None) -> str:
    """Resolve the verthor reframe script path AS A WSL PATH.

    Order: ``settings.verthorScript`` -> env ``MEDIA_STUDIO_VERTHOR_SCRIPT`` ->
    the bundled default. The result is always translated to a WSL path so
    ``wsl bash <script>`` can open the file. The script is read FROM A FILE — it
    is never piped through stdin (the proven mediapipe-corruption gotcha).
    """
    settings = settings or {}
    raw = (
        settings.get("verthorScript")
        or os.environ.get("MEDIA_STUDIO_VERTHOR_SCRIPT")
        or _DEFAULT_VERTHOR_SCRIPT
    )
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
    settings: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Build the ``wsl bash <script> ...`` argv for a verthor reframe.

    Shape (§4): ``["wsl", "bash", <script>, <in>, <out>, <aspect>, <w>, <h>]``.

    - The script is the THIRD argv element (``bash``'s positional file argument),
      i.e. read FROM A FILE. There is no ``-c``, no ``tr``, no ``|``, and nothing
      goes to bash's stdin — that is the whole point of the contract gotcha.
    - Media paths are translated to ``/mnt/...`` WSL paths and kept as single
      argv elements, so paths with spaces survive (no ``shell=True``).
    - Width/height are passed so the script targets 1080x1920 (h264) for 9:16.
    """
    width, height = output_dimensions(aspect)
    script = resolve_script(settings)
    return [
        "wsl",
        "bash",
        script,
        to_wsl_path(in_path),
        to_wsl_path(out_path),
        aspect,
        str(width),
        str(height),
    ]


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #
class ReframeEngine:
    """Vertical auto-reframe via the verthor (WSL2) adapter — the sole impl.

    ``settings`` may carry ``verthorScript`` (override the script path). ``runner``
    is the injectable subprocess seam: it receives the argv LIST and must NOT use
    ``shell=True``. Tests pass a fake runner and assert the call shape; production
    uses ``subprocess.run``.
    """

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        runner: Optional[Runner] = None,
    ) -> None:
        self._settings = settings or {}
        # Resolve the default at call time (not def time) so a test that
        # monkeypatches ``reframe.subprocess.run`` is honoured and no real wsl
        # is ever spawned by default.
        self._runner = runner if runner is not None else subprocess.run

    def reframe(
        self,
        in_path: str,
        out_path: str,
        aspect: str = DEFAULT_ASPECT,
    ) -> str:
        """Reframe ``in_path`` to vertical and write ``out_path``; return it.

        Invokes verthor under WSL as ``wsl bash <script> <args>`` (script read
        FROM A FILE, never piped via ``tr|bash`` on stdin). Output is 1080x1920
        h264 for the default 9:16 aspect. Raises :class:`ReframeError` on a
        non-zero exit code.
        """
        argv = build_reframe_argv(in_path, out_path, aspect, self._settings)
        if not isinstance(argv, list):  # defensive: never a shell string
            raise TypeError("reframe argv must be a list of strings")

        _log.info("reframe: running verthor adapter (aspect=%s)", aspect)
        completed = self._runner(
            argv,
            capture_output=True,
            text=True,
            check=False,
        )
        code = getattr(completed, "returncode", 0)
        if code != 0:
            stderr = (getattr(completed, "stderr", "") or "").strip()
            raise ReframeError(
                f"verthor reframe failed (exit {code}): {stderr or 'no stderr'}"
            )
        return out_path


# --------------------------------------------------------------------------- #
# P2 / A4: engine registry + automatic fallback (T4b)
# --------------------------------------------------------------------------- #
# Engine names are part of the UI contract (ShortMaker's auto/verthor/
# claudeshorts override). "auto" is a SELECTOR, not an engine — it resolves to
# verthor when available, else claudeshorts (with a typed fallback notice).
ENGINE_AUTO = "auto"
ENGINE_VERTHOR = "verthor"
ENGINE_CLAUDESHORTS = "claudeshorts"

# A4: exactly these two ReframeEngine implementations.
ENGINES: Dict[str, Any] = {
    ENGINE_VERTHOR: ReframeEngine,
    ENGINE_CLAUDESHORTS: ClaudeShortsReframeEngine,
}

# The typed notice's discriminator (consumers match on `notice["type"]`).
REFRAME_FALLBACK_NOTICE = "reframe.fallback"


def make_fallback_notice(requested: str, reason: str) -> Dict[str, str]:
    """Build the typed notice emitted when verthor falls back to claudeshorts.

    Shape: ``{type, requested, engine, reason, message}`` — ``message`` is the
    human line the shortmaker job surfaces via ``job.progress``.
    """
    return {
        "type": REFRAME_FALLBACK_NOTICE,
        "requested": requested,
        "engine": ENGINE_CLAUDESHORTS,
        "reason": reason,
        "message": (
            f"reframe: verthor (WSL) unavailable — {reason}; "
            f"falling back to the claudeshorts engine"
        ),
    }


def wsl_available(probe_runner: Runner = subprocess.run) -> bool:
    """Probe whether WSL is usable on this host (``wsl --status``).

    Argv list, output captured as BYTES (wsl emits UTF-16; we only need the
    exit code) so both pipes are drained (A6 lesson 2). Any spawn failure —
    wsl.exe missing, timeout, crash — means "not available".
    """
    try:
        completed = probe_runner(
            ["wsl", "--status"],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except Exception:  # noqa: BLE001 - any probe failure == unavailable
        return False
    return getattr(completed, "returncode", 1) == 0


def _script_host_path(settings: Optional[Dict[str, Any]] = None) -> str:
    """The verthor script's HOST-side path (pre-WSL-translation).

    Mirrors :func:`resolve_script`'s order (settings -> env -> bundled) but
    keeps the Windows path so existence can be checked from the host.
    """
    settings = settings or {}
    raw = (
        settings.get("verthorScript")
        or os.environ.get("MEDIA_STUDIO_VERTHOR_SCRIPT")
        or _DEFAULT_VERTHOR_SCRIPT
    )
    if raw == "__BUNDLED__":
        here = Path(__file__).resolve().parent.parent  # media_studio/
        return str(here / "scripts" / "verthor_reframe.sh")
    return str(raw)


def script_present(settings: Optional[Dict[str, Any]] = None) -> bool:
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
    settings: Optional[Dict[str, Any]] = None,
    probe_runner: Runner = subprocess.run,
) -> Optional[str]:
    """``None`` when verthor is usable, else a human reason (script/WSL)."""
    settings = settings or {}
    if not script_present(settings):
        return f"verthor script not found at {_script_host_path(settings)}"
    if not wsl_available(probe_runner):
        return "WSL probe failed (wsl --status)"
    return None


def resolve_engine_name(
    name: Optional[str],
    settings: Optional[Dict[str, Any]] = None,
    probe_runner: Runner = subprocess.run,
) -> Tuple[str, Optional[Dict[str, str]]]:
    """Resolve a requested engine name to ``(concrete_name, notice|None)``.

    - ``"claudeshorts"``: returned as-is, no probing, no notice.
    - ``"auto"`` / ``"verthor"`` (and ``None``/blank -> auto): verthor when the
      WSL probe + script check pass; otherwise **automatic fallback** to
      claudeshorts with a typed :func:`make_fallback_notice`.
    - anything else: ``ValueError`` (unknown engines fail loudly, A6 #3).
    """
    requested = str(name or ENGINE_AUTO).strip().lower() or ENGINE_AUTO
    if requested == ENGINE_CLAUDESHORTS:
        return ENGINE_CLAUDESHORTS, None
    if requested not in (ENGINE_AUTO, ENGINE_VERTHOR):
        raise ValueError(f"unknown reframe engine: {name!r}")
    reason = verthor_unavailable_reason(settings, probe_runner=probe_runner)
    if reason is None:
        return ENGINE_VERTHOR, None
    _log.warning("reframe fallback (%s requested): %s", requested, reason)
    return ENGINE_CLAUDESHORTS, make_fallback_notice(requested, reason)


def get_engine(
    name: Optional[str],
    settings: Optional[Dict[str, Any]] = None,
    probe_runner: Runner = subprocess.run,
) -> Tuple[Any, Optional[Dict[str, str]]]:
    """Build the reframe engine for ``name`` -> ``(engine, notice|None)``.

    The engine is a fresh instance of the resolved :data:`ENGINES` class,
    constructed with ``settings``. ``notice`` is non-None only when an
    automatic verthor->claudeshorts fallback happened; callers running inside a
    job should surface ``notice["message"]`` via ``job.progress``.
    """
    settings = settings or {}
    resolved, notice = resolve_engine_name(name, settings, probe_runner=probe_runner)
    return ENGINES[resolved](settings), notice
