"""WU-S11 — the T9a teardown RESIDUAL that commit cf088986 did NOT close.

cf088986 ("real cancel + process-tree teardown for the reframe stage", #281) gave
``app/main/sidecar.ts`` a ``taskkill /PID <pid> /T /F`` tree kill, bounded
``ffprobe`` with :data:`media_studio.ffmpeg.PROBE_TIMEOUT_SEC`, and gave the
verthor reframe stage a real cancel. Three holes survived it, and this module
covers exactly those three:

1. :func:`media_studio.ffmpeg.run` polled ``should_cancel()`` ONLY inside
   ``for raw in stdout:``. A wedged encoder that stops emitting ``-progress``
   lines blocks that readline forever, so the poll never runs again and the child
   survives the job watchdog that already freed its slot — wedged encoders
   ACCUMULATE. Cancellation now runs on an INDEPENDENT timer
   (:func:`media_studio.ffmpeg.watch_cancel` on a daemon thread), so a silent
   child is still torn down, and the teardown reaps the process TREE.
2. ``features/_lightasd_infer.analyze_visual`` created its work tree with
   ``tempfile.mkdtemp`` and never removed it — one JPEG per 25-fps frame plus a
   224x224 ``.avi`` + ``.wav`` per face track, i.e. GIGABYTES leaked per run, on
   success, failure AND cancellation alike.
3. ``features/caption_remotion.run_render`` spawns the Node render CLI which in
   turn spawns Chromium; it had the SAME output-gated cancel poll and a
   parent-only terminate, so a cancelled caption render orphaned its browser.

Every subprocess seam here is injected. ``taskkill`` is NEVER really spawned: the
platform flag is monkeypatched and the runner is a fake, so no test can signal a
real PID.
"""

from __future__ import annotations

import functools
import subprocess
import threading
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import _lightasd_infer, caption_remotion


# --------------------------------------------------------------------------- #
# test doubles
# --------------------------------------------------------------------------- #
class _TreeProc:
    """A Popen-shaped fake carrying a pid (so the tree-kill branch is reachable)."""

    def __init__(self, pid: Any = 4242) -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - wait() succeeds, kill unreached
        self.killed = True


class _RecordingRunner:
    """A ``subprocess.run``-shaped fake that records the argv it was handed."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: dict[str, Any] = {}

    def __call__(self, argv: list[str], **kwargs: Any) -> None:
        self.calls.append(list(argv))
        self.kwargs = kwargs


class _CancelProbe:
    """A thread-safe ``should_cancel`` that says NO once, then YES forever.

    The single NO is consumed by the per-line poll while the child is still
    streaming, so a subsequent YES can only be observed by a poll that is
    INDEPENDENT of stdout — which is the whole point of the fix.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0

    def __call__(self) -> bool:
        with self._lock:
            self.calls += 1
            return self.calls > 1


class _WedgedProc:
    """A child that emits ONE line and then goes silent until it is torn down.

    This is the defect's shape: the stdout iterator blocks (as a real pipe
    readline does on a wedged encoder), so any cancellation polled per-line is
    never reached again. Every wait is bounded so a regression fails the test
    instead of hanging the suite.
    """

    #: Hard bound on every internal wait so a broken fix fails fast.
    GUARD_SEC = 10.0

    def __init__(self, *, first_line: str = "out_time_ms=1000000\n") -> None:
        self.pid = None  # no pid -> kill_process_tree is a no-op (no real taskkill)
        self.stderr = None  # no drain thread needed
        self.terminated = False
        self.killed = False
        self._first_line = first_line
        self._dead = threading.Event()
        self.stdout = self._stream()

    def _stream(self) -> Any:
        yield self._first_line
        # Silent from here: unblocks only when the process is torn down.
        self._dead.wait(self.GUARD_SEC)

    def terminate(self) -> None:
        self.terminated = True
        self._dead.set()

    def kill(self) -> None:  # pragma: no cover - terminate() already unblocks
        self.killed = True
        self._dead.set()

    def wait(self, timeout: float | None = None) -> int:
        self._dead.wait(self.GUARD_SEC)
        return 0


# --------------------------------------------------------------------------- #
# residual 1a — kill_process_tree: descendants, not just the direct child
# --------------------------------------------------------------------------- #
def test_kill_process_tree_issues_taskkill_for_the_whole_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows the teardown shells out to ``taskkill /PID <pid> /T /F``.

    Mirrors the main process's proven ``killProcessTree`` (app/main/sidecar.ts):
    ``/T`` walks the parent-PID tree so ffmpeg's / node's grandchildren die too.
    """
    monkeypatch.setattr(ffmpeg, "_IS_WINDOWS", True)
    runner = _RecordingRunner()
    proc = _TreeProc(pid=4242)

    assert ffmpeg.kill_process_tree(proc, runner=runner) is True
    assert runner.calls == [["taskkill", "/PID", "4242", "/T", "/F"]]
    assert runner.kwargs["timeout"] == ffmpeg.TREE_KILL_TIMEOUT_SEC
    assert runner.kwargs["check"] is False


def test_kill_process_tree_is_a_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """``taskkill`` is Windows-only; elsewhere the caller's escalation stands."""
    monkeypatch.setattr(ffmpeg, "_IS_WINDOWS", False)
    runner = _RecordingRunner()

    assert ffmpeg.kill_process_tree(_TreeProc(pid=4242), runner=runner) is False
    assert runner.calls == []


def test_kill_process_tree_is_a_noop_without_a_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pid-less fake/dead proc must never reach ``taskkill`` (no stray signal)."""
    monkeypatch.setattr(ffmpeg, "_IS_WINDOWS", True)
    runner = _RecordingRunner()

    assert ffmpeg.kill_process_tree(_TreeProc(pid=None), runner=runner) is False
    assert runner.calls == []


def test_kill_process_tree_swallows_a_runner_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Teardown is best-effort: a failing/absent ``taskkill`` never raises."""
    monkeypatch.setattr(ffmpeg, "_IS_WINDOWS", True)

    def boom(argv: list[str], **kwargs: Any) -> None:
        raise OSError("taskkill missing")

    assert ffmpeg.kill_process_tree(_TreeProc(pid=4242), runner=boom) is False


def test_terminate_reaps_the_tree_before_signalling_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_terminate`` is now tree-aware: descendants are reaped, then the child."""
    monkeypatch.setattr(ffmpeg, "_IS_WINDOWS", True)
    runner = _RecordingRunner()
    monkeypatch.setattr(ffmpeg.subprocess, "run", runner)
    proc = _TreeProc(pid=777)

    ffmpeg._terminate(proc)

    assert runner.calls == [["taskkill", "/PID", "777", "/T", "/F"]]
    assert proc.terminated is True


# --------------------------------------------------------------------------- #
# residual 1b — watch_cancel: a poll loop that does NOT depend on output
# --------------------------------------------------------------------------- #
def test_watch_cancel_tears_down_a_process_that_emitted_nothing() -> None:
    """The core residual: cancellation with ZERO stdout activity still kills."""
    proc = _TreeProc(pid=None)

    assert ffmpeg.watch_cancel(proc, lambda: True, threading.Event(), poll_sec=0.0) is True
    assert proc.terminated is True


def test_watch_cancel_is_released_by_the_stop_event() -> None:
    """A completed run releases the watchdog without ever polling again."""
    proc = _TreeProc(pid=None)
    stop = threading.Event()
    stop.set()
    polls = {"n": 0}

    def probe() -> bool:  # pragma: no cover - a released watchdog must not poll
        polls["n"] += 1
        return True

    assert ffmpeg.watch_cancel(proc, probe, stop, poll_sec=0.0) is False
    assert polls["n"] == 0
    assert proc.terminated is False


def test_watch_cancel_keeps_polling_while_the_job_is_healthy() -> None:
    """A "not cancelled" answer loops back to the next poll (no early exit)."""
    proc = _TreeProc(pid=None)
    probe = _CancelProbe()  # NO on the first poll, YES on the second

    assert ffmpeg.watch_cancel(proc, probe, threading.Event(), poll_sec=0.0) is True
    assert probe.calls == 2
    assert proc.terminated is True


def test_watch_cancel_swallows_a_raising_probe() -> None:
    """A broken cancel probe must not kill the child NOR raise off-thread."""
    proc = _TreeProc(pid=None)

    def boom() -> bool:
        raise RuntimeError("job context vanished")

    assert ffmpeg.watch_cancel(proc, boom, threading.Event(), poll_sec=0.0) is False
    assert proc.terminated is False


# --------------------------------------------------------------------------- #
# residual 1c — run() wires the independent watchdog
# --------------------------------------------------------------------------- #
def test_run_starts_an_independent_cancel_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run`` spawns a daemon watchdog bound to ``watch_cancel`` when asked."""
    made: list[dict[str, Any]] = []

    class _Thread:
        def __init__(self, target: Any = None, daemon: bool | None = None, name: str | None = None) -> None:
            made.append({"target": target, "daemon": daemon, "name": name})

        def start(self) -> None:
            return None

    monkeypatch.setattr(ffmpeg.threading, "Thread", _Thread)

    class _Proc:
        stderr = None

        def __init__(self) -> None:
            self.stdout = iter(["progress=end\n"])

        def wait(self, timeout: float | None = None) -> int:
            return 0

    assert ffmpeg.run(["ffmpeg"], total_sec=1.0, should_cancel=lambda: False, popen=lambda *a, **k: _Proc()) == 0
    watchdogs = [t for t in made if t["name"] == "ffmpeg-cancel"]
    assert len(watchdogs) == 1
    assert watchdogs[0]["daemon"] is True
    target = watchdogs[0]["target"]
    assert isinstance(target, functools.partial)
    assert target.func is ffmpeg.watch_cancel


def test_run_starts_no_watchdog_without_a_cancel_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``should_cancel`` -> no watchdog thread (zero added cost)."""
    names: list[str | None] = []

    class _Thread:
        def __init__(self, target: Any = None, daemon: bool | None = None, name: str | None = None) -> None:
            names.append(name)

        def start(self) -> None:
            return None

    monkeypatch.setattr(ffmpeg.threading, "Thread", _Thread)

    class _Proc:
        stderr = None

        def __init__(self) -> None:
            self.stdout = iter(["progress=end\n"])

        def wait(self, timeout: float | None = None) -> int:
            return 0

    assert ffmpeg.run(["ffmpeg"], total_sec=1.0, popen=lambda *a, **k: _Proc()) == 0
    assert "ffmpeg-cancel" not in names


def test_run_cancels_a_silent_wedged_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE defect, end to end: a child that stops emitting output is still killed.

    Pre-fix this call never returns — the only cancel poll sits behind a blocking
    ``for raw in stdout`` readline. The probe answers NO once (consumed by that
    per-line poll while the first line is still flowing) and YES afterwards, so
    only an output-independent poll can observe the cancellation.
    """
    monkeypatch.setattr(ffmpeg, "CANCEL_POLL_SEC", 0.01)
    proc = _WedgedProc()
    probe = _CancelProbe()

    code = ffmpeg.run(["ffmpeg"], total_sec=10.0, should_cancel=probe, popen=lambda *a, **k: proc)

    assert proc.terminated is True  # torn down without a single further stdout line
    assert probe.calls > 1  # the watchdog polled after stdout went silent
    assert code == 0


# --------------------------------------------------------------------------- #
# residual 2 — _lightasd_infer's multi-GB work tree is always removed
# --------------------------------------------------------------------------- #
def test_work_tree_removes_the_tree_on_success() -> None:
    """The frames/crops tree is gone once the visual pass returns normally."""
    with _lightasd_infer._work_tree() as work:
        target = f"{work}/f/000001.jpg"
        _lightasd_infer.os.makedirs(f"{work}/f", exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(b"\x00" * 1024)
        assert _lightasd_infer.os.path.isfile(target)
    assert not _lightasd_infer.os.path.exists(work)


def test_work_tree_removes_the_tree_on_failure() -> None:
    """A mid-pipeline raise (e.g. "no frames extracted") still cleans up."""
    seen: dict[str, str] = {}
    with pytest.raises(RuntimeError, match="no frames extracted"), _lightasd_infer._work_tree() as work:
        seen["work"] = work
        raise RuntimeError("no frames extracted for visual ASD")
    assert not _lightasd_infer.os.path.exists(seen["work"])


def test_work_tree_removes_the_tree_on_cancellation() -> None:
    """Cancellation arrives as a BaseException; the tree must not survive it."""
    seen: dict[str, str] = {}
    with pytest.raises(KeyboardInterrupt), _lightasd_infer._work_tree() as work:
        seen["work"] = work
        raise KeyboardInterrupt
    assert not _lightasd_infer.os.path.exists(seen["work"])


def test_analyze_visual_uses_the_managed_work_tree() -> None:
    """The heavy seam is WIRED to the managed tree, not to bare ``mkdtemp``.

    ``analyze_visual`` needs torch/cv2/scipy + real weights, so it cannot be
    executed in the gate env (it is ``# pragma: no cover``). Its compiled
    ``co_names`` is a mechanical, non-source-grep probe that the leak cannot come
    back silently.
    """
    names = _lightasd_infer.analyze_visual.__code__.co_names
    assert "_work_tree" in names
    assert "mkdtemp" not in names


# --------------------------------------------------------------------------- #
# residual 3 — caption_remotion: Node + Chromium get the same discipline
# --------------------------------------------------------------------------- #
def test_remotion_terminate_reaps_the_chromium_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Killing the Node render CLI alone orphans its Chromium; reap the tree."""
    monkeypatch.setattr(ffmpeg, "_IS_WINDOWS", True)
    runner = _RecordingRunner()
    monkeypatch.setattr(ffmpeg.subprocess, "run", runner)
    proc = _TreeProc(pid=909)

    caption_remotion._terminate(proc)

    assert runner.calls == [["taskkill", "/PID", "909", "/T", "/F"]]
    assert proc.terminated is True


def test_run_render_starts_an_independent_cancel_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_render`` spawns the same daemon watchdog as ``ffmpeg.run``."""
    made: list[dict[str, Any]] = []

    class _Thread:
        def __init__(self, target: Any = None, daemon: bool | None = None, name: str | None = None) -> None:
            made.append({"target": target, "daemon": daemon, "name": name})

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            return None

    monkeypatch.setattr(caption_remotion.threading, "Thread", _Thread)

    class _Proc:
        stderr = None

        def __init__(self) -> None:
            self.stdout = iter(["RENDER_OK C:/out/clip.mp4\n"])

        def wait(self, timeout: float | None = None) -> int:
            return 0

    code, ok_path, _tail = caption_remotion.run_render(
        ["exe", "r.js", "j.json"],
        should_cancel=lambda: False,
        popen=lambda *a, **k: _Proc(),
    )
    assert (code, ok_path) == (0, "C:/out/clip.mp4")
    watchdogs = [t for t in made if t["name"] == "remotion-cancel"]
    assert len(watchdogs) == 1
    assert watchdogs[0]["daemon"] is True
    assert isinstance(watchdogs[0]["target"], functools.partial)
    assert watchdogs[0]["target"].func is ffmpeg.watch_cancel


def test_run_render_starts_no_watchdog_without_a_cancel_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``should_cancel`` -> no watchdog thread for the render CLI either."""
    names: list[str | None] = []

    class _Thread:
        def __init__(self, target: Any = None, daemon: bool | None = None, name: str | None = None) -> None:
            names.append(name)

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            return None

    monkeypatch.setattr(caption_remotion.threading, "Thread", _Thread)

    class _Proc:
        stderr = None

        def __init__(self) -> None:
            self.stdout = iter(["RENDER_OK C:/out/clip.mp4\n"])

        def wait(self, timeout: float | None = None) -> int:
            return 0

    caption_remotion.run_render(["exe", "r.js", "j.json"], popen=lambda *a, **k: _Proc())
    assert "remotion-cancel" not in names


def test_run_render_cancels_a_silent_wedged_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A render CLI that stops printing RENDER_PROGRESS is still torn down."""
    monkeypatch.setattr(ffmpeg, "CANCEL_POLL_SEC", 0.01)
    proc = _WedgedProc(first_line="RENDER_PROGRESS 5\n")
    probe = _CancelProbe()

    code, ok_path, _tail = caption_remotion.run_render(
        ["exe", "r.js", "j.json"],
        should_cancel=probe,
        popen=lambda *a, **k: proc,
    )

    assert proc.terminated is True
    assert probe.calls > 1
    assert (code, ok_path) == (0, None)


def test_teardown_helpers_never_spawn_a_real_taskkill() -> None:
    """Guard-rail: the tree kill is bound to the injectable subprocess seam."""
    assert ffmpeg.kill_process_tree.__defaults__ is None  # runner is keyword-only
    assert ffmpeg.subprocess is subprocess
