"""Tests for runtime_setup.bootstrap (T5) — pure-logic parts only.

NO real pip, NO network, NO subprocess: the runner / urlopen seams are faked,
zips are built in tmp_path with stdlib zipfile. (DONE-WHEN: pth writing +
pinned-list parsing tested with no real pip.)
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from media_studio import tools_resolver as tr
from media_studio.assets import manifest
from media_studio.assets.manager import ENV_SENTINEL, PINNED_PIP
from runtime_setup import bootstrap as bs


# --------------------------------------------------------------------------- #
# parse_requirements (pinned-list validation)
# --------------------------------------------------------------------------- #
class TestParseRequirements:
    def test_pins_and_options_parsed(self):
        text = """
        # comment line
        --extra-index-url https://download.pytorch.org/whl/cu124

        torch==2.6.0+cu124  # inline comment
        chatterbox-tts==0.1.2
        """
        reqs = bs.parse_requirements(text)
        assert reqs.pins == ("torch==2.6.0+cu124", "chatterbox-tts==0.1.2")
        assert reqs.options == ("--extra-index-url https://download.pytorch.org/whl/cu124",)

    def test_unpinned_requirement_rejected(self):
        with pytest.raises(bs.BootstrapError, match="not pinned"):
            bs.parse_requirements("faster-whisper>=1.0\n")

    def test_bare_name_rejected(self):
        with pytest.raises(bs.BootstrapError, match="not pinned"):
            bs.parse_requirements("numpy\n")

    def test_unknown_option_rejected(self):
        with pytest.raises(bs.BootstrapError, match="unsupported requirements option"):
            bs.parse_requirements("--find-links ./wheels\nnumpy==2.0.0\n")

    def test_empty_file_rejected(self):
        with pytest.raises(bs.BootstrapError, match="no pinned requirements"):
            bs.parse_requirements("# nothing here\n\n")

    def test_load_requirements_missing_file(self, tmp_path):
        with pytest.raises(bs.BootstrapError, match="not found"):
            bs.load_requirements(tmp_path / "nope.txt")


class TestShippedRequirementFiles:
    """The files we actually ship must themselves pass the validator."""

    def test_sidecar_file_parses_with_expected_pins(self):
        reqs = bs.load_requirements(bs.SIDECAR_REQUIREMENTS)
        assert reqs.options == ()  # main env: plain PyPI, no index games
        pins = dict(p.split("==", 1) for p in reqs.pins)
        # the T5 brief's KNOWN dev-venv versions
        assert pins["faster-whisper"] == "1.2.1"
        assert pins["ctranslate2"] == "4.8.1"
        assert pins["scenedetect"] == "0.7"
        assert pins["httpx"] == "0.28.1"
        assert pins["opencv-python"] == "4.13.0.92"
        assert pins["nvidia-cublas-cu12"] == "12.9.2.10"
        assert pins["nvidia-cudnn-cu12"] == "9.23.2.1"
        # DELIBERATELY ABSENT: mediapipe. Its legacy Solutions API (used by the
        # claudeshorts backend) only exists in wheels that pin numpy<2, which
        # conflicts with numpy==2.5.0; numpy-2-clean mediapipe removed Solutions.
        # Pinning it would install a mediapipe that crashes -> silent haar drop.
        assert "mediapipe" not in pins
        assert "kokoro-onnx" in pins  # pinned TTS engine (exact version chosen by T5)
        # A6.5 / §7: torch must NEVER enter the main sidecar env
        assert "torch" not in pins
        assert not any(p.startswith("torch") for p in pins)

    def test_chatterbox_file_parses_with_torch_cu12(self):
        reqs = bs.load_requirements(bs.CHATTERBOX_REQUIREMENTS)
        pins = dict(p.split("==", 1) for p in reqs.pins)
        # The new py3.14 trio (torch 2.11 cu128).
        assert pins["torch"] == "2.11.0+cu128"
        assert pins["torchaudio"] == "2.11.0+cu128"
        # HARDENING (WU1, dependabot #259 regression class): torch/torchaudio must
        # stay PAIRED (identical version) and BOTH must keep the +cu128 CUDA local
        # tag. #259 bumped torch->2.12.1 (stripped +cu128) while leaving torchaudio
        # at 2.11.0+cu128 — an incompatible pair that would install CPU torch for
        # the GPU dub env. These invariants fail LOUDLY on any such desync/strip,
        # independent of the exact pinned version above.
        assert pins["torch"] == pins["torchaudio"], (
            f"torch ({pins['torch']}) and torchaudio ({pins['torchaudio']}) must be the same version"
        )
        assert pins["torch"].endswith("+cu128"), f"torch must keep the +cu128 CUDA tag, got {pins['torch']}"
        assert pins["torchaudio"].endswith("+cu128"), (
            f"torchaudio must keep the +cu128 CUDA tag, got {pins['torchaudio']}"
        )
        assert pins["chatterbox-tts"] == "0.1.7"
        assert reqs.options == ("--extra-index-url https://download.pytorch.org/whl/cu128",)
        # ORDER MATTERS: mirror the CHATTERBOX_REQUIREMENTS tuple order so a
        # bootstrap-built env registers as the installed asset (sentinel match).
        assert reqs.pins[0].startswith("chatterbox-tts==")
        assert reqs.pins[1] == "torch==2.11.0+cu128"
        assert reqs.pins[2] == "torchaudio==2.11.0+cu128"


# --------------------------------------------------------------------------- #
# ._pth rendering / writing (A7 activation)
# --------------------------------------------------------------------------- #
class TestPthActivation:
    def test_render_order_and_import_site(self, tmp_path):
        body = bs.render_pth(tmp_path / "envs" / "sidecar", tmp_path / "sidecar-src")
        lines = body.splitlines()
        assert lines[0] == "python312.zip"
        assert lines[1] == "."
        assert lines[2] == str(tmp_path / "envs" / "sidecar")
        assert lines[3] == str(tmp_path / "sidecar-src")
        assert lines[-1] == "import site"  # UNCOMMENTED — pip needs site
        assert body.endswith("\n")

    def test_render_without_sidecar_src(self, tmp_path):
        lines = bs.render_pth(tmp_path / "env").splitlines()
        assert lines == ["python312.zip", ".", str(tmp_path / "env"), "import site"]

    def test_write_pth_derives_zip_name_from_existing_pth(self, tmp_path):
        embed = tmp_path / "python-embed"
        embed.mkdir()
        (embed / "python312._pth").write_text("python312.zip\n.\n#import site\n")
        written = bs.write_pth(embed, tmp_path / "env", tmp_path / "src")
        assert written == embed / "python312._pth"
        body = written.read_text(encoding="utf-8")
        assert body.splitlines()[0] == "python312.zip"
        assert "import site" in body
        assert "#import site" not in body
        assert str(tmp_path / "env") in body

    def test_write_pth_noop_for_non_embed_dir(self, tmp_path):
        # a full CPython / venv has no ._pth — nothing to activate
        assert bs.write_pth(tmp_path, tmp_path / "env") is None

    def test_find_pth_file(self, tmp_path):
        assert bs.find_pth_file(tmp_path) is None
        target = tmp_path / "python313._pth"
        target.write_text("x")
        assert bs.find_pth_file(tmp_path) == target


class TestActivateEmbedPth:
    """GUARDED ._pth activation: a read-only install dir must NOT crash setup
    (the runtime self-activates the env from the data dir instead)."""

    def test_writes_pth_when_dir_is_writable(self, tmp_path):
        embed = tmp_path / "python-embed"
        embed.mkdir()
        (embed / "python312._pth").write_text("python312.zip\n.\n#import site\n")
        written = bs.activate_embed_pth(embed, tmp_path / "env", tmp_path / "src")
        assert written == embed / "python312._pth"
        assert "import site" in written.read_text(encoding="utf-8")

    def test_returns_none_for_non_embed_dir(self, tmp_path):
        # no ._pth (a full CPython / dev venv) — nothing to activate, no error
        assert bs.activate_embed_pth(tmp_path, tmp_path / "env") is None

    def test_permission_error_is_guarded_not_raised(self, tmp_path, monkeypatch, capsys):
        # simulate a read-only install dir (e.g. Program Files): the write raises
        # PermissionError, which activate_embed_pth swallows + logs (returns None).
        def boom(*_a, **_k):
            raise PermissionError("install dir is read-only")

        monkeypatch.setattr(bs, "write_pth", boom)
        result = bs.activate_embed_pth(tmp_path / "install" / "python", tmp_path / "env")
        assert result is None
        err = capsys.readouterr().err
        assert "skipping ._pth activation" in err
        assert "self-activate the env from the data dir" in err

    def test_generic_oserror_is_guarded(self, tmp_path, monkeypatch):
        def boom(*_a, **_k):
            raise OSError("disk gremlin")

        monkeypatch.setattr(bs, "write_pth", boom)
        assert bs.activate_embed_pth(tmp_path, tmp_path / "env") is None


# --------------------------------------------------------------------------- #
# pip step argv building (mirrors the U4 env installer; NO pip is run)
# --------------------------------------------------------------------------- #
class TestBuildPipSteps:
    def test_two_steps_with_pinned_pip_and_target(self, tmp_path):
        steps = bs.build_pip_steps(
            tmp_path / "py" / "python.exe",
            tmp_path / "get-pip.py",
            tmp_path / "envs" / "sidecar",
            tmp_path / "req.txt",
        )
        assert len(steps) == 2
        step1, step2 = steps
        assert step1["argv"][0] == str(tmp_path / "py" / "python.exe")
        assert step1["argv"][1] == str(tmp_path / "get-pip.py")
        assert PINNED_PIP in step1["argv"]
        assert "--target" in step1["argv"]
        assert step2["argv"][1:4] == ["-m", "pip", "install"]
        assert step2["argv"][-2:] == ["-r", str(tmp_path / "req.txt")]
        # step 2 imports step 1's pip from the env dir
        assert step2["env"] == {"PYTHONPATH": str(tmp_path / "envs" / "sidecar")}

    def test_argv_are_lists_with_single_path_elements(self, tmp_path):
        spaced = tmp_path / "dir with spaces" / "python.exe"
        steps = bs.build_pip_steps(spaced, "g.py", "env", "r.txt")
        for step in steps:
            assert isinstance(step["argv"], list)
            assert str(spaced) in step["argv"]  # one element, not shell-split


class TestHashedLockInstall:
    """WU C4 — the first-run env installer can install a fully-hashed lock so
    every wheel over the full transitive closure is hash-verified before exec."""

    def test_hashed_lock_path_is_the_sibling_lock(self):
        assert bs.hashed_lock_path(Path("x") / "requirements-sidecar.txt") == (
            Path("x") / "requirements-sidecar.lock.txt"
        )

    def test_build_pip_steps_with_lock_uses_require_hashes(self, tmp_path):
        lock = tmp_path / "req.lock.txt"
        steps = bs.build_pip_steps(
            tmp_path / "py.exe", tmp_path / "gp.py", tmp_path / "env", tmp_path / "req.txt", lock_file=lock
        )
        step2 = steps[1]["argv"]
        for flag in bs.HASHED_LOCK_PIP_ARGS:
            assert flag in step2
        # the lock is the install source, NOT the (top-level-only) req file
        assert step2[-2:] == ["-r", str(lock)]
        assert str(tmp_path / "req.txt") not in step2

    def test_build_pip_steps_without_lock_is_unchanged(self, tmp_path):
        steps = bs.build_pip_steps("py", "gp.py", "env", tmp_path / "req.txt")
        step2 = steps[1]["argv"]
        assert "--require-hashes" not in step2
        assert step2[-2:] == ["-r", str(tmp_path / "req.txt")]

    def test_resolve_active_lock_returns_staged_valid_lock(self, tmp_path):
        req = tmp_path / "requirements-sidecar.txt"
        lock = tmp_path / "requirements-sidecar.lock.txt"
        lock.write_text("numpy==2.5.0 \\\n    --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
        assert bs.resolve_active_lock(req, None) == lock

    def test_resolve_active_lock_falls_back_loudly_when_unstaged(self, tmp_path, capsys):
        req = tmp_path / "requirements-sidecar.txt"
        assert bs.resolve_active_lock(req, None) is None
        err = capsys.readouterr().err
        assert "hashed lock not staged" in err and "UNHASHED" in err

    def test_resolve_active_lock_rejects_an_unhashed_lock(self, tmp_path):
        lock = tmp_path / "x.lock.txt"
        lock.write_text("numpy==2.5.0\n", encoding="utf-8")  # pinned but NOT hashed
        with pytest.raises(bs.BootstrapError, match="missing --hash"):
            bs.resolve_active_lock(tmp_path / "x.txt", lock)

    def test_install_env_uses_a_staged_sibling_lock(self, tmp_path):
        req = tmp_path / "requirements-sidecar.txt"
        req.write_text("numpy==2.5.0\nhttpx==0.28.1\n", encoding="utf-8")
        lock = tmp_path / "requirements-sidecar.lock.txt"
        lock.write_text(
            "numpy==2.5.0 \\\n    --hash=sha256:"
            + "a" * 64
            + "\nhttpx==0.28.1 \\\n    --hash=sha256:"
            + "b" * 64
            + "\n",
            encoding="utf-8",
        )
        (tmp_path / "root" / "tools").mkdir(parents=True)
        (tmp_path / "root" / "tools" / "get-pip.py").write_text("# gp")
        calls: list[list[str]] = []

        def fake_run(argv, extra_env):
            calls.append(list(argv))
            return 0

        bs.install_env(
            python_exe=tmp_path / "python.exe",
            root=tmp_path / "root",
            env_name="sidecar",
            req_file=req,
            run_step=fake_run,
        )
        step2 = calls[1]
        assert "--require-hashes" in step2
        assert step2[-2:] == ["-r", str(lock)]
        # the sentinel still records the top-level pins (installed-detection).
        sentinel = json.loads((tmp_path / "root" / "envs" / "sidecar" / ENV_SENTINEL).read_text(encoding="utf-8"))
        assert sentinel["requirements"] == ["numpy==2.5.0", "httpx==0.28.1"]


class TestGenerateHashedLock:
    """WU C4 — the documented F1 lock-generation script (build-prep, no network
    at test time): the pure argv builder + the injectable-runner CLI."""

    def test_argv_has_generate_hashes_and_output(self):
        from runtime_setup import generate_hashed_lock as gl

        argv = gl.build_lock_gen_argv("req.txt", "req.lock.txt")
        assert argv[:3] == ["uv", "pip", "compile"]
        assert "--generate-hashes" in argv
        assert argv[argv.index("--output-file") + 1] == "req.lock.txt"

    def test_extra_index_url_is_forwarded(self):
        from runtime_setup import generate_hashed_lock as gl

        argv = gl.build_lock_gen_argv(
            "r.txt", "r.lock.txt", extra_index_urls=["https://download.pytorch.org/whl/cu128"]
        )
        i = argv.index("--extra-index-url")
        assert argv[i + 1] == "https://download.pytorch.org/whl/cu128"

    def test_pip_compile_backend(self):
        from runtime_setup import generate_hashed_lock as gl

        argv = gl.build_lock_gen_argv("r.txt", "r.lock.txt", tool="pip-compile")
        assert argv[0] == "pip-compile"

    def test_unknown_tool_rejected(self):
        from runtime_setup import generate_hashed_lock as gl

        with pytest.raises(ValueError, match="unknown lock-gen tool"):
            gl.build_lock_gen_argv("r.txt", "r.lock.txt", tool="poetry")

    def test_main_dry_run_prints_argv(self, capsys):
        from runtime_setup import generate_hashed_lock as gl

        code = gl.main(["req.txt", "req.lock.txt", "--dry-run"])
        assert code == 0
        assert "DRY-RUN uv pip compile" in capsys.readouterr().out

    def test_main_runs_the_injected_runner_on_success(self, capsys):
        from runtime_setup import generate_hashed_lock as gl

        seen: list[list[str]] = []

        def fake_run(argv):
            seen.append(list(argv))
            return 0

        code = gl.main(["req.txt", "out.lock.txt"], run=fake_run)
        assert code == 0
        assert seen and "--generate-hashes" in seen[0]
        assert "SUCCESS:generate_hashed_lock wrote out.lock.txt" in capsys.readouterr().out

    def test_main_reports_a_nonzero_exit_loudly(self, capsys):
        from runtime_setup import generate_hashed_lock as gl

        code = gl.main(["req.txt", "out.lock.txt"], run=lambda _argv: 2)
        assert code == 2
        assert "FAILED:generate_hashed_lock exit 2" in capsys.readouterr().out


class TestRunSteps:
    def test_success_runs_all_steps_with_env(self):
        calls = []

        def fake_run(argv, extra_env):
            calls.append((list(argv), extra_env))
            return 0

        bs.run_steps(
            [{"argv": ["a"], "env": {}}, {"argv": ["b"], "env": {"PYTHONPATH": "x"}}],
            run_step=fake_run,
        )
        assert calls == [(["a"], None), (["b"], {"PYTHONPATH": "x"})]

    def test_failure_raises_with_step_and_exit_code(self):
        def fake_run(argv, extra_env):
            return 3

        with pytest.raises(bs.BootstrapError, match=r"step 1 failed \(exit 3\)"):
            bs.run_steps([{"argv": ["boom"], "env": {}}], run_step=fake_run)


# --------------------------------------------------------------------------- #
# get-pip resolution (staged -> cached -> download via injected opener)
# --------------------------------------------------------------------------- #
class TestEnsureGetPip:
    def test_staged_copy_beside_embed_python_wins(self, tmp_path):
        embed = tmp_path / "python-embed"
        embed.mkdir()
        staged = embed / "get-pip.py"
        staged.write_text("# staged")
        found = bs.ensure_get_pip(tmp_path / "root", embed, urlopen=None)
        assert found == staged

    def test_cached_copy_under_root(self, tmp_path):
        cached = tmp_path / "root" / "tools" / "get-pip.py"
        cached.parent.mkdir(parents=True)
        cached.write_text("# cached")
        found = bs.ensure_get_pip(tmp_path / "root", None, urlopen=None)
        assert found == cached

    def test_download_fallback_uses_injected_opener(self, tmp_path):
        class FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        urls = []

        def fake_urlopen(url):
            urls.append(url)
            return FakeResp(b"# downloaded get-pip")

        found = bs.ensure_get_pip(tmp_path / "root", None, urlopen=fake_urlopen)
        assert found.read_bytes() == b"# downloaded get-pip"
        assert urls == [bs.GET_PIP_URL]

    def test_download_failure_is_typed(self, tmp_path):
        def fake_urlopen(url):
            raise OSError("offline")

        with pytest.raises(bs.BootstrapError, match="get-pip"):
            bs.ensure_get_pip(tmp_path / "root", None, urlopen=fake_urlopen)


# --------------------------------------------------------------------------- #
# install_env end-to-end with fakes (still NO real pip)
# --------------------------------------------------------------------------- #
class TestInstallEnv:
    def test_validates_then_runs_then_writes_sentinel(self, tmp_path):
        req = tmp_path / "req.txt"
        req.write_text("numpy==2.4.6\nhttpx==0.28.1\n")
        (tmp_path / "root" / "tools").mkdir(parents=True)
        (tmp_path / "root" / "tools" / "get-pip.py").write_text("# gp")
        calls = []

        def fake_run(argv, extra_env):
            calls.append(list(argv))
            return 0

        env_dir = bs.install_env(
            python_exe=tmp_path / "python.exe",
            root=tmp_path / "root",
            env_name="sidecar",
            req_file=req,
            run_step=fake_run,
        )
        assert env_dir == tmp_path / "root" / "envs" / "sidecar"
        assert len(calls) == 2  # get-pip step + pip install step
        sentinel = json.loads((env_dir / ENV_SENTINEL).read_text(encoding="utf-8"))
        assert sentinel["requirements"] == ["numpy==2.4.6", "httpx==0.28.1"]

    def test_invalid_requirements_never_spawn_a_process(self, tmp_path):
        req = tmp_path / "req.txt"
        req.write_text("numpy\n")  # unpinned

        def fake_run(argv, extra_env):  # pragma: no cover - must not be reached
            raise AssertionError("pip must not run for an invalid pin list")

        with pytest.raises(bs.BootstrapError, match="not pinned"):
            bs.install_env(
                python_exe="py",
                root=tmp_path / "root",
                env_name="sidecar",
                req_file=req,
                run_step=fake_run,
            )


# --------------------------------------------------------------------------- #
# dedicated py3.14 chatterbox interpreter resolution
# --------------------------------------------------------------------------- #
class TestChatterboxPythonExe:
    def test_resolves_sibling_embed(self, tmp_path):
        res = tmp_path / "resources"
        (res / "python").mkdir(parents=True)
        cb_dir = res / bs.CHATTERBOX_EMBED_DIRNAME
        cb_dir.mkdir(parents=True)
        cb_py = cb_dir / "python.exe"
        cb_py.write_text("", encoding="utf-8")
        assert bs.chatterbox_python_exe(res) == cb_py

    def test_none_when_unstaged(self, tmp_path):
        res = tmp_path / "resources"
        (res / "python").mkdir(parents=True)
        assert bs.chatterbox_python_exe(res) is None


# --------------------------------------------------------------------------- #
# tool-archive extraction (zip built in tmp; zip-slip guarded; exe hoisted)
# --------------------------------------------------------------------------- #
def _make_zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


class TestExtraction:
    def test_extract_archive_flat(self, tmp_path):
        z = _make_zip(tmp_path / "a.zip", {"x.dll": b"1", "y.txt": b"2"})
        bs.extract_archive(z, tmp_path / "out")
        assert (tmp_path / "out" / "x.dll").read_bytes() == b"1"

    def test_zip_slip_member_rejected(self, tmp_path):
        z = _make_zip(tmp_path / "evil.zip", {"../escape.txt": b"x"})
        with pytest.raises(bs.BootstrapError, match="unsafe zip member"):
            bs.extract_archive(z, tmp_path / "out")
        assert not (tmp_path / "escape.txt").exists()

    def test_flatten_hoists_nested_exe_dir(self, tmp_path):
        target = tmp_path / "tool"
        (target / "build" / "bin").mkdir(parents=True)
        (target / "build" / "bin" / tr.LLAMA_EXE).write_bytes(b"exe")
        (target / "build" / "bin" / "ggml.dll").write_bytes(b"dll")
        bs.flatten_tool_dir(target, tr.LLAMA_EXE)
        assert (target / tr.LLAMA_EXE).read_bytes() == b"exe"
        assert (target / "ggml.dll").read_bytes() == b"dll"

    def test_flatten_noop_when_already_flat_or_missing(self, tmp_path):
        target = tmp_path / "tool"
        target.mkdir()
        bs.flatten_tool_dir(target, tr.LLAMA_EXE)  # no marker anywhere: no-op
        (target / tr.LLAMA_EXE).write_bytes(b"exe")
        bs.flatten_tool_dir(target, tr.LLAMA_EXE)  # already flat: no-op
        assert (target / tr.LLAMA_EXE).read_bytes() == b"exe"

    def test_extract_tool_archives_uses_manifest_dest(self, tmp_path):
        root = tmp_path / "root"
        cuda_entry = manifest.get_asset(tr.LLAMA_CUDA_ASSET)
        zip_path = root / cuda_entry.dest
        _make_zip(zip_path, {f"build/bin/{tr.LLAMA_EXE}": b"exe", "build/bin/a.dll": b"d"})
        done = bs.extract_tool_archives(root)
        assert done == [tr.LLAMA_CUDA_ASSET]
        assert (root / tr.TOOL_DIR_CUDA / tr.LLAMA_EXE).read_bytes() == b"exe"
        assert not zip_path.exists()  # consumed after successful extraction

    def test_extract_tool_archives_skips_missing_zips(self, tmp_path):
        assert bs.extract_tool_archives(tmp_path / "empty-root") == []


# --------------------------------------------------------------------------- #
# asset delegation + first-run set
# --------------------------------------------------------------------------- #
class TestAssets:
    def test_default_first_run_assets_cover_models_and_llama(self):
        names = bs.default_first_run_assets()
        assert "whisper-large-v3-turbo" in names
        assert "qwen3-4b-gguf" in names
        assert tr.LLAMA_CUDA_ASSET in names
        assert tr.LLAMA_CPU_ASSET in names

    def test_default_first_run_assets_include_lightasd_weights(self):
        # WU first-run-provisioning: the multi-speaker reframe engine's S3FD +
        # LR-ASD weights were registered but never in the first-run set, so a
        # fresh install silently fell back to a single-speaker/center crop. They
        # must be provisioned up front.
        names = bs.default_first_run_assets()
        assert manifest.LIGHTASD_S3FD_ASSET_NAME in names
        assert manifest.LIGHTASD_ASD_ASSET_NAME in names

    def test_default_first_run_assets_include_yunet(self):
        # v1.2.0 WU1: the claudeshorts reframe engine's YuNet face detector must be
        # provisioned up front so the detector is present or fails LOUD — never a
        # silent center crop (NO-SILENT-FALLBACK).
        assert manifest.YUNET_ASSET_NAME in bs.default_first_run_assets()

    def test_core_first_run_assets_are_exactly_the_face_asd_weights(self):
        # WU C3 CORE-ONLY marker: the marker attests env + ffmpeg + the always-on
        # face/ASD weights (YuNet tracker + S3FD + LR-ASD), NOTHING else.
        assert bs.core_first_run_assets() == [
            manifest.YUNET_ASSET_NAME,
            manifest.LIGHTASD_S3FD_ASSET_NAME,
            manifest.LIGHTASD_ASD_ASSET_NAME,
        ]

    def test_core_first_run_assets_exclude_on_demand_models(self):
        # The on-demand GGUFs / llama builds are FETCHED AT POINT-OF-USE — they
        # live OUTSIDE the marker so a Minimum/Custom install is not perpetually
        # "un-provisioned" and does not re-run bootstrap every launch.
        core = bs.core_first_run_assets()
        assert manifest.WHISPER_ASSET_NAME not in core
        assert manifest.QWEN_ASSET_NAME not in core
        assert tr.LLAMA_CUDA_ASSET not in core
        assert tr.LLAMA_CPU_ASSET not in core

    def test_core_first_run_assets_are_a_strict_subset_of_default(self):
        # Every CORE weight is still downloaded on a Default/Full run; CORE only
        # narrows what GATES the marker, never what the run installs.
        core = bs.core_first_run_assets()
        default = bs.default_first_run_assets()
        assert set(core) < set(default)

    def test_ensure_assets_delegates_to_manager(self, tmp_path):
        class FakeManager:
            def __init__(self):
                self.calls = []

            def ensure(self, names, job_ctx):
                self.calls.append(list(names))
                job_ctx.progress(50.0, "halfway")  # console sink must accept calls
                job_ctx.raise_if_cancelled()
                assert job_ctx.cancelled is False

        mgr = FakeManager()
        bs.ensure_assets(["a", "b"], tmp_path, manager=mgr)
        assert mgr.calls == [["a", "b"]]


# --------------------------------------------------------------------------- #
# fail-loud provisioning verification + first-run-complete marker
# --------------------------------------------------------------------------- #
class _FakeMgr:
    """A minimal AssetManager stand-in: installed_path echoes a per-name map."""

    def __init__(self, installed: dict[str, str | None]):
        self._installed = installed

    def installed_path(self, entry: Any) -> str | None:
        return self._installed.get(entry.name)


class TestVerifyProvisioned:
    def test_passes_when_all_assets_installed(self, tmp_path):
        names = [manifest.LIGHTASD_S3FD_ASSET_NAME, manifest.LIGHTASD_ASD_ASSET_NAME]
        mgr = _FakeMgr({n: f"{tmp_path}/{n}.bin" for n in names})
        # No raise == provisioning verified.
        bs.verify_provisioned(names, tmp_path, manager=mgr)

    def test_raises_naming_every_missing_asset(self, tmp_path):
        names = [manifest.LIGHTASD_S3FD_ASSET_NAME, manifest.LIGHTASD_ASD_ASSET_NAME]
        # S3FD installed, ASD missing -> only the missing one is named.
        mgr = _FakeMgr({manifest.LIGHTASD_S3FD_ASSET_NAME: f"{tmp_path}/s3fd.bin"})
        with pytest.raises(bs.BootstrapError, match=manifest.LIGHTASD_ASD_ASSET_NAME):
            bs.verify_provisioned(names, tmp_path, manager=mgr)

    def test_raises_for_unregistered_asset(self, tmp_path):
        with pytest.raises(bs.BootstrapError, match="not-a-real-asset"):
            bs.verify_provisioned(["not-a-real-asset"], tmp_path, manager=_FakeMgr({}))

    def test_default_manager_is_constructed_when_none(self, tmp_path, monkeypatch):
        seen: dict[str, Any] = {}

        def fake_default(root):
            seen["root"] = root
            return _FakeMgr({manifest.WHISPER_ASSET_NAME: "x"})

        monkeypatch.setattr(bs, "_default_asset_manager", fake_default)
        bs.verify_provisioned([manifest.WHISPER_ASSET_NAME], tmp_path)
        assert seen["root"] == tmp_path


class TestFirstRunCompleteMarker:
    def test_write_and_path_round_trip(self, tmp_path):
        names = ["whisper-large-v3-turbo", manifest.LIGHTASD_ASD_ASSET_NAME]
        marker = bs.write_first_run_complete(tmp_path, names)
        assert marker == bs.first_run_complete_path(tmp_path)
        assert marker.is_file()
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["assets"] == names

    def test_marker_absent_before_write(self, tmp_path):
        assert not bs.first_run_complete_path(tmp_path).exists()


# --------------------------------------------------------------------------- #
# CLI surface (dry-run only — never spawns anything)
# --------------------------------------------------------------------------- #
class TestCli:
    def test_dry_run_succeeds_and_prints_terminal_state(self, tmp_path, capsys):
        code = bs.main(["--dry-run", "--root", str(tmp_path)])
        assert code == 0
        out = capsys.readouterr().out
        assert "SUCCESS:bootstrap dry-run" in out

    def test_dry_run_with_bad_requirements_fails_closed(self, tmp_path, capsys):
        bad = tmp_path / "bad.txt"
        bad.write_text("numpy\n")
        code = bs.main(["--dry-run", "--root", str(tmp_path), "--requirements", str(bad)])
        assert code == 1
        assert "FAILED:bootstrap" in capsys.readouterr().out

    def test_tools_only_with_nothing_downloaded(self, tmp_path, capsys):
        code = bs.main(["--tools-only", "--root", str(tmp_path)])
        assert code == 0
        assert "SUCCESS:bootstrap tools-only" in capsys.readouterr().out


class TestMainFullRunProvisioning:
    """A full first run (no --skip flags) must VERIFY assets then write the
    first-run-complete marker — the honest 'everything provisioned' signal the
    Electron supervisor gates re-runs on. A verification failure must fail loud
    AND leave NO marker (so the next launch retries instead of silently running
    a half-provisioned app)."""

    def _fake_py(self, tmp_path: Path) -> Path:
        fake_py = tmp_path / "py" / "python.exe"
        fake_py.parent.mkdir(parents=True)
        fake_py.write_text("", encoding="utf-8")
        return fake_py

    def _stub_env_and_assets(self, tmp_path, monkeypatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(bs, "write_pth", lambda *a, **k: None)
        monkeypatch.setattr(bs, "install_env", lambda **k: Path(k["root"]) / "envs" / "sidecar")
        monkeypatch.setattr(bs, "activate_env_in_process", lambda *a, **k: None)
        monkeypatch.setattr(bs, "ensure_assets", lambda names, root, **k: captured.__setitem__("ensured", list(names)))
        monkeypatch.setattr(bs, "extract_tool_archives", lambda *a, **k: [])
        return captured

    def test_full_run_verifies_core_only_then_writes_marker(self, tmp_path, monkeypatch, capsys):
        captured = self._stub_env_and_assets(tmp_path, monkeypatch)
        monkeypatch.setattr(
            bs, "verify_provisioned", lambda names, root, **k: captured.__setitem__("verified", list(names))
        )
        rc = bs.main(["--root", str(tmp_path), "--python", str(self._fake_py(tmp_path))])
        assert rc == 0
        assert "SUCCESS:bootstrap first-run setup complete" in capsys.readouterr().out
        # WU C3 CORE-ONLY marker: the run STILL installs the full default set...
        assert captured["ensured"] == bs.default_first_run_assets()
        # ...but the marker is GATED on the CORE face/ASD weights ONLY, never on
        # the on-demand GGUFs (the old "verify every model" gate is gone). The
        # gated set is the CORE subset that was part of THIS run (run order).
        assert set(captured["verified"]) == set(bs.core_first_run_assets())
        assert set(captured["verified"]) < set(captured["ensured"])
        # ...and the honest completion marker records exactly that CORE set.
        marker = bs.first_run_complete_path(tmp_path)
        assert marker.is_file()
        assert set(json.loads(marker.read_text(encoding="utf-8"))["assets"]) == set(
            bs.core_first_run_assets()
        )

    def test_on_demand_only_run_is_provisioned_without_core_verification(
        self, tmp_path, monkeypatch, capsys
    ):
        # A Minimum/Custom-style run that pulls ONLY on-demand assets (no CORE
        # face/ASD weight) verifies an EMPTY core set and STILL writes the marker,
        # so the install opens provisioned (no re-bootstrap loop) — the missing
        # models surface as point-of-use "Needs download", not "setup incomplete".
        captured = self._stub_env_and_assets(tmp_path, monkeypatch)
        monkeypatch.setattr(
            bs, "verify_provisioned", lambda names, root, **k: captured.__setitem__("verified", list(names))
        )
        rc = bs.main(
            [
                "--root",
                str(tmp_path),
                "--python",
                str(self._fake_py(tmp_path)),
                "--assets",
                manifest.QWEN_ASSET_NAME,
            ]
        )
        assert rc == 0
        assert "SUCCESS:bootstrap first-run setup complete" in capsys.readouterr().out
        assert captured["ensured"] == [manifest.QWEN_ASSET_NAME]
        assert captured["verified"] == []  # no CORE weight pledged -> nothing gates
        marker = bs.first_run_complete_path(tmp_path)
        assert marker.is_file()
        assert json.loads(marker.read_text(encoding="utf-8"))["assets"] == []

    def test_failed_verification_is_loud_and_leaves_no_marker(self, tmp_path, monkeypatch, capsys):
        self._stub_env_and_assets(tmp_path, monkeypatch)

        def boom(names, root, **k):
            raise bs.BootstrapError("weight lightasd-asd did not install")

        monkeypatch.setattr(bs, "verify_provisioned", boom)
        rc = bs.main(["--root", str(tmp_path), "--python", str(self._fake_py(tmp_path))])
        assert rc == 1
        assert "FAILED:bootstrap" in capsys.readouterr().out
        assert not bs.first_run_complete_path(tmp_path).exists()

    def test_partial_run_skips_marker(self, tmp_path, monkeypatch):
        # --skip-assets is an explicit PARTIAL provision; it must NOT mark the
        # first run complete (that would let the supervisor skip a real re-run).
        self._stub_env_and_assets(tmp_path, monkeypatch)
        rc = bs.main(["--skip-assets", "--root", str(tmp_path), "--python", str(self._fake_py(tmp_path))])
        assert rc == 0
        assert not bs.first_run_complete_path(tmp_path).exists()


class TestMainOrdering:
    """Regression: the ._pth must be activated BEFORE the pip steps run.

    The embeddable python runs in isolated-path mode (ignores PYTHONPATH), so
    step 2's `python -m pip` can only import the pip that step 1 installs into
    the env dir once env_dir + `import site` are on the ._pth. A real-bundle
    bootstrap smoke caught the original 'No module named pip' (write_pth ran
    AFTER install_env); the mocked unit tests did not. This pins the order.
    """

    def test_main_activates_pth_before_installing_env(self, tmp_path, monkeypatch):
        order = []
        monkeypatch.setattr(bs, "write_pth", lambda *a, **k: order.append("pth"))

        def fake_install(**kwargs):
            order.append("install")
            return tmp_path / "envs" / "sidecar"

        monkeypatch.setattr(bs, "install_env", fake_install)
        fake_py = tmp_path / "py" / "python.exe"
        fake_py.parent.mkdir(parents=True)
        fake_py.write_text("", encoding="utf-8")

        rc = bs.main(["--skip-assets", "--root", str(tmp_path), "--python", str(fake_py)])

        assert rc == 0
        assert order == ["pth", "install"], "._pth must be written before the pip install"


class TestMainReadOnlyInstallDir:
    """WU-1 root cause: a read-only install dir (Program Files) must NOT abort
    first-run setup. The ._pth write is skipped (guarded) and the env still
    provisions into the writable DATA ROOT (``--root``)."""

    def _fake_py(self, tmp_path: Path) -> Path:
        fake_py = tmp_path / "install" / "python" / "python.exe"
        fake_py.parent.mkdir(parents=True)
        fake_py.write_text("", encoding="utf-8")
        return fake_py

    def test_pth_not_writable_still_provisions_env_in_data_root(self, tmp_path, monkeypatch, capsys):
        # 1) the install-dir ._pth write fails like a read-only Program Files dir
        def deny_pth(*_a, **_k):
            raise PermissionError("Program Files is read-only")

        monkeypatch.setattr(bs, "write_pth", deny_pth)

        # 2) the env install lands in the DATA ROOT (root == tmp_path), proving
        #    provisioning succeeds THERE even though the install dir is read-only.
        def fake_install(*, python_exe, root, env_name, req_file, embed_dir=None):
            env_dir = Path(root) / "envs" / env_name
            env_dir.mkdir(parents=True, exist_ok=True)
            (env_dir / "provisioned.marker").write_text("ok", encoding="utf-8")
            return env_dir

        monkeypatch.setattr(bs, "install_env", fake_install)
        fake_py = self._fake_py(tmp_path)

        rc = bs.main(["--skip-assets", "--root", str(tmp_path), "--python", str(fake_py)])

        # NOT a silent exit 1: setup completes, the env exists in the data root.
        assert rc == 0
        assert (tmp_path / "envs" / "sidecar" / "provisioned.marker").is_file()
        # the guard logged the read-only skip (actionable, not a crash)
        assert "skipping ._pth activation" in capsys.readouterr().err


class TestMainFailsLoud:
    """An unexpected first-run failure surfaces a single actionable FAILED line
    (what + where + how to fix) and exit 1 — never a bare traceback / silent
    empty data dir."""

    def _fake_py(self, tmp_path: Path) -> Path:
        fake_py = tmp_path / "py" / "python.exe"
        fake_py.parent.mkdir(parents=True)
        fake_py.write_text("", encoding="utf-8")
        return fake_py

    def test_permission_error_is_actionable(self, tmp_path, monkeypatch, capsys):
        def boom(**_kwargs):
            raise PermissionError("denied writing the data dir")

        monkeypatch.setattr(bs, "install_env", boom)
        rc = bs.main(["--skip-assets", "--root", str(tmp_path), "--python", str(self._fake_py(tmp_path))])
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAILED:bootstrap permission denied" in out
        assert str(tmp_path) in out  # WHERE: the data root
        assert "fix:" in out  # HOW to fix

    def test_oserror_is_actionable(self, tmp_path, monkeypatch, capsys):
        def boom(**_kwargs):
            raise OSError("No space left on device")

        monkeypatch.setattr(bs, "install_env", boom)
        rc = bs.main(["--skip-assets", "--root", str(tmp_path), "--python", str(self._fake_py(tmp_path))])
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAILED:bootstrap I/O error" in out
        assert "free disk space" in out

    def test_unexpected_error_is_actionable(self, tmp_path, monkeypatch, capsys):
        def boom(**_kwargs):
            raise RuntimeError("totally unexpected")

        monkeypatch.setattr(bs, "install_env", boom)
        rc = bs.main(["--skip-assets", "--root", str(tmp_path), "--python", str(self._fake_py(tmp_path))])
        assert rc == 1
        out = capsys.readouterr().out
        assert "FAILED:bootstrap unexpected first-run setup error" in out
        assert "RuntimeError: totally unexpected" in out


class TestMainChatterbox:
    """The --chatterbox env installs with the DEDICATED py3.14 interpreter."""

    def _fake_host(self, tmp_path: Path) -> Path:
        fake_py = tmp_path / "py" / "python.exe"
        fake_py.parent.mkdir(parents=True)
        fake_py.write_text("", encoding="utf-8")
        return fake_py

    def test_main_chatterbox_uses_dedicated_interpreter(self, tmp_path, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_install(**kwargs):
            captured.update(kwargs)
            return tmp_path / "envs" / kwargs["env_name"]

        monkeypatch.setattr(bs, "install_env", fake_install)
        dedicated = tmp_path / "python-chatterbox" / "python.exe"
        monkeypatch.setattr(bs, "chatterbox_python_exe", lambda *a, **k: dedicated)
        fake_py = self._fake_host(tmp_path)

        rc = bs.main(["--chatterbox", "--skip-env", "--skip-assets", "--root", str(tmp_path), "--python", str(fake_py)])
        assert rc == 0
        assert captured["python_exe"] == dedicated
        assert captured["env_name"] == bs.CHATTERBOX_ENV_NAME
        assert captured["embed_dir"] == dedicated.parent

    def test_main_chatterbox_falls_back_to_host_when_unstaged(self, tmp_path, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_install(**kwargs):
            captured.update(kwargs)
            return tmp_path / "envs" / kwargs["env_name"]

        monkeypatch.setattr(bs, "install_env", fake_install)
        monkeypatch.setattr(bs, "chatterbox_python_exe", lambda *a, **k: None)
        fake_py = self._fake_host(tmp_path)

        rc = bs.main(["--chatterbox", "--skip-env", "--skip-assets", "--root", str(tmp_path), "--python", str(fake_py)])
        assert rc == 0
        assert captured["python_exe"] == fake_py
        assert captured["embed_dir"] == fake_py.parent

    def test_main_chatterbox_explicit_override(self, tmp_path, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_install(**kwargs):
            captured.update(kwargs)
            return tmp_path / "envs" / kwargs["env_name"]

        monkeypatch.setattr(bs, "install_env", fake_install)
        # chatterbox_python_exe must NOT be consulted when --chatterbox-python given.
        monkeypatch.setattr(
            bs, "chatterbox_python_exe", lambda *a, **k: pytest.fail("override must bypass auto-resolve")
        )
        fake_py = self._fake_host(tmp_path)
        override = tmp_path / "custom314" / "python.exe"

        rc = bs.main(
            [
                "--chatterbox",
                "--chatterbox-python",
                str(override),
                "--skip-env",
                "--skip-assets",
                "--root",
                str(tmp_path),
                "--python",
                str(fake_py),
            ]
        )
        assert rc == 0
        assert captured["python_exe"] == override
        assert captured["embed_dir"] == override.parent

    def test_dry_run_prints_chatterbox_interpreter(self, tmp_path, monkeypatch, capsys):
        dedicated = tmp_path / "python-chatterbox" / "python.exe"
        monkeypatch.setattr(bs, "chatterbox_python_exe", lambda *a, **k: dedicated)
        code = bs.main(["--dry-run", "--root", str(tmp_path)])
        assert code == 0
        err = capsys.readouterr().err
        assert "DRY-RUN chatterbox python" in err
        assert str(dedicated) in err

    def test_dry_run_chatterbox_host_fallback_label(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(bs, "chatterbox_python_exe", lambda *a, **k: None)
        code = bs.main(["--dry-run", "--root", str(tmp_path)])
        assert code == 0
        assert "<host fallback>" in capsys.readouterr().err
