"""Handler tests for ``subtitles.import`` — the v1.5 hand-corrected-SRT escape hatch.

Closes the gap measured in ``docs/plans/v1.5/captions-translation-audit-2026-08.md``
§5.1: the PARSERS (``read_srt`` / ``read_vtt`` / ``read_ass``) were complete and
tested, but had **no production caller** — every hit outside ``subtitles.py`` was a
test, so a user with a hand-corrected ``.srt`` could not bring it back in.

Wire shape: ``subtitles.import({videoId, text, format, name?, lang?}) -> {track}``.
The renderer reads the picked file's TEXT with the standard File API and sends the
text — NOT a path. That keeps the sidecar off the renderer-supplied filesystem
entirely (no traversal surface) and needs no new Electron dialog/preload channel.

Seam style mirrors ``test_handlers_captions_export.py``: a tmp-dir ``Services``
with stub ffmpeg/whisper seams, so no subprocess / heavy dep is touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import library as _library
from media_studio.handlers import Services
from media_studio.protocol import ErrorCode, RpcContext, RpcError

SRT_TEXT = "1\n00:00:00,000 --> 00:00:02,000\nHand corrected\n\n2\n00:00:02,000 --> 00:00:04,000\nSecond line\n"


def fake_run(*_a: Any, **_k: Any) -> int:
    return 0


def fake_probe(*_a: Any, **_k: Any) -> float:
    return 12.0


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "talk.mp4"
    p.write_bytes(b"\x00fake")
    return p


@pytest.fixture
def services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", ffmpeg_run=fake_run, ffprobe_duration=fake_probe)


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _add_video(services: Services, video_file: Path) -> str:
    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    return services.library.add(str(video_file))["id"]


# --------------------------------------------------------------------------- #
# happy path — the parser finally has a production caller
# --------------------------------------------------------------------------- #
def test_import_srt_returns_a_track_with_the_parsed_cues(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    res = services.subtitles_import({"videoId": vid, "text": SRT_TEXT, "format": "srt"}, ctx)
    track = res["track"]
    assert [c["text"] for c in track["cues"]] == ["Hand corrected", "Second line"]
    assert [c["index"] for c in track["cues"]] == [1, 2]
    assert track["cues"][0]["start"] == 0.0
    assert track["cues"][1]["end"] == 4.0
    assert track["format"] == "srt"
    assert track["kind"] == "soft"


def test_import_persists_the_track_onto_the_project(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    imported = services.subtitles_import({"videoId": vid, "text": SRT_TEXT, "format": "srt"}, ctx)["track"]
    # Re-open from disk: the import must SURVIVE, or "bring my SRT back in" is a lie.
    reopened = services._load_or_create_project(vid)
    ids = [t["id"] for t in reopened.data["tracks"]]
    assert imported["id"] in ids


def test_import_honours_name_and_lang_and_defaults_them(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    named = services.subtitles_import(
        {"videoId": vid, "text": SRT_TEXT, "format": "srt", "name": "my-fixes.srt", "lang": "ro"}, ctx
    )["track"]
    assert named["name"] == "my-fixes.srt"
    assert named["lang"] == "ro"
    defaulted = services.subtitles_import({"videoId": vid, "text": SRT_TEXT, "format": "srt"}, ctx)["track"]
    assert defaulted["name"] == "Imported subtitles"
    assert defaulted["lang"] == "und"


def test_import_vtt_and_ass_round_trip_through_the_same_handler(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    vid = _add_video(services, video_file)
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nFrom VTT\n"
    ass_text = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,From ASS\n"
    )
    assert services.subtitles_import({"videoId": vid, "text": vtt, "format": "vtt"}, ctx)["track"]["cues"][0][
        "text"
    ] == ("From VTT")
    assert services.subtitles_import({"videoId": vid, "text": ass_text, "format": "ass"}, ctx)["track"]["cues"][
        0
    ]["text"] == ("From ASS")


def test_import_normalizes_the_format_string(services: Services, ctx: RpcContext, video_file: Path) -> None:
    """A picker hands us the raw extension: '.SRT'. 'ssa' is an alias of 'ass'."""
    vid = _add_video(services, video_file)
    track = services.subtitles_import({"videoId": vid, "text": SRT_TEXT, "format": ".SRT"}, ctx)["track"]
    assert track["format"] == "srt"
    ssa = "[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hi\n"
    assert services.subtitles_import({"videoId": vid, "text": ssa, "format": "ssa"}, ctx)["track"]["format"] == (
        "ass"
    )


def test_import_tolerates_crlf_and_bom_and_missing_indices(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    """The engine's tolerance must reach the wire — a Windows-authored SRT is the norm."""
    vid = _add_video(services, video_file)
    raw = "﻿00:00:00,000 --> 00:00:01,000\r\nNo index, CRLF, BOM\r\n"
    track = services.subtitles_import({"videoId": vid, "text": raw, "format": "srt"}, ctx)["track"]
    assert [c["text"] for c in track["cues"]] == ["No index, CRLF, BOM"]


# --------------------------------------------------------------------------- #
# rejection paths — typed INVALID_PARAMS, never a deep crash
# --------------------------------------------------------------------------- #
def test_import_requires_video_id(services: Services, ctx: RpcContext) -> None:
    with pytest.raises(RpcError) as exc:
        services.subtitles_import({"text": SRT_TEXT, "format": "srt"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


@pytest.mark.parametrize("bad", [None, "", "   \n  ", 123, ["nope"]])
def test_import_rejects_missing_or_blank_text(
    services: Services, ctx: RpcContext, video_file: Path, bad: Any
) -> None:
    vid = _add_video(services, video_file)
    with pytest.raises(RpcError) as exc:
        services.subtitles_import({"videoId": vid, "text": bad, "format": "srt"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS


def test_import_rejects_an_unsupported_format(services: Services, ctx: RpcContext, video_file: Path) -> None:
    vid = _add_video(services, video_file)
    with pytest.raises(RpcError) as exc:
        services.subtitles_import({"videoId": vid, "text": SRT_TEXT, "format": "docx"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS
    assert "docx" in str(exc.value)


def test_import_rejects_text_that_parses_to_zero_cues(
    services: Services, ctx: RpcContext, video_file: Path
) -> None:
    """Silently adding an EMPTY track would look like success and lose the user's file."""
    vid = _add_video(services, video_file)
    with pytest.raises(RpcError) as exc:
        services.subtitles_import({"videoId": vid, "text": "this is not a subtitle file", "format": "srt"}, ctx)
    assert exc.value.code == ErrorCode.INVALID_PARAMS
    # The project must be left untouched — no half-imported empty track.
    assert services._load_or_create_project(vid).data.get("tracks") in ([], None)
