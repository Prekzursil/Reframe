"""Unit tests for media_studio.features.caption (CaptionEngine).

Heavy-ML-free: no faster-whisper / scenedetect / verthor imports. ffmpeg is
mocked at the seam — binary resolution is monkeypatched and the runner is
injected, so no real ffmpeg is spawned and no binary needs to exist.

Focus areas mandated by CONTRACTS.md section 4 / the unit brief:
  * the t != 0 re-base (a clip starting at source t != 0 must be corrected)
  * a malicious override cue like ``{\\fake}`` is escaped (no ASS injection)
  * argv-list subprocess only (never shell=True)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import caption
from media_studio.features.caption import (
    CaptionEngine,
    CaptionError,
    build_ass,
    build_burn_argv,
    build_softmux_argv,
    escape_ass_text,
    format_ass_timestamp,
    rebase_cue_time,
    render_cue_text,
    wrap_hook_title,
)


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
def cue(index: int, start: float, end: float, text: str) -> dict[str, Any]:
    """Build a contract-shaped Cue dict {index,start,end,text}."""
    return {"index": index, "start": start, "end": end, "text": text}


@pytest.fixture()
def fake_ffmpeg(monkeypatch, tmp_path: Path):
    """Make ffmpeg.ffmpeg_path resolve to a fake binary (no real ffmpeg)."""
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda settings=None: str(fake))
    return str(fake)


class RecordingRunner:
    """Stand-in for ffmpeg.run: records argv, returns a fixed exit code."""

    def __init__(self, code: int = 0):
        self.code = code
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv, total_sec=0.0, on_progress=None, should_cancel=None):
        # capture everything we care about asserting on
        self.calls.append(
            {
                "argv": list(argv),
                "total_sec": total_sec,
                "on_progress": on_progress,
                "should_cancel": should_cancel,
            }
        )
        return self.code


# --------------------------------------------------------------------------- #
# escape_ass_text — the injection defence
# --------------------------------------------------------------------------- #
def test_escape_neutralises_override_braces():
    # The classic ASS override-injection payload from the brief.
    out = escape_ass_text(r"{\fake}")
    assert "{" not in out.replace(r"\{", "")  # no UNescaped opening brace
    assert "}" not in out.replace(r"\}", "")  # no UNescaped closing brace
    assert out == r"\{\\fake\}"


def test_escape_braces_alignment_override_injection():
    # An attacker trying to reposition/blank the text via {\an8}{\alpha&HFF&}.
    out = escape_ass_text(r"{\an8}hi{\alpha&HFF&}")
    assert r"\{" in out and r"\}" in out
    # No raw "{\" sequence survives that libass would treat as an override.
    assert "{\\an8}" not in out
    assert "{\\alpha" not in out


def test_escape_backslash_doubled_first():
    # A lone backslash would start an override (e.g. \b1). It must be doubled,
    # and braces escaped AFTER so we don't double our own escape backslashes.
    assert escape_ass_text("a\\b") == "a\\\\b"
    # combined: backslash then brace
    assert escape_ass_text("\\{") == "\\\\\\{"


def test_escape_newlines_become_ass_hard_breaks():
    assert escape_ass_text("line1\nline2") == r"line1\Nline2"
    assert escape_ass_text("a\r\nb") == r"a\Nb"
    assert escape_ass_text("a\rb") == r"a\Nb"


def test_escape_plain_text_untouched():
    assert escape_ass_text("Hello, world!") == "Hello, world!"


def test_escape_none_and_non_str():
    assert escape_ass_text(None) == ""  # type: ignore[arg-type]
    assert escape_ass_text(123) == "123"  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# format_ass_timestamp
# --------------------------------------------------------------------------- #
def test_timestamp_basic():
    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_ass_timestamp(1.5) == "0:00:01.50"
    assert format_ass_timestamp(61.23) == "0:01:01.23"
    assert format_ass_timestamp(3661.04) == "1:01:01.04"


def test_timestamp_centisecond_rounding():
    # 1.239s rounds to 1.24s (centisecond precision)
    assert format_ass_timestamp(1.239) == "0:00:01.24"
    # carry across the centisecond boundary
    assert format_ass_timestamp(1.999) == "0:00:02.00"


def test_timestamp_negative_clamped():
    assert format_ass_timestamp(-5.0) == "0:00:00.00"
    assert format_ass_timestamp(None) == "0:00:00.00"  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# rebase_cue_time
# --------------------------------------------------------------------------- #
def test_rebase_subtracts_source_start():
    assert rebase_cue_time(125.0, 120.0) == pytest.approx(5.0)


def test_rebase_clamps_below_zero():
    # A cue starting before the clip's in-point pins to the clip start.
    assert rebase_cue_time(118.0, 120.0) == 0.0


def test_rebase_zero_offset_is_identity():
    assert rebase_cue_time(7.5, 0.0) == pytest.approx(7.5)


# --------------------------------------------------------------------------- #
# build_ass — sizing + the t != 0 re-base + escaping
# --------------------------------------------------------------------------- #
def test_build_ass_sets_playres_to_width_height():
    doc = build_ass([], width=720, height=1280)
    assert "PlayResX: 720" in doc
    assert "PlayResY: 1280" in doc


def test_build_ass_default_is_vertical_short():
    doc = build_ass([])
    assert "PlayResX: 1080" in doc
    assert "PlayResY: 1920" in doc


def test_build_ass_has_required_sections():
    doc = build_ass([cue(1, 0.0, 1.0, "hi")])
    assert "[Script Info]" in doc
    assert "[V4+ Styles]" in doc
    assert "[Events]" in doc
    assert doc.startswith("[Script Info]")


def test_build_ass_rebases_nonzero_source_start():
    """⭐ The t != 0 re-base: a clip cut from source t=120 must show its first
    caption at clip-local t=0, not t=120 (which would never display)."""
    cues = [
        cue(1, 120.0, 122.0, "first"),  # -> 0.00 .. 2.00 after rebase
        cue(2, 125.5, 128.0, "second"),  # -> 5.50 .. 8.00 after rebase
    ]
    doc = build_ass(cues, width=1080, height=1920, source_start=120.0)
    # first cue is re-based to clip-local zero, NOT left at 0:02:00
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,first" in doc
    assert "Dialogue: 0,0:00:05.50,0:00:08.00,Default,,0,0,0,,second" in doc
    # the un-rebased (wrong) timestamp must NOT appear anywhere
    assert "0:02:00.00" not in doc
    assert "0:02:05.50" not in doc


def test_build_ass_zero_offset_keeps_absolute_times():
    doc = build_ass([cue(1, 3.0, 4.0, "x")], source_start=0.0)
    assert "Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,x" in doc


def test_build_ass_skips_cue_entirely_before_clip():
    """A cue that ends at/before the clip in-point can never display -> skipped."""
    cues = [
        cue(1, 100.0, 110.0, "before"),  # ends at 110, in-point 120 -> skip
        cue(2, 121.0, 123.0, "kept"),
    ]
    doc = build_ass(cues, source_start=120.0)
    assert "before" not in doc
    assert "kept" in doc


def test_build_ass_skips_zero_length_after_rebase():
    # start==end after rebase -> end <= start -> skipped
    doc = build_ass([cue(1, 5.0, 5.0, "zero")], source_start=0.0)
    assert "zero" not in doc


def test_build_ass_escapes_malicious_override_cue():
    """⭐ A malicious cue {\\fake} must be escaped in the generated ASS so libass
    renders it literally instead of executing it as an override."""
    doc = build_ass([cue(1, 0.0, 2.0, r"{\fake}")], source_start=0.0)
    # The raw injection sequence "{\fake}" must NOT appear unescaped.
    assert r"{\fake}" not in doc
    # The escaped form is present on the Dialogue line.
    assert r"\{\\fake\}" in doc


def test_build_ass_multiline_cue_uses_hard_break():
    doc = build_ass([cue(1, 0.0, 2.0, "top\nbottom")], source_start=0.0)
    assert r"top\Nbottom" in doc


def test_build_ass_trailing_newline():
    doc = build_ass([cue(1, 0.0, 1.0, "x")])
    assert doc.endswith("\n")


def test_build_ass_missing_text_field_tolerated():
    # Cue without a 'text' key should not crash (defaults to empty).
    doc = build_ass([{"index": 1, "start": 0.0, "end": 1.0}], source_start=0.0)
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,," in doc


# --------------------------------------------------------------------------- #
# P4 §8a: render_cue_text — emphasis bolding + trailing emoji (libass path)
# --------------------------------------------------------------------------- #
def test_render_cue_text_plain_equals_escape():
    # No annotation -> byte-identical to the pre-§8a escaped text.
    c = {"index": 1, "start": 0.0, "end": 1.0, "text": r"{\fake} hi"}
    assert render_cue_text(c) == escape_ass_text(r"{\fake} hi")


def test_render_cue_text_bolds_emphasis_span():
    c = {
        "index": 1,
        "start": 0.0,
        "end": 1.0,
        "text": "FREE money",
        "emphasis": [{"start": 0, "end": 4, "kind": "caps"}],
    }
    out = render_cue_text(c)
    # the emphasised word is wrapped in bold-on/bold-off override codes
    assert r"{\b1}FREE{\b0}" in out
    assert out.endswith(" money")


def test_render_cue_text_appends_trailing_emoji():
    c = {"index": 1, "start": 0.0, "end": 1.0, "text": "win", "emoji": "\U0001f3c6"}
    out = render_cue_text(c)
    assert out == "win \U0001f3c6"


def test_render_cue_text_skips_overlapping_and_out_of_range_spans():
    c = {
        "index": 1,
        "start": 0.0,
        "end": 1.0,
        "text": "abcdef",
        "emphasis": [
            {"start": 0, "end": 3, "kind": "k"},  # kept
            {"start": 2, "end": 5, "kind": "k"},  # overlaps -> skipped
            {"start": 4, "end": 99, "kind": "k"},  # clamped to 6, kept
        ],
    }
    out = render_cue_text(c)
    assert out == r"{\b1}abc{\b0}d{\b1}ef{\b0}"


def test_build_ass_emits_emphasis_and_emoji_in_dialogue():
    doc = build_ass(
        [
            {
                "index": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "huge WIN",
                "emphasis": [{"start": 5, "end": 8, "kind": "caps"}],
                "emoji": "\U0001f525",
            }
        ],
        source_start=0.0,
    )
    assert r"{\b1}WIN{\b0}" in doc
    assert "\U0001f525" in doc


# --------------------------------------------------------------------------- #
# argv builders — argv list, no shell, paths with spaces
# --------------------------------------------------------------------------- #
def test_build_burn_argv_is_list_and_uses_subtitles_filter(fake_ffmpeg):
    argv = build_burn_argv("/a b/clip.mp4", "/tmp/x y.ass", "/out/o.mp4")
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)
    # input + output preserved as single argv elements (spaces intact)
    assert "-i" in argv and argv[argv.index("-i") + 1] == "/a b/clip.mp4"
    assert argv[-1] == "/out/o.mp4"
    # libass burn-in via the subtitles filter
    assert "-vf" in argv
    vf = argv[argv.index("-vf") + 1]
    assert vf.startswith("subtitles=")
    assert "x y.ass" in vf  # the ass path is embedded
    # audio stream-copied, progress wired, overwrite
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "copy"
    assert "-progress" in argv and argv[argv.index("-progress") + 1] == "pipe:1"
    assert "-y" in argv


def test_build_burn_argv_escapes_windows_path(fake_ffmpeg):
    argv = build_burn_argv("clip.mp4", r"C:\Temp\sub.ass", "out.mp4")
    vf = argv[argv.index("-vf") + 1]
    # drive colon and backslashes escaped inside the filter, wrapped in quotes
    assert "subtitles='" in vf
    assert r"\:" in vf  # colon escaped
    assert r"\\" in vf  # backslash escaped


def test_build_softmux_argv_mp4_uses_mov_text(fake_ffmpeg):
    argv = build_softmux_argv("/in.mp4", "/s.ass", "/out.mp4")
    assert isinstance(argv, list)
    # two inputs: the video and the subtitle file
    assert argv.count("-i") == 2
    # subtitle codec is mov_text for mp4 containers
    assert "-c:s" in argv and argv[argv.index("-c:s") + 1] == "mov_text"
    # video + audio stream-copied (soft-mux, not re-encode)
    assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "copy"
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "copy"
    assert argv[-1] == "/out.mp4"


def test_build_softmux_argv_mkv_keeps_native_ass(fake_ffmpeg):
    argv = build_softmux_argv("/in.mkv", "/s.ass", "/out.mkv")
    assert "-c:s" in argv and argv[argv.index("-c:s") + 1] == "ass"


# --------------------------------------------------------------------------- #
# CaptionEngine.render — end-to-end with a fake runner (no real ffmpeg)
# --------------------------------------------------------------------------- #
def test_render_returns_out_path_and_burns_by_default(fake_ffmpeg):
    runner = RecordingRunner(code=0)
    eng = CaptionEngine(runner=runner)
    cues = [cue(1, 120.0, 122.0, "hello")]
    out = eng.render("/in.mp4", cues, "/out.mp4", source_start=120.0)
    assert out == "/out.mp4"
    assert len(runner.calls) == 1
    argv = runner.calls[0]["argv"]
    # default burn=True -> subtitles filter present
    assert "-vf" in argv and argv[argv.index("-vf") + 1].startswith("subtitles=")


def test_render_no_shell_true_anywhere(fake_ffmpeg):
    """argv-list subprocess only: the engine must hand a list to the runner and
    never a shell string / shell=True."""
    captured: dict[str, Any] = {}

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        captured["argv"] = argv
        # a shell string would be a str, not a list — assert it is a list
        assert isinstance(argv, list)
        assert not isinstance(argv, str)
        return 0

    eng = CaptionEngine(runner=runner)
    eng.render("/in.mp4", [cue(1, 0.0, 1.0, "x")], "/out.mp4")
    assert isinstance(captured["argv"], list)


def test_render_softmux_when_burn_false(fake_ffmpeg):
    runner = RecordingRunner(code=0)
    eng = CaptionEngine(runner=runner)
    eng.render("/in.mp4", [cue(1, 0.0, 1.0, "x")], "/out.mp4", burn=False)
    argv = runner.calls[0]["argv"]
    # soft-mux path: two inputs, subtitle codec, no subtitles filter
    assert argv.count("-i") == 2
    assert "-c:s" in argv
    assert "-vf" not in argv


def test_render_rebases_inside_written_ass(fake_ffmpeg, monkeypatch):
    """The ASS actually written to disk (and fed to ffmpeg) carries re-based
    times — proves render() threads source_start through to build_ass."""
    written: dict[str, str] = {}
    real_mkstemp = caption.tempfile.mkstemp

    def spy_mkstemp(*a, **k):
        fd, path = real_mkstemp(*a, **k)
        written["path"] = path
        return fd, path

    monkeypatch.setattr(caption.tempfile, "mkstemp", spy_mkstemp)

    captured_doc: dict[str, str] = {}

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        # read the ASS file ffmpeg would consume (last argv before output for
        # burn is inside -vf; we read the temp path directly)
        with open(written["path"], encoding="utf-8") as fh:
            captured_doc["ass"] = fh.read()
        return 0

    eng = CaptionEngine(runner=runner)
    eng.render("/in.mp4", [cue(1, 130.0, 132.0, "late")], "/out.mp4", source_start=130.0)
    assert "0:00:00.00,0:00:02.00,Default,,0,0,0,,late" in captured_doc["ass"]


def test_render_cleans_up_temp_ass(fake_ffmpeg):
    paths: list[str] = []

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        return 0

    import media_studio.features.caption as capmod

    orig = capmod.tempfile.mkstemp

    def spy(*a, **k):
        fd, path = orig(*a, **k)
        paths.append(path)
        return fd, path

    capmod.tempfile.mkstemp = spy  # type: ignore[assignment]
    try:
        eng = CaptionEngine(runner=runner)
        eng.render("/in.mp4", [cue(1, 0.0, 1.0, "x")], "/out.mp4")
    finally:
        capmod.tempfile.mkstemp = orig  # type: ignore[assignment]
    assert paths, "a temp ass file should have been created"
    assert not os.path.exists(paths[0]), "temp ass must be cleaned up after render"


def test_render_cleans_up_temp_even_on_error(fake_ffmpeg):
    paths: list[str] = []
    import media_studio.features.caption as capmod

    orig = capmod.tempfile.mkstemp

    def spy(*a, **k):
        fd, path = orig(*a, **k)
        paths.append(path)
        return fd, path

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        return 1  # non-zero -> CaptionError

    capmod.tempfile.mkstemp = spy  # type: ignore[assignment]
    try:
        eng = CaptionEngine(runner=runner)
        with pytest.raises(CaptionError):
            eng.render("/in.mp4", [cue(1, 0.0, 1.0, "x")], "/out.mp4")
    finally:
        capmod.tempfile.mkstemp = orig  # type: ignore[assignment]
    assert not os.path.exists(paths[0]), "temp ass cleaned up even when ffmpeg fails"


def test_render_raises_caption_error_on_nonzero_exit(fake_ffmpeg):
    runner = RecordingRunner(code=2)
    eng = CaptionEngine(runner=runner)
    with pytest.raises(CaptionError) as exc:
        eng.render("/in.mp4", [cue(1, 0.0, 1.0, "x")], "/out.mp4")
    assert "exit 2" in str(exc.value)


def test_render_threads_progress_and_cancel_to_runner(fake_ffmpeg):
    runner = RecordingRunner(code=0)
    eng = CaptionEngine(runner=runner)

    def progress_cb(pct, msg):
        return None

    def cancel_cb():
        return False

    eng.render(
        "/in.mp4",
        [cue(1, 0.0, 1.0, "x")],
        "/out.mp4",
        on_progress=progress_cb,
        should_cancel=cancel_cb,
        total_sec=12.0,
    )
    call = runner.calls[0]
    assert call["on_progress"] is progress_cb
    assert call["should_cancel"] is cancel_cb
    assert call["total_sec"] == 12.0


def test_render_uses_width_height_in_ass(fake_ffmpeg, monkeypatch):
    captured: dict[str, str] = {}
    import media_studio.features.caption as capmod

    orig = capmod.tempfile.mkstemp

    def spy(*a, **k):
        fd, path = orig(*a, **k)
        captured["path"] = path
        return fd, path

    monkeypatch.setattr(capmod.tempfile, "mkstemp", spy)

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        with open(captured["path"], encoding="utf-8") as fh:
            captured["doc"] = fh.read()
        return 0

    eng = CaptionEngine(runner=runner)
    eng.render("/in.mp4", [cue(1, 0.0, 1.0, "x")], "/out.mp4", width=720, height=1280)
    assert "PlayResX: 720" in captured["doc"]
    assert "PlayResY: 1280" in captured["doc"]


def test_engine_build_ass_method_matches_module_fn(fake_ffmpeg):
    eng = CaptionEngine()
    cues = [cue(1, 5.0, 6.0, "hi")]
    assert eng.build_ass(cues, width=640, height=480, source_start=1.0) == build_ass(
        cues, width=640, height=480, source_start=1.0
    )


# --------------------------------------------------------------------------- #
# P3-A hook-title overlay — top-anchored headline style + event + escaping
# --------------------------------------------------------------------------- #
def test_wrap_hook_title_escapes_and_wraps_two_lines():
    # A long hook wraps onto <= 2 lines joined by the ASS hard break.
    wrapped = wrap_hook_title("one two three four five six")
    assert wrapped.count(r"\N") == 1  # exactly one break -> two lines
    assert "one" in wrapped and "six" in wrapped


def test_wrap_hook_title_escapes_override_injection():
    # The hook is user-ish data: a brace-override payload must be neutralised.
    wrapped = wrap_hook_title(r"{\an8}gotcha")
    assert r"{\an8}" not in wrapped
    assert r"\{" in wrapped and r"\}" in wrapped


def test_wrap_hook_title_blank_is_empty():
    assert wrap_hook_title("") == ""
    assert wrap_hook_title("   ") == ""
    assert wrap_hook_title(None) == ""  # type: ignore[arg-type]


def test_wrap_hook_title_exits_loop_naturally_when_chunks_below_max_lines():
    # 5 words with max_lines=4 -> per_line=ceil(5/4)=2 -> 3 chunks (< max_lines),
    # so the pack loop exhausts naturally without ever hitting the max_lines break
    # (covers the for->return arc). `rest` stays empty throughout.
    wrapped = wrap_hook_title("one two three four five", max_lines=4)
    assert wrapped == r"one two\Nthree four\Nfive"
    assert wrapped.count(r"\N") == 2  # three lines


def test_build_ass_no_title_when_hook_absent():
    """Default (no hook_title) ASS has NO HookTitle style/event — byte-identical
    to the pre-P3 document."""
    doc = build_ass([cue(1, 0.0, 1.0, "hi")])
    assert "HookTitle" not in doc
    assert doc == build_ass([cue(1, 0.0, 1.0, "hi")], hook_title=None)


def test_build_ass_emits_top_anchored_title_style_and_event():
    doc = build_ass(
        [cue(1, 0.0, 1.0, "body")],
        source_start=0.0,
        hook_title="The big hook",
        total_sec=30.0,
    )
    # A dedicated HookTitle style appears in [V4+ Styles] with top alignment (8).
    assert "Style: HookTitle," in doc
    style_line = next(line for line in doc.splitlines() if line.startswith("Style: HookTitle,"))
    # Alignment is the 5th-from-last field group; assert top-anchor 8 + bold (-1).
    assert ",8," in style_line  # alignment 8 = top-centre
    assert style_line.split(",")[7] == "-1"  # Bold
    # A HookTitle Dialogue event renders for the whole clip (0 -> total_sec).
    title_event = next(line for line in doc.splitlines() if line.startswith("Dialogue:") and "HookTitle" in line)
    assert "0:00:00.00" in title_event
    assert "0:00:30.00" in title_event
    # Short hook (<=4 words) stays on a single line.
    assert "The big hook" in title_event


def test_build_ass_title_event_precedes_body_captions():
    doc = build_ass([cue(1, 0.0, 2.0, "bodytext")], hook_title="HOOK", total_sec=10.0)
    lines = [line for line in doc.splitlines() if line.startswith("Dialogue:")]
    # The title draws first (above), then the body cue.
    assert "HookTitle" in lines[0]
    assert "bodytext" in lines[1]


def test_build_ass_title_escaped_in_event():
    doc = build_ass([], hook_title=r"{\fake} hook", total_sec=5.0)
    assert r"{\fake}" not in doc  # raw injection neutralised
    assert r"\{\\fake\}" in doc  # escaped form present


def test_build_ass_title_duration_falls_back_to_last_cue():
    # No total_sec: the title spans at least to the last (re-based) cue end.
    doc = build_ass([cue(1, 100.0, 108.0, "x")], source_start=100.0, hook_title="H")
    title_event = next(line for line in doc.splitlines() if line.startswith("Dialogue:") and "HookTitle" in line)
    # last cue ends clip-local at 8.0; the 60s floor governs -> 0:01:00.00.
    assert "0:01:00.00" in title_event


def test_render_threads_hook_title_into_written_ass(fake_ffmpeg, monkeypatch):
    """render() forwards hook_title into the ASS actually written to disk."""
    written: dict[str, str] = {}
    orig = caption.tempfile.mkstemp

    def spy(*a, **k):
        fd, path = orig(*a, **k)
        written["path"] = path
        return fd, path

    monkeypatch.setattr(caption.tempfile, "mkstemp", spy)

    captured: dict[str, str] = {}

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None):
        with open(written["path"], encoding="utf-8") as fh:
            captured["ass"] = fh.read()
        return 0

    eng = CaptionEngine(runner=runner)
    eng.render("/in.mp4", [cue(1, 0.0, 1.0, "body")], "/out.mp4", hook_title="My Hook")
    assert "HookTitle" in captured["ass"]
    assert "My Hook" in captured["ass"]
