"""Extra coverage for media_studio.ffmpeg — resolution edge branches, the
stderr-drain seam, the on_progress=None path, nonzero-exit logging, and the
_terminate kill fallback. All subprocess/binary seams are mocked/injected; no
real ffmpeg is spawned and no binary needs to exist on the box.
"""

from __future__ import annotations

from pathlib import Path

from media_studio import ffmpeg


def _make_exe(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# resolve_binary edge branches
# --------------------------------------------------------------------------- #
def test_resolve_setting_names_other_binary_no_sibling_falls_through(monkeypatch, tmp_path):
    """settings names a DIFFERENT binary (ffmpeg) while we resolve ffprobe and no
    sibling exists -> the settings branch is skipped and PATH wins (70->78)."""
    ffmpeg_bin = _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    # no ffprobe beside it -> sibling lookup misses; ensure no env/bundled hit
    monkeypatch.delenv("MEDIA_STUDIO_FFPROBE", raising=False)
    monkeypatch.setattr(ffmpeg, "_BUNDLED_DIR", Path("/nonexistent/bin"))
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}")
    got = ffmpeg.resolve_binary("ffprobe", {"ffmpegPath": str(ffmpeg_bin)})
    assert got == "/usr/bin/ffprobe"


def test_resolve_setting_file_wrong_stem_no_sibling_for_same_name(monkeypatch, tmp_path):
    """A *Path-named setting (ffprobePath) that points at a file whose stem does
    not match and is not the generic ffmpegPath -> sibling lookup, then miss
    falls through (covers the 72->78 'sib not file' path)."""
    weird = _make_exe(tmp_path / f"notffprobe{ffmpeg._EXE}")
    monkeypatch.delenv("MEDIA_STUDIO_FFPROBE", raising=False)
    monkeypatch.setattr(ffmpeg, "_BUNDLED_DIR", Path("/nonexistent/bin"))
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}")
    got = ffmpeg.resolve_binary("ffprobe", {"ffprobePath": str(weird)})
    assert got == "/usr/bin/ffprobe"


def test_resolve_setting_dir_without_binary_falls_through(monkeypatch, tmp_path):
    """ffmpegPath is a dir that does NOT contain the binary -> dir branch misses
    its cand check and resolution falls through to PATH (74->78)."""
    empty_dir = tmp_path / "emptybin"
    empty_dir.mkdir()
    monkeypatch.delenv("MEDIA_STUDIO_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg, "_BUNDLED_DIR", Path("/nonexistent/bin"))
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}")
    got = ffmpeg.resolve_binary("ffmpeg", {"ffmpegPath": str(empty_dir)})
    assert got == "/usr/bin/ffmpeg"


def test_resolve_setting_nonexistent_path_falls_through(monkeypatch, tmp_path):
    """ffmpegPath points at a path that is neither a file nor a dir -> both the
    is_file and is_dir arms are skipped and resolution falls to PATH (72->78)."""
    ghost = tmp_path / "does-not-exist" / f"ffmpeg{ffmpeg._EXE}"
    monkeypatch.delenv("MEDIA_STUDIO_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg, "_BUNDLED_DIR", Path("/nonexistent/bin"))
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}")
    got = ffmpeg.resolve_binary("ffmpeg", {"ffmpegPath": str(ghost)})
    assert got == "/usr/bin/ffmpeg"


def test_resolve_from_bundled_dir(monkeypatch, tmp_path):
    """The bundled binary beside the package is used when nothing earlier hits
    (line 85)."""
    bundled = tmp_path / "bin"
    _make_exe(bundled / f"ffmpeg{ffmpeg._EXE}")
    monkeypatch.delenv("MEDIA_STUDIO_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg, "_BUNDLED_DIR", bundled)
    # which must not be consulted; if it is, fail loudly
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: "/should/not/be/used")
    got = ffmpeg.resolve_binary("ffmpeg", {})
    assert Path(got) == bundled / f"ffmpeg{ffmpeg._EXE}"


# --------------------------------------------------------------------------- #
# build_convert_argv: audioOnly without acodec (142->168 false branch)
# --------------------------------------------------------------------------- #
def test_build_convert_argv_audio_only_without_acodec(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "ffmpeg")
    argv = ffmpeg.build_convert_argv("/in.mp4", "/out.mp3", {"audioOnly": True}, None)
    assert "-vn" in argv
    assert "-c:a" not in argv  # no acodec supplied -> omitted
    assert argv[-1] == "/out.mp3"


# --------------------------------------------------------------------------- #
# run(): stderr drain seam + on_progress=None + nonzero exit logging
# --------------------------------------------------------------------------- #
class _Proc:
    """A Popen-shaped fake whose stdout/stderr are real iterables."""

    def __init__(self, stdout_lines, stderr_lines, code=0):
        self.stdout = iter(stdout_lines)
        self.stderr = iter(stderr_lines)
        self._code = code

    def wait(self, timeout=None):
        return self._code


def test_run_drains_stderr_and_logs_on_nonzero(monkeypatch):
    """A non-empty stderr is drained (266-270) and, on a nonzero exit, the tail
    is logged (297). The drain runs on a daemon thread; join it deterministically
    by patching Thread to run synchronously."""
    import threading as _threading

    started = []

    class SyncThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target

        def start(self):
            started.append(True)
            if self._target is not None:
                self._target()

    monkeypatch.setattr(ffmpeg.threading, "Thread", SyncThread)

    logged = {}
    monkeypatch.setattr(ffmpeg.log, "error", lambda *a, **k: logged.setdefault("err", (a, k)))

    proc = _Proc(
        stdout_lines=["progress=end\n"],
        # blank + carriage-return rewrite + real line exercise the seg parsing
        stderr_lines=["\n", "x\rError: boom\n", "  \n"],
        code=2,
    )
    code = ffmpeg.run(["ffmpeg"], total_sec=1.0, popen=lambda *a, **k: proc)
    assert code == 2
    assert started == [True]
    assert "err" in logged  # nonzero exit + non-empty stderr tail -> logged
    assert isinstance(_threading.Thread, type)  # original restored by monkeypatch


def test_run_drain_swallows_iteration_error(monkeypatch):
    """If iterating stderr raises, _drain swallows it (269-270) and run() still
    completes normally."""

    class SyncThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr(ffmpeg.threading, "Thread", SyncThread)

    def boom_stderr():
        yield "first line\n"
        raise OSError("pipe broke mid-drain")

    class Proc:
        def __init__(self):
            self.stdout = iter(["progress=end\n"])
            self.stderr = boom_stderr()

        def wait(self, timeout=None):
            return 0

    code = ffmpeg.run(["ffmpeg"], total_sec=1.0, popen=lambda *a, **k: Proc())
    assert code == 0  # drain error swallowed; run unaffected


def test_run_stdout_none_skips_progress_loop(monkeypatch):
    """proc.stdout is None -> the progress loop is skipped entirely (276->295)."""
    monkeypatch.setattr(ffmpeg.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())

    class Proc:
        stdout = None

        def __init__(self):
            self.stderr = iter([])

        def wait(self, timeout=None):
            return 0

    code = ffmpeg.run(["ffmpeg"], total_sec=1.0, popen=lambda *a, **k: Proc())
    assert code == 0


def test_run_stderr_none_skips_drain(monkeypatch):
    """When proc.stderr is None the drain branch is skipped (261->274)."""

    class NoErrProc:
        stderr = None

        def __init__(self):
            self.stdout = iter(["progress=end\n"])

        def wait(self, timeout=None):
            return 0

    # Thread must never be started here.
    monkeypatch.setattr(
        ffmpeg.threading,
        "Thread",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no drain expected")),
    )
    code = ffmpeg.run(["ffmpeg"], total_sec=1.0, popen=lambda *a, **k: NoErrProc())
    assert code == 0


def test_run_without_on_progress_skips_callbacks(monkeypatch):
    """on_progress is None: the end-of-progress and pct branches are skipped
    (283 continue on un-parseable line, 289->277 on_progress-None branch)."""
    monkeypatch.setattr(ffmpeg.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    proc = _Proc(
        stdout_lines=["garbage-no-equals\n", "out_time_ms=500000\n", "progress=end\n"],
        stderr_lines=[],
        code=0,
    )
    # no on_progress passed -> must not raise
    code = ffmpeg.run(["ffmpeg"], total_sec=1.0, on_progress=None, popen=lambda *a, **k: proc)
    assert code == 0


def test_run_nonzero_without_stderr_tail_does_not_log(monkeypatch):
    """Nonzero exit but empty stderr tail -> the log.error branch is NOT taken
    (the 'and stderr_tail' short-circuit)."""
    monkeypatch.setattr(ffmpeg.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    called = {"n": 0}
    monkeypatch.setattr(ffmpeg.log, "error", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    proc = _Proc(stdout_lines=["progress=end\n"], stderr_lines=[], code=1)
    code = ffmpeg.run(["ffmpeg"], total_sec=1.0, popen=lambda *a, **k: proc)
    assert code == 1
    assert called["n"] == 0


# --------------------------------------------------------------------------- #
# _terminate: wait raises -> kill fallback (307-309)
# --------------------------------------------------------------------------- #
def test_terminate_kills_when_wait_raises():
    class StubbornProc:
        def __init__(self):
            self.terminated = False
            self.killed = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            raise TimeoutError("did not die")

        def kill(self):
            self.killed = True

    proc = StubbornProc()
    ffmpeg._terminate(proc)
    assert proc.terminated is True
    assert proc.killed is True


def test_terminate_terminate_raising_is_suppressed():
    """terminate() raising is swallowed; wait() succeeds so kill is not needed."""

    class Proc:
        def __init__(self):
            self.killed = False

        def terminate(self):
            raise OSError("already gone")

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    proc = Proc()
    ffmpeg._terminate(proc)  # must not raise
    assert proc.killed is False


def test_run_cooperative_cancel_uses_terminate(monkeypatch):
    """A True should_cancel mid-stream terminates the proc (covers the cancel
    branch through _terminate)."""
    monkeypatch.setattr(ffmpeg.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())

    class CancelProc:
        def __init__(self):
            self.stdout = iter(["out_time_ms=100000\n", "out_time_ms=200000\n"])
            self.stderr = iter([])
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):  # pragma: no cover - wait succeeds, kill not reached
            pass

    proc = CancelProc()
    code = ffmpeg.run(["ffmpeg"], total_sec=10.0, should_cancel=lambda: True, popen=lambda *a, **k: proc)
    assert proc.terminated is True
    assert code == 0
