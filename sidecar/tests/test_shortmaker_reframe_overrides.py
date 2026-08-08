"""v1.5 O-2 — the per-shot re-render PARAMETER in the export path.

SCOPE.md:41-44 names two prerequisites for the orphaned ReframeOverridePanel:
"a trace producer surfaced over RPC PLUS a per-shot re-render parameter in the
export path". The trace producer is `reframe.shotPlanFor` + the decision
sidecar; this module covers the second half — a `reframeOverrides` export param,
keyed by the produced clip path the user corrected, that reaches the reframe
stage and makes it re-render only the shots that changed.

Reuses the shared harness from test_shortmaker (RecordingStages, the
registry/transcript fixtures, loader_for, _rpc_ctx), mirroring the sibling
test_ce_sidecar_media_studio_features_shortmaker_py module.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import reframe_override as ro
from media_studio.features import shortmaker as sm

# `registry` is a conftest fixture (auto-available — no import needed).
from .test_shortmaker import (  # type: ignore[attr-defined]
    RecordingStages,
    _rpc_ctx,
    loader_for,
    transcript,  # noqa: F401  (pytest fixture, used by name)
)

_CAND = {
    "rank": 1,
    "start": 0.0,
    "end": 25.0,
    "durationSec": 25.0,
    "hook": "h",
    "why": "w",
    "score": 9,
    "sourceStart": 0.0,
}

_OVERRIDE = [{"index": 0, "speaker": "b"}]


class _ReframeCapture(RecordingStages):
    """Records the settings each reframe stage call saw."""

    def __init__(self, calls: list[str]) -> None:
        super().__init__(calls)
        self.reframe_settings: list[dict[str, Any]] = []

    def reframe(self, in_path, out_path, aspect, *, settings=None, on_notice=None):
        self.reframe_settings.append(dict(settings or {}))
        return super().reframe(in_path, out_path, aspect, settings=settings, on_notice=on_notice)


def _maker(tmp_path, transcript, rec):  # noqa: F811
    return sm.ShortMaker(
        load_context=loader_for(str(tmp_path / "talk.mp4"), transcript),
        out_dir_for=lambda _vid: str(tmp_path / "out"),
        stages=rec.as_stages(),
    )


def _run(maker, registry, params):
    out = maker.export(params, _rpc_ctx(registry))
    job = registry.get(out["jobId"])
    job.wait(timeout=5)
    return job


# --------------------------------------------------------------------------- #
# export() param -> per-clip run settings
# --------------------------------------------------------------------------- #
def test_export_threads_the_overrides_to_the_clip_they_target(registry, transcript, tmp_path):  # noqa: F811
    # The real sequence: export once, correct the produced clip, re-export the
    # same candidate keyed by THAT clip path (what the gallery holds).
    first = _ReframeCapture([])
    maker = _maker(tmp_path, transcript, first)
    job = _run(maker, registry, {"videoId": "v1", "candidates": [dict(_CAND)]})
    assert job.error is None
    clip = job.result["clips"][0]["path"]

    rec = _ReframeCapture([])
    maker = _maker(tmp_path, transcript, rec)
    job = _run(
        maker,
        registry,
        {"videoId": "v1", "candidates": [dict(_CAND)], "reframeOverrides": {clip: _OVERRIDE}},
    )
    assert job.error is None
    assert rec.reframe_settings[0][sm.REFRAME_SHOT_OVERRIDES_KEY] == _OVERRIDE


def test_export_ignores_a_non_dict_reframe_overrides(registry, transcript, tmp_path):  # noqa: F811
    rec = _ReframeCapture([])
    maker = _maker(tmp_path, transcript, rec)
    job = _run(
        maker,
        registry,
        {"videoId": "v1", "candidates": [dict(_CAND)], "reframeOverrides": "nope"},
    )
    assert job.error is None
    assert sm.REFRAME_SHOT_OVERRIDES_KEY not in rec.reframe_settings[0]


def test_an_override_that_matches_no_exported_clip_fails_loud(registry, transcript, tmp_path):  # noqa: F811
    # A silent miss is the worst outcome: the user corrects a shot, the export
    # succeeds, and nothing changed. Fail instead.
    rec = _ReframeCapture([])
    maker = _maker(tmp_path, transcript, rec)
    job = _run(
        maker,
        registry,
        {"videoId": "v1", "candidates": [dict(_CAND)], "reframeOverrides": {"/no/such/clip.mp4": _OVERRIDE}},
    )
    assert job.error is not None
    assert "no exported clip" in str(job.error)


def test_a_clip_with_no_entry_keeps_plain_settings(registry, transcript, tmp_path):  # noqa: F811
    rec = _ReframeCapture([])
    maker = _maker(tmp_path, transcript, rec)
    job = _run(maker, registry, {"videoId": "v1", "candidates": [dict(_CAND)]})
    assert job.error is None
    assert sm.REFRAME_SHOT_OVERRIDES_KEY not in rec.reframe_settings[0]


# --------------------------------------------------------------------------- #
# _lazy_reframe -> the engine's correction path
# --------------------------------------------------------------------------- #
class _RerenderEngine:
    def __init__(self) -> None:
        self.rerendered: list[tuple[str, str, list[ro.ShotOverride]]] = []
        self.plain = 0

    def reframe(self, _i, out, _a, *, on_notice=None):
        self.plain += 1
        return out

    def rerender_with_overrides(self, in_path, out_path, overrides):
        self.rerendered.append((in_path, out_path, list(overrides)))
        return out_path


class _PlainEngine:
    def reframe(self, _i, out, _a, *, on_notice=None):
        return out


def _patch_engine(monkeypatch, engine):
    from media_studio.features import reframe

    monkeypatch.setattr(reframe, "get_engine", lambda _n, _s: (engine, None))


def test_lazy_reframe_takes_the_correction_path_when_overrides_are_present(monkeypatch):
    engine = _RerenderEngine()
    _patch_engine(monkeypatch, engine)
    out = sm._lazy_reframe(
        "/in.mp4",
        "/out.mp4",
        "9:16",
        settings={"reframeEngine": "reframe_multispeaker", sm.REFRAME_SHOT_OVERRIDES_KEY: _OVERRIDE},
    )
    assert out == "/out.mp4"
    assert engine.plain == 0
    assert engine.rerendered[0][2] == [ro.ShotOverride(index=0, speaker="b")]


def test_lazy_reframe_is_loud_when_the_engine_cannot_honour_a_correction(monkeypatch):
    # Silently running a normal reframe would discard the user's correction and
    # hand back a clip that looks re-rendered but is not.
    _patch_engine(monkeypatch, _PlainEngine())
    with pytest.raises(ValueError, match="cannot apply per-shot reframe corrections"):
        sm._lazy_reframe(
            "/in.mp4",
            "/out.mp4",
            "9:16",
            settings={"reframeEngine": "claudeshorts", sm.REFRAME_SHOT_OVERRIDES_KEY: _OVERRIDE},
        )


def test_lazy_reframe_is_loud_on_a_malformed_override(monkeypatch):
    _patch_engine(monkeypatch, _RerenderEngine())
    with pytest.raises(ro.OverrideError):
        sm._lazy_reframe(
            "/in.mp4",
            "/out.mp4",
            "9:16",
            settings={"reframeEngine": "reframe_multispeaker", sm.REFRAME_SHOT_OVERRIDES_KEY: ["nope"]},
        )
