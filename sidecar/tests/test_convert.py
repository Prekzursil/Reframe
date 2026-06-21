"""Unit tests for media_studio.features.convert.

Everything is mocked at the seam: ``run`` (the ffmpeg subprocess streamer) and
``probe`` (ffprobe duration) are injected, so no real ffmpeg/ffprobe is spawned
and no binary needs to exist. The argv builder is exercised through the real
``ffmpeg.build_convert_argv`` with a fake bundled-binary dir, including paths
that contain spaces and the audio-extract path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import convert
from media_studio.jobs import JobCancelled, JobRegistry


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #
def _make_exe(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n", encoding="utf-8")
    return p


@pytest.fixture()
def bins(tmp_path: Path) -> dict[str, str]:
    """A settings dict whose ffmpegPath points at a dir with fake ffmpeg/ffprobe."""
    _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    _make_exe(tmp_path / f"ffprobe{ffmpeg._EXE}")
    return {"ffmpegPath": str(tmp_path)}


class _RunRecorder:
    """A fake ffmpeg.run: records argv + total_sec, optionally streams progress."""

    def __init__(self, code: int = 0, progress_pcts: list[float] | None = None):
        self.code = code
        self.progress_pcts = progress_pcts or []
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv, total_sec=0.0, on_progress=None, should_cancel=None):
        self.calls.append({"argv": list(argv), "total_sec": total_sec, "should_cancel": should_cancel})
        if on_progress is not None:
            for pct in self.progress_pcts:
                on_progress(pct, f"{pct:.1f}%")
            on_progress(100.0, "done")
        return self.code


def _probe(value: float):
    return lambda in_path, settings=None: value


# --------------------------------------------------------------------------- #
# output_path (pure) — the heart of the unit, incl audio-extract + spaces
# --------------------------------------------------------------------------- #
def test_output_path_explicit_out_wins():
    got = convert.output_path("/a/in.mov", {"container": "mp4"}, out="/x/forced.mkv")
    assert got == "/x/forced.mkv"


def test_output_path_video_uses_container_ext():
    got = convert.output_path("/clips/talk.mov", {"container": "mp4"})
    assert Path(got) == Path("/clips/talk.mp4")


def test_output_path_video_default_container_when_absent():
    got = convert.output_path("/clips/talk.mov", {})
    assert Path(got).suffix == ".mp4"  # default video container


def test_output_path_container_strips_leading_dot_and_case():
    got = convert.output_path("/v/in.avi", {"container": ".MKV"})
    assert Path(got).suffix == ".mkv"


def test_output_path_audio_only_uses_audio_format_ext():
    got = convert.output_path("/v/in.mp4", {"audioOnly": True, "audioFormat": "mp3"})
    assert Path(got) == Path("/v/in.mp3")


def test_output_path_audio_only_maps_codec_name_to_extension():
    # aac -> m4a, libmp3lame -> mp3, libopus -> opus, libvorbis -> ogg
    assert Path(convert.output_path("/v/i.mp4", {"audioOnly": True, "audioFormat": "aac"})).suffix == ".m4a"
    assert Path(convert.output_path("/v/i.mp4", {"audioOnly": True, "audioFormat": "libmp3lame"})).suffix == ".mp3"
    assert Path(convert.output_path("/v/i.mp4", {"audioOnly": True, "audioFormat": "libopus"})).suffix == ".opus"
    assert Path(convert.output_path("/v/i.mp4", {"audioOnly": True, "audioFormat": "libvorbis"})).suffix == ".ogg"


def test_output_path_audio_only_falls_back_to_acodec():
    # No audioFormat given, but acodec implies the format.
    got = convert.output_path("/v/in.mp4", {"audioOnly": True, "acodec": "flac"})
    assert Path(got).suffix == ".flac"


def test_output_path_audio_only_default_when_unspecified():
    got = convert.output_path("/v/in.mp4", {"audioOnly": True})
    assert Path(got).suffix == ".m4a"  # default audio extension


def test_output_path_unknown_audio_format_used_verbatim():
    got = convert.output_path("/v/in.mp4", {"audioOnly": True, "audioFormat": "weird"})
    assert Path(got).suffix == ".weird"


def test_output_path_avoids_inplace_clobber():
    # Source already .mp4 and target container mp4 in the same dir -> add infix.
    got = convert.output_path("/v/in.mp4", {"container": "mp4"})
    assert got != "/v/in.mp4"
    assert "converted" in Path(got).name
    assert Path(got).suffix == ".mp4"


def test_output_path_preserves_spaces_in_path():
    got = convert.output_path("/my videos/a clip.mov", {"container": "mp4"})
    # The directory + stem (with their spaces) survive intact.
    assert Path(got).parent == Path("/my videos")
    assert Path(got).name == "a clip.mp4"


def test_output_path_preserves_spaces_for_audio_extract():
    got = convert.output_path("/my videos/a clip.mov", {"audioOnly": True, "audioFormat": "mp3"})
    assert Path(got).name == "a clip.mp3"


# --------------------------------------------------------------------------- #
# source resolution
# --------------------------------------------------------------------------- #
def test_resolve_source_prefers_explicit_path():
    assert convert._resolve_source({"path": "/p/v.mp4"}, None) == "/p/v.mp4"


def test_resolve_source_via_video_id():
    resolver = {"vid-1": "/lib/v.mp4"}.get
    assert convert._resolve_source({"videoId": "vid-1"}, resolver) == "/lib/v.mp4"


def test_resolve_source_unknown_video_id_raises():
    with pytest.raises(ValueError):
        convert._resolve_source({"videoId": "nope"}, {}.get)


def test_resolve_source_missing_both_raises():
    with pytest.raises(ValueError):
        convert._resolve_source({}, None)


# --------------------------------------------------------------------------- #
# convert_one
# --------------------------------------------------------------------------- #
def test_convert_one_builds_argv_runs_and_returns_path(bins):
    run = _RunRecorder(code=0, progress_pcts=[25.0, 50.0])
    progress: list[tuple] = []
    out = convert.convert_one(
        {"path": "/a b/in.mov", "options": {"container": "mp4", "vcodec": "libx264", "crf": 23}},
        settings=bins,
        on_progress=lambda p, m: progress.append((round(p, 1), m)),
        run=run,
        probe=_probe(10.0),
    )
    assert Path(out) == Path("/a b/in.mp4")
    # argv carries the resolved source/dest with the space preserved as one element
    argv = run.calls[0]["argv"]
    assert "/a b/in.mov" in argv
    assert argv[-1] == str(Path("/a b/in.mp4"))
    assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "libx264"
    # the probed duration was passed through for real-percentage progress
    assert run.calls[0]["total_sec"] == pytest.approx(10.0)
    # progress streamed + final done
    assert (25.0, "25.0%") in progress
    assert progress[-1] == (100.0, "done")


def test_convert_one_audio_extract_builds_vn_and_audio_ext(bins):
    run = _RunRecorder(code=0)
    out = convert.convert_one(
        {"path": "/clips/talk.mp4", "options": {"audioOnly": True, "audioFormat": "mp3", "acodec": "libmp3lame"}},
        settings=bins,
        run=run,
        probe=_probe(5.0),
    )
    assert Path(out).suffix == ".mp3"
    argv = run.calls[0]["argv"]
    assert "-vn" in argv  # audio-only strips video
    assert "-c:v" not in argv
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "libmp3lame"


def test_convert_one_resolves_video_id(bins):
    run = _RunRecorder(code=0)
    out = convert.convert_one(
        {"videoId": "v9", "options": {"container": "mkv"}},
        settings=bins,
        resolver={"v9": "/lib/source.mov"}.get,
        run=run,
        probe=_probe(0.0),
    )
    assert Path(out) == Path("/lib/source.mkv")
    assert "/lib/source.mov" in run.calls[0]["argv"]


def test_convert_one_explicit_out_override(bins):
    run = _RunRecorder(code=0)
    out = convert.convert_one(
        {"path": "/a/in.mov", "out": "/dest/final.webm", "options": {"container": "mp4"}},
        settings=bins,
        run=run,
        probe=_probe(1.0),
    )
    assert out == "/dest/final.webm"
    assert run.calls[0]["argv"][-1] == "/dest/final.webm"


def test_convert_one_nonzero_exit_raises(bins):
    run = _RunRecorder(code=1)
    with pytest.raises(RuntimeError):
        convert.convert_one(
            {"path": "/a/in.mov", "options": {"container": "mp4"}},
            settings=bins,
            run=run,
            probe=_probe(1.0),
        )


def test_convert_one_probe_failure_is_tolerated(bins):
    run = _RunRecorder(code=0)

    def boom(in_path, settings=None):
        raise OSError("ffprobe blew up")

    out = convert.convert_one(
        {"path": "/a/in.mov", "options": {"container": "mp4"}},
        settings=bins,
        run=run,
        probe=boom,
    )
    assert Path(out) == Path("/a/in.mp4")
    # a failed probe -> total_sec 0.0 (coarse progress, but the convert proceeds)
    assert run.calls[0]["total_sec"] == 0.0


def test_convert_one_passes_should_cancel_through(bins):
    run = _RunRecorder(code=0)
    flag = {"v": False}
    convert.convert_one(
        {"path": "/a/in.mov", "options": {}},
        settings=bins,
        should_cancel=lambda: flag["v"],
        run=run,
        probe=_probe(1.0),
    )
    # the cancel callback reached run()
    assert run.calls[0]["should_cancel"] is not None
    assert run.calls[0]["should_cancel"]() is False


# --------------------------------------------------------------------------- #
# convert_batch
# --------------------------------------------------------------------------- #
def test_convert_batch_returns_all_paths_in_order(bins):
    run = _RunRecorder(code=0)
    paths = convert.convert_batch(
        [
            {"path": "/a/one.mov", "options": {"container": "mp4"}},
            {"path": "/a/two.mkv", "options": {"audioOnly": True, "audioFormat": "wav"}},
        ],
        settings=bins,
        run=run,
        probe=_probe(2.0),
    )
    assert [Path(p) for p in paths] == [Path("/a/one.mp4"), Path("/a/two.wav")]
    assert len(run.calls) == 2


def test_convert_batch_progress_spans_items(bins):
    run = _RunRecorder(code=0, progress_pcts=[50.0])
    seen: list[float] = []
    convert.convert_batch(
        [
            {"path": "/a/one.mov", "options": {}},
            {"path": "/a/two.mov", "options": {}},
        ],
        settings=bins,
        on_progress=lambda p, m: seen.append(round(p, 1)),
        run=run,
        probe=_probe(1.0),
    )
    # 2 items: item0 50% -> overall 25; item0 done(100) -> 50;
    #          item1 50% -> 75; item1 done -> 100.
    assert 25.0 in seen
    assert 50.0 in seen
    assert 75.0 in seen
    assert seen[-1] == 100.0


def test_convert_batch_message_tags_item_index(bins):
    run = _RunRecorder(code=0, progress_pcts=[10.0])
    msgs: list[str] = []
    convert.convert_batch(
        [{"path": "/a/one.mov", "options": {}}],
        settings=bins,
        on_progress=lambda p, m: msgs.append(m),
        run=run,
        probe=_probe(1.0),
    )
    assert any(m.startswith("[1/1]") for m in msgs)


def test_convert_batch_empty_items_returns_empty(bins):
    run = _RunRecorder(code=0)
    assert convert.convert_batch([], settings=bins, run=run, probe=_probe(1.0)) == []
    assert run.calls == []


def test_convert_batch_stops_when_cancelled_before_item(bins):
    run = _RunRecorder(code=0)
    paths = convert.convert_batch(
        [{"path": "/a/one.mov"}, {"path": "/a/two.mov"}],
        settings=bins,
        should_cancel=lambda: True,  # cancelled before the first item even starts
        run=run,
        probe=_probe(1.0),
    )
    assert paths == []
    assert run.calls == []


def test_convert_batch_resolves_video_ids(bins):
    run = _RunRecorder(code=0)
    paths = convert.convert_batch(
        [{"videoId": "a", "options": {"container": "mp4"}}, {"videoId": "b", "options": {"container": "mkv"}}],
        settings=bins,
        resolver={"a": "/lib/a.mov", "b": "/lib/b.mov"}.get,
        run=run,
        probe=_probe(1.0),
    )
    assert [Path(p) for p in paths] == [Path("/lib/a.mp4"), Path("/lib/b.mkv")]


# --------------------------------------------------------------------------- #
# job handlers + integration with JobRegistry
# --------------------------------------------------------------------------- #
def _registry():
    events: list[tuple] = []
    reg = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    return reg, events


def test_start_handler_runs_job_and_emits_done(bins):
    run = _RunRecorder(code=0, progress_pcts=[40.0])
    handler = convert.start_handler(
        {"path": "/a b/in.mov", "options": {"container": "mp4"}},
        settings=bins,
        run=run,
        probe=_probe(8.0),
    )
    reg, events = _registry()
    job = reg.start(handler)
    assert job.wait(timeout=5)

    done = [e for e in events if e[0] == "done"]
    assert done and done[0][2] == {"path": str(Path("/a b/in.mp4"))}
    assert job.result == {"path": str(Path("/a b/in.mp4"))}
    # progress was relayed through the job (integer pct per §2)
    progress = [e for e in events if e[0] == "progress"]
    assert any(e[2] == 40 for e in progress)


def test_start_handler_path_only_no_resolver(bins):
    run = _RunRecorder(code=0)
    handler = convert.start_handler(
        {"path": "/v/clip.mov", "options": {"audioOnly": True, "audioFormat": "mp3"}},
        settings=bins,
        run=run,
        probe=_probe(3.0),
    )
    reg, events = _registry()
    job = reg.start(handler)
    assert job.wait(timeout=5)
    assert job.result == {"path": str(Path("/v/clip.mp3"))}


def test_start_handler_resolves_video_id(bins):
    run = _RunRecorder(code=0)
    handler = convert.start_handler(
        {"videoId": "z", "options": {"container": "mkv"}},
        settings=bins,
        resolver={"z": "/lib/z.mov"}.get,
        run=run,
        probe=_probe(1.0),
    )
    reg, events = _registry()
    job = reg.start(handler)
    assert job.wait(timeout=5)
    assert job.result == {"path": str(Path("/lib/z.mkv"))}


def test_start_handler_pre_cancelled_marks_cancelled(bins):
    run = _RunRecorder(code=0)
    handler = convert.start_handler({"path": "/a/in.mov", "options": {}}, settings=bins, run=run, probe=_probe(1.0))
    reg, events = _registry()
    job = reg.create(handler)
    job.request_cancel()  # cancel before it ever runs
    reg._spawn(job)
    assert job.wait(timeout=5)
    assert job.status.value == "cancelled"
    # the ffmpeg run never happened
    assert run.calls == []


def test_batch_handler_runs_and_returns_paths(bins):
    run = _RunRecorder(code=0)
    handler = convert.batch_handler(
        {
            "items": [
                {"path": "/a/one.mov", "options": {"container": "mp4"}},
                {"path": "/a/two.mov", "options": {"container": "mkv"}},
            ]
        },
        settings=bins,
        run=run,
        probe=_probe(1.0),
    )
    reg, events = _registry()
    job = reg.start(handler)
    assert job.wait(timeout=5)
    assert job.result == {"paths": [str(Path("/a/one.mp4")), str(Path("/a/two.mkv"))]}


def test_batch_handler_empty_items(bins):
    run = _RunRecorder(code=0)
    handler = convert.batch_handler({"items": []}, settings=bins, run=run, probe=_probe(1.0))
    reg, events = _registry()
    job = reg.start(handler)
    assert job.wait(timeout=5)
    assert job.result == {"paths": []}


def test_batch_handler_missing_items_key(bins):
    run = _RunRecorder(code=0)
    handler = convert.batch_handler({}, settings=bins, run=run, probe=_probe(1.0))
    reg, events = _registry()
    job = reg.start(handler)
    assert job.wait(timeout=5)
    assert job.result == {"paths": []}


def test_handler_propagates_convert_failure_as_job_error(bins):
    run = _RunRecorder(code=1)  # ffmpeg fails
    handler = convert.start_handler({"path": "/a/in.mov", "options": {}}, settings=bins, run=run, probe=_probe(1.0))
    reg, events = _registry()
    job = reg.start(handler)
    assert job.wait(timeout=5)
    assert job.status.value == "error"
    assert job.error and "code 1" in job.error
    # failure emits job.done with an error payload (clients must not hang)
    dones = [e for e in events if e[0] == "done"]
    assert len(dones) == 1
    assert "code 1" in dones[0][2]["error"]["message"]


def test_start_handler_raises_jobcancelled_when_precancelled_directly(bins):
    # Direct unit check that the handler honors the cancel flag (bypassing
    # the registry's own pre-run guard).
    import threading

    from media_studio.jobs import JobContext

    run = _RunRecorder(code=0)
    handler = convert.start_handler({"path": "/a/in.mov", "options": {}}, settings=bins, run=run, probe=_probe(1.0))
    ev = threading.Event()
    ev.set()
    ctx = JobContext(job_id="j1", _cancel_event=ev, _emit_progress=lambda *a: None)
    with pytest.raises(JobCancelled):
        handler(ctx)
    assert run.calls == []
