"""WU-B2 engine wiring: the injected llama-backstop ensure() callback.

The composition root (``Services``) owns the shared :class:`ModelRunner`, so it
builds the opaque ``ensure()`` callback the provider / translator seams invoke
for the ``local`` backstop slot. This module pins:

  * :meth:`Services._llama_ensure` — starts the server via the shared runner
    (reuse-aware, LaneLock-cooperative) then runs the bounded readiness probe;
    a start failure OR a probe timeout surfaces as a :class:`ProviderError`
    (loud, never a hang, no silent fallback);
  * the four local chat paths (select, subtitles, edit-plan) thread that
    callback into ``get_provider`` / ``get_translator`` so the llama.cpp server
    auto-starts before the first local call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.handlers import ai_ops
from media_studio.handlers._services import Services
from media_studio.models import provider as prov
from media_studio.models import translation as translation_mod


class FakeRunner:
    """A ModelRunner stand-in: records start_server, reports server_running."""

    def __init__(self, *, server_running: bool = True, start_error: Exception | None = None) -> None:
        self.started = False
        self._server_running = server_running
        self._start_error = start_error

    def start_server(self, **_kwargs: Any) -> Any:
        self.started = True
        if self._start_error is not None:
            raise self._start_error
        return object()

    @property
    def server_running(self) -> bool:
        return self._server_running


def _svc(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "d")


# --------------------------------------------------------------------------- #
# _sleep seam
# --------------------------------------------------------------------------- #
def test_sleep_delegates_to_time_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: calls.append(s))
    ai_ops._sleep(0.0)
    assert calls == [0.0]


# --------------------------------------------------------------------------- #
# _llama_ensure
# --------------------------------------------------------------------------- #
def test_llama_ensure_starts_server_then_probes_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    runner = FakeRunner(server_running=True)
    svc._model_runner = runner
    # A 200 health GET -> the readiness probe returns on the first poll (no sleep,
    # no socket): the whole ensure() completes without raising.
    monkeypatch.setattr(prov, "urllib_get_json", lambda url, body, headers, timeout: {"status": "ok"})
    ensure = svc._llama_ensure()
    ensure()
    assert runner.started is True


def test_llama_ensure_reraises_provider_error_from_start(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    svc._model_runner = FakeRunner(start_error=prov.ProviderError("boom-from-start"))
    with pytest.raises(prov.ProviderError, match="boom-from-start"):
        svc._llama_ensure()()


def test_llama_ensure_wraps_other_start_failure_as_provider_error(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    # e.g. runner.start_server raising ValueError("no GGUF configured").
    svc._model_runner = FakeRunner(start_error=ValueError("no GGUF configured"))
    with pytest.raises(prov.ProviderError, match="failed to start"):
        svc._llama_ensure()()


def test_llama_ensure_probe_timeout_raises_provider_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    # server never came up (start ok, but child not running + refused GET) -> the
    # probe fails fast on child-exit rather than hanging.
    svc._model_runner = FakeRunner(server_running=False)
    monkeypatch.setattr(
        prov,
        "urllib_get_json",
        lambda *a, **k: (_ for _ in ()).throw(prov.ProviderError("refused")),
    )
    with pytest.raises(prov.ProviderError, match="exited before becoming ready"):
        svc._llama_ensure()()


# --------------------------------------------------------------------------- #
# wiring: the ensure callback is threaded into the local chat paths
# --------------------------------------------------------------------------- #
def _capture_get_provider(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _rec(settings: Any, *, prefer: Any = None, ensure: Any = None, transport: Any = None) -> Any:
        captured["ensure"] = ensure
        captured["prefer"] = prefer
        return "PROVIDER"

    monkeypatch.setattr(prov, "get_provider", _rec)
    return captured


def test_provider_for_function_injects_ensure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    svc._model_runner = FakeRunner()
    captured = _capture_get_provider(monkeypatch)
    assert svc._provider_for_function("select") == "PROVIDER"
    assert callable(captured["ensure"])


def test_select_provider_or_local_offline_injects_ensure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    svc._model_runner = FakeRunner()
    svc.settings.set({"offline": True})
    captured = _capture_get_provider(monkeypatch)
    assert svc._select_provider_or_local() == "PROVIDER"
    assert captured["prefer"] == prov.LOCAL_PROVIDER_ID
    assert callable(captured["ensure"])


def test_editplan_provider_injects_ensure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    svc._model_runner = FakeRunner()
    captured = _capture_get_provider(monkeypatch)
    # No cloud providers -> no consent refusal / no offline egress gate: a local
    # route that carries the ensure callback.
    assert svc._editplan_provider_or_refuse() == "PROVIDER"
    assert callable(captured["ensure"])


def test_translator_for_function_injects_ensure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(tmp_path)
    svc._model_runner = FakeRunner()
    captured: dict[str, Any] = {}

    def _rec(settings: Any, *, runner: Any = None, prefer: Any = None, ensure: Any = None, **_k: Any) -> Any:
        captured["ensure"] = ensure
        return "TRANSLATOR"

    monkeypatch.setattr(translation_mod, "get_translator", _rec)
    assert svc._translator_for_function("translation") == "TRANSLATOR"
    assert callable(captured["ensure"])
