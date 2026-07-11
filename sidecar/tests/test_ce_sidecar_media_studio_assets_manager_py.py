"""Cross-edit tests for ``AssetManager._install_env`` get-pip.py cache re-verify.

Isolated companion to ``test_assets.py`` (which is a consolidated module test we
do not own here). Covers the F3c defense-in-depth re-verification added to
``_install_env``: a cached ``<root>/tools/get-pip.py`` is EXECUTED on the next env
install, so its bytes are re-hashed against the pinned sha256 and a poisoned copy
is dropped + refetched (verify-before-exec) instead of run.

All three branches of the new ``if get_pip.is_file() and sha(...) != pinned:``
guard are exercised so media_studio's 100% branch gate holds:
  * cached bytes MATCH  -> keep the cache, no refetch (is_file True, hash equal);
  * cached bytes DIFFER -> unlink + refetch (is_file True, hash not equal);
  * no cache present     -> straight to fetch (is_file False, short-circuit).

Every heavy seam (httpx client, subprocess run_cmd, disk usage) is faked; no
real network, no real pip.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from media_studio.assets import manifest
from media_studio.assets.manager import GET_PIP_URL, AssetManager


@pytest.fixture(autouse=True)
def _restore_manifest():
    """Snapshot/restore the asset registry around each test (day-1 preserved)."""
    saved = manifest.registry_snapshot()
    try:
        yield
    finally:
        manifest.registry_restore(saved)


class FakeResponse:
    """An httpx-stream-shaped response (context manager + iter_bytes)."""

    def __init__(self, status_code=200, headers=None, chunks=(b"",)):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._chunks = list(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=None):
        yield from self._chunks


class FakeClient:
    """An httpx.Client-shaped fake: records requests, serves scripted responses."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, method, url, headers=None):
        self.requests.append({"method": method, "url": url, "headers": dict(headers or {})})
        if not self._responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        return self._responses.pop(0)


def _big_free_usage(_path: str) -> SimpleNamespace:
    return SimpleNamespace(total=10**13, used=0, free=10**13)


def _env_entry(name: str) -> manifest.AssetEntry:
    return manifest.register_asset(
        name=name,
        kind="env",
        size_mb=300,
        dest=f"envs/{name}",
        installer="env",
        requirements=("kokoro-onnx==0.4.9",),
    )


def _pip_response(body: bytes) -> FakeResponse:
    return FakeResponse(200, {"Content-Length": str(len(body))}, chunks=[body])


def test_install_env_keeps_cached_get_pip_when_hash_matches(tmp_path):
    """is_file True + hash EQUAL -> the cached script is trusted, never refetched."""
    body = b"# trusted get-pip"
    good_sha = hashlib.sha256(body).hexdigest()
    (tmp_path / "tools").mkdir(parents=True)
    (tmp_path / "tools" / "get-pip.py").write_bytes(body)

    calls: list[list[str]] = []

    def run_cmd(argv, extra_env=None):
        calls.append(list(argv))
        return 0, "ok"

    mgr = AssetManager(
        root=tmp_path,
        http_factory=lambda: FakeClient([]),  # scripted-empty: any fetch fails loudly
        run_cmd=run_cmd,
        usage=_big_free_usage,
        env_vars={},
        get_pip_sha256=good_sha,
    )
    entry = _env_entry("cache-hit-env")
    mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

    # Cache untouched (same bytes) and the two env steps ran without a refetch.
    assert (tmp_path / "tools" / "get-pip.py").read_bytes() == body
    assert len(calls) == 2


def test_install_env_refetches_cached_get_pip_when_hash_mismatches(tmp_path):
    """is_file True + hash NOT equal -> the poisoned cache is dropped and refetched."""
    good_body = b"# clean get-pip"
    good_sha = hashlib.sha256(good_body).hexdigest()
    (tmp_path / "tools").mkdir(parents=True)
    (tmp_path / "tools" / "get-pip.py").write_bytes(b"# tampered get-pip")  # wrong bytes

    client = FakeClient([_pip_response(good_body)])
    calls: list[list[str]] = []

    def run_cmd(argv, extra_env=None):
        calls.append(list(argv))
        return 0, "ok"

    mgr = AssetManager(
        root=tmp_path,
        http_factory=lambda: client,
        run_cmd=run_cmd,
        usage=_big_free_usage,
        env_vars={},
        get_pip_sha256=good_sha,
    )
    entry = _env_entry("cache-poison-env")
    mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

    # The tampered copy was replaced by the sha-verified refetch, then steps ran.
    assert client.requests and client.requests[0]["url"] == GET_PIP_URL
    assert (tmp_path / "tools" / "get-pip.py").read_bytes() == good_body
    assert len(calls) == 2


def test_install_env_fetches_get_pip_when_absent(tmp_path):
    """is_file False -> the guard short-circuits and the download path fetches it."""
    body = b"# fresh get-pip"
    good_sha = hashlib.sha256(body).hexdigest()
    client = FakeClient([_pip_response(body)])
    calls: list[list[str]] = []

    def run_cmd(argv, extra_env=None):
        calls.append(list(argv))
        return 0, "ok"

    mgr = AssetManager(
        root=tmp_path,
        http_factory=lambda: client,
        run_cmd=run_cmd,
        usage=_big_free_usage,
        env_vars={},
        get_pip_sha256=good_sha,
    )
    entry = _env_entry("cache-absent-env")
    mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

    assert client.requests and client.requests[0]["url"] == GET_PIP_URL
    assert (tmp_path / "tools" / "get-pip.py").read_bytes() == body
    assert len(calls) == 2
