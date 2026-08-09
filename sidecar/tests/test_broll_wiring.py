"""Composition-root wiring for ``broll.*`` (v1.5 flagship #3).

``test_broll_ops.py`` proves the service against injected seams. That is not the
same claim as "the running sidecar can answer broll.status" — a feature can be
fully unit-tested and never registered, or registered against the wrong
directory. So this module drives the REAL ``register_all`` composition root over
a tmp-dir ``Services`` and calls the handlers it collected.

The adapters exercised here are exactly the ones the unit tests cannot see: the
``brollDir`` settings scan, the index sidecar's location under the data dir, and
the transcript read off the project manifest.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from media_studio.features import broll_ops as bo
from media_studio.handlers import Services, register_all
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext


@pytest.fixture
def wired(tmp_path):
    """``(handlers, services)`` from the real composition root, tmp-dir backed."""
    collected: dict[str, Any] = {}
    services = Services(data_dir=tmp_path / "data")
    register_all(services, register=lambda name, handler: collected.__setitem__(name, handler))
    return collected, services


def _rpc(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def test_every_broll_method_is_registered_by_the_composition_root(wired):
    handlers, _services = wired
    assert set(bo.METHODS) <= set(handlers)


def test_broll_status_answers_on_a_first_run_machine(wired):
    # No brollDir configured, no index on disk: the honest answer is "nothing
    # indexed", not a crash and not a fabricated count.
    handlers, _services = wired
    got = handlers["broll.status"]({}, RpcContext(emit_notification=lambda obj: None, jobs=None))
    assert got == {
        "indexed": False,
        "assetCount": 0,
        "libraryCount": 0,
        "model": "",
        "dim": 0,
        "stale": True,
        "staleCount": 0,
        "willEgress": False,
    }


def test_the_wired_scan_reads_the_brollDir_setting(wired, tmp_path):
    handlers, services = wired
    folder = tmp_path / "my-broll"
    folder.mkdir()
    (folder / "dog.png").write_bytes(b"x")
    (folder / "city.mp4").write_bytes(b"yy")
    services.settings.set({bo.BROLL_DIR_KEY: str(folder)})
    assert handlers["broll.status"]({}, RpcContext(emit_notification=lambda obj: None, jobs=None))["libraryCount"] == 2


def test_the_wired_index_sidecar_lives_next_to_the_data_dir(wired, registry, tmp_path):
    handlers, services = wired
    folder = tmp_path / "my-broll"
    folder.mkdir()
    (folder / "dog.png").write_bytes(b"x")
    services.settings.set({bo.BROLL_DIR_KEY: str(folder)})

    # Swap ONLY the tower: everything else on the path is the real wiring.
    sidecar = services.data_dir / bo.INDEX_FILENAME
    assert not sidecar.exists()
    bo.save_index_file(sidecar, {"version": 1, "model": "m", "dim": 2, "builtAt": "t", "assets": []})
    # The wired load_index must read from that exact location.
    got = handlers["broll.status"]({}, RpcContext(emit_notification=lambda obj: None, jobs=None))
    assert got["indexed"] is True
    assert got["model"] == "m"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["model"] == "m"


def _add_video(handlers, registry, tmp_path) -> str:
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"not really a video")
    added = handlers["library.add"]({"path": str(video)}, _rpc(registry))
    return added["id"] if "id" in added else added["video"]["id"]


def _write_index(services, model: str) -> None:
    bo.save_index_file(
        services.data_dir / bo.INDEX_FILENAME,
        {"version": 1, "model": model, "dim": 2, "builtAt": "t", "assets": []},
    )


def test_the_wired_suggest_refuses_an_index_from_another_backbone(wired, registry, tmp_path):
    handlers, services = wired
    video_id = _add_video(handlers, registry, tmp_path)
    _write_index(services, "other/model")
    job = registry.get(handlers["broll.suggest"]({"videoId": video_id}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.status.value == "error"
    assert "one joint space" in str(job.error)


def test_the_wired_transcript_read_comes_off_the_project_manifest(wired, registry, tmp_path):
    handlers, services = wired
    video_id = _add_video(handlers, registry, tmp_path)
    # A MATCHING-model index gets past require_model, so the next thing suggest
    # touches is the wired transcript read. The project has no transcript, so it
    # must refuse with the actionable message rather than loading a model to
    # embed nothing.
    _write_index(services, bo.DEFAULT_MODEL_ID)
    job = registry.get(handlers["broll.suggest"]({"videoId": video_id}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.status.value == "error"
    assert "has no transcript yet" in str(job.error)


def test_the_wired_index_job_writes_the_sidecar_to_the_data_dir(wired, registry, tmp_path):
    handlers, services = wired
    empty = tmp_path / "empty-broll"
    empty.mkdir()
    services.settings.set({bo.BROLL_DIR_KEY: str(empty)})
    # An EMPTY library needs no embeddings, so this exercises the whole wired
    # index path - scan, refresh plan, merge, SAVE - with no weights installed.
    job = registry.get(handlers["broll.index"]({}, _rpc(registry))["jobId"])
    job.wait(timeout=5)
    assert job.status.value == "done", job.error
    sidecar = services.data_dir / bo.INDEX_FILENAME
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["model"] == bo.DEFAULT_MODEL_ID


def test_broll_methods_never_enter_the_key_injection_allowlist(wired):
    # keyBridge.ts injects on the ai./director./shortmaker./index. prefixes and a
    # small exact list. broll.* is local-only, so it must match none of them —
    # otherwise a provider key would be handed to a handler that has no provider.
    handlers, _services = wired
    prefixes = ("ai.", "director.", "shortmaker.", "index.")
    for name in bo.METHODS:
        assert name in handlers
        assert not name.startswith(prefixes)
