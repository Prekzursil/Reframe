"""ffmpeg / ffprobe resolution, argv builders, and progress-streaming run().

Resolution order for the binaries (first hit wins):
  1. explicit ``settings={"ffmpegPath": "..."}`` (the dir or the binary itself)
  2. env override  ``MEDIA_STUDIO_FFMPEG`` / ``MEDIA_STUDIO_FFPROBE``
  3. a bundled binary next to this package (``resources/bin/``)
  4. the binary on ``PATH``  (shutil.which)

All subprocess calls use **argv lists** (never ``shell=True``) so paths with
spaces just work. ``run()`` streams progress by adding ``-progress pipe:1`` and
parsing the ``key=value`` lines ffmpeg emits, converting ``out_time_ms`` against
a known total duration into a 0-100 percentage delivered to a callback.

CONTRACTS.md sections 4/6/7: bundled ffmpeg resolved by absolute path; argv-list
subprocess only; logs to stderr. The subprocess is injected/mocked in tests.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .pathsafe import ensure_within
from .util import get_logger

log = get_logger("media_studio.ffmpeg")

# Where a bundled binary would live relative to this file (foundation phase may
# populate it). Resolution falls through to PATH if absent.
_BUNDLED_DIR = Path(__file__).resolve().parent / "resources" / "bin"

_EXE = ".exe" if os.name == "nt" else ""

# Progress callback: (pct: float 0..100, message: str) -> None
ProgressCb = Callable[[float, str], None]


class FfmpegNotFound(RuntimeError):
    """Raised when neither a bundled nor a PATH ffmpeg/ffprobe could be found."""


def resolve_binary(name: str, settings: Mapping[str, Any] | None = None) -> str:
    """Resolve an absolute path to ``name`` ("ffmpeg" or "ffprobe").

    Order: settings.ffmpegPath -> env override -> bundled -> PATH. Raises
    :class:`FfmpegNotFound` if nothing resolves.
    """
    settings = settings or {}

    # 1. explicit settings (ffmpegPath may point at the ffmpeg binary or its dir;
    #    when it names ffmpeg but we're resolving ffprobe, find the sibling).
    setting_val = settings.get("ffmpegPath") or settings.get(f"{name}Path")
    if setting_val:
        sp = Path(str(setting_val))
        if sp.is_file():
            # Use the file directly only when it IS the binary we want — its
            # stem matches `name`, or it's the generic ffmpegPath and we're
            # resolving ffmpeg itself (allows a custom-named ffmpeg binary).
            if sp.stem.lower() == name.lower() or (name == "ffmpeg" and "ffmpegPath" in settings):
                return str(sp)
            # Otherwise it names a different binary (ffmpegPath while we want
            # ffprobe) — look for <name> beside it.
            sib = sp.parent / f"{name}{_EXE}"
            if sib.is_file():
                return str(sib)
        elif sp.is_dir():
            cand = sp / f"{name}{_EXE}"
            if cand.is_file():
                return str(cand)

    # 2. env override
    env_val = os.environ.get(f"MEDIA_STUDIO_{name.upper()}")
    # ensure_within canonicalises the env-supplied binary path (the CodeQL
    # path-injection sink); the compact `and` mirrors the original branch shape.
    if env_val and Path(ensure_within(env_val)).is_file():
        return ensure_within(env_val)

    # 3. bundled
    bundled = _BUNDLED_DIR / f"{name}{_EXE}"
    if bundled.is_file():
        return str(bundled)

    # 4. PATH
    found = shutil.which(name)
    if found:
        return found

    raise FfmpegNotFound(f"{name} not found (set settings.ffmpegPath or PATH)")


def ffmpeg_path(settings: Mapping[str, Any] | None = None) -> str:
    """Absolute path to the ffmpeg binary."""
    return resolve_binary("ffmpeg", settings)


def ffprobe_path(settings: Mapping[str, Any] | None = None) -> str:
    """Absolute path to the ffprobe binary."""
    return resolve_binary("ffprobe", settings)


# ---------------------------------------------------------------------------
# argv builders (pure functions — fully unit-testable, no subprocess)
# ---------------------------------------------------------------------------
def build_probe_argv(in_path: str, settings: dict[str, Any] | None = None) -> list[str]:
    """argv for ``ffprobe`` that prints the media duration as a bare number."""
    return [
        ffprobe_path(settings),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        in_path,
    ]


def build_convert_argv(
    in_path: str,
    out_path: str,
    options: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """Build an ffmpeg argv list for a conversion described by ``options``.

    ``options`` keys (CONTRACTS.md section 2 ``convert.start``):
      container, vcodec, acodec, scale, fps, crf, audioOnly, audioFormat.

    Adds ``-progress pipe:1 -nostats`` so :func:`run` can parse progress, and
    ``-y`` to overwrite the output. Unknown/absent options are simply omitted.
    """
    options = options or {}
    argv: list[str] = [ffmpeg_path(settings), "-hide_banner", "-nostdin", "-y", "-i", in_path]

    if options.get("audioOnly"):
        argv += ["-vn"]
        acodec = options.get("acodec")
        if acodec:
            argv += ["-c:a", str(acodec)]
    else:
        vcodec = options.get("vcodec")
        if vcodec:
            argv += ["-c:v", str(vcodec)]
        acodec = options.get("acodec")
        if acodec:
            argv += ["-c:a", str(acodec)]
        crf = options.get("crf")
        if crf is not None:
            argv += ["-crf", str(crf)]

        vf: list[str] = []
        scale = options.get("scale")
        if scale:
            # accept "1280:720" or "1280x720"
            vf.append(f"scale={str(scale).replace('x', ':')}")
        if vf:
            argv += ["-vf", ",".join(vf)]

        fps = options.get("fps")
        if fps is not None:
            argv += ["-r", str(fps)]

    # progress + nostats so stdout carries only the -progress key=value stream
    argv += ["-progress", "pipe:1", "-nostats", out_path]
    return argv


# ---------------------------------------------------------------------------
# progress parsing
# ---------------------------------------------------------------------------
def parse_progress_line(line: str) -> tuple[str, str] | None:
    """Parse one ``key=value`` line from ffmpeg ``-progress`` output.

    Returns ``(key, value)`` or ``None`` for blank/garbage lines.
    """
    line = line.strip()
    if not line or "=" not in line:
        return None
    key, _, value = line.partition("=")
    return key.strip(), value.strip()


def _out_time_to_seconds(value: str) -> float | None:
    """Convert an ffmpeg ``out_time`` (HH:MM:SS.micro) string to seconds."""
    value = value.strip()
    if not value or value in ("N/A", "-"):
        return None
    try:
        parts = value.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        return float(value)
    except (ValueError, TypeError):
        return None


def _pct_from_progress(key: str, value: str, total_sec: float) -> float | None:
    """Derive a 0..100 percentage from an out_time(_ms|_us) progress field."""
    if total_sec <= 0:
        return None
    cur: float | None = None
    if key == "out_time_ms" or key == "out_time_us":
        # ffmpeg historically labels this "ms" but the value is microseconds.
        try:
            cur = int(value) / 1_000_000.0
        except (ValueError, TypeError):
            cur = None
    elif key == "out_time":
        cur = _out_time_to_seconds(value)
    if cur is None:
        return None
    pct = max(0.0, min(100.0, (cur / total_sec) * 100.0))
    return pct


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------
def run(
    argv: Sequence[str],
    total_sec: float = 0.0,
    on_progress: ProgressCb | None = None,
    should_cancel: Callable[[], bool] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
) -> int:
    """Run an ffmpeg argv list, streaming ``-progress`` lines to ``on_progress``.

    - ``argv`` MUST be a list (no ``shell=True``); spaces in paths are safe.
    - ``total_sec`` is the source duration used to turn ``out_time`` into a pct.
    - ``on_progress(pct, message)`` is called as progress advances and once more
      (100.0, "done") on a clean ``progress=end``.
    - ``should_cancel()`` is polled per line; if it returns True the process is
      terminated cooperatively and the return code is propagated.
    - ``popen`` is injectable so tests can mock the subprocess entirely.

    Returns the process exit code.
    """
    if isinstance(argv, str):  # guard: never accept a shell string
        raise TypeError("argv must be a list of strings, not a shell string")

    proc = popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # Phase-0 spine finding (the 29-min "stuck clip 1/5"): ffmpeg chats on
    # stderr continuously even with -nostats (banner, stream info, libass/font
    # logs). Capturing stderr=PIPE and never reading it fills the ~64KB pipe
    # buffer and BLOCKS the encode forever. Drain stderr on a daemon thread,
    # keeping a bounded tail for error reporting on a non-zero exit.
    stderr_tail: deque[str] = deque(maxlen=40)
    stderr = getattr(proc, "stderr", None)
    if stderr is not None and hasattr(stderr, "__iter__"):

        def _drain() -> None:
            try:
                for line in stderr:
                    seg = line.rstrip("\n").split("\r")[-1].strip()
                    if seg:
                        stderr_tail.append(seg)
            except Exception:  # noqa: BLE001 - drain must never raise
                pass

        threading.Thread(target=_drain, daemon=True, name="ffmpeg-stderr").start()

    last_pct = -1.0
    stdout = proc.stdout
    if stdout is not None:
        for raw in stdout:
            if should_cancel is not None and should_cancel():
                _terminate(proc)
                break
            parsed = parse_progress_line(raw)
            if parsed is None:
                continue
            key, value = parsed
            if key == "progress" and value == "end":
                if on_progress is not None:
                    on_progress(100.0, "done")
                continue
            if on_progress is not None:
                pct = _pct_from_progress(key, value, total_sec)
                if pct is not None and pct > last_pct:
                    last_pct = pct
                    on_progress(pct, f"{pct:.1f}%")

    code = proc.wait()
    if code != 0 and stderr_tail:
        log.error("ffmpeg exited %s; stderr tail: %s", code, " | ".join(list(stderr_tail)[-8:]))
    return code


def _terminate(proc: Any) -> None:
    """Cooperatively stop a subprocess: terminate, then kill if it lingers."""
    with contextlib.suppress(Exception):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()


def ffprobe_duration(
    in_path: str,
    settings: dict[str, Any] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> float:
    """Probe ``in_path`` for its duration in seconds via ffprobe.

    ``runner`` is injectable so tests mock the subprocess. Returns 0.0 if the
    duration cannot be determined.
    """
    argv = build_probe_argv(in_path, settings)
    completed = runner(argv, capture_output=True, text=True, check=False)
    out = (getattr(completed, "stdout", "") or "").strip()
    try:
        return float(out)
    except (ValueError, TypeError):
        return 0.0
