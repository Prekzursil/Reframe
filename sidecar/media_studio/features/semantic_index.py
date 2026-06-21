"""PURE semantic-index core (WU-A4): build a segment corpus, rank by cosine.

This module is the math/dict half of the semantic index — it never touches a
model, the network, settings, consent, or a budget. Those concerns live in the
embedder seam (``models/embedder.py``, WU-A2) and the ``index.*`` handlers
(WU-A5), which inject already-computed vectors here.

Two functions:

* :func:`build_corpus` flattens a §3 :class:`Transcript` into the list of
  per-segment texts to embed, in segment order.
* :func:`search` ranks already-embedded segment vectors against an
  already-embedded query vector and shapes the top-K hits. The cosine math is
  the EXISTING, length-guarded :func:`diarize.cosine_similarity` — referenced
  through the imported ``diarize`` module (never re-derived) so a dimension
  mismatch surfaces as that function's :class:`ValueError`.

Tie handling is by stable sort: equal-score segments keep their source order,
so a deterministic, lowest-index-first result is returned.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict

from . import diarize

#: A §3 transcript (the same loose dict shape used across features).
Transcript = dict[str, Any]
#: A single dense float vector (one per segment, or the query).
Vector = Sequence[float]


class Hit(TypedDict):
    """One ranked search result, shaped for the renderer (CONTRACTS.md)."""

    segmentIndex: int
    start: float
    end: float
    text: str
    score: float


def build_corpus(transcript: Transcript) -> list[str]:
    """Return the per-segment texts of ``transcript`` in segment order.

    A missing/absent ``segments`` list yields ``[]``; a segment missing ``text``
    contributes the empty string (so corpus length always matches segment count
    and the downstream vectors line up 1:1 with segments).
    """
    segments = transcript.get("segments") or []
    return [str(segment.get("text", "")) for segment in segments]


def search(
    query_vec: Vector,
    segment_vecs: Sequence[Vector],
    segments: Sequence[dict[str, Any]],
    top_k: int,
) -> list[Hit]:
    """Rank ``segments`` by cosine of their vector against ``query_vec``.

    ``segment_vecs[i]`` is the embedding of ``segments[i]``. Each result carries
    the source segment's ``segmentIndex/start/end/text`` plus its cosine
    ``score``. Results are sorted by descending score (ties keep source order via
    a stable sort) and truncated to ``top_k``. A non-positive ``top_k`` or an
    empty corpus yields ``[]``. Dimension mismatches are NOT guarded here — they
    propagate from :func:`diarize.cosine_similarity` as a :class:`ValueError`.
    """
    if top_k <= 0:
        return []
    scored: list[Hit] = []
    for index, (segment, vector) in enumerate(zip(segments, segment_vecs, strict=False)):
        score = diarize.cosine_similarity(query_vec, vector)
        scored.append(
            Hit(
                segmentIndex=index,
                start=float(segment.get("start", 0.0)),
                end=float(segment.get("end", 0.0)),
                text=str(segment.get("text", "")),
                score=score,
            )
        )
    scored.sort(key=lambda hit: hit["score"], reverse=True)
    return scored[:top_k]
