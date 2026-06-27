"""Unit tests for media_studio.features.reframe (the verthor adapter).

NO WSL, NO mediapipe, NO real verthor: the subprocess is injected via a fake
``runner`` and every assertion is on the *argv shape* the engine builds. The
central contract guarantee (CONTRACTS.md §4) is asserted explicitly:

  * the script is delivered FROM A FILE (an argv element after ``bash``), and
  * the script is NEVER piped via ``tr | bash`` over stdin.

The whole module is pure-logic + an injectable seam, so these tests pull in no
heavy-ML deps.
"""

from __future__ import annotations

import os

import pytest
from media_studio.features import reframe
from media_studio.features.reframe import ReframeEngine, ReframeError


# --------------------------------------------------------------------------- #
# fake subprocess runner
# --------------------------------------------------------------------------- #
class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_runner(returncode=0, stderr=""):
    """A subprocess.run stand-in that records every call."""
    calls = []

    def runner(argv, **kwargs):
        calls.append({"argv": argv, "kwargs": kwargs})
        return _Completed(returncode=returncode, stderr=stderr)

    runner.calls = calls
    return runner


# --------------------------------------------------------------------------- #
# aspect parsing / output dimensions
# --------------------------------------------------------------------------- #
def test_parse_aspect_colon_and_x():
    assert reframe._parse_aspect("9:16") == (9, 16)
    assert reframe._parse_aspect("9x16") == (9, 16)
    assert reframe._parse_aspect("  16:9 ") == (16, 9)


@pytest.mark.parametrize("bad", ["9", "9:16:1", "a:b", "0:16", "9:0", "-9:16", ""])
def test_parse_aspect_rejects_garbage(bad):
    with pytest.raises(ValueError):
        reframe._parse_aspect(bad)


def test_output_dimensions_default_9_16_is_1080x1920():
    # Contract pins the canonical vertical output exactly.
    assert reframe.output_dimensions("9:16") == (1080, 1920)
    assert reframe.output_dimensions() == (1080, 1920)
    assert (reframe.OUT_WIDTH, reframe.OUT_HEIGHT) == (1080, 1920)


def test_output_dimensions_other_portrait_ratio_fixes_height():
    # 3:4 portrait -> height 1920, width derived, both even.
    w, h = reframe.output_dimensions("3:4")
    assert h == 1920
    assert w == 1440
    assert w % 2 == 0 and h % 2 == 0


def test_output_dimensions_landscape_fixes_width_even():
    w, h = reframe.output_dimensions("16:9")
    assert w == 1920
    assert h % 2 == 0


# --------------------------------------------------------------------------- #
# Windows -> WSL path translation
# --------------------------------------------------------------------------- #
def test_to_wsl_path_windows_drive():
    assert reframe.to_wsl_path(r"C:\Users\me\v.mp4") == "/mnt/c/Users/me/v.mp4"
    assert reframe.to_wsl_path(r"D:\a b\out clip.mp4") == "/mnt/d/a b/out clip.mp4"


def test_to_wsl_path_preserves_spaces_unquoted():
    # Spaces are preserved verbatim; quoting is the argv layer's job.
    got = reframe.to_wsl_path(r"C:\My Videos\my talk.mov")
    assert got == "/mnt/c/My Videos/my talk.mov"
    assert '"' not in got and "'" not in got


def test_to_wsl_path_already_posix_unchanged():
    assert reframe.to_wsl_path("/mnt/c/x/y.mp4") == "/mnt/c/x/y.mp4"
    assert reframe.to_wsl_path("/opt/verthor/reframe.sh") == "/opt/verthor/reframe.sh"


def test_to_wsl_path_empty():
    assert reframe.to_wsl_path("") == ""


# --------------------------------------------------------------------------- #
# script resolution
# --------------------------------------------------------------------------- #
def test_resolve_script_default(monkeypatch):
    # Phase-0 fix: the default is the PACKAGED scripts/verthor_reframe.sh (as a
    # WSL /mnt path), not the old /opt/verthor placeholder that existed nowhere.
    monkeypatch.delenv("MEDIA_STUDIO_VERTHOR_SCRIPT", raising=False)
    got = reframe.resolve_script({})
    assert got.endswith("media_studio/scripts/verthor_reframe.sh")
    # On Windows the bundled drive path is translated to /mnt/<d>/...; on a POSIX
    # host the package path is already /-rooted and returned verbatim (no /mnt).
    if os.name == "nt":
        assert got.startswith("/mnt/")
    else:
        assert got.startswith("/")


def test_resolve_script_from_settings_translated_to_wsl(monkeypatch):
    monkeypatch.delenv("MEDIA_STUDIO_VERTHOR_SCRIPT", raising=False)
    got = reframe.resolve_script({"verthorScript": r"C:\tools\verthor\go.sh"})
    assert got == "/mnt/c/tools/verthor/go.sh"


def test_resolve_script_from_env(monkeypatch):
    monkeypatch.setenv("MEDIA_STUDIO_VERTHOR_SCRIPT", "/opt/custom/reframe.sh")
    assert reframe.resolve_script({}) == "/opt/custom/reframe.sh"


def test_resolve_script_settings_precedes_env(monkeypatch):
    monkeypatch.setenv("MEDIA_STUDIO_VERTHOR_SCRIPT", "/opt/env.sh")
    assert reframe.resolve_script({"verthorScript": "/opt/setting.sh"}) == "/opt/setting.sh"


# --------------------------------------------------------------------------- #
# argv builder — the core contract shape
# --------------------------------------------------------------------------- #
def test_build_reframe_argv_is_wsl_bash_script_from_file():
    argv = reframe.build_reframe_argv(
        r"C:\in\clip.mp4",
        r"C:\out\clip_9x16.mp4",
        "9:16",
        {"verthorScript": "/opt/verthor/reframe.sh"},
    )
    assert isinstance(argv, list)
    # wsl bash <script> ... — script is the THIRD element, read FROM A FILE.
    assert argv[0] == "wsl"
    assert argv[1] == "bash"
    assert argv[2] == "/opt/verthor/reframe.sh"
    # The script is a bare positional path: NOT bash -c, NOT a stdin string.
    assert "-c" not in argv


def test_build_reframe_argv_no_stdin_script_no_tr_bash_pipe():
    # The proven gotcha: NEVER `tr | bash`, NEVER pipe the script via stdin.
    argv = reframe.build_reframe_argv("/in.mp4", "/out.mp4", "9:16", {})
    joined = " ".join(argv)
    assert "tr " not in joined
    assert "|" not in joined  # no shell pipe anywhere in the argv
    assert "<" not in joined  # no stdin redirection
    # bash receives a FILE argument, not "-c" inline source.
    assert argv[1] == "bash"
    assert argv[2].endswith(".sh")
    assert "-c" not in argv


def test_build_reframe_argv_carries_paths_and_dimensions():
    argv = reframe.build_reframe_argv(
        r"C:\v in\a.mp4",
        r"C:\v out\b.mp4",
        "9:16",
        {"verthorScript": "/opt/verthor/reframe.sh"},
    )
    # translated WSL paths, kept as single argv elements (spaces intact)
    assert "/mnt/c/v in/a.mp4" in argv
    assert "/mnt/c/v out/b.mp4" in argv
    # aspect + the 1080x1920 target dimensions are passed through
    assert "9:16" in argv
    assert "1080" in argv
    assert "1920" in argv
    # dimensions appear as the trailing two args (w then h)
    assert argv[-2:] == ["1080", "1920"]


def test_build_reframe_argv_each_path_is_one_element():
    # A path with spaces must NOT be split across argv elements.
    argv = reframe.build_reframe_argv(
        r"C:\My Clips\talk one.mp4",
        r"C:\Out Dir\talk one v.mp4",
        "9:16",
        {},
    )
    assert "/mnt/c/My Clips/talk one.mp4" in argv
    assert "/mnt/c/Out Dir/talk one v.mp4" in argv


# --------------------------------------------------------------------------- #
# ReframeEngine.reframe — end to end with a fake runner
# --------------------------------------------------------------------------- #
def test_reframe_returns_out_path():
    runner = _make_runner(returncode=0)
    engine = ReframeEngine(
        settings={"verthorScript": "/opt/verthor/reframe.sh"},
        runner=runner,
    )
    out = engine.reframe(r"C:\in\clip.mp4", r"C:\out\clip.mp4", aspect="9:16")
    assert out == r"C:\out\clip.mp4"


def test_reframe_accepts_on_notice_for_seam_uniformity():
    # WU-3: the stage seam passes on_notice to whichever engine is resolved. The
    # verthor adapter runs subject tracking inside WSL (it cannot emit a
    # Python-side degrade notice), so it ACCEPTS on_notice and never calls it —
    # but the signature must match so _lazy_reframe can thread it uniformly.
    runner = _make_runner(returncode=0)
    engine = ReframeEngine(settings={"verthorScript": "/opt/verthor/reframe.sh"}, runner=runner)
    notices: list = []
    out = engine.reframe(r"C:\in\clip.mp4", r"C:\out\clip.mp4", on_notice=notices.append)
    assert out == r"C:\out\clip.mp4"
    assert notices == []


def test_reframe_invokes_runner_with_argv_list_no_shell():
    runner = _make_runner(returncode=0)
    engine = ReframeEngine(
        settings={"verthorScript": "/opt/verthor/reframe.sh"},
        runner=runner,
    )
    engine.reframe(r"C:\in\clip.mp4", r"C:\out\clip.mp4")

    assert len(runner.calls) == 1
    call = runner.calls[0]
    argv = call["argv"]
    # argv MUST be a list (never a shell string), and shell is not enabled.
    assert isinstance(argv, list)
    assert call["kwargs"].get("shell") in (None, False)


def test_reframe_call_is_from_file_not_stdin_script():
    # Central assertion the unit exists to guarantee.
    runner = _make_runner(returncode=0)
    engine = ReframeEngine(
        settings={"verthorScript": "/opt/verthor/reframe.sh"},
        runner=runner,
    )
    engine.reframe(r"C:\in\clip.mp4", r"C:\out\clip.mp4")

    argv = runner.calls[0]["argv"]
    # 1) script is read FROM A FILE: wsl bash <script-path> ...
    assert argv[:3] == ["wsl", "bash", "/opt/verthor/reframe.sh"]
    # 2) no inline source / no stdin script delivery
    assert "-c" not in argv
    joined = " ".join(argv)
    assert "tr " not in joined and "|" not in joined and "<" not in joined
    # 3) nothing was written to the subprocess stdin (no input= / stdin= piping)
    kwargs = runner.calls[0]["kwargs"]
    assert "input" not in kwargs
    assert kwargs.get("stdin") in (None,)


def test_reframe_targets_1080x1920_h264_dimensions():
    runner = _make_runner(returncode=0)
    engine = ReframeEngine(
        settings={"verthorScript": "/opt/verthor/reframe.sh"},
        runner=runner,
    )
    engine.reframe(r"C:\in\clip.mp4", r"C:\out\clip.mp4", aspect="9:16")

    argv = runner.calls[0]["argv"]
    # 1080x1920 vertical target is handed to the verthor script.
    assert "1080" in argv and "1920" in argv
    assert argv[-2:] == ["1080", "1920"]


def test_reframe_translates_windows_paths_to_wsl():
    runner = _make_runner(returncode=0)
    engine = ReframeEngine(
        settings={"verthorScript": "/opt/verthor/reframe.sh"},
        runner=runner,
    )
    engine.reframe(r"C:\My Vids\in clip.mp4", r"D:\out\done.mp4")

    argv = runner.calls[0]["argv"]
    assert "/mnt/c/My Vids/in clip.mp4" in argv
    assert "/mnt/d/out/done.mp4" in argv


def test_reframe_raises_on_nonzero_exit():
    runner = _make_runner(returncode=2, stderr="mediapipe: boom")
    engine = ReframeEngine(
        settings={"verthorScript": "/opt/verthor/reframe.sh"},
        runner=runner,
    )
    with pytest.raises(ReframeError) as exc:
        engine.reframe(r"C:\in\clip.mp4", r"C:\out\clip.mp4")
    assert "exit 2" in str(exc.value)
    assert "mediapipe: boom" in str(exc.value)


def test_reframe_default_aspect_is_9_16():
    runner = _make_runner(returncode=0)
    engine = ReframeEngine(
        settings={"verthorScript": "/opt/verthor/reframe.sh"},
        runner=runner,
    )
    engine.reframe(r"C:\in\clip.mp4", r"C:\out\clip.mp4")  # no aspect arg
    argv = runner.calls[0]["argv"]
    assert "9:16" in argv
    assert argv[-2:] == ["1080", "1920"]


def test_reframe_uses_subprocess_run_by_default(monkeypatch):
    # Without injection the engine wires to subprocess.run (we stub it so no
    # real wsl is spawned), and still returns out_path on success.
    recorded = {}

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        recorded["kwargs"] = kwargs
        return _Completed(returncode=0)

    monkeypatch.setattr(reframe.subprocess, "run", fake_run)
    engine = ReframeEngine(settings={"verthorScript": "/opt/verthor/reframe.sh"})
    out = engine.reframe("/in.mp4", "/out.mp4")
    assert out == "/out.mp4"
    assert recorded["argv"][0] == "wsl"
    assert recorded["kwargs"].get("shell") in (None, False)


# --------------------------------------------------------------------------- #
# to_wsl_path — the relative (drive-less) path branch
# --------------------------------------------------------------------------- #
def test_to_wsl_path_relative_no_drive_is_slash_normalized():
    # A relative Windows path (no drive letter, not already POSIX) is just
    # slash-normalized to a POSIX relative path — never gets a /mnt prefix.
    assert reframe.to_wsl_path(r"clips\a b\v.mp4") == "clips/a b/v.mp4"
    assert reframe.to_wsl_path("just_a_name.mp4") == "just_a_name.mp4"


# --------------------------------------------------------------------------- #
# ReframeEngine.reframe — defensive non-list argv guard
# --------------------------------------------------------------------------- #
def test_reframe_raises_typeerror_when_argv_not_a_list(monkeypatch):
    # Defensive guard (§4: never a shell string): if argv construction ever
    # yields a non-list, reframe refuses to invoke the runner.
    monkeypatch.setattr(reframe, "build_reframe_argv", lambda *a, **k: "wsl bash script.sh")
    engine = ReframeEngine(settings={"verthorScript": "/opt/verthor/reframe.sh"}, runner=_make_runner())
    with pytest.raises(TypeError, match="must be a list"):
        engine.reframe("/in.mp4", "/out.mp4")
