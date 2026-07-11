"""Bug-sweep regressions for the sidecar-handlers-0 fixer unit.

Covers the verified findings in ``handlers/vision_ops.py`` and
``handlers/providers_ops.py``:

* frame-time drift — the thumbnail picker samples frames WITH their aligned times
  through the new ``_frame_clip_time_loader`` seam, so a dropped native read never
  shifts the reported ``frameTimeSec`` (no coarse regrid).
* ``index.search`` gate ordering — a repeat identical query served from the
  query-vector cache (zero egress) is NOT charged a fresh budget ack.
* ``_plan_index_envelope`` offline gate — an offline index run plans LOCAL, so it
  never spuriously demands an ack / records phantom egress cents.
* degrade-to-midpoint cache — the thumbnail cache key encodes the resolved route,
  so a degraded result is not served forever after consent/weights arrive, and the
  degrade payload no longer advertises an unwritten ``thumbnailPath``.
* query-vector cache identity — the key folds the resolved embedder identity, so a
  local vector can never be served for a cloud route (no dim-guard wedge).
* RoutingPolicy Local mode is authoritative at the translation + vision seams, and
  cloud translation is per-provider TEXT-consent gated.

Heavy-free: every seam (frame loader, scorer, writer, embedder transport, vision
chat transport, translator factory) is an injected fake — no cv2 / torch / socket.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.features import shorts as sh
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models import ai_job as _ai_job
from media_studio.models import embedder as _embedder
from media_studio.models import provider as _pm
from media_studio.protocol import ErrorCode, RpcContext, RpcError


# --------------------------------------------------------------------------- #
# shared fakes / helpers
# --------------------------------------------------------------------------- #
class FakeProvider:
    def chat(self, *args: Any, **kwargs: Any) -> str:
        return "[]"

    def exemplar_block(self, language: str | None = None) -> str | None:
        return None

    def calibrated_pct(self, raw: float) -> int | None:
        return None


class RecordingScorer:
    """A FrameScorer recording its calls; returns canned per-frame scores."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.calls: list[tuple[int, str]] = []

    def __call__(self, frames: Any, prompt: str) -> list[float]:
        self.calls.append((len(list(frames)), prompt))
        return list(self._scores)


class RecordingWriter:
    def __init__(self) -> None:
        self.writes: list[tuple[Any, str]] = []

    def __call__(self, frame: Any, path: str) -> None:
        self.writes.append((frame, path))


class RecordingEmbedder:
    """A wholesale Embedder fake: deterministic per-text 2-D vectors, counts calls."""

    model = "fake-embed"

    def __init__(self, table: dict[str, list[float]] | None = None) -> None:
        self._table = table or {}
        self.calls: list[list[str]] = []

    def embed(self, texts: Any) -> list[list[float]]:
        texts = list(texts)
        self.calls.append(list(texts))
        return [self._table.get(t, [float(len(t)), 1.0]) for t in texts]


class SpyTransport:
    """A fake ``/v1/embeddings`` transport: records every egress, returns 2-D vectors."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers})
        inputs = body.get("input") or []
        return {"data": [{"embedding": [float(len(str(t))), 1.0]} for t in inputs]}


class _VisionTransport:
    """Fake vision chat transport; records calls so a cloud egress is observable."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append(url)
        return {"choices": [{"message": {"role": "assistant", "content": "0"}}]}


class _LocalBackend:
    """A fake LOCAL vlm backend: scores frames without any network."""

    def __init__(self) -> None:
        self.calls = 0

    def rank_clips(self, stacks: Any, prompt: str) -> list[float]:
        self.calls += 1
        return [0.5 for _ in list(stacks)]


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


# --------------------------------------------------------------------------- #
# thumbnail.select — helpers
# --------------------------------------------------------------------------- #
def _fake_loader(path: str, spans: Any) -> list[Any]:
    """One synthetic 3-frame stack for the single requested span (legacy seam)."""
    return [[f"f0@{lo}-{hi}", f"f1@{lo}-{hi}", f"f2@{lo}-{hi}"] for lo, hi in spans]


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "talk.mp4"
    p.write_bytes(b"\x00fake")
    return p


def _thumb_svc(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "ffmpeg_run": lambda argv, **k: 0,
        "ffprobe_duration": lambda p: 12.0,
        "provider": FakeProvider(),
        "vlm_clip_frame_loader": _fake_loader,
        "vlm_frame_encoder": lambda frame: f"ENC<{frame}>",
        "vlm_models_present": lambda s: False,
    }
    base.update(over)
    return Services(**base)


def _add_video(services: Services, video_file: Path) -> str:
    from media_studio import library as _library

    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    return services.library.add(str(video_file))["id"]


# --------------------------------------------------------------------------- #
# Finding: frame-time drift — the time-aware loader carries survivors' TRUE times
# --------------------------------------------------------------------------- #
def _short_stack_time_loader(path: str, spans: Any) -> list[Any]:
    """A time-aware loader whose native reads DROPPED positions 3 and 6 of an 8-grid.

    The 6 survivors keep their ORIGINAL grid times [0,1,2,4,5,7] (step=1.0 over
    [0,8]); the plain-loader regrid would instead spread them as _evenly_spaced(0,8,6).
    """
    return [(["f0", "f1", "f2", "f4", "f5", "f7"], [0.0, 1.0, 2.0, 4.0, 5.0, 7.0])]


def test_thumbnail_time_loader_keeps_true_survivor_time(tmp_path: Path, video_file: Path) -> None:
    scorer = RecordingScorer([0.1, 0.1, 0.1, 0.1, 0.1, 0.9])  # argmax index 5 -> time 7.0
    writer = RecordingWriter()
    svc = _thumb_svc(
        tmp_path,
        vlm_clip_frame_loader=None,  # force the time-aware branch
        vlm_clip_time_loader=_short_stack_time_loader,
        frame_scorer=scorer,
        thumbnail_writer=writer,
    )
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 0.0, "end": 8.0}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result["degraded"] is False
    # The survivor's TRUE grid time, NOT the coarse regrid _evenly_spaced(0,8,6)[5] == 6.667.
    assert result["frameTimeSec"] == 7.0
    assert sh.read_metadata(str(video_file))["thumbnailFrameSec"] == 7.0
    assert len(writer.writes) == 1


def test_thumbnail_time_loader_empty_pairs_zero_result(tmp_path: Path, video_file: Path) -> None:
    # The time-aware loader returns NO pairs (no stack at all) -> empty stack branch.
    scorer = RecordingScorer([])
    writer = RecordingWriter()
    svc = _thumb_svc(
        tmp_path,
        vlm_clip_frame_loader=None,
        vlm_clip_time_loader=lambda p, s: [],
        frame_scorer=scorer,
        thumbnail_writer=writer,
    )
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 0.0, "end": 4.0}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result["frameTimeSec"] == 0.0
    assert writer.writes == []


def test_frame_clip_time_loader_default_is_lazy(tmp_path: Path) -> None:
    # With no injection the accessor returns the native default callable
    # (coverage-excluded prod seam) — assert identity WITHOUT calling it.
    svc = Services(data_dir=tmp_path / "d")
    from media_studio.features import smolvlm2 as _sv

    assert svc._frame_clip_time_loader() is _sv._default_clip_frames_with_times


# --------------------------------------------------------------------------- #
# Finding: degrade-to-midpoint cache is route-blind (stale forever) + fake path
# --------------------------------------------------------------------------- #
def test_thumbnail_degrade_result_omits_thumbnail_path(tmp_path: Path, video_file: Path) -> None:
    # No scorer / no weights / no consent -> degrade; the payload must NOT advertise a
    # thumbnailPath (the writer never ran, so the file was never written).
    svc = _thumb_svc(tmp_path)
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 2.0, "end": 8.0}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result["degraded"] is True
    assert result["frameTimeSec"] == 5.0
    assert "thumbnailPath" not in result


def test_thumbnail_degrade_then_scored_is_not_stale(tmp_path: Path, video_file: Path) -> None:
    # First run degrades (no scorer) and caches a midpoint under route="degraded".
    svc1 = _thumb_svc(tmp_path)
    ctx1 = _ctx()
    vid = _add_video(svc1, video_file)
    params = {"videoId": vid, "path": str(video_file), "start": 0.0, "end": 6.0}
    svc1.thumbnail_select(dict(params), ctx1)
    ctx1.jobs.join(timeout=5)
    assert _done_result(ctx1)["degraded"] is True
    # A NEW Services on the SAME data_dir (SAME persistent ai-cache) WITH a scorer must
    # NOT return the stale midpoint: the route tag flips to "scored", the key differs,
    # the cache misses, and the picker actually runs.
    scorer = RecordingScorer([0.1, 0.9, 0.2])
    writer = RecordingWriter()
    svc2 = _thumb_svc(tmp_path, frame_scorer=scorer, thumbnail_writer=writer)
    ctx2 = _ctx()
    svc2.thumbnail_select(dict(params), ctx2)
    ctx2.jobs.join(timeout=5)
    result = _done_result(ctx2)
    assert result["degraded"] is False
    assert len(scorer.calls) == 1  # the picker ran, not a stale midpoint replay


# --------------------------------------------------------------------------- #
# vision resolvers — RoutingPolicy Local is authoritative (skip the cloud branch)
# --------------------------------------------------------------------------- #
def _vision_settings(*, with_consent: bool, policy: str) -> dict[str, Any]:
    return {
        "confirmCloudBudget": False,
        "providers": [
            {
                "id": "gemini",
                "provider": "Gemini",
                "kind": "cloud",
                "baseUrl": "https://example/v1",
                "model": "gemini-flash",
                "apiKeys": ["sk-vision-key-9999"],
                "enabled": True,
                "capabilities": ["text", "vision"],
                "unit": "req",
            }
        ],
        "routing": {"perFunction": {"vision": {"provider": "gemini", "fallback": []}}},
        "consent": {"perProvider": {"Gemini": {"frames": with_consent}}},
        "routingPolicy": {"global": policy, "overrides": {}},
    }


def _vision_svc(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "provider": None,
        "vlm_frame_encoder": lambda f: "b",
        "vlm_clip_frame_loader": lambda p, s: [["f"]],
    }
    base.update(over)
    return Services(**base)


def test_resolve_frame_scorer_routing_local_uses_local_backend(tmp_path: Path) -> None:
    transport = _VisionTransport()
    backend = _LocalBackend()
    svc = _vision_svc(
        tmp_path,
        vlm_chat_transport=transport,
        vlm_models_present=lambda s: True,
        frame_backend_factory=lambda _s: backend,
    )
    svc.settings.set(_vision_settings(with_consent=True, policy="local"))
    scorer = svc._resolve_frame_scorer(svc.settings.get())
    assert scorer is not None
    scores = scorer(["a", "b"], "p")
    assert backend.calls == 1, "routing-Local did not route to the local backend"
    assert transport.calls == [], "frames egressed to cloud under a Local routing policy"
    assert len(scores) == 2


def test_resolve_frame_scorer_routing_local_no_weights_is_none(tmp_path: Path) -> None:
    transport = _VisionTransport()
    svc = _vision_svc(tmp_path, vlm_chat_transport=transport, vlm_models_present=lambda s: False)
    svc.settings.set(_vision_settings(with_consent=True, policy="local"))
    assert svc._resolve_frame_scorer(svc.settings.get()) is None
    assert transport.calls == []


def test_resolve_vlm_reranker_routing_local_uses_local_weights(tmp_path: Path) -> None:
    svc = _vision_svc(tmp_path, vlm_chat_transport=_VisionTransport(), vlm_models_present=lambda s: True)
    svc.settings.set(_vision_settings(with_consent=True, policy="local"))
    rr = svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4")
    from media_studio.features import smolvlm2 as sv

    assert isinstance(rr, sv.SmolVlmReranker)
    assert rr._factory is sv._default_backend_factory  # local, NOT the cloud closure


def test_resolve_vlm_reranker_routing_local_no_weights_is_none(tmp_path: Path) -> None:
    svc = _vision_svc(tmp_path, vlm_chat_transport=_VisionTransport(), vlm_models_present=lambda s: False)
    svc.settings.set(_vision_settings(with_consent=True, policy="local"))
    assert svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4") is None


# --------------------------------------------------------------------------- #
# index.* — helpers
# --------------------------------------------------------------------------- #
def _index_svc(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {"data_dir": tmp_path / "data", "provider": FakeProvider()}
    base.update(over)
    return Services(**base)


def _transcript() -> dict[str, Any]:
    return {
        "language": "en",
        "durationSec": 30.0,
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "we talk about pricing here"},
            {"start": 5.0, "end": 10.0, "text": "now a totally different topic"},
        ],
    }


def _add_video_with_transcript(svc: Services, tmp_path: Path) -> str:
    from media_studio import library as _library

    media = tmp_path / "idx.mp4"
    media.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 30.0)
    vid = svc.library.add(str(media))["id"]
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = _transcript()
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


def _build(svc: Services, vid: str) -> None:
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    _done_result(ctx)


# --------------------------------------------------------------------------- #
# Finding: index.search cache hit must NOT be charged a fresh budget ack
# --------------------------------------------------------------------------- #
def test_index_search_cached_query_skips_budget_ack(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _index_svc(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    # Build + first search under consent granted, budget OFF -> the query vector caches.
    svc.settings.set(_cloud_settings(text_consent=True))
    _build(svc, vid)
    svc.index_search({"videoId": vid, "query": "q"}, _ctx())
    spy.calls.clear()
    # Now the budget gate is ON; the SAME query with NO ack must be served from cache
    # (zero egress) WITHOUT raising — the gate runs only on a cache MISS.
    svc.settings.set(_cloud_settings(text_consent=True, confirm_budget=True))
    out = svc.index_search({"videoId": vid, "query": "q"}, _ctx())
    assert "hits" in out
    assert spy.calls == [], "a cached (zero-egress) query re-embedded / re-gated under budget-on"


def test_index_search_uncached_query_still_gated_under_budget_on(tmp_path: Path) -> None:
    # Control: a cache-MISS cloud query under budget-on still demands the ack (the gate
    # bites on genuine egress) — proving the cache-hit bypass is not a blanket bypass.
    spy = SpyTransport()
    svc = _index_svc(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    svc.settings.set(_cloud_settings(text_consent=True))
    _build(svc, vid)
    svc.settings.set(_cloud_settings(text_consent=True, confirm_budget=True))
    with pytest.raises(RpcError) as ei:
        svc.index_search({"videoId": vid, "query": "never-searched"}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# Finding: _plan_index_envelope must honor the offline gate (plan LOCAL)
# --------------------------------------------------------------------------- #
def test_plan_index_envelope_offline_is_local_route(tmp_path: Path) -> None:
    svc = _index_svc(tmp_path, embed_transport=SpyTransport())
    svc.settings.set({**_cloud_settings(text_consent=True), "offline": True})
    inputs = _ai_job.AiInputs(messages=({"role": "user", "content": "q"},), model="")
    envelope = svc._plan_index_envelope(inputs)
    assert envelope.route.willEgress is False


def test_plan_index_envelope_online_cloud_route_egresses(tmp_path: Path) -> None:
    svc = _index_svc(tmp_path, embed_transport=SpyTransport())
    svc.settings.set(_cloud_settings(text_consent=True))
    inputs = _ai_job.AiInputs(messages=({"role": "user", "content": "q"},), model="")
    envelope = svc._plan_index_envelope(inputs)
    assert envelope.route.willEgress is True


def test_index_search_offline_records_no_spend(tmp_path: Path) -> None:
    svc = _index_svc(tmp_path, embed_transport=SpyTransport())
    vid = _add_video_with_transcript(svc, tmp_path)
    svc.settings.set({**_cloud_settings(text_consent=True), "offline": True})
    _build(svc, vid)
    before = svc._spend_ledger().month_to_date()
    svc.index_search({"videoId": vid, "query": "q"}, _ctx())
    assert svc._spend_ledger().month_to_date() == before  # offline -> no phantom egress cents


def test_index_search_offline_with_budget_on_does_not_block(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _index_svc(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    svc.settings.set({**_cloud_settings(text_consent=True, confirm_budget=True), "offline": True})
    _build(svc, vid)
    out = svc.index_search({"videoId": vid, "query": "q"}, _ctx())  # no ack -> must NOT raise
    assert "hits" in out
    assert spy.calls == []


# --------------------------------------------------------------------------- #
# Finding: query-vector cache identity — no local/cloud vector collision (dim wedge)
# --------------------------------------------------------------------------- #
def test_index_search_cache_not_poisoned_across_offline_toggle(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _index_svc(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    # Build on the cloud route (2-dim SpyTransport vectors).
    svc.settings.set(_cloud_settings(text_consent=True))
    _build(svc, vid)
    # Toggle offline: the query embeds LOCAL (384-dim) which mismatches the built dim
    # -> typed rebuild error. The local vector is cached under an embedder="local" key.
    svc.settings.set({**_cloud_settings(text_consent=True), "offline": True})
    with pytest.raises(RpcError) as ei:
        svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    assert "rebuild" in str(ei.value).lower()
    # Toggle back online, rebuild on the cloud route, then re-search the SAME query.
    svc.settings.set(_cloud_settings(text_consent=True))
    _build(svc, vid)
    out = svc.index_search({"videoId": vid, "query": "pricing"}, _ctx())
    # Before the fix this re-raised (the stale 384-dim local vector was served from a
    # model-only key); the embedder-identity key keeps the cloud slot separate.
    assert "hits" in out


def test_index_search_dim_guard_uses_local_embedder_dim(tmp_path: Path) -> None:
    # Sanity: the offline half of the poisoning path really is a dim mismatch (proves
    # the raises above is the dim guard, not some unrelated refusal).
    assert _embedder.DEFAULT_LOCAL_EMBED_DIM != 2


# --------------------------------------------------------------------------- #
# Finding: _translator_for_function — RoutingPolicy Local + TEXT-consent gates
# --------------------------------------------------------------------------- #
def _cloud_text_entry(pid: str) -> dict[str, Any]:
    return {
        "id": pid,
        "provider": pid,
        "kind": "cloud",
        "apiKeys": ["k"],
        "enabled": True,
        "capabilities": ["text"],
        "baseUrl": f"http://{pid}",
        "model": "m",
    }


def test_translator_for_function_forces_local_when_routing_local(tmp_path: Path, monkeypatch) -> None:
    from media_studio.models import translation as _tm

    captured: dict[str, Any] = {}

    def spy(settings: Any, *, runner: Any = None, prefer: Any = None, ensure: Any = None) -> Any:
        captured["prefer"] = prefer
        return object()

    monkeypatch.setattr(_tm, "get_translator", spy)
    svc = Services(data_dir=tmp_path / "d")
    svc.settings.set(
        {
            "routingPolicy": {"global": "local", "overrides": {}},
            "routing": {"perFunction": {"translation": {"provider": "cloudy"}}},
            "providers": [_cloud_text_entry("cloudy")],
            "consent": {"perProvider": {"cloudy": {"text": True}}},
        }
    )
    svc._translator_for_function("translation")
    assert captured["prefer"] == _pm.LOCAL_PROVIDER_ID, "routing-Local translation did not force local"


def test_translator_for_function_keeps_routed_prefer_when_routing_cloud(tmp_path: Path, monkeypatch) -> None:
    from media_studio.models import translation as _tm

    captured: dict[str, Any] = {}

    def spy(settings: Any, *, runner: Any = None, prefer: Any = None, ensure: Any = None) -> Any:
        captured["prefer"] = prefer
        return object()

    monkeypatch.setattr(_tm, "get_translator", spy)
    svc = Services(data_dir=tmp_path / "d")
    svc.settings.set(
        {
            "routingPolicy": {"global": "cloud", "overrides": {}},
            "routing": {"perFunction": {"translation": {"provider": "cloudy"}}},
            "providers": [_cloud_text_entry("cloudy")],
            "consent": {"perProvider": {"cloudy": {"text": True}}},
        }
    )
    svc._translator_for_function("translation")
    assert captured["prefer"] == "cloudy"


def test_translator_for_function_forces_local_when_offline(tmp_path: Path, monkeypatch) -> None:
    from media_studio.models import translation as _tm

    captured: dict[str, Any] = {}

    def spy(settings: Any, *, runner: Any = None, prefer: Any = None, ensure: Any = None) -> Any:
        captured["prefer"] = prefer
        return object()

    monkeypatch.setattr(_tm, "get_translator", spy)
    svc = Services(data_dir=tmp_path / "d")
    svc.settings.set(
        {
            "offline": True,
            "routingPolicy": {"global": "cloud", "overrides": {}},  # offline overrides even cloud
            "routing": {"perFunction": {"translation": {"provider": "cloudy"}}},
            "providers": [_cloud_text_entry("cloudy")],
            "consent": {"perProvider": {"cloudy": {"text": True}}},
        }
    )
    svc._translator_for_function("translation")
    assert captured["prefer"] == _pm.LOCAL_PROVIDER_ID


def test_translator_for_function_drops_non_text_consented_cloud(tmp_path: Path, monkeypatch) -> None:
    from media_studio.models import translation as _tm

    captured: dict[str, Any] = {}

    def spy(settings: Any, *, runner: Any = None, prefer: Any = None, ensure: Any = None) -> Any:
        captured["providers"] = [str(p.get("provider")) for p in settings.get("providers", [])]
        return object()

    monkeypatch.setattr(_tm, "get_translator", spy)
    svc = Services(data_dir=tmp_path / "d")
    svc.settings.set(
        {
            "routingPolicy": {"global": "cloud", "overrides": {}},
            "routing": {"perFunction": {"translation": {"provider": "yes"}}},
            "providers": [_cloud_text_entry("yes"), _cloud_text_entry("no")],
            "consent": {"perProvider": {"yes": {"text": True}, "no": {"text": False}}},
        }
    )
    svc._translator_for_function("translation")
    assert captured["providers"] == ["yes"], "a non-text-consented cloud entry leaked into the translator pool"
