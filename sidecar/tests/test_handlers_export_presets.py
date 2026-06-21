"""Registration-site smoke for the ``exportPresets.*`` group (WU2).

Asserts the single composition root ``register_all`` (handlers.py) wires the
four direct-return CRUD methods — and ONLY those four new keys — onto the
registry, each bound to a ``PresetStore`` under ``Services.data_dir`` (so the
catalog file is ``export-presets.json`` next to ``recipes.json``). Heavy seams
are untouched (this group is filesystem-only). Mirrors the recipes register-site
smoke in ``test_handlers.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio import handlers, protocol
from media_studio.handlers import Services
from media_studio.protocol import RpcContext

EXPORT_PRESET_METHODS = {
    "exportPresets.list",
    "exportPresets.save",
    "exportPresets.delete",
    "exportPresets.reset",
}


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=None)


def test_register_all_wires_export_preset_methods(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert set(registered) >= EXPORT_PRESET_METHODS


def test_register_all_adds_only_the_four_export_preset_keys(tmp_path: Path) -> None:
    """No stray ``exportPresets.*`` key beyond the documented four (acceptance 1)."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    export_keys = {k for k in registered if k.startswith("exportPresets.")}
    assert export_keys == EXPORT_PRESET_METHODS


def test_export_presets_list_bound_to_data_dir_seeds(tmp_path: Path) -> None:
    """The registered handler is the live catalog: list returns the three seeds,
    and the catalog file lands under ``Services.data_dir`` as ``export-presets.json``."""
    data_dir = tmp_path / "d"
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=data_dir),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    out = registered["exportPresets.list"]({}, _ctx())
    assert {p["id"] for p in out["presets"]} == {"tiktok", "reels", "shorts"}
    assert (data_dir / "export-presets.json").exists()


def test_export_presets_registered_on_real_protocol(tmp_path: Path) -> None:
    """register_all onto the real registry installs the keys (conftest restores)."""
    handlers.register_all(services=Services(data_dir=tmp_path / "d"))
    for method in EXPORT_PRESET_METHODS:
        assert method in protocol.METHODS
