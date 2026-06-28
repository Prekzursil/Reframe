"""Tests for media_studio.features.smolvlm2 — Tier-2 SmolVLM2 re-rank seam (WU8).

The PURE half (prompt build, reply parse into a full permutation, reorder) is
tested with plain strings + dicts — no model, no video. The :class:`SmolVlmReranker`
is tested with a FAKE backend whose ``rank_clips`` returns canned per-clip scores
and a FAKE clip-frame loader returning synthetic stacks, plus every degrade gate
(empty / single / top_k<=1, backend failure, score-count mismatch, off-by-default
None seam, the offline build gate). No transformers / torch import anywhere.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import smolvlm2 as sv


# --------------------------------------------------------------------------- #
# helpers / fakes (the injected seams)
# --------------------------------------------------------------------------- #
def cand(start: float = 0.0, end: float = 30.0, hook: str = "", why: str = "") -> dict[str, Any]:
    """A minimal Candidate-shaped dict for the re-ranker."""
    return {"start": start, "end": end, "hook": hook, "why": why, "rank": 0}


class FakeBackend:
    """A SmolVlmBackend whose rank_clips returns canned per-clip scores.

    ``scores`` may be a list (returned verbatim) or a callable ``(frames,
    prompt) -> list``. ``record`` captures the call args for assertions.
    """

    def __init__(self, scores: Any, *, record: dict[str, Any] | None = None) -> None:
        self._scores = scores
        self._record = record if record is not None else {}

    def rank_clips(self, frames_per_clip: Any, prompt: str) -> list[float]:
        self._record["prompt"] = prompt
        self._record["n_clips"] = len(list(frames_per_clip))
        if callable(self._scores):
            return list(self._scores(frames_per_clip, prompt))
        return list(self._scores)


class RaisingBackend:
    """A SmolVlmBackend that always raises (the failure-degrade path)."""

    def rank_clips(self, frames_per_clip: Any, prompt: str) -> list[float]:
        raise RuntimeError("model OOM")


def make_factory(backend: Any, record: dict[str, Any] | None = None) -> Any:
    """A backend_factory returning ``backend``; records the settings it got."""

    def factory(settings: Any) -> Any:
        if record is not None:
            record["settings"] = settings
        return backend

    return factory


def fake_loader(record: dict[str, Any] | None = None) -> Any:
    """A clip-frame loader returning one synthetic stack per span."""

    def loader(path: str, spans: Any) -> list[Any]:
        spans_list = list(spans)
        if record is not None:
            record["path"] = path
            record["spans"] = spans_list
        return [[f"frame@{lo}-{hi}"] for lo, hi in spans_list]

    return loader


# --------------------------------------------------------------------------- #
# pure: build_rerank_prompt
# --------------------------------------------------------------------------- #
class TestBuildRerankPrompt:
    def test_numbers_clips_with_hook(self):
        prompt = sv.build_rerank_prompt([cand(hook="A bold claim"), cand(hook="A twist")])
        assert "[0] A bold claim" in prompt
        assert "[1] A twist" in prompt
        assert "BEST to worst" in prompt

    def test_falls_back_to_why_then_generic(self):
        prompt = sv.build_rerank_prompt([cand(hook="", why="the payoff"), cand(hook="", why="")])
        assert "[0] the payoff" in prompt
        assert "[1] (clip)" in prompt

    def test_custom_instruction_override(self):
        prompt = sv.build_rerank_prompt([cand(hook="x")], instruction="Rank by humor.")
        assert prompt.startswith("Rank by humor.")
        assert "[0] x" in prompt

    def test_blank_instruction_uses_default(self):
        # An override that is only whitespace falls back to the default lead-in.
        prompt = sv.build_rerank_prompt([cand(hook="x")], instruction="   ")
        assert "BEST to worst" in prompt

    def test_empty_candidates_is_just_instruction(self):
        prompt = sv.build_rerank_prompt([])
        assert "\n" not in prompt
        assert "BEST to worst" in prompt


# --------------------------------------------------------------------------- #
# pure: parse_rerank_order (the n-mismatch guard -> always a full permutation)
# --------------------------------------------------------------------------- #
class TestParseRerankOrder:
    def test_simple_csv(self):
        assert sv.parse_rerank_order("2,0,1", 3) == [2, 0, 1]

    def test_extracts_from_prose(self):
        assert sv.parse_rerank_order("Best is clip 1, then 0 and finally 2.", 3) == [1, 0, 2]

    def test_omitted_indices_appended_ascending(self):
        # Model only named clip 2 -> 0 and 1 appended in order (full permutation).
        assert sv.parse_rerank_order("2", 3) == [2, 0, 1]

    def test_out_of_range_ignored_then_filled(self):
        # 9 is out of range; 1 kept, then 0 and 2 appended.
        assert sv.parse_rerank_order("9, 1", 3) == [1, 0, 2]

    def test_duplicates_dropped(self):
        assert sv.parse_rerank_order("0, 0, 1, 1", 3) == [0, 1, 2]

    def test_no_indices_is_identity(self):
        assert sv.parse_rerank_order("no numbers here", 3) == [0, 1, 2]

    def test_empty_text_is_identity(self):
        assert sv.parse_rerank_order("", 2) == [0, 1]

    def test_multi_digit_indices(self):
        assert sv.parse_rerank_order("11,0", 12)[:2] == [11, 0]

    def test_zero_n_is_empty(self):
        assert sv.parse_rerank_order("0,1", 0) == []

    def test_negative_n_is_empty(self):
        assert sv.parse_rerank_order("0", -1) == []


# --------------------------------------------------------------------------- #
# pure: reorder_by_indices
# --------------------------------------------------------------------------- #
class TestReorderByIndices:
    def test_applies_permutation(self):
        cands = [cand(hook="a"), cand(hook="b"), cand(hook="c")]
        out = sv.reorder_by_indices(cands, [2, 0, 1])
        assert [c["hook"] for c in out] == ["c", "a", "b"]

    def test_returns_copies_not_mutating_input(self):
        cands = [cand(hook="a")]
        out = sv.reorder_by_indices(cands, [0], scores=[0.5])
        out[0]["hook"] = "MUTATED"
        assert cands[0]["hook"] == "a"
        assert sv.SCORE_FIELD not in cands[0]

    def test_stamps_clamped_score_by_original_index(self):
        cands = [cand(hook="a"), cand(hook="b")]
        out = sv.reorder_by_indices(cands, [1, 0], scores=[0.2, 1.9])
        # b was original index 1 (score 1.9 -> clamped 1.0), a index 0 (0.2)
        assert out[0]["hook"] == "b" and out[0][sv.SCORE_FIELD] == 1.0
        assert out[1]["hook"] == "a" and out[1][sv.SCORE_FIELD] == 0.2

    def test_out_of_range_index_skipped(self):
        cands = [cand(hook="a")]
        assert sv.reorder_by_indices(cands, [5, 0]) == [{**cand(hook="a")}]

    def test_no_scores_omits_score_field(self):
        out = sv.reorder_by_indices([cand(hook="a")], [0])
        assert sv.SCORE_FIELD not in out[0]

    def test_score_index_past_scores_len_omitted(self):
        # order references idx 1 but scores has only 1 entry -> no field stamped.
        cands = [cand(hook="a"), cand(hook="b")]
        out = sv.reorder_by_indices(cands, [0, 1], scores=[0.5])
        assert out[0][sv.SCORE_FIELD] == 0.5
        assert sv.SCORE_FIELD not in out[1]


# --------------------------------------------------------------------------- #
# SmolVlmReranker.rerank_top_k
# --------------------------------------------------------------------------- #
class TestRerankTopK:
    def test_reorders_top_slice_leaves_tail(self):
        record: dict[str, Any] = {}
        cands = [cand(hook=h) for h in ("a", "b", "c", "d")]
        # scores favor index 1 then 0 within the top-2 slice
        backend = FakeBackend([0.3, 0.9], record=record)
        rr = sv.SmolVlmReranker(backend_factory=make_factory(backend), clip_frame_loader=fake_loader())
        out = rr.rerank_top_k(cands, top_k=2)
        assert [c["hook"] for c in out] == ["b", "a", "c", "d"]  # tail c,d untouched
        assert out[0][sv.SCORE_FIELD] == 0.9
        assert record["n_clips"] == 2  # only the top slice went to the model

    def test_top_k_clamped_to_len(self):
        cands = [cand(hook="a"), cand(hook="b")]
        backend = FakeBackend([0.1, 0.8])
        rr = sv.SmolVlmReranker(backend_factory=make_factory(backend), clip_frame_loader=fake_loader())
        out = rr.rerank_top_k(cands, top_k=99)
        assert [c["hook"] for c in out] == ["b", "a"]

    def test_empty_is_noop(self):
        rr = sv.SmolVlmReranker(backend_factory=make_factory(FakeBackend([])), clip_frame_loader=fake_loader())
        assert rr.rerank_top_k([], top_k=10) == []

    def test_single_candidate_noop_returns_copy(self):
        cands = [cand(hook="a")]
        rr = sv.SmolVlmReranker(backend_factory=make_factory(FakeBackend([0.9])), clip_frame_loader=fake_loader())
        out = rr.rerank_top_k(cands, top_k=10)
        assert [c["hook"] for c in out] == ["a"]
        out[0]["hook"] = "X"
        assert cands[0]["hook"] == "a"  # copy, not the original

    def test_top_k_one_is_noop(self):
        cands = [cand(hook="a"), cand(hook="b")]
        rr = sv.SmolVlmReranker(backend_factory=make_factory(FakeBackend([0.1])), clip_frame_loader=fake_loader())
        assert [c["hook"] for c in rr.rerank_top_k(cands, top_k=1)] == ["a", "b"]

    def test_backend_failure_keeps_input_order(self):
        cands = [cand(hook="a"), cand(hook="b")]
        rr = sv.SmolVlmReranker(backend_factory=make_factory(RaisingBackend()), clip_frame_loader=fake_loader())
        assert [c["hook"] for c in rr.rerank_top_k(cands, top_k=2)] == ["a", "b"]

    def test_score_count_mismatch_keeps_input_order(self):
        cands = [cand(hook="a"), cand(hook="b")]
        backend = FakeBackend([0.9])  # only 1 score for 2 clips
        rr = sv.SmolVlmReranker(backend_factory=make_factory(backend), clip_frame_loader=fake_loader())
        assert [c["hook"] for c in rr.rerank_top_k(cands, top_k=2)] == ["a", "b"]

    def test_uses_default_top_k(self):
        # No top_k -> TOP_K_DEFAULT; 3 < default so all three are reordered.
        cands = [cand(hook=h) for h in ("a", "b", "c")]
        backend = FakeBackend([0.1, 0.2, 0.9])
        rr = sv.SmolVlmReranker(backend_factory=make_factory(backend), clip_frame_loader=fake_loader())
        assert [c["hook"] for c in rr.rerank_top_k(cands)] == ["c", "b", "a"]

    def test_spans_passed_to_loader(self):
        record: dict[str, Any] = {}
        cands = [cand(start=1.0, end=5.0, hook="a"), cand(start=6.0, end=9.0, hook="b")]
        rr = sv.SmolVlmReranker(
            backend_factory=make_factory(FakeBackend([0.5, 0.6])),
            clip_frame_loader=fake_loader(record),
            media_path="/v.mp4",
        )
        rr.rerank_top_k(cands, top_k=2)
        assert record["path"] == "/v.mp4"
        assert record["spans"] == [(1.0, 5.0), (6.0, 9.0)]

    def test_missing_start_end_default_to_zero(self):
        record: dict[str, Any] = {}
        cands = [{"hook": "a"}, {"hook": "b"}]  # no start/end keys
        rr = sv.SmolVlmReranker(
            backend_factory=make_factory(FakeBackend([0.5, 0.6])),
            clip_frame_loader=fake_loader(record),
        )
        rr.rerank_top_k(cands, top_k=2)
        assert record["spans"] == [(0.0, 0.0), (0.0, 0.0)]

    def test_instruction_threaded_into_prompt(self):
        record: dict[str, Any] = {}
        cands = [cand(hook="a"), cand(hook="b")]
        rr = sv.SmolVlmReranker(
            backend_factory=make_factory(FakeBackend([0.5, 0.6], record=record)),
            clip_frame_loader=fake_loader(),
            instruction="Rank by surprise.",
        )
        rr.rerank_top_k(cands, top_k=2)
        assert record["prompt"].startswith("Rank by surprise.")

    def test_settings_passed_to_factory(self):
        record: dict[str, Any] = {}
        cands = [cand(hook="a"), cand(hook="b")]
        rr = sv.SmolVlmReranker(
            settings={"k": "v"},
            backend_factory=make_factory(FakeBackend([0.1, 0.2]), record=record),
            clip_frame_loader=fake_loader(),
        )
        rr.rerank_top_k(cands, top_k=2)
        assert record["settings"] == {"k": "v"}


# --------------------------------------------------------------------------- #
# build_reranker (the opt-in / offline gate)
# --------------------------------------------------------------------------- #
class TestBuildReranker:
    def test_returns_reranker_when_models_present(self):
        rr = sv.build_reranker(models_present=lambda s: True, backend_factory=make_factory(FakeBackend([])))
        assert isinstance(rr, sv.SmolVlmReranker)

    def test_none_when_missing_and_offline(self):
        rr = sv.build_reranker(settings={"offline": True}, models_present=lambda s: False)
        assert rr is None

    def test_reranker_when_missing_but_online(self):
        # Missing weights but online -> a download could fetch them: build it.
        rr = sv.build_reranker(settings={"offline": False}, models_present=lambda s: False)
        assert isinstance(rr, sv.SmolVlmReranker)

    def test_threads_seams_through(self):
        record: dict[str, Any] = {}
        rr = sv.build_reranker(
            settings={"a": 1},
            media_path="/x.mp4",
            models_present=lambda s: True,
            backend_factory=make_factory(FakeBackend([0.4, 0.5]), record=record),
            clip_frame_loader=fake_loader(),
            instruction="hi",
        )
        assert rr is not None
        out = rr.rerank_top_k([cand(hook="a"), cand(hook="b")], top_k=2)
        assert len(out) == 2
        assert record["settings"] == {"a": 1}


# --------------------------------------------------------------------------- #
# default_models_present (asset-manager lookup; failure -> False)
# --------------------------------------------------------------------------- #
class TestDefaultModelsPresent:
    def test_unknown_asset_is_false(self, monkeypatch: pytest.MonkeyPatch):
        # When the asset is NOT registered, the manifest lookup returns None -> False.
        # F3c: the module now self-registers smolvlm2-2.2b at import, and a dev box
        # may have the snapshot in its HF cache (installed_path would then be truthy),
        # so force get_asset -> None to exercise this branch deterministically (no
        # host-HF-cache dependency) — mirrors test_saliency's equivalent.
        from media_studio.assets import manifest as real_manifest

        monkeypatch.setattr(real_manifest, "get_asset", lambda _name: None)
        assert sv.default_models_present({}) is False

    def test_registered_and_installed_is_true(self, monkeypatch: pytest.MonkeyPatch):
        # Patch the REAL modules' attributes (the function imports them lazily by
        # name, so attribute patching is what it actually resolves).
        from media_studio.assets import manager as real_manager
        from media_studio.assets import manifest as real_manifest

        sentinel_entry = object()
        monkeypatch.setattr(real_manifest, "get_asset", lambda name: sentinel_entry)

        class _Mgr:
            def __init__(self, *, settings_provider: Any) -> None:
                self._sp = settings_provider

            def installed_path(self, entry: Any) -> str:
                # exercise the settings_provider lambda (dict(settings)) + entry passthrough
                assert entry is sentinel_entry
                assert self._sp() == {"x": 1}
                return "/cache/smolvlm2"

        monkeypatch.setattr(real_manager, "AssetManager", _Mgr)
        assert sv.default_models_present({"x": 1}) is True

    def test_get_asset_none_is_false(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manifest as real_manifest

        monkeypatch.setattr(real_manifest, "get_asset", lambda name: None)
        assert sv.default_models_present({}) is False

    def test_machinery_exception_swallowed_to_false(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manifest as real_manifest

        def boom(name: str) -> Any:
            raise RuntimeError("asset machinery broken")

        monkeypatch.setattr(real_manifest, "get_asset", boom)
        assert sv.default_models_present({}) is False


# --------------------------------------------------------------------------- #
# CloudVlmBackend (WU-vision) — offloads the Tier-2 re-rank to a vision-capable
# rotation pool. The pool arrives via CLOSURE (BackendFactory signature is
# unchanged); a FAKE pool returns a canned ranking reply. base64 frame encoding
# is behind an injectable seam so no cv2/PIL is imported under the gate.
# --------------------------------------------------------------------------- #
class FakePool:
    """A duck-typed rotation pool whose ``chat`` returns a canned reply.

    ``reply`` may be a string (returned verbatim) or a callable
    ``(messages, **kwargs) -> str``. ``calls`` records every chat invocation so a
    test can assert the capability filter + that base64 frames reached the pool.
    """

    def __init__(self, reply: Any) -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: Any, **kwargs: Any) -> str:
        msgs = [dict(m) for m in messages]
        self.calls.append({"messages": msgs, "kwargs": kwargs})
        if callable(self._reply):
            return str(self._reply(msgs, **kwargs))
        return str(self._reply)


class RaisingPool:
    """A pool whose ``chat`` always raises (the failure-degrade path)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: Any, **kwargs: Any) -> str:
        self.calls.append({"messages": list(messages)})
        raise RuntimeError("pool exhausted")


def _img_parts(call: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the image_url content parts out of a recorded FakePool chat call."""
    content = call["messages"][-1]["content"]
    return [p for p in content if isinstance(p, dict) and p.get("type") == "image_url"]


class TestScoresFromOrder:
    def test_descending_scores_reproduce_order(self) -> None:
        # order [2,0,1] -> idx2 best (1.0), idx0 mid (0.5), idx1 worst (0.0)
        scores = sv._scores_from_order([2, 0, 1], 3)
        assert scores == [0.5, 0.0, 1.0]
        # feeding back through _order_from_scores reproduces the input order
        assert sv._order_from_scores(scores) == [2, 0, 1]

    def test_single_clip_is_one(self) -> None:
        assert sv._scores_from_order([0], 1) == [1.0]

    def test_n_le_zero_is_empty(self) -> None:
        assert sv._scores_from_order([], 0) == []
        assert sv._scores_from_order([0], -1) == []

    def test_out_of_range_index_skipped(self) -> None:
        # a defensively out-of-range index leaves its (absent) slot untouched.
        scores = sv._scores_from_order([5, 0], 2)
        assert scores[0] == 0.0  # position 1 -> (1-1)/1 = 0.0
        assert scores[1] == 0.0  # idx 5 ignored; slot 1 never written


class TestCloudVlmBackend:
    def test_ranks_clips_into_scores_descending_by_reply_order(self) -> None:
        # The cloud VLM says clip 2 is best, then 0, then 1.
        pool = FakePool("2,0,1")
        backend = sv.CloudVlmBackend(pool=pool, settings={}, frame_encoder=lambda f: f"b64:{f}")
        scores = backend.rank_clips([["fA"], ["fB"], ["fC"]], "rank these")
        assert len(scores) == 3
        # best (idx 2) > then idx 0 > then idx 1
        assert scores[2] > scores[0] > scores[1]

    def test_sends_base64_frames_through_vision_capability(self) -> None:
        pool = FakePool("0,1")
        backend = sv.CloudVlmBackend(pool=pool, settings={}, frame_encoder=lambda f: f"ENC<{f}>")
        backend.rank_clips([["x"], ["y", "z"]], "prompt text")
        assert len(pool.calls) == 1
        call = pool.calls[0]
        assert call["kwargs"]["capability"] == "vision"
        # the prompt text rode along as a text part
        text_parts = [p for p in call["messages"][-1]["content"] if p.get("type") == "text"]
        assert any("prompt text" in p["text"] for p in text_parts)
        # every sampled frame was base64-encoded into an image_url data part
        images = _img_parts(call)
        assert len(images) == 3  # 1 + 2 frames
        assert all("ENC<" in img["image_url"]["url"] for img in images)

    def test_empty_clips_returns_empty_without_calling_pool(self) -> None:
        pool = FakePool("0")
        backend = sv.CloudVlmBackend(pool=pool, settings={}, frame_encoder=lambda f: "b")
        assert backend.rank_clips([], "p") == []
        assert pool.calls == []

    def test_pool_failure_propagates_for_reranker_noop(self) -> None:
        # CloudVlmBackend does NOT swallow; SmolVlmReranker's try/except degrades to
        # identity order (so a cloud failure leaves the order unchanged).
        backend = sv.CloudVlmBackend(pool=RaisingPool(), settings={}, frame_encoder=lambda f: "b")
        with pytest.raises(RuntimeError):
            backend.rank_clips([["a"], ["b"]], "p")

    def test_reranker_uses_cloud_backend_to_reorder(self) -> None:
        # End-to-end: a cloud backend injected via the factory reorders the top slice.
        pool = FakePool("1,0")  # clip 1 best
        cands = [cand(hook="a"), cand(hook="b"), cand(hook="c")]
        rr = sv.SmolVlmReranker(
            backend_factory=lambda settings: sv.CloudVlmBackend(
                pool=pool, settings=settings, frame_encoder=lambda f: "b"
            ),
            clip_frame_loader=fake_loader(),
        )
        out = rr.rerank_top_k(cands, top_k=2)
        assert [c["hook"] for c in out] == ["b", "a", "c"]  # tail c untouched

    def test_n_mismatch_reply_degrades_to_identity(self) -> None:
        # A reply naming only out-of-range / no valid indices yields identity order;
        # SmolVlmReranker then keeps the input order (no-op).
        pool = FakePool("no valid indices here")
        cands = [cand(hook="a"), cand(hook="b")]
        rr = sv.SmolVlmReranker(
            backend_factory=lambda settings: sv.CloudVlmBackend(
                pool=pool, settings=settings, frame_encoder=lambda f: "b"
            ),
            clip_frame_loader=fake_loader(),
        )
        # identity order -> scores descending by index -> same order kept
        assert [c["hook"] for c in rr.rerank_top_k(cands, top_k=2)] == ["a", "b"]

    def test_honors_model_and_sampling_settings(self) -> None:
        record: dict[str, Any] = {}

        def reply(messages: Any, **kwargs: Any) -> str:
            record.update(kwargs)
            return "0,1"

        pool = FakePool(reply)
        backend = sv.CloudVlmBackend(
            pool=pool,
            settings={"visionModel": "gemini-flash", "visionMaxTokens": 256},
            frame_encoder=lambda f: "b",
        )
        backend.rank_clips([["a"], ["b"]], "p")
        assert record["capability"] == "vision"
        assert record["max_tokens"] == 256


# --------------------------------------------------------------------------- #
# module surface
# --------------------------------------------------------------------------- #
def test_constants_and_exports():
    assert sv.MODEL_ID == "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
    assert sv.ASSET_NAME == "smolvlm2-2.2b"
    assert sv.TOP_K_DEFAULT == 10
    assert sv.FRAMES_PER_CLIP > 0
    assert sv.SMOLVLM_VRAM_MB == 5200
    for name in sv.__all__:
        assert hasattr(sv, name)
