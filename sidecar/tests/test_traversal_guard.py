"""T5 PATH-TRAVERSAL guards — batch store ids + convert output/input confinement.

Three verified defects, one test module (the two features share one root cause:
an untrusted renderer string reaching a filesystem/ffmpeg sink unguarded).

1. ``features/batch.py`` — the batch ID becomes a filename component
   (``batches/<id>.json``), so an id of ``../settings`` made ``batch.status``
   READ and ``batch.delete`` DELETE the app's own ``<data_dir>/settings.json``
   (which holds the cloud API key). Fixed by an opaque-id GRAMMAR plus real
   containment through ``ensure_within(<batch dir>, <safe id>.json)``.
2. ``features/convert.py`` — the caller-supplied ``out`` was handed to ffmpeg
   ``-y`` verbatim, i.e. overwrite ANY writable file. Fixed by confining the
   destination to the source's own directory or the app data root.
3. ``features/convert.py`` — a renderer input string reached ffmpeg/ffprobe as an
   HTTP/FTP/UNC/``concat`` PROTOCOL (SSRF, internal-service probing, SMB
   credential leak, arbitrary local read). Fixed by the shared
   ``pathsafe.ensure_local_media_input`` guard.

Everything is exercised at the seam: ``run``/``probe`` are injected, so no real
ffmpeg is spawned and the assertions read the argv that WOULD have been executed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg
from media_studio.features import batch, convert
from media_studio.jobs import JobRegistry
from media_studio.pathsafe import PathTraversalError, UnsafeMediaInputError
from media_studio.protocol import RpcContext, RpcError

# --------------------------------------------------------------------------- #
# shared fixtures / doubles
# --------------------------------------------------------------------------- #
#: ids that must never reach the filesystem as a path component.
UNSAFE_IDS: tuple[str, ...] = (
    "../settings",
    "..\\..\\evil",
    "..",
    ".",
    "",
    "a/b",
    "a\\b",
    "/etc/passwd",
    "C:/Windows/win.ini",
    ".hidden",
    "id with space",
    "id\nwith-newline",
)


def _registry() -> JobRegistry:
    return JobRegistry(emit_progress=lambda *a: None, emit_done=lambda *a: None)


def _ctx(reg: JobRegistry | None = None) -> RpcContext:
    return RpcContext(emit_notification=lambda *a: None, jobs=reg)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """An app data root holding the victim ``settings.json`` + a ``batches/`` dir."""
    root = tmp_path / "data"
    (root / "batches").mkdir(parents=True)
    (root / "settings.json").write_text(
        json.dumps({"cloudApiKey": "sk-live-SECRET", "useCloud": True}),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def store(data_dir: Path) -> batch.BatchStore:
    return batch.BatchStore(data_dir / "batches")


class _RunRecorder:
    """A fake ``ffmpeg.run`` that records the argv it WOULD have executed."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, total_sec=0.0, on_progress=None, should_cancel=None) -> int:  # noqa: ANN001
        self.calls.append(list(argv))
        return 0


def _probe(in_path: str, settings: dict[str, Any] | None = None) -> float:
    return 1.0


@pytest.fixture()
def bins(tmp_path: Path) -> dict[str, str]:
    """Settings pointing at a dir with fake ffmpeg/ffprobe binaries."""
    binaries = tmp_path / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        (binaries / f"{name}{ffmpeg._EXE}").write_text("#!/bin/sh\n", encoding="utf-8")
    return {"ffmpegPath": str(binaries)}


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    """A source clip in its OWN directory (never the fake-bin or data dir)."""
    src = tmp_path / "clips" / "in.mov"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"\x00" * 16)
    return src


# =========================================================================== #
# 1. batch — the id grammar + real containment (the 8-slice finding)
# =========================================================================== #
class TestBatchIdContainment:
    def test_delete_refuses_dotdot_id_and_leaves_settings_json(self, store: batch.BatchStore, data_dir: Path) -> None:
        """THE headline: ``batch.delete({"id": "../settings"})`` must not unlink settings.json."""
        victim = data_dir / "settings.json"
        with pytest.raises(RpcError):
            store.delete("../settings")
        assert victim.exists(), "batch.delete traversal deleted the app's settings.json"
        assert "sk-live-SECRET" in victim.read_text(encoding="utf-8")

    def test_load_refuses_dotdot_id_so_settings_cannot_be_read_back(self, store: batch.BatchStore) -> None:
        """``batch.status`` must not be able to read an arbitrary JSON file."""
        with pytest.raises(RpcError):
            store.load("../settings")

    def test_load_refuses_windows_absolute_id(self, store: batch.BatchStore, tmp_path: Path) -> None:
        with pytest.raises(RpcError):
            store.load(str(tmp_path / "elsewhere" / "boom"))

    def test_load_refuses_backslash_traversal(self, store: batch.BatchStore) -> None:
        with pytest.raises(RpcError):
            store.load("..\\..\\evil")

    @pytest.mark.parametrize("bad_id", UNSAFE_IDS)
    def test_every_store_entry_point_refuses_an_unsafe_id(self, store: batch.BatchStore, bad_id: str) -> None:
        for call in (
            lambda: store.load(bad_id),
            lambda: store.delete(bad_id),
            lambda: store.update_item(bad_id, "v1", status="done"),
            lambda: store.set_status(bad_id, "error"),
        ):
            with pytest.raises(RpcError):
                call()

    def test_error_message_is_log_safe(self, store: batch.BatchStore) -> None:
        with pytest.raises(RpcError) as exc:
            store.load("id\r\nFAKE LOG LINE")
        assert "\n" not in str(exc.value) and "\r" not in str(exc.value)

    def test_path_is_confined_under_the_batch_dir(self, store: batch.BatchStore) -> None:
        import os

        assert store._path("abc123") == Path(os.path.realpath(str(store.dir / "abc123.json")))

    def test_new_state_refuses_an_unsafe_batch_id(self) -> None:
        with pytest.raises(RpcError):
            batch.new_state("n", "t", ["v1"], batch_id="../settings")

    def test_new_state_accepts_a_safe_batch_id(self) -> None:
        assert batch.new_state("n", "t", ["v1"], batch_id="fixed-id")["id"] == "fixed-id"

    def test_generated_ids_round_trip_unchanged(self, store: batch.BatchStore) -> None:
        """The guard costs no feature: create/load/update/status/delete still work."""
        state = store.create("run", "tpl", ["v1", "v2"])
        batch_id = state["id"]
        assert store.load(batch_id) is not None
        assert store.update_item(batch_id, "v1", status="done")["items"][0]["status"] == "done"
        assert store.set_status(batch_id, "error")["status"] == "error"
        assert [s["id"] for s in store.list()] == [batch_id]
        assert store.delete(batch_id) is True
        assert store.load(batch_id) is None


class TestBatchRpcSurfaceRefusesTraversal:
    """The renderer-facing ``batch.*`` methods, not just the store."""

    @staticmethod
    def _service(data_dir: Path) -> batch.Batch:
        return batch.Batch(batch.BatchStore(data_dir / "batches"))

    @pytest.mark.parametrize("method", ["status", "delete", "start", "resume", "plan"])
    def test_traversal_id_is_refused(self, data_dir: Path, method: str) -> None:
        service = self._service(data_dir)
        with pytest.raises(RpcError):
            getattr(service, method)({"id": "../settings"}, _ctx(_registry()))
        assert (data_dir / "settings.json").exists()


# =========================================================================== #
# 2. convert — output confinement (no arbitrary ffmpeg `-y` overwrite)
# =========================================================================== #
class TestConvertOutputConfinement:
    @pytest.fixture(autouse=True)
    def _pin_data_root(self, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pin the app data root to ``<tmp>/data`` so the refusals never depend on
        the ambient ``MEDIA_STUDIO_CONFIG_DIR`` of the machine running the suite."""
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(data_dir))

    def test_out_outside_the_source_dir_is_refused(self, bins: dict[str, str], source: Path, tmp_path: Path) -> None:
        run = _RunRecorder()
        victim = tmp_path / "home" / ".ssh" / "authorized_keys"
        with pytest.raises(PathTraversalError) as exc:
            convert.convert_one(
                {"path": str(source), "out": str(victim), "options": {"container": "mp4"}},
                settings=bins,
                run=run,
                probe=_probe,
            )
        assert "outside the source directory and the app data root" in str(exc.value)
        assert run.calls == [], "ffmpeg was invoked with an unconfined destination"

    def test_out_traversal_out_of_the_source_dir_is_refused(self, bins: dict[str, str], source: Path) -> None:
        run = _RunRecorder()
        with pytest.raises(PathTraversalError):
            convert.convert_one(
                {"path": str(source), "out": str(source.parent / ".." / "escaped.mp4")},
                settings=bins,
                run=run,
                probe=_probe,
            )
        assert run.calls == []

    def test_out_inside_the_source_dir_is_allowed(self, bins: dict[str, str], source: Path) -> None:
        run = _RunRecorder()
        chosen = source.parent / "chosen.mp4"
        out = convert.convert_one(
            {"path": str(source), "out": str(chosen), "options": {"container": "mp4"}},
            settings=bins,
            run=run,
            probe=_probe,
        )
        assert out == str(chosen)
        assert run.calls[0][-1] == str(chosen)

    def test_out_inside_the_data_root_is_allowed(
        self, bins: dict[str, str], source: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(data_dir))
        run = _RunRecorder()
        exported = data_dir / "exports" / "final.mp4"
        out = convert.convert_one(
            {"path": str(source), "out": str(exported), "options": {"container": "mp4"}},
            settings=bins,
            run=run,
            probe=_probe,
        )
        assert out == str(exported)
        assert run.calls[0][-1] == str(exported)

    def test_derived_default_still_lands_next_to_the_source(self, bins: dict[str, str], source: Path) -> None:
        run = _RunRecorder()
        out = convert.convert_one(
            {"path": str(source), "options": {"container": "mp4"}},
            settings=bins,
            run=run,
            probe=_probe,
        )
        assert Path(out) == source.parent / "in.mp4"
        assert run.calls[0][-1] == str(source.parent / "in.mp4")

    def test_batch_item_out_is_confined_too(self, bins: dict[str, str], source: Path, tmp_path: Path) -> None:
        run = _RunRecorder()
        with pytest.raises(PathTraversalError):
            convert.convert_batch(
                [{"path": str(source), "out": str(tmp_path / "elsewhere" / "boom.mp4")}],
                settings=bins,
                run=run,
                probe=_probe,
            )
        assert run.calls == []


# =========================================================================== #
# 3. convert — media-input guard (no protocol / UNC input reaches ffmpeg)
# =========================================================================== #
class TestConvertInputGuard:
    @pytest.mark.parametrize(
        "bad_input",
        [
            "http://169.254.169.254/latest/meta-data",
            "https://evil.example/x.mp4",
            "ftp://host/x.mp4",
            "concat:/etc/passwd|/etc/shadow",
            "file:///etc/passwd",
            "\\\\attacker.example\\share\\a.mp4",
            "//attacker.example/share/a.mp4",
        ],
    )
    def test_renderer_supplied_protocol_input_is_refused(self, bins: dict[str, str], bad_input: str) -> None:
        run = _RunRecorder()
        with pytest.raises(UnsafeMediaInputError):
            convert.convert_one(
                {"path": bad_input, "options": {"container": "mp4"}},
                settings=bins,
                run=run,
                probe=_probe,
            )
        assert run.calls == [], "a non-local media input reached the ffmpeg argv"

    def test_resolver_supplied_protocol_input_is_refused(self, bins: dict[str, str]) -> None:
        run = _RunRecorder()
        with pytest.raises(UnsafeMediaInputError):
            convert.convert_one(
                {"videoId": "v1", "options": {"container": "mp4"}},
                settings=bins,
                resolver={"v1": "http://evil.example/x.mp4"}.get,
                run=run,
                probe=_probe,
            )
        assert run.calls == []

    def test_local_source_still_converts(self, bins: dict[str, str], source: Path) -> None:
        run = _RunRecorder()
        out = convert.convert_one(
            {"path": str(source), "options": {"container": "mkv"}},
            settings=bins,
            run=run,
            probe=_probe,
        )
        assert Path(out).suffix == ".mkv"
        assert str(source) in run.calls[0]
