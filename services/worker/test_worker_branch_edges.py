"""Targeted tests for the worker's remaining edge-case branches."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.models import (  # pylint: disable=import-error
    Job,
    MediaAsset,
    UsageEvent,
    UsageLedgerEntry,
)
from media_core.subtitles.builder import SubtitleLine  # pylint: disable=import-error
from media_core.transcribe.models import Word  # pylint: disable=import-error
from sqlmodel import select  # pylint: disable=import-error
from services.worker import worker  # pylint: disable=import-error


def _line(start, end, text="hi"):
    return SubtitleLine(
        start=start, end=end, words=[Word(text=text, start=start, end=end)]
    )


def test_find_repo_root_fallback(tmp_path):
    """When no ``apps/api`` ancestor exists, the parent dir is returned."""
    nested = tmp_path / "a" / "b" / "c.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    assert worker._find_repo_root(nested) == nested.parent


def test_worker_rel_dir_remote_storage_with_org():
    """A non-local storage backend with an org id nests under the org tmp dir."""
    org = uuid4()
    rel = worker._worker_rel_dir(storage=SimpleNamespace(), org_id=org)
    assert rel == f"{org}/tmp"
    # Local backend (or no org) uses the flat tmp dir.
    from app.storage import LocalStorageBackend  # pylint: disable=import-outside-toplevel

    local = LocalStorageBackend(media_root="/tmp/x")
    assert worker._worker_rel_dir(storage=local, org_id=org) == "tmp"


def test_resolve_local_asset_path_without_media_prefix():
    """A local URI without a ``media/`` prefix maps straight under media_root."""
    asset = MediaAsset(kind="video", uri="tmp/clip.mp4", mime_type="video/mp4")
    path = worker._resolve_local_asset_path(asset, "/root")
    assert path == Path("/root") / "tmp" / "clip.mp4"


def test_asset_size_bytes_without_media_prefix(worker_env):
    """Asset size resolves URIs that lack the ``media/`` prefix."""
    asset = worker_env.add_asset(uri="tmp/sized.bin", mime_type="application/octet-stream")
    target = worker_env.media_root / "tmp" / "sized.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"abc")
    assert worker._asset_size_bytes(asset) == 3


def test_asset_size_bytes_oserror(worker_env, monkeypatch):
    """An OSError while stat-ing an asset yields a zero size."""
    asset = worker_env.add_asset(uri="/media/tmp/x.bin", mime_type="x")
    real_exists = Path.exists

    def boom(self):
        raise OSError("stat failed")

    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "stat", boom)
    assert worker._asset_size_bytes(asset) == 0
    monkeypatch.setattr(Path, "exists", real_exists)


def test_download_remote_uri_bin_suffix(worker_env, monkeypatch):
    """A URI with no extension and no mime type uses the ``.bin`` suffix."""
    worker_local = worker_env.worker
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        worker_local.urllib.request, "urlopen", lambda *a, **k: _Resp()
    )

    def fake_copy(_resp, fileobj):
        captured["name"] = Path(fileobj.name).suffix
        fileobj.write(b"data")

    monkeypatch.setattr(worker_local.shutil, "copyfileobj", fake_copy)
    dest = worker_local._download_remote_uri_to_tmp(uri="https://cdn/download")
    assert dest.suffix == ".bin"


def test_create_thumbnail_with_kwargs_ffmpeg_success(worker_env, monkeypatch):
    """Thumbnail creation forwards project/org/owner kwargs through ffmpeg."""
    worker_local = worker_env.worker
    video = worker_local.new_tmp_file(".mp4")
    video.write_bytes(b"video")
    monkeypatch.setattr(worker_local.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return MediaAsset(kind="image", uri="/media/tmp/t.png", mime_type="image/png")

    def fake_runner(cmd, check=True, capture_output=True):  # pylint: disable=unused-argument
        Path(cmd[-1]).write_bytes(b"png")

    monkeypatch.setattr(worker_local, "create_asset", fake_create)
    proj, org, owner = uuid4(), uuid4(), uuid4()
    asset = worker_local.create_thumbnail_asset(
        video,
        runner=fake_runner,
        project_id=proj,
        org_id=org,
        owner_user_id=owner,
    )
    assert asset.uri.endswith(".png")
    assert captured["project_id"] == proj
    assert captured["org_id"] == org
    assert captured["owner_user_id"] == owner
    assert captured["source_path"] is not None


def test_create_thumbnail_ffmpeg_empty_output_falls_back(worker_env, monkeypatch):
    """An ffmpeg run that produces no output file falls back to a placeholder."""
    worker_local = worker_env.worker
    video = worker_local.new_tmp_file(".mp4")
    video.write_bytes(b"video")
    monkeypatch.setattr(worker_local.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    seen: list[str] = []

    def fake_create(**kwargs):
        seen.append(kwargs.get("contents") and "fallback" or "real")
        return MediaAsset(kind="image", uri="/media/tmp/t.png", mime_type="image/png")

    # Runner does not create the output file -> size check fails -> fallback.
    monkeypatch.setattr(worker_local, "create_asset", fake_create)
    worker_local.create_thumbnail_asset(
        video, runner=lambda *a, **k: None
    )
    assert "fallback" in seen


def test_create_thumbnail_existing_video_no_ffmpeg(worker_env, monkeypatch):
    """An existing video with no ffmpeg uses the placeholder fallback (line 554)."""
    worker_local = worker_env.worker
    video = worker_local.new_tmp_file(".mp4")
    video.write_bytes(b"video")
    monkeypatch.setattr(worker_local.shutil, "which", lambda name: None)

    created: list = []
    monkeypatch.setattr(
        worker_local,
        "create_asset",
        lambda **k: created.append(k) or MediaAsset(
            kind="image", uri="/media/tmp/f.png", mime_type="image/png"
        ),
    )
    worker_local.create_thumbnail_asset(video)
    assert created and created[0]["contents"]


def test_record_usage_no_subscription(worker_env):
    """Usage recording with an org but no subscription uses the free plan."""
    org = uuid4()
    with worker_env.session() as session:
        worker._record_usage_event(
            session,
            org_id=org,
            user_id=None,
            job_id=uuid4(),
            metric="job_minutes",
            quantity=2.0,
        )
        session.commit()
        ledger = session.exec(select(UsageLedgerEntry)).all()
    assert ledger[0].payload["plan_code"] == "free"
    assert ledger[0].unit == "minute"


def test_record_usage_unknown_metric(worker_env):
    """An unrecognised metric records with the default count unit."""
    org = uuid4()
    with worker_env.session() as session:
        worker._record_usage_event(
            session,
            org_id=org,
            user_id=None,
            job_id=uuid4(),
            metric="mystery_metric",
            quantity=1.0,
        )
        session.commit()
        ledger = session.exec(select(UsageLedgerEntry)).all()
    assert ledger[0].unit == "count"


def test_record_output_asset_usage_zero_size_and_no_minutes(worker_env):
    """Completion usage skips minutes/storage events when both are zero."""
    org = uuid4()
    # Asset has no duration and is remote (size 0) -> neither sub-event fires.
    remote = worker_env.add_asset(uri="https://cdn/x.mp4", mime_type="video/mp4", org_id=org)
    job = Job(job_type="cut", org_id=org, id=uuid4(), output_asset_id=remote.id)
    with worker_env.session() as session:
        worker._record_output_asset_usage(session, job, session.get(MediaAsset, remote.id))
        session.commit()
        events = session.exec(select(UsageEvent)).all()
    assert events == []


def test_record_job_completion_usage_no_output(worker_env):
    """Completion usage with no output asset only records jobs_completed."""
    org = uuid4()
    job = Job(job_type="cut", org_id=org, id=uuid4())
    with worker_env.session() as session:
        worker._record_job_completion_usage(session, job)
        session.commit()
        events = session.exec(select(UsageEvent)).all()
    assert {e.metric for e in events} == {"jobs_completed"}


def test_record_job_completion_usage_missing_output(worker_env):
    """An output asset id pointing at a deleted asset records only jobs_completed."""
    org = uuid4()
    job = Job(job_type="cut", org_id=org, id=uuid4(), output_asset_id=uuid4())
    with worker_env.session() as session:
        worker._record_job_completion_usage(session, job)
        session.commit()
        events = session.exec(select(UsageEvent)).all()
    assert {e.metric for e in events} == {"jobs_completed"}


def test_job_related_asset_ids_no_output_and_non_list():
    """No output asset and non-list clip_assets yield an empty id set."""
    job = Job(job_type="shorts", payload={"clip_assets": "not-a-list"})
    assert worker._job_related_asset_ids(job) == set()


def test_delete_asset_without_uri(worker_env):
    """An asset with no URI is deleted without touching storage."""
    asset = worker_env.add_asset(kind="video", uri="/media/tmp/a.mp4", mime_type="x")
    with worker_env.session() as session:
        stored = session.get(MediaAsset, asset.id)
        stored.uri = None
        worker._delete_asset(session, stored)
        session.commit()
        assert session.get(MediaAsset, asset.id) is None


def test_delete_asset_storage_error_is_swallowed(worker_env, monkeypatch):
    """A storage deletion error is logged and the row is still removed."""
    asset = worker_env.add_asset(kind="video", uri="/media/tmp/b.mp4", mime_type="x")

    class _Storage:
        def delete_uri(self, _uri):
            raise RuntimeError("delete failed")

    monkeypatch.setattr(worker, "_worker_storage", lambda: _Storage())
    with worker_env.session() as session:
        stored = session.get(MediaAsset, asset.id)
        worker._delete_asset(session, stored)
        session.commit()
        assert session.get(MediaAsset, asset.id) is None


def test_system_info_has_module_true(worker_env, monkeypatch):
    """``system_info`` reports a present module via the has_module True branch."""
    import builtins  # pylint: disable=import-outside-toplevel

    worker_local = worker_env.worker
    real_import = builtins.__import__
    # Pretend the optional feature modules import cleanly so has_module returns
    # True, while delegating every other import to the real importer.
    feature_modules = {
        "faster_whisper",
        "whispercpp",
        "argostranslate",
        "pyannote.audio",
        "speechbrain",
    }

    def fake_import(name, *args, **kwargs):
        if name in feature_modules:
            return SimpleNamespace()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    info = worker_local.system_info.run()
    assert all(info["features"].values())


def test_build_groq_translator_non_empty_model(monkeypatch):
    """A non-empty resolved model skips the default-model fallback branch."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setattr(
        worker, "get_groq_chat_client_from_env", lambda: SimpleNamespace()
    )
    translator = worker._build_groq_translator(
        {"groq_model": "mixtral-8x7b"}, warnings=[]
    )
    assert translator.model == "mixtral-8x7b"


def test_shift_subtitle_words_handles_bad_word():
    """A word whose timing cannot be coerced is skipped."""
    bad = SimpleNamespace(start="x", end=1.0, text="bad", probability=None)
    good = Word(text="ok", start=10.0, end=11.0)
    shifted = worker._shift_subtitle_words(
        [bad, good], start=10.0, clip_duration=5.0
    )
    assert [w.text for w in shifted] == ["ok"]


def test_shift_subtitle_words_word_construct_failure(monkeypatch):
    """A failure constructing the shifted Word is skipped."""
    word = Word(text="t", start=10.0, end=11.0)

    real_word = worker.Word

    def flaky(*_args, **_kwargs):
        raise ValueError("cannot build")

    monkeypatch.setattr(worker, "Word", flaky)
    try:
        shifted = worker._shift_subtitle_words(
            [word], start=10.0, clip_duration=5.0
        )
        assert shifted == []
    finally:
        monkeypatch.setattr(worker, "Word", real_word)


def test_shift_subtitle_line_collapsed_window():
    """A line that survives the first guard but collapses to zero is dropped."""
    # line overlaps [0,10) so the first guard passes, but clip_duration=2 makes
    # shifted_end (2) <= shifted_start (5), hitting the line 2191 return None.
    line = _line(5.0, 12.0)
    assert worker._shift_subtitle_line(
        line, start=0.0, end=10.0, clip_duration=2.0
    ) is None


def test_resolve_style_from_options_empty_preset():
    """An empty style and empty preset fall through to the default preset."""
    resolved = worker._resolve_style_from_options({"style_preset": ""})
    assert resolved["font"] == "Inter"


def test_shift_subtitle_line_empty_text_word_failure(monkeypatch):
    """When word-shifting fails and text fallback also fails, the line is dropped."""
    line = SubtitleLine(
        start=10.0, end=15.0, words=[Word(text="x", start=0.0, end=1.0)]
    )
    real_word = worker.Word

    def flaky(*args, **kwargs):
        raise ValueError("no word")

    monkeypatch.setattr(worker, "Word", flaky)
    try:
        # _shift_subtitle_words returns [] (flaky), text fallback also raises -> None.
        assert worker._shift_subtitle_line(
            line, start=10.0, end=15.0, clip_duration=5.0
        ) is None
    finally:
        monkeypatch.setattr(worker, "Word", real_word)


def test_shift_subtitle_line_no_text_fallback():
    """A line whose words shift out and whose text is empty is dropped."""
    line = SubtitleLine(start=10.0, end=15.0, words=[])
    assert worker._shift_subtitle_line(
        line, start=10.0, end=15.0, clip_duration=5.0
    ) is None


def test_apply_groq_segment_scoring_none_lines(worker_env, monkeypatch):
    """When subtitle loading returns None the scorer returns early (line 2729)."""
    worker_local = worker_env.worker
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setattr(
        worker_local, "_groq_load_subtitle_lines", lambda *a, **k: None
    )
    warnings: list[str] = []
    worker_local._apply_groq_segment_scoring(
        [],
        opts={},
        prompt="p",
        subtitle_asset_id="any",
        warnings=warnings,
    )
    # No "Applied Groq" / "GROQ_API_KEY" warning means it returned at the guard.
    assert not any("Applied Groq" in w for w in warnings)


def test_build_clip_subtitle_assets_no_subtitle_asset(worker_env, monkeypatch):
    """A falsy subtitle asset returns ``(asset, None)`` without styling (line 2839)."""
    worker_local = worker_env.worker
    ctx = worker_local.ShortsClipContext(
        job_id="job",
        src_path=Path("src.mp4"),
        mime_type="video/mp4",
        asset_kwargs={},
        use_subtitles=True,
        style_preset=None,
        subtitles=worker_local.ShortsSubtitleContext(
            style_for_clip={}, subtitle_source_lines=None, warnings=[]
        ),
    )
    monkeypatch.setattr(
        worker_local, "_build_clip_subtitle_file", lambda *a, **k: Path("s.vtt")
    )
    monkeypatch.setattr(
        worker_local, "create_asset_for_existing_file", lambda **k: None
    )
    seg = SimpleNamespace(start=0.0, end=2.0)
    subtitle_asset, styled_asset = worker_local._build_clip_subtitle_assets(
        ctx, idx=0, seg=seg, clip_path=Path("c.mp4")
    )
    assert subtitle_asset is None and styled_asset is None


def test_cleanup_skips_missing_and_referenced_assets(worker_env):
    """Cleanup skips assets that are gone or still referenced by other jobs."""
    worker_local = worker_env.worker
    org = uuid4()
    referenced = worker_env.add_asset(
        uri="/media/tmp/ref.mp4", mime_type="video/mp4", org_id=org
    )
    worker_env.write_media_file(referenced, b"x")
    missing_id = uuid4()
    job = Job(
        job_type="shorts",
        org_id=org,
        output_asset_id=referenced.id,
        payload={
            "clip_assets": [
                {"asset_id": str(referenced.id)},
                {"asset_id": str(missing_id)},
            ]
        },
    )
    # A second job still referencing the asset as input keeps it alive.
    other_job = Job(job_type="cut", org_id=org, input_asset_id=referenced.id)
    from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel

    with worker_env.session() as session:
        session.add(other_job)
        session.commit()
        cleaned = worker_local._cleanup_job_and_assets(
            session,
            job,
            plan_code="free",
            now=datetime.now(timezone.utc),
        )
        session.commit()
    # Referenced asset is kept; missing asset is skipped -> nothing cleaned.
    assert cleaned == 0
