"""media_studio.handlers - the composition root (F4b: split into a package).

Re-exports the former monolithic handlers.py public surface so
`media_studio.handlers.<name>` keeps working byte-identically: the Services
class, register_all, the module logger, the INVALID_PARAMS validators, and the
pure wire helpers a few tests import directly."""

from __future__ import annotations

from ._services import Services
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
from .composition import register_all

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
