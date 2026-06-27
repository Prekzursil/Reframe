"""P4 §4 — subtitle DELIVERY + caption position through run_export + the export
handler. Reuses the shared harness from test_shortmaker (RecordingStages, the
registry/transcript fixtures, loader_for, _rpc_ctx)."""

from __future__ import annotations

from media_studio.features import shortmaker as sm

# `registry` is a conftest fixture (auto-available — no import needed).
from .test_shortmaker import (  # type: ignore[attr-defined]
    RecordingStages,
    _rpc_ctx,
    loader_for,
    make_ctx,
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


def test_run_export_softmux_sets_burn_false(transcript, tmp_path):  # noqa: F811
    rec = RecordingStages([])
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[dict(_CAND)],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"subtitleMode": "softmux"},
    )
    assert rec.caption_kwargs[0]["burn"] is False


def test_run_export_burn_mode_burns(transcript, tmp_path):  # noqa: F811
    rec = RecordingStages([])
    sm.run_export(
        make_ctx(),
        video_id="v1",
        candidates=[dict(_CAND)],
        load_context=loader_for(str(tmp_path / "src.mp4"), transcript),
        out_dir=str(tmp_path / "out"),
        stages=rec.as_stages(),
        settings={"subtitleMode": "burn"},
    )
    assert rec.caption_kwargs[0]["burn"] is True


def _maker(tmp_path, transcript, rec):  # noqa: F811
    return sm.ShortMaker(
        load_context=loader_for(str(tmp_path / "talk.mp4"), transcript),
        out_dir_for=lambda vid: str(tmp_path / "out"),
        stages=rec.as_stages(),
    )


def test_export_handler_threads_subtitle_mode_and_position(registry, transcript, tmp_path):  # noqa: F811
    rec = RecordingStages([])
    maker = _maker(tmp_path, transcript, rec)
    box = {"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.15}
    out = maker.export(
        {
            "videoId": "v1",
            "candidates": [dict(_CAND)],
            "subtitleMode": "sidecar",
            "captionPosition": box,
        },
        _rpc_ctx(registry),
    )
    registry.get(out["jobId"]).wait(timeout=5)
    cap = rec.caption_kwargs[0]
    assert cap["settings"]["subtitleMode"] == "sidecar"
    assert cap["settings"]["captionPosition"] == box
    assert cap["burn"] is False  # sidecar delivery never burns


def test_export_handler_ignores_non_dict_caption_position(registry, transcript, tmp_path):  # noqa: F811
    rec = RecordingStages([])
    maker = _maker(tmp_path, transcript, rec)
    out = maker.export(
        {
            "videoId": "v1",
            "candidates": [dict(_CAND)],
            "captionPosition": "not-a-dict",
        },
        _rpc_ctx(registry),
    )
    registry.get(out["jobId"]).wait(timeout=5)
    assert "captionPosition" not in rec.caption_kwargs[0]["settings"]
