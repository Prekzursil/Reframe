"""Tests for media_studio.settings_store (the §2 settings.* persistence layer).

Pure filesystem I/O, no heavy imports. The config path is injected at a tmp dir so
no real per-user config file is ever touched.
"""

from __future__ import annotations

import json
import os as _real_os
from pathlib import Path

import pytest
from media_studio.settings_store import (
    DEFAULT_SETTINGS,
    SettingsStore,
    default_config_dir,
)


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "settings.json")


def test_get_returns_defaults_when_no_file(store: SettingsStore) -> None:
    out = store.get()
    # §2: includes {useCloud, modelsDir, ffmpegPath}
    assert out["useCloud"] is False
    assert out["modelsDir"] == ""
    assert out["ffmpegPath"] == ""


def test_brand_kit_defaults_present(store: SettingsStore) -> None:
    """P4 §8d / C12: the brand-kit keys are discoverable in the defaults."""
    out = store.get()
    assert out["brandLogoPath"] == ""
    assert out["brandCaptionTemplate"] == ""
    assert out["brandFontFamily"] == ""


def test_no_output_dir_default(store: SettingsStore) -> None:
    """C12: there is intentionally NO ``outputDir`` (exports stay in exports_dir)."""
    assert "outputDir" not in store.get()
    assert "outputDir" not in DEFAULT_SETTINGS


def test_brand_kit_keys_round_trip(store: SettingsStore) -> None:
    store.set({"brandLogoPath": "C:/brand/logo.png", "brandFontFamily": "Inter"})
    out = store.get()
    assert out["brandLogoPath"] == "C:/brand/logo.png"
    assert out["brandFontFamily"] == "Inter"
    assert out["brandCaptionTemplate"] == ""  # untouched -> default


def test_set_merges_and_persists(store: SettingsStore) -> None:
    out = store.set({"useCloud": True})
    assert out["useCloud"] is True
    # A fresh read sees the persisted value (round-trips through disk).
    assert store.get()["useCloud"] is True


def test_set_is_a_partial_merge(store: SettingsStore) -> None:
    store.set({"modelsDir": "D:/models"})
    store.set({"useCloud": True})  # must NOT wipe modelsDir
    out = store.get()
    assert out["modelsDir"] == "D:/models"
    assert out["useCloud"] is True


def test_set_persists_cloud_api_key_but_not_in_a_project(store: SettingsStore, tmp_path: Path) -> None:
    # The key lives ONLY in the per-user config file, never a project folder (§0).
    store.set({"cloudApiKey": "sk-secret"})
    assert store.get()["cloudApiKey"] == "sk-secret"
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["cloudApiKey"] == "sk-secret"


def test_set_rejects_non_dict(store: SettingsStore) -> None:
    with pytest.raises(ValueError):
        store.set(["not", "a", "dict"])  # type: ignore[arg-type]


def test_corrupt_file_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = SettingsStore(path)
    assert store.get() == dict(DEFAULT_SETTINGS)


def test_default_config_dir_honors_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path / "cfg"))
    assert default_config_dir() == tmp_path / "cfg"


class _OsShim:
    """A stand-in for the ``os`` module that overrides only ``name``.

    Everything else (``environ``, ``path``, ...) delegates to the real ``os`` so
    that ``pathlib.Path()`` — which reads the *real* ``os.name`` to pick its
    flavor — is unaffected. This lets the POSIX/Windows branches of
    ``default_config_dir`` be exercised on either host without forcing pathlib to
    instantiate a foreign-flavor path (which raises on a mismatched OS).
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, attr: str):  # delegate everything else to real os
        return getattr(_real_os, attr)


def test_default_config_dir_windows_uses_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows branch (os.name == "nt"): %APPDATA%/media-studio.
    monkeypatch.delenv("MEDIA_STUDIO_CONFIG_DIR", raising=False)
    monkeypatch.setattr("media_studio.settings_store.os", _OsShim("nt"))
    monkeypatch.setenv("APPDATA", "/roaming")
    out = default_config_dir()
    assert out.parts[-2:] == ("roaming", "media-studio")


def test_default_config_dir_windows_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows branch with no APPDATA -> expanduser("~").
    monkeypatch.delenv("MEDIA_STUDIO_CONFIG_DIR", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    shim = _OsShim("nt")
    shim.path = type("P", (), {"expanduser": staticmethod(lambda _p: "/home/me")})()
    monkeypatch.setattr("media_studio.settings_store.os", shim)
    out = default_config_dir()
    assert out.parts[-3:] == ("home", "me", "media-studio")


def test_default_config_dir_posix_uses_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    # POSIX branch with XDG_CONFIG_HOME set.
    monkeypatch.delenv("MEDIA_STUDIO_CONFIG_DIR", raising=False)
    monkeypatch.setattr("media_studio.settings_store.os", _OsShim("posix"))
    monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg/config")
    out = default_config_dir()
    assert out.parts[-3:] == ("xdg", "config", "media-studio")


def test_default_config_dir_posix_falls_back_to_dotconfig(monkeypatch: pytest.MonkeyPatch) -> None:
    # POSIX branch with no XDG -> ~/.config/media-studio.
    monkeypatch.delenv("MEDIA_STUDIO_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    shim = _OsShim("posix")
    shim.path = type("P", (), {"expanduser": staticmethod(lambda _p: "/home/me")})()
    monkeypatch.setattr("media_studio.settings_store.os", shim)
    out = default_config_dir()
    assert out.parts[-4:] == ("home", "me", ".config", "media-studio")
