"""Assets subsystem: manifest registry + download/runtime-setup manager + RPC.

PLAN-P2 U4 (shared infra, ONE owner). Other tracks register their artifacts
with a single call::

    from media_studio.assets.manifest import register_asset
    register_asset(name=..., kind=..., size_mb=..., dest=..., url=..., sha256=...)

The wiring agent registers the RPC surface from ``handlers.register_all``::

    from .assets import rpc as _assets_rpc
    _assets_rpc.register(root=svc.data_dir, settings_provider=svc.settings.get)

Import-light: no httpx / huggingface_hub / subprocess use at import time (the
manager reaches them lazily inside job bodies). No native modules — nothing
here needs ``__main__._preimport_native_modules`` (A6 lesson 1 n/a).
"""

from __future__ import annotations

from .manager import AssetError, AssetManager
from .manifest import AssetEntry, all_assets, get_asset, register_asset

__all__ = [
    "AssetEntry",
    "AssetError",
    "AssetManager",
    "all_assets",
    "get_asset",
    "register_asset",
]
