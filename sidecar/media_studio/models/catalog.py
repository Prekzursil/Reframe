"""Static multi-provider model catalog (WU-catalog).

A hand-curated, **dated** catalog ranking each free/paid LLM by fitness for
Reframe's five tasks (Moment-Find/Select, Caption/Title/Hook, Translation,
Vision/OCR, Edit-Plan Gen), with a privacy axis (a ``trains_on_input`` flag plus
a coarse ``privacy_tier``) so the UI can warn before private data leaves the
machine. Seeded VERBATIM from ``docs/providers/CATALOG-SEED.md`` (research pass
``wf_e4773258``, 2026-06-16).

This is **pure data + pure helpers** — no network, no model, no ``time`` import,
no cross-import of the other Hub modules. It is the single source of truth the
``providers.catalog`` RPC serializes for the renderer and the
``top_pick_for_task`` ranking that the presets/recommender consume.

Honesty rule (matches the seed's ⛔ section): every quality label is *dated
guidance* ("our pick · as of <date>"), never an objective benchmark, and free
tiers churn — re-verify ``CATALOG-SEED.md`` at build time. The "N keys =/=
N x quota" reality lives in the SETUP/MODEL-GUIDE docs, not here.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# --------------------------------------------------------------------------- #
# Axes (enums kept tiny so JSON serialization is the enum *value*)
# --------------------------------------------------------------------------- #


class Task(enum.Enum):
    """The five Reframe tasks the catalog ranks each model against."""

    MOMENT_FIND = "moment_find"  # 1: Moment-Find / Select
    CAPTION = "caption"  # 2: Caption / Title / Hook
    TRANSLATION = "translation"  # 3: Translation
    VISION = "vision"  # 4: Vision / OCR
    EDIT_PLAN = "edit_plan"  # 5: Edit-Plan Gen


class TierGrade(enum.Enum):
    """Per-task fitness grade. ``NA`` = the model cannot serve this task."""

    S = "S"
    A = "A"
    B = "B"
    C = "C"
    NA = "na"


class Capability(enum.Enum):
    """What a model can ingest. Vision models are also text-capable."""

    TEXT = "text"
    VISION = "vision"


class Unit(enum.Enum):
    """The unit the provider's free limit is denominated in."""

    REQ = "req"
    TOKEN = "token"


class CostClass(enum.Enum):
    """Coarse cost posture used for ordering and UI badges."""

    FREE = "free"
    FREEMIUM = "freemium"  # free tier exists but credit/$10 unlocks more
    PAID = "paid"


class PrivacyTier(enum.Enum):
    """Coarse privacy posture for sending real user data."""

    SAFE = "SAFE"
    CONDITIONAL = "CONDITIONAL"  # flip opt-out / ZDR first
    AVOID = "AVOID"  # free tier trains / human review possible


#: ``trains_on_input`` is a bool, or the string ``"conditional"`` when the
#: provider trains unless the user flips an opt-out / ZDR toggle.
TrainsOnInput = Literal[True, False, "conditional"]

#: Numeric weight per grade, used by ``order_by("quality")``.
_GRADE_SCORE: dict[TierGrade, int] = {
    TierGrade.S: 5,
    TierGrade.A: 4,
    TierGrade.B: 3,
    TierGrade.C: 2,
    TierGrade.NA: 0,
}

#: The snapshot date stamped on every entry (seed research date).
AS_OF_DATE = "2026-06-16"


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CatalogEntry:
    """One curated model row. Immutable so the shared ``CATALOG`` can't drift."""

    id: str
    provider: str
    model: str
    capabilities: tuple[Capability, ...]
    context_tokens: int
    per_task_tier: Mapping[Task, TierGrade]
    cost_class: CostClass
    free_limits: str
    #: Higher = more generous free tier (relative weight for ``order_by("limit")``).
    free_limit_score: int
    unit: Unit
    trains_on_input: TrainsOnInput
    privacy_tier: PrivacyTier
    recommended_for: tuple[Task, ...]
    notes: str
    as_of_date: str = AS_OF_DATE

    def best_grade_score(self) -> int:
        """The score of this model's strongest task grade (for quality order)."""
        return max(_GRADE_SCORE[g] for g in self.per_task_tier.values())

    def grade_for(self, task: Task) -> TierGrade:
        """This model's grade for ``task`` (``NA`` if it cannot serve it)."""
        return self.per_task_tier[task]


def _tiers(
    t1: TierGrade,
    t2: TierGrade,
    t3: TierGrade,
    t4: TierGrade,
    t5: TierGrade,
) -> Mapping[Task, TierGrade]:
    """Build the per-task grade map from the seed table's column order."""
    return {
        Task.MOMENT_FIND: t1,
        Task.CAPTION: t2,
        Task.TRANSLATION: t3,
        Task.VISION: t4,
        Task.EDIT_PLAN: t5,
    }


_S, _A, _B, _C, _NA = (
    TierGrade.S,
    TierGrade.A,
    TierGrade.B,
    TierGrade.C,
    TierGrade.NA,
)
_TEXT: tuple[Capability, ...] = (Capability.TEXT,)
_MULTI: tuple[Capability, ...] = (Capability.TEXT, Capability.VISION)


# --------------------------------------------------------------------------- #
# CATALOG — seeded VERBATIM from docs/providers/CATALOG-SEED.md
# --------------------------------------------------------------------------- #

CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="groq-gpt-oss-120b",
        provider="Groq",
        model="GPT-OSS-120B",
        capabilities=_TEXT,
        context_tokens=128_000,
        per_task_tier=_tiers(_S, _A, _A, _NA, _S),
        cost_class=CostClass.FREE,
        free_limits="30 RPM / 1K RPD / 200K TPD",
        free_limit_score=80,
        unit=Unit.TOKEN,
        trains_on_input=False,
        privacy_tier=PrivacyTier.SAFE,
        recommended_for=(Task.MOMENT_FIND, Task.EDIT_PLAN),
        notes="No-retention default — SAFE. Best free reasoning + structured JSON.",
    ),
    CatalogEntry(
        id="groq-llama-3.3-70b",
        provider="Groq",
        model="Llama 3.3 70B",
        capabilities=_TEXT,
        context_tokens=128_000,
        per_task_tier=_tiers(_A, _S, _S, _NA, _A),
        cost_class=CostClass.FREE,
        free_limits="30 RPM / 1K RPD / 100K TPD",
        free_limit_score=70,
        unit=Unit.TOKEN,
        trains_on_input=False,
        privacy_tier=PrivacyTier.SAFE,
        recommended_for=(Task.CAPTION, Task.TRANSLATION),
        notes="Fast, generous, safe — caption/title/hook + translation volume.",
    ),
    CatalogEntry(
        id="cerebras-qwen3-235b",
        provider="Cerebras",
        model="Qwen3-235B",
        capabilities=_TEXT,
        context_tokens=128_000,
        per_task_tier=_tiers(_S, _A, _A, _NA, _S),
        cost_class=CostClass.FREE,
        free_limits="~30 RPM / 1M tok/day",
        free_limit_score=90,
        unit=Unit.TOKEN,
        trains_on_input="conditional",
        privacy_tier=PrivacyTier.CONDITIONAL,
        recommended_for=(Task.MOMENT_FIND, Task.EDIT_PLAN),
        notes="Train policy UNVERIFIED (likely no-train) — confirm ToS at signup.",
    ),
    CatalogEntry(
        id="cerebras-llama-3.3-70b",
        provider="Cerebras",
        model="Llama 3.3 70B",
        capabilities=_TEXT,
        context_tokens=128_000,
        per_task_tier=_tiers(_A, _S, _S, _NA, _A),
        cost_class=CostClass.FREE,
        free_limits="~30 RPM / 1M tok/day",
        free_limit_score=85,
        unit=Unit.TOKEN,
        trains_on_input="conditional",
        privacy_tier=PrivacyTier.CONDITIONAL,
        recommended_for=(Task.CAPTION, Task.TRANSLATION),
        notes="Train policy UNVERIFIED — confirm ToS at signup.",
    ),
    CatalogEntry(
        id="sambanova-llama-3.1-405b",
        provider="SambaNova",
        model="Llama 3.1 405B",
        capabilities=_TEXT,
        context_tokens=128_000,
        per_task_tier=_tiers(_A, _A, _A, _NA, _A),
        cost_class=CostClass.FREE,
        free_limits="~10-30 RPM / ~200K tok/day",
        free_limit_score=50,
        unit=Unit.TOKEN,
        trains_on_input=False,
        privacy_tier=PrivacyTier.SAFE,
        recommended_for=(Task.MOMENT_FIND,),
        notes="Claims no prompt collection — SAFE-ish; card requirement unclear.",
    ),
    CatalogEntry(
        id="gemini-2.5-flash",
        provider="Google AI Studio",
        model="Gemini 2.5 Flash",
        capabilities=_MULTI,
        context_tokens=1_000_000,
        per_task_tier=_tiers(_S, _A, _A, _S, _S),
        cost_class=CostClass.FREE,
        free_limits="15 RPM / 1500 RPD / ~1M TPM",
        free_limit_score=75,
        unit=Unit.REQ,
        trains_on_input=True,
        privacy_tier=PrivacyTier.AVOID,
        recommended_for=(Task.VISION,),
        notes="FREE tier TRAINS (outside EEA/UK/CH), human review possible — "
        "AVOID for private/PII data.",
    ),
    CatalogEntry(
        id="gemini-2.5-flash-lite",
        provider="Google AI Studio",
        model="Gemini 2.5 Flash-Lite",
        capabilities=_MULTI,
        context_tokens=1_000_000,
        per_task_tier=_tiers(_A, _S, _A, _S, _A),
        cost_class=CostClass.FREE,
        free_limits="30 RPM / 1500 RPD",
        free_limit_score=65,
        unit=Unit.REQ,
        trains_on_input=True,
        privacy_tier=PrivacyTier.AVOID,
        recommended_for=(Task.VISION,),
        notes="Best free OCR + 1M ctx, but FREE tier TRAINS — AVOID private; "
        "use GitHub GPT-4o-mini or paid Gemini for PII frames.",
    ),
    CatalogEntry(
        id="github-gpt-4o-mini",
        provider="GitHub Models",
        model="GPT-4o-mini",
        capabilities=_MULTI,
        context_tokens=128_000,
        per_task_tier=_tiers(_B, _A, _A, _A, _B),
        cost_class=CostClass.FREE,
        free_limits="~15 RPM / 150 RPD (prototyping)",
        free_limit_score=30,
        unit=Unit.REQ,
        trains_on_input=False,
        privacy_tier=PrivacyTier.SAFE,
        recommended_for=(Task.VISION,),
        notes="No-train (not for prod) — SAFE-ish; prototyping only. Good for "
        "private/PII frames behind the free Gemini.",
    ),
    CatalogEntry(
        id="mistral-pixtral",
        provider="Mistral",
        model="Pixtral",
        capabilities=_MULTI,
        context_tokens=128_000,
        per_task_tier=_tiers(_B, _A, _S, _A, _B),
        cost_class=CostClass.FREEMIUM,
        free_limits="Experiment ~1B tok/mo (phone verify)",
        free_limit_score=60,
        unit=Unit.TOKEN,
        trains_on_input="conditional",
        privacy_tier=PrivacyTier.CONDITIONAL,
        recommended_for=(Task.TRANSLATION,),
        notes="Trains by DEFAULT; opt-out toggle — flip it first. Strong EU "
        "translation quality.",
    ),
    CatalogEntry(
        id="cloudflare-workers-ai",
        provider="Cloudflare",
        model="Workers AI (Llama 3.1 / Qwen 2.5)",
        capabilities=_TEXT,
        context_tokens=8_000,
        per_task_tier=_tiers(_C, _B, _B, _NA, _C),
        cost_class=CostClass.FREE,
        free_limits="10K Neurons/day",
        free_limit_score=40,
        unit=Unit.REQ,
        trains_on_input=False,
        privacy_tier=PrivacyTier.SAFE,
        recommended_for=(),
        notes="No-train — SAFE, but 2K-8K context is LIMITING for transcripts.",
    ),
    CatalogEntry(
        id="openrouter-free-text",
        provider="OpenRouter",
        model="DeepSeek/Qwen :free (text)",
        capabilities=_TEXT,
        context_tokens=128_000,
        per_task_tier=_tiers(_A, _A, _A, _NA, _A),
        cost_class=CostClass.FREEMIUM,
        free_limits="20 RPM / 50 RPD (->1000 after one-time $10)",
        free_limit_score=45,
        unit=Unit.REQ,
        trains_on_input="conditional",
        privacy_tier=PrivacyTier.CONDITIONAL,
        recommended_for=(),
        notes="Downstream MAY train unless ZDR is set — flip ZDR first. The "
        "one-time $10 lifetime credit lifts 50->1000 RPD.",
    ),
    CatalogEntry(
        id="openrouter-free-vision",
        provider="OpenRouter",
        model="Gemma/Nemotron-VL :free (vision)",
        capabilities=_MULTI,
        context_tokens=256_000,
        per_task_tier=_tiers(_NA, _NA, _NA, _B, _NA),
        cost_class=CostClass.FREEMIUM,
        free_limits="20 RPM / ~50-200 RPD",
        free_limit_score=40,
        unit=Unit.REQ,
        trains_on_input="conditional",
        privacy_tier=PrivacyTier.CONDITIONAL,
        recommended_for=(Task.VISION,),
        notes="Downstream MAY train; set ZDR. Vision-only free fallback.",
    ),
    CatalogEntry(
        id="openai-api",
        provider="OpenAI",
        model="OpenAI API (paid)",
        capabilities=_MULTI,
        context_tokens=128_000,
        per_task_tier=_tiers(_A, _A, _A, _A, _A),
        cost_class=CostClass.PAID,
        free_limits="credits (~no free tier)",
        free_limit_score=10,
        unit=Unit.TOKEN,
        trains_on_input=False,
        privacy_tier=PrivacyTier.SAFE,
        recommended_for=(),
        notes="No-train by default (API) — SAFE. 30-day retention has a "
        "legal-hold caveat. The paid backstop behind the free tiers.",
    ),
)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

#: The valid keys accepted by :func:`order_by`.
OrderKey = Literal["quality", "limit", "context"]


def filter_by_capability(
    capability: Capability,
    *,
    catalog: Sequence[CatalogEntry] = CATALOG,
) -> list[CatalogEntry]:
    """Return entries that declare ``capability`` (preserving catalog order)."""
    return [e for e in catalog if capability in e.capabilities]


def order_by(
    key: OrderKey,
    *,
    catalog: Sequence[CatalogEntry] = CATALOG,
) -> list[CatalogEntry]:
    """Return a new list ordered by ``key`` (descending), never mutating source.

    * ``"quality"`` — by the entry's strongest per-task grade.
    * ``"limit"``  — by ``free_limit_score`` (more generous free tier first).
    * ``"context"`` — by ``context_tokens``.
    """
    if key == "quality":
        return sorted(catalog, key=lambda e: e.best_grade_score(), reverse=True)
    if key == "limit":
        return sorted(catalog, key=lambda e: e.free_limit_score, reverse=True)
    if key == "context":
        return sorted(catalog, key=lambda e: e.context_tokens, reverse=True)
    raise ValueError(f"unknown order key: {key!r}")


#: The editorial "Top pick per task" from ``CATALOG-SEED.md`` (seeded verbatim;
#: the free-tier/grade math alone can't reproduce these because the seed prefers
#: the SAFE Groq models over the higher-quota-but-unverified Cerebras ones, and
#: prefers Gemini Flash-Lite over Flash for OCR). Validated against ``CATALOG``
#: at import time, so a typo or a removed entry fails fast (no silent drift).
TOP_PICKS: Mapping[Task, str] = {
    Task.MOMENT_FIND: "groq-gpt-oss-120b",
    Task.CAPTION: "groq-llama-3.3-70b",
    Task.TRANSLATION: "groq-llama-3.3-70b",
    Task.VISION: "gemini-2.5-flash-lite",
    Task.EDIT_PLAN: "groq-gpt-oss-120b",
}


def top_pick_for_task(
    task: Task,
    *,
    catalog: Sequence[CatalogEntry] = CATALOG,
) -> CatalogEntry:
    """Return the single best catalog entry for ``task``.

    Prefers the seed's editorial :data:`TOP_PICKS` when that model is present in
    ``catalog`` and can serve ``task``; otherwise ranks the eligible entries by
    per-task grade, breaking ties with the more generous free tier then the
    larger context. Entries graded ``NA`` for the task are ineligible; raises
    ``ValueError`` if none can serve the task.
    """
    eligible = [e for e in catalog if e.grade_for(task) is not TierGrade.NA]
    if not eligible:
        raise ValueError(f"no catalog entry serves task: {task.value}")
    preferred_id = TOP_PICKS[task]
    for entry in eligible:
        if entry.id == preferred_id:
            return entry
    return max(
        eligible,
        key=lambda e: (
            _GRADE_SCORE[e.grade_for(task)],
            e.free_limit_score,
            e.context_tokens,
        ),
    )


__all__ = [
    "AS_OF_DATE",
    "CATALOG",
    "Capability",
    "CatalogEntry",
    "CostClass",
    "OrderKey",
    "PrivacyTier",
    "Task",
    "TierGrade",
    "TrainsOnInput",
    "Unit",
    "filter_by_capability",
    "order_by",
    "top_pick_for_task",
]
