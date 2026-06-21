"""Tests for media_studio.features.ocr_list — ``ocrExtractList`` engine (WU-ocr).

The PURE half (frame text-box ordering, cross-frame dedup, poster selection) is
tested with plain dicts/strings — no model, no image decode. The engine is tested
with a FAKE OCR backend whose ``read_text`` returns canned boxes per frame and a
FAKE frame source, plus every degrade gate (empty / blank frames, backend
failure -> typed ``OcrError``) and the per-data-type FRAME-consent gate (a
non-consented vision provider is NEVER reached — the cloud path is refused and the
run falls to local-only). No rapidocr / onnxruntime / cv2 import anywhere.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import ocr_list as ol


# --------------------------------------------------------------------------- #
# helpers / fakes (the injected seams)
# --------------------------------------------------------------------------- #
def box(text: str, top: float = 0.0, left: float = 0.0) -> dict[str, Any]:
    """A minimal OCR box dict (text + top-left anchor for reading order)."""
    return {"text": text, "top": top, "left": left}


class FakeBackend:
    """An OcrBackend whose ``read_text`` returns canned boxes per frame.

    ``per_frame`` is a list aligned to the input frames; each element is the box
    list that frame OCRs to. ``record`` captures the frames seen for assertions.
    """

    def __init__(self, per_frame: list[list[dict[str, Any]]], *, record: dict[str, Any] | None = None) -> None:
        self._per_frame = per_frame
        self._record = record if record is not None else {}
        self._record["frames"] = []

    def read_text(self, frame: Any) -> list[dict[str, Any]]:
        idx = len(self._record["frames"])
        self._record["frames"].append(frame)
        return self._per_frame[idx] if idx < len(self._per_frame) else []


class RaisingBackend:
    """An OcrBackend that always raises (the failure-degrade path)."""

    def read_text(self, frame: Any) -> list[dict[str, Any]]:
        raise RuntimeError("onnxruntime session crashed")


# --------------------------------------------------------------------------- #
# pure: box ordering + dedup + poster selection
# --------------------------------------------------------------------------- #
def test_order_boxes_top_to_bottom_then_left() -> None:
    boxes = [box("c", top=20, left=0), box("a", top=0, left=5), box("b", top=0, left=50)]
    assert ol.order_boxes(boxes) == ["a", "b", "c"]


def test_order_boxes_skips_blank_text() -> None:
    boxes = [box("keep", top=0), box("   ", top=1), box("", top=2)]
    assert ol.order_boxes(boxes) == ["keep"]


def test_order_boxes_empty() -> None:
    assert ol.order_boxes([]) == []


def test_dedup_preserves_first_occurrence_order() -> None:
    assert ol.dedup_lines(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_dedup_strips_and_drops_blank() -> None:
    assert ol.dedup_lines([" a ", "a", "", "  "]) == ["a"]


def test_dedup_empty() -> None:
    assert ol.dedup_lines([]) == []


# --------------------------------------------------------------------------- #
# extract_list — the engine over the injected backend
# --------------------------------------------------------------------------- #
def test_extract_list_orders_and_dedups_across_frames() -> None:
    # frame 0 -> two lines; frame 1 -> a repeat + a new line.
    record: dict[str, Any] = {}
    backend = FakeBackend(
        [
            [box("Question 1", top=0), box("Answer A", top=10)],
            [box("Answer A", top=10), box("Answer B", top=20)],
        ],
        record=record,
    )
    result = ol.extract_list(["f0", "f1"], backend=backend)
    assert result.text == ["Question 1", "Answer A", "Answer B"]
    # poster = the frame that produced the most text lines (frame 0, 2 lines == frame1 2 -> first wins).
    assert result.poster == 0
    assert record["frames"] == ["f0", "f1"]


def test_extract_list_poster_is_richest_frame() -> None:
    backend = FakeBackend(
        [
            [box("one", top=0)],
            [box("a", top=0), box("b", top=10), box("c", top=20)],
            [box("x", top=0), box("y", top=10)],
        ]
    )
    result = ol.extract_list(["f0", "f1", "f2"], backend=backend)
    assert result.poster == 1  # the 3-line frame


def test_extract_list_blank_frames_yield_empty_no_raise() -> None:
    backend = FakeBackend([[], [box("   ")], []])
    result = ol.extract_list(["f0", "f1", "f2"], backend=backend)
    assert result.text == []
    assert result.poster is None  # no frame produced any text


def test_extract_list_no_frames() -> None:
    backend = FakeBackend([])
    result = ol.extract_list([], backend=backend)
    assert result.text == []
    assert result.poster is None


def test_extract_list_backend_raise_is_typed_ocr_error() -> None:
    with pytest.raises(ol.OcrError):
        ol.extract_list(["f0"], backend=RaisingBackend())


# --------------------------------------------------------------------------- #
# FRAME-consent gate (acceptance (b)): a non-consented vision provider is NEVER
# reached — the cloud path is refused and the run falls to local-only.
# --------------------------------------------------------------------------- #
class SpyCloudBackend:
    """A backend that records whether the cloud egress path was ever taken."""

    def __init__(self, hits: list[str]) -> None:
        self._hits = hits

    def read_text(self, frame: Any) -> list[dict[str, Any]]:
        self._hits.append("EGRESS")  # pragma: no cover - must never run when unconsented
        return []


def test_resolve_backend_no_frame_consent_never_reaches_cloud() -> None:
    hits: list[str] = []
    settings = {
        "providers": [{"provider": "openai", "capabilities": ["vision"]}],
        # NO consent.perProvider.openai.frames -> default-deny.
    }
    local = FakeBackend([[box("local")]])
    backend = ol.resolve_ocr_backend(
        settings,
        local_factory=lambda _s: local,
        cloud_factory=lambda _s: SpyCloudBackend(hits),
    )
    # the cloud factory must NOT be selected -> the spy is never constructed/called.
    result = ol.extract_list(["f0"], backend=backend)
    assert result.text == ["local"]
    assert hits == []  # the non-consented cloud provider was never reached


def test_resolve_backend_with_frame_consent_uses_cloud() -> None:
    settings = {
        "providers": [{"provider": "openai", "capabilities": ["vision"]}],
        "consent": {"perProvider": {"openai": {"frames": True}}},
    }
    cloud = FakeBackend([[box("cloud")]])
    backend = ol.resolve_ocr_backend(
        settings,
        local_factory=lambda _s: FakeBackend([[box("local")]]),
        cloud_factory=lambda _s: cloud,
    )
    result = ol.extract_list(["f0"], backend=backend)
    assert result.text == ["cloud"]


def test_resolve_backend_default_factories_are_used_when_absent() -> None:
    # No providers at all -> always local; default local factory is the lazy seam,
    # so inject only the cloud spy and assert the real default local path is chosen
    # by passing an explicit local factory but omitting cloud (defaults to None-safe).
    local = FakeBackend([[box("only-local")]])
    backend = ol.resolve_ocr_backend({}, local_factory=lambda _s: local)
    result = ol.extract_list(["f0"], backend=backend)
    assert result.text == ["only-local"]


def test_resolve_backend_providers_not_a_list_falls_to_local() -> None:
    # A cloud_factory IS supplied, so the consent gate runs; but ``providers`` is
    # not a list (malformed) -> the gate returns False -> local path, cloud unused.
    hits: list[str] = []
    settings = {"providers": "not-a-list"}
    backend = ol.resolve_ocr_backend(
        settings,
        local_factory=lambda _s: FakeBackend([[box("local")]]),
        cloud_factory=lambda _s: SpyCloudBackend(hits),
    )
    result = ol.extract_list(["f0"], backend=backend)
    assert result.text == ["local"]
    assert hits == []


# --------------------------------------------------------------------------- #
# asset registration (version-agnostic: reads whatever the manifest slot resolves)
# --------------------------------------------------------------------------- #
def test_ocr_asset_is_registered_and_version_agnostic() -> None:
    from media_studio.assets import manifest

    entry = manifest.get_asset(ol.ASSET_NAME)
    assert entry is not None
    # the engine MUST NOT hardcode a PP-OCR version: ASSET_NAME has no version token.
    assert "v4" not in ol.ASSET_NAME and "v5" not in ol.ASSET_NAME
