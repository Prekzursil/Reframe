"""Shared handler primitives (F4b split): wire-coercion dataclasses, the
INVALID_PARAMS validators, the result type aliases, and the module logger.
Imported by every handlers/*_ops module and the composition root."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import ErrorCode, RpcError
from ..util import get_logger

log = get_logger("media_studio.handlers")

Video = dict[str, Any]
SubtitleTrack = dict[str, Any]
Candidate = dict[str, Any]


@dataclass(frozen=True)
class _BudgetRequest:
    """A wire-coerced budget request (satisfies ``budget.BudgetRequest`` duck-type).

    ``target_size`` is the discrete output count (``None`` -> the budget default);
    the two byte fields are the per-request egress split by data kind.
    """

    target_size: int | None
    text_bytes: int
    frame_bytes: int


@dataclass(frozen=True)
class _LocalPoolEntry:
    """A single local backstop pool entry (satisfies ``budget.PoolEntry``)."""

    provider: str = "local"
    local: bool = True


@dataclass(frozen=True)
class _LocalOnlyPool:
    """A local-only fallback pool used when the provider module is a test stub.

    Satisfies :func:`budget.estimate`'s pool shape (``.entries`` of provider/local
    items); the budget then reports local-only with zero cloud egress.
    """

    entries: tuple[_LocalPoolEntry, ...] = (_LocalPoolEntry(),)


@dataclass(frozen=True)
class _DirectorPlanEntry:
    """A stored Director plan (WU-plan-rpc): the validated EditPlan + its context.

    ``video_id`` correlates the plan to its source for ``director.apply``;
    ``messages`` is the planner chat (replayed by ``director.previewCost`` so the
    pre-flight cache key matches the plan step exactly — ZERO new LLM calls).
    """

    plan: Any  # edit_plan.EditPlan (typed in the handler; Any here to keep imports light)
    video_id: str
    messages: tuple[dict[str, str], ...]


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _require_number(params: dict[str, Any], key: str, default: float) -> float:
    """Validate ``params[key]`` as a real number, returning ``default`` when absent.

    F3b: rejects non-numeric values — and ``bool`` (``True``/``False`` are
    ``int`` subclasses but never a valid count/coordinate/fps) — with a clean
    :data:`ErrorCode.INVALID_PARAMS` instead of letting a string/None crash
    deeper in the pipeline (``float("x")`` / ``int(None)``).
    """
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{key} must be a number")
    return float(value)


def _routing_block(routing: dict[str, Any]) -> dict[str, Any]:
    """Extract the persistable ``{perFunction}`` block from a preset routing.

    ``presets.apply_preset`` returns ``{activePreset, perFunction}``; the settings
    ``routing`` key stores only the ``{perFunction}`` map (``activePreset`` is its
    own settings key), so this drops the redundant ``activePreset`` field.
    """
    return {"perFunction": routing["perFunction"]}
