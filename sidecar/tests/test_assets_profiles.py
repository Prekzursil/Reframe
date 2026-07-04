"""WU C1 — installer profiles + real progress (ETA/speed) + retry + graceful skip.

Covers the additive C1 surface on top of the existing asset manager:
  * manifest: per-entry ``tier``/``why`` tags + ``resolve_profile`` (Minimum /
    Default / Full / Custom);
  * manager: ``download_speed_eta`` / ``format_bytes_progress`` / ``backoff_delay``
    pure helpers, the ``component``/``plan`` explain surface, download ETA+speed in
    the progress message, automatic exponential-backoff+jitter retry that reuses
    the Range-resume ``.part``, and graceful per-item failure (skip + note);
  * rpc: profile-aware ``assets.ensure`` + the new ``assets.plan`` handler.

Every network/clock/sleep/rng seam is injected — no real download, wall-clock
wait, or randomness.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from media_studio.assets import manifest
from media_studio.assets import rpc as assets_rpc
from media_studio.assets.manager import (
    MB,
    AssetError,
    AssetIntegrityError,
    AssetManager,
    backoff_delay,
    download_speed_eta,
    format_bytes_progress,
    format_eta,
)
from media_studio.jobs import JobCancelled
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fixtures / fakes
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _restore_manifest():
    saved = manifest.registry_snapshot()
    try:
        yield
    finally:
        manifest.registry_restore(saved)


def big_free_usage(_path: str) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(total=10**13, used=0, free=10**13)


def sha_of(*parts: bytes) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


_DUMMY_SHA256 = "a" * 64


def download_entry(name="tiny", *, sha256=_DUMMY_SHA256, size_mb=0.001, dest=None, tier="optional", why=""):
    return manifest.register_asset(
        name=name,
        kind="model",
        size_mb=size_mb,
        dest=dest or f"models/{name}.bin",
        url=f"https://example.test/{name}.bin",
        sha256=sha256,
        tier=tier,
        why=why,
    )


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=(b"",), raise_after=None):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._chunks = list(chunks)
        # raise_after: after yielding this many chunks, raise the given exception
        self._raise_after = raise_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, chunk_size=None):
        for index, chunk in enumerate(self._chunks):
            if self._raise_after is not None and index == self._raise_after[0]:
                raise self._raise_after[1]
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
        if not self._responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        return self._responses.pop(0)


class RecordingSleep:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, delay: float) -> None:
        self.calls.append(delay)


class MaxRng:
    """A deterministic rng whose ``uniform(a, b)`` always returns ``b`` (full jitter)."""

    def uniform(self, a: float, b: float) -> float:  # noqa: D102
        return b


def make_manager(tmp_path: Path, **kw) -> AssetManager:
    kw.setdefault("usage", big_free_usage)
    kw.setdefault("env_vars", {})
    return AssetManager(root=tmp_path, **kw)


class JobCtx:
    """Minimal JobContext-shaped double: records progress, drives cancellation."""

    def __init__(self, cancel=False):
        self._cancel = cancel
        self.progresses: list[tuple[float, str]] = []

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def raise_if_cancelled(self) -> None:
        if self._cancel:
            raise JobCancelled("job")

    def progress(self, pct: float, message: str = "") -> None:
        self.progresses.append((pct, message))


# --------------------------------------------------------------------------- #
# pure helpers: ETA / speed / backoff
# --------------------------------------------------------------------------- #
class TestSpeedEtaHelpers:
    def test_speed_and_eta_normal(self):
        # 10 MB done in 2s => 5 MB/s; 20 MB remaining => 4s ETA.
        speed, eta = download_speed_eta(10 * MB, 20 * MB, 2.0)
        assert speed == pytest.approx(5 * MB)
        assert eta == pytest.approx(4.0)

    def test_zero_elapsed_is_unknown(self):
        assert download_speed_eta(10 * MB, 5 * MB, 0.0) == (None, None)

    def test_zero_done_is_unknown(self):
        assert download_speed_eta(0, 5 * MB, 3.0) == (None, None)

    def test_zero_remaining_gives_zero_eta(self):
        speed, eta = download_speed_eta(4 * MB, 0, 2.0)
        assert speed == pytest.approx(2 * MB)
        assert eta == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "sec,expected",
        [(0, "0s"), (45, "45s"), (59.9, "59s"), (60, "1m00s"), (125, "2m05s"), (3600, "1h00m"), (3725, "1h02m")],
    )
    def test_format_eta_bands(self, sec, expected):
        assert format_eta(sec) == expected

    def test_format_bytes_progress_full(self):
        msg = format_bytes_progress("qwen", 500 * MB, 2500 * MB, 12.5 * MB, 160.0)
        assert msg == "qwen: 500/2500 MB · 12.5 MB/s · ETA 2m40s"

    def test_format_bytes_progress_no_speed_no_eta(self):
        assert format_bytes_progress("x", 3 * MB, 9 * MB, None, None) == "x: 3/9 MB"

    def test_backoff_full_jitter_caps(self):
        rng = MaxRng()
        # attempt 0 -> base; 1 -> 2*base; then capped.
        assert backoff_delay(0, base=1.0, cap=30.0, rng=rng) == pytest.approx(1.0)
        assert backoff_delay(1, base=1.0, cap=30.0, rng=rng) == pytest.approx(2.0)
        assert backoff_delay(2, base=1.0, cap=30.0, rng=rng) == pytest.approx(4.0)
        assert backoff_delay(10, base=1.0, cap=30.0, rng=rng) == pytest.approx(30.0)  # capped


# --------------------------------------------------------------------------- #
# manifest: tier tags + profile resolution
# --------------------------------------------------------------------------- #
class TestManifestProfiles:
    def test_tier_field_defaults_optional_and_validates(self):
        entry = manifest.AssetEntry(
            name="p1", kind="model", size_mb=1, dest="models/p1.bin", url="u", sha256=_DUMMY_SHA256
        )
        assert entry.tier == "optional"
        assert entry.why == ""
        with pytest.raises(ValueError, match="tier must be one of"):
            manifest.AssetEntry(
                name="p2", kind="model", size_mb=1, dest="d", url="u", sha256=_DUMMY_SHA256, tier="premium"
            )

    def test_active_core_entries_are_tier_core(self):
        core = {e.name for e in manifest.all_assets() if e.tier == "core"}
        assert manifest.WHISPER_ASSET_NAME in core
        assert manifest.QWEN_ASSET_NAME in core
        assert manifest.YUNET_ASSET_NAME in core
        assert manifest.LIGHTASD_S3FD_ASSET_NAME in core
        assert manifest.LIGHTASD_ASD_ASSET_NAME in core

    def test_optional_entries_are_not_core(self):
        by_name = {e.name: e for e in manifest.all_assets()}
        assert by_name[manifest.EDGETAM_ASSET_NAME].tier == "optional"
        assert by_name[manifest.HSEMOTION_ASSET_NAME].tier == "optional"
        assert by_name[manifest.RAPIDOCR_ASSET_NAME].tier == "optional"

    def test_active_entries_carry_a_plain_english_why(self):
        # The manifest.py active set (day-1 + phase-8 + lightasd + yunet + edgetam)
        # each carries a plain-English why for the assets.plan explain surface.
        active = {
            manifest.WHISPER_ASSET_NAME,
            manifest.QWEN_ASSET_NAME,
            manifest.EMBEDDER_ASSET_NAME,
            manifest.HSEMOTION_ASSET_NAME,
            manifest.RAPIDOCR_ASSET_NAME,
            manifest.LIGHTASD_S3FD_ASSET_NAME,
            manifest.LIGHTASD_ASD_ASSET_NAME,
            manifest.YUNET_ASSET_NAME,
            manifest.EDGETAM_ASSET_NAME,
        }
        by_name = {e.name: e for e in manifest.all_assets()}
        for name in active:
            assert by_name[name].why, f"{name} is missing a plain-English 'why'"

    def test_resolve_minimum_is_empty(self):
        assert manifest.resolve_profile("minimum") == []

    def test_resolve_default_is_core_only(self):
        names = manifest.resolve_profile("default")
        tiers = {manifest.get_asset(n).tier for n in names}
        assert tiers == {"core"}
        assert manifest.WHISPER_ASSET_NAME in names
        assert manifest.EDGETAM_ASSET_NAME not in names

    def test_resolve_full_includes_core_and_optional(self):
        names = set(manifest.resolve_profile("full"))
        assert manifest.WHISPER_ASSET_NAME in names
        assert manifest.EDGETAM_ASSET_NAME in names
        assert manifest.HSEMOTION_ASSET_NAME in names

    def test_resolve_is_case_insensitive(self):
        assert manifest.resolve_profile("DEFAULT") == manifest.resolve_profile("default")

    def test_resolve_custom_returns_given_names_deduped(self):
        download_entry("c-a")
        download_entry("c-b")
        assert manifest.resolve_profile("custom", ["c-a", "c-b", "c-a"]) == ["c-a", "c-b"]

    def test_resolve_custom_empty_is_empty(self):
        assert manifest.resolve_profile("custom") == []

    def test_resolve_custom_unknown_name_raises(self):
        with pytest.raises(ValueError, match="unknown asset"):
            manifest.resolve_profile("custom", ["never-registered"])

    def test_resolve_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="profile must be one of"):
            manifest.resolve_profile("mega")


# --------------------------------------------------------------------------- #
# manager: component + plan explain surface
# --------------------------------------------------------------------------- #
class TestPlanSurface:
    def test_component_carries_what_why_size_tier(self, tmp_path):
        entry = download_entry("explain", size_mb=1234, tier="core", why="does the thing")
        mgr = make_manager(tmp_path)
        comp = mgr.component(entry)
        assert comp["name"] == "explain"
        assert comp["tier"] == "core"
        assert comp["why"] == "does the thing"
        assert comp["sizeMB"] == 1234
        assert comp["installed"] is False
        assert "label" in comp and "dest" in comp

    def test_plan_totals_and_to_download(self, tmp_path):
        a = download_entry("plan-a", size_mb=100, tier="core", why="a")
        download_entry("plan-b", size_mb=50, tier="core", why="b")
        mgr = make_manager(tmp_path)
        # Pre-install plan-a so it drops out of the to-download total.
        dest = mgr.resolve_dest(a)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x" * int(100 * MB * 0.6))
        plan = mgr.plan("custom", ["plan-a", "plan-b"])
        assert plan["profile"] == "custom"
        assert plan["totalMB"] == pytest.approx(150)
        assert plan["toDownloadMB"] == pytest.approx(50)  # only plan-b remains
        names = [c["name"] for c in plan["components"]]
        assert names == ["plan-a", "plan-b"]


# --------------------------------------------------------------------------- #
# manager: download progress carries ETA + speed
# --------------------------------------------------------------------------- #
class TestDownloadProgressEta:
    def test_progress_message_has_speed_and_eta(self, tmp_path):
        body = b"z" * (2 * MB)
        entry = download_entry("etacheck", size_mb=4, sha256=sha_of(body, body))
        client = FakeClient([FakeResponse(200, {"Content-Length": str(4 * MB)}, chunks=[body, body])])
        # Deterministic clock: 0.0 at start, then +1s each read.
        ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        mgr = make_manager(tmp_path, http_factory=lambda: client, clock=lambda: next(ticks))
        messages: list[str] = []
        mgr._download_file(
            str(entry.url),
            mgr.resolve_dest(entry),
            size_mb=4,
            sha256=entry.sha256,
            on_frac=lambda f, m="": messages.append(m),
            should_cancel=lambda: False,
            label="etacheck",
        )
        mid = [m for m in messages if "MB/s" in m]
        assert mid, f"expected a speed-bearing progress message, got {messages}"
        assert "ETA" in mid[0]


# --------------------------------------------------------------------------- #
# manager: automatic retry (exponential backoff + jitter, reusing .part resume)
# --------------------------------------------------------------------------- #
class TestRetry:
    def test_transient_drop_is_retried_and_resumes_from_part(self, tmp_path):
        head, tail = b"h" * (1 * MB), b"t" * (1 * MB)
        entry = download_entry("resumer", size_mb=2, sha256=sha_of(head, tail))
        # 1st stream: 200, yields head then raises ConnectionError before tail.
        # 2nd stream: 206 resume from the byte offset, yields tail.
        resp1 = FakeResponse(
            200, {"Content-Length": str(2 * MB)}, chunks=[head, tail], raise_after=(1, ConnectionError("drop"))
        )
        resp2 = FakeResponse(
            206,
            {"Content-Range": f"bytes {MB}-{2 * MB - 1}/{2 * MB}", "Content-Length": str(MB)},
            chunks=[tail],
        )
        client = FakeClient([resp1, resp2])
        sleep = RecordingSleep()
        mgr = make_manager(
            tmp_path,
            http_factory=lambda: client,
            sleep=sleep,
            rng=MaxRng(),
            retry_base=0.5,
            retry_cap=10.0,
            max_download_retries=3,
        )
        ctx = JobCtx()
        result = mgr.ensure(["resumer"], ctx)
        assert result["installed"] == ["resumer"]
        assert result["failed"] == []
        assert mgr.resolve_dest(entry).read_bytes() == head + tail
        # exactly one retry => one backoff sleep, at base (attempt 0, full jitter=b).
        assert sleep.calls == [pytest.approx(0.5)]
        # the resume request carried a Range header from the .part offset.
        assert client.requests[1]["headers"].get("Range") == f"bytes={MB}-"

    def test_retries_exhausted_surfaces_failure(self, tmp_path):
        download_entry("doomed", size_mb=1)
        responses = [
            FakeResponse(200, {"Content-Length": str(MB)}, chunks=[b"x"], raise_after=(0, ConnectionError("nope")))
            for _ in range(5)
        ]
        client = FakeClient(responses)
        sleep = RecordingSleep()
        mgr = make_manager(tmp_path, http_factory=lambda: client, sleep=sleep, rng=MaxRng(), max_download_retries=2)
        ctx = JobCtx()
        with pytest.raises(AssetError):
            mgr.ensure(["doomed"], ctx)
        assert len(sleep.calls) == 2  # 2 retries then give up

    def test_integrity_error_is_not_retried(self, tmp_path):
        body = b"q" * (1 * MB)
        # sha pin deliberately WRONG => AssetIntegrityError, must NOT retry.
        entry = download_entry("badsha", size_mb=1, sha256=sha_of(b"different"))
        client = FakeClient([FakeResponse(200, {"Content-Length": str(MB)}, chunks=[body])])
        sleep = RecordingSleep()
        mgr = make_manager(tmp_path, http_factory=lambda: client, sleep=sleep, rng=MaxRng())
        with pytest.raises(AssetIntegrityError, match="sha256 mismatch"):
            mgr._install_with_retry(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert sleep.calls == []

    def test_cancellation_is_not_retried(self, tmp_path):
        entry = download_entry("cancelme", size_mb=1)
        cancel = {"v": False}
        body = b"c" * (1 * MB)

        def _mark(_chunk):
            cancel["v"] = True

        resp = FakeResponse(200, {"Content-Length": str(MB)}, chunks=[body])
        client = FakeClient([resp])
        sleep = RecordingSleep()
        mgr = make_manager(tmp_path, http_factory=lambda: client, sleep=sleep, rng=MaxRng())
        with pytest.raises(JobCancelled):
            mgr._install_with_retry(entry, on_frac=lambda f, m="": None, should_cancel=lambda: True)
        assert sleep.calls == []


# --------------------------------------------------------------------------- #
# manager.ensure: graceful per-item failure (skip + note, never brick)
# --------------------------------------------------------------------------- #
class TestGracefulSkip:
    def test_one_failed_item_is_skipped_others_install(self, tmp_path):
        good = b"g" * (1 * MB)
        download_entry("bad-item", size_mb=1)
        download_entry("good-item", size_mb=1, sha256=sha_of(good))
        client = FakeClient(
            [
                FakeResponse(500, {}, chunks=[]),  # bad-item: HTTP 500 (definitive, not retried)
                FakeResponse(200, {"Content-Length": str(MB)}, chunks=[good]),  # good-item OK
            ]
        )
        mgr = make_manager(tmp_path, http_factory=lambda: client, max_download_retries=0)
        ctx = JobCtx()
        result = mgr.ensure(["bad-item", "good-item"], ctx)
        assert result["installed"] == ["good-item"]
        assert [f["name"] for f in result["failed"]] == ["bad-item"]
        assert "HTTP 500" in result["failed"][0]["error"]
        # progress still climbs to 100 (install not bricked).
        assert ctx.progresses[-1][0] == 100.0

    def test_cancellation_mid_item_aborts_whole_job(self, tmp_path):
        # Cancel arrives DURING an item's download (loop-top guard passes, then
        # should_cancel fires mid-stream) -> ensure re-raises JobCancelled, never
        # swallowing it as a per-item "skip".
        download_entry("cancel-mid", size_mb=1)
        client = FakeClient([FakeResponse(200, {"Content-Length": str(MB)}, chunks=[b"c" * MB])])

        class CancelMidInstall(JobCtx):
            @property
            def cancelled(self) -> bool:
                return True  # should_cancel() sees it -> _download_file aborts

            def raise_if_cancelled(self) -> None:
                return  # loop-top guard passes (cancel "arrives" mid-item)

        mgr = make_manager(tmp_path, http_factory=lambda: client, max_download_retries=0)
        with pytest.raises(JobCancelled):
            mgr.ensure(["cancel-mid"], CancelMidInstall())

    def test_all_failed_raises_so_job_errors(self, tmp_path):
        download_entry("only-bad", size_mb=1)
        client = FakeClient([FakeResponse(500, {}, chunks=[])])
        mgr = make_manager(tmp_path, http_factory=lambda: client, max_download_retries=0)
        with pytest.raises(AssetError, match="only-bad"):
            mgr.ensure(["only-bad"], JobCtx())

    def test_already_installed_survivor_prevents_error(self, tmp_path):
        present = download_entry("already", size_mb=1)
        download_entry("failing", size_mb=1)
        mgr = make_manager(
            tmp_path,
            http_factory=lambda: FakeClient([FakeResponse(500, {}, chunks=[])]),
            max_download_retries=0,
        )
        dest = mgr.resolve_dest(present)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"y" * int(MB * 0.6))
        result = mgr.ensure(["already", "failing"], JobCtx())
        assert result["installed"] == ["already"]
        assert [f["name"] for f in result["failed"]] == ["failing"]


# --------------------------------------------------------------------------- #
# rpc: profile-aware ensure + assets.plan
# --------------------------------------------------------------------------- #
class FakeJob:
    def __init__(self, job_id, body):
        self.id = job_id
        self._body = body

    def run(self):
        return self._body(JobCtx())


class FakeJobs:
    def __init__(self):
        self.started = []

    def start(self, body):
        job = FakeJob(f"job-{len(self.started)}", body)
        self.started.append(job)
        return job


def rpc_ctx(jobs=None) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=jobs or FakeJobs())


class TestRpcProfiles:
    def test_ensure_by_profile_resolves_names(self, tmp_path):
        mgr = make_manager(tmp_path)
        jobs = FakeJobs()
        handler = assets_rpc.make_ensure_handler(mgr)
        res = handler({"profile": "minimum"}, rpc_ctx(jobs))
        assert res["jobId"] == "job-0"
        # minimum resolves to [] => the job body ensures nothing.
        out = jobs.started[0].run()
        assert out["installed"] == []

    def test_ensure_by_names_still_works(self, tmp_path):
        download_entry("byname", size_mb=0)
        mgr = make_manager(tmp_path)
        jobs = FakeJobs()
        handler = assets_rpc.make_ensure_handler(mgr)
        res = handler({"names": ["byname"]}, rpc_ctx(jobs))
        assert res["jobId"] == "job-0"

    def test_ensure_invalid_profile_type_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_ensure_handler(mgr)
        with pytest.raises(RpcError, match="profile"):
            handler({"profile": 123}, rpc_ctx())

    def test_ensure_unknown_profile_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_ensure_handler(mgr)
        with pytest.raises(RpcError, match="profile must be one of"):
            handler({"profile": "mega"}, rpc_ctx())

    def test_ensure_bad_custom_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_ensure_handler(mgr)
        with pytest.raises(RpcError, match="custom"):
            handler({"profile": "custom", "custom": [1, 2]}, rpc_ctx())

    def test_plan_handler_returns_components(self, tmp_path):
        download_entry("planned", size_mb=42, tier="core", why="needed")
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_plan_handler(mgr)
        out = handler({"profile": "custom", "custom": ["planned"]}, rpc_ctx())
        assert out["profile"] == "custom"
        assert out["components"][0]["why"] == "needed"
        assert out["toDownloadMB"] == pytest.approx(42)

    def test_plan_handler_requires_profile(self, tmp_path):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_plan_handler(mgr)
        with pytest.raises(RpcError, match="profile"):
            handler({}, rpc_ctx())

    def test_plan_handler_unknown_profile_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_plan_handler(mgr)
        with pytest.raises(RpcError, match="profile must be one of"):
            handler({"profile": "nope"}, rpc_ctx())

    def test_plan_handler_bad_custom_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_plan_handler(mgr)
        with pytest.raises(RpcError, match="custom"):
            handler({"profile": "custom", "custom": "notalist"}, rpc_ctx())

    def test_register_includes_plan(self, tmp_path):
        registered: dict[str, Any] = {}
        assets_rpc.register(
            make_manager(tmp_path),
            register_fn=lambda name, fn: registered.__setitem__(name, fn),
        )
        assert "assets.plan" in registered
