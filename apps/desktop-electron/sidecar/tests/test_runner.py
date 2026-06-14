"""Unit tests for media_studio.models.runner.

Subprocess, whisper loading, and the CUDA free-hook are ALL injected/mocked: no
process is ever spawned (no ``llama-server.exe`` needed), faster-whisper is never
imported, and no GPU is touched. The tests cover the argv builder, the GGUF path
resolution, the LaneLock single-occupant eviction, and the ModelRunner
start/stop/load/free lifecycle including the "one heavy model at a time" rule.
"""
from __future__ import annotations

from typing import Any, List, Optional

import pytest

from media_studio.models import runner as rn
from media_studio.models.runner import (
    LANE_LLAMA,
    LANE_WHISPER,
    LaneLock,
    ModelRunner,
    build_server_argv,
    resolve_gguf_path,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeProc:
    """A stand-in subprocess handle recording terminate/kill/wait calls."""

    def __init__(self, argv: List[str], *, exits_after: Optional[int] = None):
        self.argv = argv
        self.terminated = False
        self.killed = False
        self.waited = False
        self._poll_calls = 0
        self._exits_after = exits_after  # poll() returns 0 after N calls; None=alive

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        return 0

    def poll(self) -> Optional[int]:
        self._poll_calls += 1
        if self._exits_after is not None and self._poll_calls > self._exits_after:
            return 0
        return None


class FakePopen:
    """A popen seam recording every argv it is asked to spawn."""

    def __init__(self):
        self.spawned: List[List[str]] = []
        self.procs: List[FakeProc] = []

    def __call__(self, argv, *args: Any, **kwargs: Any) -> FakeProc:
        # Guard: the runner must pass a list (argv), never a shell string.
        assert isinstance(argv, list), "runner must spawn with an argv list"
        assert "shell" not in kwargs or kwargs["shell"] is False
        self.spawned.append(list(argv))
        proc = FakeProc(list(argv))
        self.procs.append(proc)
        return proc


class FakeWhisper:
    """A stand-in loaded whisper model (an opaque object)."""


# --------------------------------------------------------------------------- #
# build_server_argv (pure function)
# --------------------------------------------------------------------------- #
def test_build_server_argv_core_shape():
    argv = build_server_argv("D:/models/qwen3-4b.gguf")
    assert argv[0] == rn.DEFAULT_LLAMA_SERVER
    assert "-m" in argv and argv[argv.index("-m") + 1] == "D:/models/qwen3-4b.gguf"
    assert "--port" in argv and argv[argv.index("--port") + 1] == str(rn.DEFAULT_PORT)


def test_build_server_argv_is_a_list_not_a_string():
    argv = build_server_argv("/path with spaces/model.gguf")
    assert isinstance(argv, list)
    # the spaced path is ONE argv element (shell-safe)
    assert "/path with spaces/model.gguf" in argv


def test_build_server_argv_includes_host_ctx_and_gpu_layers():
    argv = build_server_argv(
        "m.gguf", host="0.0.0.0", port=9000, ctx_size=4096, gpu_layers=20
    )
    assert argv[argv.index("--host") + 1] == "0.0.0.0"
    assert argv[argv.index("--port") + 1] == "9000"
    assert argv[argv.index("--ctx-size") + 1] == "4096"
    assert argv[argv.index("--n-gpu-layers") + 1] == "20"


def test_build_server_argv_custom_server_path():
    argv = build_server_argv("m.gguf", server_path="/opt/llama/server")
    assert argv[0] == "/opt/llama/server"


def test_build_server_argv_extra_args_appended():
    argv = build_server_argv("m.gguf", extra_args=["--flash-attn", "--threads", "8"])
    assert argv[-3:] == ["--flash-attn", "--threads", "8"]


def test_build_server_argv_requires_gguf():
    with pytest.raises(ValueError):
        build_server_argv("")


# --------------------------------------------------------------------------- #
# resolve_gguf_path (CONTRACTS.md §2 settings.*)
# --------------------------------------------------------------------------- #
def test_resolve_gguf_explicit_path_wins():
    assert resolve_gguf_path({"ggufPath": "/x/model.gguf"}) == "/x/model.gguf"


def test_resolve_gguf_from_models_dir():
    got = resolve_gguf_path({"modelsDir": "D:/models"})
    assert got == "D:/models/qwen3-4b.gguf"


def test_resolve_gguf_normalizes_backslashes_and_trailing_slash():
    got = resolve_gguf_path({"modelsDir": "D:\\models\\"})
    assert got == "D:/models/qwen3-4b.gguf"


def test_resolve_gguf_none_when_unconfigured():
    assert resolve_gguf_path({}) is None
    assert resolve_gguf_path(None) is None


# --------------------------------------------------------------------------- #
# LaneLock single-occupant eviction
# --------------------------------------------------------------------------- #
def test_lanelock_starts_empty():
    lane = LaneLock()
    assert lane.occupant is None


def test_lanelock_acquire_records_occupant():
    lane = LaneLock()
    evicted: List[str] = []
    lane.acquire(LANE_LLAMA, evicted.append)
    assert lane.occupant == LANE_LLAMA
    assert evicted == []  # nothing to evict on first acquire


def test_lanelock_swap_evicts_previous_occupant():
    lane = LaneLock()
    evicted: List[str] = []
    lane.acquire(LANE_LLAMA, evicted.append)
    lane.acquire(LANE_WHISPER, evicted.append)
    assert lane.occupant == LANE_WHISPER
    assert evicted == [LANE_LLAMA]  # the llama lane was evicted for whisper


def test_lanelock_reacquire_same_lane_is_noop():
    lane = LaneLock()
    evicted: List[str] = []
    lane.acquire(LANE_LLAMA, evicted.append)
    lane.acquire(LANE_LLAMA, evicted.append)
    assert lane.occupant == LANE_LLAMA
    assert evicted == []  # no eviction when re-acquiring the same lane


def test_lanelock_release_clears_matching_occupant():
    lane = LaneLock()
    lane.acquire(LANE_LLAMA, lambda _l: None)
    lane.release(LANE_LLAMA)
    assert lane.occupant is None


def test_lanelock_release_nonoccupant_is_noop():
    lane = LaneLock()
    lane.acquire(LANE_LLAMA, lambda _l: None)
    lane.release(LANE_WHISPER)  # not the occupant -> no change
    assert lane.occupant == LANE_LLAMA


# --------------------------------------------------------------------------- #
# ModelRunner: llama.cpp server lifecycle
# --------------------------------------------------------------------------- #
def _runner(popen=None, whisper_load=None, free_hook=None, settings=None):
    return ModelRunner(
        settings=settings if settings is not None else {"ggufPath": "/m/model.gguf"},
        popen=popen or FakePopen(),
        whisper_load=whisper_load,
        free_hook=free_hook or (lambda: None),
    )


def test_start_server_spawns_with_argv_list():
    popen = FakePopen()
    r = _runner(popen=popen)
    proc = r.start_server()
    assert proc is popen.procs[0]
    assert r.server_running is True
    # spawned with an argv list naming the gguf + port
    argv = popen.spawned[0]
    assert "/m/model.gguf" in argv
    assert "--port" in argv


def test_start_server_claims_llama_lane():
    r = _runner()
    r.start_server()
    assert r.heavy_occupant == LANE_LLAMA


def test_start_server_idempotent():
    popen = FakePopen()
    r = _runner(popen=popen)
    p1 = r.start_server()
    p2 = r.start_server()
    assert p1 is p2
    assert len(popen.spawned) == 1  # only spawned once


def test_start_server_uses_explicit_gguf_argument():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})  # no settings path
    r.start_server(gguf_path="/explicit/x.gguf")
    assert "/explicit/x.gguf" in popen.spawned[0]


def test_start_server_raises_without_a_model():
    r = _runner(settings={})  # neither ggufPath nor modelsDir
    with pytest.raises(ValueError):
        r.start_server()


def test_stop_server_terminates_and_clears():
    popen = FakePopen()
    r = _runner(popen=popen)
    r.start_server()
    proc = popen.procs[0]
    r.stop_server()
    assert proc.terminated is True
    assert r.server_running is False
    assert r.heavy_occupant is None


def test_stop_server_when_not_running_is_noop():
    r = _runner()
    r.stop_server()  # should not raise
    assert r.server_running is False


def test_server_running_false_after_proc_exits():
    popen = FakePopen()
    r = _runner(popen=popen)
    r.start_server()
    # Force the proc to report exited on the next poll.
    popen.procs[0]._exits_after = 0
    assert r.server_running is False


# --------------------------------------------------------------------------- #
# ModelRunner: whisper lifecycle
# --------------------------------------------------------------------------- #
def test_load_whisper_uses_injected_loader():
    model = FakeWhisper()
    loads: List[int] = []

    def load():
        loads.append(1)
        return model

    r = _runner(whisper_load=load)
    got = r.load_whisper()
    assert got is model
    assert r.whisper_loaded is True
    assert r.heavy_occupant == LANE_WHISPER
    assert len(loads) == 1


def test_load_whisper_idempotent():
    calls: List[int] = []
    r = _runner(whisper_load=lambda: calls.append(1) or FakeWhisper())
    m1 = r.load_whisper()
    m2 = r.load_whisper()
    assert m1 is m2
    assert len(calls) == 1  # loaded only once


def test_load_whisper_without_seam_raises():
    r = _runner(whisper_load=None)
    with pytest.raises(ValueError):
        r.load_whisper()


def test_free_whisper_runs_free_hook_and_clears():
    freed: List[int] = []
    r = _runner(whisper_load=FakeWhisper, free_hook=lambda: freed.append(1))
    r.load_whisper()
    r.free_whisper()
    assert r.whisper_loaded is False
    assert r.heavy_occupant is None
    assert freed == [1]  # CUDA free-hook fired


def test_free_whisper_when_not_loaded_is_noop():
    freed: List[int] = []
    r = _runner(whisper_load=FakeWhisper, free_hook=lambda: freed.append(1))
    r.free_whisper()
    assert freed == []  # nothing loaded -> free-hook not called


def test_free_hook_failure_is_swallowed():
    def boom():
        raise RuntimeError("cuda gone")

    r = _runner(whisper_load=FakeWhisper, free_hook=boom)
    r.load_whisper()
    r.free_whisper()  # must not raise despite the free-hook failing
    assert r.whisper_loaded is False


# --------------------------------------------------------------------------- #
# the headline rule: ONE heavy model resident at a time
# --------------------------------------------------------------------------- #
def test_loading_whisper_stops_running_server():
    popen = FakePopen()
    r = _runner(popen=popen, whisper_load=FakeWhisper)
    r.start_server()
    assert r.server_running is True
    # Loading whisper must evict (stop) the llama server first.
    r.load_whisper()
    assert r.server_running is False
    assert r.whisper_loaded is True
    assert r.heavy_occupant == LANE_WHISPER
    assert popen.procs[0].terminated is True


def test_starting_server_frees_resident_whisper():
    popen = FakePopen()
    freed: List[int] = []
    r = _runner(popen=popen, whisper_load=FakeWhisper, free_hook=lambda: freed.append(1))
    r.load_whisper()
    assert r.whisper_loaded is True
    # Starting the server must evict (free) the whisper model first.
    r.start_server()
    assert r.whisper_loaded is False
    assert r.server_running is True
    assert r.heavy_occupant == LANE_LLAMA
    assert freed == [1]  # whisper free-hook fired during eviction


def test_never_two_heavy_residents_after_swaps():
    popen = FakePopen()
    r = _runner(popen=popen, whisper_load=FakeWhisper)
    r.start_server()
    r.load_whisper()
    r.start_server()
    r.load_whisper()
    # After all the swaps, exactly one heavy resident — whisper — is live.
    assert r.whisper_loaded is True
    assert r.server_running is False
    assert r.heavy_occupant == LANE_WHISPER


# --------------------------------------------------------------------------- #
# shutdown / context manager
# --------------------------------------------------------------------------- #
def test_shutdown_tears_down_everything():
    popen = FakePopen()
    freed: List[int] = []
    r = _runner(popen=popen, whisper_load=FakeWhisper, free_hook=lambda: freed.append(1))
    r.start_server()
    # (loading whisper would evict the server; load directly after to have both
    # paths exercised, then shutdown must clear whatever remains)
    r.shutdown()
    assert r.server_running is False
    assert r.whisper_loaded is False
    assert r.heavy_occupant is None
    assert popen.procs[0].terminated is True


def test_shutdown_is_idempotent():
    r = _runner(whisper_load=FakeWhisper)
    r.load_whisper()
    r.shutdown()
    r.shutdown()  # second call must not raise
    assert r.whisper_loaded is False


def test_context_manager_shuts_down_on_exit():
    popen = FakePopen()
    with _runner(popen=popen) as r:
        r.start_server()
        assert r.server_running is True
    # exiting the with-block calls shutdown()
    assert r.server_running is False
    assert popen.procs[0].terminated is True


def test_terminate_proc_kills_when_wait_times_out():
    # A proc whose wait() raises (simulating a timeout) must be killed.
    class Stubborn(FakeProc):
        def wait(self, timeout: float | None = None) -> int:
            raise RuntimeError("still running")

    proc = Stubborn(["x"])
    rn._terminate_proc(proc)
    assert proc.terminated is True
    assert proc.killed is True


def test_proc_exited_handles_missing_poll():
    class NoPoll:
        pass

    assert rn._proc_exited(NoPoll()) is False


# --------------------------------------------------------------------------- #
# T3: model-identity-aware start_server (switch / reuse / current_model_path)
# --------------------------------------------------------------------------- #
def test_current_model_path_lifecycle():
    popen = FakePopen()
    r = _runner(popen=popen)
    assert r.current_model_path is None
    r.start_server()
    assert r.current_model_path == "/m/model.gguf"
    r.stop_server()
    assert r.current_model_path is None


def test_start_server_same_model_reuses_process():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    p1 = r.start_server(gguf_path="/m/a.gguf")
    p2 = r.start_server(gguf_path="/m/a.gguf")
    assert p1 is p2
    assert len(popen.spawned) == 1
    assert popen.procs[0].terminated is False


def test_start_server_same_model_different_spelling_reuses():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    p1 = r.start_server(gguf_path="D:/Models/A.gguf")
    p2 = r.start_server(gguf_path="d:\\models\\a.gguf")
    assert p1 is p2
    assert len(popen.spawned) == 1


def test_start_server_different_model_restarts():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    p1 = r.start_server(gguf_path="/m/a.gguf")
    p2 = r.start_server(gguf_path="/m/b.gguf")
    assert p1 is not p2
    assert len(popen.spawned) == 2
    # graceful stop of the old server before the new spawn
    assert popen.procs[0].terminated is True
    assert "/m/b.gguf" in popen.spawned[1]
    assert r.current_model_path == "/m/b.gguf"
    assert r.server_running is True


def test_model_switch_keeps_llama_lane():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    r.start_server(gguf_path="/m/a.gguf")
    r.start_server(gguf_path="/m/b.gguf")
    assert r.heavy_occupant == LANE_LLAMA


def test_settings_resolved_switch_restarts():
    # An explicit start, then a settings-resolved start naming a DIFFERENT
    # model: the runner must notice and switch.
    popen = FakePopen()
    r = _runner(popen=popen, settings={"ggufPath": "/m/settings.gguf"})
    r.start_server(gguf_path="/m/explicit.gguf")
    r.start_server()  # resolves /m/settings.gguf from settings -> different
    assert len(popen.spawned) == 2
    assert "/m/settings.gguf" in popen.spawned[1]
    assert r.current_model_path == "/m/settings.gguf"


def test_start_server_running_with_no_model_resolvable_reuses():
    # Degenerate: server running, no path passed, nothing in settings -> the
    # live process is reused rather than raising.
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    p1 = r.start_server(gguf_path="/m/a.gguf")
    p2 = r.start_server()
    assert p1 is p2
    assert len(popen.spawned) == 1


def test_start_server_relaunches_after_crash():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    r.start_server(gguf_path="/m/a.gguf")
    popen.procs[0]._exits_after = 0  # the server died on its own
    p2 = r.start_server(gguf_path="/m/a.gguf")
    assert p2 is popen.procs[1]
    assert len(popen.spawned) == 2
    assert r.server_running is True


def test_start_server_gpu_layers_override_in_argv():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    r.start_server(gguf_path="/m/a.gguf", gpu_layers=24)
    argv = popen.spawned[0]
    assert argv[argv.index("--n-gpu-layers") + 1] == "24"


def test_start_server_extra_args_forwarded():
    popen = FakePopen()
    r = _runner(popen=popen, settings={})
    r.start_server(gguf_path="/m/a.gguf", extra_args=["--flash-attn"])
    assert popen.spawned[0][-1] == "--flash-attn"


def test_model_switch_evicted_by_whisper_then_restartable():
    # switch interleaved with the heavy-lane rule: whisper eviction clears the
    # model path; a later start_server relaunches cleanly.
    popen = FakePopen()
    r = _runner(popen=popen, whisper_load=FakeWhisper, settings={})
    r.start_server(gguf_path="/m/a.gguf")
    r.load_whisper()  # evicts the server (lane swap)
    assert r.current_model_path is None
    r.start_server(gguf_path="/m/b.gguf")
    assert r.current_model_path == "/m/b.gguf"
    assert r.whisper_loaded is False  # whisper evicted back out
    assert len(popen.spawned) == 2


def test_normalize_model_path_helpers():
    assert rn._same_model("D:\\m\\A.gguf", "d:/m/a.gguf") is True
    assert rn._same_model("/m/a.gguf", "/m/b.gguf") is False
    assert rn._same_model(None, "/m/a.gguf") is False
    assert rn._same_model("/m/a.gguf", None) is False
