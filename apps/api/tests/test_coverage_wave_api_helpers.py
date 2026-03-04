from __future__ import annotations

import builtins
import logging
import sys
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import billing, cleanup, local_queue, logging_config, storage


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


@pytest.fixture(autouse=True)
def _reset_local_queue_state(monkeypatch):
    local_queue._executor.cache_clear()
    if hasattr(local_queue._worker_tasks, "cache_clear"):
        local_queue._worker_tasks.cache_clear()
    with local_queue._pending_lock:
        local_queue._pending.clear()
    monkeypatch.delenv("REFRAME_LOCAL_QUEUE_MODE", raising=False)
    monkeypatch.delenv("LOCAL_QUEUE_MODE", raising=False)
    monkeypatch.delenv("REFRAME_LOCAL_QUEUE_WORKERS", raising=False)
    yield
    local_queue._executor.cache_clear()
    if hasattr(local_queue._worker_tasks, "cache_clear"):
        local_queue._worker_tasks.cache_clear()
    with local_queue._pending_lock:
        local_queue._pending.clear()


def test_local_queue_truthy_and_mode_detection(monkeypatch):
    _expect(local_queue._truthy("1"), "Expected truthy helper to treat 1 as true")
    _expect(not local_queue._truthy("0"), "Expected truthy helper to treat 0 as false")
    _expect(not local_queue.is_local_queue_mode(), "Expected local queue mode disabled by default")
    monkeypatch.setenv("REFRAME_LOCAL_QUEUE_MODE", "true")
    _expect(local_queue.is_local_queue_mode(), "Expected local queue mode via REFRAME_LOCAL_QUEUE_MODE")
    monkeypatch.delenv("REFRAME_LOCAL_QUEUE_MODE", raising=False)
    monkeypatch.setenv("LOCAL_QUEUE_MODE", "yes")
    _expect(local_queue.is_local_queue_mode(), "Expected local queue mode via LOCAL_QUEUE_MODE")


def test_local_queue_dispatch_and_revoke(monkeypatch):
    monkeypatch.setenv("REFRAME_LOCAL_QUEUE_MODE", "true")
    calls: list[tuple[str, tuple[object, ...]]] = []
    ready = threading.Event()

    def fake_run_task(task_name: str, args: tuple[object, ...]) -> None:
        calls.append((task_name, args))
        ready.set()

    monkeypatch.setattr(local_queue, "_run_task", fake_run_task)

    task_id = local_queue.dispatch_task("tasks.echo", "hello", queue="high")
    _expect(task_id.startswith("local-"), "Expected local queue task id prefix")
    _expect(ready.wait(timeout=2), "Expected dispatched task to execute")

    for _ in range(20):
        with local_queue._pending_lock:
            if task_id not in local_queue._pending:
                break
        time.sleep(0.02)

    _expect(calls == [("tasks.echo", ("hello",))], "Expected _run_task dispatch call")
    _expect(not local_queue.revoke_task("missing"), "Expected revoke false for missing task")


def test_local_queue_dispatch_requires_enabled():
    with pytest.raises(RuntimeError):
        local_queue.dispatch_task("tasks.echo")


def test_local_queue_diagnostics_enabled_and_error_paths(monkeypatch):
    monkeypatch.setenv("REFRAME_LOCAL_QUEUE_MODE", "true")

    monkeypatch.setattr(
        local_queue,
        "_worker_tasks",
        lambda: {"tasks.system_info": SimpleNamespace(run=lambda: {"ffmpeg": {"present": True}})},
    )
    payload = local_queue.diagnostics()
    _expect(payload["ping_ok"] is True, "Expected diagnostics ping ok")
    _expect(payload["system_info"] == {"ffmpeg": {"present": True}}, "Expected system_info payload")
    _expect(payload["error"] is None, "Expected no diagnostics error")

    monkeypatch.setattr(local_queue, "_worker_tasks", lambda: {})
    payload_no_task = local_queue.diagnostics()
    _expect(payload_no_task["ping_ok"] is True, "Expected diagnostics ping true in local mode")
    _expect(payload_no_task["system_info"] is None, "Expected missing system_info")
    _expect("unavailable" in str(payload_no_task["error"]), "Expected unavailable error message")

    monkeypatch.delenv("REFRAME_LOCAL_QUEUE_MODE", raising=False)
    disabled = local_queue.diagnostics()
    _expect(disabled["ping_ok"] is False, "Expected disabled diagnostics ping false")
    _expect("disabled" in str(disabled["error"]).lower(), "Expected disabled diagnostics error")


def test_local_storage_backend_file_lifecycle(tmp_path):
    backend = storage.LocalStorageBackend(media_root=tmp_path, public_prefix="/media")
    uri = backend.write_bytes(rel_dir="org-a/tmp", filename="hello.txt", data=b"hello")
    _expect(uri == "/media/org-a/tmp/hello.txt", "Expected media URI for written bytes")
    local_path = backend.resolve_local_path(uri)
    _expect(local_path.read_bytes() == b"hello", "Expected file contents after write_bytes")

    source = tmp_path / "source.bin"
    source.write_bytes(b"abc")
    uri_file = backend.write_file(rel_dir="org-a/out", filename="copy.bin", source_path=source)
    _expect(uri_file == "/media/org-a/out/copy.bin", "Expected media URI for write_file")
    _expect(backend.get_download_url(uri_file) == uri_file, "Expected direct URI for local download")
    _expect(backend.resolve_local_path("/media/org-a/out/copy.bin").read_bytes() == b"abc", "Expected copied bytes")

    backend.delete_uri(uri_file)
    _expect(not backend.resolve_local_path(uri_file).exists(), "Expected deleted URI to remove file")

    with pytest.raises(ValueError):
        backend.resolve_local_path("/media/../../escape.txt")
    with pytest.raises(ValueError):
        backend.resolve_local_path("https://example.test/file.bin")
    with pytest.raises(ValueError):
        backend.create_presigned_upload(rel_dir="a", filename="b", content_type=None, expires_seconds=60)
    with pytest.raises(ValueError):
        backend.create_multipart_upload(rel_dir="a", filename="b", content_type=None)
    with pytest.raises(ValueError):
        backend.sign_multipart_part(key="k", provider_upload_id="u", part_number=1, expires_seconds=60)
    with pytest.raises(ValueError):
        backend.complete_multipart_upload(key="k", provider_upload_id="u", parts=[])
    with pytest.raises(ValueError):
        backend.abort_multipart_upload(key="k", provider_upload_id="u")


def test_storage_helpers_and_get_storage_modes(monkeypatch, tmp_path):
    _expect(storage.is_remote_uri("https://example.test/a"), "Expected https URI to be treated as remote")
    _expect(storage.is_remote_uri("s3://bucket/key"), "Expected s3 URI to be treated as remote")
    _expect(not storage.is_remote_uri("/media/a"), "Expected local path to be non-remote")
    _expect(storage._join_key("/a/", "b", "c/") == "a/b/c", "Expected normalized key join")

    monkeypatch.setenv("S3_BUCKET", "")
    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "local")
    local_backend = storage.get_storage(media_root=tmp_path)
    _expect(isinstance(local_backend, storage.LocalStorageBackend), "Expected local storage backend")

    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "unknown-backend")
    with pytest.raises(ValueError):
        storage.get_storage(media_root=tmp_path)

    monkeypatch.setenv("REFRAME_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "true")
    with pytest.raises(RuntimeError):
        storage.get_storage(media_root=tmp_path)


def test_s3_storage_backend_core_paths(monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, tuple, dict]] = []

        def put_object(self, **kwargs):
            self.calls.append(("put_object", (), kwargs))

        def upload_file(self, *args, **kwargs):
            self.calls.append(("upload_file", args, kwargs))

        def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
            self.calls.append(("generate_presigned_url", (op,), {"Params": Params, "ExpiresIn": ExpiresIn}))
            return f"https://upload.example/{op}"

        def create_multipart_upload(self, **kwargs):
            self.calls.append(("create_multipart_upload", (), kwargs))
            return {"UploadId": "upload-1"}

        def complete_multipart_upload(self, **kwargs):
            self.calls.append(("complete_multipart_upload", (), kwargs))

        def abort_multipart_upload(self, **kwargs):
            self.calls.append(("abort_multipart_upload", (), kwargs))

        def delete_object(self, **kwargs):
            self.calls.append(("delete_object", (), kwargs))

    fake_client = FakeClient()

    class FakeSession:
        def client(self, *_args, **_kwargs):
            return fake_client

    class FakeSessionFactory:
        def Session(self, **_kwargs):
            return FakeSession()

    monkeypatch.setattr(storage, "_ensure_boto3", lambda: SimpleNamespace(session=FakeSessionFactory()))

    backend = storage.S3StorageBackend(
        bucket="bucket-a",
        prefix="tenant",
        endpoint_url="https://s3.example.test",
        public_base_url="https://cdn.example.test/assets",
        public_downloads=True,
        presign_expires_seconds=300,
    )

    src = tmp_path / "in.bin"
    src.write_bytes(b"data")

    uri = backend.write_bytes(rel_dir="org", filename="bytes.bin", data=b"1", content_type="application/octet-stream")
    _expect(uri == "s3://bucket-a/tenant/org/bytes.bin", "Expected S3 URI for write_bytes")
    uri_file = backend.write_file(rel_dir="org", filename="file.bin", source_path=src, content_type="application/octet-stream")
    _expect(uri_file == "s3://bucket-a/tenant/org/file.bin", "Expected S3 URI for write_file")
    _expect(backend.get_download_url(uri_file) == "https://cdn.example.test/assets/tenant/org/file.bin", "Expected public download URL path")
    _expect(backend.get_download_url("s3://other-bucket/file") is None, "Expected None for foreign-bucket URI")

    presigned = backend.create_presigned_upload(
        rel_dir="org",
        filename="upload.bin",
        content_type="application/octet-stream",
        expires_seconds=120,
    )
    _expect(presigned["method"] == "PUT", "Expected PUT method for presigned upload")

    multi = backend.create_multipart_upload(rel_dir="org", filename="multi.bin", content_type=None)
    _expect(multi["upload_id"] == "upload-1", "Expected multipart upload id")

    part = backend.sign_multipart_part(
        key=multi["key"],
        provider_upload_id=multi["upload_id"],
        part_number=1,
        expires_seconds=60,
    )
    _expect(part["method"] == "PUT", "Expected multipart part PUT upload")

    backend.complete_multipart_upload(
        key=multi["key"],
        provider_upload_id=multi["upload_id"],
        parts=[{"part_number": 2, "etag": "b"}, {"part_number": 1, "etag": "a"}],
    )
    with pytest.raises(ValueError):
        backend.complete_multipart_upload(key=multi["key"], provider_upload_id=multi["upload_id"], parts=[{"part_number": 0}])

    backend.abort_multipart_upload(key=multi["key"], provider_upload_id=multi["upload_id"])
    backend.delete_uri(uri)

    with pytest.raises(ValueError):
        backend.resolve_local_path(uri)

    ops = [name for name, _args, _kwargs in fake_client.calls]
    _expect("put_object" in ops, "Expected put_object call")
    _expect("upload_file" in ops, "Expected upload_file call")
    _expect("create_multipart_upload" in ops, "Expected create_multipart_upload call")
    _expect("complete_multipart_upload" in ops, "Expected complete_multipart_upload call")
    _expect("abort_multipart_upload" in ops, "Expected abort_multipart_upload call")


def test_json_formatter_and_setup_logging_paths():
    formatter = logging_config.JsonFormatter()

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord(
            name="reframe.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failure: %s",
            args=("x",),
            exc_info=sys.exc_info(),
        )
        record.user_id = "u-1"
        rendered = formatter.format(record)
        _expect('"message": "failure: x"' in rendered, "Expected rendered log message")
        _expect('"user_id": "u-1"' in rendered, "Expected extra log field")
        _expect("exc_info" in rendered, "Expected formatted exception info")

    logger = logging.getLogger("reframe")
    setattr(logger, "_reframe_configured", False)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    logging_config.setup_logging(log_format="plain", log_level="warning")
    first_count = len(logger.handlers)
    logging_config.setup_logging(log_format="json", log_level="debug")
    _expect(len(logger.handlers) == first_count, "Expected setup logging to be idempotent")


def test_cleanup_old_files_and_loop_start(tmp_path):
    target = tmp_path / "tmp"
    target.mkdir(parents=True, exist_ok=True)

    old_file = target / "old.txt"
    new_file = target / "new.txt"
    old_file.write_text("old", encoding="utf-8")
    new_file.write_text("new", encoding="utf-8")

    old_ts = time.time() - 10_000
    os.utime(old_file, (old_ts, old_ts))

    cleanup._remove_old_files(target, older_than=cleanup.timedelta(seconds=1))
    _expect(not old_file.exists(), "Expected old file cleanup")
    _expect(new_file.exists(), "Expected newer file to remain")

    thread = cleanup.start_cleanup_loop(str(tmp_path), interval_seconds=60, ttl_hours=24)
    _expect(thread is not None, "Expected cleanup thread")
    _expect(thread.daemon, "Expected cleanup loop thread daemonized")
    _expect((tmp_path / "tmp").exists(), "Expected tmp directory creation")


def test_billing_plan_and_stripe_paths(monkeypatch):
    free = billing.get_plan_policy("unknown-plan")
    _expect(free.code == "free", "Expected free fallback policy")
    _expect(billing.get_plan_policy("enterprise").seat_limit == 200, "Expected enterprise policy lookup")

    class _Settings:
        enable_billing = False
        stripe_secret_key = ""

    monkeypatch.setattr(billing, "get_settings", lambda: _Settings())
    with pytest.raises(RuntimeError):
        billing.build_checkout_session(
            customer_id=None,
            price_id="price_x",
            success_url="https://ok",
            cancel_url="https://cancel",
        )

    class _SettingsEnabledNoKey:
        enable_billing = True
        stripe_secret_key = ""

    monkeypatch.setattr(billing, "get_settings", lambda: _SettingsEnabledNoKey())
    with pytest.raises(RuntimeError):
        billing.build_customer_portal_session(customer_id="cus_1", return_url="https://ret")

    class _SettingsEnabled:
        enable_billing = True
        stripe_secret_key = "sk_test_123"

    checkout_calls: list[dict] = []
    modify_calls: list[tuple[str, dict]] = []
    portal_calls: list[dict] = []

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            checkout_calls.append(kwargs)
            return {"id": "cs_1", "url": "https://checkout"}

    class _Subscription:
        @staticmethod
        def modify(sub_id: str, **kwargs):
            modify_calls.append((sub_id, kwargs))

    class _PortalSession:
        @staticmethod
        def create(**kwargs):
            portal_calls.append(kwargs)
            return {"id": "bps_1", "url": "https://portal"}

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=_CheckoutSession),
        Subscription=_Subscription,
        billing_portal=SimpleNamespace(Session=_PortalSession),
    )

    monkeypatch.setattr(billing, "get_settings", lambda: _SettingsEnabled())
    monkeypatch.setattr(billing, "_get_stripe", lambda: fake_stripe)

    checkout = billing.build_checkout_session(
        customer_id="cus_1",
        price_id="price_1",
        quantity=0,
        success_url="https://ok",
        cancel_url="https://cancel",
        metadata={"org_id": "x"},
    )
    _expect(checkout["id"] == "cs_1", "Expected checkout id")
    _expect(checkout_calls[0]["line_items"][0]["quantity"] == 1, "Expected quantity coercion to minimum 1")

    billing.update_subscription_seat_limit(subscription_id="sub_1", quantity=0)
    _expect(modify_calls[0][0] == "sub_1", "Expected subscription id for seat update")
    _expect(modify_calls[0][1]["items"][0]["quantity"] == 1, "Expected seat quantity minimum to 1")

    portal = billing.build_customer_portal_session(customer_id="cus_1", return_url="https://return")
    _expect(portal["url"] == "https://portal", "Expected portal URL")
    _expect(portal_calls[0]["customer"] == "cus_1", "Expected portal customer id")


def test_get_stripe_import_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "stripe":
            raise ImportError("missing stripe")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError):
        billing._get_stripe()


