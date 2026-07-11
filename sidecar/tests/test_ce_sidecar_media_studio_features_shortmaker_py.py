"""CE reconcile (Finding #3) — per-export caption OVERRIDE threading.

A ``captionOverride`` dict must flow through ``shortmaker.export()``'s dict-only
guard into the run settings, and ``_lazy_caption`` must forward it to
``CaptionEngine.render(override=...)`` (``None`` when absent). These tests cover
BOTH sides of the new dict-only guard and the new ``settings or {}`` seam so the
media_studio 100% branch gate holds.

Reuses the shared harness from test_shortmaker (RecordingStages, the
registry/transcript fixtures, loader_for, _rpc_ctx) — mirrors the sibling
test_shortmaker_export_delivery module.
"""

from __future__ import annotations

from typing import Any

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


def _maker(tmp_path, transcript, rec):  # noqa: F811
    return sm.ShortMaker(
        load_context=loader_for(str(tmp_path / "talk.mp4"), transcript),
        out_dir_for=lambda vid: str(tmp_path / "out"),
        stages=rec.as_stages(),
    )


# --------------------------------------------------------------------------- #
# export() dict-only guard (both branches)
# --------------------------------------------------------------------------- #
def test_export_handler_threads_caption_override(registry, transcript, tmp_path):  # noqa: F811
    rec = RecordingStages([])
    maker = _maker(tmp_path, transcript, rec)
    override = {"outline": True, "uppercase": True}
    out = maker.export(
        {
            "videoId": "v1",
            "candidates": [dict(_CAND)],
            "captionOverride": override,
        },
        _rpc_ctx(registry),
    )
    job = registry.get(out["jobId"])
    job.wait(timeout=5)
    assert job.error is None  # fail loud if the pipeline raised
    assert rec.caption_kwargs[0]["settings"]["captionOverride"] == override


def test_export_handler_ignores_non_dict_caption_override(registry, transcript, tmp_path):  # noqa: F811
    rec = RecordingStages([])
    maker = _maker(tmp_path, transcript, rec)
    out = maker.export(
        {
            "videoId": "v1",
            "candidates": [dict(_CAND)],
            "captionOverride": "not-a-dict",
        },
        _rpc_ctx(registry),
    )
    job = registry.get(out["jobId"])
    job.wait(timeout=5)
    assert job.error is None
    assert "captionOverride" not in rec.caption_kwargs[0]["settings"]


# --------------------------------------------------------------------------- #
# _lazy_caption -> CaptionEngine.render(override=...) + the ``settings or {}`` seam
# --------------------------------------------------------------------------- #
def _capture_render(monkeypatch, settings) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class FakeLibass:
        def __init__(self, s):
            pass

        def render(self, clip, cues, out, **kw):
            captured["kw"] = kw
            return out

    import media_studio.features.caption as cap

    monkeypatch.setattr(cap, "CaptionEngine", FakeLibass)
    sm._lazy_caption(
        "clip.mp4",
        [],
        "out.mp4",
        source_start=0.0,
        burn=True,
        width=1080,
        height=1920,
        settings=settings,
    )
    return captured["kw"]


def test_lazy_caption_threads_override_dict(monkeypatch):
    # settings is a truthy dict -> the ``settings or {}`` seam takes the dict.
    override = {"card": True}
    kw = _capture_render(
        monkeypatch,
        {"captionStyle": "libass", "subtitleMode": "burn", "captionOverride": override},
    )
    assert kw["override"] == override


def test_lazy_caption_override_none_when_absent(monkeypatch):
    # settings=None exercises the falsy side of the new ``settings or {}`` seam;
    # an absent override resolves to None (render/build_ass tolerate None).
    kw = _capture_render(monkeypatch, None)
    assert kw["override"] is None
