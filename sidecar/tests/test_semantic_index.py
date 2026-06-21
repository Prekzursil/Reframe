"""Tests for media_studio.features.semantic_index — the PURE semantic-search core.

This WU (WU-A4) is logic-independent of the embedder/handlers: the segment
corpus is built from a §3 transcript, and ``search`` ranks already-computed
segment vectors against an already-computed query vector via the EXISTING
``diarize.cosine_similarity`` (no re-derived math, no model, no network). All
tests inject hand-built vectors so cosine ordering is fully deterministic.
"""

from __future__ import annotations

import pytest
from media_studio.features import diarize, semantic_index


# --------------------------------------------------------------------------- #
# build_corpus
# --------------------------------------------------------------------------- #
class TestBuildCorpus:
    def test_extracts_segment_texts_in_order(self):
        transcript = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello world"},
                {"start": 1.0, "end": 2.0, "text": "second segment"},
            ]
        }
        assert semantic_index.build_corpus(transcript) == ["hello world", "second segment"]

    def test_empty_transcript_returns_empty_list(self):
        assert semantic_index.build_corpus({}) == []

    def test_empty_segments_returns_empty_list(self):
        assert semantic_index.build_corpus({"segments": []}) == []

    def test_missing_text_defaults_to_empty_string(self):
        transcript = {"segments": [{"start": 0.0, "end": 1.0}]}
        assert semantic_index.build_corpus(transcript) == [""]

    def test_non_string_text_coerced_to_str(self):
        transcript = {"segments": [{"text": 42}]}
        assert semantic_index.build_corpus(transcript) == ["42"]


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def _segments() -> list[dict[str, object]]:
    return [
        {"start": 0.0, "end": 1.0, "text": "alpha"},
        {"start": 1.0, "end": 2.0, "text": "beta"},
        {"start": 2.0, "end": 3.0, "text": "gamma"},
    ]


class TestSearch:
    def test_orders_by_descending_cosine_and_truncates(self):
        # query aligns most with the 2nd vector, then 1st, then 3rd.
        segment_vecs = [
            [1.0, 0.0],  # cos vs query = ~0.707
            [1.0, 1.0],  # cos vs query = 1.0
            [0.0, 1.0],  # cos vs query = ~0.707 (tie with idx 0)
        ]
        query_vec = [1.0, 1.0]
        hits = semantic_index.search(query_vec, segment_vecs, _segments(), top_k=2)
        assert [h["segmentIndex"] for h in hits] == [1, 0]
        assert len(hits) == 2
        # descending order on score
        assert hits[0]["score"] >= hits[1]["score"]

    def test_tie_preserves_source_order(self):
        # idx 0 and idx 2 tie; stable sort keeps the lower source index first.
        segment_vecs = [[1.0, 0.0], [-1.0, 0.0], [1.0, 0.0]]
        query_vec = [1.0, 0.0]
        hits = semantic_index.search(query_vec, segment_vecs, _segments(), top_k=3)
        assert [h["segmentIndex"] for h in hits] == [0, 2, 1]

    def test_empty_corpus_returns_empty(self):
        assert semantic_index.search([1.0, 0.0], [], [], top_k=5) == []

    def test_top_k_larger_than_corpus_returns_all(self):
        segment_vecs = [[1.0, 0.0], [0.0, 1.0]]
        hits = semantic_index.search([1.0, 0.0], segment_vecs, _segments()[:2], top_k=99)
        assert len(hits) == 2

    def test_top_k_zero_returns_empty(self):
        segment_vecs = [[1.0, 0.0]]
        assert semantic_index.search([1.0, 0.0], segment_vecs, _segments()[:1], top_k=0) == []

    def test_top_k_negative_returns_empty(self):
        segment_vecs = [[1.0, 0.0]]
        assert semantic_index.search([1.0, 0.0], segment_vecs, _segments()[:1], top_k=-3) == []

    def test_hit_carries_source_segment_fields(self):
        segment_vecs = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
        query_vec = [1.0, 0.0]
        hits = semantic_index.search(query_vec, segment_vecs, _segments(), top_k=1)
        top = hits[0]
        assert top["segmentIndex"] == 0
        assert top["start"] == 0.0
        assert top["end"] == 1.0
        assert top["text"] == "alpha"
        assert top["score"] == pytest.approx(1.0)

    def test_hit_defaults_for_missing_segment_fields(self):
        segment_vecs = [[1.0, 0.0]]
        hits = semantic_index.search([1.0, 0.0], segment_vecs, [{}], top_k=1)
        top = hits[0]
        assert top["start"] == 0.0
        assert top["end"] == 0.0
        assert top["text"] == ""

    def test_dimension_mismatch_delegates_to_cosine_similarity(self):
        # the length guard lives in cosine_similarity (diarize.py) — search must
        # NOT re-derive it, so the same ValueError propagates.
        with pytest.raises(ValueError, match="length mismatch"):
            semantic_index.search([1.0, 0.0], [[1.0, 0.0, 0.0]], _segments()[:1], top_k=1)

    def test_uses_diarize_cosine_similarity(self, monkeypatch):
        calls: list[tuple[object, object]] = []
        real = diarize.cosine_similarity

        def spy(a, b):
            calls.append((list(a), list(b)))
            return real(a, b)

        monkeypatch.setattr(semantic_index.diarize, "cosine_similarity", spy)
        semantic_index.search([1.0, 0.0], [[1.0, 0.0]], _segments()[:1], top_k=1)
        assert calls == [([1.0, 0.0], [1.0, 0.0])]
