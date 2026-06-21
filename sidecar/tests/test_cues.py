"""Unit tests for media_studio.features.cues (P4 §2/C6/C7: captions.cues).

WORD-level cues for the live preview overlay, built from a persisted transcript
via an injected context loader (Services._shortmaker_context in production). No
library/whisper/ffmpeg/network: the loader is a fake returning a transcript dict.
Mirrors the test style of test_shorts.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import cues as cu
from media_studio.protocol import RpcContext, RpcError


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def transcript(segments: list[dict[str, Any]], language: str = "en") -> dict[str, Any]:
    return {"language": language, "segments": segments}


WORD_SEGMENTS = [
    {
        "start": 0.0,
        "end": 2.0,
        "text": "Hello world.",
        "words": [
            {"text": "Hello", "start": 0.0, "end": 1.0},
            {"text": "world.", "start": 1.0, "end": 2.0},
        ],
    },
    {
        "start": 2.0,
        "end": 3.5,
        "text": "Big secret.",
        "words": [
            {"text": "Big", "start": 2.0, "end": 2.7},
            {"text": "secret.", "start": 2.7, "end": 3.5},
        ],
    },
]


# --------------------------------------------------------------------------- #
# word_cues — the pure flattener
# --------------------------------------------------------------------------- #
def test_word_cues_emits_word_level_cues() -> None:
    out = cu.word_cues(transcript(WORD_SEGMENTS))
    # WORD-level: 4 words across 2 segments (not 2 segment cues).
    assert [c["text"] for c in out] == ["Hello", "world.", "Big", "secret."]
    # source-absolute seconds, contract shape {index,start,end,text}, 1..N.
    assert [c["index"] for c in out] == [1, 2, 3, 4]
    assert out[0] == {"index": 1, "start": 0.0, "end": 1.0, "text": "Hello"}
    assert out[2]["start"] == 2.0 and out[2]["end"] == 2.7


def test_word_cues_falls_back_to_segment_when_no_words() -> None:
    segs = [{"start": 0.0, "end": 2.0, "text": "No words here", "words": []}]
    out = cu.word_cues(transcript(segs))
    assert out == [{"index": 1, "start": 0.0, "end": 2.0, "text": "No words here"}]


def test_word_cues_skips_blank_and_untimed_and_zero_length() -> None:
    segs = [
        {
            "start": 0.0,
            "end": 5.0,
            "text": "x",
            "words": [
                {"text": "  ", "start": 0.0, "end": 1.0},  # blank -> skip
                {"text": "kept", "start": 1.0, "end": 2.0},  # kept
                {"text": "bad", "start": None, "end": 2.0},  # untimed -> skip
                {"text": "zero", "start": 3.0, "end": 3.0},  # zero len -> skip
                {"text": "neg", "start": 5.0, "end": 4.0},  # negative -> skip
            ],
        }
    ]
    out = cu.word_cues(transcript(segs))
    assert [c["text"] for c in out] == ["kept"]
    assert out[0]["index"] == 1  # renumbered over the kept cues


def test_word_cues_empty_transcript() -> None:
    assert cu.word_cues(None) == []
    assert cu.word_cues({}) == []
    assert cu.word_cues({"segments": []}) == []


# --------------------------------------------------------------------------- #
# captions.cues RPC — {videoId} -> {cues: Cue[]}
# --------------------------------------------------------------------------- #
def test_captions_cues_returns_word_level_cues() -> None:
    loaded: list[str] = []

    def loader(video_id: str) -> dict[str, Any]:
        loaded.append(video_id)
        return {"path": "/v.mp4", "transcript": transcript(WORD_SEGMENTS)}

    svc = cu.Cues(load_context=loader)
    out = svc.cues({"videoId": "vid-1"}, ctx())
    assert loaded == ["vid-1"]
    assert "cues" in out
    assert [c["text"] for c in out["cues"]] == ["Hello", "world.", "Big", "secret."]


def test_captions_cues_requires_video_id() -> None:
    svc = cu.Cues(load_context=lambda v: {})
    with pytest.raises(RpcError):
        svc.cues({}, ctx())


def test_captions_cues_missing_transcript_returns_empty() -> None:
    svc = cu.Cues(load_context=lambda v: {"path": "/v.mp4", "transcript": None})
    assert svc.cues({"videoId": "v"}, ctx()) == {"cues": []}


def test_captions_cues_loader_failure_returns_empty() -> None:
    def boom(video_id: str) -> dict[str, Any]:
        raise RuntimeError("library exploded")

    svc = cu.Cues(load_context=boom)
    # A load miss is non-fatal: the overlay just shows nothing.
    assert svc.cues({"videoId": "v"}, ctx()) == {"cues": []}


# --------------------------------------------------------------------------- #
# register — wires captions.cues via the injected registrar (C6)
# --------------------------------------------------------------------------- #
def test_register_wires_captions_cues() -> None:
    registered: dict[str, Any] = {}
    svc = cu.register(
        load_context=lambda v: {"transcript": transcript(WORD_SEGMENTS)},
        register_fn=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "captions.cues" in registered
    assert isinstance(svc, cu.Cues)
    # the registered callable is the bound method and returns the same shape
    out = registered["captions.cues"]({"videoId": "v"}, ctx())
    assert [c["text"] for c in out["cues"]] == ["Hello", "world.", "Big", "secret."]
