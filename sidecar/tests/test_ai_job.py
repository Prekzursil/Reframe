"""Unit tests for the AI-Job envelope (WU-envelope).

``plan_ai_job`` is PURE → its route / costEst / cacheKey assembly is tested with
fixtures and the REAL :class:`AiCache` (tmp dir) + REAL :mod:`budget` with tiny
faked pool/catalog. ``run_ai_job`` is driven through a fake :class:`JobRegistry`
(the REAL one from ``jobs.py``, with capturing sinks) + a fake provider factory +
the real cache; the tests pin:

  * ``ai.planJob`` (the ``planned()`` pre-flight) performs ZERO provider calls
    (the provider factory is never invoked);
  * every AI job emits progress + a terminal ``job.done`` (result or error);
  * a cache HIT skips the provider entirely (factory untouched, transport spy
    untouched);
  * cancel mid-job returns the cancelled status with no provider call;
  * a single ``job.done`` error payload on provider exhaustion;
  * a ``degraded`` notice is emitted when the run falls through to local.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from media_studio.jobs import JobRegistry
from media_studio.models.ai_cache import AiCache, Message
from media_studio.models.ai_job import (
    AiInputs,
    AiJob,
    AiRoute,
    CatalogFreeCapAdapter,
    plan_ai_job,
    run_ai_job,
)
from media_studio.models.provider import ProviderError


# --------------------------------------------------------------------------- #
# fakes — budget pool / catalog (duck-typed, mirror the budget Protocols)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FakeEntry:
    provider: str
    local: bool


@dataclass(frozen=True)
class FakePool:
    entries: tuple[FakeEntry, ...]


class FakeCatalog:
    """Catalog stub: every provider is uncapped unless ``caps`` pins a cap."""

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self._caps = caps or {}

    def free_cap(self, provider: str) -> int | None:
        return self._caps.get(provider)


@dataclass(frozen=True)
class FakeRequest:
    target_size: int | None
    text_bytes: int
    frame_bytes: int


def _inputs(*, content: str = "hello", model: str = "m", **params: Any) -> AiInputs:
    return AiInputs(
        messages=({"role": "user", "content": content},),
        model=model,
        params=params,
    )


def _cloud_pool() -> FakePool:
    return FakePool((FakeEntry("Groq", False), FakeEntry("local", True)))


def _local_only_pool() -> FakePool:
    return FakePool((FakeEntry("local", True),))


# --------------------------------------------------------------------------- #
# fake providers
# --------------------------------------------------------------------------- #
class SpyProvider:
    """A provider whose ``chat`` records calls and returns a canned reply."""

    def __init__(self, reply: str = "answer") -> None:
        self.reply = reply
        self.calls: list[Sequence[Message]] = []

    def chat(self, messages: Sequence[Message], **_kwargs: Any) -> str:
        self.calls.append(list(messages))
        return self.reply


class RaisingProvider:
    """A provider whose ``chat`` always raises :class:`ProviderError` (exhaustion)."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: Sequence[Message], **_kwargs: Any) -> str:
        self.calls += 1
        raise ProviderError("provider pool exhausted (text): all keys 429")


class DegradingProvider:
    """A provider exposing ``on_rotation``; fires a 'local' failover then replies."""

    def __init__(self, reply: str = "from-local") -> None:
        self.reply = reply
        self._cbs: list[Any] = []

    def on_rotation(self, cb: Any) -> None:
        self._cbs.append(cb)

    def chat(self, messages: Sequence[Message], **_kwargs: Any) -> str:
        for cb in self._cbs:
            cb(_RotEvt("local"))
        return self.reply


@dataclass(frozen=True)
class _RotEvt:
    provider: str


# --------------------------------------------------------------------------- #
# job harness — the REAL JobRegistry with capturing sinks
# --------------------------------------------------------------------------- #
class JobHarness:
    """Wraps a real :class:`JobRegistry`, capturing progress + done emissions."""

    def __init__(self) -> None:
        self.progress: list[tuple[str, int, str]] = []
        self.done: list[tuple[str, Any]] = []
        self.registry = JobRegistry(self._on_progress, self._on_done)

    def _on_progress(self, job_id: str, pct: int, message: str) -> None:
        self.progress.append((job_id, pct, message))

    def _on_done(self, job_id: str, result: Any) -> None:
        self.done.append((job_id, result))

    def messages(self) -> list[str]:
        return [m for _, _, m in self.progress]


# --------------------------------------------------------------------------- #
# plan_ai_job — PURE assembly
# --------------------------------------------------------------------------- #
def test_plan_builds_route_cost_and_cache_key(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = plan_ai_job(
        _inputs(content="abc"),
        pool=_cloud_pool(),
        catalog=FakeCatalog(),
        cache=cache,
    )
    assert isinstance(env, AiJob)
    assert isinstance(env.route, AiRoute)
    assert env.route.providers == ("Groq",)
    assert env.route.degradeChain == ("Groq", "local")
    assert env.route.cacheHit is False
    assert env.route.willEgress is True
    # cacheKey is the AiCache content hash for the same request.
    assert env.cacheKey == cache.key(list(env.inputs.messages), "m", {})
    assert env.costEst.requests == 1
    assert env.costEst.egressBytes == len(b"abc")


def test_plan_uses_explicit_budget_request_when_pinned(tmp_path: Any) -> None:
    inputs = AiInputs(
        messages=({"role": "user", "content": "x"},),
        model="m",
        request=FakeRequest(target_size=4, text_bytes=100, frame_bytes=0),
    )
    env = plan_ai_job(inputs, pool=_cloud_pool(), catalog=FakeCatalog(), cache=AiCache(store_dir=tmp_path))
    assert env.costEst.requests == 4
    assert env.costEst.egressBytes == 400


def test_plan_cache_hit_flags_no_egress(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    inputs = _inputs(content="seeded")
    key = cache.key(list(inputs.messages), "m", {})
    cache.put(key, "already-cached")
    env = plan_ai_job(inputs, pool=_cloud_pool(), catalog=FakeCatalog(), cache=cache)
    assert env.route.cacheHit is True
    assert env.route.willEgress is False
    assert "Cached" in env.preview


def test_plan_local_only_pool_never_egresses(tmp_path: Any) -> None:
    env = plan_ai_job(
        _inputs(),
        pool=_local_only_pool(),
        catalog=FakeCatalog(),
        cache=AiCache(store_dir=tmp_path),
    )
    assert env.route.providers == ()
    assert env.route.willEgress is False
    assert "Local only" in env.preview


def test_plan_preview_includes_provider_and_kb(tmp_path: Any) -> None:
    env = plan_ai_job(
        _inputs(content="payload"),
        pool=_cloud_pool(),
        catalog=FakeCatalog(),
        cache=AiCache(store_dir=tmp_path),
    )
    assert "Groq" in env.preview
    assert "KB" in env.preview


def test_planned_json_has_zero_provider_calls_shape(tmp_path: Any) -> None:
    """ai.planJob's planned() returns route+costEst+cacheHit+willEgress+budget."""
    env = plan_ai_job(_inputs(), pool=_cloud_pool(), catalog=FakeCatalog(), cache=AiCache(store_dir=tmp_path))
    planned = env.planned()
    assert set(planned) >= {"route", "costEst", "cacheHit", "willEgress", "budget"}
    assert planned["route"]["degradeChain"] == ["Groq", "local"]
    assert planned["costEst"]["requests"] == 1
    assert planned["budget"] == planned["costEst"]
    assert planned["cacheHit"] is False


def test_plan_within_free_limits_false_over_cap(tmp_path: Any) -> None:
    inputs = AiInputs(
        messages=({"role": "user", "content": "x"},),
        model="m",
        request=FakeRequest(target_size=10, text_bytes=1, frame_bytes=0),
    )
    env = plan_ai_job(inputs, pool=_cloud_pool(), catalog=FakeCatalog({"Groq": 5}), cache=AiCache(store_dir=tmp_path))
    assert env.costEst.withinFreeLimits is False


# --------------------------------------------------------------------------- #
# run_ai_job — execution on a real JobRegistry
# --------------------------------------------------------------------------- #
def _env(cache: AiCache, *, content: str = "q", pool: Any = None) -> AiJob:
    return plan_ai_job(
        _inputs(content=content),
        pool=pool or _cloud_pool(),
        catalog=FakeCatalog(),
        cache=cache,
    )


def test_run_emits_progress_and_terminal_done(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    harness = JobHarness()
    spy = SpyProvider("answer")
    env = _env(cache)
    job = run_ai_job(env, jobs=harness.registry, provider_factory=lambda: spy, cache=cache)
    harness.registry.join(timeout=5)
    assert job.finished
    # progress emitted, then a terminal job.done with the result.
    assert harness.progress
    assert harness.done[-1][1]["result"] == "answer"
    assert harness.done[-1][1]["cacheHit"] is False
    assert spy.calls  # the provider WAS called on a miss


def test_run_cache_hit_skips_provider(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    inputs = _inputs(content="cached-q")
    key = cache.key(list(inputs.messages), "m", {})
    cache.put(key, "stored-result")
    env = plan_ai_job(inputs, pool=_cloud_pool(), catalog=FakeCatalog(), cache=cache)
    harness = JobHarness()
    spy = SpyProvider("SHOULD-NOT-RUN")

    def _factory() -> SpyProvider:  # pragma: no cover -- must never be invoked on a hit
        return spy

    run_ai_job(env, jobs=harness.registry, provider_factory=_factory, cache=cache)
    harness.registry.join(timeout=5)
    assert harness.done[-1][1] == {"result": "stored-result", "cacheHit": True, "degraded": False}
    assert spy.calls == []  # provider transport spy UNTOUCHED on a cache hit


def test_run_stores_result_in_cache_on_miss(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache, content="fresh")
    harness = JobHarness()
    run_ai_job(env, jobs=harness.registry, provider_factory=lambda: SpyProvider("computed"), cache=cache)
    harness.registry.join(timeout=5)
    assert cache.get(env.cacheKey) == "computed"


def test_run_exhaustion_emits_single_done_error(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    raiser = RaisingProvider()
    run_ai_job(env, jobs=harness.registry, provider_factory=lambda: raiser, cache=cache)
    harness.registry.join(timeout=5)
    # exactly one terminal job.done, carrying the A3 error payload.
    assert len(harness.done) == 1
    err = harness.done[-1][1]["error"]
    assert err["type"] == "ProviderError"
    assert "exhausted" in err["message"]
    assert cache.get(env.cacheKey) is None  # nothing cached on failure


def test_run_degraded_emits_notice(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    run_ai_job(env, jobs=harness.registry, provider_factory=lambda: DegradingProvider("local-ans"), cache=cache)
    harness.registry.join(timeout=5)
    assert any("degraded" in m for m in harness.messages())
    assert harness.done[-1][1]["degraded"] is True
    assert harness.done[-1][1]["result"] == "local-ans"


def test_run_cancel_observed_returns_cancelled(tmp_path: Any) -> None:
    """A job whose cancel flag is set before the body executes makes no call."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)

    # A single-thread registry that finishes synchronously lets us pre-set cancel.
    captured: dict[str, Any] = {}

    class InlineRegistry:
        """Runs the handler inline with a context whose cancel flag is pre-set."""

        def start(self, handler: Any, **_kw: Any) -> Any:
            captured["result"] = handler(_CancelledCtx())
            return _DummyJob()

    spy = SpyProvider()
    run_ai_job(env, jobs=InlineRegistry(), provider_factory=lambda: spy, cache=cache)
    assert captured["result"] == {"cancelled": True}
    assert spy.calls == []  # no provider call after a pre-cancel


def test_run_cancel_after_provider_build_returns_cancelled(tmp_path: Any) -> None:
    """Cancel observed AFTER the factory but before chat: no chat, cancelled."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    captured: dict[str, Any] = {}
    spy = SpyProvider()

    class MidCancelRegistry:
        def start(self, handler: Any, **_kw: Any) -> Any:
            captured["result"] = handler(_CancelAfterFirstCheckCtx())
            return _DummyJob()

    run_ai_job(env, jobs=MidCancelRegistry(), provider_factory=lambda: spy, cache=cache)
    assert captured["result"] == {"cancelled": True}
    assert spy.calls == []


class _CancelledCtx:
    """A JobContext stand-in that is cancelled from the very first check."""

    cancelled = True

    def progress(self, _pct: float, _msg: str = "") -> None:  # pragma: no cover -- never reached pre-cancel
        raise AssertionError("progress must not be called on a pre-cancelled job")


class _CancelAfterFirstCheckCtx:
    """Cancelled = False on the first check, True after the provider is built."""

    def __init__(self) -> None:
        self._checks = 0

    @property
    def cancelled(self) -> bool:
        self._checks += 1
        return self._checks > 1  # first check (entry) False; second (post-build) True

    def progress(self, _pct: float, _msg: str = "") -> None:
        return None


@dataclass
class _DummyJob:
    finished: bool = True


def test_run_passes_metadata_to_registry(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    captured: dict[str, Any] = {}

    class CapturingRegistry:
        def start(self, handler: Any, **kw: Any) -> Any:
            captured.update(kw)
            handler(_NoopCtx())
            return _DummyJob()

    run_ai_job(
        env,
        jobs=CapturingRegistry(),
        provider_factory=lambda: SpyProvider(),
        cache=cache,
        feature="phase8",
        label="Select",
        videoId="vid-1",
    )
    assert captured == {"feature": "phase8", "label": "Select", "videoId": "vid-1"}


class _NoopCtx:
    cancelled = False

    def progress(self, _pct: float, _msg: str = "") -> None:
        return None


def test_subscribe_degrade_noop_on_plain_provider(tmp_path: Any) -> None:
    """A provider without on_rotation never degrades (graceful no-op)."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    run_ai_job(env, jobs=harness.registry, provider_factory=lambda: SpyProvider("plain"), cache=cache)
    harness.registry.join(timeout=5)
    assert harness.done[-1][1]["degraded"] is False


def test_degrade_listener_ignores_non_local_rotation(tmp_path: Any) -> None:
    """A failover to another CLOUD provider is not a degrade."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()

    class CloudFailoverProvider:
        def __init__(self) -> None:
            self._cbs: list[Any] = []

        def on_rotation(self, cb: Any) -> None:
            self._cbs.append(cb)

        def chat(self, messages: Sequence[Message], **_kwargs: Any) -> str:
            for cb in self._cbs:
                cb(_RotEvt("Cerebras"))  # cloud -> cloud, NOT local
            return "cloud2"

    run_ai_job(env, jobs=harness.registry, provider_factory=CloudFailoverProvider, cache=cache)
    harness.registry.join(timeout=5)
    assert harness.done[-1][1]["degraded"] is False
    assert harness.done[-1][1]["result"] == "cloud2"


def test_run_returns_the_job(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    job = run_ai_job(env, jobs=harness.registry, provider_factory=lambda: SpyProvider(), cache=cache)
    harness.registry.join(timeout=5)
    assert hasattr(job, "id")


# --------------------------------------------------------------------------- #
# run_ai_job — custom work body (the phase8_select / subtitles_translate path)
# --------------------------------------------------------------------------- #
def test_run_custom_work_returns_handler_shape(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    spy = SpyProvider("ranked")
    seen: dict[str, Any] = {}

    def work(ctx: Any, envelope: AiJob, provider: Any) -> dict[str, Any]:
        seen["provider"] = provider
        seen["cacheKey"] = envelope.cacheKey
        ctx.progress(50.0, "selecting")
        return {"candidates": [provider.chat(list(envelope.inputs.messages))]}

    run_ai_job(env, jobs=harness.registry, provider_factory=lambda: spy, cache=cache, work=work)
    harness.registry.join(timeout=5)
    # the handler's OWN result shape flows straight to job.done (no {result} wrap).
    assert harness.done[-1][1] == {"candidates": ["ranked"]}
    assert seen["provider"] is spy
    assert seen["cacheKey"] == env.cacheKey


def test_run_custom_work_emits_degraded_notice(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()

    def work(ctx: Any, envelope: AiJob, provider: Any) -> dict[str, Any]:
        return {"track": provider.chat(list(envelope.inputs.messages))}

    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: DegradingProvider("local-track"),
        cache=cache,
        work=work,
    )
    harness.registry.join(timeout=5)
    assert any("degraded" in m for m in harness.messages())
    assert harness.done[-1][1] == {"track": "local-track"}


def test_run_custom_work_honors_precancel(tmp_path: Any) -> None:
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    spy = SpyProvider()
    captured: dict[str, Any] = {}

    def work(_ctx: Any, _env: AiJob, _prov: Any) -> dict[str, Any]:  # pragma: no cover -- never reached pre-cancel
        raise AssertionError("work must not run on a pre-cancelled job")

    class InlineRegistry:
        def start(self, handler: Any, **_kw: Any) -> Any:
            captured["result"] = handler(_CancelledCtx())
            return _DummyJob()

    run_ai_job(env, jobs=InlineRegistry(), provider_factory=lambda: spy, cache=cache, work=work)
    assert captured["result"] == {"cancelled": True}
    assert spy.calls == []


# --------------------------------------------------------------------------- #
# run_ai_job — on_egress completion callback (WU-spend-cap record-at-completion)
# --------------------------------------------------------------------------- #
def test_on_egress_fires_after_a_real_cloud_run(tmp_path: Any) -> None:
    """A miss against a cloud pool egresses → the callback fires exactly once."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)  # cloud pool, fresh content -> willEgress True
    harness = JobHarness()
    fired: list[AiJob] = []
    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: SpyProvider("ans"),
        cache=cache,
        on_egress=fired.append,
    )
    harness.registry.join(timeout=5)
    assert len(fired) == 1
    assert fired[0] is env


def test_on_egress_records_on_degraded_to_local(tmp_path: Any) -> None:
    """A run that fell through to local still egressed (attempted cloud) → record."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    fired: list[AiJob] = []
    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: DegradingProvider("local-ans"),
        cache=cache,
        on_egress=fired.append,
    )
    harness.registry.join(timeout=5)
    assert len(fired) == 1


def test_on_egress_skipped_for_local_only_pool(tmp_path: Any) -> None:
    """A local-only pool never egresses → the callback must NOT fire."""
    cache = AiCache(store_dir=tmp_path)
    env = plan_ai_job(_inputs(content="loc"), pool=_local_only_pool(), catalog=FakeCatalog(), cache=cache)
    assert env.route.willEgress is False
    harness = JobHarness()
    fired: list[AiJob] = []
    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: SpyProvider("ans"),
        cache=cache,
        on_egress=fired.append,
    )
    harness.registry.join(timeout=5)
    assert fired == []


def test_on_egress_skipped_on_cache_hit(tmp_path: Any) -> None:
    """A cache hit returns before the provider → no egress, no record."""
    cache = AiCache(store_dir=tmp_path)
    inputs = _inputs(content="hot")
    env = plan_ai_job(inputs, pool=_cloud_pool(), catalog=FakeCatalog(), cache=cache)
    cache.put(env.cacheKey, "stored")  # populate AFTER planning -> runtime hit
    harness = JobHarness()
    fired: list[AiJob] = []
    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: SpyProvider("SHOULD-NOT-RUN"),
        cache=cache,
        on_egress=fired.append,
    )
    harness.registry.join(timeout=5)
    assert fired == []


def test_on_egress_skipped_when_provider_errors(tmp_path: Any) -> None:
    """A provider exception aborts before the record point → ledger untouched."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    fired: list[AiJob] = []
    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: RaisingProvider(),
        cache=cache,
        on_egress=fired.append,
    )
    harness.registry.join(timeout=5)
    assert fired == []


def test_on_egress_fires_for_custom_work_cloud_run(tmp_path: Any) -> None:
    """The custom-work path also records when it egressed over a cloud pool."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    fired: list[AiJob] = []

    def work(ctx: Any, envelope: AiJob, provider: Any) -> dict[str, Any]:
        return {"candidates": [provider.chat(list(envelope.inputs.messages))]}

    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: SpyProvider("ranked"),
        cache=cache,
        work=work,
        on_egress=fired.append,
    )
    harness.registry.join(timeout=5)
    assert len(fired) == 1


def test_on_egress_skipped_for_custom_work_local_only(tmp_path: Any) -> None:
    """Custom work over a local-only pool does not egress → no record."""
    cache = AiCache(store_dir=tmp_path)
    env = plan_ai_job(_inputs(content="cw-loc"), pool=_local_only_pool(), catalog=FakeCatalog(), cache=cache)
    harness = JobHarness()
    fired: list[AiJob] = []

    def work(ctx: Any, envelope: AiJob, provider: Any) -> dict[str, Any]:
        return {"track": provider.chat(list(envelope.inputs.messages))}

    run_ai_job(
        env,
        jobs=harness.registry,
        provider_factory=lambda: SpyProvider("ans"),
        cache=cache,
        work=work,
        on_egress=fired.append,
    )
    harness.registry.join(timeout=5)
    assert fired == []


def test_run_without_on_egress_is_unchanged(tmp_path: Any) -> None:
    """The default (no on_egress) path runs exactly as before — backward compat."""
    cache = AiCache(store_dir=tmp_path)
    env = _env(cache)
    harness = JobHarness()
    run_ai_job(env, jobs=harness.registry, provider_factory=lambda: SpyProvider("ans"), cache=cache)
    harness.registry.join(timeout=5)
    assert harness.done[-1][1]["result"] == "ans"


# --------------------------------------------------------------------------- #
# CatalogFreeCapAdapter (WAVE-1 carryforward #1)
# --------------------------------------------------------------------------- #
def test_catalog_adapter_reports_uncapped() -> None:
    adapter = CatalogFreeCapAdapter()
    assert adapter.free_cap("Groq") is None
    assert adapter.free_cap("anything") is None


def test_catalog_adapter_holds_module_reference() -> None:
    from media_studio.models import catalog as real_catalog

    adapter = CatalogFreeCapAdapter(real_catalog)
    # adapter integrates with the real budget estimate (uncapped -> within limits).
    env = plan_ai_job(
        _inputs(content="x"),
        pool=_cloud_pool(),
        catalog=adapter,
        cache=AiCache(store_dir=__import__("tempfile").mkdtemp()),
    )
    assert env.costEst.withinFreeLimits is True
