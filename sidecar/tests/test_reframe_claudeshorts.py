"""Unit tests for the claudeshorts reframe engine (T4b) + the engine registry.

NO mediapipe, NO cv2, NO wsl, NO real ffmpeg: every heavy seam (prober,
detector, encode runner, wsl probe, importer) is injected. Coverage per the
unit's DONE-WHEN:

  * rect math — centered subject -> centered crop; moving subject -> smoothed
    (eased) track that damps jitter;
  * ffmpeg argv shape — ONE crop+scale pass, argv list, 1080x1920, progress
    flags, dynamic x(t) only when the subject moves;
  * fallback selection logic — reframe.get_engine / resolve_engine_name with a
    MOCKED wsl probe (verthor available / wsl down / script missing).
"""

from __future__ import annotations

import json

import pytest
from media_studio.features import reframe
from media_studio.features import reframe_claudeshorts as cs
from media_studio.features.reframe import ReframeEngine, ReframeError
from media_studio.features.reframe_claudeshorts import (
    ClaudeShortsReframeEngine,
    ClaudeShortsReframeError,
)


# --------------------------------------------------------------------------- #
# fakes / fixtures
# --------------------------------------------------------------------------- #
class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_ff_runner(returncode=0):
    """An ffmpeg.run-shaped fake that records every encode call."""
    calls = []

    def runner(argv, total_sec=0.0, on_progress=None, should_cancel=None, **kw):
        calls.append({"argv": argv, "total_sec": total_sec, "kwargs": kw})
        return returncode

    runner.calls = calls
    return runner


@pytest.fixture
def fake_bins(tmp_path):
    """settings with a resolvable fake ffmpeg/ffprobe dir (no real binaries)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"):
        (bin_dir / name).write_text("")
    return {"ffmpegPath": str(bin_dir)}


def _vf_of(argv):
    return argv[argv.index("-vf") + 1]


def _eval_crop_x(expr: str, t: float) -> float:
    """Evaluate the ffmpeg crop-x expression for a given ``t`` (test oracle).

    NO eval(): a tiny recursive-descent reader of the exact
    ``if(lt(t,T),SEG,ELSE)`` piecewise-linear grammar emitted by
    ``build_crop_x_expr`` (segments are ``x0+(x1-x0)*(t-t0)/(dt)``), used to
    prove x(t) is a smooth INTERPOLATION with no stepped teleports.
    """
    import re

    def split_top(s: str) -> list[str]:
        parts, depth, start = [], 0, 0
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(s[start:i])
                start = i + 1
        parts.append(s[start:])
        return parts

    def ev(s: str) -> float:
        s = s.strip()
        if s.startswith("if("):
            cond, a, b = split_top(s[3:-1])
            return ev(a) if ev_cond(cond) else ev(b)
        # a linear segment "x0+(x1-x0)*(t-t0)/(dt)" or a bare integer
        m = re.fullmatch(r"(-?\d+)\+\((-?\d+)-(-?\d+)\)\*\(t-([\d.]+)\)/\(([\d.]+)\)", s)
        if m:
            x0, x1, _x0b, t0, dt = (float(g) for g in m.groups())
            return x0 + (x1 - x0) * (t - t0) / dt
        return float(s)

    def ev_cond(s: str) -> bool:
        # only "lt(t,T)" appears
        inner = s.strip()[3:-1]
        _lhs, rhs = split_top(inner)
        return t < float(rhs)

    return ev(expr)


def _engine(
    fake_bins,
    detector,
    runner=None,
    dims=(1280, 720, 8.0),
    backend_probe=None,
):
    runner = runner or _make_ff_runner(0)
    kwargs = {}
    if backend_probe is not None:
        kwargs["backend_probe"] = backend_probe
    eng = ClaudeShortsReframeEngine(
        settings=fake_bins,
        runner=runner,
        prober=lambda _path: dims,
        detector=detector,
        **kwargs,
    )
    return eng, runner


# --------------------------------------------------------------------------- #
# aspect / crop-rect math
# --------------------------------------------------------------------------- #
def test_output_dimensions_canonical_9_16():
    assert cs.output_dimensions("9:16") == (1080, 1920)
    assert cs.output_dimensions() == (1080, 1920)


def test_output_dimensions_other_ratios_even():
    w, h = cs.output_dimensions("3:4")
    assert h == 1920 and w % 2 == 0
    w, h = cs.output_dimensions("16:9")
    assert w == 1920 and h % 2 == 0


@pytest.mark.parametrize("bad", ["9", "a:b", "0:16", "9:0", ""])
def test_parse_aspect_rejects_garbage(bad):
    with pytest.raises(ValueError):
        cs._parse_aspect(bad)


def test_crop_size_landscape_to_9_16_is_route_a_rect():
    # ENGINE1_BUILD_RECIPE: 1280x720 talking-head -> crop 405x720.
    assert cs.crop_size(1280, 720, "9:16") == (405, 720)
    assert cs.crop_size(1920, 1080, "9:16") == (608, 1080)


def test_crop_size_portrait_source_crops_height():
    w, h = cs.crop_size(1080, 1920, "16:9")
    assert w == 1080
    assert h == 608


def test_crop_size_rejects_bad_dims():
    with pytest.raises(ValueError):
        cs.crop_size(0, 720)


def test_centered_crop_centers_both_axes():
    rect = cs.centered_crop(1280, 720, "9:16")
    assert rect == {"x": 437, "y": 0, "w": 405, "h": 720}
    rect = cs.centered_crop(1080, 1920, "16:9")
    assert rect["y"] == (1920 - rect["h"]) // 2


def test_crop_x_for_center_centered_subject_gives_centered_crop():
    # The unit's headline rect-math assertion.
    x = cs.crop_x_for_center(0.5, 405, 1280)
    centered = (1280 - 405) // 2
    assert abs(x - centered) <= 1


def test_crop_x_for_center_clamps_to_frame():
    assert cs.crop_x_for_center(0.0, 405, 1280) == 0
    assert cs.crop_x_for_center(1.0, 405, 1280) == 1280 - 405
    # crop as wide as the source: only x=0 fits.
    assert cs.crop_x_for_center(0.9, 1280, 1280) == 0


# --------------------------------------------------------------------------- #
# smoothing / windows / keyframes
# --------------------------------------------------------------------------- #
def test_smooth_centers_constant_input_unchanged():
    # A constant subject -> a constant track (zero-phase EMA of a constant).
    assert cs.smooth_centers([0.5, 0.5, 0.5]) == pytest.approx([0.5, 0.5, 0.5])


def test_smooth_centers_zero_phase_no_lag_bias():
    """Heavy zero-phase (forward+backward) EMA: the smoothed track of a step
    settles symmetrically around the step (no single-direction lag), and stays
    bounded within the raw range — it follows the subject without chasing noise."""
    raw = [0.2, 0.2, 0.8, 0.8, 0.8]
    out = cs.smooth_centers(raw, alpha=cs.SMOOTH_ALPHA)
    assert min(out) >= min(raw) - 1e-9
    assert max(out) <= max(raw) + 1e-9
    # the track is monotone non-decreasing across the single up-step
    assert all(b >= a - 1e-9 for a, b in zip(out, out[1:], strict=False))
    # zero-phase: the midpoint sample sits near the step's halfway value, i.e.
    # the smoothing is NOT biased toward the earlier (0.2) side like a causal EMA.
    assert out[2] == pytest.approx(0.5, abs=0.2)


def test_smooth_centers_low_alpha_is_heavier_than_high():
    """A LOWER alpha smooths harder — the track deviates LESS from the mean,
    proving the knob controls smoothing strength (jitter damping)."""
    raw = [0.5, 0.9, 0.1, 0.9, 0.1]
    heavy = cs.smooth_centers(raw, alpha=0.15)
    light = cs.smooth_centers(raw, alpha=0.6)
    heavy_swing = max(heavy) - min(heavy)
    light_swing = max(light) - min(light)
    assert heavy_swing < light_swing


def test_smooth_centers_damps_jitter():
    raw = [0.5, 0.9, 0.1, 0.9, 0.1]
    out = cs.smooth_centers(raw)
    raw_jump = max(abs(b - a) for a, b in zip(raw, raw[1:], strict=False))
    out_jump = max(abs(b - a) for a, b in zip(out, out[1:], strict=False))
    assert out_jump < raw_jump


def test_median_prefilter_kills_single_frame_spike():
    """A lone outlier sample is replaced by its neighbours' median, not kept.

    Detector noise on real footage produces single-frame spikes (a stray face on
    a graphic, a mis-detect on a turn). A spike between two steady samples must be
    pulled back to the steady value BEFORE the EMA sees it, so it cannot drag the
    track. Edges mirror (median over the available neighbours), so endpoints are
    never corrupted by a clamp.
    """
    out = cs.median_prefilter([0.65, 0.1, 0.65], window=3)
    assert out[1] == pytest.approx(0.65)
    # a constant input is returned unchanged
    assert cs.median_prefilter([0.4, 0.4, 0.4]) == pytest.approx([0.4, 0.4, 0.4])
    # a sustained step is NOT smeared (median preserves the level on each side)
    assert cs.median_prefilter([0.2, 0.2, 0.8, 0.8]) == pytest.approx([0.2, 0.2, 0.8, 0.8])


def test_median_prefilter_identity_cases():
    """``window<=1`` and short (<2-sample) tracks are returned unchanged — the
    pre-filter is a no-op there (nothing to median over)."""
    assert cs.median_prefilter([0.1, 0.9, 0.2], window=1) == pytest.approx([0.1, 0.9, 0.2])
    assert cs.median_prefilter([0.7]) == pytest.approx([0.7])
    assert cs.median_prefilter([]) == []


def test_smooth_centers_outlier_does_not_drag_opening():
    """The real m03 failure: a single early outlier (a stray left detection at
    the clip start) must NOT drag the smoothed OPENING crop off the steady
    subject. The opening sample drives the crop's first-keyframe x, so an outlier
    there shows empty studio. After the median pre-filter the opening tracks the
    steady subject, not the spike."""
    # first sample is a far-left spike; the subject is steadily at ~0.64.
    raw = [0.38, 0.65, 0.69, 0.63, 0.63, 0.64, 0.64, 0.64]
    out = cs.smooth_centers(raw)
    # the opening must sit near the steady subject, not be dragged toward 0.38.
    assert out[0] == pytest.approx(0.64, abs=0.06)


def test_window_timestamps_midpoints():
    assert cs.window_timestamps(10.0, window_sec=2.0) == [1.0, 3.0, 5.0, 7.0, 9.0]


def test_window_timestamps_caps_and_degenerates():
    assert len(cs.window_timestamps(1000.0)) == cs.MAX_WINDOWS
    assert cs.window_timestamps(0.0) == [0.0]
    assert cs.window_timestamps(0.5) == [0.25]


def test_dedupe_keyframes_drops_small_middle_moves():
    kfs = cs.build_keyframes([1, 2, 3, 4, 5], [100, 101, 150, 151, 200])
    out = cs.dedupe_keyframes(kfs, min_delta=8.1)
    assert [k["x"] for k in out] == [100, 150, 200]
    # first + last always survive
    assert out[0]["t"] == 1 and out[-1]["t"] == 5


def test_dedupe_keyframes_short_lists_untouched():
    kfs = cs.build_keyframes([1, 2], [100, 500])
    assert cs.dedupe_keyframes(kfs, min_delta=8.1) == kfs


def test_is_static():
    near = cs.build_keyframes([1, 2], [437, 439])
    far = cs.build_keyframes([1, 2], [400, 500])
    assert cs.is_static(near, epsilon=8.1) is True
    assert cs.is_static(far, epsilon=8.1) is False
    assert cs.is_static([], epsilon=8.1) is True


# --------------------------------------------------------------------------- #
# crop-x expression + ffmpeg argv shape
# --------------------------------------------------------------------------- #
def test_build_crop_x_expr_static():
    assert cs.build_crop_x_expr(437, None) == "437"
    assert cs.build_crop_x_expr(437, []) == "437"
    one = cs.build_keyframes([2.0], [123])
    assert cs.build_crop_x_expr(437, one) == "123"


def test_build_crop_x_expr_piecewise_linear():
    kfs = cs.build_keyframes([1.0, 3.0], [100, 300])
    expr = cs.build_crop_x_expr(437, kfs)
    # nested if() lerp segments, a t=0 hold prepended, last x held at the end
    assert expr.startswith("if(lt(t,")
    assert expr.count("if(") == 2  # [0->1 hold] + [1->3 lerp]
    assert "(t-1.000)/(2.000)" in expr
    assert expr.endswith("300))")
    assert " " not in expr  # ffmpeg expression-safe


def test_build_crop_x_expr_skips_duplicate_timestamps():
    kfs = cs.build_keyframes([1.0, 1.0, 3.0], [100, 100, 300])
    expr = cs.build_crop_x_expr(437, kfs)
    assert "/(0.000)" not in expr  # no division-by-zero segment


def test_build_reframe_argv_one_pass_shape(fake_bins):
    crop = {"x": 437, "y": 0, "w": 405, "h": 720}
    argv = cs.build_reframe_argv("C:\\in\\a clip.mp4", "C:\\out\\b clip.mp4", crop, None, "9:16", fake_bins)
    assert isinstance(argv, list)
    # ONE -vf with crop AND scale chained (the single ffmpeg pass)
    assert argv.count("-vf") == 1
    vf = _vf_of(argv)
    assert vf.startswith("crop=405:720:'437':0,")
    assert "scale=1080:1920:flags=lanczos" in vf
    assert "setsar=1" in vf
    # encode + progress flags for ffmpeg.run
    assert "libx264" in argv and "yuv420p" in argv
    assert argv[argv.index("-progress") + 1] == "pipe:1"
    assert "-nostats" in argv and "-y" in argv and "-nostdin" in argv
    # paths are single argv elements (spaces intact), in then out
    assert "C:\\in\\a clip.mp4" in argv and argv[-1] == "C:\\out\\b clip.mp4"


def test_build_reframe_argv_keyframed_x(fake_bins):
    crop = {"x": 437, "y": 0, "w": 405, "h": 720}
    kfs = cs.build_keyframes([1.0, 3.0], [100, 300])
    vf = _vf_of(cs.build_reframe_argv("/in.mp4", "/out.mp4", crop, kfs, "9:16", fake_bins))
    assert "crop=405:720:'if(lt(t," in vf  # quoted dynamic expression


def test_output_dimensions_social_presets_square_and_portrait():
    # WU R3: the curated 1:1 / 4:5 aspects resolve to their 1080-wide social dims
    # (NOT the generic long-edge-1920 math), shared with the verthor engine.
    assert cs.output_dimensions("1:1") == (1080, 1080)
    assert cs.output_dimensions("4:5") == (1080, 1350)
    assert cs.output_dimensions("9x16") == (1080, 1920)


def test_crop_size_for_square_and_portrait_aspects():
    # The crop RECTANGLE is parameterized by aspect: the same source yields a
    # 1:1 / 4:5 / 9:16 crop window (reuse the crop solution at different ratios).
    assert cs.crop_size(1280, 720, "1:1") == (720, 720)
    assert cs.crop_size(1280, 720, "4:5") == (576, 720)
    assert cs.crop_size(1280, 720, "9:16") == (405, 720)


@pytest.mark.parametrize(
    ("aspect", "dims"),
    [("1:1", "1080:1080"), ("4:5", "1080:1350"), ("9:16", "1080:1920")],
)
def test_build_reframe_argv_scales_to_each_social_aspect(fake_bins, aspect, dims):
    # The ONE ffmpeg pass scales to the per-aspect output dimensions.
    crop = {"x": 100, "y": 0, "w": 405, "h": 720}
    vf = _vf_of(cs.build_reframe_argv("/in.mp4", "/out.mp4", crop, None, aspect, fake_bins))
    assert f"scale={dims}:flags=lanczos" in vf


def test_build_frame_extract_argv(fake_bins):
    argv = cs.build_frame_extract_argv("/in.mp4", 1.5, "/tmp/f.jpg", fake_bins)
    assert argv[argv.index("-ss") + 1] == "1.500"
    assert argv[argv.index("-frames:v") + 1] == "1"
    assert argv[-1] == "/tmp/f.jpg"


# --------------------------------------------------------------------------- #
# probing
# --------------------------------------------------------------------------- #
def _probe_json(w=1280, h=720, fmt_duration="8.0", stream_duration=None):
    stream = {"width": w, "height": h}
    if stream_duration is not None:
        stream["duration"] = stream_duration
    data = {"streams": [stream]}
    if fmt_duration is not None:
        data["format"] = {"duration": fmt_duration}
    return json.dumps(data)


def test_probe_video_parses_geometry_and_duration(fake_bins):
    runner = lambda argv, **kw: _Completed(stdout=_probe_json())  # noqa: E731
    assert cs.probe_video("/in.mp4", fake_bins, runner=runner) == (1280, 720, 8.0)


def test_probe_video_falls_back_to_stream_duration(fake_bins):
    runner = lambda argv, **kw: _Completed(  # noqa: E731
        stdout=_probe_json(fmt_duration=None, stream_duration="6.5")
    )
    assert cs.probe_video("/in.mp4", fake_bins, runner=runner)[2] == 6.5


def test_probe_video_bad_duration_degrades_to_zero(fake_bins):
    runner = lambda argv, **kw: _Completed(  # noqa: E731
        stdout=_probe_json(fmt_duration="N/A")
    )
    assert cs.probe_video("/in.mp4", fake_bins, runner=runner)[2] == 0.0


def test_probe_video_garbage_raises_typed_error(fake_bins):
    runner = lambda argv, **kw: _Completed(stdout="not json")  # noqa: E731
    with pytest.raises(ClaudeShortsReframeError):
        cs.probe_video("/in.mp4", fake_bins, runner=runner)


def test_probe_argv_uses_ffprobe_json(fake_bins):
    argv = cs.build_probe_streams_argv("/in.mp4", fake_bins)
    assert "ffprobe" in argv[0]
    assert "-show_streams" in argv and "json" in argv
    assert argv[-1] == "/in.mp4"


# --------------------------------------------------------------------------- #
# detection backend selection (importer mocked — no natives anywhere)
# --------------------------------------------------------------------------- #
def _importer(available):
    def imp(name):
        if name in available:
            return object()
        raise ImportError(name)

    return imp


def test_detect_backend_prefers_mediapipe_when_both_import():
    assert cs.detect_backend(_importer({"mediapipe", "cv2"})) == "mediapipe"


def test_detect_backend_haar_when_mediapipe_missing():
    assert cs.detect_backend(_importer({"cv2"})) == "haar"


def test_detect_backend_mediapipe_without_cv2_raises_setup_error():
    # mediapipe alone cannot decode frames; cv2 is required. With cv2 absent the
    # backend is UNAVAILABLE -> an EXPLICIT setup/provisioning error, never a
    # silent "center" that degrades per-clip (WU-3 NO-SILENT-FALLBACK).
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError) as exc:
        cs.detect_backend(_importer({"mediapipe"}))
    assert "cv2" in str(exc.value).lower() or "opencv" in str(exc.value).lower()


def test_detect_backend_no_natives_raises_setup_error():
    # No native modules at all -> explicit setup error (fail loud at setup), not a
    # silent center fallback the rest of the pipeline can't distinguish.
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError):
        cs.detect_backend(_importer(set()))


def test_backend_unavailable_is_a_reframe_error_subclass():
    # So a single ``except ClaudeShortsReframeError`` at the job boundary still
    # catches it, but it is DISTINCT from a per-clip degrade (caught separately).
    assert issubclass(cs.ClaudeShortsBackendUnavailableError, cs.ClaudeShortsReframeError)


def test_detect_subject_centers_center_backend_short_circuits():
    def boom(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("no frame extraction for the center backend")

    assert cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=boom, backend="center") == []


def test_native_preimport_flag_lists_mediapipe_and_cv2():
    # A6 lesson 1 — the wiring agent consumes this (see WIRING-T4B.md).
    assert set(cs.NATIVE_MODULES_FOR_PREIMPORT) == {"mediapipe", "cv2"}


# --------------------------------------------------------------------------- #
# engine end-to-end (fake prober/detector/runner)
# --------------------------------------------------------------------------- #
def test_engine_centered_subject_one_static_pass(fake_bins):
    ts = cs.window_timestamps(8.0)
    eng, runner = _engine(fake_bins, detector=lambda p, t: [(x, 0.5) for x in ts])
    out = eng.reframe("C:\\in\\clip.mp4", "C:\\out\\clip.mp4", "9:16")
    assert out == "C:\\out\\clip.mp4"
    # ONE ffmpeg pass total
    assert len(runner.calls) == 1
    vf = _vf_of(runner.calls[0]["argv"])
    # centered subject -> centered crop (static, no animated expression)
    assert "if(" not in vf
    x = int(vf.split(":'")[1].split("'")[0])
    assert abs(x - 437) <= 1
    assert "scale=1080:1920" in vf


def test_engine_no_subject_center_crop(fake_bins):
    eng, runner = _engine(fake_bins, detector=lambda p, t: [])
    eng.reframe("/in.mp4", "/out.mp4")
    vf = _vf_of(runner.calls[0]["argv"])
    assert "crop=405:720:'437':0" in vf


def test_engine_moving_subject_smoothed_keyframed_track(fake_bins):
    moving = [(1.0, 0.1), (3.0, 0.3), (5.0, 0.5), (7.0, 0.9)]
    eng, runner = _engine(fake_bins, detector=lambda p, t: moving)
    crop, kfs, duration = eng.compute_plan("/in.mp4")
    assert duration == 8.0
    assert len(kfs) >= 2  # genuinely animated
    # the track is SMOOTHED: eased x values lag the raw target, monotone here
    xs = [k["x"] for k in kfs]
    assert xs == sorted(xs)
    raw_last = cs.crop_x_for_center(0.9, 405, 1280)
    assert xs[-1] < raw_last  # easing lag — not a raw pass-through
    # and the single encode pass uses the animated expression
    eng.reframe("/in.mp4", "/out.mp4")
    assert len(runner.calls) == 1
    assert "if(lt(t," in _vf_of(runner.calls[0]["argv"])


def test_engine_stable_subject_off_center_static_clamped(fake_bins):
    eng, _ = _engine(fake_bins, detector=lambda p, t: [(1.0, 0.99), (3.0, 0.99)])
    crop, kfs, _d = eng.compute_plan("/in.mp4")
    assert kfs == []  # static
    assert crop["x"] == 1280 - 405  # clamped to the frame edge


# --------------------------------------------------------------------------- #
# TDD (a): an OFF-CENTER subject -> crop centered ON THE SUBJECT, not frame-center
# --------------------------------------------------------------------------- #
def test_engine_offcenter_static_subject_crops_on_subject_not_frame_center(fake_bins):
    """A speaker sitting steadily LEFT of frame center (cx≈0.25) must yield a
    static crop centered on HIM — NOT drifted back toward frame center. This is
    the regression the static-bias change introduced (empty studio shown)."""
    # cx=0.25 across every window: genuinely static, off to the left.
    ts = cs.window_timestamps(8.0)
    eng, _ = _engine(fake_bins, detector=lambda p, t: [(x, 0.25) for x in ts])
    crop, kfs, _d = eng.compute_plan("/in.mp4")
    assert kfs == []  # static subject -> one fixed crop
    # crop centered on the subject: x ≈ 0.25*1280 - 405/2 = 117.5
    subject_x = cs.crop_x_for_center(0.25, 405, 1280)
    frame_center_x = (1280 - 405) // 2  # 437
    assert abs(crop["x"] - subject_x) <= 2
    # and it is NOT sitting near frame center (the drift bug)
    assert abs(crop["x"] - frame_center_x) > 100


def test_engine_offcenter_static_keeps_subject_inside_crop(fake_bins):
    """The subject's horizontal position stays WITHIN the crop window (he is not
    pushed to the frame edge / out of view)."""
    ts = cs.window_timestamps(8.0)
    cx = 0.7
    eng, _ = _engine(fake_bins, detector=lambda p, t: [(x, cx) for x in ts])
    crop, _kfs, _d = eng.compute_plan("/in.mp4")
    subj_px = cx * 1280
    assert crop["x"] <= subj_px <= crop["x"] + crop["w"]


# --------------------------------------------------------------------------- #
# TDD (b): a profile/weak-face frame -> person/motion fallback still locates him
# --------------------------------------------------------------------------- #
def test_subject_finder_falls_back_to_person_when_face_absent(monkeypatch):
    """Face detector returns None (profile/turned head) -> the PERSON (HOG body)
    detector locates the subject so the crop stays on him."""
    # face finder: never finds a face. person finder: body at cx=0.8.
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend: (lambda img: None, lambda: None))
    monkeypatch.setattr(cs, "_person_center", lambda img: 0.8)
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: pytest.fail("motion must not run when person hit"))
    find, _close = cs._make_subject_finder("haar")
    assert find(object()) == pytest.approx(0.8)


def test_subject_finder_falls_back_to_motion_when_face_and_person_absent(monkeypatch):
    """Neither face nor body detectable -> MOTION saliency (vs the previous
    frame) still locates the moving speaker. The first frame (no prev) yields
    None; the second resolves via motion."""
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend: (lambda img: None, lambda: None))
    monkeypatch.setattr(cs, "_person_center", lambda img: None)
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: 0.35)
    find, _close = cs._make_subject_finder("haar")
    assert find("frame0") is None  # no previous frame yet -> motion can't run
    assert find("frame1") == pytest.approx(0.35)  # diff vs frame0 locates motion


def test_subject_finder_face_hit_skips_fallbacks(monkeypatch):
    """When the FACE is found, neither person nor motion fallback runs."""
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend: (lambda img: 0.5, lambda: None))
    monkeypatch.setattr(cs, "_person_center", lambda img: pytest.fail("person must not run on a face hit"))
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: pytest.fail("motion must not run on a face hit"))
    find, _close = cs._make_subject_finder("mediapipe")
    assert find(object()) == pytest.approx(0.5)


def test_subject_finder_center_backend_has_no_finder():
    find, close = cs._make_subject_finder("center")
    assert find is None
    close()  # the no-op closer is callable


def test_subject_finder_no_face_finder_goes_straight_to_person(monkeypatch):
    """When the FACE backend yields no finder at all (e.g. missing haar cascade),
    the subject finder skips the face step and uses the person fallback."""
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend: (None, lambda: None))
    monkeypatch.setattr(cs, "_person_center", lambda img: 0.6)
    find, _close = cs._make_subject_finder("haar")
    assert find(object()) == pytest.approx(0.6)


def test_engine_profile_video_tracks_via_fallback_not_center(fake_bins):
    """End-to-end (b): the detector (simulating face->person/motion fallback)
    returns an off-center track; the engine crops on the SUBJECT, never the
    centered no-subject fallback."""
    ts = cs.window_timestamps(8.0)
    # subject located at 0.78 in every window via the fallback chain.
    eng, runner = _engine(fake_bins, detector=lambda p, t: [(x, 0.78) for x in ts])
    eng.reframe("/in.mp4", "/out.mp4")
    vf = _vf_of(runner.calls[0]["argv"])
    x = int(vf.split(":'")[1].split("'")[0])
    assert x != (1280 - 405) // 2  # NOT the center-crop fallback x (437)
    assert abs(x - cs.crop_x_for_center(0.78, 405, 1280)) <= 2


# --------------------------------------------------------------------------- #
# TDD (c): smooth interpolation -> no stepped jumps between sampled windows
# --------------------------------------------------------------------------- #
def test_engine_moving_subject_interpolates_no_teleport(fake_bins):
    """A subject panning across the frame yields an INTERPOLATED x(t) — the per-
    frame crop-x change is bounded (no teleport between sample windows)."""
    moving = [(float(i), 0.1 + 0.1 * i) for i in range(8)]  # 0.1 -> 0.8 over 8s
    eng, _ = _engine(fake_bins, detector=lambda p, t: moving)
    crop, kfs, duration = eng.compute_plan("/in.mp4")
    assert len(kfs) >= 2
    expr = cs.build_crop_x_expr(crop["x"], kfs)
    # evaluate the piecewise-linear x(t) on a dense time grid (no stepped jumps).
    xs = [_eval_crop_x(expr, t) for t in [i * 0.1 for i in range(int(duration * 10) + 1)]]
    max_step = max(abs(b - a) for a, b in zip(xs, xs[1:], strict=False))
    full_span = max(xs) - min(xs)
    # a teleport would move a large fraction of the whole pan in one 0.1s step;
    # interpolation keeps each step tiny relative to the total travel.
    assert full_span > 0
    assert max_step < full_span * 0.2


def test_engine_smoothing_lags_raw_target(fake_bins):
    """Heavy EMA: the tracked endpoints LAG the raw per-window target (the crop
    eases toward the subject rather than snapping), proving smoothing is active."""
    moving = [(1.0, 0.1), (3.0, 0.3), (5.0, 0.5), (7.0, 0.9)]
    eng, _ = _engine(fake_bins, detector=lambda p, t: moving)
    _crop, kfs, _d = eng.compute_plan("/in.mp4")
    raw_last = cs.crop_x_for_center(0.9, 405, 1280)
    assert kfs[-1]["x"] < raw_last  # eased, not a raw pass-through


def test_engine_detector_failure_degrades_to_center(fake_bins):
    def broken(p, t):
        raise RuntimeError("mediapipe exploded")

    eng, runner = _engine(fake_bins, detector=broken)
    out = eng.reframe("/in.mp4", "/out.mp4")
    assert out == "/out.mp4"
    assert "'437'" in _vf_of(runner.calls[0]["argv"])


# --------------------------------------------------------------------------- #
# WU-3 NO-SILENT-FALLBACK: compute_plan must SURFACE a per-clip degraded signal
# (never swallow a detection failure / trust-gate miss into a silent center crop)
# --------------------------------------------------------------------------- #
def test_compute_plan_detection_exception_surfaces_degraded_notice(fake_bins):
    """A broken detector still degrades to a center crop, but the degrade is
    SURFACED via on_notice (structured) instead of being swallowed with a log."""

    def broken(p, t):
        raise RuntimeError("mediapipe exploded")

    eng, _ = _engine(fake_bins, detector=broken)
    notices: list[dict] = []
    crop, kfs, _d = eng.compute_plan("/in.mp4", on_notice=notices.append)
    # still a centered crop (encode proceeds) ...
    assert kfs == [] and crop["x"] == 437
    # ... but the degrade was reported, not silently swallowed.
    assert len(notices) == 1
    assert notices[0]["type"] == cs.REFRAME_DEGRADED_NOTICE
    assert "center crop" in notices[0]["message"].lower()
    assert "mediapipe exploded" in notices[0]["reason"]


def test_compute_plan_trust_gate_miss_surfaces_degraded_notice(fake_bins):
    """No locatable subject (zero / too-few hits) -> centered crop AND a surfaced
    'tracking unavailable' notice so the UI can show a degraded badge."""
    eng, _ = _engine(fake_bins, detector=lambda p, t: [])
    notices: list[dict] = []
    crop, kfs, _d = eng.compute_plan("/in.mp4", on_notice=notices.append)
    assert kfs == [] and crop["x"] == 437
    assert len(notices) == 1
    assert notices[0]["type"] == cs.REFRAME_DEGRADED_NOTICE
    assert "center crop" in notices[0]["message"].lower()


def test_compute_plan_subject_found_emits_no_notice(fake_bins):
    """A clean track must NOT emit a degraded notice (no false 'degraded' badge)."""
    ts = cs.window_timestamps(8.0)
    eng, _ = _engine(fake_bins, detector=lambda p, t: [(x, 0.5) for x in ts])
    notices: list[dict] = []
    eng.compute_plan("/in.mp4", on_notice=notices.append)
    assert notices == []


def test_compute_plan_backend_unavailable_propagates_not_swallowed(fake_bins):
    """A native-backend setup error (cv2/mediapipe absent) is a PROVISIONING
    failure: it must propagate (fail loud at setup), NOT be swallowed into a
    per-clip center-crop degrade."""

    def no_backend(p, t):
        raise cs.ClaudeShortsBackendUnavailableError("opencv (cv2) not installed")

    eng, _ = _engine(fake_bins, detector=no_backend)
    notices: list[dict] = []
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError):
        eng.compute_plan("/in.mp4", on_notice=notices.append)
    # not turned into a per-clip degrade notice
    assert notices == []


def test_reframe_threads_on_notice_through_to_compute_plan(fake_bins):
    """The engine's reframe() forwards on_notice so the degrade surfaces from the
    one-shot reframe entry point too."""
    eng, _ = _engine(fake_bins, detector=lambda p, t: [])
    notices: list[dict] = []
    eng.reframe("/in.mp4", "/out.mp4", on_notice=notices.append)
    assert len(notices) == 1
    assert notices[0]["type"] == cs.REFRAME_DEGRADED_NOTICE


# --------------------------------------------------------------------------- #
# NO-SILENT-FALLBACK: a MODEL being unavailable (mediapipe absent -> the weaker
# OpenCV/haar backend) must NAME the missing model in the degrade notice, so the
# center-crop fallback is never silently attributed to "no subject" alone.
# --------------------------------------------------------------------------- #
def test_make_degraded_notice_names_missing_mediapipe_on_haar_backend():
    """The typed notice enriches its message when the active backend is haar
    (mediapipe unavailable) — the CAUSE is surfaced, not swallowed."""
    notice = cs.make_degraded_notice("no trackable subject located", backend="haar")
    assert notice["type"] == cs.REFRAME_DEGRADED_NOTICE
    assert "center crop" in notice["message"].lower()
    assert "mediapipe" in notice["message"].lower()
    # the raw reason is preserved verbatim for logs/UI attribution
    assert notice["reason"] == "no trackable subject located"


def test_make_degraded_notice_omits_hint_when_mediapipe_present():
    """When mediapipe IS the active backend the message must NOT claim it is
    missing (no false 'install mediapipe' advice)."""
    notice = cs.make_degraded_notice("no trackable subject located", backend="mediapipe")
    assert "mediapipe" not in notice["message"].lower()


def test_compute_plan_haar_backend_degrade_names_missing_mediapipe(fake_bins):
    """END-TO-END: mediapipe unavailable (haar backend) + a center-crop degrade ->
    the surfaced notice names the missing model. Still exactly ONE notice (the
    model cause is folded into the existing degrade, not a second badge)."""
    eng, _ = _engine(
        fake_bins,
        detector=lambda p, t: [],  # no subject -> center-crop degrade
        backend_probe=lambda: "haar",  # mediapipe absent
    )
    notices: list[dict] = []
    crop, kfs, _d = eng.compute_plan("/in.mp4", on_notice=notices.append)
    assert kfs == [] and crop["x"] == 437  # still degrades to center (encode proceeds)
    assert len(notices) == 1
    msg = notices[0]["message"].lower()
    assert "center crop" in msg
    assert "mediapipe" in msg  # the missing MODEL is surfaced, never silent


def test_compute_plan_mediapipe_backend_degrade_omits_downgrade_hint(fake_bins):
    """With mediapipe present, a genuine no-subject degrade must NOT falsely claim
    the model is missing."""
    eng, _ = _engine(
        fake_bins,
        detector=lambda p, t: [],
        backend_probe=lambda: "mediapipe",
    )
    notices: list[dict] = []
    eng.compute_plan("/in.mp4", on_notice=notices.append)
    assert len(notices) == 1
    assert "mediapipe" not in notices[0]["message"].lower()


def test_compute_plan_detector_exception_on_haar_names_missing_model(fake_bins):
    """A detector RUNTIME failure on the haar backend also names the missing model
    in its surfaced degrade (the enrichment applies to every center-crop path)."""

    def broken(p, t):
        raise RuntimeError("boom")

    eng, _ = _engine(fake_bins, detector=broken, backend_probe=lambda: "haar")
    notices: list[dict] = []
    eng.compute_plan("/in.mp4", on_notice=notices.append)
    assert len(notices) == 1
    assert "mediapipe" in notices[0]["message"].lower()
    assert "boom" in notices[0]["reason"]


def test_compute_plan_backend_probe_provisioning_failure_propagates(fake_bins):
    """If the backend probe itself reports NO usable backend (no cv2/mediapipe),
    that PROVISIONING failure propagates loudly — never a silent center crop."""

    def no_backend():
        raise cs.ClaudeShortsBackendUnavailableError("opencv (cv2) not installed")

    eng, _ = _engine(fake_bins, detector=lambda p, t: [], backend_probe=no_backend)
    notices: list[dict] = []
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError):
        eng.compute_plan("/in.mp4", on_notice=notices.append)
    assert notices == []  # not turned into a per-clip degrade badge


def test_engine_default_backend_probe_is_detect_backend(fake_bins):
    """The engine's default backend probe is the real ``detect_backend`` (so the
    degrade cause is resolved from the live import state when not injected)."""
    eng, _ = _engine(fake_bins, detector=lambda p, t: [(0.0, 0.5)])
    assert eng._backend_probe is cs.detect_backend


def test_engine_passes_total_sec_and_argv_list(fake_bins):
    eng, runner = _engine(fake_bins, detector=lambda p, t: [])
    eng.reframe("/in.mp4", "/out.mp4")
    call = runner.calls[0]
    assert isinstance(call["argv"], list)
    assert call["total_sec"] == 8.0
    assert "shell" not in call["kwargs"]


def test_engine_nonzero_exit_raises_typed_error(fake_bins):
    eng, _ = _engine(fake_bins, detector=lambda p, t: [], runner=_make_ff_runner(3))
    with pytest.raises(ClaudeShortsReframeError) as exc:
        eng.reframe("/in.mp4", "/out.mp4")
    assert "exit 3" in str(exc.value)


def test_engine_default_aspect_is_9_16(fake_bins):
    eng, runner = _engine(fake_bins, detector=lambda p, t: [])
    eng.reframe("/in.mp4", "/out.mp4")  # no aspect argument
    assert "scale=1080:1920" in _vf_of(runner.calls[0]["argv"])


# --------------------------------------------------------------------------- #
# registry + automatic fallback (reframe.get_engine — MOCKED wsl which-probe)
# --------------------------------------------------------------------------- #
def _which(found=True):
    """A ``shutil.which``-shaped fake recording every lookup.

    ``found=True`` -> ``wsl`` resolves to a path (WSL present);
    ``found=False`` -> ``None`` (WSL absent on this host).
    """
    calls = []

    def which(name):
        calls.append(name)
        return "/usr/bin/wsl" if found else None

    which.calls = calls
    return which


def _never_which(name):  # pragma: no cover - must never run
    raise AssertionError("which must not run for an explicit claudeshorts request")


@pytest.fixture
def verthor_script(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIA_STUDIO_VERTHOR_SCRIPT", raising=False)
    script = tmp_path / "verthor_reframe.sh"
    script.write_text("#!/bin/bash\n")
    return {"verthorScript": str(script)}


def test_engines_registry_has_the_a4_impls_plus_r1_multispeaker():
    # A4: verthor + claudeshorts; R1 (V1.1) adds the hybrid multi-speaker engine.
    from media_studio.features.reframe_multispeaker import MultiSpeakerReframeEngine

    assert set(reframe.ENGINES) == {"verthor", "claudeshorts", "reframe_multispeaker"}
    assert reframe.ENGINES["verthor"] is ReframeEngine
    assert reframe.ENGINES["claudeshorts"] is ClaudeShortsReframeEngine
    assert reframe.ENGINES["reframe_multispeaker"] is MultiSpeakerReframeEngine


def test_wsl_available_probe_shapes():
    # WSL presence is a pure PATH lookup (shutil.which) — never a subprocess,
    # so a half-installed WSL whose `wsl --status` would hang can never block.
    present = _which(found=True)
    assert reframe.wsl_available(which=present) is True
    assert present.calls == ["wsl"]
    assert reframe.wsl_available(which=_which(found=False)) is False


def test_script_present(verthor_script):
    assert reframe.script_present(verthor_script) is True
    assert reframe.script_present({"verthorScript": "definitely_missing/nope.sh"}) is False
    # POSIX path lives inside WSL — not host-checkable, the wsl probe decides.
    assert reframe.script_present({"verthorScript": "/opt/verthor/reframe.sh"}) is True


def test_script_present_bundled_default_resolves_packaged_script(monkeypatch):
    """No settings + no env -> the BUNDLED verthor script path is resolved
    (verthor is opt-in, but its host path still resolves to the packaged .sh).
    This exercises the _script_host_path bundled-default branch."""
    monkeypatch.delenv("MEDIA_STUDIO_VERTHOR_SCRIPT", raising=False)
    host = reframe._script_host_path({})
    assert host.endswith("verthor_reframe.sh")
    assert "__BUNDLED__" not in host
    # the packaged script ships in the repo, so it is present on the host.
    assert reframe.script_present({}) is True


def test_resolve_explicit_claudeshorts_never_probes():
    name, notice = reframe.resolve_engine_name("claudeshorts", {}, which=_never_which)
    assert name == "claudeshorts"
    assert notice is None


@pytest.mark.parametrize("requested", ["auto", "", None])
def test_resolve_auto_is_claudeshorts_without_probing_wsl(requested):
    """P3 DEFAULT FLIP: auto (and blank/None) -> claudeshorts, the NO-WSL
    default. No WSL/script probe runs (``_never_which`` would explode), and no
    fallback notice is produced."""
    name, notice = reframe.resolve_engine_name(requested, {}, which=_never_which)
    assert name == "claudeshorts"
    assert notice is None


def test_resolve_explicit_verthor_when_available(verthor_script):
    """EXPLICIT verthor still resolves to verthor when WSL + script are present."""
    name, notice = reframe.resolve_engine_name("verthor", verthor_script, which=_which(found=True))
    assert name == "verthor"
    assert notice is None


def test_resolve_explicit_verthor_errors_when_wsl_absent(verthor_script):
    """EXPLICIT verthor must FAIL LOUDLY when WSL is absent — never silently
    fall back. verthor is an explicit opt-in; the default is claudeshorts."""
    with pytest.raises(ReframeError) as exc:
        reframe.resolve_engine_name("verthor", verthor_script, which=_which(found=False))
    assert "WSL" in str(exc.value)


def test_resolve_explicit_verthor_errors_when_script_missing(monkeypatch):
    """Explicit verthor also errors (not falls back) when the script is missing."""
    monkeypatch.delenv("MEDIA_STUDIO_VERTHOR_SCRIPT", raising=False)
    with pytest.raises(ReframeError) as exc:
        reframe.resolve_engine_name(
            "verthor",
            {"verthorScript": "definitely_missing/nope.sh"},
            which=_never_which,  # script check fails BEFORE any wsl probe
        )
    assert "not found" in str(exc.value)


def test_resolve_unknown_engine_raises():
    with pytest.raises(ValueError):
        reframe.resolve_engine_name("ffmpeg-magic", {})


def test_get_engine_returns_constructed_instances(verthor_script):
    # P3: auto -> claudeshorts (no WSL probe), no notice.
    eng, notice = reframe.get_engine("auto", {}, which=_never_which)
    assert isinstance(eng, ClaudeShortsReframeEngine)
    assert notice is None

    # explicit claudeshorts -> claudeshorts, no probe.
    eng, notice = reframe.get_engine("claudeshorts", {}, which=_never_which)
    assert isinstance(eng, ClaudeShortsReframeEngine)
    assert notice is None

    # explicit verthor (WSL present) -> the verthor (WSL) engine.
    eng, notice = reframe.get_engine("verthor", verthor_script, which=_which(found=True))
    assert isinstance(eng, ReframeEngine)
    assert notice is None


def test_get_engine_explicit_verthor_errors_when_wsl_absent(verthor_script):
    with pytest.raises(ReframeError):
        reframe.get_engine("verthor", verthor_script, which=_which(found=False))


# --------------------------------------------------------------------------- #
# build_crop_x_expr — keyframe ALREADY at t=0 (no synthetic t=0 prepend)
# --------------------------------------------------------------------------- #
def test_build_crop_x_expr_first_keyframe_at_zero_not_prepended():
    # First keyframe already at t=0 -> the t=0-prepend branch is skipped; the
    # expression still interpolates between the two real keyframes.
    kfs = [{"t": 0.0, "x": 100}, {"t": 2.0, "x": 300}]
    expr = cs.build_crop_x_expr(0, kfs)
    assert expr.startswith("if(lt(t,2.000),")
    assert "100+(300-100)*(t-0.000)/(2.000)" in expr
    # exactly one segment (no extra prepended t=0 keyframe doubling it up)
    assert expr.count("if(lt(t,") == 1


# --------------------------------------------------------------------------- #
# engine — defensive non-list argv guard (§A6.4: never a shell string)
# --------------------------------------------------------------------------- #
def test_engine_raises_typeerror_when_argv_not_a_list(fake_bins, monkeypatch):
    eng, _runner = _engine(fake_bins, detector=lambda p, t: [])
    monkeypatch.setattr(cs, "build_reframe_argv", lambda *a, **k: "ffmpeg -i in out")
    with pytest.raises(TypeError, match="must be a list"):
        eng.reframe("/in.mp4", "/out.mp4")


# --------------------------------------------------------------------------- #
# _make_face_finder — the haar (cv2) branch + the center (no-finder) branch.
#
# cv2 IS installed; the haar cascade ships with opencv, so the finder runs REAL
# (deterministic) inference on synthetic frames — no network, no model download.
# The mediapipe branch is reported for pragma (legacy mp.solutions API absent in
# the installed mediapipe build; see the deliverable report).
# --------------------------------------------------------------------------- #
def test_make_face_finder_center_backend_returns_no_finder():
    find, close = cs._make_face_finder("center")
    assert find is None
    close()  # the no-op closer is safely callable


# --------------------------------------------------------------------------- #
# _make_face_finder — the mediapipe branch (fake mediapipe module injected).
#
# The installed mediapipe build lacks the legacy ``mp.solutions`` API, so we
# inject a fake ``mediapipe`` module exposing exactly the slice the engine uses
# (solutions.face_detection.FaceDetection -> process(rgb).detections with a
# relative_bounding_box). cv2 stays REAL (cvtColor on a numpy frame).
# --------------------------------------------------------------------------- #
def _fake_mediapipe(detections):
    import sys
    import types

    captured: dict = {"closed": False}

    class _Detector:
        def process(self, rgb):
            captured["rgb_shape"] = getattr(rgb, "shape", None)
            return types.SimpleNamespace(detections=detections)

        def close(self):
            captured["closed"] = True

    def _factory(*, model_selection, min_detection_confidence):
        captured["model_selection"] = model_selection
        return _Detector()

    mod = types.ModuleType("mediapipe")
    mod.solutions = types.SimpleNamespace(  # type: ignore[attr-defined]
        face_detection=types.SimpleNamespace(FaceDetection=_factory)
    )
    sys.modules["mediapipe"] = mod
    return mod, captured


def _bbox(xmin, width, height, ymin=0.0):
    import types

    # The real mediapipe relative_bounding_box carries ymin too (the finder uses
    # it to build the per-face motion box for the active-speaker tie-break).
    return types.SimpleNamespace(
        location_data=types.SimpleNamespace(
            relative_bounding_box=types.SimpleNamespace(xmin=xmin, ymin=ymin, width=width, height=height)
        )
    )


def test_make_face_finder_mediapipe_returns_best_detection_center(monkeypatch):
    import numpy as np

    # Two detections; the larger-area one (0.4*0.4) wins over (0.2*0.2).
    small = _bbox(0.0, 0.2, 0.2)
    big = _bbox(0.5, 0.4, 0.4)
    _mod, captured = _fake_mediapipe([small, big])
    monkeypatch.setitem(__import__("sys").modules, "mediapipe", _mod)

    find, close = cs._make_face_finder("mediapipe")
    assert callable(find)
    cx = find(np.zeros((90, 160, 3), dtype=np.uint8))
    # best bbox center x = xmin + width/2 = 0.5 + 0.2 = 0.7
    assert cx == pytest.approx(0.7)
    assert captured["model_selection"] == 1
    close()
    assert captured["closed"] is True


def test_make_face_finder_mediapipe_no_detection_returns_none(monkeypatch):
    import numpy as np

    _mod, _captured = _fake_mediapipe([])  # no detections
    monkeypatch.setitem(__import__("sys").modules, "mediapipe", _mod)
    find, _close = cs._make_face_finder("mediapipe")
    assert find(np.zeros((50, 50, 3), dtype=np.uint8)) is None


def test_make_face_finder_haar_returns_callable_finder():
    import numpy as np

    find, close = cs._make_face_finder("haar")
    assert callable(find)
    # A blank frame has no face -> the haar finder returns None (no detection).
    blank = np.zeros((120, 240, 3), dtype=np.uint8)
    assert find(blank) is None
    close()


def test_make_face_finder_haar_returns_normalized_center_on_detection(monkeypatch):
    import cv2
    import numpy as np

    # Stub the cascade so detectMultiScale reports a face box; this drives the
    # "largest face -> normalized horizontal center" return (lines 437-438).
    class _FaceCascade:
        def __init__(self, *_a):
            pass

        def empty(self):
            return False

        def detectMultiScale(self, gray, scaleFactor, minNeighbors):
            # two boxes; the larger (by w*h) wins. frame width below is 200.
            return [(10, 10, 20, 20), (100, 10, 40, 40)]  # second is larger

    monkeypatch.setattr(cv2, "CascadeClassifier", _FaceCascade)
    find, close = cs._make_face_finder("haar")
    img = np.zeros((120, 200, 3), dtype=np.uint8)  # width 200
    cx = find(img)
    # largest face center x = 100 + 40/2 = 120; normalized = 120/200 = 0.6
    assert cx == pytest.approx(0.6)
    close()


def test_make_face_finder_haar_no_faces_returns_none(monkeypatch):
    import cv2
    import numpy as np

    class _NoFaceCascade:
        def __init__(self, *_a):
            pass

        def empty(self):
            return False

        def detectMultiScale(self, gray, scaleFactor, minNeighbors):
            return ()  # empty -> finder returns None

    monkeypatch.setattr(cv2, "CascadeClassifier", _NoFaceCascade)
    find, _close = cs._make_face_finder("haar")
    assert find(np.zeros((50, 50, 3), dtype=np.uint8)) is None


def test_make_face_finder_haar_missing_cascade_raises_provisioning_error(monkeypatch):
    """A missing/empty haar cascade is a PROVISIONING failure (a broken OpenCV
    install), NOT a silent per-clip degrade: it must raise the loud
    ``ClaudeShortsBackendUnavailableError`` so the job surfaces an actionable
    "reinstall opencv" error instead of quietly using a center crop
    (WU no-silent-fallback)."""
    import cv2

    # Force an EMPTY cascade (the "cascade file missing/unreadable" branch).
    class _EmptyCascade:
        def __init__(self, *_a):
            pass

        def empty(self):
            return True

    monkeypatch.setattr(cv2, "CascadeClassifier", _EmptyCascade)
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError) as exc:
        cs._make_face_finder("haar")
    assert "cascade" in str(exc.value).lower()


# --------------------------------------------------------------------------- #
# detect_subject_centers — the non-center body (real cv2.imread of fake frames)
# --------------------------------------------------------------------------- #
def test_detect_subject_centers_haar_reads_extracted_frames():
    import cv2
    import numpy as np

    # A frame_runner that writes a REAL (blank) jpeg to the requested path so
    # cv2.imread succeeds; the haar finder finds no face -> no samples appended.
    def frame_runner(argv, capture_output=True, check=False):
        out_path = argv[-1]
        cv2.imwrite(out_path, np.zeros((80, 160, 3), dtype=np.uint8))
        return type("C", (), {"returncode": 0})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5, 1.5], frame_runner=frame_runner, backend="haar")
    # blank frames -> haar finds nothing -> empty sample list, but the body ran
    # (frames extracted + read) without spawning real ffmpeg/cv2 download.
    assert samples == []


def test_detect_subject_centers_skips_missing_and_unreadable_frames():
    # A frame_runner that NEVER writes the frame file -> os.path.exists False ->
    # the frame is skipped (the "frame not produced" continue branch).
    def no_write_runner(argv, capture_output=True, check=False):
        return type("C", (), {"returncode": 1})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=no_write_runner, backend="haar")
    assert samples == []


def test_detect_subject_centers_skips_unreadable_frame(monkeypatch):
    # The frame file EXISTS but cv2.imread can't decode it (None) -> skipped
    # (the "img is None" continue branch, distinct from "file not produced").
    import cv2

    monkeypatch.setattr(cs, "_make_face_finder", lambda backend: (lambda img: 0.5, lambda: None))
    monkeypatch.setattr(cv2, "imread", lambda path: None)  # always unreadable

    def frame_runner(argv, capture_output=True, check=False):
        # Write SOMETHING so os.path.exists is True, but imread (stubbed) -> None.
        with open(argv[-1], "wb") as fh:
            fh.write(b"not-a-real-jpeg")
        return type("C", (), {"returncode": 0})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=frame_runner, backend="haar")
    assert samples == []


def test_detect_subject_centers_no_finder_backend_returns_empty(monkeypatch):
    # When _make_subject_finder yields no finder (None) the body returns [] early.
    monkeypatch.setattr(cs, "_make_subject_finder", lambda backend: (None, lambda: None))

    def boom(*a, **k):  # pragma: no cover - must never run (no finder -> no frames)
        raise AssertionError("no frame extraction without a finder")

    assert cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=boom, backend="haar") == []


def test_detect_subject_centers_collects_when_finder_returns_center(monkeypatch):
    import cv2
    import numpy as np

    # Stub the finder to report a center for every frame so the sample-append
    # branch (cx is not None) is exercised; cv2.imread reads a real jpeg.
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend: (lambda img: 0.42, lambda: None))

    def frame_runner(argv, capture_output=True, check=False):
        cv2.imwrite(argv[-1], np.zeros((60, 120, 3), dtype=np.uint8))
        return type("C", (), {"returncode": 0})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5, 1.5], frame_runner=frame_runner, backend="haar")
    assert samples == [(0.5, 0.42), (1.5, 0.42)]


def test_detect_subject_centers_finder_close_failure_is_swallowed(monkeypatch):
    import cv2
    import numpy as np

    def boom_close():
        raise RuntimeError("close blew up")

    monkeypatch.setattr(cs, "_make_face_finder", lambda backend: (lambda img: 0.5, boom_close))

    def frame_runner(argv, capture_output=True, check=False):
        cv2.imwrite(argv[-1], np.zeros((40, 80, 3), dtype=np.uint8))
        return type("C", (), {"returncode": 0})()

    # A failing close() must never mask the collected results (cleanup-swallow).
    samples = cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=frame_runner, backend="haar")
    assert samples == [(0.5, 0.5)]


# --------------------------------------------------------------------------- #
# _person_center — HOG body fallback (real cv2; sub-window guard + stubbed hit)
# --------------------------------------------------------------------------- #
def test_person_center_skips_subwindow_frame_no_crash():
    import numpy as np

    # Frame smaller than the 64x128 HOG window -> guarded out (would segfault).
    small = np.zeros((80, 160, 3), dtype=np.uint8)
    assert cs._person_center(small) is None


def test_person_center_no_person_returns_none():
    import numpy as np

    # A blank window-sized frame -> the real HOG finds no person.
    blank = np.zeros((256, 256, 3), dtype=np.uint8)
    assert cs._person_center(blank) is None


def test_person_center_returns_normalized_center_on_detection(monkeypatch):
    import cv2
    import numpy as np

    class _HOG:
        def setSVMDetector(self, _d):
            pass

        def detectMultiScale(self, _img, winStride):
            # two bodies; the higher-weighted (second) wins. frame width = 400.
            rects = [(10, 0, 60, 120), (300, 0, 60, 120)]
            weights = [0.2, 0.9]
            return rects, weights

    monkeypatch.setattr(cv2, "HOGDescriptor", lambda: _HOG())
    monkeypatch.setattr(cv2, "HOGDescriptor_getDefaultPeopleDetector", lambda: object())
    img = np.zeros((200, 400, 3), dtype=np.uint8)  # width 400
    cx = cs._person_center(img)
    # best body center x = 300 + 60/2 = 330; normalized = 330/400 = 0.825
    assert cx == pytest.approx(0.825)


def test_person_center_no_rects_returns_none(monkeypatch):
    import cv2
    import numpy as np

    class _HOG:
        def setSVMDetector(self, _d):
            pass

        def detectMultiScale(self, _img, winStride):
            return (), None  # no rects, no weights

    monkeypatch.setattr(cv2, "HOGDescriptor", lambda: _HOG())
    monkeypatch.setattr(cv2, "HOGDescriptor_getDefaultPeopleDetector", lambda: object())
    assert cs._person_center(np.zeros((200, 200, 3), dtype=np.uint8)) is None


def test_person_center_missing_weights_uses_zero(monkeypatch):
    import cv2
    import numpy as np

    class _HOG:
        def setSVMDetector(self, _d):
            pass

        def detectMultiScale(self, _img, winStride):
            return [(40, 0, 80, 120)], None  # rect present, weights None

    monkeypatch.setattr(cv2, "HOGDescriptor", lambda: _HOG())
    monkeypatch.setattr(cv2, "HOGDescriptor_getDefaultPeopleDetector", lambda: object())
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    # single rect, center x = 40 + 80/2 = 80; normalized = 80/200 = 0.4
    assert cs._person_center(img) == pytest.approx(0.4)


# --------------------------------------------------------------------------- #
# _motion_center — inter-frame saliency fallback (real cv2 diff)
# --------------------------------------------------------------------------- #
def test_motion_center_locates_moving_block():
    import numpy as np

    prev = np.zeros((100, 200, 3), dtype=np.uint8)
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    # a bright block appears on the RIGHT half -> motion centroid is right-of-center.
    img[:, 150:180, :] = 255
    cx = cs._motion_center(prev, img)
    assert cx is not None
    assert cx > 0.6  # centroid near x≈165/200 = 0.825


def test_motion_center_no_motion_returns_none():
    import numpy as np

    frame = np.full((60, 120, 3), 30, dtype=np.uint8)
    # identical frames -> zero diff -> no motion located.
    assert cs._motion_center(frame, frame.copy()) is None


def test_motion_center_shape_mismatch_returns_none():
    import numpy as np

    prev = np.zeros((100, 200, 3), dtype=np.uint8)
    img = np.zeros((90, 160, 3), dtype=np.uint8)  # different geometry (scene cut)
    assert cs._motion_center(prev, img) is None


# --------------------------------------------------------------------------- #
# WU PHASE-5 — WIDE-SHOT framing: lock onto the DOMINANT/active single speaker
# (largest face/person; tie-break by motion). NEVER the empty gap between two
# people / an edge-cut. Multi-speaker SWITCHING is V2 (docs/ROADMAP.md).
# --------------------------------------------------------------------------- #
# select_dominant — the pure subject-selection core.
def test_select_dominant_empty_returns_none():
    assert cs.select_dominant([]) is None


def test_select_dominant_single_candidate_returns_it():
    assert cs.select_dominant([(0.3, 100.0, 0.0)]) == pytest.approx(0.3)


def test_select_dominant_two_people_different_sizes_picks_larger():
    """Two-person shot, different face/person sizes -> the LARGER (closer =
    dominant) subject is framed, not the smaller one nor the midpoint."""
    cands = [(0.25, 2000.0, 0.0), (0.8, 300.0, 0.0)]  # left big, right small
    assert cs.select_dominant(cands) == pytest.approx(0.25)


def test_select_dominant_larger_wins_over_higher_activity_when_gap_is_real():
    """A genuinely larger subject beats a smaller, more-active one — size (who is
    featured) dominates unless the sizes are a near-tie."""
    cands = [(0.2, 5000.0, 0.0), (0.9, 500.0, 99.0)]
    assert cs.select_dominant(cands) == pytest.approx(0.2)


def test_select_dominant_wide_offcenter_locks_on_person_not_center():
    """A single off-center person in a WIDE shot -> framed ON him, never drifted
    back to frame center / an empty studio."""
    assert cs.select_dominant([(0.82, 1500.0, 0.0)]) == pytest.approx(0.82)


def test_select_dominant_equal_size_tie_broken_by_motion():
    """A symmetric two-shot (equal face size) -> the ACTIVE (talking, more
    motion) speaker is framed, not an arbitrary largest-by-a-pixel pick."""
    left = (0.25, 1000.0, 0.1)
    right = (0.75, 1000.0, 5.0)  # more motion -> the active speaker
    assert cs.select_dominant([left, right]) == pytest.approx(0.75)


def test_select_dominant_near_size_tie_uses_motion():
    """Within DOMINANT_SIZE_TIE_FRAC the marginally-smaller but ACTIVE speaker
    still wins (the tie band, not a hard equality)."""
    bigger_quiet = (0.2, 1000.0, 0.0)
    smaller_active = (0.8, 1000.0 * (1.0 - cs.DOMINANT_SIZE_TIE_FRAC / 2.0), 9.0)
    assert cs.select_dominant([bigger_quiet, smaller_active]) == pytest.approx(0.8)


def test_select_dominant_all_zero_size_falls_back_to_activity():
    """Degenerate (all zero-area) candidates -> activity decides (covers the
    largest<=0 guard)."""
    assert cs.select_dominant([(0.1, 0.0, 1.0), (0.9, 0.0, 5.0)]) == pytest.approx(0.9)


def test_select_dominant_exact_tie_is_deterministic_first():
    """Exact ties (same size + same activity) resolve to the FIRST candidate —
    deterministic, so the crop never flips frame-to-frame on a coin-flip."""
    assert cs.select_dominant([(0.3, 100.0, 0.0), (0.7, 100.0, 0.0)]) == pytest.approx(0.3)


# _region_activity — per-face motion score for the active-speaker tie-break.
def test_region_activity_no_prev_frame_returns_zero():
    import numpy as np

    img = np.zeros((50, 50, 3), dtype=np.uint8)
    assert cs._region_activity(None, img, (0, 0, 50, 50)) == 0.0


def test_region_activity_shape_mismatch_returns_zero():
    import numpy as np

    prev = np.zeros((40, 40, 3), dtype=np.uint8)
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    assert cs._region_activity(prev, img, (0, 0, 40, 40)) == 0.0


def test_region_activity_empty_or_out_of_range_box_returns_zero():
    import numpy as np

    f = np.zeros((50, 50, 3), dtype=np.uint8)
    assert cs._region_activity(f, f.copy(), (30, 0, 30, 50)) == 0.0  # x1<=x0
    assert cs._region_activity(f, f.copy(), (60, 60, 70, 70)) == 0.0  # clamps to empty


def test_region_activity_detects_change_inside_box_only():
    import numpy as np

    prev = np.zeros((50, 80, 3), dtype=np.uint8)
    cur = np.zeros((50, 80, 3), dtype=np.uint8)
    cur[10:40, 10:40, :] = 200
    moved = cs._region_activity(prev, cur, (10, 10, 40, 40))
    still = cs._region_activity(prev, cur, (50, 0, 80, 50))
    assert moved > 0.0
    assert still == 0.0


# _dominant_cluster_centroid — motion fallback picks ONE cluster, never the gap.
def test_dominant_cluster_centroid_single_run():
    assert cs._dominant_cluster_centroid([0, 0, 4, 4, 0, 0]) == pytest.approx(2.5)


def test_dominant_cluster_centroid_picks_run_with_most_motion():
    # left run cols 2-3 (sum 2) vs right run cols 6-8 (sum 30) -> dominant = right.
    col = [0, 0, 1, 1, 0, 0, 10, 10, 10, 0]
    assert cs._dominant_cluster_centroid(col) == pytest.approx(7.0)


def test_dominant_cluster_centroid_run_extends_to_end():
    # a run touching the last column exercises the trailing-run append.
    assert cs._dominant_cluster_centroid([0, 0, 5, 5]) == pytest.approx(2.5)


def test_motion_center_two_movers_picks_dominant_not_midpoint():
    """The empty-studio bug: two people both moving in a wide/two-shot. The
    GLOBAL centroid would land in the gap between them; the dominant-cluster
    centroid locks onto the more-active subject instead."""
    import numpy as np

    prev = np.zeros((100, 300, 3), dtype=np.uint8)
    img = np.zeros((100, 300, 3), dtype=np.uint8)
    img[40:60, 20:40, :] = 255  # small mover, left
    img[20:80, 240:280, :] = 255  # big mover, right (dominant)
    cx = cs._motion_center(prev, img)
    assert cx is not None
    assert cx > 0.7  # right cluster, NOT the ~0.5 midpoint gap


# face/person finders — dominant selection wired through the real detectors.
def test_make_face_finder_haar_two_faces_picks_larger(monkeypatch):
    import cv2
    import numpy as np

    class _TwoFaces:
        def __init__(self, *_a):
            pass

        def empty(self):
            return False

        def detectMultiScale(self, gray, scaleFactor, minNeighbors):
            # left small (20x20 @x=20), right large (60x60 @x=300). width = 400.
            return [(20, 20, 20, 20), (300, 20, 60, 60)]

    monkeypatch.setattr(cv2, "CascadeClassifier", _TwoFaces)
    find, _close = cs._make_face_finder("haar")
    cx = find(np.zeros((120, 400, 3), dtype=np.uint8))
    # larger face center x = 300 + 30 = 330 -> 330/400 = 0.825.
    assert cx == pytest.approx(0.825)


def test_make_face_finder_haar_active_speaker_motion_tiebreak(monkeypatch):
    import cv2
    import numpy as np

    class _TwoEqual:
        def __init__(self, *_a):
            pass

        def empty(self):
            return False

        def detectMultiScale(self, gray, scaleFactor, minNeighbors):
            return [(20, 20, 40, 40), (120, 20, 40, 40)]  # equal size; width = 200

    monkeypatch.setattr(cv2, "CascadeClassifier", _TwoEqual)
    find, _close = cs._make_face_finder("haar")
    f0 = np.zeros((100, 200, 3), dtype=np.uint8)
    f1 = np.zeros((100, 200, 3), dtype=np.uint8)
    f1[20:60, 120:160, :] = 200  # the RIGHT face moves (talking)
    find(f0)  # establish previous frame
    cx = find(f1)
    assert cx == pytest.approx(0.7)  # active (right) speaker: (120 + 20) / 200


def test_make_face_finder_mediapipe_active_speaker_motion_tiebreak(monkeypatch):
    import numpy as np

    left = _bbox(0.05, 0.2, 0.4)  # equal-size faces
    right = _bbox(0.6, 0.2, 0.4)
    _mod, _captured = _fake_mediapipe([left, right])
    monkeypatch.setitem(__import__("sys").modules, "mediapipe", _mod)
    find, close = cs._make_face_finder("mediapipe")
    f0 = np.zeros((100, 200, 3), dtype=np.uint8)
    f1 = np.zeros((100, 200, 3), dtype=np.uint8)
    f1[0:40, 120:160, :] = 200  # right face box (x 120..160, y 0..40) moves
    find(f0)
    cx = find(f1)
    assert cx == pytest.approx(0.7)  # right active speaker: xmin + width/2 = 0.6 + 0.1
    close()


def test_person_center_prefers_larger_closer_body_over_higher_weight(monkeypatch):
    import cv2
    import numpy as np

    class _HOG:
        def setSVMDetector(self, _d):
            pass

        def detectMultiScale(self, _img, winStride):
            # left BIG body (closer) lower weight; right small higher weight. width=400.
            return [(10, 0, 160, 300), (320, 0, 40, 90)], [0.3, 0.95]

    monkeypatch.setattr(cv2, "HOGDescriptor", lambda: _HOG())
    monkeypatch.setattr(cv2, "HOGDescriptor_getDefaultPeopleDetector", lambda: object())
    cx = cs._person_center(np.zeros((320, 400, 3), dtype=np.uint8))
    # dominant = larger (closer) body -> center x = 10 + 80 = 90 -> 90/400 = 0.225.
    assert cx == pytest.approx(0.225)


def test_single_speaker_capability_note_is_honest():
    """The honest 'V1 follows a single speaker' capability copy is a real,
    asserted artifact (not just prose) — and points at the V2 switching roadmap."""
    note = cs.SINGLE_SPEAKER_CAPABILITY_NOTE
    assert "single speaker" in note.lower()
    assert "v2" in note.lower()
