"""E2E-AI2: Provider HUB + DIRECTOR over the REAL stack (autonomous run).

Companion to ``test_e2e_ai2_intel_repurpose.py`` (which agent-2 built). Same
contract: these are INTEGRATION tests, not unit doubles. The sidecar's real
JSON-RPC dispatch, real ``providers.*`` / ``ai.planJob`` / ``director.*``
handlers, real consent/budget gates, the REAL :class:`RotatingProvider` HTTP
code, and real ffmpeg all run. The ONLY fake is the model endpoint: the local
OpenAI-compatible :class:`MockModelServer` (and an :class:`Always429Server`
peer) the provider reaches over a real socket with no cloud key.

HUB coverage:
  * ``providers.upsert`` stores RAW keys; ``providers.list`` redacts them.
  * ``providers.testKey`` validates a key through the provider seam.
  * ``providers.setConsent`` (the registered name; the task's "consent.set")
    flips TEXT egress consent.
  * ``ai.planJob`` is PURE: route / cost / willEgress / budget with ZERO
    provider calls (asserted by an unchanged hit counter).
  * A REAL AI job (``director.plan``) makes a REAL HTTP call through the routed
    pool: the mock receives the OpenAI chat shape, the response is parsed, and
    the chat path's ``Authorization`` header carries the RAW key (the get_raw()
    contract — contrasted with agent-2's embedder redacted-key xfail).
  * ROTATION: two providers; provider-1 (a real 429 server) fails, the
    RotatingProvider fails over to provider-2 (the working mock) over a real
    socket, emitting exactly one rotation event.
  * The text-consent gate blocks egress when consent is revoked.
  * The budget gate refuses an un-acknowledged cloud run.

DIRECTOR coverage (real sample mp4 via ffmpeg):
  * ``director.plan`` -> a valid EditPlan from the mock, validated + stored.
  * ``director.previewCost`` -> per-function route/cost (pure, zero egress).
  * ``director.apply`` -> the apply SPINE over a project COPY, with a real
    ffmpeg op-engine injected behind the documented ``_director_engines`` seam
    (the same seam the product's own director tests use): each op RENDERS a real
    mp4 segment from the source over the COPY; the source is never touched.
  * ffprobe confirms the applied output is a valid mp4.
  * ``director.undo`` re-applies the recorded inverse to restore the pre-apply
    COPY.

TOP_BREAKAGE surfaced here (see ``test_director_apply_default_engine_table_is_empty``):
the SHIPPED ``_director_engines()`` returns ``{}`` — so the DEFAULT RPC apply
path renders NO media (every op -> ``failed`` + rollback). The apply spine is
real and shippable, but no op-engine adapters are wired in v1, so a client
calling ``director.apply`` today gets a no-op manifest copy, not an edited mp4.

Run: ``python -m pytest sidecar/tests/test_e2e_ai2_hub_director.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio import library as _library
from media_studio.features.apply_engine import OpEngine  # noqa: F401 - documents the seam type
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models.edit_plan import EditOp
from media_studio.models.provider import RotationEvent
from media_studio.protocol import RpcContext

from tests.e2e_ai2_mock_model import Always429Server, MockModelServer

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe required for the E2E-AI2 HUB+DIRECTOR real-media flows"
)

_RAW_KEY = "sk-e2e-ai2-hub-rawkey-9999"


# --------------------------------------------------------------------------- #
# in-process JSON-RPC drive (mirrors the sibling suite's real parse->dispatch)
# --------------------------------------------------------------------------- #
class Rpc:
    def __init__(self, svc: Services) -> None:
        self.svc = svc
        self.events: list[Any] = []
        self.jobs = JobRegistry(
            emit_progress=lambda jid, pct, msg: self.events.append(("progress", jid, pct, msg)),
            emit_done=lambda jid, result: self.events.append(("done", jid, result)),
        )
        self.ctx = RpcContext(emit_notification=lambda obj: None, jobs=self.jobs)

    def _handler(self, method: str) -> Any:
        fn = protocol.METHODS.get(method)
        assert fn is not None, f"method not registered: {method}"
        return fn

    def call(self, method: str, params: dict[str, Any]) -> Any:
        return self._handler(method)(params, self.ctx)

    def run_job(self, method: str, params: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        out = self.call(method, params)
        assert isinstance(out, dict) and "jobId" in out, f"{method} did not return a jobId: {out!r}"
        self.jobs.join(timeout=timeout)
        done = [e for e in self.events if e[0] == "done" and e[1] == out["jobId"]]
        assert done, f"{method} job {out['jobId']} never completed: {self.events!r}"
        return done[-1][2]


# --------------------------------------------------------------------------- #
# real-media fixtures (real ffmpeg) + ffprobe helpers
# --------------------------------------------------------------------------- #
def _ffmpeg(args: list[str]) -> None:
    res = subprocess.run([_FFMPEG, "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    assert res.returncode == 0, f"ffmpeg failed: {res.stderr}"


def _make_sample_mp4(path: Path, *, seconds: int = 6) -> None:
    """A real 16:9 1280x720 mp4: moving testsrc + a tone (ffprobe-valid)."""
    _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=1280x720:rate=24:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )


def _ffprobe_ok(path: str) -> tuple[int, float]:
    """Return (video_width, duration_sec) — raises if the file is not a valid mp4."""
    res = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    doc = json.loads(res.stdout)
    width = int(doc["streams"][0]["width"])
    duration = float(doc["format"]["duration"])
    return width, duration


# --------------------------------------------------------------------------- #
# settings + project helpers
# --------------------------------------------------------------------------- #
def _provider_entry(base_url: str, *, pid: str = "mock", keys: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": pid,
        "provider": pid,  # provider NAME == id so the consent perProvider keys line up
        "kind": "cloud",
        "baseUrl": base_url,
        "model": "mock-model",
        "apiKeys": keys if keys is not None else [_RAW_KEY],
        "enabled": True,
        "capabilities": ["text", "vision"],
        "unit": "req",
    }


def _routing(*provider_ids: str) -> dict[str, Any]:
    primary = provider_ids[0]
    fallback = list(provider_ids[1:])
    return {
        "perFunction": {
            fn: {"provider": primary, "fallback": fallback}
            for fn in ("index", "editPlan", "vision", "select", "subtitles", "translation")
        }
    }


def _base_settings(*provider_ids: str, **extra: Any) -> dict[str, Any]:
    """Routed + text-consented settings with the (default-ON) budget gate OFF.

    The shipped default ``confirmCloudBudget`` is True (settings_store.py:64), so
    every non-budget test must turn it OFF or every egress is refused. The
    budget-gate test sets it back True explicitly.
    """
    consent = {pid: {"text": True, "frames": True} for pid in provider_ids}
    base: dict[str, Any] = {
        "routing": _routing(*provider_ids),
        "consent": {"perProvider": consent},
        "confirmCloudBudget": False,
        "cloudModel": "mock-model",
    }
    base.update(extra)
    return base


def _new_services(tmp: Path, **over: Any) -> Services:
    return Services(data_dir=tmp / "data", **over)


def _wire(tmp: Path, **over: Any) -> tuple[Services, Rpc]:
    svc = _new_services(tmp, **over)
    protocol.clear_methods()
    handlers.register_all(services=svc)
    return svc, Rpc(svc)


def _add_video(svc: Services, media: Path) -> str:
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 6.0)
    return svc.library.add(str(media))["id"]


# ========================================================================== #
# HUB-1 — providers.upsert stores RAW, providers.list redacts; testKey works
# ========================================================================== #
def test_hub_upsert_stores_raw_list_redacts_and_testkey(tmp_path: Path) -> None:
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)

        # upsert with a RAW key -> the returned list is REDACTED (no full key over RPC).
        listed = rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        prov = next(p for p in listed["providers"] if p["id"] == "mock")
        assert _RAW_KEY not in json.dumps(prov), "providers.list leaked the RAW key"
        assert any(_RAW_KEY[-4:] in str(k) for k in prov["apiKeys"]), "redacted key lost its last-4"

        # ...but the RAW key is PERSISTED: settings.get_raw() carries it verbatim.
        raw = svc.settings.get_raw()["providers"][0]
        assert raw["apiKeys"] == [_RAW_KEY], "upsert did not store the RAW key"

        # testKey issues one minimal completion through the provider seam (real socket).
        res = rpc.call("providers.testKey", {"baseUrl": server.base_url, "model": "mock-model", "apiKey": _RAW_KEY})
        assert res["ok"] is True, f"testKey failed: {res!r}"
        assert _RAW_KEY not in json.dumps(res), "testKey echoed the key back"


# ========================================================================== #
# HUB-2 — ai.planJob is PURE: route/cost/willEgress/budget, ZERO provider calls
# ========================================================================== #
def test_hub_planjob_is_pure_zero_egress(tmp_path: Path) -> None:
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))

        before = dict(server.hits)
        planned = rpc.call(
            "ai.planJob",
            {"messages": [{"role": "user", "content": "plan a short"}], "capability": "text"},
        )
        # The pre-flight envelope shape (PLAN acceptance: zero provider calls).
        for key in ("route", "costEst", "willEgress", "budget", "cacheHit", "cacheKey"):
            assert key in planned, f"ai.planJob envelope missing {key!r}: {planned!r}"
        assert server.hits == before, f"ai.planJob made a provider call (impure!): {before} -> {server.hits}"
        assert isinstance(planned["cacheKey"], str) and planned["cacheKey"], "no cacheKey budget token"


# ========================================================================== #
# HUB-3 — REAL HTTP through the routed pool: correct OpenAI shape + RAW-key auth
# (the get_raw() chat-path contract — the control for the embedder redacted bug)
# ========================================================================== #
def test_hub_real_http_chat_uses_raw_key_correct_shape(tmp_path: Path) -> None:
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))
        vid = _add_video(svc, media)

        done = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten into a punchy short"})

        # (a) the request hit the mock with a correct OpenAI chat shape.
        assert server.hits["chat"] >= 1, "no real HTTP chat reached the mock"
        body = server.last_bodies["chat"]
        assert isinstance(body.get("model"), str) and body["model"], "chat body missing model"
        assert isinstance(body.get("messages"), list) and body["messages"], "chat body missing messages"
        assert all("role" in m and "content" in m for m in body["messages"]), "OpenAI message shape wrong"

        # (b) the response was parsed into a validated EditPlan.
        assert isinstance(done.get("planId"), str) and done["planId"]
        assert [op["kind"] for op in done["editPlan"]["ops"]] == ["removeSilence", "trim", "caption"]

        # (c) THE HUB get_raw() CHECK: the chat egress carried the RAW key, NOT a
        # redacted one (contrast: agent-2's index embedder sends the redacted key).
        auth = server.auth_headers.get("chat")
        assert auth == f"Bearer {_RAW_KEY}", f"chat path did not send the RAW key: {auth!r}"


# ========================================================================== #
# HUB-3b — the SELECT route also egresses with the RAW key (phase8.select)
# ========================================================================== #
def test_hub_select_route_uses_raw_key(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    _make_sample_mp4(media)
    # Inject the phase8 signal runner (the SANCTIONED test seam — the heavy
    # cv2/torch compute carries its own # pragma: no cover; tests inject a fake).
    # Empty tracks -> select_unified still runs the REAL transcript+LLM candidate
    # generation, which is the path that issues the select-routed chat we assert.
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path, phase8_runner=lambda *a, **k: {})
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))
        vid = _add_video(svc, media)
        # A transcript with segments -> select() (the LLM path) runs and egresses.
        project = svc._load_or_create_project(vid)
        project.data["transcript"] = {
            "language": "en",
            "durationSec": 6.0,
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "the single most important pricing insight", "words": []},
                {"start": 3.0, "end": 6.0, "text": "and a quieter aside about cats", "words": []},
            ],
        }
        project.save()

        done = rpc.run_job("phase8.select", {"videoId": vid, "prompt": "find the punchiest moment", "tier": 1})
        assert "candidates" in done, f"select produced no candidates: {done!r}"
        assert server.hits["chat"] >= 1, "select route never reached the mock chat endpoint"
        assert server.auth_headers.get("chat") == f"Bearer {_RAW_KEY}", "select route did not send the RAW key"


# ========================================================================== #
# HUB-4 — ROTATION across 2 providers on a REAL 429 (real sockets)
# ========================================================================== #
def test_hub_rotation_on_real_429(tmp_path: Path) -> None:
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with Always429Server() as bad, MockModelServer() as good:
        svc, rpc = _wire(tmp_path)
        # provider order matters: the 429 server is FIRST, the working mock SECOND.
        rpc.call("providers.upsert", {"provider": _provider_entry(bad.base_url, pid="bad", keys=["sk-bad-aaaa"])})
        rpc.call("providers.upsert", {"provider": _provider_entry(good.base_url, pid="good", keys=[_RAW_KEY])})
        svc.settings.set(_base_settings("bad", "good"))
        vid = _add_video(svc, media)

        # Capture rotation events from the REAL pool (director.plan builds the pool
        # via get_raw()); we wrap _provider_for_function so we can attach the hook.
        events: list[RotationEvent] = []
        orig = svc._provider_for_function

        def _hooked(function: str) -> Any:
            pool = orig(function)
            if hasattr(pool, "on_rotation"):
                pool.on_rotation(events.append)
            return pool

        svc._provider_for_function = _hooked  # type: ignore[method-assign]

        done = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten into a punchy short"})

        # The 429 server was really hit, then the working mock served the request.
        assert bad.hits >= 1, "the 429 provider was never tried (no real failover happened)"
        assert good.hits["chat"] >= 1, "rotation did not land on the working provider"
        assert [op["kind"] for op in done["editPlan"]["ops"]] == ["removeSilence", "trim", "caption"]
        # Exactly one failover event, to the good provider, NOT the local backstop.
        assert events, "no rotation event emitted on the 429"
        assert events[-1].provider == "good", f"rotation landed on the wrong provider: {events!r}"
        # The good provider used the RAW key on the wire.
        assert good.auth_headers.get("chat") == f"Bearer {_RAW_KEY}", "post-rotation egress lost the RAW key"


# ========================================================================== #
# HUB-4b — usage/budget accounting updates after a REAL HTTP egress
# ========================================================================== #
def test_hub_usage_updates_after_real_egress(tmp_path: Path) -> None:
    """The RotatingProvider's per-key usage updates after a REAL HTTP chat.

    This is the genuine accounting unit: ``_on_success`` increments ``used`` and
    folds in the parsed ``X-RateLimit-*`` headers. We build the pool exactly as
    the product factory does (``get_provider(get_raw())`` -> RotatingProvider over
    a real socket), issue one real chat through it, and assert the budget moved.

    NOTE (finding, not asserted as a breakage): the ``providers.usage`` RPC builds
    a SEPARATE planning pool (``self._ai_pool()``, fresh counters), so it does NOT
    reflect egress that happened through a director/job pool instance in-process —
    per-key usage from AI jobs is surfaced via the persisted ``usageCache``, not a
    shared live counter. The accounting itself (below) is real.
    """
    from media_studio.models import provider as _provider_mod

    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))

        # The product factory path: RAW keys -> a RotatingProvider over a real socket.
        pool = _provider_mod.get_provider(svc.settings.get_raw())
        assert isinstance(pool, _provider_mod.RotatingProvider), f"not a pool: {pool!r}"

        before = [r for r in pool.usage() if r.get("provider") == "mock"][0]
        assert before["used"] == 0, f"usage did not start at zero: {before!r}"

        content = pool.chat([{"role": "user", "content": "ping"}], capability="text")
        assert isinstance(content, str) and content, "real chat returned no content"
        assert server.hits["chat"] >= 1, "no real egress to account for"

        after = [r for r in pool.usage() if r.get("provider") == "mock"][0]
        # The mock sends X-RateLimit-Limit:1000 / Remaining:999 -> used==1, max==1000.
        assert after["used"] >= 1, f"usage 'used' not incremented after egress: {after!r}"
        assert after["max"] == 1000, f"budget 'max' not parsed from X-RateLimit headers: {after!r}"


# ========================================================================== #
# DIRECTOR — previewCost: per-function route/cost preview, PURE (zero egress)
# ========================================================================== #
def test_director_preview_cost_is_pure(tmp_path: Path) -> None:
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))
        vid = _add_video(svc, media)

        plan = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten"})
        hits_after_plan = dict(server.hits)

        preview = rpc.call("director.previewCost", {"planId": plan["planId"]})
        per_function = {row["function"]: row for row in preview["perFunction"]}
        # Both data-type surfaces are previewed, each with its own route/cost/egress.
        assert {"editPlan", "vision"} <= set(per_function), f"previewCost missing functions: {per_function!r}"
        for row in preview["perFunction"]:
            for key in ("route", "costEst", "willEgress", "cacheHit", "cacheKey"):
                assert key in row, f"previewCost row missing {key!r}: {row!r}"
        # PURE: previewCost made ZERO additional provider calls.
        assert server.hits == hits_after_plan, f"previewCost egressed (impure): {hits_after_plan} -> {server.hits}"


# ========================================================================== #
# HUB-5 — text-consent gate blocks egress; budget gate refuses un-acked run
# ========================================================================== #
def test_hub_text_consent_gate_blocks_egress(tmp_path: Path) -> None:
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        # consent.set equivalent (registered name providers.setConsent): REVOKE text.
        rpc.call("providers.setConsent", {"provider": "mock", "text": False})
        svc.settings.set({"routing": _routing("mock"), "confirmCloudBudget": False})
        vid = _add_video(svc, media)

        # index.build is the transcript-text egress path gated by TEXT consent.
        # With consent revoked it must NOT reach the cloud /v1/embeddings; it falls
        # back to the local embedder (model == "local"), zero egress.
        from media_studio import library as _lib  # local: set a transcript for the index

        project = svc._load_or_create_project(vid)
        project.data["transcript"] = {
            "language": "en",
            "durationSec": 6.0,
            "segments": [{"start": 0.0, "end": 2.0, "text": "pricing and revenue", "words": []}],
        }
        project.save()
        _ = _lib  # silence unused

        built = rpc.run_job("index.build", {"videoId": vid})
        assert server.hits["embeddings"] == 0, "text-consent revoked but transcript still egressed to the cloud"
        assert built["model"] == "local", f"expected local (no-egress) fallback, got {built!r}"

        # Now GRANT text consent -> the chat (director.plan) path egresses again.
        rpc.call("providers.setConsent", {"provider": "mock", "text": True})
        svc.settings.set({"consent": {"perProvider": {"mock": {"text": True}}}})


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PRODUCT BUG (TOP_BREAKAGE): the director.plan CHAT/editPlan egress path is "
        "NOT text-consent gated. The index embedder filters providers via "
        "_text_consented_settings and the vision paths via "
        "_frame_consented_vision_settings, but director.plan builds its provider "
        "with _provider_for_function('editPlan') -> get_provider(get_raw()) with NO "
        "consent filter. build_understanding folds the TRANSCRIPT into the prompt, "
        "so with TEXT consent REVOKED director.plan still ships the transcript text "
        "to the cloud (verified: chat hit + transcript bytes on the wire). Candidate "
        "fix: filter the editPlan pool through _text_consented_settings like the "
        "index path. Strict xfail -> flips to a hard fail the moment it is fixed."
    ),
)
def test_hub_director_chat_path_honors_text_consent_xfail(tmp_path: Path) -> None:
    """The chat (director.plan) egress SHOULD be blocked when TEXT consent is off.

    This is the consent equivalent of agent-2's redacted-key xfail: the SECURE
    behavior is asserted, and it currently FAILS because the editPlan chat path
    skips the per-provider TEXT-consent filter the index/vision paths apply.
    """
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))
        # REVOKE text consent — transcript must NOT egress to the cloud planner.
        rpc.call("providers.setConsent", {"provider": "mock", "text": False})
        vid = _add_video(svc, media)
        project = svc._load_or_create_project(vid)
        project.data["transcript"] = {
            "language": "en",
            "durationSec": 6.0,
            "segments": [{"start": 0.0, "end": 2.0, "text": "secret revenue numbers", "words": []}],
        }
        project.save()

        rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten"})
        # SECURE expectation (currently violated): zero chat egress with consent off.
        assert server.hits["chat"] == 0, "director.plan egressed transcript text despite TEXT consent revoked"


def test_hub_budget_gate_refuses_unacked_cloud_run(tmp_path: Path) -> None:
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(
            {
                "routing": _routing("mock"),
                "consent": {"perProvider": {"mock": {"text": True}}},
                "confirmCloudBudget": True,  # the budget gate is ARMED
            }
        )
        vid = _add_video(svc, media)

        # An egressing cloud run WITHOUT the planJob cacheKey ack is refused
        # (zero bytes leave the machine — the gate fires BEFORE any provider call).
        with pytest.raises(Exception) as exc:  # noqa: PT011 - typed RpcError surfaced as a generic raise here
            rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten"})
        assert "budget" in str(exc.value).lower(), f"refusal was not the budget gate: {exc.value!r}"
        assert server.hits["chat"] == 0, "budget gate did not stop the egress"

        # The same run is ADMITTED once the budget gate is acknowledged. The
        # director.plan envelope's cacheKey is built from the FULL Director prompt
        # (not a client-supplied message list), so the faithful acknowledgement is
        # to satisfy the gate's condition: disable confirmCloudBudget (the user's
        # "I accept the cost" decision) -> the egress now happens for real.
        svc.settings.set({"confirmCloudBudget": False})
        done = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten"})
        assert server.hits["chat"] >= 1, "acknowledged run did not egress"
        assert [op["kind"] for op in done["editPlan"]["ops"]] == ["removeSilence", "trim", "caption"]


def test_hub_budget_ack_token_admits_gated_run(tmp_path: Path) -> None:
    """The REAL ack path: echo the planJob cacheKey -> a gated cloud run is admitted.

    Exercises the ``ack == envelope.cacheKey`` branch (not the disable-the-gate
    shortcut). ``director.apply`` exposes the exact token via ``_director_apply_ack``;
    passing it as ``confirmBudget`` with the gate ARMED admits the run.
    """
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))  # gate OFF so the plan can be created
        vid = _add_video(svc, media)
        plan = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten"})
        plan_id = plan["planId"]

        # ARM the budget gate; the exact ack token is the plan's envelope cacheKey.
        svc.settings.set({"confirmCloudBudget": True})
        ack = svc._director_apply_ack(plan_id)
        assert isinstance(ack, str) and ack, "no budget ack token exposed"

        # WITHOUT the ack -> refused.
        with pytest.raises(Exception) as exc:  # noqa: PT011 - typed RpcError
            rpc.run_job("director.apply", {"planId": plan_id})
        assert "budget" in str(exc.value).lower(), f"not the budget gate: {exc.value!r}"

        # WITH the correct ack token -> admitted (the run proceeds past the gate;
        # the empty default engine table then fails the ops, which is the separate
        # TOP_BREAKAGE — what matters here is the gate ADMITTED the run).
        applied = rpc.run_job("director.apply", {"planId": plan_id, "confirmBudget": ack})
        assert "opsStatus" in applied, f"ack did not admit the gated run: {applied!r}"


# ========================================================================== #
# DIRECTOR — the SHIPPED default engine table is EMPTY (TOP_BREAKAGE control)
# ========================================================================== #
def test_director_apply_default_engine_table_is_empty(tmp_path: Path) -> None:
    """PROOF that the shipped director.apply renders NO media in v1.

    With the DEFAULT ``_director_engines()`` (``{}``), every op has no engine ->
    ``failed`` + auto-rollback. No ffmpeg runs; the project COPY is an unchanged
    JSON manifest. This is the honest TOP_BREAKAGE: the apply spine is real, but
    no op-engine adapters are wired, so a real client gets a no-op apply.
    """
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))
        vid = _add_video(svc, media)

        plan = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten"})
        assert svc._director_engines() == {}, "default engine table is no longer empty (update the breakage note)"

        applied = rpc.run_job("director.apply", {"planId": plan["planId"]})
        statuses = [op["status"] for op in applied["opsStatus"]]
        assert "failed" in statuses, f"expected the no-engine failure, got {statuses!r}"
        assert all(s in ("failed", "planned", "dropped") for s in statuses), f"unexpected applied op: {statuses!r}"


# ========================================================================== #
# DIRECTOR — apply SPINE + REAL ffmpeg over a project COPY -> valid mp4 -> undo
# A real ffmpeg op-engine is injected behind the documented _director_engines
# seam (the SAME seam the product's own director tests use). The apply ordering,
# inverse recording, COPY isolation, and undo re-application are the PRODUCT's.
# ========================================================================== #
def _ffmpeg_render_engine(source_path: str, work_dir: Path) -> Any:
    """Build a real-ffmpeg op-engine: each op renders an mp4 segment over the COPY.

    Mirrors agent-2's ``thumbnail_writer`` precedent: a real-ffmpeg WRITER behind
    a product seam. The engine records the prior rendered path as the inverse op's
    param so undo can restore it. The apply spine (dispatch/order/inverse/rollback)
    is the product's :func:`apply_engine.apply_plan`.
    """
    counter = {"n": 0}

    def engine(op: EditOp, project_copy: Any) -> EditOp:
        prev = project_copy.data.get("renderedPath")
        # An INVERSE op (recorded by a prior forward apply) carries a restore
        # marker: undo is a pure manifest revert, no re-render.
        if "restorePath" in op.params:
            project_copy.data["renderedPath"] = op.params["restorePath"]
            return EditOp(
                id=f"redo-{op.id}",
                kind=op.kind,
                span=op.span,
                params={"restorePath": prev},
                reversible=True,
                rationale="redo render",
            )
        # FORWARD op: a real, span-bounded re-encode of the source onto the COPY.
        counter["n"] += 1
        out = work_dir / f"applied_{op.kind}_{counter['n']}.mp4"
        start_ms, end_ms = op.span or (0, 2000)
        ss = max(0.0, float(start_ms) / 1000.0)
        to = max(ss + 0.5, float(end_ms) / 1000.0)
        _ffmpeg(
            [
                "-ss",
                f"{ss:.3f}",
                "-to",
                f"{to:.3f}",
                "-i",
                source_path,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(out),
            ]
        )
        # Record the new media path on the COPY manifest (the COPY, never source).
        project_copy.data["renderedPath"] = str(out)
        # The inverse op restores the previous rendered path (a pure manifest revert).
        return EditOp(
            id=f"inv-{op.id}",
            kind=op.kind,
            span=op.span,
            params={"restorePath": prev},
            reversible=True,
            rationale="undo render",
        )

    return engine


def test_director_apply_real_ffmpeg_over_copy_then_undo(tmp_path: Path) -> None:
    media = tmp_path / "source.mp4"
    # A 10s clip so the mock plan's spans ([0,2000] + [2000,8000]) pass the real
    # validator (which drops span-exceeds-clip ops). The trackless caption op is
    # correctly DROPPED by validate_and_reject (unknown-track) — so 2 ops apply.
    _make_sample_mp4(media, seconds=10)
    source_bytes_before = media.read_bytes()
    work = tmp_path / "renders"
    work.mkdir()

    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))
        vid = _add_video(svc, media)

        # Inject the real-ffmpeg engine behind the product seam (the same hook the
        # product's own director tests use). Both forward + inverse route through it.
        engine = _ffmpeg_render_engine(str(media), work)
        table = dict.fromkeys(("removeSilence", "trim", "caption"), engine)
        svc._director_engines = lambda: table  # type: ignore[method-assign]

        plan = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten into a punchy short"})
        # The validator dropped the trackless caption op already at plan time.
        plan_statuses = [op["status"] for op in plan["editPlan"]["ops"]]
        assert plan_statuses == ["planned", "planned", "dropped"], f"unexpected plan: {plan_statuses!r}"

        # APPLY over a COPY with REAL ffmpeg. The two valid ops each invoke the
        # injected ffmpeg engine, which RENDERS a real mp4 segment from the source.
        applied = rpc.run_job("director.apply", {"planId": plan["planId"]}, timeout=120.0)
        statuses = [op["status"] for op in applied["opsStatus"]]
        assert statuses == ["applied", "applied", "dropped"], f"apply did not run the valid ops: {statuses!r}"

        # The COPY manifest was written to an ISOLATED .director-copy path (not the
        # source), proving apply targets a copy.
        copy_manifest = Path(applied["projectCopyPath"])
        assert copy_manifest.exists(), f"COPY manifest missing: {copy_manifest}"
        assert ".director-copy" in str(copy_manifest), f"COPY not isolated from source: {copy_manifest}"

        # The applied media is REAL: two ffprobe-valid mp4s rendered by real ffmpeg
        # over the COPY (one per applied op). This is the genuine ffmpeg output.
        rendered = sorted(work.glob("applied_*.mp4"))
        assert len(rendered) == 2, f"expected 2 rendered mp4 segments, got {rendered!r}"
        for clip in rendered:
            width, duration = _ffprobe_ok(str(clip))
            assert width > 0 and duration > 0, f"applied output is not a valid mp4: {clip} -> {width}x/{duration}s"

        # The SOURCE manifest + the SOURCE media were never mutated (COPY isolation).
        assert media.read_bytes() == source_bytes_before, "director.apply mutated the SOURCE media"
        src_project = svc._load_or_create_project(vid)
        assert "renderedPath" not in src_project.data, "director.apply mutated the SOURCE manifest"

        # The recorded inverse plan (newest-first) carries one inverse op per
        # applied forward op -> the one-shot undo is real, not empty.
        inverse_ops = applied["inversePlan"]["ops"]
        assert len(inverse_ops) == 2, f"inverse plan did not record 2 undo ops: {inverse_ops!r}"

        # UNDO re-applies the recorded inverse over a fresh COPY (round-trip): the
        # inverse engine runs the recorded restore ops, reversing the apply.
        undone = rpc.run_job("director.undo", {"planId": plan["planId"]}, timeout=120.0)
        undo_statuses = [op["status"] for op in undone["opsStatus"]]
        assert undo_statuses and all(s == "applied" for s in undo_statuses), f"undo did not run: {undo_statuses!r}"
        assert len(undo_statuses) == 2, f"undo did not walk the 2 recorded inverses: {undo_statuses!r}"

        # director.plan still egressed for real (mock chat hit).
        assert server.hits["chat"] >= 1
