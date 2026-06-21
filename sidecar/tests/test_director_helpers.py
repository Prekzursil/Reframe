"""Tests for the pure Director helper transforms (WU-plan-rpc, features/director.py).

PURE-logic only: build the validator facts + the fenced media understanding from
a manifest, the deterministic source anchor, and a unique plan id — no provider,
no I/O. These back the thin ``director.*`` RPC handlers.
"""

from __future__ import annotations

from media_studio.features.director import (
    build_understanding,
    new_plan_id,
    source_hash,
)
from media_studio.features.edit_validate import Understanding


def test_new_plan_id_is_unique_and_prefixed() -> None:
    a = new_plan_id()
    b = new_plan_id()
    assert a.startswith("plan-")
    assert a != b


def test_source_hash_is_deterministic_and_path_duration_sensitive() -> None:
    h1 = source_hash("/v/a.mp4", 12000)
    assert h1 == source_hash("/v/a.mp4", 12000)  # deterministic
    assert h1 != source_hash("/v/b.mp4", 12000)  # path-sensitive
    assert h1 != source_hash("/v/a.mp4", 13000)  # duration-sensitive
    assert len(h1) == 16


def test_build_understanding_collects_tracks_and_fences_transcript() -> None:
    data = {
        "transcript": "hello world",
        "tracks": [
            {"id": "t1", "kind": "caption"},
            {"id": "t2"},
            {"kind": "no-id"},  # skipped (no id)
            "junk",  # skipped (not a mapping)
        ],
    }
    understanding, media = build_understanding(data, duration_ms=12000)
    assert isinstance(understanding, Understanding)
    assert understanding.clip_duration_ms == 12000
    assert understanding.tracks == ("t1", "t2")
    assert media["durationMs"] == 12000
    assert media["tracks"] == ["t1", "t2"]
    assert media["transcript"] == "hello world"


def test_build_understanding_without_transcript_or_tracks() -> None:
    understanding, media = build_understanding({}, duration_ms=5000)
    assert understanding.tracks == ()
    assert media["tracks"] == []
    assert "transcript" not in media  # absent transcript omitted from the fence


def test_build_understanding_ignores_non_list_tracks() -> None:
    understanding, _media = build_understanding({"tracks": "not-a-list"}, duration_ms=1)
    assert understanding.tracks == ()
