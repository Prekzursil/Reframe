"""Tests for the WU-spend-cap handler surface (monthly cumulative spend ceiling).

The per-run budget gate (test_handlers_budget_preflight) only sizes ONE run; this
WU bounds the MONTH-TO-DATE total accrued across many approved cloud-AI runs:

  * a hard-cap REFUSAL before egress when ``enforceMonthlyHardLimit`` and
    ``month_to_date + this-job-estimate`` exceeds ``monthlyHardLimitCents``
    (independent of the ``confirmCloudBudget`` ack gate);
  * a non-blocking soft WARNING merged into ``ai.planJob`` output when over the
    soft cap;
  * recording each egressing run's estimated cost in the spend ledger at
    completion;
  * the ``providers.spend`` RPC returning month-to-date + the configured caps;
  * backward compatibility: defaults off/0 cap and warn nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models.ai_cache import Message
from media_studio.models.spend_ledger import SpendLedger
from media_studio.protocol import RpcContext, RpcError

# 2026-06-21 00:00:00 UTC -> month "2026-06".
_JUN_2026 = 1781913600.0


class _CloudEntry:
    provider = "Groq"
    local = False


class _LocalEntry:
    provider = "local"
    local = True


class _CloudPool:
    entries = (_CloudEntry(), _LocalEntry())


class SpyProvider:
    def __init__(self, reply: str = "answer") -> None:
        self.reply = reply
        self.calls: list[Any] = []

    def chat(self, messages: Sequence[Message], **_kwargs: Any) -> str:
        self.calls.append(list(messages))
        return self.reply


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


@pytest.fixture
def svc(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", provider=SpyProvider(), library=None, now=lambda: _JUN_2026)


def _cloud(svc: Services) -> None:
    """Force an egressing (cloud) pool so willEgress is True."""
    svc._ai_pool = lambda: _CloudPool()  # type: ignore[method-assign]


def _envelope(svc: Services, content: str = "q") -> Any:
    from media_studio.models import ai_job as _ai_job

    inputs = _ai_job.AiInputs(messages=({"role": "user", "content": content},), model="m")
    return svc.plan_ai_job_envelope(inputs)


# --------------------------------------------------------------------------- #
# the cents estimate seam — non-zero for a real cloud run
# --------------------------------------------------------------------------- #
def test_job_cents_estimate_is_non_zero_for_cloud_run(svc: Services) -> None:
    _cloud(svc)
    env = _envelope(svc)
    assert svc._estimate_job_cents(env) > 0


def test_job_cents_estimate_is_zero_for_local_only(svc: Services) -> None:
    env = _envelope(svc)  # default local-only pool
    assert env.route.willEgress is False
    assert svc._estimate_job_cents(env) == 0


# --------------------------------------------------------------------------- #
# the spend ledger accessor
# --------------------------------------------------------------------------- #
def test_spend_ledger_lives_under_data_dir(svc: Services) -> None:
    ledger = svc._spend_ledger()
    assert isinstance(ledger, SpendLedger)
    assert ledger.path == svc.data_dir / "spend-ledger.json"


def test_spend_ledger_uses_the_injected_clock(svc: Services) -> None:
    ledger = svc._spend_ledger()
    assert ledger.current_month() == "2026-06"


# --------------------------------------------------------------------------- #
# hard-cap refusal (synchronous, before egress)
# --------------------------------------------------------------------------- #
def _run(svc: Services, provider: Any = None) -> tuple[JobRegistry, list[Any]]:
    done: list[Any] = []
    registry = JobRegistry(lambda *_a: None, lambda jid, res: done.append(res))
    rctx = RpcContext(emit_notification=lambda obj: None, jobs=registry)
    job = svc._run_ai_job(
        rctx,
        messages=[{"role": "user", "content": "go"}],
        model="m",
        provider=provider or SpyProvider("ok"),
        work=None,
        feature="ai",
        label="AI",
        ack=None,
    )
    registry.join(timeout=5)
    return registry, done, job  # type: ignore[return-value]


def test_hard_cap_refuses_when_over_ceiling(svc: Services) -> None:
    _cloud(svc)
    svc.settings.set({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 50, "confirmCloudBudget": False})
    # Pre-load the ledger AT the cap so this job (cost >= 1) tips it strictly over.
    svc._spend_ledger().record(50)
    rctx = RpcContext(emit_notification=lambda obj: None, jobs=JobRegistry(lambda *_a: None, lambda *_a: None))
    with pytest.raises(RpcError, match=r"monthly spend cap \$0\.50 reached"):
        svc._run_ai_job(
            rctx,
            messages=[{"role": "user", "content": "go"}],
            model="m",
            provider=SpyProvider("ok"),
            work=None,
            feature="ai",
            label="AI",
            ack=None,
        )


def test_hard_cap_allows_projected_exactly_at_ceiling(svc: Services) -> None:
    # projected == cap is NOT "exceeded" -> the run proceeds (strict >).
    _cloud(svc)
    svc.settings.set({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 50, "confirmCloudBudget": False})
    svc._spend_ledger().record(49)  # +1 job estimate -> projected 50 == cap
    _registry, done, job = _run(svc, SpyProvider("ok"))
    assert job.finished
    assert done[-1]["result"] == "ok"


def test_hard_cap_ignored_when_limit_is_zero(svc: Services) -> None:
    # enforce ON but cap 0 -> treated as unconfigured -> no refusal.
    _cloud(svc)
    svc.settings.set({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 0, "confirmCloudBudget": False})
    svc._spend_ledger().record(9999)
    _registry, done, job = _run(svc, SpyProvider("ok"))
    assert job.finished


def test_hard_cap_proceeds_when_under_ceiling(svc: Services) -> None:
    _cloud(svc)
    svc.settings.set({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 100000, "confirmCloudBudget": False})
    _registry, done, job = _run(svc, SpyProvider("ok"))
    assert job.finished
    assert done[-1]["result"] == "ok"


def test_hard_cap_not_enforced_when_switch_off(svc: Services) -> None:
    _cloud(svc)
    # Cap is tiny + already exceeded, but enforcement is OFF -> the run proceeds.
    svc.settings.set({"enforceMonthlyHardLimit": False, "monthlyHardLimitCents": 1, "confirmCloudBudget": False})
    svc._spend_ledger().record(9999)
    _registry, done, job = _run(svc, SpyProvider("ok"))
    assert job.finished
    assert done[-1]["result"] == "ok"


def test_hard_cap_ignores_local_only_run(svc: Services) -> None:
    # No cloud pool -> local-only -> never egresses -> never refused, even over cap.
    svc.settings.set({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 1, "confirmCloudBudget": False})
    svc._spend_ledger().record(9999)
    _registry, done, job = _run(svc, SpyProvider("loc"))
    assert job.finished


def test_hard_cap_independent_of_confirm_cloud_budget(svc: Services) -> None:
    # confirmCloudBudget is ON (would require an ack), but we pass the matching ack;
    # the hard cap must STILL refuse the over-cap run.
    _cloud(svc)
    svc.settings.set({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 1, "confirmCloudBudget": True})
    svc._spend_ledger().record(9999)
    env = _envelope(svc)
    rctx = RpcContext(emit_notification=lambda obj: None, jobs=JobRegistry(lambda *_a: None, lambda *_a: None))
    with pytest.raises(RpcError, match="monthly spend cap"):
        svc._run_ai_job(
            rctx,
            messages=[{"role": "user", "content": "q"}],
            model="m",
            provider=SpyProvider("ok"),
            work=None,
            feature="ai",
            label="AI",
            ack=env.cacheKey,
        )


# --------------------------------------------------------------------------- #
# record-at-completion (the on_egress closure)
# --------------------------------------------------------------------------- #
def test_completed_cloud_run_records_cost(svc: Services) -> None:
    _cloud(svc)
    svc.settings.set({"confirmCloudBudget": False})
    before = svc._spend_ledger().month_to_date()
    assert before == 0
    _registry, done, job = _run(svc, SpyProvider("ok"))
    assert job.finished
    after = svc._spend_ledger().month_to_date()
    assert after > 0


def test_local_only_run_records_nothing(svc: Services) -> None:
    svc.settings.set({"confirmCloudBudget": False})
    _registry, done, job = _run(svc, SpyProvider("loc"))
    assert job.finished
    assert svc._spend_ledger().month_to_date() == 0


# --------------------------------------------------------------------------- #
# soft-cap warning on ai.planJob (non-blocking)
# --------------------------------------------------------------------------- #
def test_soft_warning_present_when_over_soft_cap(svc: Services) -> None:
    _cloud(svc)
    svc.settings.set({"monthlySoftLimitCents": 10})
    svc._spend_ledger().record(20)  # already over the soft cap
    out = svc.ai_plan_job({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, ctx=_rctx())
    assert "spendWarning" in out
    assert out["spendWarning"]["softLimitCents"] == 10
    assert out["spendWarning"]["monthToDateCents"] == 20


def test_no_soft_warning_when_under_soft_cap(svc: Services) -> None:
    _cloud(svc)
    svc.settings.set({"monthlySoftLimitCents": 100000})
    out = svc.ai_plan_job({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, ctx=_rctx())
    assert "spendWarning" not in out


def test_no_soft_warning_when_soft_cap_disabled(svc: Services) -> None:
    _cloud(svc)
    svc.settings.set({"monthlySoftLimitCents": 0})
    svc._spend_ledger().record(99999)
    out = svc.ai_plan_job({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, ctx=_rctx())
    assert "spendWarning" not in out


def test_no_soft_warning_for_local_only_plan(svc: Services) -> None:
    # local-only -> zero job estimate; MTD alone under cap -> no warning.
    svc.settings.set({"monthlySoftLimitCents": 100})
    out = svc.ai_plan_job({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, ctx=_rctx())
    assert "spendWarning" not in out


# --------------------------------------------------------------------------- #
# providers.spend RPC
# --------------------------------------------------------------------------- #
def test_providers_spend_reports_mtd_and_caps(svc: Services) -> None:
    svc.settings.set({"monthlySoftLimitCents": 500, "monthlyHardLimitCents": 2000, "enforceMonthlyHardLimit": True})
    svc._spend_ledger().record(123)
    out = svc.providers_spend({}, _rctx())
    assert out["month"] == "2026-06"
    assert out["monthToDateCents"] == 123
    assert out["softLimitCents"] == 500
    assert out["hardLimitCents"] == 2000
    assert out["enforceHardLimit"] is True


def test_providers_spend_defaults_are_off(svc: Services) -> None:
    out = svc.providers_spend({}, _rctx())
    assert out["monthToDateCents"] == 0
    assert out["softLimitCents"] == 0
    assert out["hardLimitCents"] == 0
    assert out["enforceHardLimit"] is False


def test_providers_spend_registered_in_register_all(tmp_path: Path) -> None:
    from media_studio import handlers, protocol

    svc = Services(data_dir=tmp_path / "data", provider=SpyProvider(), library=None)
    handlers.register_all(svc)
    assert "providers.spend" in protocol.METHODS


# --------------------------------------------------------------------------- #
# backward compatibility: defaults off => no cap, no warning, but still records
# --------------------------------------------------------------------------- #
def test_defaults_do_not_cap_or_warn(svc: Services) -> None:
    _cloud(svc)
    svc.settings.set({"confirmCloudBudget": False})
    # Defaults: enforceMonthlyHardLimit False, both caps 0. Even with a big prior
    # spend, the run is neither refused nor warned.
    svc._spend_ledger().record(1_000_000)
    out = svc.ai_plan_job({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, ctx=_rctx())
    assert "spendWarning" not in out
    _registry, done, job = _run(svc, SpyProvider("ok"))
    assert job.finished
    assert done[-1]["result"] == "ok"


def _rctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


# --------------------------------------------------------------------------- #
# index.* egress paths — the OTHER cloud chokepoint (build job + sync search)
# These prove the monthly cap + recording also cover index embedding egress, not
# just _run_ai_job (a willEgress-only coverage gate would miss a bypassing path).
# --------------------------------------------------------------------------- #
class _SpyTransport:
    """A fake ``/v1/embeddings`` transport: returns a fixed-dim vector per input."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append(body)
        inputs = body.get("input") or []
        return {"data": [{"embedding": [float(len(str(t))), 1.0]} for t in inputs]}


def _index_cloud_settings() -> dict[str, Any]:
    """Cloud index route with TEXT consent granted so willEgress is True."""
    return {
        "confirmCloudBudget": False,
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
        "consent": {"perProvider": {"OpenAI": {"text": True}}},
    }


def _index_svc(tmp_path: Path, spy: _SpyTransport) -> tuple[Services, str]:
    from media_studio import library as _library

    svc = Services(data_dir=tmp_path / "data", provider=SpyProvider(), embed_transport=spy, now=lambda: _JUN_2026)
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 30.0)
    vid = svc.library.add(str(media))["id"]
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = {
        "language": "en",
        "durationSec": 30.0,
        "segments": [{"start": 0.0, "end": 5.0, "text": "pricing talk"}],
    }
    project.save()
    return svc, vid


def _index_ctx() -> RpcContext:
    events: list[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda *_a: None,
        emit_done=lambda jid, result: events.append(result),
    )
    rctx = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    rctx.events = events  # type: ignore[attr-defined]
    return rctx


def test_index_build_cloud_run_records_spend(tmp_path: Path) -> None:
    spy = _SpyTransport()
    svc, vid = _index_svc(tmp_path, spy)
    svc.settings.set(_index_cloud_settings())
    assert svc._spend_ledger().month_to_date() == 0
    ctx = _index_ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    assert spy.calls, "consent granted but no cloud egress happened"
    assert svc._spend_ledger().month_to_date() > 0


def test_index_build_hard_cap_refuses_before_egress(tmp_path: Path) -> None:
    spy = _SpyTransport()
    svc, vid = _index_svc(tmp_path, spy)
    settings = _index_cloud_settings()
    settings.update({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 1})
    svc.settings.set(settings)
    svc._spend_ledger().record(9999)
    with pytest.raises(RpcError, match="monthly spend cap"):
        svc.index_build({"videoId": vid}, _index_ctx())
    assert spy.calls == [], "index build egressed despite being over the hard cap"


def test_index_search_cloud_query_records_spend(tmp_path: Path) -> None:
    spy = _SpyTransport()
    svc, vid = _index_svc(tmp_path, spy)
    svc.settings.set(_index_cloud_settings())
    # Build first (also records); then isolate the search-side record.
    ctx = _index_ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    after_build = svc._spend_ledger().month_to_date()
    spy.calls.clear()
    svc.index_search({"videoId": vid, "query": "pricing talk"}, _index_ctx())
    assert spy.calls, "search query did not egress"
    assert svc._spend_ledger().month_to_date() > after_build


def test_index_search_hard_cap_refuses_before_egress(tmp_path: Path) -> None:
    spy = _SpyTransport()
    svc, vid = _index_svc(tmp_path, spy)
    svc.settings.set(_index_cloud_settings())
    # Build under-cap so the index exists, then tighten the cap before searching.
    ctx = _index_ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    spy.calls.clear()
    settings = _index_cloud_settings()
    settings.update({"enforceMonthlyHardLimit": True, "monthlyHardLimitCents": 1})
    svc.settings.set(settings)
    svc._spend_ledger().record(9999)
    with pytest.raises(RpcError, match="monthly spend cap"):
        svc.index_search({"videoId": vid, "query": "pricing talk"}, _index_ctx())
    assert spy.calls == [], "index search egressed despite being over the hard cap"


def test_index_search_cache_hit_records_nothing(tmp_path: Path) -> None:
    spy = _SpyTransport()
    svc, vid = _index_svc(tmp_path, spy)
    svc.settings.set(_index_cloud_settings())
    ctx = _index_ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    # First search egresses + records; a repeat identical query hits the cache.
    svc.index_search({"videoId": vid, "query": "repeat me"}, _index_ctx())
    mtd_after_first = svc._spend_ledger().month_to_date()
    spy.calls.clear()
    svc.index_search({"videoId": vid, "query": "repeat me"}, _index_ctx())
    assert spy.calls == [], "a cached query re-embedded"
    assert svc._spend_ledger().month_to_date() == mtd_after_first
