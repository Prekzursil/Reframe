"""Unit tests for the claudeshorts reframe engine (T4b) + the engine registry.

NO real YuNet/ONNX download, NO WSL, NO real ffmpeg: every heavy seam (prober,
detector, encode runner, wsl probe, importer, cv2.FaceDetectorYN, the YuNet model
resolver) is injected/mocked, so the suite never depends on the installed opencv
build or a downloaded model (the hardening cv2 whack-a-mole lesson). Coverage per
the unit's DONE-WHEN:

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


def test_detect_backend_yunet_when_cv2_imports():
    # v1.2.0 WU1: the sole face backend is YuNet (cv2.FaceDetectorYN). cv2
    # importable -> "yunet"; the actual model/class presence is checked later in
    # _make_face_finder (fail-loud), not here.
    assert cs.detect_backend(_importer({"cv2"})) == "yunet"


def test_detect_backend_no_cv2_raises_setup_error():
    # No cv2 -> subject tracking is impossible -> explicit setup/provisioning
    # error (fail loud at setup), never a silent "center" the rest of the pipeline
    # can't distinguish from a legitimate no-subject clip (WU-3 NO-SILENT-FALLBACK).
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError) as exc:
        cs.detect_backend(_importer(set()))
    assert "cv2" in str(exc.value).lower() or "opencv" in str(exc.value).lower()


def test_backend_unavailable_is_a_reframe_error_subclass():
    # So a single ``except ClaudeShortsReframeError`` at the job boundary still
    # catches it, but it is DISTINCT from a per-clip degrade (caught separately).
    assert issubclass(cs.ClaudeShortsBackendUnavailableError, cs.ClaudeShortsReframeError)


def test_detect_subject_centers_center_backend_short_circuits():
    def boom(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("no frame extraction for the center backend")

    assert cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=boom, backend="center") == []


def test_native_preimport_flag_lists_cv2_only():
    # A6 lesson 1 — v1.2.0 WU1 dropped mediapipe; YuNet runs entirely through cv2,
    # so cv2 is the only native module this engine flags for __main__ pre-import.
    assert set(cs.NATIVE_MODULES_FOR_PREIMPORT) == {"cv2"}


# --------------------------------------------------------------------------- #
# resolve_yunet_model_path — asset-store resolution of the pinned YuNet ONNX.
# The manifest + asset-manager seams are monkeypatched so no real download / disk
# probe happens (the "mock the native backend" hardening lesson).
# --------------------------------------------------------------------------- #
def test_resolve_yunet_model_path_unregistered_returns_none(monkeypatch):
    from media_studio.assets import manifest

    monkeypatch.setattr(manifest, "get_asset", lambda _name: None)
    # settings=None exercises the ``settings or {}`` falsy arm (no manager built).
    assert cs.resolve_yunet_model_path() is None


def test_resolve_yunet_model_path_returns_installed_path(monkeypatch):
    from media_studio.assets import manager, manifest

    monkeypatch.setattr(manifest, "get_asset", lambda _name: object())

    class _Mgr:
        def __init__(self, **_kw):
            pass

        def installed_path(self, _entry):
            return "/models/yunet-face-detection-2023mar.onnx"

    monkeypatch.setattr(manager, "AssetManager", _Mgr)
    # a truthy settings dict exercises the ``settings or {}`` truthy arm.
    assert cs.resolve_yunet_model_path({"modelsDir": "x"}) == "/models/yunet-face-detection-2023mar.onnx"


def test_resolve_yunet_model_path_not_installed_returns_none(monkeypatch):
    from media_studio.assets import manager, manifest

    monkeypatch.setattr(manifest, "get_asset", lambda _name: object())

    class _Mgr:
        def __init__(self, **_kw):
            pass

        def installed_path(self, _entry):
            return None  # registered but not yet downloaded

    monkeypatch.setattr(manager, "AssetManager", _Mgr)
    assert cs.resolve_yunet_model_path({}) is None


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
# TDD (b): a profile/weak-face frame -> motion fallback still locates the speaker
# (v1.2.0 WU1: the HOG person/body fallback was DROPPED — YuNet handles turned
# faces and the imgproc-only motion fallback covers the rest; no second objdetect
# surface). ``_make_face_finder`` now takes (backend, settings).
# --------------------------------------------------------------------------- #
def test_subject_finder_falls_back_to_motion_when_face_absent(monkeypatch):
    """Face detector returns None (profile/turned head) -> MOTION saliency (vs the
    previous frame) still locates the moving speaker. The first frame (no prev)
    yields None; the second resolves via motion."""
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend, settings=None: (lambda img: None, lambda: None))
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: 0.35)
    find, _close = cs._make_subject_finder("yunet")
    assert find("frame0") is None  # no previous frame yet -> motion can't run
    assert find("frame1") == pytest.approx(0.35)  # diff vs frame0 locates motion


def test_subject_finder_face_hit_skips_motion(monkeypatch):
    """When the FACE is found, the motion fallback does not run."""
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend, settings=None: (lambda img: 0.5, lambda: None))
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: pytest.fail("motion must not run on a face hit"))
    find, _close = cs._make_subject_finder("yunet")
    assert find(object()) == pytest.approx(0.5)


def test_subject_finder_center_backend_has_no_finder():
    find, close = cs._make_subject_finder("center")
    assert find is None
    close()  # the no-op closer is callable


def test_subject_finder_no_face_finder_goes_straight_to_motion(monkeypatch):
    """When the FACE backend yields no finder at all, the subject finder skips the
    face step and uses the motion fallback (against the previous frame)."""
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend, settings=None: (None, lambda: None))
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: 0.6)
    find, _close = cs._make_subject_finder("yunet")
    assert find("frame0") is None  # no previous frame yet
    assert find("frame1") == pytest.approx(0.6)


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
        raise RuntimeError("detector exploded")

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
        raise RuntimeError("detector exploded")

    eng, _ = _engine(fake_bins, detector=broken)
    notices: list[dict] = []
    crop, kfs, _d = eng.compute_plan("/in.mp4", on_notice=notices.append)
    # still a centered crop (encode proceeds) ...
    assert kfs == [] and crop["x"] == 437
    # ... but the degrade was reported, not silently swallowed.
    assert len(notices) == 1
    assert notices[0]["type"] == cs.REFRAME_DEGRADED_NOTICE
    assert "center crop" in notices[0]["message"].lower()
    assert "detector exploded" in notices[0]["reason"]


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
# make_degraded_notice — v1.2.0 WU1 simplified (no backend/model-naming). A
# missing YuNet model/backend fails LOUD earlier; this notice only carries a
# genuine per-clip "no subject / detector failed" degrade, never a silent crop.
# --------------------------------------------------------------------------- #
def test_make_degraded_notice_carries_reason_and_type():
    """The typed notice carries the structured type, a human 'center crop'
    message, and the raw reason verbatim for logs/UI attribution."""
    notice = cs.make_degraded_notice("no trackable subject located")
    assert notice["type"] == cs.REFRAME_DEGRADED_NOTICE
    assert "center crop" in notice["message"].lower()
    assert notice["reason"] == "no trackable subject located"
    # no stale model-name enrichment: a single-detector degrade names no backend.
    assert "mediapipe" not in notice["message"].lower()


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


def test_engine_default_backend_probe_calls_detect_backend_with_settings(fake_bins, monkeypatch):
    """The engine's default backend probe calls the real ``detect_backend`` THREADING
    its settings through (v1.2.0 WU2), so the ``reframeTracker`` opt-in is honoured
    from the live import state when not injected."""
    seen: dict = {}

    def fake_detect_backend(importer=None, settings=None):
        seen["settings"] = settings
        return "yunet"

    monkeypatch.setattr(cs, "detect_backend", fake_detect_backend)
    eng, _ = _engine({**fake_bins, "reframeTracker": "yunet"}, detector=lambda p, t: [(0.0, 0.5)])
    assert eng._backend_probe() == "yunet"
    assert seen["settings"] == eng._settings  # settings reach detect_backend


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
# _make_face_finder — the YuNet (cv2.FaceDetectorYN) branch + the center branch.
#
# cv2.FaceDetectorYN is MOCKED (raising=False) and resolve_yunet_model_path is
# stubbed, so these tests NEVER depend on the installed opencv build actually
# shipping the objdetect YuNet class or on the ONNX model being downloaded — the
# hardening "mock the native backend" lesson (CI runs opencv-python-headless).
# --------------------------------------------------------------------------- #
def _yunet_faces(*boxes):
    """An Nx15 YuNet ``detect`` result (rows [x, y, w, h, 10 landmarks, score])."""
    import numpy as np

    arr = np.zeros((len(boxes), 15), dtype=np.float32)
    for i, (x, y, w, h) in enumerate(boxes):
        arr[i, 0:4] = (x, y, w, h)
    return arr


def _install_fake_yunet(monkeypatch, faces, *, model_path="/models/yunet.onnx"):
    """Install a fake cv2.FaceDetectorYN + stub the model resolver.

    ``faces`` is the fixed ``detect`` result (an Nx>=4 array, or None for no
    detections). Returns a record of the create args + per-frame setInputSize
    calls so tests can assert the wiring.
    """
    import cv2

    monkeypatch.setattr(cs, "resolve_yunet_model_path", lambda settings=None: model_path)
    rec: dict = {"created": None, "sizes": []}

    class _Detector:
        def setInputSize(self, size):
            rec["sizes"].append(tuple(size))

        def detect(self, _img):
            return (1, faces)

    class _FaceDetectorYN:
        @staticmethod
        def create(model, config, size, score_threshold=0.0, **_kw):
            rec["created"] = {
                "model": model,
                "config": config,
                "size": tuple(size),
                "score_threshold": score_threshold,
            }
            return _Detector()

    monkeypatch.setattr(cv2, "FaceDetectorYN", _FaceDetectorYN, raising=False)
    return rec


def test_make_face_finder_center_backend_returns_no_finder():
    find, close = cs._make_face_finder("center")
    assert find is None
    close()  # the no-op closer is safely callable


def test_make_face_finder_yunet_returns_normalized_center_on_detection(monkeypatch):
    import numpy as np

    # two faces; the larger (by w*h) wins. frame width below is 400.
    faces = _yunet_faces((10, 10, 20, 20), (300, 10, 60, 60))  # second is larger
    rec = _install_fake_yunet(monkeypatch, faces)
    find, close = cs._make_face_finder("yunet")
    assert callable(find)
    img = np.zeros((120, 400, 3), dtype=np.uint8)  # width 400
    cx = find(img)
    # largest face center x = 300 + 60/2 = 330; normalized = 330/400 = 0.825
    assert cx == pytest.approx(0.825)
    # wiring: created with the resolved model path + per-frame input size (w, h).
    assert rec["created"]["model"] == "/models/yunet.onnx"
    assert rec["created"]["score_threshold"] == pytest.approx(0.6)
    assert rec["sizes"] == [(400, 120)]
    close()


def test_make_face_finder_yunet_no_faces_returns_none(monkeypatch):
    import numpy as np

    # detect returns None (the "faces is not None else []" false arc) -> no subject.
    _install_fake_yunet(monkeypatch, None)
    find, _close = cs._make_face_finder("yunet")
    assert find(np.zeros((60, 120, 3), dtype=np.uint8)) is None


def test_make_face_finder_yunet_two_faces_picks_larger(monkeypatch):
    import numpy as np

    # left small (20x20 @x=20), right large (60x60 @x=300). width = 400.
    faces = _yunet_faces((20, 20, 20, 20), (300, 20, 60, 60))
    _install_fake_yunet(monkeypatch, faces)
    find, _close = cs._make_face_finder("yunet")
    cx = find(np.zeros((120, 400, 3), dtype=np.uint8))
    # larger face center x = 300 + 30 = 330 -> 330/400 = 0.825.
    assert cx == pytest.approx(0.825)


def test_make_face_finder_yunet_active_speaker_motion_tiebreak(monkeypatch):
    import numpy as np

    # two EQUAL-size faces (width 200); the active (moving) one wins the tie.
    faces = _yunet_faces((20, 20, 40, 40), (120, 20, 40, 40))
    _install_fake_yunet(monkeypatch, faces)
    find, _close = cs._make_face_finder("yunet")
    f0 = np.zeros((100, 200, 3), dtype=np.uint8)
    f1 = np.zeros((100, 200, 3), dtype=np.uint8)
    f1[20:60, 120:160, :] = 200  # the RIGHT face box moves (talking)
    find(f0)  # establish previous frame (both quiet -> first/left wins)
    cx = find(f1)
    assert cx == pytest.approx(0.7)  # active (right) speaker: (120 + 20) / 200


def test_make_face_finder_yunet_missing_facedetectoryn_raises(monkeypatch):
    """A cv2 build that imports but lacks cv2.FaceDetectorYN (headless/stripped) is
    a PROVISIONING failure: fail loud with the typed backend error instead of a
    bare AttributeError or a silent center crop (WU no-silent-fallback)."""
    import cv2

    monkeypatch.delattr(cv2, "FaceDetectorYN", raising=False)
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError) as exc:
        cs._make_face_finder("yunet")
    assert "facedetectoryn" in str(exc.value).lower()


def test_make_face_finder_yunet_missing_model_raises(monkeypatch):
    """The YuNet class is present but the sha256-pinned ONNX is NOT provisioned ->
    a LOUD provisioning error (name the asset), never a silent center crop."""
    import cv2

    # FaceDetectorYN present (so the hasattr guard passes) but the model resolves
    # to None (not downloaded).
    monkeypatch.setattr(cv2, "FaceDetectorYN", object(), raising=False)
    monkeypatch.setattr(cs, "resolve_yunet_model_path", lambda settings=None: None)
    with pytest.raises(cs.ClaudeShortsBackendUnavailableError) as exc:
        cs._make_face_finder("yunet")
    msg = str(exc.value).lower()
    assert "yunet" in msg and "provision" in msg


# --------------------------------------------------------------------------- #
# detect_subject_centers — the non-center body (real cv2.imread of fake frames).
# The YuNet backend is MOCKED via _install_fake_yunet (no ONNX download / native
# objdetect dependency); some tests stub _make_face_finder directly.
# --------------------------------------------------------------------------- #
def test_detect_subject_centers_yunet_reads_extracted_frames(monkeypatch):
    import cv2
    import numpy as np

    # Mock a present YuNet that detects no face, so the body runs on a cv2 build
    # that lacks the native objdetect class (CI's opencv-python-headless).
    _install_fake_yunet(monkeypatch, None)

    # A frame_runner that writes a REAL (blank) jpeg to the requested path so
    # cv2.imread succeeds; YuNet finds no face -> no samples appended.
    def frame_runner(argv, capture_output=True, check=False):
        out_path = argv[-1]
        cv2.imwrite(out_path, np.zeros((80, 160, 3), dtype=np.uint8))
        return type("C", (), {"returncode": 0})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5, 1.5], frame_runner=frame_runner, backend="yunet")
    # blank frames -> YuNet finds nothing -> empty sample list, but the body ran
    # (frames extracted + read) without spawning real ffmpeg / an ONNX download.
    assert samples == []


def test_detect_subject_centers_skips_missing_and_unreadable_frames(monkeypatch):
    # Stub the face finder (present, no-face) so building the finder does not touch
    # the real YuNet class/model; exercise the "frame not produced" continue.
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend, settings=None: (lambda img: None, lambda: None))

    # A frame_runner that NEVER writes the frame file -> os.path.exists False ->
    # the frame is skipped (the "frame not produced" continue branch).
    def no_write_runner(argv, capture_output=True, check=False):
        return type("C", (), {"returncode": 1})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=no_write_runner, backend="yunet")
    assert samples == []


def test_detect_subject_centers_skips_unreadable_frame(monkeypatch):
    # The frame file EXISTS but cv2.imread can't decode it (None) -> skipped
    # (the "img is None" continue branch, distinct from "file not produced").
    import cv2

    monkeypatch.setattr(cs, "_make_face_finder", lambda backend, settings=None: (lambda img: 0.5, lambda: None))
    monkeypatch.setattr(cv2, "imread", lambda path: None)  # always unreadable

    def frame_runner(argv, capture_output=True, check=False):
        # Write SOMETHING so os.path.exists is True, but imread (stubbed) -> None.
        with open(argv[-1], "wb") as fh:
            fh.write(b"not-a-real-jpeg")
        return type("C", (), {"returncode": 0})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=frame_runner, backend="yunet")
    assert samples == []


def test_detect_subject_centers_no_finder_backend_returns_empty(monkeypatch):
    # When _make_subject_finder yields no finder (None) the body returns [] early.
    monkeypatch.setattr(cs, "_make_subject_finder", lambda backend, settings=None, **_kw: (None, lambda: None))

    def boom(*a, **k):  # pragma: no cover - must never run (no finder -> no frames)
        raise AssertionError("no frame extraction without a finder")

    assert cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=boom, backend="yunet") == []


def test_detect_subject_centers_collects_when_finder_returns_center(monkeypatch):
    import cv2
    import numpy as np

    # Stub the finder to report a center for every frame so the sample-append
    # branch (cx is not None) is exercised; cv2.imread reads a real jpeg.
    monkeypatch.setattr(cs, "_make_face_finder", lambda backend, settings=None: (lambda img: 0.42, lambda: None))

    def frame_runner(argv, capture_output=True, check=False):
        cv2.imwrite(argv[-1], np.zeros((60, 120, 3), dtype=np.uint8))
        return type("C", (), {"returncode": 0})()

    samples = cs.detect_subject_centers("/in.mp4", [0.5, 1.5], frame_runner=frame_runner, backend="yunet")
    assert samples == [(0.5, 0.42), (1.5, 0.42)]


def test_detect_subject_centers_finder_close_failure_is_swallowed(monkeypatch):
    import cv2
    import numpy as np

    def boom_close():
        raise RuntimeError("close blew up")

    monkeypatch.setattr(cs, "_make_face_finder", lambda backend, settings=None: (lambda img: 0.5, boom_close))

    def frame_runner(argv, capture_output=True, check=False):
        cv2.imwrite(argv[-1], np.zeros((40, 80, 3), dtype=np.uint8))
        return type("C", (), {"returncode": 0})()

    # A failing close() must never mask the collected results (cleanup-swallow).
    samples = cs.detect_subject_centers("/in.mp4", [0.5], frame_runner=frame_runner, backend="yunet")
    assert samples == [(0.5, 0.5)]


def test_detect_subject_centers_threads_settings_into_finder(monkeypatch):
    # The engine's settings must reach _make_subject_finder (and thence the YuNet
    # model resolver) — a regression guard for the settings-plumbing WU1 added.
    seen: dict = {}

    def fake_finder(backend, settings=None, **_kw):
        seen["backend"] = backend
        seen["settings"] = settings
        return (lambda img: None, lambda: None)

    monkeypatch.setattr(cs, "_make_subject_finder", fake_finder)
    cs.detect_subject_centers(
        "/in.mp4",
        [0.5],
        settings={"modelsDir": "/x"},
        frame_runner=lambda *a, **k: type("C", (), {"returncode": 1})(),
        backend="yunet",
    )
    assert seen == {"backend": "yunet", "settings": {"modelsDir": "/x"}}


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


def test_single_speaker_capability_note_is_honest():
    """The honest 'V1 follows a single speaker' capability copy is a real,
    asserted artifact (not just prose) — and points at the V2 switching roadmap."""
    note = cs.SINGLE_SPEAKER_CAPABILITY_NOTE
    assert "single speaker" in note.lower()
    assert "v2" in note.lower()


# --------------------------------------------------------------------------- #
# v1.2.0 WU2 — OPT-IN EdgeTAM occlusion-robust tracker. Every EdgeTAM seam (the
# importer, the checkpoint resolver, the tracker factory) is MOCKED, so the suite
# never depends on torch / the EdgeTAM package / a downloaded checkpoint (the cv2
# whack-a-mole hardening lesson). DEFAULT stays YuNet; EdgeTAM is a settings opt-in.
# --------------------------------------------------------------------------- #
class _FakeTracker:
    """A stand-in EdgeTAM tracker: scripted per-frame cx + a recorded release."""

    def __init__(self, cxs):
        self._cxs = list(cxs)
        self.released = False

    def track(self, _img):
        return self._cxs.pop(0) if self._cxs else None

    def release(self):
        self.released = True


def test_edgetam_error_is_a_backend_unavailable_subclass():
    # So compute_plan's existing "except ClaudeShortsBackendUnavailableError:
    # raise" re-raises an opted-in EdgeTAM failure LOUD (never a per-clip degrade,
    # never a silent fall back to YuNet - WU2 req 2).
    assert issubclass(cs.EdgeTamBackendUnavailableError, cs.ClaudeShortsBackendUnavailableError)
    assert issubclass(cs.EdgeTamBackendUnavailableError, cs.ClaudeShortsReframeError)


def test_detect_backend_defaults_to_yunet_without_opt_in(monkeypatch):
    # No reframeTracker setting -> the DEFAULT YuNet path (cv2 importable).
    monkeypatch.setattr(cs, "resolve_edgetam_model_path", lambda s=None: pytest.fail("edgetam path must not run"))
    assert cs.detect_backend(_importer({"cv2"}), settings={}) == "yunet"
    assert cs.detect_backend(_importer({"cv2"}), settings={"reframeTracker": "yunet"}) == "yunet"


def test_detect_backend_blank_tracker_falls_back_to_yunet():
    # A whitespace-only reframeTracker exercises the "strip().lower() or
    # TRACKER_YUNET" arm -> the YuNet default, not an unknown backend.
    assert cs.detect_backend(_importer({"cv2"}), settings={"reframeTracker": "   "}) == "yunet"


def test_detect_backend_unknown_tracker_falls_back_to_yunet():
    # Any non-edgetam value is the YuNet default (only "edgetam" opts in).
    assert cs.detect_backend(_importer({"cv2"}), settings={"reframeTracker": "sam99"}) == "yunet"


def test_detect_backend_edgetam_opt_in_all_available(monkeypatch):
    # cv2 + torch importable AND the checkpoint provisioned -> "edgetam".
    monkeypatch.setattr(cs, "resolve_edgetam_model_path", lambda s=None: "/models/edgetam.pt")
    assert cs.detect_backend(_importer({"cv2", "torch"}), settings={"reframeTracker": "edgetam"}) == "edgetam"


def test_detect_backend_edgetam_case_insensitive(monkeypatch):
    monkeypatch.setattr(cs, "resolve_edgetam_model_path", lambda s=None: "/models/edgetam.pt")
    assert cs.detect_backend(_importer({"cv2", "torch"}), settings={"reframeTracker": "EdgeTAM"}) == "edgetam"


def test_detect_backend_edgetam_missing_cv2_fails_loud():
    # cv2 (frame decode) missing -> LOUD typed error, never a silent YuNet fallback.
    with pytest.raises(cs.EdgeTamBackendUnavailableError) as exc:
        cs.detect_backend(_importer(set()), settings={"reframeTracker": "edgetam"})
    assert "cv2" in str(exc.value)


def test_detect_backend_edgetam_missing_torch_fails_loud():
    # cv2 present but torch missing -> LOUD typed error (exercises the 2nd loop arm).
    with pytest.raises(cs.EdgeTamBackendUnavailableError) as exc:
        cs.detect_backend(_importer({"cv2"}), settings={"reframeTracker": "edgetam"})
    assert "torch" in str(exc.value)


def test_detect_backend_edgetam_unprovisioned_checkpoint_fails_loud(monkeypatch):
    # torch+cv2 importable but the checkpoint is not downloaded -> LOUD typed error.
    monkeypatch.setattr(cs, "resolve_edgetam_model_path", lambda s=None: None)
    with pytest.raises(cs.EdgeTamBackendUnavailableError) as exc:
        cs.detect_backend(_importer({"cv2", "torch"}), settings={"reframeTracker": "edgetam"})
    assert cs._edgetam_asset_name() in str(exc.value)


def test_edgetam_asset_name_matches_manifest():
    from media_studio.assets import manifest

    assert cs._edgetam_asset_name() == manifest.EDGETAM_ASSET_NAME


def test_resolve_edgetam_model_path_unregistered_returns_none(monkeypatch):
    from media_studio.assets import manifest

    monkeypatch.setattr(manifest, "get_asset", lambda _name: None)
    assert cs.resolve_edgetam_model_path() is None  # settings=None -> falsy arm


def test_resolve_edgetam_model_path_returns_installed_path(monkeypatch):
    from media_studio.assets import manager, manifest

    monkeypatch.setattr(manifest, "get_asset", lambda _name: object())

    class _Mgr:
        def __init__(self, **_kw):
            pass

        def installed_path(self, _entry):
            return "/models/edgetam.pt"

    monkeypatch.setattr(manager, "AssetManager", _Mgr)
    assert cs.resolve_edgetam_model_path({"modelsDir": "x"}) == "/models/edgetam.pt"


def test_resolve_edgetam_model_path_not_installed_returns_none(monkeypatch):
    from media_studio.assets import manager, manifest

    monkeypatch.setattr(manifest, "get_asset", lambda _name: object())

    class _Mgr:
        def __init__(self, **_kw):
            pass

        def installed_path(self, _entry):
            return None

    monkeypatch.setattr(manager, "AssetManager", _Mgr)
    assert cs.resolve_edgetam_model_path({}) is None


def test_make_edgetam_finder_propagates_tracker_and_wires_release():
    tracker = _FakeTracker([0.2, 0.8])
    find, close = cs._make_edgetam_finder({"reframeTracker": "edgetam"}, lambda s: tracker)
    assert find("f0") == pytest.approx(0.2)
    assert find("f1") == pytest.approx(0.8)
    assert find("f2") is None  # tracker exhausted -> lost
    close()
    assert tracker.released is True  # close() == the tracker's release (6 GB stage free)


def test_make_edgetam_finder_factory_failure_propagates_loud():
    def boom(_settings):
        raise cs.EdgeTamBackendUnavailableError("no torch")

    with pytest.raises(cs.EdgeTamBackendUnavailableError):
        cs._make_edgetam_finder({}, boom)


def test_subject_finder_edgetam_primary_hit_skips_motion(monkeypatch):
    tracker = _FakeTracker([0.66])
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: pytest.fail("motion must not run on an edgetam hit"))
    find, close = cs._make_subject_finder("edgetam", {}, edgetam_tracker_factory=lambda s: tracker)
    assert find(object()) == pytest.approx(0.66)
    close()
    assert tracker.released is True


def test_subject_finder_edgetam_miss_falls_back_to_motion(monkeypatch):
    # EdgeTAM lost the subject this frame (None) -> the imgproc-only motion last
    # resort covers the gap. Motion is NOT face tracking, so this is not the
    # "silent fall back to face tracking" WU2 req 2 forbids.
    tracker = _FakeTracker([None, None])
    monkeypatch.setattr(cs, "_motion_center", lambda prev, img: 0.4)
    find, _close = cs._make_subject_finder("edgetam", {}, edgetam_tracker_factory=lambda s: tracker)
    assert find("frame0") is None  # no previous frame yet -> motion can't run
    assert find("frame1") == pytest.approx(0.4)  # motion vs frame0


def test_engine_edgetam_opt_in_tracks_end_to_end(fake_bins, monkeypatch):
    # Full opt-in path: reframeTracker="edgetam", a fake tracker + fake frames,
    # cv2.imread stubbed. The engine crops on the tracked subject, one ffmpeg pass.
    import cv2
    import numpy as np

    settings = {**fake_bins, "reframeTracker": "edgetam"}
    ts = cs.window_timestamps(8.0)
    tracker = _FakeTracker([0.8] * len(ts))
    monkeypatch.setattr(cs, "resolve_edgetam_model_path", lambda s=None: "/models/edgetam.pt")
    # Resolve the backend via the FAKE importer (cv2+torch "present") so neither the
    # engine's backend probe nor detect_subject_centers imports the REAL torch — the
    # heavy import is never a test dependency (the cv2 whack-a-mole lesson; real torch
    # is absent in the CI gate env). The real _detect_edgetam_backend logic still runs.
    monkeypatch.setattr(
        cs,
        "detect_backend",
        lambda importer=None, settings=None: cs._detect_edgetam_backend(_importer({"cv2", "torch"}), settings or {}),
    )
    monkeypatch.setattr(cv2, "imread", lambda path: np.zeros((72, 128, 3), dtype="uint8"))

    def frame_runner(argv, capture_output=True, check=False):
        with open(argv[-1], "wb") as fh:
            fh.write(b"x")
        return type("C", (), {"returncode": 0})()

    runner = _make_ff_runner(0)
    eng = ClaudeShortsReframeEngine(
        settings=settings,
        runner=runner,
        prober=lambda _p: (1280, 720, 8.0),
        detector=lambda p, t: cs.detect_subject_centers(
            p, t, settings=settings, frame_runner=frame_runner, edgetam_tracker_factory=lambda s: tracker
        ),
    )
    eng.reframe("/in.mp4", "/out.mp4")
    vf = _vf_of(runner.calls[0]["argv"])
    x = int(vf.split(":'")[1].split("'")[0])
    assert abs(x - cs.crop_x_for_center(0.8, 405, 1280)) <= 2  # tracked, not center (437)


def test_engine_edgetam_opt_in_unavailable_fails_loud(fake_bins, monkeypatch):
    # Opted IN to EdgeTAM but torch is absent -> compute_plan raises the typed
    # EdgeTamBackendUnavailableError up front (via the real _backend_probe), never a
    # silent fall back to the YuNet default (WU2 req 2). No ffmpeg pass runs.
    settings = {**fake_bins, "reframeTracker": "edgetam"}
    monkeypatch.setattr(
        cs,
        "detect_backend",
        lambda importer=None, settings=None: cs._detect_edgetam_backend(_importer({"cv2"}), settings or {}),
    )
    eng = ClaudeShortsReframeEngine(settings=settings, runner=_make_ff_runner(0), prober=lambda _p: (1280, 720, 8.0))
    with pytest.raises(cs.EdgeTamBackendUnavailableError):
        eng.compute_plan("/in.mp4")
