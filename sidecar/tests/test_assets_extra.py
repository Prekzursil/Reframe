"""Extra coverage for media_studio.assets.manager + manifest — the
case-insensitive header fallback, the disk-preflight filesystem-root break, the
default lazy seams (_default_http_client / _default_run_cmd / _default_hf_fetch),
the env-sentinel decode-error path, the unknown-asset guard in ensure(), and the
416/empty-chunk/no-data/cancel installer branches.

All network/subprocess/heavy seams are mocked or replaced; no real download, no
real pip, no httpx/huggingface_hub import in the default-seam tests (those patch
the lazy import target).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from media_studio.assets import manifest
from media_studio.assets.manager import (
    AssetError,
    AssetManager,
    _default_hf_fetch,
    _default_http_client,
    _default_run_cmd,
    _header,
    env_sentinel_path,
    part_path,
    preflight_disk,
)
from media_studio.jobs import JobCancelled


@pytest.fixture(autouse=True)
def _restore_manifest():
    saved = manifest.registry_snapshot()
    try:
        yield
    finally:
        manifest.registry_restore(saved)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=(b"",), on_chunk=None):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._chunks = list(chunks)
        self._on_chunk = on_chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=None):
        for chunk in self._chunks:
            if self._on_chunk is not None:
                self._on_chunk(chunk)
            yield chunk


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, method, url, headers=None):
        self.requests.append({"method": method, "url": url, "headers": dict(headers or {})})
        return self._responses.pop(0)


def big_free_usage(_path: str) -> SimpleNamespace:
    return SimpleNamespace(total=10**13, used=0, free=10**13)


def make_manager(tmp_path, *, client=None, run_cmd=None, hf_fetch=None, usage=big_free_usage):
    return AssetManager(
        root=tmp_path,
        http_factory=(lambda: client) if client is not None else None,
        run_cmd=run_cmd,
        hf_fetch=hf_fetch,
        python_exe="C:/embed/python.exe",
        usage=usage,
        env_vars={},
    )


def download_entry(name="x", *, sha256=None, size_mb=0.001, dest=None):
    return manifest.register_asset(
        name=name,
        kind="model",
        size_mb=size_mb,
        dest=dest or f"models/{name}.bin",
        url=f"https://example.test/{name}.bin",
        sha256=sha256,
    )


# --------------------------------------------------------------------------- #
# _header case-insensitive fallback loop (101->105, 106-107)
# --------------------------------------------------------------------------- #
class _GetlessHeaders:
    """A mapping WITHOUT a .get attribute, forcing the iteration fallback."""

    def __init__(self, data):
        self._data = dict(data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key):
        return self._data[key]


def test_header_iteration_fallback_finds_case_insensitive():
    headers = _GetlessHeaders({"X-Weird-Case": "value-1"})
    assert _header(headers, "x-weird-case") == "value-1"


def test_header_iteration_fallback_returns_none_when_absent():
    headers = _GetlessHeaders({"Other": "z"})
    assert _header(headers, "content-length") is None


def test_header_get_returns_none_then_iteration_also_none():
    """A dict whose .get yields nothing AND no matching key -> None (106-107)."""
    assert _header({"a": "b"}, "missing") is None


# --------------------------------------------------------------------------- #
# preflight_disk: filesystem-root break (line 152)
# --------------------------------------------------------------------------- #
def test_preflight_breaks_at_filesystem_root(monkeypatch):
    """A path whose ancestors NEVER exist walks up to the drive root, where
    parent == probe, then breaks and probes that root (covers line 152)."""
    seen: list[str] = []

    def fake_usage(path: str) -> SimpleNamespace:
        seen.append(path)
        return SimpleNamespace(total=0, used=0, free=10**13)

    import media_studio.assets.manager as mgr_mod

    # Force every ancestor to look non-existent so the walk runs to the root,
    # where Path(root).parent == Path(root) triggers the break.
    monkeypatch.setattr(mgr_mod.Path, "exists", lambda self: False)
    preflight_disk(r"C:\never\made\here", 1, usage=fake_usage)
    assert seen  # usage was consulted on the (root) probe after the break


# --------------------------------------------------------------------------- #
# default lazy seams (269-271, 282-292, 301-303)
# --------------------------------------------------------------------------- #
def test_default_http_client_builds_httpx_client(monkeypatch):
    """_default_http_client lazily imports httpx and builds a Client; we install
    a fake httpx module so no real network lib is required."""
    created = {}

    class FakeTimeout:
        def __init__(self, t):
            created["timeout"] = t

    class FakeHttpxClient:
        def __init__(self, follow_redirects=None, timeout=None):
            created["follow_redirects"] = follow_redirects
            created["timeout_obj"] = timeout

    fake_httpx = SimpleNamespace(Client=FakeHttpxClient, Timeout=FakeTimeout)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    client = _default_http_client()
    assert isinstance(client, FakeHttpxClient)
    assert created["follow_redirects"] is True
    assert created["timeout"] == 30.0


def test_default_run_cmd_runs_subprocess_with_argv_list(monkeypatch):
    """_default_run_cmd merges extra_env, runs an argv list (never shell), and
    returns (returncode, stdout)."""
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=7, stdout="hello-out")

    import media_studio.assets.manager as mgr_mod

    monkeypatch.setattr(mgr_mod.subprocess, "run", fake_run)
    code, out = _default_run_cmd(["py", "-V"], {"EXTRA": "1"})
    assert code == 7
    assert out == "hello-out"
    assert captured["argv"] == ["py", "-V"]
    assert captured["kwargs"]["env"]["EXTRA"] == "1"
    assert captured["kwargs"].get("shell") in (None, False)


def test_default_run_cmd_none_stdout_becomes_empty(monkeypatch):
    import media_studio.assets.manager as mgr_mod

    monkeypatch.setattr(mgr_mod.subprocess, "run", lambda argv, **k: SimpleNamespace(returncode=0, stdout=None))
    code, out = _default_run_cmd(["py"], None)
    assert code == 0
    assert out == ""


def test_default_hf_fetch_calls_snapshot_download(monkeypatch):
    """_default_hf_fetch lazily imports huggingface_hub.snapshot_download; we
    install a fake module so the real lib is not needed."""
    seen = {}

    def fake_snapshot_download(repo_id=None, revision=None):
        seen["repo_id"] = repo_id
        seen["revision"] = revision
        return Path("/cache/snap")

    fake_hub = SimpleNamespace(snapshot_download=fake_snapshot_download)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    out = _default_hf_fetch("org/model", "rev1")
    assert out == str(Path("/cache/snap"))
    assert seen == {"repo_id": "org/model", "revision": "rev1"}


# --------------------------------------------------------------------------- #
# _env_installed: sentinel that is not valid JSON (382-383)
# --------------------------------------------------------------------------- #
def test_env_installed_bad_json_sentinel_is_not_installed(tmp_path):
    entry = manifest.register_asset(
        name="badjson-env",
        kind="env",
        size_mb=10,
        dest="envs/badjson",
        installer="env",
        requirements=("numpy==2.1.0",),
    )
    env_dir = tmp_path / "envs" / "badjson"
    env_dir.mkdir(parents=True)
    env_sentinel_path(env_dir).write_text("{not valid json", encoding="utf-8")
    mgr = make_manager(tmp_path)
    assert mgr.installed_path(entry) is None


# --------------------------------------------------------------------------- #
# ensure(): unknown asset name raises AssetError (line 419)
# --------------------------------------------------------------------------- #
def test_ensure_unknown_asset_raises(tmp_path):
    mgr = make_manager(tmp_path)
    job_ctx = SimpleNamespace(
        progress=lambda *a, **k: None,
        raise_if_cancelled=lambda: None,
        cancelled=False,
    )
    with pytest.raises(AssetError, match="unknown asset"):
        mgr.ensure(["does-not-exist"], job_ctx)


# --------------------------------------------------------------------------- #
# _download_file: 416 fires on_frac (506->508)
# --------------------------------------------------------------------------- #
def test_416_full_part_calls_on_frac(tmp_path):
    entry = download_entry("done416")
    client = FakeClient([FakeResponse(416, {}, chunks=[])])
    mgr = make_manager(tmp_path, client=client)
    dest = mgr.resolve_dest(entry)
    dest.parent.mkdir(parents=True)
    part_path(dest).write_bytes(b"all-here")
    fracs: list[float] = []
    mgr._install(entry, on_frac=lambda f, m="": fracs.append(f), should_cancel=lambda: False)
    assert dest.read_bytes() == b"all-here"
    assert fracs == [1.0]  # the 416 short-circuit reported via on_frac


def test_416_full_part_without_on_frac(tmp_path):
    """The 416 short-circuit with on_frac=None skips the callback (506->508)."""
    entry = download_entry("done416b")
    client = FakeClient([FakeResponse(416, {}, chunks=[])])
    mgr = make_manager(tmp_path, client=client)
    dest = mgr.resolve_dest(entry)
    dest.parent.mkdir(parents=True)
    part_path(dest).write_bytes(b"all-here-too")
    # _download_file invoked directly with on_frac=None to hit the false arm.
    mgr._download_file(str(entry.url), dest, size_mb=entry.size_mb, on_frac=None, label="done416b")
    assert dest.read_bytes() == b"all-here-too"


# --------------------------------------------------------------------------- #
# _download_file: total derived from size_mb (519) + empty-chunk skip (528)
# --------------------------------------------------------------------------- #
def test_total_falls_back_to_size_mb_and_empty_chunk_skipped(tmp_path):
    # No Content-Length header -> total comes from size_mb; an interleaved empty
    # chunk must be skipped without advancing or writing.
    entry = download_entry("nolen", size_mb=0.001)
    client = FakeClient([FakeResponse(200, {}, chunks=[b"part", b"", b"more"])])
    mgr = make_manager(tmp_path, client=client)
    fracs: list[float] = []
    mgr._install(entry, on_frac=lambda f, m="": fracs.append(f), should_cancel=lambda: False)
    assert mgr.resolve_dest(entry).read_bytes() == b"partmore"
    assert fracs[-1] == 1.0
    assert fracs == sorted(fracs)  # monotonic; empty chunk produced no regression


# --------------------------------------------------------------------------- #
# _finalize: no .part produced -> AssetError (line 544)
# --------------------------------------------------------------------------- #
def test_finalize_no_data_raises(tmp_path):
    """A 200 with zero chunks leaves no bytes; _finalize sees no .part file and
    raises (the open(part, 'wb') creates an empty file, so to hit the *missing*
    branch we drive _finalize directly)."""
    mgr = make_manager(tmp_path)
    missing_part = tmp_path / "ghost.part"
    dest = tmp_path / "ghost.bin"
    with pytest.raises(AssetError, match="produced no data"):
        mgr._finalize(missing_part, dest, None, "ghost")


# --------------------------------------------------------------------------- #
# _install_hf: cancel before fetch (line 561)
# --------------------------------------------------------------------------- #
def test_hf_install_cancelled_before_fetch(tmp_path):
    called = {"fetch": 0}

    def hf_fetch(repo_id, revision):
        called["fetch"] += 1
        return "/snap"

    mgr = make_manager(tmp_path, hf_fetch=hf_fetch)
    entry = manifest.get_asset(manifest.WHISPER_ASSET_NAME)
    with pytest.raises(JobCancelled):
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: True)
    assert called["fetch"] == 0  # fetch never reached


# --------------------------------------------------------------------------- #
# _install_env: cancel between steps (line 593)
# --------------------------------------------------------------------------- #
def test_env_installed_true_arm(tmp_path):
    """installed_path() env branch returns the dest string when the sentinel
    matches the current pins (covers line 370/379 True arm)."""
    entry = manifest.register_asset(
        name="ready-env",
        kind="env",
        size_mb=10,
        dest="envs/ready",
        installer="env",
        requirements=("numpy==2.1.0",),
    )
    env_dir = tmp_path / "envs" / "ready"
    env_dir.mkdir(parents=True)
    import json as _json

    env_sentinel_path(env_dir).write_text(
        _json.dumps({"name": "ready-env", "requirements": ["numpy==2.1.0"]}),
        encoding="utf-8",
    )
    mgr = make_manager(tmp_path)
    assert mgr.installed_path(entry) == str(env_dir)


def test_env_installed_false_when_sentinel_missing(tmp_path):
    """_env_installed returns False when no sentinel file exists (line 379)."""
    entry = manifest.register_asset(
        name="unbuilt-env",
        kind="env",
        size_mb=10,
        dest="envs/unbuilt",
        installer="env",
        requirements=("numpy==2.1.0",),
    )
    env_dir = tmp_path / "envs" / "unbuilt"
    env_dir.mkdir(parents=True)  # dir exists, but NO sentinel inside
    mgr = make_manager(tmp_path)
    assert mgr.installed_path(entry) is None


def test_env_install_cancelled_between_steps(tmp_path):
    """should_cancel returns False during get-pip presence check then True at the
    first step boundary -> JobCancelled with no run_cmd executed."""
    (tmp_path / "tools").mkdir(parents=True)
    (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")

    run_calls = {"n": 0}

    def run_cmd(argv, extra_env=None):  # pragma: no cover - must not be reached
        run_calls["n"] += 1
        return 0, ""

    entry = manifest.register_asset(
        name="cancel-env",
        kind="env",
        size_mb=10,
        dest="envs/cancel",
        installer="env",
        requirements=("numpy==2.1.0",),
    )
    mgr = make_manager(tmp_path, run_cmd=run_cmd)
    with pytest.raises(JobCancelled):
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: True)
    assert run_calls["n"] == 0


# --------------------------------------------------------------------------- #
# manifest: detect_existing_gguf explicit-path-missing branch (99->exit, 101)
#           and modelsDir present but file absent (201->203)
# --------------------------------------------------------------------------- #
def test_detect_gguf_explicit_present(tmp_path):
    """An explicit ggufPath that EXISTS returns it (covers the `if p.is_file()`
    true arm -> the 99->exit / 101 region)."""
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(b"GGUF")
    assert manifest.detect_existing_gguf({"ggufPath": str(gguf)}) == str(gguf)


def test_detect_gguf_modelsdir_present_but_no_file(tmp_path):
    """modelsDir is set but the default-named file is absent -> None (201->203
    false arm: the `if cand.is_file()` is not taken)."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    assert manifest.detect_existing_gguf({"modelsDir": str(models_dir)}) is None


def test_detect_gguf_explicit_set_but_missing_then_no_modelsdir(tmp_path):
    """ggufPath set but NOT a file, and no modelsDir -> None (99->exit region:
    the explicit branch's is_file is False and the function exits via 203)."""
    assert manifest.detect_existing_gguf({"ggufPath": str(tmp_path / "nope.gguf")}) is None


# --------------------------------------------------------------------------- #
# AssetEntry.__post_init__: env installer requires a dest (manifest line 101)
# --------------------------------------------------------------------------- #
def test_env_entry_without_dest_raises():
    with pytest.raises(ValueError, match="requires a dest env dir"):
        manifest.AssetEntry(
            name="no-dest-env",
            kind="env",
            size_mb=10,
            installer="env",
            requirements=("numpy==2.1.0",),
        )


def test_valid_env_entry_passes_all_post_init_checks():
    """A fully-valid env entry runs the env branch to completion (99->exit)."""
    entry = manifest.AssetEntry(
        name="good-env",
        kind="env",
        size_mb=10,
        dest="envs/good",
        installer="env",
        requirements=("numpy==2.1.0", "scipy==1.14.1"),
    )
    assert entry.requirements == ("numpy==2.1.0", "scipy==1.14.1")
