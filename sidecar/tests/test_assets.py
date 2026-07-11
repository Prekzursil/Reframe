"""Tests for the assets subsystem (U4): manifest registry, download manager
(resume math / disk preflight / atomic finalize / sha), env-installer argv,
hf installer seam, and the assets.* RPC handlers.

ALL network/subprocess/heavy seams are mocked: a fake httpx-shaped client, a
recording run_cmd, an injected disk_usage, a fake hf_fetch. No real download,
no real pip, no huggingface_hub import.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from media_studio import protocol
from media_studio.assets import manifest
from media_studio.assets import rpc as assets_rpc
from media_studio.assets.manager import (
    DISK_MARGIN_MB,
    GET_PIP_SHA256,
    GET_PIP_URL,
    MB,
    PINNED_PIP,
    AssetError,
    AssetManager,
    build_env_install_argvs,
    env_sentinel_path,
    file_size_ok,
    hf_repo_dir,
    parse_total_bytes,
    part_path,
    preflight_disk,
    resume_headers,
    resume_offset,
    sha256_file,
)
from media_studio.jobs import JobCancelled
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fixtures / fakes
# --------------------------------------------------------------------------- #
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


def big_free_usage(_path: str) -> SimpleNamespace:
    return SimpleNamespace(total=10**13, used=0, free=10**13)


def make_manager(
    tmp_path: Path,
    *,
    client: FakeClient | None = None,
    run_cmd=None,
    hf_fetch=None,
    settings: dict[str, Any] | None = None,
    env_vars: dict[str, str] | None = None,
    usage=big_free_usage,
    python_exe: str = "C:/embed py/python.exe",
    get_pip_sha256: str | None = None,
) -> AssetManager:
    return AssetManager(
        root=tmp_path,
        settings_provider=(lambda: settings) if settings is not None else None,
        http_factory=(lambda: client) if client is not None else None,
        run_cmd=run_cmd,
        hf_fetch=hf_fetch,
        python_exe=python_exe,
        usage=usage,
        env_vars=env_vars if env_vars is not None else {},
        get_pip_sha256=get_pip_sha256,
    )


# F3c: installer='download' entries now REQUIRE a sha256 pin at registration
# (manifest.AssetEntry.__post_init__). The helper defaults to a valid 64-hex
# placeholder so the many manager tests that don't care about integrity keep
# building entries; tests that exercise the verify path still pass an explicit one.
_DUMMY_SHA256 = "a" * 64


def sha_of(*parts: bytes) -> str:
    """sha256 of concatenated body parts (lets download tests pin the served bytes)."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


def download_entry(name="tiny-model", *, sha256=_DUMMY_SHA256, size_mb=0.001, dest=None):
    return manifest.register_asset(
        name=name,
        kind="model",
        size_mb=size_mb,
        dest=dest or f"models/{name}.bin",
        url=f"https://example.test/{name}.bin",
        sha256=sha256,
    )


# --------------------------------------------------------------------------- #
# manifest: registration API + day-1 entries
# --------------------------------------------------------------------------- #
class TestManifest:
    def test_register_asset_kwargs_and_lookup(self):
        entry = manifest.register_asset(
            name="yolo-weights",
            kind="tool",
            size_mb=12,
            dest="tools/yolo.pt",
            url="https://example.test/yolo.pt",
            sha256=_DUMMY_SHA256,
        )
        assert manifest.get_asset("yolo-weights") is entry
        assert entry in manifest.all_assets()

    def test_register_accepts_prebuilt_entry(self):
        entry = manifest.AssetEntry(
            name="prebuilt",
            kind="model",
            size_mb=1,
            dest="models/p.bin",
            url="https://example.test/p.bin",
            sha256=_DUMMY_SHA256,
        )
        assert manifest.register_asset(entry) is entry
        assert manifest.get_asset("prebuilt") == entry

    def test_duplicate_identical_registration_is_noop(self):
        kwargs = {
            "name": "dup",
            "kind": "model",
            "size_mb": 1,
            "dest": "models/dup.bin",
            "url": "https://example.test/dup.bin",
            "sha256": _DUMMY_SHA256,
        }
        first = manifest.register_asset(**kwargs)
        second = manifest.register_asset(**kwargs)
        assert first is second

    def test_conflicting_duplicate_raises(self):
        download_entry("conflict")
        with pytest.raises(ValueError, match="conflicting"):
            manifest.register_asset(
                name="conflict",
                kind="tool",
                size_mb=2,
                dest="tools/other.bin",
                url="https://example.test/other.bin",
                sha256=_DUMMY_SHA256,
            )

    def test_entry_and_kwargs_together_rejected(self):
        entry = manifest.get_asset(manifest.QWEN_ASSET_NAME)
        with pytest.raises(ValueError, match="not both"):
            manifest.register_asset(entry, name="x")

    @pytest.mark.parametrize(
        "bad",
        [
            {"name": "", "kind": "model", "size_mb": 1, "dest": "d", "url": "u"},
            {"name": "x", "kind": "weights", "size_mb": 1, "dest": "d", "url": "u"},
            {"name": "x", "kind": "model", "size_mb": -1, "dest": "d", "url": "u"},
            {"name": "x", "kind": "model", "size_mb": 1, "dest": "d", "url": "u", "installer": "curl"},
            # download installer requires url + dest
            {"name": "x", "kind": "model", "size_mb": 1, "dest": "d"},
            {"name": "x", "kind": "model", "size_mb": 1, "url": "u"},
            # hf installer requires hf_repo
            {"name": "x", "kind": "model", "size_mb": 1, "installer": "hf"},
            # env installer requires dest + requirements
            {"name": "x", "kind": "env", "size_mb": 1, "installer": "env", "dest": "envs/x"},
        ],
    )
    def test_invalid_entries_raise(self, bad):
        with pytest.raises(ValueError):
            manifest.AssetEntry(**bad)

    def test_env_requirements_must_be_pinned(self):
        with pytest.raises(ValueError, match="not pinned"):
            manifest.AssetEntry(
                name="loose-env",
                kind="env",
                size_mb=10,
                dest="envs/loose",
                installer="env",
                requirements=("soundfile",),
            )
        pinned = manifest.AssetEntry(
            name="pinned-env",
            kind="env",
            size_mb=10,
            dest="envs/pinned",
            installer="env",
            requirements=["soundfile==0.12.1"],
        )
        assert pinned.requirements == ("soundfile==0.12.1",)

    # --- F3c: integrity + revision pinning enforcement --------------------- #
    def test_download_entry_requires_sha256(self):
        # installer='download' WITHOUT a sha256 is rejected at registration.
        with pytest.raises(ValueError, match="installer='download' requires a sha256"):
            manifest.AssetEntry(
                name="unpinned-dl",
                kind="model",
                size_mb=1,
                dest="models/x.bin",
                url="https://example.test/x.bin",
            )

    @pytest.mark.parametrize("bad_sha", ["", "abc", "z" * 64, "A" * 63, "a" * 65, "  " + "a" * 62 + "  "])
    def test_download_sha256_must_be_64_hex(self, bad_sha):
        with pytest.raises(ValueError, match="sha256"):
            manifest.AssetEntry(
                name="badsha-dl",
                kind="model",
                size_mb=1,
                dest="models/x.bin",
                url="https://example.test/x.bin",
                sha256=bad_sha,
            )

    def test_download_sha256_accepts_uppercase_hex(self):
        entry = manifest.AssetEntry(
            name="upper-dl",
            kind="model",
            size_mb=1,
            dest="models/x.bin",
            url="https://example.test/x.bin",
            sha256="A" * 64,
        )
        assert entry.sha256 == "A" * 64

    def test_hf_resolve_download_url_must_pin_commit_hash(self):
        # An HF resolve URL on a branch/tag ref (not a 40-hex commit) is rejected.
        with pytest.raises(ValueError, match="commit hash"):
            manifest.AssetEntry(
                name="hf-main-dl",
                kind="model",
                size_mb=1,
                dest="models/x.gguf",
                url="https://huggingface.co/org/repo/resolve/main/x.gguf",
                sha256="a" * 64,
            )

    def test_hf_resolve_download_url_with_commit_hash_ok(self):
        commit = "bc640142c66e1fdd12af0bd68f40445458f3869b"
        entry = manifest.AssetEntry(
            name="hf-pinned-dl",
            kind="model",
            size_mb=1,
            dest="models/x.gguf",
            url=f"https://huggingface.co/org/repo/resolve/{commit}/x.gguf",
            sha256="a" * 64,
        )
        assert commit in entry.url

    def test_non_hf_download_url_needs_no_commit_revision(self):
        # A plain (non-HF) pinned URL is fine with just a sha256 (no resolve/<ref>).
        entry = manifest.AssetEntry(
            name="gh-dl",
            kind="model",
            size_mb=1,
            dest="models/x.onnx",
            url="https://github.com/org/repo/raw/abcdef/x.onnx",
            sha256="a" * 64,
        )
        assert entry.installer == "download"

    def test_hf_installer_requires_pinned_revision(self):
        # installer='hf' WITHOUT an hf_revision is rejected (no floating 'main').
        with pytest.raises(ValueError, match="hf_revision"):
            manifest.AssetEntry(
                name="hf-no-rev",
                kind="model",
                size_mb=1,
                installer="hf",
                hf_repo="org/repo",
            )

    @pytest.mark.parametrize("bad_rev", ["main", "v1.0", "z" * 40, "a" * 39, "a" * 41])
    def test_hf_installer_revision_must_be_commit_hash(self, bad_rev):
        with pytest.raises(ValueError, match="commit hash"):
            manifest.AssetEntry(
                name="hf-bad-rev",
                kind="model",
                size_mb=1,
                installer="hf",
                hf_repo="org/repo",
                hf_revision=bad_rev,
            )

    def test_hf_installer_with_commit_revision_ok(self):
        entry = manifest.AssetEntry(
            name="hf-ok-rev",
            kind="model",
            size_mb=1,
            installer="hf",
            hf_repo="org/repo",
            hf_revision="0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        )
        assert entry.hf_revision == "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"

    def test_python_kind_defaults_to_host(self):
        entry = manifest.AssetEntry(
            name="host-env",
            kind="env",
            size_mb=10,
            dest="envs/host",
            installer="env",
            requirements=["soundfile==0.12.1"],
        )
        assert entry.python_kind == "host"

    def test_invalid_python_kind_rejected(self):
        with pytest.raises(ValueError, match="python_kind must be one of"):
            manifest.AssetEntry(
                name="bad-kind-env",
                kind="env",
                size_mb=10,
                dest="envs/bad",
                installer="env",
                requirements=["soundfile==0.12.1"],
                python_kind="py99",
            )

    def test_day1_whisper_entry(self):
        entry = manifest.get_asset(manifest.WHISPER_ASSET_NAME)
        assert entry is not None
        assert entry.kind == "model"
        assert entry.installer == "hf"
        assert entry.hf_repo == "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
        assert entry.size_mb > 0
        # F3c: the hf revision is a pinned 40-hex commit, never floating 'main'.
        assert entry.hf_revision and len(entry.hf_revision) == 40
        assert entry.hf_revision != "main"

    def test_day1_qwen_entry(self):
        entry = manifest.get_asset(manifest.QWEN_ASSET_NAME)
        assert entry is not None
        assert entry.kind == "model"
        assert entry.installer == "download"
        assert entry.url and entry.url.endswith(".gguf")
        assert entry.dest == "models/qwen3-4b.gguf"
        assert entry.detect is manifest.detect_existing_gguf
        # F3c: a real 64-hex sha256 + an HF resolve URL pinned to a commit hash.
        assert entry.sha256 and len(entry.sha256) == 64
        assert "/resolve/main/" not in entry.url

    def test_day1_embedder_entry(self):
        # WU-A3 AC-(c): the small local embedder is registered with a non-empty
        # sha + installer, retrievable via get_asset.
        entry = manifest.get_asset(manifest.EMBEDDER_ASSET_NAME)
        assert entry is not None
        assert entry.kind == "model"
        assert entry.installer == "download"
        assert entry.sha256  # non-empty integrity pin (AC-(c))
        assert len(entry.sha256) == 64  # a real hex sha256
        assert entry.url and entry.url.endswith(".onnx")
        assert entry.dest == "models/all-minilm-l6-v2.onnx"
        assert entry.size_mb > 0

    def test_embedder_entry_is_listed_in_all_assets(self):
        names = {a.name for a in manifest.all_assets()}
        assert manifest.EMBEDDER_ASSET_NAME in names

    def test_phase8_optional_entries_are_sha_pinned(self):
        # F3c: the optional emotion + OCR download entries each carry a 64-hex
        # sha256 (they EXECUTE no code, but the file is integrity-verified).
        for name in (manifest.HSEMOTION_ASSET_NAME, manifest.RAPIDOCR_ASSET_NAME):
            entry = manifest.get_asset(name)
            assert entry is not None, name
            assert entry.installer == "download"
            assert entry.sha256 and len(entry.sha256) == 64, name

    def test_lightasd_weights_are_sha_pinned_and_commit_pinned(self):
        # R1: the vendored S3FD + LR-ASD active-speaker weights enter the manifest
        # as sha256-pinned download assets, each URL carrying a 40-hex commit (the
        # S3FD via an HF resolve commit, the ASD via a GitHub-raw commit) — never a
        # moving branch/tag (F3c). The ASD weight is LR-ASD (the Light-ASD successor).
        s3fd = manifest.get_asset(manifest.LIGHTASD_S3FD_ASSET_NAME)
        asd = manifest.get_asset(manifest.LIGHTASD_ASD_ASSET_NAME)
        for entry in (s3fd, asd):
            assert entry is not None
            assert entry.installer == "download"
            assert entry.sha256 and len(entry.sha256) == 64
            assert entry.size_mb > 0
        assert "huggingface.co" in s3fd.url and "/resolve/main/" not in s3fd.url
        assert s3fd.url.endswith("sfd_face.pth")
        assert "github.com/Junhua-Liao/LR-ASD" in asd.url
        assert manifest.LIGHTASD_ASD_COMMIT in asd.url
        assert asd.url.endswith("finetuning_TalkSet.model")
        names = {a.name for a in manifest.all_assets()}
        assert {manifest.LIGHTASD_S3FD_ASSET_NAME, manifest.LIGHTASD_ASD_ASSET_NAME} <= names

    def test_yunet_entry_is_sha_pinned_and_commit_pinned(self):
        # v1.2.0 WU1: the YuNet face detector (claudeshorts speaker tracking, MIT)
        # enters the manifest as a sha256-pinned download whose HF resolve URL
        # carries a 40-hex commit hash (never a moving branch/tag — F3c), pointing
        # at the OFFICIAL OpenCV mirror's ONNX file.
        entry = manifest.get_asset(manifest.YUNET_ASSET_NAME)
        assert entry is not None
        assert entry.kind == "model"
        assert entry.installer == "download"
        assert entry.sha256 and len(entry.sha256) == 64
        assert entry.size_mb > 0
        assert "huggingface.co/opencv/face_detection_yunet" in entry.url
        assert "/resolve/main/" not in entry.url
        assert manifest.YUNET_COMMIT in entry.url
        assert entry.url.endswith(".onnx")
        assert entry.dest.endswith(".onnx")
        # MIT license surfaced in the human label (task requirement).
        assert "MIT" in entry.label
        assert manifest.YUNET_ASSET_NAME in {a.name for a in manifest.all_assets()}

    def test_yunet_size_mb_keeps_the_small_onnx_detectable_as_installed(self):
        # The ONNX is only ~0.23 MB; size_mb must stay below the manager's
        # file_size_ok floor (0.5 * size_mb) so a fully-downloaded file is not
        # mistaken for a truncated leftover.
        from media_studio.assets.manager import MB, MIN_SIZE_FRACTION

        entry = manifest.get_asset(manifest.YUNET_ASSET_NAME)
        actual_bytes = 232_589  # the real file size (verified by download)
        floor = int(entry.size_mb * MB * MIN_SIZE_FRACTION)
        assert floor <= actual_bytes

    def test_edgetam_entry_is_sha_pinned_and_commit_pinned(self):
        # v1.2.0 WU2: the EdgeTAM occlusion-robust video tracker (opt-in reframe
        # backend, Apache-2.0) enters the manifest as a sha256-pinned download
        # whose GitHub-raw URL carries a 40-hex commit hash (never a moving
        # branch/tag — F3c), pointing at the checkpoint committed in the upstream
        # facebookresearch/EdgeTAM repo.
        entry = manifest.get_asset(manifest.EDGETAM_ASSET_NAME)
        assert entry is not None
        assert entry.kind == "model"
        assert entry.installer == "download"
        assert entry.sha256 and len(entry.sha256) == 64
        assert entry.size_mb > 0
        assert "github.com/facebookresearch/EdgeTAM" in entry.url
        assert manifest.EDGETAM_COMMIT in entry.url
        assert "/raw/main/" not in entry.url
        assert entry.url.endswith("edgetam.pt")
        assert entry.dest.endswith(".pt")
        # Apache-2.0 license surfaced in the human label (WU2 requirement 3).
        assert "Apache-2.0" in entry.label
        assert manifest.EDGETAM_ASSET_NAME in {a.name for a in manifest.all_assets()}

    def test_edgetam_size_mb_keeps_the_checkpoint_detectable_as_installed(self):
        # The checkpoint is ~53.5 MB; size_mb must stay below the manager's
        # file_size_ok floor (0.5 * size_mb) so a fully-downloaded file is not
        # mistaken for a truncated leftover.
        from media_studio.assets.manager import MB, MIN_SIZE_FRACTION

        entry = manifest.get_asset(manifest.EDGETAM_ASSET_NAME)
        actual_bytes = 56_116_523  # the real file size (verified by download)
        floor = int(entry.size_mb * MB * MIN_SIZE_FRACTION)
        assert floor <= actual_bytes

    def test_rapidocr_url_is_a_live_pinned_hf_commit(self):
        # F3c re-point: the old GitHub-release URL 404'd; it now resolves an HF
        # commit-pinned ONNX (the resolve URL must carry a commit hash, asserted
        # by AssetEntry, and the file ends in .onnx).
        entry = manifest.get_asset(manifest.RAPIDOCR_ASSET_NAME)
        assert entry is not None
        assert "huggingface.co" in entry.url
        assert "/resolve/main/" not in entry.url
        assert entry.url.endswith(".onnx")

    def test_every_download_asset_in_registry_is_sha_pinned(self):
        # F3c invariant: NO installer='download' entry may ship without a sha256.
        for entry in manifest.all_assets():
            if entry.installer == "download":
                assert entry.sha256 and len(entry.sha256) == 64, entry.name

    def test_qwen_detect_existing_gguf(self, tmp_path):
        gguf = tmp_path / "anywhere" / "my-qwen.gguf"
        gguf.parent.mkdir(parents=True)
        gguf.write_bytes(b"GGUF")
        assert manifest.detect_existing_gguf({"ggufPath": str(gguf)}) == str(gguf)
        # missing explicit path -> None
        assert manifest.detect_existing_gguf({"ggufPath": str(tmp_path / "no.gguf")}) is None
        # modelsDir + default name
        models_dir = tmp_path / "models dir with spaces"
        models_dir.mkdir()
        (models_dir / "qwen3-4b.gguf").write_bytes(b"GGUF")
        found = manifest.detect_existing_gguf({"modelsDir": str(models_dir)})
        assert found == str(models_dir / "qwen3-4b.gguf")
        assert manifest.detect_existing_gguf({}) is None


# --------------------------------------------------------------------------- #
# pure helpers: resume math, totals, preflight, size check, env argv
# --------------------------------------------------------------------------- #
class TestResumeMath:
    def test_resume_headers_fresh(self):
        assert resume_headers(0) == {}

    def test_resume_headers_partial(self):
        assert resume_headers(1234) == {"Range": "bytes=1234-"}

    def test_resume_offset_missing_part(self, tmp_path):
        assert resume_offset(tmp_path / "nope.bin.part") == 0

    def test_resume_offset_existing_part(self, tmp_path):
        part = tmp_path / "x.bin.part"
        part.write_bytes(b"abcdef")
        assert resume_offset(part) == 6

    def test_part_path_beside_dest(self, tmp_path):
        dest = tmp_path / "models" / "m.gguf"
        assert part_path(dest) == tmp_path / "models" / "m.gguf.part"

    def test_parse_total_206_content_range(self):
        headers = {"Content-Range": "bytes 100-999/5000"}
        assert parse_total_bytes(206, headers, 100) == 5000

    def test_parse_total_206_star_falls_back_to_offset_plus_length(self):
        headers = {"Content-Range": "bytes 100-999/*", "Content-Length": "900"}
        assert parse_total_bytes(206, headers, 100) == 1000

    def test_parse_total_200_content_length(self):
        assert parse_total_bytes(200, {"Content-Length": "777"}, 0) == 777
        assert parse_total_bytes(200, {"content-length": "777"}, 0) == 777

    def test_parse_total_unknown(self):
        assert parse_total_bytes(200, {}, 0) is None
        assert parse_total_bytes(206, {}, 5) is None


class TestPreflight:
    def test_low_disk_raises(self, tmp_path):
        low = lambda _p: SimpleNamespace(total=10**12, used=0, free=1 * MB)  # noqa: E731
        with pytest.raises(AssetError, match="insufficient disk"):
            preflight_disk(tmp_path, 100, usage=low)

    def test_enough_disk_passes(self, tmp_path):
        preflight_disk(tmp_path, 100, usage=big_free_usage)

    def test_walks_to_existing_ancestor(self, tmp_path):
        seen: list[str] = []

        def usage(path: str) -> SimpleNamespace:
            seen.append(path)
            return SimpleNamespace(total=0, used=0, free=10**13)

        preflight_disk(tmp_path / "not" / "yet" / "made", 1, usage=usage)
        assert seen == [str(tmp_path)]

    def test_margin_counts(self, tmp_path):
        # free covers the asset but NOT the margin -> blocked.
        free = int((10 + DISK_MARGIN_MB / 2) * MB)
        usage = lambda _p: SimpleNamespace(total=0, used=0, free=free)  # noqa: E731
        with pytest.raises(AssetError):
            preflight_disk(tmp_path, 10, usage=usage)


class TestFileSizeOk:
    def test_missing_and_empty_files(self, tmp_path):
        assert file_size_ok(tmp_path / "missing.bin", 1) is False
        empty = tmp_path / "empty.bin"
        empty.write_bytes(b"")
        assert file_size_ok(empty, 0) is False

    def test_truncated_vs_plausible(self, tmp_path):
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * (1 * MB))
        assert file_size_ok(f, 10) is False  # 1MB of a declared 10MB: truncated
        assert file_size_ok(f, 1) is True  # full declared size
        assert file_size_ok(f, 0) is True  # unknown size: existence is enough


class TestEnvInstallArgv:
    def test_two_pinned_argv_steps_no_shell(self, tmp_path):
        env_dir = tmp_path / "envs" / "chatterbox env"
        get_pip = tmp_path / "tools" / "get-pip.py"
        reqs = ("torch==2.4.1", "chatterbox-tts==0.1.2")
        steps = build_env_install_argvs("C:/py 3.12/python.exe", get_pip, env_dir, reqs)

        assert len(steps) == 2
        for step in steps:
            assert isinstance(step["argv"], list)
            assert all(isinstance(a, str) for a in step["argv"])

        step1, step2 = steps
        assert step1["argv"][0] == "C:/py 3.12/python.exe"
        assert step1["argv"][1] == str(get_pip)
        assert PINNED_PIP in step1["argv"]  # pip itself is pinned (A6.5)
        assert "--target" in step1["argv"]
        assert step1["argv"][step1["argv"].index("--target") + 1] == str(env_dir)
        assert step1["env"] == {}

        assert step2["argv"][:4] == ["C:/py 3.12/python.exe", "-m", "pip", "install"]
        assert step2["argv"][step2["argv"].index("--target") + 1] == str(env_dir)
        for req in reqs:
            assert req in step2["argv"]
        # step 2 imports the pip bootstrapped into the env dir itself (A7).
        assert step2["env"] == {"PYTHONPATH": str(env_dir)}

    def test_argvs_carry_no_loose_requirements(self, tmp_path):
        steps = build_env_install_argvs("py", tmp_path / "gp.py", tmp_path / "e", ("numpy==2.1.0",))
        joined = [a for s in steps for a in s["argv"]]
        assert "numpy==2.1.0" in joined


# --------------------------------------------------------------------------- #
# download machinery (fake httpx client)
# --------------------------------------------------------------------------- #
class TestDownload:
    def test_fresh_download_atomic_and_no_range(self, tmp_path):
        body = [b"hello ", b"world"]
        client = FakeClient([FakeResponse(200, {"Content-Length": "11"}, chunks=body)])
        mgr = make_manager(tmp_path, client=client)
        entry = download_entry("fresh", sha256=sha_of(*body))
        dest = mgr.resolve_dest(entry)

        fracs: list[float] = []
        mgr._install(entry, on_frac=lambda f, m="": fracs.append(f), should_cancel=lambda: False)

        assert dest.read_bytes() == b"hello world"
        assert not part_path(dest).exists()  # atomic temp+rename cleaned up
        assert "Range" not in client.requests[0]["headers"]
        assert fracs[-1] == 1.0
        assert all(b <= a for a, b in zip(fracs[1:], fracs, strict=False))  # non-decreasing

    def test_resume_sends_range_and_appends(self, tmp_path):
        # finalize verifies the FULL file (existing partial b"1234" + appended chunks).
        mgr_entry = download_entry("resume", sha256=sha_of(b"1234567890"))
        client = FakeClient(
            [
                FakeResponse(
                    206,
                    {"Content-Range": "bytes 4-9/10", "Content-Length": "6"},
                    chunks=[b"56", b"7890"],
                )
            ]
        )
        mgr = make_manager(tmp_path, client=client)
        dest = mgr.resolve_dest(mgr_entry)
        dest.parent.mkdir(parents=True)
        part_path(dest).write_bytes(b"1234")  # existing partial

        mgr._install(mgr_entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

        assert client.requests[0]["headers"]["Range"] == "bytes=4-"
        assert dest.read_bytes() == b"1234567890"
        assert not part_path(dest).exists()

    def test_server_ignoring_range_restarts_clean(self, tmp_path):
        entry = download_entry("restart", sha256=sha_of(b"fullbody"))
        client = FakeClient([FakeResponse(200, {"Content-Length": "8"}, chunks=[b"fullbody"])])
        mgr = make_manager(tmp_path, client=client)
        dest = mgr.resolve_dest(entry)
        dest.parent.mkdir(parents=True)
        part_path(dest).write_bytes(b"stalepartial")

        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

        # 200 means the WHOLE body: the stale partial must not survive in front.
        assert dest.read_bytes() == b"fullbody"

    def test_416_with_full_part_finalizes(self, tmp_path):
        entry = download_entry("complete", sha256=sha_of(b"already-all-here"))
        client = FakeClient([FakeResponse(416, {}, chunks=[])])
        mgr = make_manager(tmp_path, client=client)
        dest = mgr.resolve_dest(entry)
        dest.parent.mkdir(parents=True)
        part_path(dest).write_bytes(b"already-all-here")

        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert dest.read_bytes() == b"already-all-here"

    def test_http_error_raises_asset_error(self, tmp_path):
        entry = download_entry("failing")
        client = FakeClient([FakeResponse(503, {}, chunks=[])])
        mgr = make_manager(tmp_path, client=client)
        with pytest.raises(AssetError, match="HTTP 503"):
            mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

    def test_sha_mismatch_removes_part_and_raises(self, tmp_path):
        entry = download_entry("shabad", sha256="0" * 64)
        client = FakeClient([FakeResponse(200, {"Content-Length": "4"}, chunks=[b"data"])])
        mgr = make_manager(tmp_path, client=client)
        dest = mgr.resolve_dest(entry)
        with pytest.raises(AssetError, match="sha256 mismatch"):
            mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert not dest.exists()
        assert not part_path(dest).exists()  # corrupt part purged for clean retry

    def test_sha_match_passes(self, tmp_path):
        import hashlib

        good = hashlib.sha256(b"data").hexdigest()
        entry = download_entry("shagood", sha256=good.upper())  # case-insensitive
        client = FakeClient([FakeResponse(200, {"Content-Length": "4"}, chunks=[b"data"])])
        mgr = make_manager(tmp_path, client=client)
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert mgr.resolve_dest(entry).read_bytes() == b"data"

    def test_cancel_mid_download_keeps_part_for_resume(self, tmp_path):
        entry = download_entry("cancelme")
        flag = {"cancel": False}

        def after_first_chunk(_chunk):
            flag["cancel"] = True

        client = FakeClient(
            [
                FakeResponse(
                    200,
                    {"Content-Length": "8"},
                    chunks=[b"head", b"tail"],
                    on_chunk=after_first_chunk,
                )
            ]
        )
        mgr = make_manager(tmp_path, client=client)
        dest = mgr.resolve_dest(entry)
        with pytest.raises(JobCancelled):
            mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: flag["cancel"])
        assert not dest.exists()
        assert part_path(dest).exists()  # resumable remainder kept

    def test_sha256_file_helper(self, tmp_path):
        import hashlib

        f = tmp_path / "h.bin"
        f.write_bytes(b"abc123")
        assert sha256_file(f) == hashlib.sha256(b"abc123").hexdigest()


# --------------------------------------------------------------------------- #
# installed detection + assets.list view
# --------------------------------------------------------------------------- #
class TestInstalledAndList:
    def test_info_shape_matches_a3(self, tmp_path):
        mgr = make_manager(tmp_path)
        entry = download_entry("shape")
        info = mgr.info(entry)
        assert set(info.keys()) == {"name", "kind", "sizeMB", "installed", "dest"}
        assert info["name"] == "shape"
        assert info["kind"] == "model"
        assert info["sizeMB"] == entry.size_mb
        assert info["installed"] is False
        assert info["dest"] == str(tmp_path / "models" / "shape.bin")

    def test_installed_requires_exists_and_size_ok(self, tmp_path):
        mgr = make_manager(tmp_path)
        entry = download_entry("sized", size_mb=10)
        dest = mgr.resolve_dest(entry)
        assert mgr.installed_path(entry) is None  # missing
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"x" * (1 * MB))
        assert mgr.installed_path(entry) is None  # truncated (1MB of 10MB)
        dest.write_bytes(b"x" * (10 * MB))
        assert mgr.installed_path(entry) == str(dest)

    def test_detect_probe_marks_installed(self, tmp_path):
        gguf = tmp_path / "elsewhere" / "qwen3-4b.gguf"
        gguf.parent.mkdir(parents=True)
        gguf.write_bytes(b"GGUF")
        mgr = make_manager(tmp_path, settings={"ggufPath": str(gguf)})
        entry = manifest.get_asset(manifest.QWEN_ASSET_NAME)
        assert mgr.installed_path(entry) == str(gguf)
        info = mgr.info(entry)
        assert info["installed"] is True
        assert info["dest"] == str(gguf)

    def test_hf_installed_via_cache_snapshot(self, tmp_path):
        hf_home = tmp_path / "hf home"
        env_vars = {"HF_HOME": str(hf_home)}
        mgr = make_manager(tmp_path, env_vars=env_vars)
        entry = manifest.get_asset(manifest.WHISPER_ASSET_NAME)
        assert mgr.installed_path(entry) is None
        repo = hf_repo_dir(entry.hf_repo, env_vars)
        snap = repo / "snapshots" / "abc123"
        snap.mkdir(parents=True)
        (snap / "model.bin").write_bytes(b"weights")
        assert mgr.installed_path(entry) == str(repo)

    def test_hf_cache_env_precedence(self, tmp_path):
        from media_studio.assets.manager import hf_cache_dir

        assert hf_cache_dir({"HF_HUB_CACHE": str(tmp_path / "hub")}) == tmp_path / "hub"
        assert hf_cache_dir({"HF_HOME": str(tmp_path / "home")}) == tmp_path / "home" / "hub"
        default = hf_cache_dir({})
        assert default.parts[-2:] == ("huggingface", "hub")

    def test_list_assets_covers_manifest(self, tmp_path):
        mgr = make_manager(tmp_path)
        names = [a["name"] for a in mgr.list_assets()]
        assert manifest.WHISPER_ASSET_NAME in names
        assert manifest.QWEN_ASSET_NAME in names

    def test_settings_provider_failure_is_nonfatal(self, tmp_path):
        def boom():
            raise RuntimeError("no settings")

        mgr = AssetManager(root=tmp_path, settings_provider=boom, env_vars={})
        entry = manifest.get_asset(manifest.QWEN_ASSET_NAME)
        assert mgr.installed_path(entry) is None  # falls back to {}


# --------------------------------------------------------------------------- #
# env installer (recording run_cmd; no real subprocess)
# --------------------------------------------------------------------------- #
def env_entry(name="tts-env", reqs=("kokoro-onnx==0.4.9", "onnxruntime==1.20.1")):
    return manifest.register_asset(
        name=name,
        kind="env",
        size_mb=300,
        dest=f"envs/{name}",
        installer="env",
        requirements=reqs,
    )


class TestEnvInstaller:
    def test_runs_pinned_argvs_and_writes_sentinel(self, tmp_path):
        calls: list[dict[str, Any]] = []

        def run_cmd(argv, extra_env=None):
            calls.append({"argv": list(argv), "env": dict(extra_env or {})})
            return 0, "ok"

        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")

        entry = env_entry()
        mgr = make_manager(tmp_path, run_cmd=run_cmd, python_exe="C:/embed/python.exe")
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

        env_dir = tmp_path / "envs" / "tts-env"
        assert len(calls) == 2
        assert calls[0]["argv"][0] == "C:/embed/python.exe"
        assert PINNED_PIP in calls[0]["argv"]
        assert calls[1]["argv"][1:4] == ["-m", "pip", "install"]
        assert "kokoro-onnx==0.4.9" in calls[1]["argv"]
        assert calls[1]["env"] == {"PYTHONPATH": str(env_dir)}
        # success sentinel records the pins; manager now reports installed.
        sentinel = env_sentinel_path(env_dir)
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        assert data["requirements"] == list(entry.requirements)
        assert mgr.installed_path(entry) == str(env_dir)

    def test_install_env_uses_chatterbox_interpreter_for_chatterbox_kind(self, tmp_path):
        calls: list[list[str]] = []

        def run_cmd(argv, extra_env=None):
            calls.append(list(argv))
            return 0, "ok"

        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
        entry = manifest.register_asset(
            name="chatter-env",
            kind="env",
            size_mb=300,
            dest="envs/chatter-env",
            installer="env",
            requirements=("torch==2.10.0+cu128",),
            python_kind="chatterbox",
        )
        mgr = AssetManager(
            root=tmp_path,
            run_cmd=run_cmd,
            python_exe="C:/host/python.exe",
            chatterbox_python=lambda: "C:/py314/python.exe",
            usage=big_free_usage,
            env_vars={},
        )
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert calls and calls[0][0] == "C:/py314/python.exe"
        assert calls[1][0] == "C:/py314/python.exe"

    def test_install_env_honors_cancel_during_steps(self, tmp_path):
        # 952->953: a mid-install cancel during the env-setup steps loop raises
        # JobCancelled (not a silent partial completion). The first step's run_cmd
        # flips cancel ON, so the loop is entered once, then aborts on the next step.
        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
        state = {"cancel": False}

        def run_cmd(argv, extra_env=None):
            state["cancel"] = True
            return 0, "ok"

        entry = manifest.register_asset(
            name="cancel-env",
            kind="env",
            size_mb=300,
            dest="envs/cancel-env",
            installer="env",
            requirements=("pkg==1.0",),
        )
        mgr = AssetManager(
            root=tmp_path,
            run_cmd=run_cmd,
            python_exe="C:/host/python.exe",
            usage=big_free_usage,
            env_vars={},
        )
        with pytest.raises(JobCancelled):
            mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: state["cancel"])

    def test_install_env_chatterbox_kind_falls_back_when_no_dedicated(self, tmp_path):
        calls: list[list[str]] = []

        def run_cmd(argv, extra_env=None):
            calls.append(list(argv))
            return 0, "ok"

        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
        entry = manifest.register_asset(
            name="chatter-env-fallback",
            kind="env",
            size_mb=300,
            dest="envs/chatter-env-fallback",
            installer="env",
            requirements=("torch==2.10.0+cu128",),
            python_kind="chatterbox",
        )
        mgr = AssetManager(
            root=tmp_path,
            run_cmd=run_cmd,
            python_exe="C:/host/python.exe",
            chatterbox_python=lambda: None,  # py3.14 embed not staged
            usage=big_free_usage,
            env_vars={},
        )
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert calls and calls[0][0] == "C:/host/python.exe"

    def test_install_env_host_kind_uses_host_interpreter(self, tmp_path):
        calls: list[list[str]] = []

        def run_cmd(argv, extra_env=None):
            calls.append(list(argv))
            return 0, "ok"

        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
        entry = env_entry("host-kind-env")  # default python_kind="host"
        # chatterbox_python would raise if consulted — a host-kind entry must not.
        mgr = AssetManager(
            root=tmp_path,
            run_cmd=run_cmd,
            python_exe="C:/host/python.exe",
            chatterbox_python=lambda: pytest.fail("host-kind must not consult chatterbox_python"),
            usage=big_free_usage,
            env_vars={},
        )
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert calls and calls[0][0] == "C:/host/python.exe"

    def test_install_env_chatterbox_kind_uses_default_resolver_when_unset(self, tmp_path, monkeypatch):
        # No chatterbox_python injected -> lazy-bind to chatterbox.default_chatterbox_python.
        import media_studio.features.tts.chatterbox as cbmod

        monkeypatch.setattr(cbmod, "default_chatterbox_python", lambda: "C:/auto314/python.exe")
        calls: list[list[str]] = []

        def run_cmd(argv, extra_env=None):
            calls.append(list(argv))
            return 0, "ok"

        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
        entry = manifest.register_asset(
            name="chatter-env-default",
            kind="env",
            size_mb=300,
            dest="envs/chatter-env-default",
            installer="env",
            requirements=("torch==2.10.0+cu128",),
            python_kind="chatterbox",
        )
        mgr = AssetManager(root=tmp_path, run_cmd=run_cmd, usage=big_free_usage, env_vars={})
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert calls and calls[0][0] == "C:/auto314/python.exe"

    def test_step_failure_raises_with_output_tail(self, tmp_path):
        def run_cmd(argv, extra_env=None):
            return 1, "resolving...\nERROR: no matching distribution"

        (tmp_path / "tools").mkdir(parents=True)
        (tmp_path / "tools" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
        entry = env_entry("bad-env")
        mgr = make_manager(tmp_path, run_cmd=run_cmd)
        with pytest.raises(AssetError, match="no matching distribution"):
            mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert not env_sentinel_path(tmp_path / "envs" / "bad-env").exists()

    def test_get_pip_downloaded_when_missing(self, tmp_path):
        # F3c: get-pip.py is EXECUTED, so it is verified BEFORE exec — the manager
        # downloads it pinned to a sha256 (here injected to match the fake bytes).
        body = b"# get-pip"
        good_sha = hashlib.sha256(body).hexdigest()
        client = FakeClient([FakeResponse(200, {"Content-Length": str(len(body))}, chunks=[body])])
        calls: list[list[str]] = []

        def run_cmd(argv, extra_env=None):
            calls.append(list(argv))
            return 0, ""

        entry = env_entry("dl-env")
        mgr = make_manager(tmp_path, client=client, run_cmd=run_cmd, get_pip_sha256=good_sha)
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)

        assert client.requests[0]["url"] == GET_PIP_URL
        assert (tmp_path / "tools" / "get-pip.py").read_bytes() == body
        assert len(calls) == 2

    def test_get_pip_tampered_download_rejected_before_exec(self, tmp_path):
        # A get-pip.py whose bytes don't match the pinned sha256 is REJECTED (no
        # .part promoted, no env steps run) — the verify-before-exec guarantee.
        body = b"# evil get-pip"  # does NOT match get_pip_sha256
        client = FakeClient([FakeResponse(200, {"Content-Length": str(len(body))}, chunks=[body])])
        ran: list[list[str]] = []

        def run_cmd(argv, extra_env=None):
            ran.append(list(argv))
            return 0, ""

        entry = env_entry("tamper-env")
        mgr = make_manager(tmp_path, client=client, run_cmd=run_cmd, get_pip_sha256="b" * 64)
        with pytest.raises(AssetError, match="sha256 mismatch"):
            mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        assert ran == []  # never executed the tampered script
        assert not (tmp_path / "tools" / "get-pip.py").exists()

    def test_get_pip_sha256_defaults_to_pinned_constant(self, tmp_path):
        # When the seam is not injected, the manager uses the pinned module constant.
        mgr = make_manager(tmp_path)
        assert mgr._get_pip_sha256 == GET_PIP_SHA256
        assert len(GET_PIP_SHA256) == 64

    def test_changed_pins_flip_installed_off(self, tmp_path):
        entry = env_entry("pin-env", reqs=("numpy==2.1.0",))
        env_dir = tmp_path / "envs" / "pin-env"
        env_dir.mkdir(parents=True)
        env_sentinel_path(env_dir).write_text(
            json.dumps({"name": "pin-env", "requirements": ["numpy==2.0.0"]}),
            encoding="utf-8",
        )
        mgr = make_manager(tmp_path)
        assert mgr.installed_path(entry) is None  # stale pins -> reinstall needed


# --------------------------------------------------------------------------- #
# hf installer (fake fetch seam)
# --------------------------------------------------------------------------- #
class TestHfInstaller:
    def test_ensure_calls_snapshot_seam(self, tmp_path):
        fetched: list[tuple] = []

        def hf_fetch(repo_id, revision):
            fetched.append((repo_id, revision))
            return str(tmp_path / "snap")

        mgr = make_manager(tmp_path, hf_fetch=hf_fetch)
        entry = manifest.get_asset(manifest.WHISPER_ASSET_NAME)
        mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)
        # F3c: the snapshot seam is now called with the PINNED commit revision.
        assert fetched == [
            ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", manifest.WHISPER_HF_REVISION),
        ]

    def test_hf_failure_becomes_asset_error(self, tmp_path):
        def hf_fetch(repo_id, revision):
            raise OSError("offline")

        mgr = make_manager(tmp_path, hf_fetch=hf_fetch)
        entry = manifest.get_asset(manifest.WHISPER_ASSET_NAME)
        with pytest.raises(AssetError, match="hf download failed"):
            mgr._install(entry, on_frac=lambda f, m="": None, should_cancel=lambda: False)


# --------------------------------------------------------------------------- #
# ensure as a JOB through the rpc handlers (registry + collected from conftest)
# --------------------------------------------------------------------------- #
def rpc_ctx(registry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


class TestEnsureJob:
    def test_ensure_job_progress_and_done_payload(self, tmp_path, registry, collected):
        # Content must plausibly match the declared size: the entry claims
        # 0.001 MB (~1049 bytes) and file_size_ok demands >= 50% of it, so a
        # 10-byte body would (correctly) read as NOT installed afterwards.
        body_a, body_b = b"a" * 600, b"b" * 500
        entry = download_entry("jobasset", sha256=sha_of(body_a, body_b))
        client = FakeClient([FakeResponse(200, {"Content-Length": "1100"}, chunks=[body_a, body_b])])
        mgr = make_manager(tmp_path, client=client)
        handler = assets_rpc.make_ensure_handler(mgr)

        res = handler({"names": ["jobasset"]}, rpc_ctx(registry))
        job_id = res["jobId"]
        assert isinstance(job_id, str)
        registry.join(timeout=5)

        progresses = [p for kind, p in collected if kind == "progress" and p[0] == job_id]
        assert progresses, "ensure job must stream progress"
        assert progresses[-1][1] == 100

        dones = [p for kind, p in collected if kind == "done" and p[0] == job_id]
        assert len(dones) == 1
        payload = dones[0][1]
        assert payload["installed"] == ["jobasset"]
        by_name = {a["name"]: a for a in payload["assets"]}
        assert by_name["jobasset"]["installed"] is True
        assert mgr.resolve_dest(entry).read_bytes() == body_a + body_b

    def test_preflight_blocks_low_disk_via_error_payload(self, tmp_path, registry, collected):
        download_entry("toolarge", size_mb=99999)
        low = lambda _p: SimpleNamespace(total=10**12, used=0, free=10 * MB)  # noqa: E731
        mgr = make_manager(tmp_path, usage=low)
        handler = assets_rpc.make_ensure_handler(mgr)

        res = handler({"names": ["toolarge"]}, rpc_ctx(registry))
        registry.join(timeout=5)

        dones = [p for kind, p in collected if kind == "done" and p[0] == res["jobId"]]
        assert len(dones) == 1
        err = dones[0][1]["error"]
        assert err["type"] == "AssetError"
        assert "insufficient disk" in err["message"]

    def test_download_failure_surfaces_error_payload(self, tmp_path, registry, collected):
        download_entry("flaky")
        client = FakeClient([FakeResponse(500, {}, chunks=[])])
        mgr = make_manager(tmp_path, client=client)
        handler = assets_rpc.make_ensure_handler(mgr)

        res = handler({"names": ["flaky"]}, rpc_ctx(registry))
        registry.join(timeout=5)
        dones = [p for kind, p in collected if kind == "done" and p[0] == res["jobId"]]
        assert dones[0][1]["error"]["type"] == "AssetError"

    def test_ensure_skips_already_installed(self, tmp_path, registry, collected):
        entry = download_entry("present", size_mb=0)
        boom_factory_called = {"n": 0}

        def boom_factory():
            boom_factory_called["n"] += 1
            raise AssertionError("network must not be touched for installed assets")

        mgr = AssetManager(
            root=tmp_path,
            http_factory=boom_factory,
            usage=big_free_usage,
            env_vars={},
        )
        dest = mgr.resolve_dest(entry)
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"already here")

        handler = assets_rpc.make_ensure_handler(mgr)
        res = handler({"names": ["present"]}, rpc_ctx(registry))
        registry.join(timeout=5)

        dones = [p for kind, p in collected if kind == "done" and p[0] == res["jobId"]]
        assert dones[0][1]["installed"] == ["present"]
        assert boom_factory_called["n"] == 0

    @pytest.mark.parametrize(
        "params",
        [{}, {"names": []}, {"names": "whisper"}, {"names": [1, 2]}, {"names": [""]}],
    )
    def test_ensure_validates_names(self, tmp_path, registry, params):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_ensure_handler(mgr)
        with pytest.raises(RpcError):
            handler(params, rpc_ctx(registry))

    def test_ensure_unknown_name_fails_fast(self, tmp_path, registry):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_ensure_handler(mgr)
        with pytest.raises(RpcError, match="unknown asset"):
            handler({"names": ["never-registered"]}, rpc_ctx(registry))

    def test_ensure_requires_job_registry(self, tmp_path):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_ensure_handler(mgr)
        ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
        with pytest.raises(RpcError, match="job registry"):
            handler({"names": [manifest.QWEN_ASSET_NAME]}, ctx)

    def test_multi_asset_aggregate_progress_monotonic(self, tmp_path, registry, collected):
        download_entry("multi-a", size_mb=0.001, sha256=sha_of(b"aaaa"))
        download_entry("multi-b", size_mb=0.001, sha256=sha_of(b"bbbb"))
        client = FakeClient(
            [
                FakeResponse(200, {"Content-Length": "4"}, chunks=[b"aaaa"]),
                FakeResponse(200, {"Content-Length": "4"}, chunks=[b"bbbb"]),
            ]
        )
        mgr = make_manager(tmp_path, client=client)
        handler = assets_rpc.make_ensure_handler(mgr)
        res = handler({"names": ["multi-a", "multi-b"]}, rpc_ctx(registry))
        registry.join(timeout=5)
        pcts = [p[1] for kind, p in collected if kind == "progress" and p[0] == res["jobId"]]
        assert pcts == sorted(pcts)
        assert pcts[-1] == 100


# --------------------------------------------------------------------------- #
# registration + list/cancel handlers
# --------------------------------------------------------------------------- #
class TestRpcRegistration:
    def test_register_wires_exactly_the_assets_methods(self, tmp_path):
        registered: dict[str, Any] = {}
        mgr = assets_rpc.register(make_manager(tmp_path), register_fn=lambda n, h: registered.update({n: h}))
        assert set(registered) == {"assets.list", "assets.plan", "assets.ensure", "assets.cancel"}
        assert isinstance(mgr, AssetManager)

    def test_register_defaults_to_protocol_registry(self, tmp_path):
        # conftest's autouse fixture restores METHODS afterwards.
        assets_rpc.register(make_manager(tmp_path))
        assert "assets.list" in protocol.METHODS
        assert "assets.ensure" in protocol.METHODS
        assert "assets.cancel" in protocol.METHODS

    def test_list_handler_returns_assets_envelope(self, tmp_path, registry):
        mgr = make_manager(tmp_path)
        handler = assets_rpc.make_list_handler(mgr)
        result = handler({}, rpc_ctx(registry))
        assert isinstance(result["assets"], list)
        names = {a["name"] for a in result["assets"]}
        assert manifest.WHISPER_ASSET_NAME in names

    def test_cancel_handler_cancels_running_job(self, registry):
        import threading

        started = threading.Event()

        def slow_job(job_ctx):
            started.set()
            while not job_ctx.cancelled:
                job_ctx.raise_if_cancelled()
                threading.Event().wait(0.01)

        job = registry.start(slow_job)
        assert started.wait(timeout=5)
        handler = assets_rpc.make_cancel_handler()
        result = handler({"jobId": job.id}, rpc_ctx(registry))
        assert result == {"ok": True}
        registry.join(timeout=5)
        assert job.status.value == "cancelled"

    def test_cancel_handler_validates_params(self, registry):
        handler = assets_rpc.make_cancel_handler()
        with pytest.raises(RpcError):
            handler({}, rpc_ctx(registry))
        with pytest.raises(RpcError):
            handler({"jobId": "x"}, RpcContext(emit_notification=lambda o: None, jobs=None))

    def test_cancel_unknown_job_is_ok_noop(self, registry):
        handler = assets_rpc.make_cancel_handler()
        assert handler({"jobId": "job-999"}, rpc_ctx(registry)) == {"ok": True}
