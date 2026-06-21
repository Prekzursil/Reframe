"""WU-2 — ``library.thumbnail`` RPC tests.

Extract a poster from a SOURCE library video by reusing the shorts ffmpeg poster
engine, persist ``thumbnailPath`` onto the Video, and return it. Idempotent.

The ffmpeg ``run`` seam is FAKED (records the argv + "creates" the output by
touching it). No real ffmpeg / no subprocess is ever spawned — the heavy body
lives behind the injected ``ffmpeg_run`` seam, so 100% line+branch needs no
``# pragma`` here. These tests pin the §WU-2 falsifiable acceptance criteria.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio.features import shorts as _shorts
from media_studio.handlers import Services
from media_studio.protocol import ErrorCode, RpcContext, RpcError


class FakeRunner:
    """A fake ffmpeg ``run`` seam: records each argv and creates the output file.

    Mirrors ``ffmpeg.run(argv, total_sec=...) -> int`` (the same seam
    ``shorts.thumbnail`` uses). The output path is the argv's LAST element (the
    poster path), which the fake touches so an idempotence re-check sees it exist.
    """

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv: Any, total_sec: float = 0.0) -> int:
        self.calls.append(list(argv))
        if self.code == 0:
            out = Path(argv[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\xff\xd8\xff")  # minimal JPEG marker
        return self.code


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


@pytest.fixture
def fake_video(tmp_path: Path) -> Path:
    p = tmp_path / "src" / "talk.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00\x00fakebytes")
    return p


def _make_services(tmp_path: Path, runner: FakeRunner) -> tuple[Services, dict[str, Any]]:
    svc = Services(
        data_dir=tmp_path / "data",
        ffmpeg_run=runner,
        ffprobe_duration=lambda _p: 0.0,
    )
    return svc, {}


def test_first_call_invokes_runner_once_with_build_thumbnail_argv(
    tmp_path: Path, ctx: RpcContext, fake_video: Path
) -> None:
    runner = FakeRunner()
    svc, _ = _make_services(tmp_path, runner)
    video = svc.library.add(str(fake_video))

    result = svc.library_thumbnail({"id": video["id"]}, ctx)

    out = svc.data_dir / "thumbnails" / f"{video['id']}.jpg"
    assert result["thumbnailPath"] == str(out)
    assert len(runner.calls) == 1
    expected = _shorts.build_thumbnail_argv(video["path"], str(out), svc.settings.get())
    assert runner.calls[0] == expected


def test_second_call_is_idempotent_no_runner_invocation(tmp_path: Path, ctx: RpcContext, fake_video: Path) -> None:
    runner = FakeRunner()
    svc, _ = _make_services(tmp_path, runner)
    video = svc.library.add(str(fake_video))

    first = svc.library_thumbnail({"id": video["id"]}, ctx)
    second = svc.library_thumbnail({"id": video["id"]}, ctx)

    assert second["thumbnailPath"] == first["thumbnailPath"]
    assert len(runner.calls) == 1  # second call short-circuits on existing poster


def test_returned_path_is_under_data_dir_thumbnails(tmp_path: Path, ctx: RpcContext, fake_video: Path) -> None:
    runner = FakeRunner()
    svc, _ = _make_services(tmp_path, runner)
    video = svc.library.add(str(fake_video))

    result = svc.library_thumbnail({"id": video["id"]}, ctx)

    prefix = str(svc.data_dir / "thumbnails")
    assert result["thumbnailPath"].startswith(prefix)


def test_persists_thumbnail_path_onto_library_video(tmp_path: Path, ctx: RpcContext, fake_video: Path) -> None:
    runner = FakeRunner()
    svc, _ = _make_services(tmp_path, runner)
    video = svc.library.add(str(fake_video))

    result = svc.library_thumbnail({"id": video["id"]}, ctx)

    # Re-list (fresh read from disk) shows the persisted poster path.
    relisted = next(v for v in svc.library.list() if v["id"] == video["id"])
    assert relisted["thumbnailPath"] == result["thumbnailPath"]


def test_missing_video_id_raises_invalid_params(tmp_path: Path, ctx: RpcContext) -> None:
    runner = FakeRunner()
    svc, _ = _make_services(tmp_path, runner)

    with pytest.raises(RpcError) as exc:
        svc.library_thumbnail({"id": "does-not-exist"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS
    assert len(runner.calls) == 0


def test_id_param_is_required(tmp_path: Path, ctx: RpcContext) -> None:
    runner = FakeRunner()
    svc, _ = _make_services(tmp_path, runner)

    with pytest.raises(RpcError) as exc:
        svc.library_thumbnail({}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_runner_nonzero_exit_raises_internal_error(tmp_path: Path, ctx: RpcContext, fake_video: Path) -> None:
    runner = FakeRunner(code=1)
    svc, _ = _make_services(tmp_path, runner)
    video = svc.library.add(str(fake_video))

    with pytest.raises(RpcError) as exc:
        svc.library_thumbnail({"id": video["id"]}, ctx)
    assert exc.value.code == ErrorCode.INTERNAL_ERROR
    # On a failed run, nothing is persisted onto the Video.
    relisted = next(v for v in svc.library.list() if v["id"] == video["id"])
    assert relisted["thumbnailPath"] == ""


def test_uses_default_ffmpeg_run_seam_when_not_injected(
    tmp_path: Path, ctx: RpcContext, fake_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no injected ffmpeg_run, the handler resolves the default seam lazily.
    # Patch the module-level default resolver so no real ffmpeg is touched.
    calls: list[list[str]] = []

    def fake_run(argv: Any, total_sec: float = 0.0) -> int:
        calls.append(list(argv))
        out = Path(argv[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff\xd8\xff")
        return 0

    monkeypatch.setattr(handlers, "_self_ffmpeg_run", lambda: fake_run)
    svc = Services(data_dir=tmp_path / "data", ffprobe_duration=lambda _p: 0.0)
    video = svc.library.add(str(fake_video))

    result = svc.library_thumbnail({"id": video["id"]}, ctx)

    assert len(calls) == 1
    assert result["thumbnailPath"].endswith(f"{video['id']}.jpg")


def test_library_thumbnail_is_registered(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "library.thumbnail" in registered
