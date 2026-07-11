"""Cross-edit tests for the WU ``index.plan`` handler (vision_ops.index_plan).

Isolated (uniquely-named) so it never collides with the consolidated
``test_handlers_index.py``. ``index.plan`` is the pure PLANNING twin of
``index.build`` / ``index.search``: it constructs the SAME ``ai_job.AiInputs``
those handlers build and returns ``envelope.planned()`` WITHOUT starting a job or
touching a provider. These tests pin every new branch of the ``content`` ternary
(query present / query blank / query absent) plus the consent-driven
``willEgress`` surface and the cacheKey round-trip that ``index.search`` demands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models import ai_job as _ai_job
from media_studio.protocol import ErrorCode, RpcContext, RpcError


class FakeProvider:
    def chat(self, *args: Any, **kwargs: Any) -> str:
        return "[]"


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


def _add_video_with_transcript(svc: Services, tmp_path: Path) -> str:
    from media_studio import library as _library

    media = tmp_path / "talk.mp4"
    media.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 30.0)
    vid = svc.library.add(str(media))["id"]
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = {
        "language": "en",
        "durationSec": 30.0,
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "we talk about pricing here"},
            {"start": 5.0, "end": 10.0, "text": "now a totally different topic"},
        ],
    }
    project.save()
    return vid


# --------------------------------------------------------------------------- #
# boundary validation: a missing/blank videoId is a loud INVALID_PARAMS
# --------------------------------------------------------------------------- #
def test_index_plan_requires_video_id(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError) as ei:
        svc.index_plan({}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# query-present branch: cacheKey mirrors the SAME inputs index.search builds and
# willEgress is True under a text-consented cloud embedder.
# --------------------------------------------------------------------------- #
def test_index_plan_query_present_matches_search_cachekey_and_egresses(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set(_cloud_settings(text_consent=True))
    plan = svc.index_plan({"videoId": "v1", "query": "pricing"}, _ctx())

    expected = svc._plan_index_envelope(
        _ai_job.AiInputs(messages=({"role": "user", "content": "pricing"},), model="")
    )
    assert plan["cacheKey"] == expected.cacheKey
    assert plan["willEgress"] is True


# --------------------------------------------------------------------------- #
# query-absent branch: content defaults to the "index.build" sentinel, so the
# plan matches index.build's own envelope inputs.
# --------------------------------------------------------------------------- #
def test_index_plan_no_query_defaults_to_build_sentinel(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set(_cloud_settings(text_consent=True))
    plan = svc.index_plan({"videoId": "v1"}, _ctx())

    expected = svc._plan_index_envelope(
        _ai_job.AiInputs(messages=({"role": "user", "content": "index.build"},), model="")
    )
    assert plan["cacheKey"] == expected.cacheKey


# --------------------------------------------------------------------------- #
# query-blank branch: an empty-string query is falsy, so it ALSO falls to the
# "index.build" sentinel (exercises the ``and`` false-with-str-type arc).
# --------------------------------------------------------------------------- #
def test_index_plan_blank_query_falls_back_to_build_sentinel(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set(_cloud_settings(text_consent=True))
    plan = svc.index_plan({"videoId": "v1", "query": ""}, _ctx())

    expected = svc._plan_index_envelope(
        _ai_job.AiInputs(messages=({"role": "user", "content": "index.build"},), model="")
    )
    assert plan["cacheKey"] == expected.cacheKey


# --------------------------------------------------------------------------- #
# consent-denied: the text-consent filter strips the cloud provider, so the plan
# routes local and willEgress is False (no budget ack ever demanded).
# --------------------------------------------------------------------------- #
def test_index_plan_consent_denied_will_not_egress(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set(_cloud_settings(text_consent=False))
    plan = svc.index_plan({"videoId": "v1", "query": "pricing"}, _ctx())
    assert plan["willEgress"] is False


# --------------------------------------------------------------------------- #
# round-trip: the plan's cacheKey is exactly the confirmBudget ack index.search's
# _enforce_egress_gates demands, so re-issuing search with it proceeds + egresses.
# --------------------------------------------------------------------------- #
def test_index_plan_cachekey_round_trips_through_index_search(tmp_path: Path) -> None:
    spy = SpyTransport()
    svc = _services(tmp_path, embed_transport=spy)
    vid = _add_video_with_transcript(svc, tmp_path)
    # Build under consent with the budget gate OFF so the build itself needs no ack.
    svc.settings.set(_cloud_settings(text_consent=True))
    ctx = _ctx()
    svc.index_build({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)
    _done_result(ctx)
    spy.calls.clear()

    # Turn the budget gate ON: an unacked cloud search is refused before any egress.
    svc.settings.set(_cloud_settings(text_consent=True, confirm_budget=True))
    with pytest.raises(RpcError) as ei:
        svc.index_search({"videoId": vid, "query": "q"}, _ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS
    assert spy.calls == []

    # Recover the ack via index.plan and re-issue -> the search now proceeds.
    ack = svc.index_plan({"videoId": vid, "query": "q"}, _ctx())["cacheKey"]
    out = svc.index_search({"videoId": vid, "query": "q", "confirmBudget": ack}, _ctx())
    assert spy.calls, "acked cloud search still did not egress"
    assert "hits" in out
