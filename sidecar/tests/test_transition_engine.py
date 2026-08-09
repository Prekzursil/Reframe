"""Unit tests for the ``transition`` op kind: model, validator, and engine adapter.

The pure filtergraph math lives in ``test_transitions.py``; this file covers the
WIRING — that ``transition`` is a real op kind, survives the validate-and-reject
pass, dispatches to a real engine, re-points the COPY manifest, and records a
restore-inverse so ``director.undo`` round-trips (the same contract every other
wired kind satisfies).

The ONE impure thing — the ffmpeg subprocess — is the injected ``runner``, faked
here to stub the output file and record both the argv AND the ``total_sec``
progress denominator, because that denominator is where a transition provably
differs from a join: it is the OVERLAP-SUBTRACTED duration, not the sum.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.features import director_op_engines as engines_mod
from media_studio.features import transitions as tr
from media_studio.features.director_op_engines import (
    RESTORE_KEY,
    WIRED_KINDS,
    DirectorEngineError,
    build_engines,
)
from media_studio.features.edit_validate import Understanding, validate_and_reject
from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import OP_KINDS, EditOp, EditPlan


class TransitionRunner:
    """Fake ffmpeg runner: stubs the output file, records argv + total_sec."""

    def __init__(self, *, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []
        self.totals: list[float] = []

    def __call__(self, argv: Any, total_sec: float = 0.0, **_k: Any) -> int:
        self.calls.append(list(argv))
        self.totals.append(total_sec)
        if self.code == 0:
            Path(argv[-1]).write_bytes(b"\x00rendered")
        return self.code


def _copy(tmp_path: Path) -> ProjectCopy:
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\x00source")
    manifest = tmp_path / ".director-copy" / "project.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    return ProjectCopy(data={"video": {"path": str(src)}}, manifest_path=manifest)


def _stub_probes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    durations: dict[str, float] | None = None,
    default_duration: float = 12.0,
    dims: tuple[int, int] = (1920, 1080),
) -> None:
    table = durations or {}
    monkeypatch.setattr(
        engines_mod._ffmpeg,
        "ffprobe_duration",
        lambda path, *_a, **_k: table.get(str(path), default_duration),
    )
    monkeypatch.setattr(engines_mod._shorts, "probe_dims", lambda *_a, **_k: dims)


def _extra(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(b"\x00clip")
    return str(path)


# --------------------------------------------------------------------------- #
# the op kind exists end to end
# --------------------------------------------------------------------------- #


def test_transition_is_a_model_op_kind() -> None:
    assert "transition" in OP_KINDS


def test_transition_is_wired_to_a_real_engine() -> None:
    assert "transition" in WIRED_KINDS
    assert "transition" in build_engines(runner=TransitionRunner())
    # It is NOT a deferred kind: deferral would mean per-op `failed` + rollback.
    assert "transition" not in engines_mod.DEFERRED_KINDS


# --------------------------------------------------------------------------- #
# validate-and-reject
# --------------------------------------------------------------------------- #


def _plan(op: EditOp) -> EditPlan:
    return EditPlan(plan_id="p", video_id="v", goal="g", source_hash="h", ops=(op,))


def test_validator_keeps_a_transition_with_clips() -> None:
    op = EditOp(id="t1", kind="transition", params={"clips": ["/b.mp4"]})
    result = validate_and_reject(_plan(op), understanding=Understanding(clip_duration_ms=60_000))
    assert result.ops[0].status == "planned"


def test_validator_drops_a_transition_with_nothing_to_join() -> None:
    # A transition is a BOUNDARY treatment — with one clip there is no boundary.
    op = EditOp(id="t1", kind="transition", params={})
    result = validate_and_reject(_plan(op), understanding=Understanding(clip_duration_ms=60_000))
    assert result.ops[0].status == "dropped"
    assert result.ops[0].status_reason == "precondition-unmet"


def test_validator_does_not_require_a_span_for_a_transition() -> None:
    # A boundary op acts on the junction between clips, not on a source range.
    op = EditOp(id="t1", kind="transition", span=None, params={"clips": ["/b.mp4"]})
    result = validate_and_reject(_plan(op), understanding=Understanding(clip_duration_ms=60_000))
    assert result.ops[0].status == "planned"


# --------------------------------------------------------------------------- #
# forward render
# --------------------------------------------------------------------------- #


def test_transition_renders_an_xfade_and_repoints_the_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probes(monkeypatch)
    runner = TransitionRunner()
    pc = _copy(tmp_path)
    before = pc.data["video"]["path"]
    op = EditOp(id="t1", kind="transition", params={"clips": [_extra(tmp_path, "b.mp4")]})

    inverse = build_engines(runner=runner)["transition"](op, pc)

    argv = runner.calls[0]
    graph = argv[argv.index("-filter_complex") + 1]
    assert argv.count("-i") == 2
    # The default style is a cross-dissolve -> xfade's `fade`, 500ms, starting at
    # 12.0 - 0.5 = 11.5s into the first clip.
    assert "xfade=transition=fade:duration=0.500:offset=11.500" in graph
    assert "acrossfade=d=0.500" in graph
    assert pc.data["video"]["path"] != before
    assert inverse.params[RESTORE_KEY] == before


def test_transition_honours_style_and_duration_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probes(monkeypatch)
    runner = TransitionRunner()
    op = EditOp(
        id="t1",
        kind="transition",
        params={"clips": [_extra(tmp_path, "b.mp4")], "style": "wipeLeft", "durationMs": 1500},
    )

    build_engines(runner=runner)["transition"](op, _copy(tmp_path))

    graph = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    assert "xfade=transition=wipeleft:duration=1.500:offset=10.500" in graph


def test_transition_conforms_to_the_probed_source_geometry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # xfade refuses mismatched geometry, so every input is conformed to the
    # SOURCE clip's real probed size — not a hardcoded 1080x1920.
    _stub_probes(monkeypatch, dims=(1280, 720))
    runner = TransitionRunner()
    op = EditOp(id="t1", kind="transition", params={"clips": [_extra(tmp_path, "b.mp4")]})

    build_engines(runner=runner)["transition"](op, _copy(tmp_path))

    graph = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in graph
    assert graph.count("scale=1280:720") == 2


def test_transition_progress_total_subtracts_the_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # THE distinguishing behaviour vs join: 10s + 20s with a 1s transition is a
    # 29s output, not 30s. Asserted on the progress denominator, which is the one
    # place the adapter has to have done the overlap math itself.
    src = _copy(tmp_path)
    other = _extra(tmp_path, "b.mp4")
    _stub_probes(monkeypatch, durations={src.data["video"]["path"]: 10.0, other: 20.0})
    runner = TransitionRunner()
    op = EditOp(id="t1", kind="transition", params={"clips": [other], "durationMs": 1000})

    build_engines(runner=runner)["transition"](op, src)

    assert runner.totals[0] == pytest.approx(29.0)


def test_transition_chains_three_clips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probes(monkeypatch)
    runner = TransitionRunner()
    op = EditOp(
        id="t1",
        kind="transition",
        params={"clips": [_extra(tmp_path, "b.mp4"), _extra(tmp_path, "c.mp4")]},
    )

    build_engines(runner=runner)["transition"](op, _copy(tmp_path))

    argv = runner.calls[0]
    graph = argv[argv.index("-filter_complex") + 1]
    assert argv.count("-i") == 3
    assert graph.count("xfade=") == 2
    assert argv[argv.index("-map") + 1] == "[vx2]"


# --------------------------------------------------------------------------- #
# undo
# --------------------------------------------------------------------------- #


def test_transition_inverse_restores_without_rerendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probes(monkeypatch)
    runner = TransitionRunner()
    pc = _copy(tmp_path)
    original = pc.data["video"]["path"]
    engine = build_engines(runner=runner)["transition"]
    inverse = engine(EditOp(id="t1", kind="transition", params={"clips": [_extra(tmp_path, "b.mp4")]}), pc)
    rendered = pc.data["video"]["path"]

    reinverse = engine(inverse, pc)

    assert pc.data["video"]["path"] == original
    assert reinverse.params[RESTORE_KEY] == rendered
    assert len(runner.calls) == 1  # the undo re-pointed; it did NOT re-render


# --------------------------------------------------------------------------- #
# every failure is a typed DirectorEngineError (per-op failed + auto-rollback)
# --------------------------------------------------------------------------- #


def test_transition_requires_clips(tmp_path: Path) -> None:
    with pytest.raises(DirectorEngineError, match="non-empty params\\['clips'\\]"):
        build_engines(runner=TransitionRunner())["transition"](EditOp(id="t", kind="transition"), _copy(tmp_path))


def test_transition_error_message_names_the_op_kind(tmp_path: Path) -> None:
    # The shared clips guard is used by BOTH join and transition, so it must not
    # tell a transition user their "join op" is malformed.
    with pytest.raises(DirectorEngineError, match="transition op"):
        build_engines(runner=TransitionRunner())["transition"](EditOp(id="t", kind="transition"), _copy(tmp_path))


def test_transition_rejects_an_unknown_style(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probes(monkeypatch)
    op = EditOp(id="t", kind="transition", params={"clips": [_extra(tmp_path, "b.mp4")], "style": "starWipe"})
    with pytest.raises(DirectorEngineError, match="unknown transition style"):
        build_engines(runner=TransitionRunner())["transition"](op, _copy(tmp_path))


def test_transition_rejects_a_clip_shorter_than_the_transition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pc = _copy(tmp_path)
    other = _extra(tmp_path, "b.mp4")
    _stub_probes(monkeypatch, durations={pc.data["video"]["path"]: 10.0, other: 0.4})
    op = EditOp(id="t", kind="transition", params={"clips": [other], "durationMs": 1000})
    with pytest.raises(DirectorEngineError, match="shorter than"):
        build_engines(runner=TransitionRunner())["transition"](op, pc)


def test_transition_rejects_unprobeable_geometry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # probe_dims returns (0, 0) on ANY failure. Scaling to 0x0 would emit a
    # broken filtergraph, so this must fail the op, not render garbage.
    _stub_probes(monkeypatch, dims=(0, 0))
    op = EditOp(id="t", kind="transition", params={"clips": [_extra(tmp_path, "b.mp4")]})
    with pytest.raises(DirectorEngineError, match="could not probe .* dimensions"):
        build_engines(runner=TransitionRunner())["transition"](op, _copy(tmp_path))


def test_transition_surfaces_a_non_zero_ffmpeg_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_probes(monkeypatch)
    op = EditOp(id="t", kind="transition", params={"clips": [_extra(tmp_path, "b.mp4")]})
    with pytest.raises(DirectorEngineError, match="ffmpeg exit 1"):
        build_engines(runner=TransitionRunner(code=1))["transition"](op, _copy(tmp_path))


# --------------------------------------------------------------------------- #
# the re-encode disclosure is reachable from the engine module
# --------------------------------------------------------------------------- #


def test_engine_module_reexports_the_reencode_disclosure() -> None:
    # The UI reads this through the RPC surface; keeping it importable from the
    # engine module means the cost cannot be wired without the disclosure.
    assert "re-encode" in engines_mod.transition_reencode_note(2)
    assert engines_mod.transition_reencode_note(2) == tr.reencode_note(2)
