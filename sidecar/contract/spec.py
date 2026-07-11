"""The single source of truth for the Reframe RPC contract (v1.5 POC slice).

This module is the ONE place a contract method's existence, its parameter and
result shapes, its key-injection requirement, and its job/direct kind are
declared. Every other representation of the contract — the TypeScript
``client.ts`` wrappers, ``schemas.ts``, the ``MethodName`` union, the
``needsKeyInjection`` allowlist, the Python-side param validators, and the typed
``Settings`` model — is GENERATED from here by :mod:`contract.generate`. See
``docs/rpc-contract-v2.md`` for the design and ``docs/rpc-contract-v2-migration.md``
for the incremental migration plan.

Design constraints honored here (CONTRACTS.md §6/§7 "keep it lean"):
  * stdlib only — the data models are plain :func:`dataclasses.dataclass` types,
    NOT pydantic. The sidecar is deliberately dependency-light (§7: "stdlib
    JSON-RPC, no FastAPI"), so the contract adds no runtime dependency.
  * one-way dependency — this package NEVER imports ``media_studio``. The runtime
    (``media_studio``) is the eventual CONSUMER of the generated artifacts; the
    contract stands alone so it can be type-checked and generated in isolation.
  * wire-faithful field names — dataclass field names are the FROZEN camelCase
    wire names verbatim (mirroring ``schemas.ts``), so the generator maps
    field name -> JSON Schema property -> TS field with zero transformation. The
    ``N815`` mixed-case lint is suppressed for this module (pyproject) with this
    exact rationale.

POC slice (5 representative methods, chosen to span every drift surface):
  * ``ping``               — no params, no key, protocol built-in (baseline).
  * ``library.add``        — a required ``{path}`` param + a data-model result.
  * ``settings.get`` /     — the typed ``Settings`` surface (retires the
    ``settings.set``          ``dict[str, Any]`` untyped-settings finding).
  * ``shortmaker.select``  — a key-injection method (prefix family) that is a JOB
                              and reads settings (the ``silenceTrimm`` typo site).
  * ``providers.revealKey``— a key-injection method matched by the EXACT allowlist
                              (not a prefix), proving both classifier paths.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

# --------------------------------------------------------------------------- #
# §3 shared data models (field names identical to schemas.ts / the Python wire)
# --------------------------------------------------------------------------- #


@dataclass
class Video:
    """A library source video (mirrors ``schemas.ts`` ``Video``)."""

    id: str
    path: str
    title: str
    addedAt: str
    durationSec: float
    hasTranscript: bool


@dataclass
class RevealKeyResult:
    """The single raw key returned by ``providers.revealKey`` (WU-D3)."""

    key: str


@dataclass
class Autosave:
    """The workspace autosave settings block (nested under ``Settings``)."""

    enabled: bool = True
    debounceMs: int = 1500


@dataclass
class ExportDefaults:
    """The pre-selected export formats block (nested under ``Settings``)."""

    subtitleFormat: str = "srt"
    nleFormat: str = "edl"
    nleFps: int = 30


@dataclass
class ShortmakerControls:
    """The ``shortmaker.select`` controls object (CONTRACTS.md §2).

    Every field is optional; an absent field takes the pipeline default. Typing
    these (instead of ``Record<string, unknown>`` / ``dict[str, Any]``) is the
    same win as the typed ``Settings`` model — a misspelled control is a compile
    error, not a silently-ignored ``None``.
    """

    count: int | None = None
    minSec: float | None = None
    maxSec: float | None = None
    aspect: str | None = None
    language: str | None = None
    captionStyle: str | None = None


@dataclass
class Settings:
    """The typed settings surface both sides assert (retires findings #6/#7).

    The first block mirrors the keys and defaults of
    ``media_studio.settings_store.DEFAULT_SETTINGS`` (the parity test asserts they
    agree). The second block DECLARES the previously-undeclared shortmaker/refine
    control keys that were only ever reached via stringly-typed
    ``settings.get("...")`` — so a typo like ``settings.get("silenceTrimm")``
    becomes a type error instead of a silent ``None``. Every field is optional,
    matching the store's partial-merge reality (``settings.set`` sends a subset).
    """

    # ---- declared in DEFAULT_SETTINGS (parity-checked) ----
    useCloud: bool = False
    modelsDir: str = ""
    ffmpegPath: str = ""
    confirmCloudBudget: bool = True
    defaultTargetJobSize: int = 8  # mirrors media_studio.models.budget.DEFAULT_TARGET_JOB_SIZE
    monthlySoftLimitCents: int = 0
    monthlyHardLimitCents: int = 0
    enforceMonthlyHardLimit: bool = False
    activePreset: str = ""
    firstRunChoiceMade: bool = False
    lastOpenedVideoId: str = ""
    autosave: Autosave | None = None
    exportDefaults: ExportDefaults | None = None
    # ---- newly DECLARED here (previously only stringly-accessed) ----
    silenceTrim: bool | None = None
    removeFillers: bool | None = None
    hookTitle: bool | None = None
    stabilize: bool | None = None
    captionStyle: str | None = None
    captionSpeakerLabels: bool | None = None


# --------------------------------------------------------------------------- #
# Parameter models (one dataclass per method that takes params)
# --------------------------------------------------------------------------- #


@dataclass
class LibraryAddParams:
    """``library.add`` params: a required source ``{path}``."""

    path: str


@dataclass
class RevealKeyParams:
    """``providers.revealKey`` params: ``{id, index?}`` (index selects the pool slot)."""

    id: str
    index: int = 0


@dataclass
class ShortmakerSelectParams:
    """``shortmaker.select`` params: ``{videoId, prompt, controls}``."""

    videoId: str
    prompt: str
    controls: ShortmakerControls


# --------------------------------------------------------------------------- #
# The method registry
# --------------------------------------------------------------------------- #


class Binding(Enum):
    """How a method's positional TS wrapper args map onto the JSON-RPC params.

    * ``NONE``   — the method takes no params: ``() => rpc(name)``.
    * ``NAMED``  — each params field is a positional arg mapped to a named key:
      ``(a, b) => rpc(name, { a, b })`` (the common case).
    * ``SPREAD`` — the single arg IS the params object: ``(v) => rpc(name, v)``
      (``settings.set``, which sends a partial ``Settings``).
    """

    NONE = "none"
    NAMED = "named"
    SPREAD = "spread"


@dataclass(frozen=True)
class MethodSpec:
    """One RPC method's full contract — the atom the generator consumes."""

    #: The frozen wire method name (e.g. ``"providers.revealKey"``).
    name: str
    #: The nested path of the TS client wrapper (e.g. ``("providers", "revealKey")``).
    ts_path: tuple[str, ...]
    #: The params dataclass, or ``None`` for a no-arg method.
    params: type | None
    #: How the TS wrapper binds its args onto the params (see :class:`Binding`).
    binding: Binding
    #: The TS return-type expression (e.g. ``"{ video: Video }"``).
    result_ts: str
    #: Named types referenced by ``result_ts`` that must be imported (name -> module).
    result_imports: tuple[tuple[str, str], ...]
    #: ``True`` when the sidecar handler needs live provider keys injected (keyBridge).
    needs_key: bool
    #: ``"direct"`` (resolves its payload) or ``"job"`` (resolves ``{jobId}``).
    kind: str


#: The two source modules generated TS may import result/param types from.
_OWN = "./schemas.generated"  # generated in this PR
_HAND = "../schemas"  # hand-written, not yet migrated (JobHandle / Candidate)


METHODS: tuple[MethodSpec, ...] = (
    MethodSpec(
        name="ping",
        ts_path=("ping",),
        params=None,
        binding=Binding.NONE,
        result_ts="{ pong: boolean; version: string }",
        result_imports=(),
        needs_key=False,
        kind="direct",
    ),
    MethodSpec(
        name="library.add",
        ts_path=("library", "add"),
        params=LibraryAddParams,
        binding=Binding.NAMED,
        result_ts="{ video: Video }",
        result_imports=(("Video", _OWN),),
        needs_key=False,
        kind="direct",
    ),
    MethodSpec(
        name="settings.get",
        ts_path=("settings", "get"),
        params=None,
        binding=Binding.NONE,
        result_ts="Settings",
        result_imports=(("Settings", _OWN),),
        needs_key=False,
        kind="direct",
    ),
    MethodSpec(
        name="settings.set",
        ts_path=("settings", "set"),
        params=Settings,
        binding=Binding.SPREAD,
        result_ts="Settings",
        result_imports=(("Settings", _OWN),),
        needs_key=False,
        kind="direct",
    ),
    MethodSpec(
        name="shortmaker.select",
        ts_path=("shortmaker", "select"),
        params=ShortmakerSelectParams,
        binding=Binding.NAMED,
        result_ts="JobHandle & { candidates?: Candidate[] }",
        result_imports=(("JobHandle", _HAND), ("Candidate", _HAND)),
        needs_key=True,
        kind="job",
    ),
    MethodSpec(
        name="providers.revealKey",
        ts_path=("providers", "revealKey"),
        params=RevealKeyParams,
        binding=Binding.NAMED,
        result_ts="RevealKeyResult",
        result_imports=(("RevealKeyResult", _OWN),),
        needs_key=True,
        kind="direct",
    ),
)


#: Every named data model the generator emits into ``schemas.generated.ts`` and
#: the Python ``SETTINGS_SCHEMA`` / param schemas. Order is the emission order.
DATA_MODELS: tuple[type, ...] = (
    Video,
    RevealKeyResult,
    Autosave,
    ExportDefaults,
    ShortmakerControls,
    Settings,
)


def method_names() -> tuple[str, ...]:
    """Every method name in declaration order (drives the ``MethodName`` union)."""
    return tuple(m.name for m in METHODS)


def needs_key_names() -> tuple[str, ...]:
    """The method names that require key injection, sorted for stable emission."""
    return tuple(sorted(m.name for m in METHODS if m.needs_key))


def param_field_names(params: type) -> tuple[str, ...]:
    """The declared field names of a params dataclass, in declaration order."""
    return tuple(f.name for f in fields(params))
