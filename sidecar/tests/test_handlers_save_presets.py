"""WU-10 handlers: ``savePresets.list/apply/upsert/remove``.

A named ``{autosave, exportDefaults}`` bundle persisted under the ``savePresets``
settings key. Mirrors ``providers.applyPreset`` (resolve -> persist to settings)
but stores user-named bundles rather than routing presets.

The settings ``set`` is a SHALLOW top-level merge (``settings_store.py``: writing
``savePresets`` REPLACES the whole block), so every handler read-modify-writes the
full ``savePresets`` block to preserve ``presets`` and ``active``. Tests pin the
blind-merge invariant (sibling keys untouched), the missing-name error, and the
remove-active branch.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio import handlers as H
from media_studio import protocol


def _ctx() -> Any:
    return protocol.RpcContext(emit_notification=lambda _msg: None, jobs=None)


def _svc(tmp_path: Any) -> H.Services:
    return H.Services(data_dir=str(tmp_path))


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_save_presets_handlers_registered(tmp_path: Any) -> None:
    registered: dict[str, Any] = {}
    H.register_all(_svc(tmp_path), register=lambda name, fn: registered.__setitem__(name, fn))
    assert "savePresets.list" in registered
    assert "savePresets.apply" in registered
    assert "savePresets.upsert" in registered
    assert "savePresets.remove" in registered


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_list_empty_default(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    out = svc.save_presets_list({}, _ctx())
    assert out == {"presets": {}, "active": ""}


# --------------------------------------------------------------------------- #
# upsert
# --------------------------------------------------------------------------- #


def test_upsert_creates_named_bundle(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    autosave = {"enabled": False, "debounceMs": 500}
    export_defaults = {"subtitleFormat": "vtt", "nleFormat": "fcpxml", "nleFps": 24}
    out = svc.save_presets_upsert({"name": "a", "autosave": autosave, "exportDefaults": export_defaults}, _ctx())
    assert out["presets"]["a"]["autosave"] == autosave
    assert out["presets"]["a"]["exportDefaults"] == export_defaults
    # Round-trips through list.
    listed = svc.save_presets_list({}, _ctx())
    assert listed["presets"]["a"]["autosave"] == autosave


def test_upsert_omitted_fields_default_to_empty(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    out = svc.save_presets_upsert({"name": "bare"}, _ctx())
    assert out["presets"]["bare"] == {"autosave": {}, "exportDefaults": {}}


def test_upsert_updates_existing_in_place(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    svc.save_presets_upsert({"name": "a", "autosave": {"enabled": True}}, _ctx())
    out = svc.save_presets_upsert({"name": "a", "autosave": {"enabled": False}}, _ctx())
    # One entry, updated (not duplicated).
    assert list(out["presets"].keys()) == ["a"]
    assert out["presets"]["a"]["autosave"] == {"enabled": False}


def test_upsert_preserves_siblings(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    svc.save_presets_upsert({"name": "a", "autosave": {"enabled": True}}, _ctx())
    svc.save_presets_upsert({"name": "b", "autosave": {"enabled": False}}, _ctx())
    out = svc.save_presets_list({}, _ctx())
    assert set(out["presets"].keys()) == {"a", "b"}


def test_upsert_missing_name_is_invalid(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.save_presets_upsert({}, _ctx())


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #


def test_apply_sets_active_and_returns_preset(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    autosave = {"enabled": True, "debounceMs": 1000}
    svc.save_presets_upsert({"name": "a", "autosave": autosave}, _ctx())
    out = svc.save_presets_apply({"name": "a"}, _ctx())
    assert out["active"] == "a"
    assert out["savePreset"]["autosave"] == autosave
    # Persisted.
    assert svc.save_presets_list({}, _ctx())["active"] == "a"


def test_apply_missing_name_is_invalid(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.save_presets_apply({}, _ctx())


def test_apply_unknown_preset_is_a_typed_error(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.save_presets_apply({"name": "missing"}, _ctx())


# --------------------------------------------------------------------------- #
# remove
# --------------------------------------------------------------------------- #


def test_remove_drops_preset(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    svc.save_presets_upsert({"name": "a"}, _ctx())
    svc.save_presets_upsert({"name": "b"}, _ctx())
    out = svc.save_presets_remove({"name": "a"}, _ctx())
    assert set(out["presets"].keys()) == {"b"}


def test_remove_active_resets_active(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    svc.save_presets_upsert({"name": "a"}, _ctx())
    svc.save_presets_apply({"name": "a"}, _ctx())
    out = svc.save_presets_remove({"name": "a"}, _ctx())
    assert out["active"] == ""
    assert "a" not in out["presets"]


def test_remove_non_active_keeps_active(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    svc.save_presets_upsert({"name": "a"}, _ctx())
    svc.save_presets_upsert({"name": "b"}, _ctx())
    svc.save_presets_apply({"name": "a"}, _ctx())
    out = svc.save_presets_remove({"name": "b"}, _ctx())
    assert out["active"] == "a"
    assert set(out["presets"].keys()) == {"a"}


def test_remove_missing_name_is_invalid(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.save_presets_remove({}, _ctx())


def test_remove_unknown_preset_is_a_typed_error(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    with pytest.raises(protocol.RpcError):
        svc.save_presets_remove({"name": "ghost"}, _ctx())


# --------------------------------------------------------------------------- #
# Blind-merge invariant: sibling settings keys survive a savePresets write.
# --------------------------------------------------------------------------- #


def test_save_presets_write_preserves_sibling_settings(tmp_path: Any) -> None:
    svc = _svc(tmp_path)
    svc.settings.set({"lastOpenedVideoId": "vid-42"})
    svc.save_presets_upsert({"name": "a", "autosave": {"enabled": True}}, _ctx())
    # The unrelated sibling key is untouched by the savePresets block replace.
    assert svc.settings.get()["lastOpenedVideoId"] == "vid-42"


def test_save_presets_block_handles_corrupt_existing_block(tmp_path: Any) -> None:
    # Defensive: a non-dict ``savePresets`` (corrupt settings) is treated as empty.
    svc = _svc(tmp_path)
    svc.settings.set({"savePresets": "garbage"})
    out = svc.save_presets_upsert({"name": "a"}, _ctx())
    assert out["presets"]["a"] == {"autosave": {}, "exportDefaults": {}}
    assert svc.save_presets_list({}, _ctx())["active"] == ""
