"""Unit tests for media_studio.features.tracks.

The ffmpeg subprocess seam is fully injected/mocked: no real ffmpeg is spawned,
no binary needs to exist (binary resolution is monkeypatched). Every burn /
soft-mux / strip op asserts the argv LIST shape (never a shell string) so
paths-with-spaces and "no shell=True" correctness is locked in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import tracks
from media_studio.features.tracks import (
    KIND_HARD,
    KIND_SOFT,
    HardSubtitleError,
    TrackError,
    TrackNotFoundError,
)


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture()
def fake_ffmpeg(monkeypatch):
    """Make ffmpeg_path/ffprobe resolution deterministic without a real binary."""
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda settings=None: "/bin/ffprobe")
    return "/bin/ffmpeg"


def _cue(index: int, start: float, end: float, text: str) -> dict[str, Any]:
    return {"index": index, "start": start, "end": end, "text": text}


def _track(track_id="t1", kind=KIND_SOFT, **over) -> dict[str, Any]:
    base = {
        "id": track_id,
        "lang": "en",
        "name": "English",
        "format": "srt",
        "kind": kind,
        "cues": [_cue(1, 0.0, 1.0, "hi")],
    }
    base.update(over)
    return base


def _project(*tracklist) -> dict[str, Any]:
    return {"id": "p1", "video": {"path": "/v.mp4"}, "tracks": list(tracklist), "clips": [], "settings": {}}


class _RunSpy:
    """A stand-in for ffmpeg.run: records the argv it was given, returns ``code``."""

    def __init__(self, code: int = 0, drive_progress=False):
        self.code = code
        self.calls: list[dict[str, Any]] = []
        self.drive_progress = drive_progress

    def __call__(self, argv, total_sec=0.0, on_progress=None, should_cancel=None):
        self.calls.append(
            {"argv": argv, "total_sec": total_sec, "on_progress": on_progress, "should_cancel": should_cancel}
        )
        if self.drive_progress and on_progress is not None:
            on_progress(50.0, "50%")
            on_progress(100.0, "done")
        return self.code

    @property
    def argv(self) -> list[str]:
        return self.calls[-1]["argv"]


# =========================================================================== #
# manifest edits: list / add / remove / rename / relabel
# =========================================================================== #
def test_list_tracks_returns_copy():
    t = _track()
    proj = _project(t)
    got = tracks.list_tracks(proj)
    assert got == [t]
    got.append({"id": "x"})  # mutating the returned list must not touch project
    assert len(proj["tracks"]) == 1


def test_list_tracks_creates_missing_list():
    proj = {"id": "p"}
    assert tracks.list_tracks(proj) == []
    assert proj["tracks"] == []


def test_find_track_hit_and_miss():
    proj = _project(_track("a"), _track("b"))
    assert tracks.find_track(proj, "b")["id"] == "b"
    with pytest.raises(TrackNotFoundError):
        tracks.find_track(proj, "zzz")


def test_add_track_normalizes_and_appends():
    proj = _project()
    added = tracks.add_track(proj, {"id": "new", "cues": []})
    assert added["kind"] == KIND_SOFT  # default kind
    assert added["lang"] == "und"  # default lang
    assert added["name"] == "new"  # name defaults to id
    assert added["format"] == "srt"  # default format
    assert proj["tracks"][-1]["id"] == "new"


def test_add_track_is_idempotent_by_id():
    proj = _project(_track("dup", name="orig"))
    again = tracks.add_track(proj, {"id": "dup", "name": "changed"})
    assert again["name"] == "orig"  # existing row returned, unchanged
    assert len(proj["tracks"]) == 1


def test_add_track_preserves_path_ref():
    proj = _project()
    added = tracks.add_track(proj, {"id": "p", "path": "/subs/en.srt", "cues": []})
    assert added["path"] == "/subs/en.srt"


def test_add_track_rejects_missing_id():
    with pytest.raises(TrackError):
        tracks.add_track(_project(), {"cues": []})


def test_add_track_rejects_bad_kind():
    with pytest.raises(TrackError):
        tracks.add_track(_project(), {"id": "x", "kind": "burned"})


def test_remove_soft_track_returns_and_drops_it():
    proj = _project(_track("a"), _track("b"))
    removed = tracks.remove_track(proj, "a")
    assert removed["id"] == "a"
    assert [t["id"] for t in proj["tracks"]] == ["b"]


def test_remove_hard_track_surfaces_error():
    proj = _project(_track("hard", kind=KIND_HARD))
    with pytest.raises(HardSubtitleError) as ei:
        tracks.remove_track(proj, "hard")
    assert "cannot be removed" in str(ei.value)
    # the track must remain on the project (nothing dropped)
    assert [t["id"] for t in proj["tracks"]] == ["hard"]


def test_remove_unknown_track_raises():
    with pytest.raises(TrackNotFoundError):
        tracks.remove_track(_project(_track("a")), "nope")


def test_rename_track_sets_name():
    proj = _project(_track("a", name="old"))
    out = tracks.rename_track(proj, "a", "New Name")
    assert out["name"] == "New Name"
    assert proj["tracks"][0]["name"] == "New Name"


def test_rename_track_rejects_empty():
    proj = _project(_track("a"))
    with pytest.raises(TrackError):
        tracks.rename_track(proj, "a", "   ")


def test_relabel_track_sets_lang():
    proj = _project(_track("a", lang="en"))
    out = tracks.relabel_track(proj, "a", "es")
    assert out["lang"] == "es"


def test_relabel_track_rejects_empty():
    proj = _project(_track("a"))
    with pytest.raises(TrackError):
        tracks.relabel_track(proj, "a", "")


def test_normalize_track_rejects_non_dict():
    with pytest.raises(TrackError):
        tracks.normalize_track("not a dict")  # type: ignore[arg-type]


# =========================================================================== #
# ASS escaping (CONTRACTS.md section 4) — no {}/override injection
# =========================================================================== #
def test_ass_escape_braces_blocked():
    out = tracks.ass_escape("hello {b1}world")
    assert "{" not in out.replace("\\{", "")  # only escaped braces remain
    assert "\\{" in out and "\\}" in out


def test_ass_escape_backslash_neutralized():
    out = tracks.ass_escape("a\\Nb")  # raw \N (libass newline) -> literal
    assert out == "a\\\\Nb"


def test_ass_escape_newlines_become_soft_breaks():
    assert tracks.ass_escape("line1\nline2") == "line1\\Nline2"
    assert tracks.ass_escape("a\r\nb") == "a\\Nb"
    assert tracks.ass_escape("a\rb") == "a\\Nb"


def test_ass_escape_handles_none_and_empty():
    assert tracks.ass_escape("") == ""
    assert tracks.ass_escape(None) == ""  # type: ignore[arg-type]


def test_ass_escape_injection_attempt_is_inert():
    # An attempted override block must not survive as a real (unescaped) override.
    out = tracks.ass_escape("{\\an8}{\\c&H0000FF&}danger")
    assert out.startswith("\\{")
    # Safety invariant: every "{" is escaped, i.e. preceded by a backslash, so
    # libass never sees a live override-block opener.
    for i, ch in enumerate(out):
        if ch == "{":
            assert i > 0 and out[i - 1] == "\\"


# =========================================================================== #
# ASS document build: sizing, timestamps, rebase
# =========================================================================== #
def test_build_ass_document_has_header_and_sizing():
    doc = tracks.build_ass_document([_cue(1, 0, 1, "hi")], width=720, height=1280)
    assert "[Script Info]" in doc
    assert "PlayResX: 720" in doc
    assert "PlayResY: 1280" in doc
    assert "[Events]" in doc
    assert "Dialogue:" in doc


def test_build_ass_timestamp_centiseconds():
    assert tracks._ass_timestamp(0) == "0:00:00.00"
    assert tracks._ass_timestamp(3661.5) == "1:01:01.50"
    assert tracks._ass_timestamp(-5) == "0:00:00.00"  # clamped


def test_build_ass_document_rebases_by_source_start():
    cues = [_cue(1, 100.0, 102.0, "A"), _cue(2, 105.0, 107.0, "B")]
    doc = tracks.build_ass_document(cues, source_start=100.0)
    # 100s clip -> local 0..2 ; 105s -> 5..7
    assert "0:00:00.00,0:00:02.00" in doc
    assert "0:00:05.00,0:00:07.00" in doc


def test_build_ass_document_drops_cues_before_rebase_point():
    cues = [_cue(1, 10.0, 20.0, "before"), _cue(2, 60.0, 62.0, "after")]
    doc = tracks.build_ass_document(cues, source_start=50.0)
    assert "before" not in doc
    assert "after" in doc


def test_build_ass_document_clamps_straddling_cue_to_zero():
    cues = [_cue(1, 48.0, 53.0, "straddle")]
    doc = tracks.build_ass_document(cues, source_start=50.0)
    # start clamped to 0, end = 3
    assert "0:00:00.00,0:00:03.00" in doc


def test_build_ass_document_escapes_cue_text():
    doc = tracks.build_ass_document([_cue(1, 0, 1, "{\\an8}x")])
    assert "\\{" in doc
    assert "{\\an8}" not in doc


# =========================================================================== #
# argv builders — burn / soft-mux / strip  (argv LIST, no shell=True)
# =========================================================================== #
def test_build_burn_argv_uses_libass_filter(fake_ffmpeg):
    argv = tracks.build_burn_argv("/a b/in.mp4", "/a b/subs.ass", "/a b/out.mp4")
    assert isinstance(argv, list)
    assert argv[0] == "/bin/ffmpeg"
    assert "-i" in argv and argv[argv.index("-i") + 1] == "/a b/in.mp4"
    assert argv[-1] == "/a b/out.mp4"  # spaces preserved as one element
    vf = argv[argv.index("-vf") + 1]
    assert vf.startswith("subtitles=")  # libass filter
    assert "subs.ass" in vf
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "copy"
    assert "-progress" in argv and argv[argv.index("-progress") + 1] == "pipe:1"
    assert "shell" not in argv  # no shell anything in the argv


def test_build_burn_argv_maps_all_streams(fake_ffmpeg):
    """burn must ``-map 0`` so extra audio (muxed dubs) + soft subs survive."""
    argv = tracks.build_burn_argv("/in.mp4", "/subs.ass", "/out.mp4")
    map_idxs = [i for i, a in enumerate(argv) if a == "-map"]
    assert map_idxs, "burn argv must map streams"
    # a -map is followed by "0" (all input-0 streams)
    assert any(argv[i + 1] == "0" for i in map_idxs)


def test_burn_subtitle_codec_mov_text_for_mp4(fake_ffmpeg):
    argv = tracks.build_burn_argv("/in.mkv", "/subs.ass", "/out.mp4")
    assert argv[argv.index("-c:s") + 1] == "mov_text"


def test_burn_subtitle_codec_copy_for_mkv(fake_ffmpeg):
    argv = tracks.build_burn_argv("/in.mp4", "/subs.ass", "/out.mkv")
    assert argv[argv.index("-c:s") + 1] == "copy"


def test_ass_filter_path_escapes_windows_path():
    vf = tracks._ass_filter_path(r"C:\a b\subs.ass")
    assert vf.startswith("subtitles='") and vf.endswith("'")
    assert "\\\\" in vf  # backslashes doubled
    assert "\\:" in vf  # colon escaped


def test_build_soft_mux_argv_maps_both_inputs(fake_ffmpeg):
    argv = tracks.build_soft_mux_argv("/in.mp4", "/subs.srt", "/out.mkv", lang="es")
    assert argv.count("-i") == 2
    assert argv[argv.index("-i") + 1] == "/in.mp4"
    # both streams mapped
    map_idxs = [i for i, a in enumerate(argv) if a == "-map"]
    mapped = {argv[i + 1] for i in map_idxs}
    assert mapped == {"0", "1"}
    assert "-c" in argv and argv[argv.index("-c") + 1] == "copy"
    # lang metadata tagged on the new sub stream
    assert "-metadata:s:s:0" in argv
    assert argv[argv.index("-metadata:s:s:0") + 1] == "language=es"
    assert argv[-1] == "/out.mkv"


def test_soft_mux_subtitle_codec_mov_text_for_mp4(fake_ffmpeg):
    argv = tracks.build_soft_mux_argv("/in.mp4", "/s.srt", "/out.mp4")
    assert argv[argv.index("-c:s") + 1] == "mov_text"


def test_soft_mux_subtitle_codec_copy_for_mkv(fake_ffmpeg):
    argv = tracks.build_soft_mux_argv("/in.mkv", "/s.srt", "/out.mkv")
    assert argv[argv.index("-c:s") + 1] == "copy"


def test_soft_mux_omits_lang_metadata_when_absent(fake_ffmpeg):
    argv = tracks.build_soft_mux_argv("/in.mkv", "/s.srt", "/out.mkv")
    assert "-metadata:s:s:0" not in argv


def test_build_soft_mux_argv_tags_new_stream_index(fake_ffmpeg):
    """With N pre-existing subtitle streams, the lang tag targets output s:s:N."""
    argv = tracks.build_soft_mux_argv("/in.mkv", "/s.srt", "/out.mkv", lang="de", existing_sub_count=3)
    assert "-metadata:s:s:3" in argv
    assert argv[argv.index("-metadata:s:s:3") + 1] == "language=de"
    assert "-metadata:s:s:0" not in argv


def test_build_soft_mux_argv_default_count_tags_stream_zero(fake_ffmpeg):
    """Default existing_sub_count=0 keeps the subtitle-free-input behaviour."""
    argv = tracks.build_soft_mux_argv("/in.mkv", "/s.srt", "/out.mkv", lang="de")
    assert "-metadata:s:s:0" in argv


class _CompletedProbe:
    """Stand-in for subprocess.CompletedProcess used by _probe_subtitle_count."""

    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


def test_probe_subtitle_count_counts_nonempty_lines(fake_ffmpeg):
    # ffprobe csv output: one index per subtitle stream (+ a trailing blank line)
    runner = lambda argv, **kw: _CompletedProbe(returncode=0, stdout="2\n3\n\n")  # noqa: E731
    assert tracks._probe_subtitle_count("/in.mkv", None, runner) == 2


def test_probe_subtitle_count_zero_when_no_subtitle_streams(fake_ffmpeg):
    runner = lambda argv, **kw: _CompletedProbe(returncode=0, stdout="")  # noqa: E731
    assert tracks._probe_subtitle_count("/in.mkv", None, runner) == 0


def test_probe_subtitle_count_raises_on_probe_failure(fake_ffmpeg):
    runner = lambda argv, **kw: _CompletedProbe(returncode=3, stdout="")  # noqa: E731
    with pytest.raises(TrackError, match="probe failed"):
        tracks._probe_subtitle_count("/in.mkv", None, runner)


def test_build_strip_argv_negative_maps_chosen_stream(fake_ffmpeg):
    argv = tracks.build_strip_argv("/a b/in.mkv", "/a b/out.mkv", sub_stream_index=1)
    assert "-map" in argv
    assert "0" in argv  # keep everything
    assert "-0:s:1" in argv  # then drop chosen sub stream
    assert "-c" in argv and argv[argv.index("-c") + 1] == "copy"
    assert argv[-1] == "/a b/out.mkv"


def test_build_strip_argv_rejects_negative_index(fake_ffmpeg):
    with pytest.raises(TrackError):
        tracks.build_strip_argv("/in.mkv", "/out.mkv", sub_stream_index=-1)


# =========================================================================== #
# write_ass_sidecar — filesystem I/O
# =========================================================================== #
def test_write_ass_sidecar_writes_file(tmp_path: Path):
    out = tmp_path / "nested" / "subs.ass"
    cues = [_cue(1, 0, 1.5, "hello")]
    got = tracks.write_ass_sidecar(cues, out)
    assert Path(got).exists()
    text = Path(got).read_text(encoding="utf-8")
    assert "Dialogue:" in text and "hello" in text


# =========================================================================== #
# high-level ops — burn / soft-mux / strip with the run seam mocked
# =========================================================================== #
def test_burn_track_runs_ffmpeg_and_writes_sidecar(fake_ffmpeg, tmp_path: Path):
    in_path = str(tmp_path / "clip.mp4")
    track = _track(cues=[_cue(1, 0, 2, "yo")])
    run = _RunSpy(code=0)
    out = tracks.burn_track(
        in_path,
        track,
        run=run,
        duration=lambda *a, **k: 12.0,
    )
    assert out.endswith("clip-hardsub.mp4")
    # ffmpeg was invoked once, with an argv LIST whose filter is libass
    assert len(run.calls) == 1
    argv = run.argv
    assert isinstance(argv, list)
    assert argv[0] == "/bin/ffmpeg"
    assert argv[argv.index("-vf") + 1].startswith("subtitles=")
    assert run.calls[0]["total_sec"] == 12.0
    # the ass sidecar was generated beside the input
    assert (tmp_path / "clip-captions.ass").exists()


def test_burn_track_uses_custom_out_and_ass_path(fake_ffmpeg, tmp_path: Path):
    in_path = str(tmp_path / "clip.mp4")
    out_path = str(tmp_path / "final.mp4")
    ass_path = str(tmp_path / "cc.ass")
    run = _RunSpy(code=0)
    got = tracks.burn_track(
        in_path,
        _track(),
        out_path=out_path,
        ass_path=ass_path,
        run=run,
        duration=lambda *a, **k: 0.0,
    )
    assert got == out_path
    assert Path(ass_path).exists()
    assert run.argv[-1] == out_path


def test_burn_track_rebases_with_source_start(fake_ffmpeg, tmp_path: Path):
    in_path = str(tmp_path / "clip.mp4")
    ass_path = str(tmp_path / "cc.ass")
    track = _track(cues=[_cue(1, 100.0, 102.0, "rebased")])
    tracks.burn_track(
        in_path,
        track,
        ass_path=ass_path,
        source_start=100.0,
        run=_RunSpy(0),
        duration=lambda *a, **k: 0.0,
    )
    text = Path(ass_path).read_text(encoding="utf-8")
    assert "0:00:00.00,0:00:02.00" in text  # 100..102 -> local 0..2


def test_burn_track_raises_on_ffmpeg_failure(fake_ffmpeg, tmp_path: Path):
    in_path = str(tmp_path / "clip.mp4")
    with pytest.raises(TrackError):
        tracks.burn_track(
            in_path,
            _track(),
            run=_RunSpy(code=1),
            duration=lambda *a, **k: 0.0,
        )


def test_burn_track_forwards_progress_through_ctx(fake_ffmpeg, tmp_path: Path):
    in_path = str(tmp_path / "clip.mp4")
    seen: list[tuple] = []

    class Ctx:
        cancelled = False

        def progress(self, pct, msg=""):
            seen.append((pct, msg))

    tracks.burn_track(
        in_path,
        _track(),
        ass_path=str(tmp_path / "c.ass"),
        ctx=Ctx(),
        run=_RunSpy(code=0, drive_progress=True),
        duration=lambda *a, **k: 10.0,
    )
    assert (50.0, "50%") in seen
    assert (100.0, "done") in seen


def test_soft_mux_track_runs_and_tags_lang(fake_ffmpeg, tmp_path: Path):
    in_path = str(tmp_path / "v.mkv")
    run = _RunSpy(code=0)
    out = tracks.soft_mux_track(
        in_path,
        "/subs.srt",
        _track(lang="fr"),
        run=run,
        duration=lambda *a, **k: 5.0,
        sub_count=lambda *a, **k: 0,  # input carries no pre-existing subtitles
    )
    assert out.endswith("v-softsub.mkv")
    argv = run.argv
    assert argv[argv.index("-metadata:s:s:0") + 1] == "language=fr"
    assert argv.count("-i") == 2


def test_soft_mux_track_tags_new_stream_past_existing_subs(fake_ffmpeg, tmp_path: Path):
    """When the input already carries 2 subtitle streams, the lang tag must land
    on the NEW (3rd, index 2) stream — not the first pre-existing one."""
    run = _RunSpy(code=0)
    tracks.soft_mux_track(
        str(tmp_path / "v.mkv"),
        "/subs.srt",
        _track(lang="fr"),
        run=run,
        duration=lambda *a, **k: 5.0,
        sub_count=lambda *a, **k: 2,
    )
    argv = run.argv
    assert "-metadata:s:s:2" in argv
    assert argv[argv.index("-metadata:s:s:2") + 1] == "language=fr"
    # the old (wrong) stream-0 tag must NOT be emitted
    assert "-metadata:s:s:0" not in argv


def test_soft_mux_track_probe_failure_raises(fake_ffmpeg, tmp_path: Path):
    def boom_count(*_a, **_k):
        raise TrackError("subtitle-stream probe failed (ffprobe exit 3)")

    with pytest.raises(TrackError, match="probe failed"):
        tracks.soft_mux_track(
            str(tmp_path / "v.mkv"),
            "/s.srt",
            _track(lang="fr"),
            run=_RunSpy(code=0),
            duration=lambda *a, **k: 0.0,
            sub_count=boom_count,
        )


def test_soft_mux_track_raises_on_failure(fake_ffmpeg, tmp_path: Path):
    with pytest.raises(TrackError):
        tracks.soft_mux_track(
            str(tmp_path / "v.mkv"),
            "/s.srt",
            _track(),
            run=_RunSpy(code=2),
            duration=lambda *a, **k: 0.0,
            sub_count=lambda *a, **k: 0,
        )


def test_strip_track_runs_and_drops_stream(fake_ffmpeg, tmp_path: Path):
    in_path = str(tmp_path / "v.mkv")
    run = _RunSpy(code=0)
    out = tracks.strip_track(
        in_path,
        sub_stream_index=2,
        run=run,
        duration=lambda *a, **k: 7.0,
    )
    assert out.endswith("v-stripped.mkv")
    assert "-0:s:2" in run.argv


def test_strip_track_raises_on_failure(fake_ffmpeg, tmp_path: Path):
    with pytest.raises(TrackError):
        tracks.strip_track(
            str(tmp_path / "v.mkv"),
            run=_RunSpy(code=3),
            duration=lambda *a, **k: 0.0,
        )


def test_ops_survive_duration_probe_failure(fake_ffmpeg, tmp_path: Path):
    def boom(*a, **k):
        raise RuntimeError("probe exploded")

    run = _RunSpy(code=0)
    out = tracks.strip_track(str(tmp_path / "v.mkv"), run=run, duration=boom)
    assert out.endswith("v-stripped.mkv")
    assert run.calls[0]["total_sec"] == 0.0  # fell back to coarse progress


def test_strip_track_forwards_cancel_predicate(fake_ffmpeg, tmp_path: Path):
    run = _RunSpy(code=0)

    class Ctx:
        cancelled = True

        def progress(self, pct, msg=""):
            pass

    tracks.strip_track(
        str(tmp_path / "v.mkv"),
        ctx=Ctx(),
        run=run,
        duration=lambda *a, **k: 1.0,
    )
    should_cancel = run.calls[0]["should_cancel"]
    assert should_cancel is not None and should_cancel() is True


def test_no_op_passes_shell_true_anywhere(fake_ffmpeg, tmp_path: Path):
    """Defensive: none of the builders/ops ever produce a 'shell' token."""
    burn = tracks.build_burn_argv("/i.mp4", "/s.ass", "/o.mp4")
    soft = tracks.build_soft_mux_argv("/i.mp4", "/s.srt", "/o.mkv")
    strip = tracks.build_strip_argv("/i.mkv", "/o.mkv")
    for argv in (burn, soft, strip):
        assert isinstance(argv, list)
        assert all(isinstance(a, str) for a in argv)
        assert "shell" not in argv
