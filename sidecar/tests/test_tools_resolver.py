"""Tests for media_studio.tools_resolver (T5).

Pure path logic — every chain is exercised against tmp_path trees with
injected env mappings / which() fakes. No subprocess, no network, no real
%APPDATA% (MEDIA_STUDIO_CONFIG_DIR is monkeypatched where detect probes
resolve the assets root themselves).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from media_studio import ffmpeg as ffmpeg_mod
from media_studio import tools_resolver as tr
from media_studio.assets import manifest


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


@pytest.fixture()
def isolated_dev_dir(tmp_path, monkeypatch):
    """Point the dev-path link of the llama chain at an EMPTY tmp dir so a real
    D:/tools install on the dev machine can never leak into assertions."""
    dev = tmp_path / "devtools"
    dev.mkdir()
    monkeypatch.setattr(tr, "DEV_LLAMA_DIR", str(dev))
    return dev


# --------------------------------------------------------------------------- #
# llama-server chain
# --------------------------------------------------------------------------- #
class TestResolveLlamaServer:
    def test_settings_file_wins(self, tmp_path, isolated_dev_dir):
        exe = _touch(tmp_path / "custom" / "my-llama.exe")
        # env + appdata also populated — settings must still win
        env_exe = _touch(tmp_path / "env" / tr.LLAMA_EXE)
        _touch(tmp_path / "root" / tr.TOOL_DIR_CUDA / tr.LLAMA_EXE)
        found = tr.resolve_llama_server(
            {"llamaServerPath": str(exe)},
            env={tr.ENV_LLAMA_SERVER: str(env_exe)},
            root=tmp_path / "root",
        )
        assert found == str(exe)

    def test_settings_dir_resolves_exe_inside(self, tmp_path, isolated_dev_dir):
        exe = _touch(tmp_path / "lls" / tr.LLAMA_EXE)
        found = tr.resolve_llama_server({"llamaServerPath": str(tmp_path / "lls")}, env={}, root=tmp_path / "root")
        assert found == str(exe)

    def test_missing_settings_falls_to_env(self, tmp_path, isolated_dev_dir):
        env_exe = _touch(tmp_path / "env" / tr.LLAMA_EXE)
        found = tr.resolve_llama_server(
            {"llamaServerPath": str(tmp_path / "nope")},  # does not exist
            env={tr.ENV_LLAMA_SERVER: str(env_exe)},
            root=tmp_path / "root",
        )
        assert found == str(env_exe)

    def test_env_dir_form_accepted(self, tmp_path, isolated_dev_dir):
        exe = _touch(tmp_path / "envdir" / tr.LLAMA_EXE)
        found = tr.resolve_llama_server({}, env={tr.ENV_LLAMA_SERVER: str(tmp_path / "envdir")}, root=tmp_path / "r")
        assert found == str(exe)

    def test_appdata_cuda_preferred_over_cpu(self, tmp_path, isolated_dev_dir):
        root = tmp_path / "root"
        cuda = _touch(root / tr.TOOL_DIR_CUDA / tr.LLAMA_EXE)
        _touch(root / tr.TOOL_DIR_CPU / tr.LLAMA_EXE)
        found = tr.resolve_llama_server({}, env={}, root=root)
        assert found == str(cuda)

    def test_appdata_cpu_when_no_cuda(self, tmp_path, isolated_dev_dir):
        root = tmp_path / "root"
        cpu = _touch(root / tr.TOOL_DIR_CPU / tr.LLAMA_EXE)
        found = tr.resolve_llama_server({}, env={}, root=root)
        assert found == str(cpu)

    def test_dev_path_is_last(self, tmp_path, isolated_dev_dir):
        dev_exe = _touch(isolated_dev_dir / tr.LLAMA_EXE)
        found = tr.resolve_llama_server({}, env={}, root=tmp_path / "empty")
        assert found == str(dev_exe)

    def test_whole_chain_miss_returns_none(self, tmp_path, isolated_dev_dir):
        assert tr.resolve_llama_server({}, env={}, root=tmp_path / "empty") is None


# --------------------------------------------------------------------------- #
# node-runner chain
# --------------------------------------------------------------------------- #
class TestResolveNodeRunner:
    def test_settings_wins(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tr, "REPO_ROOT", tmp_path / "norepo")
        exe = _touch(tmp_path / "el" / tr.ELECTRON_EXE)
        env_exe = _touch(tmp_path / "env-el" / tr.ELECTRON_EXE)
        found = tr.resolve_node_runner(
            {tr.SETTING_NODE_RUNNER: str(exe)},
            env={tr.ENV_NODE_RUNNER: str(env_exe)},
            which=lambda _name: None,
        )
        assert found == str(exe)

    def test_env_injected_by_supervisor(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tr, "REPO_ROOT", tmp_path / "norepo")
        env_exe = _touch(tmp_path / "app.exe")
        found = tr.resolve_node_runner({}, env={tr.ENV_NODE_RUNNER: str(env_exe)}, which=lambda _name: None)
        assert found == str(env_exe)

    def test_dev_electron_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tr, "REPO_ROOT", tmp_path)
        dev = _touch(tmp_path / "app" / "node_modules" / "electron" / "dist" / tr.ELECTRON_EXE)
        found = tr.resolve_node_runner({}, env={}, which=lambda _name: None)
        assert found == str(dev)

    def test_node_on_path_last_resort(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tr, "REPO_ROOT", tmp_path / "norepo")
        found = tr.resolve_node_runner({}, env={}, which=lambda name: "/usr/bin/node" if name == "node" else None)
        assert found == "/usr/bin/node"

    def test_whole_chain_miss_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tr, "REPO_ROOT", tmp_path / "norepo")
        assert tr.resolve_node_runner({}, env={}, which=lambda _name: None) is None


# --------------------------------------------------------------------------- #
# ffmpeg delegation + wsl probe
# --------------------------------------------------------------------------- #
class TestFfmpegAndWsl:
    def test_ffmpeg_delegates_to_ffmpeg_module(self, monkeypatch):
        calls = []

        def fake_resolve(name, settings=None):
            calls.append((name, settings))
            return f"/bin/{name}"

        monkeypatch.setattr(ffmpeg_mod, "resolve_binary", fake_resolve)
        assert tr.resolve_tool("ffmpeg", {"ffmpegPath": "x"}) == "/bin/ffmpeg"
        assert tr.resolve_tool("ffprobe") == "/bin/ffprobe"
        assert calls[0] == ("ffmpeg", {"ffmpegPath": "x"})

    def test_ffmpeg_miss_maps_to_none(self, monkeypatch):
        def raise_nf(name, settings=None):
            raise ffmpeg_mod.FfmpegNotFound(name)

        monkeypatch.setattr(ffmpeg_mod, "resolve_binary", raise_nf)
        assert tr.resolve_tool("ffmpeg") is None

    def test_wsl_available_true_false(self):
        assert tr.wsl_available(which=lambda name: "C:/wsl.exe") is True
        assert tr.wsl_available(which=lambda name: None) is False

    def test_resolve_tool_wsl_returns_path(self):
        assert tr.resolve_tool("wsl", which=lambda name: "C:/Windows/wsl.exe") == "C:/Windows/wsl.exe"


# --------------------------------------------------------------------------- #
# resolve_tool / require_tool surface
# --------------------------------------------------------------------------- #
class TestPublicSurface:
    def test_unknown_tool_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown tool"):
            tr.resolve_tool("frobnicator")

    def test_require_tool_returns_hit(self, tmp_path, isolated_dev_dir):
        exe = _touch(tmp_path / "x" / tr.LLAMA_EXE)
        assert tr.require_tool("llama-server", {"llamaServerPath": str(exe)}, env={}, root=tmp_path / "r") == str(exe)

    def test_require_tool_raises_with_fix_hint(self, tmp_path, isolated_dev_dir):
        with pytest.raises(tr.ToolNotFound, match="llamaServerPath"):
            tr.require_tool("llama-server", {}, env={}, root=tmp_path / "empty")

    def test_require_tool_node_hint_names_supervisor_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tr, "REPO_ROOT", tmp_path / "norepo")
        with pytest.raises(tr.ToolNotFound, match=tr.ENV_NODE_RUNNER):
            tr.require_tool("node-runner", {}, env={}, which=lambda _n: None)


# --------------------------------------------------------------------------- #
# tool-asset registration (U4 manifest entries)
# --------------------------------------------------------------------------- #
class TestToolAssets:
    def test_llama_assets_registered_as_pinned_tools(self):
        for name in (tr.LLAMA_CUDA_ASSET, tr.LLAMA_CUDART_ASSET, tr.LLAMA_CPU_ASSET):
            entry = manifest.get_asset(name)
            assert entry is not None, name
            assert entry.kind == "tool"
            assert entry.installer == "download"
            # PINNED url: the release tag is part of the download path (A6.5)
            assert str(entry.url).startswith(
                f"https://github.com/ggml-org/llama.cpp/releases/download/{tr.LLAMA_RELEASE_TAG}/"
            )
            assert entry.dest.startswith("tools/downloads/")
            assert entry.detect is not None

    def test_register_is_idempotent(self):
        # identical re-register must be a no-op (module re-import safety)
        tr.register_tool_assets()
        assert manifest.get_asset(tr.LLAMA_CUDA_ASSET) is not None

    def test_tool_archives_map_onto_manifest(self):
        for arch in tr.TOOL_ARCHIVES:
            assert manifest.get_asset(arch.asset) is not None
            assert arch.extract_to.startswith("tools/")
        # cudart extracts INTO the cuda dir (DLLs must sit beside the exe)
        by_asset = {a.asset: a.extract_to for a in tr.TOOL_ARCHIVES}
        assert by_asset[tr.LLAMA_CUDART_ASSET] == by_asset[tr.LLAMA_CUDA_ASSET]


# --------------------------------------------------------------------------- #
# detect probes (settings -> extracted under the assets root -> dev path)
# --------------------------------------------------------------------------- #
class TestDetectProbes:
    def test_detect_cuda_finds_extracted_exe(self, tmp_path, monkeypatch, isolated_dev_dir):
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
        exe = _touch(tmp_path / tr.TOOL_DIR_CUDA / tr.LLAMA_EXE)
        assert tr.detect_llama_cuda({}) == str(exe)

    def test_detect_cuda_settings_path_wins(self, tmp_path, monkeypatch, isolated_dev_dir):
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
        exe = _touch(tmp_path / "somewhere" / tr.LLAMA_EXE)
        assert tr.detect_llama_cuda({"llamaServerPath": str(exe)}) == str(exe)

    def test_detect_cuda_dev_path_counts_as_installed(self, tmp_path, monkeypatch, isolated_dev_dir):
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path / "empty"))
        dev_exe = _touch(isolated_dev_dir / tr.LLAMA_EXE)
        assert tr.detect_llama_cuda({}) == str(dev_exe)

    def test_detect_cuda_none_when_absent(self, tmp_path, monkeypatch, isolated_dev_dir):
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path / "empty"))
        assert tr.detect_llama_cuda({}) is None

    def test_detect_cpu(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
        assert tr.detect_llama_cpu({}) is None
        exe = _touch(tmp_path / tr.TOOL_DIR_CPU / tr.LLAMA_EXE)
        assert tr.detect_llama_cpu({}) == str(exe)

    def test_detect_cudart_dll(self, tmp_path, monkeypatch, isolated_dev_dir):
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
        assert tr.detect_llama_cudart({}) is None
        dll = _touch(tmp_path / tr.TOOL_DIR_CUDA / "cudart64_12.dll")
        assert tr.detect_llama_cudart({}) == str(dll)
