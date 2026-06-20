"""Registration-site smoke for the ``templates.*`` group (WU5).

Asserts the single composition root ``register_all`` (handlers.py) wires the four
``templates.*`` methods — and ONLY those four new keys — onto the registry, each
bound to a :class:`templates.TemplateStore` under ``Services.data_dir`` (so the
file is ``templates.json`` next to ``recipes.json`` / ``export-presets.json``),
and that the ``apply`` fan-out resolves preset ids from the live export-preset
catalog wired in the same root. Mirrors the exportPresets register-site smoke.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio.handlers import Services
from media_studio.protocol import RpcContext, RpcError

TEMPLATE_METHODS = {
    "templates.list",
    "templates.save",
    "templates.delete",
    "templates.apply",
}


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=None)


def test_register_all_wires_template_methods(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert set(registered) >= TEMPLATE_METHODS


def test_register_all_adds_only_the_four_template_keys(tmp_path: Path) -> None:
    """No stray ``templates.*`` key beyond the documented four (acceptance 4)."""
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    template_keys = {k for k in registered if k.startswith("templates.")}
    assert template_keys == TEMPLATE_METHODS


def test_templates_save_list_bound_to_data_dir(tmp_path: Path) -> None:
    """The registered handler is the live store: a saved template round-trips and
    the file lands under ``Services.data_dir`` as ``templates.json``."""
    data_dir = tmp_path / "d"
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=data_dir),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    registered["templates.save"](
        {
            "template": {
                "id": "tpl",
                "name": "T",
                "steps": [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}}],
                "exportTargets": ["tiktok"],
            }
        },
        _ctx(),
    )
    out = registered["templates.list"]({}, _ctx())
    assert [t["id"] for t in out["templates"]] == ["tpl"]
    assert (data_dir / "templates.json").exists()


def test_templates_apply_resolves_presets_from_wired_catalog(tmp_path: Path) -> None:
    """The wired ``apply`` fan-out resolves a real seed preset id (``tiktok``) from
    the export-preset catalog registered in the same composition root — proving the
    presets_provider is bound to the live catalog, not an empty map."""
    data_dir = tmp_path / "d"
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=data_dir),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    # apply runs the pure pre-job path (bind + fan-out over the live catalog)
    # BEFORE the registry check, so a null registry isolates the fan-out outcome:
    #   * a KNOWN seed id ("tiktok") resolves -> reaches the no-registry refusal
    #     ("no job registry available"), proving the catalog is bound + non-empty;
    #   * an UNKNOWN id ("__nope__") fails loud in the fan-out itself.
    registered["templates.save"](
        {
            "template": {
                "id": "tpl",
                "name": "T",
                "steps": [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok"]}}],
                "exportTargets": ["tiktok"],
            }
        },
        _ctx(),
    )
    with pytest.raises(RpcError, match="no job registry available"):
        registered["templates.apply"]({"templateId": "tpl", "videoId": "v1"}, _ctx())

    registered["templates.save"](
        {
            "template": {
                "id": "bad",
                "name": "Bad",
                "steps": [{"method": "shortmaker.export", "params": {"exportTargets": ["__nope__"]}}],
                "exportTargets": ["__nope__"],
            }
        },
        _ctx(),
    )
    with pytest.raises(RpcError, match="export target not found"):
        registered["templates.apply"]({"templateId": "bad", "videoId": "v1"}, _ctx())


def test_templates_registered_on_real_protocol(tmp_path: Path) -> None:
    """register_all onto the real registry installs the keys (conftest restores)."""
    handlers.register_all(services=Services(data_dir=tmp_path / "d"))
    for method in TEMPLATE_METHODS:
        assert method in protocol.METHODS
