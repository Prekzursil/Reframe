"""WU-D2b-2 CONSUME + NO-PERSIST end-to-end: the per-request key injection overlay.

These lock the composition-root wiring that turns main's injected `_injectedKeys`
into a request-scoped `SettingsStore.key_overlay` while guaranteeing the RAW key
never lands on disk, in a log line, or in the persisted job store:

  * the wrapper POPS `_injectedKeys` off the params IN PLACE (so `dispatch`'s
    `record_request` / `rpc.py`'s error logger — which read the SAME object — see
    a clean frame) and runs the handler under the overlay so `get_raw()` returns
    the live key for THAT request only;
  * a request WITHOUT the field is an ordinary call (no overlay opened);
  * the HEADLINE invariant: a providers.upsert round-trip leaves ZERO plaintext
    key bytes in settings.json or any sibling on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.handlers import Services, register_all
from media_studio.handlers.composition import _key_overlay_wrapper
from media_studio.protocol import ParsedRequest, RpcContext, dispatch

_RAW = "sk-inject-SECRET-ABCDWXYZ"
_RAW_2 = "sk-inject-SECRET-second-7890"


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda _obj: None, jobs=None)


@pytest.fixture
def wired(tmp_path: Path) -> Services:
    """A Services whose §2 handlers are registered through the WRAPPED registry."""
    protocol.clear_methods()
    svc = register_all(Services(data_dir=tmp_path))
    yield svc
    protocol.clear_methods()


def _seed_provider(svc: Services) -> None:
    # Persist a provider whose apiKeys are stripped to markers at rest.
    svc.settings.set({"providers": [{"id": "groq", "provider": "Groq", "apiKeys": [_RAW]}]})


# --------------------------------------------------------------------------- #
# CONSUME: the wrapper opens the overlay so get_raw() sees the injected RAW key
# --------------------------------------------------------------------------- #
def test_wrapper_applies_overlay_so_handler_sees_raw_key(wired: Services) -> None:
    _seed_provider(wired)
    # At rest the store holds only the marker.
    assert wired.settings.get_raw()["providers"][0]["apiKeys"] == ["…WXYZ"]
    # revealKey reads get_raw(); driven through the WRAPPED registry with an
    # injected key it resolves the LIVE key (proving the overlay was opened).
    handler = protocol.METHODS["providers.revealKey"]
    out = handler({"id": "groq", "_injectedKeys": {"providers": {"groq": [_RAW]}}}, _ctx())
    assert out == {"key": _RAW}
    # ...and the overlay is closed again after the call (no lingering keys).
    assert wired.settings.get_raw()["providers"][0]["apiKeys"] == ["…WXYZ"]


def test_wrapper_strips_injected_keys_from_params_in_place(wired: Services) -> None:
    _seed_provider(wired)
    params: dict[str, Any] = {"id": "groq", "_injectedKeys": {"providers": {"groq": [_RAW]}}}
    protocol.METHODS["providers.revealKey"](params, _ctx())
    # The SAME dict `dispatch` would record / log has the key bundle removed.
    assert "_injectedKeys" not in params


def test_wrapper_passthrough_without_injected_keys(wired: Services) -> None:
    _seed_provider(wired)
    # No `_injectedKeys` -> no overlay -> the at-rest marker is what reveal sees,
    # i.e. the ordinary (non-key-bearing) call path is unchanged.
    out = protocol.METHODS["providers.revealKey"]({"id": "groq"}, _ctx())
    assert out == {"key": "…WXYZ"}


def test_wrapper_tolerates_non_dict_params() -> None:
    # A non-dict params (defensive) never crashes the wrapper's pop guard.
    svc = Services()
    calls: list[Any] = []

    def handler(params: Any, ctx: RpcContext) -> str:
        calls.append(params)
        return "ok"

    wrapped = _key_overlay_wrapper(svc, handler)
    assert wrapped("not-a-dict", _ctx()) == "ok"  # type: ignore[arg-type]
    assert calls == ["not-a-dict"]


# --------------------------------------------------------------------------- #
# NO-LEAK: dispatch never records/logs the injected keys (reference-pop proof)
# --------------------------------------------------------------------------- #
def test_dispatch_leaves_no_injected_keys_on_the_request(wired: Services) -> None:
    _seed_provider(wired)
    req = ParsedRequest(
        id=1,
        method="providers.revealKey",
        params={"id": "groq", "_injectedKeys": {"providers": {"groq": [_RAW]}}},
        is_notification=False,
    )
    out = dispatch(req, _ctx())
    assert out == {"key": _RAW}  # the overlay reached the handler
    # The request object dispatch would hand to record_request / the error logger
    # no longer carries the key bundle — no raw key can reach the job store.
    assert "_injectedKeys" not in req.params
    assert _RAW not in json.dumps(req.params)


# --------------------------------------------------------------------------- #
# HEADLINE: a providers.upsert round-trip leaves ZERO plaintext key on disk
# --------------------------------------------------------------------------- #
def test_upsert_round_trip_leaves_zero_plaintext_key_bytes_on_disk(wired: Services, tmp_path: Path) -> None:
    upsert = protocol.METHODS["providers.upsert"]
    # A raw key handed straight to upsert (the non-main path) is still stripped at
    # rest — defense-in-depth: the invariant holds regardless of the caller.
    upsert({"id": "groq", "provider": "Groq", "apiKeys": [_RAW, _RAW_2]}, _ctx())
    upsert({"provider": {"id": "openai", "apiKeys": [_RAW]}}, _ctx())

    config = Path(wired.settings.config_path)
    # Scan settings.json AND every sibling the atomic write may have left behind.
    for candidate in config.parent.iterdir():
        if candidate.is_file():
            blob = candidate.read_bytes()
            for raw in (_RAW, _RAW_2):
                assert raw.encode("utf-8") not in blob, f"plaintext key leaked into {candidate.name}"

    # The persisted document holds only last-4 markers; the live keys are gone.
    on_disk = json.loads(config.read_text(encoding="utf-8"))
    assert on_disk["providers"][0]["apiKeys"] == ["…WXYZ", "…7890"]
    assert on_disk["providers"][1]["apiKeys"] == ["…WXYZ"]

    # The keys remain usable ONLY via the request-scoped injection overlay.
    with wired.settings.key_overlay({"providers": {"groq": [_RAW, _RAW_2], "openai": [_RAW]}}):
        raw = wired.settings.get_raw()["providers"]
        assert raw[0]["apiKeys"] == [_RAW, _RAW_2]
        assert raw[1]["apiKeys"] == [_RAW]
