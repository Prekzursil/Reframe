"""WU-3b1 — ``library.keepCopy`` / ``library.managedStatus`` / ``library.managedEvict``
/ ``library.managedClear`` RPC tests.

The handlers are thin pass-throughs to the :class:`Library` façade
(:mod:`media_studio.keepcopy`): keepCopy copies the source bytes into the managed
store and re-points lineage; managedStatus is read-only; managedEvict/managedClear
free the bytes and re-point each entity back to its original. These pin the RPC
surface — param validation, result shape, loud error mapping to INVALID_PARAMS, and
registration. No heavy dep / real ffmpeg (an injected zero-duration probe); the byte
copy runs the real atomic machinery over tiny temp files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from media_studio import handlers
from media_studio.handlers import Services
from media_studio.protocol import ErrorCode, RpcContext, RpcError


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", ffprobe_duration=lambda _p: 0.0)


def _add_source(svc: Services, tmp_path: Path, name: str, data: bytes) -> tuple[str, Path]:
    media = tmp_path / name
    media.write_bytes(data)
    return svc.library.add(str(media))["id"], media


# --------------------------------------------------------------------------- #
# library.keepCopy
# --------------------------------------------------------------------------- #
def test_keep_copy_returns_managed_row(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4", data=b"keep-me")
    out = svc.library_keep_copy({"id": src}, ctx)
    managed = out["managed"]
    assert managed["originalPath"] == str(media.resolve())
    assert Path(managed["managedPath"]).read_bytes() == b"keep-me"
    # lineage re-point: the library entity is now authoritative on the managed copy.
    assert svc.library.get(src)["path"] == managed["managedPath"]


def test_keep_copy_unknown_id_is_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as exc:
        svc.library_keep_copy({"id": "ghost"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_keep_copy_missing_source_is_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4", data=b"x")
    media.unlink()
    with pytest.raises(RpcError) as exc:
        svc.library_keep_copy({"id": src}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_keep_copy_id_param_required(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as exc:
        svc.library_keep_copy({}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# library.managedStatus
# --------------------------------------------------------------------------- #
def test_managed_status_reports_size_cap_count(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4", data=b"abcd")
    empty = svc.library_managed_status({}, ctx)
    assert empty["count"] == 0
    assert empty["sizeBytes"] == 0
    assert empty["capBytes"] > 0
    svc.library_keep_copy({"id": src}, ctx)
    after = svc.library_managed_status({}, ctx)
    assert after["count"] == 1
    assert after["sizeBytes"] == 4


# --------------------------------------------------------------------------- #
# library.managedEvict / library.managedClear
# --------------------------------------------------------------------------- #
def test_managed_evict_frees_the_copy(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4", data=b"payload")
    managed = svc.library_keep_copy({"id": src}, ctx)["managed"]
    out = svc.library_managed_evict({"id": src}, ctx)
    assert out == {"ok": True, "entityId": src}
    assert not Path(managed["managedPath"]).exists()
    assert svc.library.get(src)["path"] == str(media.resolve())  # reverts to original


def test_managed_evict_unknown_is_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as exc:
        svc.library_managed_evict({"id": "ghost"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_managed_evict_id_param_required(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as exc:
        svc.library_managed_evict({}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_managed_clear_removes_all(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    a, _ma = _add_source(svc, tmp_path, "a.mp4", data=b"aaa")
    b, _mb = _add_source(svc, tmp_path, "b.mp4", data=b"bbb")
    svc.library_keep_copy({"id": a}, ctx)
    svc.library_keep_copy({"id": b}, ctx)
    out = svc.library_managed_clear({}, ctx)
    assert out == {"ok": True, "cleared": 2}
    assert svc.library_managed_status({}, ctx)["count"] == 0


def test_managed_evict_original_gone_refuses_loud(tmp_path: Path, ctx: RpcContext) -> None:
    """RPC managedEvict of a copy whose original is gone fails LOUD (INVALID_PARAMS): the
    managed copy is the only surviving copy and must not be silently destroyed."""
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4", data=b"only-copy")
    managed = svc.library_keep_copy({"id": src}, ctx)["managed"]
    media.unlink()  # original gone -> irreplaceable
    with pytest.raises(RpcError) as exc:
        svc.library_managed_evict({"id": src}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS
    assert Path(managed["managedPath"]).exists()  # not destroyed


def test_managed_evict_force_destroys_only_copy(tmp_path: Path, ctx: RpcContext) -> None:
    """RPC managedEvict with force=true is the explicit escape hatch (destroys it)."""
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4", data=b"only-copy")
    managed = svc.library_keep_copy({"id": src}, ctx)["managed"]
    media.unlink()
    out = svc.library_managed_evict({"id": src, "force": True}, ctx)
    assert out == {"ok": True, "entityId": src}
    assert not Path(managed["managedPath"]).exists()


def test_managed_clear_refuses_when_irreplaceable(tmp_path: Path, ctx: RpcContext) -> None:
    """RPC managedClear refuses LOUD (INVALID_PARAMS), destroying nothing, when any copy's
    original is gone — unless force=true."""
    svc = _services(tmp_path)
    a, ma = _add_source(svc, tmp_path, "a.mp4", data=b"aaa")
    managed = svc.library_keep_copy({"id": a}, ctx)["managed"]
    ma.unlink()  # irreplaceable
    with pytest.raises(RpcError) as exc:
        svc.library_managed_clear({}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS
    assert Path(managed["managedPath"]).exists()  # nothing destroyed
    # force=true clears it.
    out = svc.library_managed_clear({"force": True}, ctx)
    assert out == {"ok": True, "cleared": 1}
    assert not Path(managed["managedPath"]).exists()


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_keepcopy_methods_are_registered(tmp_path: Path) -> None:
    registered: dict[str, object] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in ("library.keepCopy", "library.managedStatus", "library.managedEvict", "library.managedClear"):
        assert method in registered
