"""Gaze-correction planning, capability probe, and the ethics-gated RPC (C15).

The single most important test in this file is
:func:`TestService.test_run_refuses_without_a_likeness_attestation`: it asserts
that an unattested request is REFUSED and that the heavy backend is never even
constructed. A face-manipulation path that runs before the attestation is checked
is the defect this whole gate exists to prevent, so the assertion is on the
backend factory NOT being called — not merely on the error type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from media_studio.features import gaze
from media_studio.features.gaze import (
    DEFAULT_STRENGTH,
    WARP_RADIUS_FRACTION,
    EyeBox,
    EyePair,
    FacePlan,
    GazeReport,
    SkipReason,
    gaze_available,
    plan_face,
    warp_radius,
)
from media_studio.jobs import JobRegistry
from media_studio.models.likeness import SCOPE_GAZE
from media_studio.protocol import RpcContext, RpcError

FRAME_W, FRAME_H = 640, 480
ATTESTED = {"likenessAttested": True, "likenessSubject": "ada"}


def _rpc_ctx(registry: JobRegistry | None) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def _patch(size: int, iris_offset_x: float = 0.0) -> np.ndarray:
    """A synthetic eye crop with the iris displaced ``iris_offset_x`` px."""
    centre = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size]
    dist = np.hypot(xx - (centre + iris_offset_x), yy - centre)
    patch = np.full((size, size), 230, dtype=np.uint8)
    patch[dist <= max(size * 0.15, 2.0)] = 30
    return patch


def _reader(offset_x: float = 0.0) -> Any:
    """A ``read_patch`` seam returning a synthetic crop for any requested box."""

    def read_patch(box: EyeBox) -> np.ndarray:
        return _patch(box.w, offset_x)

    return read_patch


def _good_pair(score: float = 0.9) -> EyePair:
    return EyePair(right=(220.0, 200.0), left=(320.0, 202.0), score=score)


# --------------------------------------------------------------------------- #
# warp_radius
# --------------------------------------------------------------------------- #
def test_warp_radius_is_a_fraction_of_the_box() -> None:
    assert warp_radius(EyeBox(x=0, y=0, w=40, h=40)) == pytest.approx(40 * WARP_RADIUS_FRACTION)


def test_warp_radius_stays_inside_the_box() -> None:
    # A radius >= half the box would push the falloff past the crop edge, so the
    # eyelid boundary would move. Pin the intent.
    assert WARP_RADIUS_FRACTION < 0.5


def test_warp_radius_is_never_zero_for_a_minimal_box() -> None:
    assert warp_radius(EyeBox(x=0, y=0, w=2, h=2)) > 0.0


# --------------------------------------------------------------------------- #
# plan_face — the pure decision layer
# --------------------------------------------------------------------------- #
def test_plan_face_returns_one_edit_per_eye() -> None:
    plan = plan_face(
        _good_pair(), frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=_reader(-6.0)
    )
    assert plan.skipped is None
    assert len(plan.eyes) == 2


def test_plan_face_shifts_an_offset_iris_toward_centre() -> None:
    # Iris displaced LEFT of the aperture centre -> a positive (rightward) shift.
    plan = plan_face(
        _good_pair(), frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=_reader(-6.0)
    )
    assert all(edit.shift[0] > 0 for edit in plan.eyes)


def test_plan_face_produces_no_shift_for_a_centred_iris() -> None:
    plan = plan_face(
        _good_pair(), frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=_reader(0.0)
    )
    assert plan.skipped is None
    # A symmetric iris centroid lands on the aperture centre to within float
    # noise, so the shift is negligible rather than bit-exact zero. (The
    # bit-exact case is zero STRENGTH, asserted separately below.)
    assert all(edit.shift == pytest.approx((0.0, 0.0), abs=1e-6) for edit in plan.eyes)


def test_plan_face_at_zero_strength_produces_no_shift() -> None:
    plan = plan_face(
        _good_pair(), frame_w=FRAME_W, frame_h=FRAME_H, strength=0.0, read_patch=_reader(-6.0)
    )
    assert all(edit.shift == (0.0, 0.0) for edit in plan.eyes)


def test_plan_face_propagates_a_skip_and_plans_nothing() -> None:
    plan = plan_face(
        _good_pair(score=0.1), frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=_reader(-6.0)
    )
    assert plan.skipped == SkipReason.LOW_CONFIDENCE
    assert plan.eyes == ()


def test_plan_face_never_calls_the_reader_for_a_skipped_face() -> None:
    """A skipped face must not even have its pixels read."""
    calls: list[EyeBox] = []

    def spy(box: EyeBox) -> np.ndarray:
        calls.append(box)
        return _patch(box.w)

    plan_face(_good_pair(score=0.1), frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=spy)
    assert calls == []


def test_plan_face_skips_an_eye_whose_box_falls_outside_the_frame() -> None:
    # Landmarks off-frame (a partially-cropped face): that eye yields no box, so
    # it is dropped while the in-frame eye is still corrected.
    pair = EyePair(right=(-400.0, 200.0), left=(320.0, 200.0), score=0.9)
    plan = plan_face(pair, frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=_reader(-6.0))
    assert plan.skipped is None
    assert len(plan.eyes) == 1


def test_plan_face_carries_the_radius_and_iris_into_each_edit() -> None:
    plan = plan_face(
        _good_pair(), frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=_reader(-6.0)
    )
    edit = plan.eyes[0]
    assert edit.radius == pytest.approx(warp_radius(edit.box))
    assert 0.0 <= edit.iris[0] <= edit.box.w


def test_plan_face_respects_the_max_shift_cap() -> None:
    # An iris pushed to the very edge of the crop demands a shift LARGER than the
    # cap, so this exercises the clamp rather than passing trivially: a real
    # (non-zero) rightward shift that still never exceeds MAX_SHIFT_FRACTION.
    plan = plan_face(
        _good_pair(), frame_w=FRAME_W, frame_h=FRAME_H, strength=1.0, read_patch=_reader(-14.5)
    )
    cap = gaze.max_shift_px(gaze.interocular_px(_good_pair()))
    assert plan.eyes
    assert all(0.0 < edit.shift[0] <= cap + 1e-6 for edit in plan.eyes)


# --------------------------------------------------------------------------- #
# GazeReport
# --------------------------------------------------------------------------- #
def test_gaze_report_round_trips_as_plain_json_types() -> None:
    report = GazeReport(frames_total=10, frames_corrected=7, eyes_corrected=13, skipped={"low-confidence": 3})
    payload = report.as_dict()
    assert payload == {
        "framesTotal": 10,
        "framesCorrected": 7,
        "eyesCorrected": 13,
        "skipped": {"low-confidence": 3},
    }


# --------------------------------------------------------------------------- #
# gaze_available — the capability probe (mirrors stabilize.vidstab_available)
# --------------------------------------------------------------------------- #
def test_gaze_available_true_when_the_yunet_model_resolves() -> None:
    assert gaze_available({}, resolve_model=lambda s: "C:/models/yunet.onnx") is True


def test_gaze_available_false_when_the_model_is_absent() -> None:
    assert gaze_available({}, resolve_model=lambda s: None) is False


def test_gaze_available_false_when_the_resolver_raises() -> None:
    # Any probe failure counts as "not available" — it must never raise.
    def boom(settings: dict[str, Any]) -> str | None:
        raise RuntimeError("asset manager exploded")

    assert gaze_available({}, resolve_model=boom) is False


def test_gaze_available_accepts_no_settings() -> None:
    assert gaze_available(resolve_model=lambda s: "yunet.onnx") is True


# --------------------------------------------------------------------------- #
# the RPC service
# --------------------------------------------------------------------------- #
class _FakeBackend:
    """Records what it was asked to do; returns a canned report.

    Deliberately EXERCISES all three seams the service hands it (``plan``,
    ``on_progress``, ``should_cancel``), because a seam the fake never calls is a
    seam whose wiring no test actually proves.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.released = 0
        self.plans: list[FacePlan] = []
        self.cancel_seen: list[bool] = []

    def process(
        self,
        in_path: str,
        out_path: str,
        *,
        plan: Any,
        on_progress: Any = None,
        should_cancel: Any = None,
    ) -> GazeReport:
        self.calls.append((in_path, out_path))
        self.plans.append(plan(_good_pair(), frame_w=FRAME_W, frame_h=FRAME_H, read_patch=_reader(-6.0)))
        self.cancel_seen.append(bool(should_cancel()))
        on_progress(50.0, "warping")
        return GazeReport(frames_total=4, frames_corrected=3, eyes_corrected=6, skipped={})

    def release(self) -> None:
        self.released += 1


def _service(tmp_path: Path, backend: Any, *, settings: dict[str, Any] | None = None) -> Any:
    created: list[dict[str, Any]] = []

    def factory(resolved: dict[str, Any]) -> Any:
        created.append(resolved)
        return backend

    service = gaze.GazeService(
        resolver=lambda vid: "/lib/in.mp4" if vid == "v1" else None,
        out_dir=tmp_path / "gaze",
        settings_provider=lambda: dict(settings or {}),
        backend_factory=factory,
        available=lambda s: True,
    )
    return service, created


class TestService:
    # ---- the ETHICS gate -------------------------------------------------- #
    def test_run_refuses_without_a_likeness_attestation(self, tmp_path, registry) -> None:
        """The load-bearing ethics assertion: no attestation, no backend, no job."""
        backend = _FakeBackend()
        svc, created = _service(tmp_path, backend)
        with pytest.raises(RpcError, match="likeness"):
            svc.run({"videoId": "v1"}, _rpc_ctx(registry))
        # The refusal happened BEFORE any heavy work was set up.
        assert created == []
        assert backend.calls == []

    def test_run_refuses_an_explicitly_declined_attestation(self, tmp_path, registry) -> None:
        svc, created = _service(tmp_path, _FakeBackend())
        params = {"videoId": "v1", "likenessAttested": False, "likenessSubject": "ada"}
        with pytest.raises(RpcError, match="likeness"):
            svc.run(params, _rpc_ctx(registry))
        assert created == []

    def test_run_refuses_an_attestation_with_no_subject(self, tmp_path, registry) -> None:
        svc, _created = _service(tmp_path, _FakeBackend())
        with pytest.raises(RpcError, match="likeness"):
            svc.run({"videoId": "v1", "likenessAttested": True}, _rpc_ctx(registry))

    def test_run_accepts_a_persisted_attestation(self, tmp_path, registry) -> None:
        settings = {"likeness": {"attestations": {"ada": {"gaze": True}}}}
        svc, _created = _service(tmp_path, _FakeBackend(), settings=settings)
        out = svc.run({"videoId": "v1", "likenessSubject": "ada"}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["likeness"] == {"subject": "ada", "scope": SCOPE_GAZE, "source": "settings"}

    def test_run_records_the_attestation_that_authorised_it(self, tmp_path, registry) -> None:
        svc, _created = _service(tmp_path, _FakeBackend())
        out = svc.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        # An audit trail: WHICH attestation permitted this alteration.
        assert job.result["likeness"] == {"subject": "ada", "scope": SCOPE_GAZE, "source": "request"}

    # ---- normal operation ------------------------------------------------- #
    def test_run_returns_a_job_and_the_report(self, tmp_path, registry) -> None:
        backend = _FakeBackend()
        svc, created = _service(tmp_path, backend)
        out = svc.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(registry))
        assert "jobId" in out
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        assert job.result["report"]["framesCorrected"] == 3
        assert job.result["path"].endswith(".gaze.mp4")
        assert len(created) == 1
        assert backend.released == 1

    def test_run_hands_the_backend_a_working_planner(self, tmp_path, registry) -> None:
        """The planner the service injects must actually plan (not just exist)."""
        backend = _FakeBackend()
        svc, _created = _service(tmp_path, backend)
        out = svc.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        plan = backend.plans[0]
        assert isinstance(plan, FacePlan)
        assert plan.skipped is None
        assert len(plan.eyes) == 2
        # The strength the caller asked for reached the planner: an off-centre
        # iris produced a real correction.
        assert all(edit.shift[0] > 0 for edit in plan.eyes)
        assert backend.cancel_seen == [False]

    def test_run_accepts_an_explicit_path(self, tmp_path, registry) -> None:
        backend = _FakeBackend()
        svc, _created = _service(tmp_path, backend)
        out = svc.run({"path": "/elsewhere/clip.mp4", **ATTESTED}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert backend.calls[0][0] == "/elsewhere/clip.mp4"

    def test_run_defaults_the_strength(self, tmp_path, registry) -> None:
        svc, _created = _service(tmp_path, _FakeBackend())
        out = svc.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert registry.get(out["jobId"]).result["strength"] == pytest.approx(DEFAULT_STRENGTH)

    def test_run_clamps_a_hostile_strength(self, tmp_path, registry) -> None:
        svc, _created = _service(tmp_path, _FakeBackend())
        out = svc.run({"videoId": "v1", "strength": 99.0, **ATTESTED}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert registry.get(out["jobId"]).result["strength"] == pytest.approx(1.0)

    def test_run_releases_the_backend_even_when_processing_raises(self, tmp_path, registry) -> None:
        class Exploding(_FakeBackend):
            def process(self, in_path, out_path, **kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("cuda oom")

        backend = Exploding()
        svc, _created = _service(tmp_path, backend)
        out = svc.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert backend.released == 1  # no leaked model on the failure path

    # ---- refusals --------------------------------------------------------- #
    def test_run_unknown_video_raises(self, tmp_path, registry) -> None:
        svc, _created = _service(tmp_path, _FakeBackend())
        with pytest.raises(RpcError, match="unknown video"):
            svc.run({"videoId": "ghost", **ATTESTED}, _rpc_ctx(registry))

    def test_run_missing_video_id_raises(self, tmp_path, registry) -> None:
        svc, _created = _service(tmp_path, _FakeBackend())
        with pytest.raises(RpcError, match="videoId"):
            svc.run({"videoId": "", **ATTESTED}, _rpc_ctx(registry))

    def test_run_without_a_job_registry_raises(self, tmp_path) -> None:
        svc, _created = _service(tmp_path, _FakeBackend())
        with pytest.raises(RpcError, match="job registry"):
            svc.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(None))

    def test_run_raises_typed_unavailable_when_the_model_is_absent(self, tmp_path, registry) -> None:
        """An EXPLICIT request with YuNet missing NAMES the cause, never degrades."""
        service = gaze.GazeService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "gaze",
            settings_provider=lambda: {},
            backend_factory=lambda s: _FakeBackend(),
            available=lambda s: False,
        )
        out = service.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(registry))
        job = registry.get(out["jobId"])
        job.wait(timeout=5)
        # JobRecord.error is a STRING (jobs.py), so assert on the message: it must
        # NAME the missing asset rather than degrading to a silent pass-through.
        assert job.error is not None
        assert "yunet" in job.error.lower()
        assert job.result is None

    def test_run_settings_provider_raising_yields_empty(self, tmp_path, registry) -> None:
        def boom() -> dict[str, Any]:
            raise RuntimeError("settings exploded")

        service = gaze.GazeService(
            resolver=lambda vid: "/lib/in.mp4",
            out_dir=tmp_path / "gaze",
            settings_provider=boom,
            backend_factory=lambda s: _FakeBackend(),
            available=lambda s: True,
        )
        # Settings failure must not break the op; the per-request attestation still
        # authorises it (a persisted-only attestation would correctly refuse).
        out = service.run({"videoId": "v1", **ATTESTED}, _rpc_ctx(registry))
        registry.get(out["jobId"]).wait(timeout=5)
        assert registry.get(out["jobId"]).result["report"]["framesTotal"] == 4


# --------------------------------------------------------------------------- #
# register()
# --------------------------------------------------------------------------- #
def test_register_wires_exactly_the_gaze_methods(tmp_path) -> None:
    registered: dict[str, Any] = {}
    gaze.register(
        resolver=lambda vid: None,
        out_dir=tmp_path,
        register_fn=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert sorted(registered) == ["gaze.probe", "gaze.run"]


def test_gaze_probe_reports_availability(tmp_path) -> None:
    registered: dict[str, Any] = {}
    gaze.register(
        resolver=lambda vid: None,
        out_dir=tmp_path,
        register_fn=lambda name, fn: registered.__setitem__(name, fn),
        available=lambda s: True,
    )
    assert registered["gaze.probe"]({}, _rpc_ctx(None)) == {"available": True}


def test_gaze_probe_reports_unavailability(tmp_path) -> None:
    registered: dict[str, Any] = {}
    gaze.register(
        resolver=lambda vid: None,
        out_dir=tmp_path,
        register_fn=lambda name, fn: registered.__setitem__(name, fn),
        available=lambda s: False,
    )
    assert registered["gaze.probe"]({}, _rpc_ctx(None)) == {"available": False}


def test_register_uses_the_real_registry_and_defaults_by_default(tmp_path) -> None:
    """No injected seams at all: exercises every production default.

    The autouse ``_restore_methods`` fixture snapshots/restores the global METHODS
    registry, so registering for real here cannot leak into another test.
    """
    from media_studio import protocol

    service = gaze.register(resolver=lambda vid: None, out_dir=tmp_path)
    assert isinstance(service, gaze.GazeService)
    assert "gaze.run" in protocol.METHODS
    assert "gaze.probe" in protocol.METHODS


# --------------------------------------------------------------------------- #
# FacePlan shape
# --------------------------------------------------------------------------- #
def test_face_plan_is_frozen() -> None:
    plan = FacePlan(skipped=None, eyes=())
    with pytest.raises(AttributeError):
        plan.skipped = SkipReason.LOW_CONFIDENCE  # type: ignore[misc]
