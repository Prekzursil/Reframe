"""Tests for the WU-A5 ``index.*`` handlers (semantic index build/search/status).

Heavy-free: the embedder is exercised TWO ways, deliberately —

* a **wholesale** injected ``embedder`` fake (short-circuits resolution) drives the
  happy-path / cache / status / idempotency cases without any provider wiring;
* a **transport-level** seam (the REAL :class:`embedder.CloudEmbedder` over a fake
  ``embed_transport``) drives the privacy proofs: with text consent GRANTED the
  fake transport DOES receive the text (positive control), and with consent DENIED
  the SAME fake transport receives ZERO calls (so the gate is proven, not mocked
  away). A single wholesale fake cannot prove the consent gate — it bypasses the
  cloud-vs-local decision entirely.

The build job runs on a real JobRegistry; its ``job.done.result`` is asserted.
Persistence uses ``tmp_path`` (no real network, no manifest bloat).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models import embedder as _embedder
from media_studio.protocol import ErrorCode, RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fakes / seams
# --------------------------------------------------------------------------- #
class FakeProvider:
    def chat(self, *args: Any, **kwargs: Any) -> str:
        return "[]"


class RecordingEmbedder:
    """A wholesale Embedder fake: deterministic per-text 2-D vectors, counts calls.

    Vectors are fixed 2-D so build (segments) and search (query) always share a
    dimension — exactly as a single real embedder route would.
    """

    model = "fake-embed"

    def __init__(self, table: dict[str, list[float]] | None = None) -> None:
        self._table = table or {}
        self.calls: list[list[str]] = []

    def embed(self, texts: Any) -> list[list[float]]:
        texts = list(texts)
        self.calls.append(list(texts))
        return [self._table.get(t, [float(len(t)), 1.0]) for t in texts]


class SpyTransport:
    """A fake ``/v1/embeddings`` transport: records every egress, returns vectors."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers})
        inputs = body.get("input") or []
        return {"data": [{"embedding": [float(len(str(t))), 1.0]} for t in inputs]}


def _services(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {"data_dir": tmp_path / "data", "provider": FakeProvider()}
    base.update(over)
    return Services(**base)


def _ctx() -> RpcContext:
    events: list[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    context = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    context.events = events  # type: ignore[attr-defined]
    return context


def _done_result(ctx: RpcContext) -> dict[str, Any]:
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done, "job never completed"
    return done[-1][2]


def _transcript() -> dict[str, Any]:
    return {
        "language": "en",
        "durationSec": 30.0,
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "we talk about pricing here"},
            {"start": 5.0, "end": 10.0, "text": "now a totally different topic"},
        ],
    }


def _add_video_with_transcript(svc: Services, tmp_path: Path, transcript: Any = None) -> str:
    from media_studio import library as _library

    media = tmp_path / "talk.mp4"
    media.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 30.0)
    vid = svc.library.add(str(media))["id"]
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = _transcript() if transcript is None else transcript
    project.save()
    return vid


def _cloud_settings(*, text_consent: bool, confirm_budget: bool = False) -> dict[str, Any]:
    return {
        "confirmCloudBudget": confirm_budget,
        "providers": [
            {
                "id": "openai",
                "provider": "OpenAI",
                "kind": "cloud",
                "baseUrl": "https://example/v1",
                "model": "text-embedding-3-small",
                "apiKeys": ["sk-index-key-1234"],
                "enabled": True,
                "capabilities": ["text"],
                "unit": "req",
            }
        ],
        "routing": {"perFunction": {"index": {"provider": "openai", "fallback": []}}},
        "consent": {"perProvider": {"OpenAI": {"text": text_consent}}},
    }


def _set_settings(svc: Services, settings: dict[str, Any]) -> None:
    svc.settings.set(settings)


# --------------------------------------------------------------------------- #
# registration (AC a)
# --------------------------------------------------------------------------- #
def test_register_all_wires_index_methods(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert {"index.build", "index.search", "index.status"} <= set(registered)


# --------------------------------------------------------------------------- #
# AC b/f: build persists vectors, status reflects built, rebuild overwrites
# --------------------------------------------------------------------------- #
def test_index_build_persists_and_status_reflects_built(tmp_path: Path) -> None:
    emb = RecordingEmbedder()
    clock = iter([111.0, 222.0])
    svc = _services(tmp_path, embedder=emb, now=lambda: next(clock))
    vid = _add_video_with_transcript(svc, tmp_path)

    # status before build: not built.
    assert svc.index_status({"videoId": vid}, _ctx()) == {
        "built": False,
        "segmentCount": 0,
        "model": None,
        "builtAt": None,
        "dim": 0,
    }

    ctx = _ctx()
    out = svc.index_build({"videoId": vid}, ctx)
    assert "jobId" in out
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result == {"segmentCount": 2, "model": "fake-embed", "builtAt": 111.0, "dim": 2}

    # sidecar exists and aligns 1:1 with segments.
    sidecar = svc.projects_dir / f"{vid}.index.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert len(payload["vectors"]) == 2
    assert payload["builtAt"] == 111.0

    status = svc.index_status({"videoId": vid}, _ctx())
    assert status == {"built": True, "segmentCount": 2, "model": "fake-embed", "builtAt": 111.0, "dim": 2}

    # AC f: rebuild overwrites; builtAt advances (monotonic fake clock).
    ctx2 = _ctx()
    svc.index_build({"videoId": vid}, ctx2)
    ctx2.jobs.join(timeout=5)
    assert _done_result(ctx2)["builtAt"] == 222.0
    assert svc.index_status({"videoId": vid}, _ctx())["builtAt"] == 222.0


def test_index_build_empty_transcript_segments_builds_empty(tmp_path: Path) -> None:
    emb = RecordingEmbedder()
    svc = _services(tmp_path, embedder=emb, now=lambda: 5.0)
    vid = _add_video_with_transcript(svc, tmp_path, transcript={"language": "en", "segments": []})
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result == {"segmentCount": 0, "model": "fake-embed", "builtAt": 5.0, "dim": 0}
    assert svc.index_status({"videoId": vid}, _ctx())["segmentCount"] == 0


def test_index_build_requires_jobs(tmp_path: Path) -> None:
    svc = _services(tmp_path, embedder=RecordingEmbedder())
    nojobs = RpcContext(emit_notification=lambda obj: None, jobs=None)
    with pytest.raises(RpcError) as ei:
        svc.index_build({"videoId": "x"}, nojobs)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_index_build_no_transcript_raises(tmp_path: Path) -> None:
    from media_studio import library as _library

    svc = _services(tmp_path, embedder=RecordingEmbedder())
    media = tmp_path / "v.mp4"
    media.write_bytes(b"\x00")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 9.0)
    vid = svc.library.add(str(media))["id"]
    with pytest.raises(RpcError) as ei:
        svc.index_build({"videoId": vid}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# AC d: search on an unbuilt index -> typed "build first" (not [] / crash)
# --------------------------------------------------------------------------- #
def test_index_search_unbuilt_raises_build_first(tmp_path: Path) -> None:
    svc = _services(tmp_path, embedder=RecordingEmbedder())
    vid = _add_video_with_transcript(svc, tmp_path)
    with pytest.raises(RpcError) as ei:
        svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# search happy path: top-K hits ranked by cosine; topK respected
# --------------------------------------------------------------------------- #
def test_index_search_returns_ranked_hits(tmp_path: Path) -> None:
    # Segment 0 vector == query vector -> perfect cosine; segment 1 orthogonal.
    table = {
        "we talk about pricing here": [1.0, 0.0],
        "now a totally different topic": [0.0, 1.0],
        "pricing": [1.0, 0.0],
    }
    emb = RecordingEmbedder(table)
    svc = _services(tmp_path, embedder=emb, now=lambda: 1.0)
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)

    out = svc.index_search({"videoId": vid, "query": "pricing", "topK": 1}, _ctx())
    assert len(out["hits"]) == 1
    top = out["hits"][0]
    assert top["segmentIndex"] == 0
    assert top["text"] == "we talk about pricing here"
    assert top["start"] == 0.0
    assert top["score"] == pytest.approx(1.0)


def test_index_search_refuses_stale_index_after_retranscribe(tmp_path: Path) -> None:
    """Bug-sweep: a re-transcribe changes the segments, so the persisted vectors no
    longer line up. index.search refuses the stale index (typed rebuild prompt)
    instead of zipping new segments onto old vectors (silently-wrong hits)."""
    emb = RecordingEmbedder({"pricing": [1.0, 0.0]})
    svc = _services(tmp_path, embedder=emb, now=lambda: 1.0)
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    # Re-transcribe: overwrite with DIFFERENT segments.
    proj = svc._load_or_create_project(vid)
    proj.data["transcript"] = {
        "language": "en",
        "durationSec": 30.0,
        "segments": [{"start": 0.0, "end": 5.0, "text": "completely new content after retranscribe"}],
    }
    proj.save()
    with pytest.raises(RpcError) as ei:
        svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    assert "stale" in str(ei.value).lower(), f"expected a stale-index refusal, got {ei.value!r}"


def test_index_search_skips_fingerprint_for_legacy_index(tmp_path: Path) -> None:
    """Backward-compat: an index built before this fix carries no transcriptFp, so
    the staleness check is skipped (it is served as-is rather than force-flagged)."""
    emb = RecordingEmbedder({"pricing": [1.0, 0.0]})
    svc = _services(tmp_path, embedder=emb, now=lambda: 1.0)
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    # Simulate a legacy index: strip the fingerprint the fix now writes.
    idx = svc._read_index(vid)
    idx.pop("transcriptFp", None)
    svc._write_index(vid, idx)
    # Even after a re-transcribe, a legacy index is NOT flagged (skips the check).
    proj = svc._load_or_create_project(vid)
    proj.data["transcript"] = {"language": "en", "durationSec": 30.0,
                               "segments": [{"start": 0.0, "end": 5.0, "text": "pricing"}]}
    proj.save()
    out = svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    assert "hits" in out  # served without raising


# --------------------------------------------------------------------------- #
# AC e: repeat identical query is a cache hit (embedder not re-invoked)
# --------------------------------------------------------------------------- #
def test_index_search_query_embedding_is_cached(tmp_path: Path) -> None:
    emb = RecordingEmbedder({"pricing": [1.0, 0.0]})
    svc = _services(tmp_path, embedder=emb, now=lambda: 1.0)
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    build_calls = len(emb.calls)

    svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    after_first = len(emb.calls)
    assert after_first == build_calls + 1  # one query embed

    svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    assert len(emb.calls) == after_first  # cache hit: no new embed call


# --------------------------------------------------------------------------- #
# AC c (build path) — POSITIVE control: consent GRANTED -> text egresses.
# Written FIRST so a vacuous get_embedder wiring fails immediately.
# --------------------------------------------------------------------------- #
def test_index_build_cloud_consent_granted_egresses_text(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    _set_settings(svc, _cloud_settings(text_consent=True))
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    _done_result(ctx)
    # The fake transport received the transcript segment texts (real egress proof).
    assert spy.calls, "consent granted but no egress happened (embedder wired wrong)"
    sent = spy.calls[0]["body"]["input"]
    assert "we talk about pricing here" in sent


# --------------------------------------------------------------------------- #
# AC c (build path) — NEGATIVE: consent DENIED -> transcript never egresses.
# --------------------------------------------------------------------------- #
def test_index_build_cloud_consent_denied_no_text_egress(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    _set_settings(svc, _cloud_settings(text_consent=False))
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    # The non-consented provider was DROPPED -> LocalEmbedder backstop -> zero egress.
    assert spy.calls == [], "transcript text egressed to a non-consented provider"
    assert result["segmentCount"] == 2
    assert result["model"] == "local"


# --------------------------------------------------------------------------- #
# AC c2 (search path, privacy-critical) — consent DENIED -> query never egresses.
# --------------------------------------------------------------------------- #
def _build_then_clear_spy(svc: Services, spy: SpyTransport, vid: str) -> None:
    """Build the index through the real embedder route, then forget the build egress.

    Building and searching MUST share the same embedder route so the persisted
    vector dim matches the query vector dim (production always does). We build under
    the SAME consent route the search will use, then reset the spy so the assertion
    isolates the SEARCH egress. No budget toggle is needed: the build path plans its
    envelope over the SAME text-consented settings as search, so a consent-denied
    build routes local (willEgress False) and is never refused for a missing ack.
    """
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    _done_result(ctx)
    spy.calls.clear()


def test_index_search_cloud_consent_denied_query_no_egress(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    # Build + search BOTH under the cloud DENIED route -> LocalEmbedder for both, so
    # the persisted (local) vectors and the (local) query vector share a dim and the
    # cosine is well-formed; the proof is that the cloud transport is never touched.
    _set_settings(svc, _cloud_settings(text_consent=False))
    _build_then_clear_spy(svc, spy, vid)

    out = svc.index_search({"videoId": vid, "query": "secret query"}, _ctx())
    assert spy.calls == [], "query text egressed to a non-consented provider"
    assert "hits" in out


def test_index_search_cloud_consent_granted_query_egresses(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    _set_settings(svc, _cloud_settings(text_consent=True))
    _build_then_clear_spy(svc, spy, vid)

    svc.index_search({"videoId": vid, "query": "find pricing"}, _ctx())
    assert spy.calls, "consent granted but query never egressed"
    assert "find pricing" in spy.calls[0]["body"]["input"]


# --------------------------------------------------------------------------- #
# OFFLINE ENFORCEMENT (bug fix): offline forbids cloud embedding egress even when
# TEXT consent is fully granted + the cloud route is preferred. The embedder must
# fall back to the LocalEmbedder backstop (zero egress) for BOTH build and search.
# --------------------------------------------------------------------------- #
def _offline_cloud_settings() -> dict[str, Any]:
    return {**_cloud_settings(text_consent=True), "offline": True}


def test_index_build_offline_consent_granted_no_text_egress(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    _set_settings(svc, _offline_cloud_settings())
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    # Offline -> the cloud entry is dropped -> LocalEmbedder backstop -> zero egress.
    assert spy.calls == [], "transcript text egressed while offline"
    assert result["segmentCount"] == 2
    assert result["model"] == "local"


def test_index_search_offline_consent_granted_query_no_egress(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    # Build + search BOTH offline -> LocalEmbedder for both, dims align, the cloud
    # transport is never touched on the search query embedding.
    _set_settings(svc, _offline_cloud_settings())
    _build_then_clear_spy(svc, spy, vid)

    out = svc.index_search({"videoId": vid, "query": "secret query"}, _ctx())
    assert spy.calls == [], "query text egressed while offline"
    assert "hits" in out


# --------------------------------------------------------------------------- #
# AC c3 (search path) — confirmCloudBudget on: unacked blocks, acked proceeds.
# --------------------------------------------------------------------------- #
def test_index_search_budget_ack_required_then_proceeds(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    # Build with consent + budget OFF (so the build job is unacked-friendly), then
    # turn the budget gate on for the search. Build + search share the cloud route.
    _set_settings(svc, _cloud_settings(text_consent=True))
    _build_then_clear_spy(svc, spy, vid)
    _set_settings(svc, _cloud_settings(text_consent=True, confirm_budget=True))

    # Unacked cloud search -> typed budget-ack error BEFORE any egress.
    with pytest.raises(RpcError) as ei:
        svc.index_search({"videoId": vid, "query": "q"}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS
    assert spy.calls == [], "egressed before the budget ack"

    # Recover the cacheKey via the SAME inputs index.search builds (model "" since
    # the route's model lives per-provider-entry, not a top-level cloudEmbedModel),
    # then re-issue with the ack -> the search now proceeds and egresses.
    from media_studio.models import ai_job as _ai_job

    inputs = _ai_job.AiInputs(messages=({"role": "user", "content": "q"},), model="")
    envelope = svc._plan_index_envelope(inputs)
    out = svc.index_search({"videoId": vid, "query": "q", "confirmBudget": envelope.cacheKey}, _ctx())
    assert spy.calls, "acked cloud search still did not egress"
    assert "hits" in out


def test_index_search_consent_denied_with_budget_on_does_not_block(tmp_path: Path) -> None:
    # consent DENIED -> local route -> willEgress False -> the budget ack gate must
    # NOT fire (the two gates must not contradict). The search proceeds with no ack.
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    _set_settings(svc, _cloud_settings(text_consent=False, confirm_budget=True))
    _build_then_clear_spy(svc, spy, vid)

    out = svc.index_search({"videoId": vid, "query": "q"}, _ctx())  # no ack, must NOT raise
    assert spy.calls == []
    assert "hits" in out


# --------------------------------------------------------------------------- #
# build-path budget coherence: consent DENIED + budget ON -> local build, NO ack
# (DESIGN §1.5 "default privacy preset -> local -> zero egress regardless").
# --------------------------------------------------------------------------- #
def test_index_build_consent_denied_with_budget_on_does_not_block(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    _set_settings(svc, _cloud_settings(text_consent=False, confirm_budget=True))
    ctx = _ctx()
    # No confirmBudget ack passed: a denied build routes local (willEgress False),
    # so the ack gate must NOT fire and the job must complete with a local index.
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert spy.calls == []
    assert result["model"] == "local"
    assert result["segmentCount"] == 2


def test_index_build_consent_granted_with_budget_on_requires_ack(tmp_path: Path) -> None:
    # The flip side: consent GRANTED + budget ON + no ack -> the cloud build IS
    # refused with a typed budget-ack error before any egress (gate still bites).
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    _set_settings(svc, _cloud_settings(text_consent=True, confirm_budget=True))
    with pytest.raises(RpcError) as ei:
        svc.index_build({"videoId": vid}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS
    assert spy.calls == []


# --------------------------------------------------------------------------- #
# AC d (extended): a route change after build -> dimension mismatch is a TYPED
# "rebuild" error out of index.search, not a raw cosine ValueError.
# --------------------------------------------------------------------------- #
def test_index_search_dimension_mismatch_raises_rebuild(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    # Build on the privacy default (LocalEmbedder, 384-dim, no cloud route)...
    _set_settings(svc, {"providers": []})
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    built = _done_result(ctx)
    assert built["dim"] == _embedder.DEFAULT_LOCAL_EMBED_DIM
    # ...then switch to a cloud route (SpyTransport -> 2-dim query vector). The query
    # dim (2) no longer matches the persisted dim (384) -> typed rebuild error.
    _set_settings(svc, _cloud_settings(text_consent=True))
    with pytest.raises(RpcError) as ei:
        svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS
    assert "rebuild" in str(ei.value).lower()


# --------------------------------------------------------------------------- #
# real CloudEmbedder is constructed from the routed cloud entry (not get_embedder)
# --------------------------------------------------------------------------- #
def test_resolve_index_embedder_builds_cloud_from_routed_entry(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    settings = _cloud_settings(text_consent=True)
    _set_settings(svc, settings)
    resolved = svc._resolve_index_embedder(settings)
    assert isinstance(resolved, _embedder.CloudEmbedder)
    assert resolved.base_url == "https://example/v1"
    assert resolved.model == "text-embedding-3-small"


def test_resolve_index_embedder_local_when_no_cloud_entry(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    resolved = svc._resolve_index_embedder({"providers": []})
    assert isinstance(resolved, _embedder.LocalEmbedder)


def test_resolve_index_embedder_local_when_entry_has_no_key(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    settings = _cloud_settings(text_consent=True)
    settings["providers"][0]["apiKeys"] = []
    resolved = svc._resolve_index_embedder(settings)
    assert isinstance(resolved, _embedder.LocalEmbedder)


def test_resolve_index_embedder_injected_wins(tmp_path: Path) -> None:
    emb = RecordingEmbedder()
    svc = _services(tmp_path, embedder=emb)
    assert svc._resolve_index_embedder(_cloud_settings(text_consent=True)) is emb


# --------------------------------------------------------------------------- #
# REGRESSION (bug #5): the settings-DRIVEN index egress (no injected embedder)
# must carry the RAW apiKey to the wire, not the REDACTED last-4 form.
#
# Mirrors the e2e-ai2 strict-xfail companion
# ``test_intel_semantic_settings_driven_egress_redacted_key_bug`` as a PASSING
# regression: the call sites resolved the embedder over ``self.settings.get()``
# (which redacts ``apiKeys`` to ``…1234``), so ``CloudEmbedder`` built an
# ``Authorization: Bearer …1234`` header — a corrupted key (non-latin-1 ellipsis
# crashes locally / 401 on a real cloud). The vision/director factories correctly
# use ``get_raw()`` (handlers.py); the embedder path now does too. The unit
# consent tests above missed this because they assert on the egressed TEXT
# (``body["input"]``), never on the egressed KEY (``headers["Authorization"]``).
# --------------------------------------------------------------------------- #
_RAW_INDEX_KEY: str = "sk-index-key-1234"
_REDACTED_INDEX_KEY: str = "…1234"  # secrets.redact_keys(...) of _RAW_INDEX_KEY


def test_index_build_egresses_raw_apikey_not_redacted(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    _set_settings(svc, _cloud_settings(text_consent=True))
    vid = _add_video_with_transcript(svc, tmp_path)
    ctx = _ctx()
    # WU-D2b-2: the embedder settings are captured synchronously at dispatch, so
    # main's per-request key injection must be active for that capture — the
    # overlay puts the RAW key into the captured settings the job's embedder uses.
    with svc.settings.key_overlay({"providers": {"openai": [_RAW_INDEX_KEY]}}):
        svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    _done_result(ctx)
    assert spy.calls, "consent granted but no egress happened (embedder wired wrong)"
    auth = spy.calls[0]["headers"]["Authorization"]
    assert auth == f"Bearer {_RAW_INDEX_KEY}", auth
    assert _REDACTED_INDEX_KEY not in auth


def test_index_search_egresses_raw_apikey_not_redacted(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    _set_settings(svc, _cloud_settings(text_consent=True))
    _build_then_clear_spy(svc, spy, vid)

    # WU-D2b-2: the query-embedder settings are captured under the injection
    # overlay (main injects the live key for the provider-calling search).
    with svc.settings.key_overlay({"providers": {"openai": [_RAW_INDEX_KEY]}}):
        svc.index_search({"videoId": vid, "query": "find pricing"}, _ctx())
    assert spy.calls, "consent granted but query never egressed"
    auth = spy.calls[0]["headers"]["Authorization"]
    assert auth == f"Bearer {_RAW_INDEX_KEY}", auth
    assert _REDACTED_INDEX_KEY not in auth
