"""Tests for media_studio.settings_store (the §2 settings.* persistence layer).

Pure filesystem I/O, no heavy imports. The config path is injected at a tmp dir so
no real per-user config file is ever touched.
"""
from __future__ import annotations

import json
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
