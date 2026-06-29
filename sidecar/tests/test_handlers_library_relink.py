"""L5 — ``library.reveal`` / ``library.regenerate`` / ``library.pinHash`` /
``library.relink`` RPC tests.

The handlers are thin pass-throughs to the :class:`Library` façade
(:mod:`media_studio.relink`): reveal/regenerate are read-only; pinHash/relink
mutate the entity row only after a whole-file BLAKE3 verify. These pin the RPC
surface — param validation, result shape, loud error mapping to INVALID_PARAMS,
and registration. No heavy dep / real ffmpeg (an injected zero-duration probe).
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

    return SimpleNamespace(id="job-1", status=JobStatus.DONE, request={"method": method, "params": {"preset": "p"}})


def _add_source(svc: Services, tmp_path: Path, name: str, data: bytes = b"\x00") -> tuple[str, Path]:
    media = tmp_path / name
    media.write_bytes(data)
    return svc.library.add(str(media))["id"], media


def _record_short(svc: Services, src: str, clip_id: str = "clip1") -> None:
    svc.library.record_lineage(
        _job(),
        inputs=[{"id": src}],
        outputs=[{"id": clip_id, "kind": "short", "path": "/x/c.mp4"}],
        agent={"appVersion": "1.1.0", "route": {"mode": "local"}},
    )


# --------------------------------------------------------------------------- #
# library.reveal
# --------------------------------------------------------------------------- #
def test_reveal_returns_present_source(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4")
    out = svc.library_reveal({"id": src}, ctx)
    assert out["sources"][0]["path"] == str(media.resolve())
    assert out["sources"][0]["exists"] is True
    assert out["missing"] == []


def test_reveal_unknown_id_is_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as exc:
        svc.library_reveal({"id": "ghost"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_reveal_id_param_required(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as exc:
        svc.library_reveal({}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# library.regenerate
# --------------------------------------------------------------------------- #
def test_regenerate_ready_descriptor(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4")
    _record_short(svc, src)
    out = svc.library_regenerate({"id": "clip1"}, ctx)
    assert out["op"] == "shorts.select"
    assert out["ready"] is True


def test_regenerate_raw_source_is_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4")
    with pytest.raises(RpcError) as exc:
        svc.library_regenerate({"id": src}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# library.pinHash
# --------------------------------------------------------------------------- #
def test_pin_hash_records_digest(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4", data=b"abc")
    out = svc.library_pin_hash({"id": src}, ctx)
    assert out["entity"]["contentHash"].startswith("blake3:")


def test_pin_hash_missing_file_is_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, media = _add_source(svc, tmp_path, "talk.mp4")
    media.unlink()
    with pytest.raises(RpcError) as exc:
        svc.library_pin_hash({"id": src}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# library.relink
# --------------------------------------------------------------------------- #
def test_relink_repoints_on_match(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4", data=b"content")
    svc.library_pin_hash({"id": src}, ctx)
    moved = tmp_path / "moved.mp4"
    moved.write_bytes(b"content")
    out = svc.library_relink({"id": src, "path": str(moved)}, ctx)
    assert out["entity"]["path"] == str(moved.resolve())


def test_relink_mismatch_is_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4", data=b"content")
    svc.library_pin_hash({"id": src}, ctx)
    wrong = tmp_path / "wrong.mp4"
    wrong.write_bytes(b"NOT the same")
    with pytest.raises(RpcError) as exc:
        svc.library_relink({"id": src, "path": str(wrong)}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_relink_path_param_required(tmp_path: Path, ctx: RpcContext) -> None:
    svc = _services(tmp_path)
    src, _media = _add_source(svc, tmp_path, "talk.mp4")
    with pytest.raises(RpcError) as exc:
        svc.library_relink({"id": src}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_l5_methods_are_registered(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in ("library.reveal", "library.regenerate", "library.pinHash", "library.relink"):
        assert method in registered
