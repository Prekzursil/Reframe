"""F3b — the ``_require_number`` numeric param validator + its call sites.

``handlers._require_number`` rejects non-numeric (and bool — ``True``/``False``
are ``int`` subclasses but never a valid count/coordinate/fps) params with a
clean ``INVALID_PARAMS`` instead of letting a string/None crash deeper in the
pipeline. Wired into ``index.search`` (topK), ``nle.export`` (fps) and the
thumbnail span (start/end).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import library as _library
from media_studio.handlers import Services, _require_number
from media_studio.jobs import JobRegistry
from media_studio.protocol import ErrorCode, RpcContext, RpcError


# --------------------------------------------------------------------------- #
# unit: the validator (table-driven)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("params", "default", "expected"),
    [
        ({"n": 5}, 0.0, 5.0),
        ({"n": 2.5}, 0.0, 2.5),
        ({"n": 0}, 9.0, 0.0),  # present zero is honoured (not the default)
        ({}, 8.0, 8.0),  # missing -> default
        ({"n": -3}, 0.0, -3.0),
    ],
)
def test_require_number_accepts_numbers_and_defaults(params: dict[str, Any], default: float, expected: float) -> None:
    assert _require_number(params, "n", default) == expected


@pytest.mark.parametrize("bad", ["7", None, True, False, [1], {"x": 1}])
def test_require_number_rejects_non_numbers_and_bools(bad: Any) -> None:
    with pytest.raises(RpcError) as ei:
        _require_number({"n": bad}, "n", 0.0)
    assert ei.value.code == ErrorCode.INVALID_PARAMS
    assert "n must be a number" in str(ei.value)


# --------------------------------------------------------------------------- #
# integration: the three wired call sites reject bad values cleanly
# --------------------------------------------------------------------------- #
@pytest.fixture
def services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data")


@pytest.fixture
def ctx() -> RpcContext:
    jobs = JobRegistry(emit_progress=lambda *a: None, emit_done=lambda *a: None)
    return RpcContext(emit_notification=lambda obj: None, jobs=jobs)


def _add_video(services: Services, tmp_path: Path) -> str:
    p = tmp_path / "talk.mp4"
    p.write_bytes(b"\x00fake")
    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    return services.library.add(str(p))["id"]


def test_index_search_rejects_non_numeric_topk(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as ei:
        services.index_search({"videoId": "v1", "query": "x", "topK": "lots"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_nle_export_rejects_non_numeric_fps(services: Services, ctx: RpcContext, tmp_path: Path) -> None:
    vid = _add_video(services, tmp_path)
    with pytest.raises(RpcError) as ei:
        services.nle_export({"videoId": vid, "fps": "fast"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_nle_export_rejects_bool_fps(services: Services, ctx: RpcContext, tmp_path: Path) -> None:
    vid = _add_video(services, tmp_path)
    with pytest.raises(RpcError) as ei:
        services.nle_export({"videoId": vid, "fps": True}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_thumbnail_select_rejects_non_numeric_start(services: Services, ctx: RpcContext, tmp_path: Path) -> None:
    vid = _add_video(services, tmp_path)
    with pytest.raises(RpcError) as ei:
        services.thumbnail_select({"videoId": vid, "path": "/v.mp4", "start": "begin", "end": 3.0}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS
