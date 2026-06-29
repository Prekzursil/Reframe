"""L3 — ``library.lineage`` RPC tests.

Surfaces an asset's W3C-PROV provenance through the Services handler: ancestors
(what it was made from) + descendants (what was made from it), composed over the
SQLite store the L1/L2 lineage write populates. The handler is a thin direct
pass-through to :meth:`Library.lineage` -> :func:`lineage.lineage_of`, so these
pin the RPC surface (param validation, shape, registration). No heavy dep / no
real ffmpeg is touched (the library uses an injected zero-duration probe).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio.handlers import Services
from media_studio.jobs import JobStatus
from media_studio.protocol import ErrorCode, RpcContext, RpcError


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", ffprobe_duration=lambda _p: 0.0)


def _job(method: str = "shorts.select") -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(id="job-1", status=JobStatus.DONE, request={"method": method, "params": {}})


def _add_source(svc: Services, tmp_path: Path, name: str) -> str:
    media = tmp_path / name
    media.write_bytes(b"\x00")
    return svc.library.add(str(media))["id"]


def test_lineage_returns_ancestors_and_descendants(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src = _add_source(svc, tmp_path, "talk.mp4")
    svc.library.record_lineage(
        _job(),
        inputs=[{"id": src}],
        outputs=[{"id": "clip1", "kind": "short", "path": "/x/c.mp4"}],
        agent={"appVersion": "1.1.0", "route": {"mode": "local"}},
    )

    result = svc.library_lineage({"id": "clip1"}, ctx)
    assert result["id"] == "clip1"
    assert result["entity"]["id"] == "clip1"
    assert [a["id"] for a in result["ancestors"]] == [src]
    assert result["descendants"] == []

    from_source = svc.library_lineage({"id": src}, ctx)
    assert [d["id"] for d in from_source["descendants"]] == ["clip1"]

    # L4: the produced clip carries its provenance card data through the RPC;
    # the raw source (imported, not produced) carries none.
    assert result["provenance"]["op"] == "shorts.select"
    assert result["provenance"]["route"] == {"mode": "local"}
    assert from_source["provenance"] is None


def test_lineage_unknown_id_returns_empty_structure(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    result = svc.library_lineage({"id": "ghost"}, ctx)
    assert result == {
        "id": "ghost",
        "entity": None,
        "ancestors": [],
        "descendants": [],
        "provenance": None,
    }


def test_lineage_id_param_is_required(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as exc:
        svc.library_lineage({}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_library_lineage_is_registered(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "library.lineage" in registered
