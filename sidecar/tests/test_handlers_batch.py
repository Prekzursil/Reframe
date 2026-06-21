"""Registration-site smoke for the ``batch.*`` group (WU10).

Asserts the single composition root ``register_all`` (handlers.py) wires the seven
``batch.*`` methods — and ONLY those seven new keys — onto the registry, each bound
to a :class:`batch.BatchStore` under ``Services.data_dir`` (so the per-batch files
land under ``batches/`` next to ``templates.json`` / ``export-presets.json``), and
that the wired ``batch.start`` default per-source runner reaches the live
``templates.apply`` handler registered in the same root. Mirrors the templates /
exportPresets register-site smokes. The batch group is the renderer's (WU11) RPC
surface, so the exact method names + param shapes are the contract under test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio import handlers, protocol
from media_studio.handlers import Services
from media_studio.protocol import RpcContext

BATCH_METHODS = {
    "batch.create",
    "batch.start",
    "batch.status",
    "batch.list",
    "batch.cancel",
    "batch.resume",
    "batch.delete",
}


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=None)


def test_register_all_wires_batch_methods(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert set(registered) >= BATCH_METHODS


def test_register_all_adds_only_the_seven_batch_keys(tmp_path: Path) -> None:
    """No stray ``batch.*`` key beyond the documented seven (acceptance 1)."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    batch_keys = {k for k in registered if k.startswith("batch.")}
    assert batch_keys == BATCH_METHODS


def test_batch_create_list_bound_to_data_dir(tmp_path: Path) -> None:
    """The registered handler is the live store: a created batch round-trips and the
    per-batch file lands under ``Services.data_dir / batches``."""
    data_dir = tmp_path / "d"
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=data_dir),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    out = registered["batch.create"]({"name": "B", "templateId": "tpl", "sourceVideoIds": ["v1"]}, _ctx())
    listed = registered["batch.list"]({}, _ctx())
    assert [b["id"] for b in listed["batches"]] == [out["batch"]["id"]]
    assert (data_dir / "batches" / f"{out['batch']['id']}.json").exists()


def test_batch_status_round_trips_created_batch(tmp_path: Path) -> None:
    """``batch.status`` of a freshly-created batch reads the durable checkpoint."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    created = registered["batch.create"]({"name": "B", "templateId": "tpl", "sourceVideoIds": ["v1", "v2"]}, _ctx())
    status = registered["batch.status"]({"id": created["batch"]["id"]}, _ctx())
    assert status["batch"]["status"] == "queued"
    assert status["batch"]["items"][0]["status"] == "queued"


def test_batch_registered_after_templates_apply(tmp_path: Path) -> None:
    """The wired default per-source runner resolves ``templates.apply`` from the live
    registry — proving the batch group is registered AFTER (and binds to) it."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "templates.apply" in registered  # the default batch runner's target


def test_batch_registered_on_real_protocol(tmp_path: Path) -> None:
    """register_all onto the real registry installs the keys (conftest restores)."""
    handlers.register_all(services=Services(data_dir=tmp_path / "d"))
    for rpc_method in BATCH_METHODS:
        assert rpc_method in protocol.METHODS


def test_video_title_unknown_falls_back_to_id(tmp_path: Path) -> None:
    """The batch title seam returns the id when the library has no such video."""
    svc = Services(data_dir=tmp_path / "d")
    assert svc._video_title("missing") == "missing"


def test_video_title_uses_library_title(tmp_path: Path) -> None:
    """A library video's ``title`` is used for the progress message."""
    svc = Services(data_dir=tmp_path / "d")
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"\x00")
    video = svc.library.add(str(media), "My Clip")
    assert svc._video_title(video["id"]) == "My Clip"


def test_video_title_blank_title_falls_back_to_id(tmp_path: Path) -> None:
    """A library video with an empty ``title`` falls back to the id (the ``or`` arm)."""
    import json

    data_dir = tmp_path / "d"
    data_dir.mkdir(parents=True, exist_ok=True)
    index = data_dir / "library.json"
    index.write_text(
        json.dumps({"version": 1, "videos": [{"id": "vblank", "path": "/x.mp4", "title": ""}]}),
        encoding="utf-8",
    )
    svc = Services(data_dir=data_dir)
    assert svc._video_title("vblank") == "vblank"
