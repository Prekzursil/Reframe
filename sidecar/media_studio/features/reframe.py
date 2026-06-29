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
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Any

from ..util import get_logger
from . import aspect as _aspect
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
# Injectable ``shutil.which``-shaped seam for the WSL presence probe.
WhichFn = Callable[[str], str | None]


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
    ``wsl bash <script>`` can open the file. The script is read FROM A FILE — it
    is never piped through stdin (the proven mediapipe-corruption gotcha).
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
        settings: dict[str, Any] | None = None,
        runner: Runner | None = None,
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
        on_notice: Callable[[dict[str, str]], None] | None = None,
    ) -> str:
        """Reframe ``in_path`` to vertical and write ``out_path``; return it.

        Invokes verthor under WSL as ``wsl bash <script> <args>`` (script read
        FROM A FILE, never piped via ``tr|bash`` on stdin). Output is 1080x1920
        h264 for the default 9:16 aspect. Raises :class:`ReframeError` on a
        non-zero exit code.

        ``on_notice`` is accepted for stage-seam uniformity with the in-sidecar
        claudeshorts engine (so :func:`shortmaker._lazy_reframe` can thread it to
        whichever engine is resolved). verthor runs subject tracking INSIDE WSL,
        so it cannot emit a Python-side speaker-tracking-degrade notice — the
        parameter is therefore intentionally not invoked here.
        """
        _ = on_notice  # verthor degrades inside WSL; no Python-side notice to emit
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
            raise ReframeError(f"verthor reframe failed (exit {code}): {stderr or 'no stderr'}")
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

# A4: exactly these two ReframeEngine implementations.
ENGINES: dict[str, Any] = {
    ENGINE_VERTHOR: ReframeEngine,
    ENGINE_CLAUDESHORTS: ClaudeShortsReframeEngine,
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
