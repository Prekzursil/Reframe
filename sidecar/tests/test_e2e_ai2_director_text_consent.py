"""E2E: ``director.plan`` chat egress honors per-provider TEXT consent (FIX #6).

Ported from the strict-xfail proof on ``chore/e2e-ai2``
(``test_hub_director_chat_path_honors_text_consent_xfail``). That xfail documented
a PRIVACY leak: ``director.plan`` built its editPlan provider via
``_provider_for_function("editPlan") -> get_provider(get_raw())`` with NO consent
filter, while ``build_understanding`` folds the TRANSCRIPT into the planner prompt
-- so with TEXT consent REVOKED the transcript still shipped to the cloud.

These are INTEGRATION tests over the REAL stack: real JSON-RPC dispatch, the real
``director.*`` handlers, the real consent/budget gates, and the REAL
:class:`RotatingProvider` HTTP code. The ONLY fake is the model endpoint -- a
local OpenAI-compatible :class:`MockModelServer` the provider reaches over a real
socket with no cloud key, COUNTING every chat hit so egress can be PROVEN.

The SECURE behavior (what the editPlan path now does, mirroring the index
embedder's ``_text_consented_settings`` gate and the vision
``_frame_consented_vision_settings`` gate):

  * REVOKED text consent -> ``director.plan`` REFUSES before any chat: zero bytes
    leave the machine (the chat hit counter stays 0). Chat has no in-process local
    backstop (unlike the embedder's ``LocalEmbedder``), so the gate's no-egress
    outcome is a clear refusal, not a silent local completion.
  * GRANTED text consent -> ``director.plan`` egresses for real with the RAW key.

Run: ``python -m pytest sidecar/tests/test_e2e_ai2_director_text_consent.py``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio import library as _library
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext

from tests.e2e_ai2_mock_model import MockModelServer

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(
    not (_FFMPEG and _FFPROBE),
    reason="ffmpeg/ffprobe required for the E2E director TEXT-consent real-media flow",
)

_RAW_KEY = "sk-e2e-director-consent-rawkey-9999"


# --------------------------------------------------------------------------- #
# in-process JSON-RPC drive (mirrors the sibling E2E-AI2 suite)
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
# real-media fixture (real ffmpeg)
# --------------------------------------------------------------------------- #
def _make_sample_mp4(path: Path, *, seconds: int = 6) -> None:
    """A real 16:9 1280x720 mp4: moving testsrc + a tone (ffprobe-valid)."""
    res = subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-loglevel",
            "error",
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
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"ffmpeg failed: {res.stderr}"


# --------------------------------------------------------------------------- #
# settings + project helpers
# --------------------------------------------------------------------------- #
def _provider_entry(base_url: str, *, pid: str = "mock") -> dict[str, Any]:
    return {
        "id": pid,
        "provider": pid,  # provider NAME == id so the consent perProvider keys line up
        "kind": "cloud",
        "baseUrl": base_url,
        "model": "mock-model",
        "apiKeys": [_RAW_KEY],
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


def _base_settings(*provider_ids: str, text: bool = True) -> dict[str, Any]:
    """Routed settings with the (default-ON) budget gate OFF; text consent per ``text``.

    The shipped default ``confirmCloudBudget`` is True, so a non-budget test must
    turn it OFF or every egress is refused. The egress decision under test here is
    the TEXT-consent gate, not the budget gate.
    """
    consent = {pid: {"text": text, "frames": True} for pid in provider_ids}
    return {
        "routing": _routing(*provider_ids),
        "consent": {"perProvider": consent},
        "confirmCloudBudget": False,
        "cloudModel": "mock-model",
    }


def _wire(tmp: Path) -> tuple[Services, Rpc]:
    svc = Services(data_dir=tmp / "data")
    protocol.clear_methods()
    handlers.register_all(services=svc)
    return svc, Rpc(svc)


def _add_video(svc: Services, media: Path) -> str:
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 6.0)
    return svc.library.add(str(media))["id"]


def _set_transcript(svc: Services, vid: str) -> None:
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = {
        "language": "en",
        "durationSec": 6.0,
        "segments": [{"start": 0.0, "end": 2.0, "text": "secret revenue numbers", "words": []}],
    }
    project.save()


# ========================================================================== #
# FIX #6 — director.plan chat egress is TEXT-consent gated (was leaking)
# ========================================================================== #
def test_director_plan_refuses_when_text_consent_revoked(tmp_path: Path) -> None:
    """REVOKED text consent -> director.plan ships ZERO transcript bytes to the cloud.

    The secure equivalent of the ``chore/e2e-ai2`` strict xfail: with TEXT consent
    off, the editPlan chat path is refused BEFORE any egress, so the mock chat
    endpoint is never reached.
    """
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock"))
        # REVOKE text consent -- transcript must NOT egress to the cloud planner.
        rpc.call("providers.setConsent", {"provider": "mock", "text": False})
        vid = _add_video(svc, media)
        _set_transcript(svc, vid)

        # SECURE expectation: the gate fires synchronously, refusing the run.
        with pytest.raises(Exception) as exc:  # noqa: PT011 - typed RpcError surfaced as a generic raise
            rpc.call("director.plan", {"videoId": vid, "goal": "tighten"})
        assert "consent" in str(exc.value).lower(), f"refusal was not the text-consent gate: {exc.value!r}"
        assert server.hits["chat"] == 0, "director.plan egressed transcript text despite TEXT consent revoked"


def test_director_plan_never_egresses_to_a_non_consented_provider_in_a_mixed_pool(tmp_path: Path) -> None:
    """Per-entry gate: a NON-consented cloud entry is never the egress target.

    The mixed-consent rotation hole: two cloud providers, TEXT consent granted to
    ONLY one, and the editPlan route deliberately PREFERS the NON-consented one. A
    boolean all-or-nothing check would pass (one entry is consented) yet still
    egress the transcript to the non-consented primary (or fail over to it on a
    429). The SECURE behavior drops the non-consented entry BEFORE the pool is
    built, so the transcript can only ever reach the consented provider.
    """
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as no_srv, MockModelServer() as yes_srv:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(no_srv.base_url, pid="no")})
        rpc.call("providers.upsert", {"provider": _provider_entry(yes_srv.base_url, pid="yes")})
        # Consent: ONLY "yes" may receive text; routing PREFERS the non-consented "no".
        svc.settings.set(
            {
                "routing": _routing("no", "yes"),
                "consent": {"perProvider": {"yes": {"text": True}, "no": {"text": False}}},
                "confirmCloudBudget": False,
                "cloudModel": "mock-model",
            }
        )
        vid = _add_video(svc, media)
        _set_transcript(svc, vid)

        done = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten"})

        assert no_srv.hits["chat"] == 0, (
            "transcript egressed to the NON-consented provider despite revoked text consent"
        )
        assert yes_srv.hits["chat"] >= 1, "the consented provider was never reached"
        assert [op["kind"] for op in done["editPlan"]["ops"]] == ["removeSilence", "trim", "caption"]
        assert yes_srv.auth_headers.get("chat") == f"Bearer {_RAW_KEY}", "consented egress did not send the RAW key"


def test_director_plan_egresses_when_text_consent_granted(tmp_path: Path) -> None:
    """GRANTED text consent -> the editPlan chat path egresses for real with the RAW key.

    The consented-path control: the fix must NOT block a user who DID opt in. The
    chat reaches the mock and the response is parsed into a validated EditPlan; the
    egress carries the RAW key (the get_raw() factory contract).
    """
    media = tmp_path / "talk.mp4"
    _make_sample_mp4(media)
    with MockModelServer() as server:
        svc, rpc = _wire(tmp_path)
        rpc.call("providers.upsert", {"provider": _provider_entry(server.base_url)})
        svc.settings.set(_base_settings("mock", text=True))
        vid = _add_video(svc, media)
        _set_transcript(svc, vid)

        done = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten into a punchy short"})

        assert server.hits["chat"] >= 1, "consent granted but the chat never reached the mock"
        assert isinstance(done.get("planId"), str) and done["planId"]
        assert [op["kind"] for op in done["editPlan"]["ops"]] == ["removeSilence", "trim", "caption"]
        assert server.auth_headers.get("chat") == f"Bearer {_RAW_KEY}", "consented egress did not send the RAW key"
