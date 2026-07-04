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
    UnsafeConfigDirError,
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
    # SECURITY (adv-fix): the RPC-facing get() MUST NOT echo the full cloud key —
    # it is redacted to last-4 exactly like providers[].apiKeys. Only get_raw()
    # (the factory path, never registered over RPC) and the on-disk store keep the
    # live key. set() returns the redacted view too (no echo of a full key).
    redacted = store.set({"cloudApiKey": "sk-secret-1234"})
    assert redacted["cloudApiKey"] == "…1234"
    assert store.get()["cloudApiKey"] == "…1234"
    assert store.get_raw()["cloudApiKey"] == "sk-secret-1234"
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["cloudApiKey"] == "sk-secret-1234"


def test_get_does_not_redact_empty_cloud_api_key(store: SettingsStore) -> None:
    # An empty/absent cloud key must render as-is ("") — never "…" — so the UI
    # does not imply a key exists when none is set (the redact branch is skipped).
    store.set({"cloudApiKey": ""})
    assert store.get()["cloudApiKey"] == ""


def test_set_rejects_non_dict(store: SettingsStore) -> None:
    with pytest.raises(ValueError):
        store.set(["not", "a", "dict"])  # type: ignore[arg-type]


def test_corrupt_file_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = SettingsStore(path)
    assert store.get() == dict(DEFAULT_SETTINGS)


def test_default_config_dir_honors_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A4/R7: a SAFE absolute-local override is honored, but CANONICALIZED (realpath
    # resolves symlinks + normalizes) before use — so compare against the realpath.
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path / "cfg"))
    assert default_config_dir() == Path(_real_os.path.realpath(tmp_path / "cfg"))


# --------------------------------------------------------------------------- #
# A4/R7: MEDIA_STUDIO_CONFIG_DIR is attacker-influenceable; the sidecar (a second,
# independent consumer of the data root) must REFUSE a non-local / device / `..`
# override rather than pip-install models into it. Defense-in-depth mirror of the
# Electron dataRoot.ts guard.
# --------------------------------------------------------------------------- #
def test_default_config_dir_rejects_unc_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", "\\\\evil-host\\share\\data")
    with pytest.raises(UnsafeConfigDirError):
        default_config_dir()


def test_default_config_dir_rejects_posix_unc_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # A forward-slash double-separator (`//host/share`) is the same UNC shape.
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", "//evil-host/share/data")
    with pytest.raises(UnsafeConfigDirError):
        default_config_dir()


def test_default_config_dir_rejects_device_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", "\\\\.\\PhysicalDrive0")
    with pytest.raises(UnsafeConfigDirError):
        default_config_dir()


def test_default_config_dir_rejects_traversal_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", "/base/../etc/passwd")
    with pytest.raises(UnsafeConfigDirError):
        default_config_dir()


def test_default_config_dir_rejects_relative_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", "relative/data")
    with pytest.raises(UnsafeConfigDirError):
        default_config_dir()


def test_unsafe_config_dir_error_is_a_value_error() -> None:
    # It subclasses ValueError so existing broad `except ValueError` handlers still
    # catch it (the store already treats bad config as a ValueError family).
    assert issubclass(UnsafeConfigDirError, ValueError)


def test_default_config_dir_canonicalizes_a_safe_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A safe absolute-local override with a redundant `.` segment is normalized to
    # its realpath (the canonical form used at the filesystem sink).
    noisy = _real_os.path.join(str(tmp_path), ".", "cfg")
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", noisy)
    assert default_config_dir() == Path(_real_os.path.realpath(tmp_path / "cfg"))


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


# --------------------------------------------------------------------------- #
# WU-keys: providers/consent defaults + RAW-vs-REDACTED split
# --------------------------------------------------------------------------- #
def test_provider_hub_defaults_present(store: SettingsStore) -> None:
    out = store.get()
    assert out["providers"] == []
    assert out["consent"] == {"perProvider": {}}


def test_get_redacts_provider_api_keys(store: SettingsStore) -> None:
    store.set(
        {
            "providers": [
                {"id": "groq", "provider": "Groq", "apiKeys": ["gsk-secret-WXYZ", "gsk-second-7890"]},
            ]
        }
    )
    redacted = store.get()["providers"]
    assert redacted[0]["apiKeys"] == ["…WXYZ", "…7890"]
    # No full key crosses the RPC-facing get().
    blob = json.dumps(store.get())
    assert "gsk-secret-WXYZ" not in blob
    assert "gsk-second-7890" not in blob


def test_get_raw_returns_full_provider_keys(store: SettingsStore) -> None:
    store.set({"providers": [{"id": "groq", "apiKeys": ["gsk-full-raw-KEY1"]}]})
    raw = store.get_raw()["providers"]
    assert raw[0]["apiKeys"] == ["gsk-full-raw-KEY1"]
    # get() (redacted) and get_raw() (full) genuinely differ.
    assert store.get()["providers"][0]["apiKeys"] != raw[0]["apiKeys"]


def test_get_raw_persists_to_disk_unredacted(store: SettingsStore, tmp_path: Path) -> None:
    store.set({"providers": [{"id": "groq", "apiKeys": ["gsk-on-disk-RAW7"]}]})
    on_disk = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    # The persisted store is RAW (the factory reads it via get_raw); only get() redacts.
    assert on_disk["providers"][0]["apiKeys"] == ["gsk-on-disk-RAW7"]


def test_get_redaction_does_not_corrupt_other_fields(store: SettingsStore) -> None:
    store.set(
        {
            "providers": [
                {"id": "groq", "provider": "Groq", "baseUrl": "https://x/v1", "apiKeys": ["abcdEFGH"], "enabled": True}
            ],
            "consent": {"perProvider": {"Groq": {"text": True, "frames": False}}},
        }
    )
    out = store.get()
    p = out["providers"][0]
    assert p["provider"] == "Groq"
    assert p["baseUrl"] == "https://x/v1"
    assert p["enabled"] is True
    assert out["consent"] == {"perProvider": {"Groq": {"text": True, "frames": False}}}


def test_get_tolerates_non_list_providers(tmp_path: Path) -> None:
    # A corrupt/hand-edited settings file with a non-list providers value must
    # not crash the redacting get(): the redaction step is skipped and the bad
    # value is passed through (the false arm of the isinstance guard).
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"providers": "not-a-list"}), encoding="utf-8")
    store = SettingsStore(path)
    assert store.get()["providers"] == "not-a-list"


# --------------------------------------------------------------------------- #
# F4b: redacted get -> set round-trip must PRESERVE the RAW key (no silent loss)
# --------------------------------------------------------------------------- #
def test_set_preserves_raw_cloud_key_on_redacted_round_trip(store: SettingsStore) -> None:
    """Writing back the redacted cloudApiKey keeps the live RAW key on disk."""
    store.set({"cloudApiKey": "sk-secret-1234"})
    redacted = store.get()["cloudApiKey"]
    assert redacted == "…1234"
    # The UI reads the redacted view and writes the whole block back unchanged.
    store.set({"cloudApiKey": redacted, "useCloud": True})
    assert store.get_raw()["cloudApiKey"] == "sk-secret-1234"
    assert store.get_raw()["useCloud"] is True


def test_set_writes_a_genuinely_new_cloud_key(store: SettingsStore) -> None:
    """A non-redacted incoming cloudApiKey REPLACES the stored one (not preserved)."""
    store.set({"cloudApiKey": "sk-old-AAAA"})
    store.set({"cloudApiKey": "sk-new-BBBB"})
    assert store.get_raw()["cloudApiKey"] == "sk-new-BBBB"


def test_set_cloud_key_no_stored_value_passes_through(store: SettingsStore) -> None:
    """With nothing stored, an incoming cloudApiKey is written verbatim (no restore)."""
    store.set({"cloudApiKey": "…1234"})
    # No prior RAW key existed, so the placeholder cannot be restored; it persists.
    assert store.get_raw()["cloudApiKey"] == "…1234"


def test_set_non_str_cloud_key_passes_through(store: SettingsStore) -> None:
    """A non-string cloudApiKey value bypasses the restore guard and is stored."""
    store.set({"cloudApiKey": "sk-secret-1234"})
    store.set({"cloudApiKey": None})
    assert store.get_raw()["cloudApiKey"] is None


def test_set_preserves_raw_provider_keys_on_redacted_round_trip(store: SettingsStore) -> None:
    """Writing back redacted provider apiKeys keeps the live RAW keys on disk."""
    store.set({"providers": [{"id": "groq", "apiKeys": ["gsk-secret-WXYZ", "gsk-second-7890"]}]})
    redacted = store.get()["providers"]
    assert redacted[0]["apiKeys"] == ["…WXYZ", "…7890"]
    # Round-trip the redacted block back (UI edits an unrelated field).
    store.set({"providers": [{"id": "groq", "apiKeys": redacted[0]["apiKeys"], "enabled": False}]})
    raw = store.get_raw()["providers"]
    assert raw[0]["apiKeys"] == ["gsk-secret-WXYZ", "gsk-second-7890"]
    assert raw[0]["enabled"] is False


def test_set_provider_mixed_new_and_redacted_keys(store: SettingsStore) -> None:
    """A redacted key is restored while a sibling NEW key at a new index is kept."""
    store.set({"providers": [{"id": "groq", "apiKeys": ["gsk-keep-WXYZ"]}]})
    redacted = store.get()["providers"][0]["apiKeys"][0]
    # Index 0 is the redacted existing key; index 1 is a brand-new raw key.
    store.set({"providers": [{"id": "groq", "apiKeys": [redacted, "gsk-added-RAW2"]}]})
    raw = store.get_raw()["providers"][0]["apiKeys"]
    assert raw == ["gsk-keep-WXYZ", "gsk-added-RAW2"]


def test_set_unknown_provider_keys_pass_through(store: SettingsStore) -> None:
    """A provider with no stored counterpart writes its apiKeys verbatim."""
    store.set({"providers": [{"id": "new", "apiKeys": ["…WXYZ"]}]})
    assert store.get_raw()["providers"][0]["apiKeys"] == ["…WXYZ"]


def test_set_provider_without_apikeys_list_passes_through(store: SettingsStore) -> None:
    """A provider entry whose apiKeys is absent/non-list is left untouched."""
    store.set({"providers": [{"id": "groq", "apiKeys": ["gsk-raw-WXYZ"]}]})
    store.set({"providers": [{"id": "groq", "model": "x"}]})
    saved = store.get_raw()["providers"][0]
    assert saved == {"id": "groq", "model": "x"}


def test_set_non_dict_provider_entry_passes_through(store: SettingsStore) -> None:
    """A non-dict entry in the incoming providers list is preserved as-is."""
    store.set({"providers": ["not-a-dict"]})
    assert store.get_raw()["providers"] == ["not-a-dict"]


def test_set_tolerates_corrupt_stored_providers(tmp_path: Path) -> None:
    """A non-list / non-dict stored providers value never crashes the restore step."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"providers": "not-a-list"}), encoding="utf-8")
    store = SettingsStore(path)
    store.set({"providers": [{"id": "groq", "apiKeys": ["gsk-raw-WXYZ"]}]})
    assert store.get_raw()["providers"][0]["apiKeys"] == ["gsk-raw-WXYZ"]


def test_set_skips_corrupt_stored_provider_dict(tmp_path: Path) -> None:
    """Stored provider entries that are non-dict or lack id/apiKeys are skipped."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"providers": ["bad", {"id": 5, "apiKeys": ["x"]}, {"id": "groq", "apiKeys": "nope"}]}),
        encoding="utf-8",
    )
    store = SettingsStore(path)
    # None of the corrupt stored entries map a restorable key; new write wins.
    store.set({"providers": [{"id": "groq", "apiKeys": ["…WXYZ"]}]})
    assert store.get_raw()["providers"][0]["apiKeys"] == ["…WXYZ"]


def test_set_provider_non_str_id_passes_through(store: SettingsStore) -> None:
    """An incoming provider whose id is not a string skips the restore lookup."""
    store.set({"providers": [{"id": 5, "apiKeys": ["…WXYZ"]}]})
    assert store.get_raw()["providers"][0]["apiKeys"] == ["…WXYZ"]


def test_set_without_secret_keys_is_unaffected(store: SettingsStore) -> None:
    """A plain set (no cloudApiKey / providers) skips the restore branches entirely."""
    store.set({"useCloud": True})
    assert store.get_raw()["useCloud"] is True


# --------------------------------------------------------------------------- #
# WU-0 (ux-qol): additive QoL defaults + merge behavior the downstream WUs rely on
# --------------------------------------------------------------------------- #
def test_qol_defaults_present_exact(store: SettingsStore) -> None:
    """The four additive WU-0 keys land with their EXACT documented defaults."""
    out = store.get()
    assert out["lastOpenedVideoId"] == ""
    assert out["autosave"] == {"enabled": True, "debounceMs": 1500}
    assert out["exportDefaults"] == {"subtitleFormat": "srt", "nleFormat": "edl", "nleFps": 30}
    assert out["savePresets"] == {"presets": {}, "active": ""}


# --------------------------------------------------------------------------- #
# WU-spend-cap: monthly cumulative spend-cap settings (additive, default-off)
# --------------------------------------------------------------------------- #
def test_spend_cap_defaults_present_and_off(store: SettingsStore) -> None:
    """The spend-cap keys land OFF/0 so the cap is backward-compatibly disabled."""
    out = store.get()
    assert out["monthlySoftLimitCents"] == 0
    assert out["monthlyHardLimitCents"] == 0
    assert out["enforceMonthlyHardLimit"] is False


def test_spend_cap_keys_are_user_settable(store: SettingsStore) -> None:
    out = store.set(
        {
            "monthlySoftLimitCents": 500,
            "monthlyHardLimitCents": 2000,
            "enforceMonthlyHardLimit": True,
        }
    )
    assert out["monthlySoftLimitCents"] == 500
    assert out["monthlyHardLimitCents"] == 2000
    assert out["enforceMonthlyHardLimit"] is True


def test_export_defaults_exact_acceptance(store: SettingsStore) -> None:
    """Acceptance pin: DEFAULT_SETTINGS['exportDefaults'] is exactly the §spec dict."""
    assert DEFAULT_SETTINGS["exportDefaults"] == {
        "subtitleFormat": "srt",
        "nleFormat": "edl",
        "nleFps": 30,
    }


def test_qol_keys_round_trip(store: SettingsStore) -> None:
    """A scalar QoL key persists through the blind merge without disturbing siblings."""
    store.set({"lastOpenedVideoId": "vid-42"})
    out = store.get()
    assert out["lastOpenedVideoId"] == "vid-42"
    # Siblings remain at their defaults (untouched).
    assert out["autosave"] == {"enabled": True, "debounceMs": 1500}
    assert out["savePresets"] == {"presets": {}, "active": ""}


def test_save_presets_set_is_shallow_replace_not_deep_merge(store: SettingsStore) -> None:
    """settings.set is a SHALLOW dict.update merge (settings_store.py:167-182).

    Setting savePresets to a partial block REPLACES the whole block — `presets`
    is NOT preserved. This pins the REAL behavior (do not assume deep merge): a
    caller that wants to keep `presets` must send the full block. This is the
    contract WU-10/WU-11 must honor when they read/write savePresets.
    """
    store.set({"savePresets": {"presets": {"p1": {"x": 1}}, "active": "p1"}})
    # A partial update with only `active` overwrites the entire savePresets block.
    store.set({"savePresets": {"active": "p2"}})
    out = store.get()
    assert out["savePresets"] == {"active": "p2"}
    assert "presets" not in out["savePresets"]


def test_autosave_partial_set_round_trips(store: SettingsStore) -> None:
    """Setting autosave round-trips; like savePresets, it is a shallow replace."""
    store.set({"autosave": {"enabled": False}})
    out = store.get()
    assert out["autosave"] == {"enabled": False}
    # Other top-level QoL keys are untouched by the shallow top-level merge.
    assert out["exportDefaults"] == {"subtitleFormat": "srt", "nleFormat": "edl", "nleFps": 30}
