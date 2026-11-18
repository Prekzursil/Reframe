"""media_studio.handlers - the composition root (F4b: split into a package).

Re-exports the former monolithic handlers.py public surface so
`media_studio.handlers.<name>` keeps working byte-identically: the Services
class, register_all, the module logger, the INVALID_PARAMS validators, and the
pure wire helpers a few tests import directly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._shared import _invalid, _require_number, _require_str, _routing_block, log
from ._wire import (
    _advisor_report_to_wire,
    _coerce_tier,
    _evenly_spaced,
    _function_readiness_items,
    _js_number,
    _missing_tier_assets,
    _provider_has_key,
    _readiness_item,
    _routed_cloud_provider,
    _run_phase8_signals,
    _self_ffmpeg_run,
    _self_ffprobe,
    _self_test_report_to_wire,
    _signals_summary,
    _tier_readiness_items,
)
if TYPE_CHECKING:  # imported lazily below; a module-level import here is the
    from ._services import Services  # runtime cycle _services -> handlers.*

    from .composition import register_all


def __getattr__(name: str) -> Any:
    """Lazy re-export of the cycle-forming names (PEP 562).

    ``_services`` imports every ``*_ops`` module at class-body time and the
    ops modules TYPE_CHECKING-import ``Services`` back; importing either of
    these eagerly from the package ``__init__`` closed a runtime cycle that
    CodeQL flagged ~150 times (py/unsafe-cyclic-import). The public surface
    (``handlers.Services``, ``handlers.register_all``, the ``*_ops``
    submodules) keeps working exactly as before — resolved on first access.
    """
    if name == "Services":
        from ._services import Services

        return Services
    if name == "register_all":
        from .composition import register_all

        return register_all
    if name in {
        "ai_ops",
        "director_ops",
        "library_ops",
        "media_ops",
        "providers_ops",
        "shortmaker_ops",
        "system_ops",
        "vision_ops",
    }:
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Services",
    "register_all",
    "log",
    "_invalid",
    "_require_str",
    "_require_number",
    "_routing_block",
    "_self_ffmpeg_run",
    "_self_ffprobe",
    "_evenly_spaced",
    "_js_number",
    "_coerce_tier",
    "_signals_summary",
    "_missing_tier_assets",
    "_tier_readiness_items",
    "_function_readiness_items",
    "_routed_cloud_provider",
    "_provider_has_key",
    "_readiness_item",
    "_advisor_report_to_wire",
    "_self_test_report_to_wire",
    "_run_phase8_signals",
]
