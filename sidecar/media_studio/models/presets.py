"""Provider-Hub presets + per-function routing (WU-presets).

A **pure** seam (no network, no heavy deps, no cross-import of the sibling Hub
modules at runtime): given an INJECTED catalog and a settings mapping it resolves
one of three smart presets into a concrete ``routing.perFunction`` map, ranks
per-function model candidates from the catalog, and answers the first-run
local-vs-cloud default.

The five Reframe AI functions (the task seams) — each maps to one catalog task
tier (PLAN §WU-presets · CATALOG-SEED tasks 1..5):

  * ``select``      — Moment-Find / Select   (task 1)
  * ``subtitles``   — Caption / Title / Hook (task 2)
  * ``translation`` — Translation            (task 3)
  * ``vision``      — Vision / OCR           (task 4)
  * ``editPlan``    — Edit-Plan generation   (task 5)

The catalog is **duck-typed** so the ranking logic never hard-depends on
``catalog.py``. A catalog need only expose ``all() -> Iterable[entry]`` where each
``entry`` carries: ``id: str``, ``provider: str``, ``capabilities: Sequence[str]``
(includes ``"vision"`` for multimodal models), ``per_task_tier: Mapping[str,str]``
(per-function grade ``S``/``A``/``B``/``C``/``na``) and ``privacy_tier: str``
(``SAFE``/``CONDITIONAL``/``AVOID``).

The REAL :mod:`media_studio.models.catalog` keys ``per_task_tier`` by the
:class:`catalog.Task` ENUM (not the function-name string) and exposes no
``all()`` — so :class:`CatalogAdapter` (carryforward #1) is the thin, PURE bridge
that re-exposes the curated catalog through this duck-typed surface. It imports
the (equally pure, network-free) catalog module lazily so the ranking helpers
above stay independent and 100%-testable against a fake catalog.

Routing shape returned by :func:`apply_preset`::

    {
        "activePreset": "<name>",
        "perFunction": {
            "<function>": {"provider": "<model-id>" | LOCAL, "fallback": [ids...]},
            ...
        },
    }

The local backstop is the sentinel :data:`LOCAL`; ``privacy`` routes every
function to it with no cloud egress at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Sentinel provider id for the always-available local backstop.
LOCAL = "local"

#: The five Reframe AI functions, in canonical (catalog task 1..5) order.
FUNCTIONS: tuple[str, ...] = ("select", "subtitles", "translation", "vision", "editPlan")

#: Functions whose egress is privacy-sensitive (vision = frames leave the box).
_VISION_FUNCTIONS: frozenset[str] = frozenset({"vision"})

#: Grade -> rank weight (lower is better; ``na`` is unrankable / excluded).
_GRADE_RANK: dict[str, int] = {"S": 0, "A": 1, "B": 2, "C": 3}

#: The capability a function requires of a catalog entry (default = "text").
_REQUIRED_CAPABILITY: dict[str, str] = dict.fromkeys(FUNCTIONS, "text")
_REQUIRED_CAPABILITY["vision"] = "vision"

#: Preset descriptors: per-function routing STRATEGY (resolved against catalog).
#: "local"      -> the local backstop only (no cloud egress)
#: "cloud"      -> the catalog's top capable cloud pick (local as last fallback)
#: "cloudSafe"  -> top capable cloud pick that is NOT privacy-tier AVOID
PRESETS: dict[str, dict[str, str]] = {
    "privacy": dict.fromkeys(FUNCTIONS, "local"),
    "bestFreeCloud": dict.fromkeys(FUNCTIONS, "cloud"),
    # balanced: cloud for text tasks (privacy-aware), local for vision frames.
    "balanced": {
        "select": "cloudSafe",
        "subtitles": "cloudSafe",
        "translation": "cloudSafe",
        "vision": "local",
        "editPlan": "cloudSafe",
    },
}


# --------------------------------------------------------------------------- #
# Duck-typed catalog surface (documentation / type-checker aid only)
# --------------------------------------------------------------------------- #


@runtime_checkable
class CatalogEntryLike(Protocol):
    """The minimal entry surface :mod:`presets` reads from a catalog."""

    id: str
    provider: str
    capabilities: tuple[str, ...]
    per_task_tier: Mapping[str, str]
    privacy_tier: str


@runtime_checkable
class CatalogLike(Protocol):
    """A catalog need only expose ``all()`` returning entry-likes."""

    def all(self) -> tuple[CatalogEntryLike, ...]: ...


# --------------------------------------------------------------------------- #
# Ranking / suggestion
# --------------------------------------------------------------------------- #


def _grade_for(entry: CatalogEntryLike, function: str) -> str:
    """Return the entry's grade for ``function`` (``na`` when unset)."""
    return entry.per_task_tier.get(function, "na")


def _is_candidate(entry: CatalogEntryLike, function: str) -> bool:
    """True iff ``entry`` can serve ``function`` (capability + a real grade)."""
    needed = _REQUIRED_CAPABILITY[function]
    if needed not in entry.capabilities:
        return False
    return _grade_for(entry, function) in _GRADE_RANK


def suggest_for_function(
    function: str,
    catalog: CatalogLike,
    prefs: Mapping[str, Any],
) -> list[CatalogEntryLike]:
    """Return catalog entries able to serve ``function``, best-ranked first.

    Capability-mismatched and ``na``-grade entries are never proposed. When
    ``prefs["requireSafePrivacy"]`` is truthy, ``AVOID``-tier entries are
    dropped. Equal grades preserve catalog order (stable sort).
    """
    if function not in _REQUIRED_CAPABILITY:
        raise ValueError(f"unknown function: {function!r}")
    require_safe = bool(prefs.get("requireSafePrivacy"))
    candidates = [
        entry
        for entry in catalog.all()
        if _is_candidate(entry, function) and not (require_safe and entry.privacy_tier == "AVOID")
    ]
    candidates.sort(key=lambda e: _GRADE_RANK[_grade_for(e, function)])
    return candidates


# --------------------------------------------------------------------------- #
# Preset application
# --------------------------------------------------------------------------- #


def _resolve_slot(
    function: str,
    strategy: str,
    catalog: CatalogLike,
) -> dict[str, Any]:
    """Resolve one function's preset strategy into a routing slot."""
    if strategy == "local":
        return {"provider": LOCAL, "fallback": []}

    prefs: dict[str, Any] = {"requireSafePrivacy": strategy == "cloudSafe"}
    ranked = suggest_for_function(function, catalog, prefs)
    if not ranked:
        # No capable cloud candidate -> never propose a model the catalog lacks.
        return {"provider": LOCAL, "fallback": []}

    primary = ranked[0].id
    fallback = [entry.id for entry in ranked[1:]]
    fallback.append(LOCAL)  # the local backstop is always the last resort.
    return {"provider": primary, "fallback": fallback}


def apply_preset(
    name: str,
    settings: Mapping[str, Any],  # noqa: ARG001 - reserved for per-project overrides
    catalog: CatalogLike,
) -> dict[str, Any]:
    """Resolve preset ``name`` into a concrete ``routing`` mapping (pure).

    ``settings`` is accepted for future per-project overrides; the resolution is
    catalog-driven and deterministic today.
    """
    descriptor = PRESETS.get(name)
    if descriptor is None:
        raise ValueError(f"unknown preset: {name!r}")
    per_function = {function: _resolve_slot(function, strategy, catalog) for function, strategy in descriptor.items()}
    return {"activePreset": name, "perFunction": per_function}


# --------------------------------------------------------------------------- #
# First-run local-vs-cloud default
# --------------------------------------------------------------------------- #


def first_run_default(settings: Mapping[str, Any]) -> str:
    """Return the local-safe default preset until the user makes a choice.

    Pre-choice (``firstRunChoiceMade`` falsey) the answer is always ``"privacy"``
    (all-local, no egress). Once a choice is recorded, a non-privacy
    ``activePreset`` resolves to the cloud-capable default ``"bestFreeCloud"``;
    a privacy choice (or no recorded preset) stays ``"privacy"``.
    """
    if not settings.get("firstRunChoiceMade"):
        return "privacy"
    active = settings.get("activePreset")
    if active and active != "privacy":
        return "bestFreeCloud"
    return "privacy"


# --------------------------------------------------------------------------- #
# Catalog adapter (carryforward #1) — bridge the REAL catalog to this duck-type
# --------------------------------------------------------------------------- #

#: Map each Reframe FUNCTION (this module's seam name) to the catalog's ``Task``
#: enum member name. Kept as a string-keyed dict of *enum member names* so this
#: module imports nothing from ``catalog`` at module load; the adapter resolves
#: the names to real enum members lazily. Built lazily/validated in the adapter.
_FUNCTION_TASK_NAMES: dict[str, str] = {
    "select": "MOMENT_FIND",
    "subtitles": "CAPTION",
    "translation": "TRANSLATION",
    "vision": "VISION",
    "editPlan": "EDIT_PLAN",
}


class _AdaptedEntry:
    """One real :class:`catalog.CatalogEntry` re-exposed through the duck-type.

    Flattens the catalog's enum-keyed ``per_task_tier`` into the FUNCTION-name ->
    grade-string map the ranking helpers consume, and the ``Capability`` /
    ``PrivacyTier`` enums into their plain ``.value`` strings. PURE — it only
    re-reads already-loaded curated data.
    """

    __slots__ = ("id", "provider", "capabilities", "per_task_tier", "privacy_tier")

    def __init__(self, entry: Any, function_tasks: Mapping[str, Any]) -> None:
        self.id: str = entry.id
        self.provider: str = entry.provider
        self.capabilities: tuple[str, ...] = tuple(c.value for c in entry.capabilities)
        # Typed as the invariant Mapping the CatalogEntryLike protocol declares so a
        # structural check passes; the value is a plain dict at runtime.
        self.per_task_tier: Mapping[str, str] = {
            function: entry.per_task_tier[task].value for function, task in function_tasks.items()
        }
        self.privacy_tier: str = entry.privacy_tier.value


class CatalogAdapter:
    """Expose the REAL curated catalog through the :class:`CatalogLike` surface.

    The constructor accepts an optional ``catalog`` tuple of real
    :class:`catalog.CatalogEntry` rows (default: the shared ``catalog.CATALOG``)
    so tests can pin a tiny subset. Each row is wrapped in :class:`_AdaptedEntry`
    so ``apply_preset`` / ``suggest_for_function`` read FUNCTION-name-keyed grades
    + plain-string capabilities/privacy and resolve real picks (carryforward #1 —
    without this the function-name lookup would miss the enum keys and every grade
    would fall to ``"na"``, collapsing every preset to local).
    """

    def __init__(self, *, catalog: Any | None = None) -> None:
        from . import catalog as _catalog  # local: import-light pure data bridge

        rows = catalog if catalog is not None else _catalog.CATALOG
        function_tasks = {function: _catalog.Task[name] for function, name in _FUNCTION_TASK_NAMES.items()}
        self._entries: tuple[_AdaptedEntry, ...] = tuple(_AdaptedEntry(row, function_tasks) for row in rows)

    def all(self) -> tuple[CatalogEntryLike, ...]:
        return self._entries


def function_tasks() -> dict[str, Any]:
    """Return the FUNCTION-name -> real ``catalog.Task`` map (resolved lazily).

    Exposed for handlers/tests that need the function<->task correspondence (e.g.
    to read the catalog's ``top_pick_for_task`` for a given seam). Importing the
    catalog here keeps the ranking helpers above catalog-free.
    """
    from . import catalog as _catalog  # local: import-light pure data bridge

    return {function: _catalog.Task[name] for function, name in _FUNCTION_TASK_NAMES.items()}
