import json

from media_core.segment.shorts import (
    SegmentCandidate,
    score_segments_heuristic,
    score_segments_llm,
)


def test_score_segments_heuristic_counts_keywords():
    cands = [
        SegmentCandidate(start=0, end=10, snippet="This has keyword apple"),
        SegmentCandidate(start=11, end=20, snippet="No match here"),
    ]
    out = score_segments_heuristic(cands, keywords=["apple"])
    scores = [c.score for c in out]
    assert scores[0] > scores[1]


def test_score_segments_llm_uses_client_response():
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages):
                    payload = json.loads(messages[-1]["content"])
                    scores = [
                        {"start": c["start"], "end": c["end"], "score": idx + 1}
                        for idx, c in enumerate(payload["candidates"])
                    ]

                    class Choice:
                        def __init__(self, content):
                            self.message = type("m", (), {"content": content})

                    class Resp:
                        def __init__(self, choices):
                            self.choices = choices

                    return Resp([Choice(json.dumps(scores))])

    cands = [SegmentCandidate(start=0, end=5), SegmentCandidate(start=6, end=9)]
    out = score_segments_llm(
        transcript="",
        candidates=cands,
        prompt="score",
        model="fake-model",
        client=FakeClient(),
    )
    assert out[0].score == 1
    assert out[1].score == 2
