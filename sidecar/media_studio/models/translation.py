"""Tiered subtitle translation (T3): local MT GGUF -> heavy local -> hosted.

The survey (``docs/research/MT-MODELS-2026.md``, verified live 2026-06-12) picked:

  * **tier1** — TranslateGemma-4B-it Q4_K_M (2.49GB, fully GPU-resident): the
    fast local default for high/mid-resource languages.
  * **tier2** — TranslateGemma-12B-it Q4_K_M (7.4GB, PARTIAL offload, labelled
    ``SLOW`` in progress messages): the low-resource/quality tier.
  * **tier3** — a hosted OpenAI-compatible provider
    (:class:`~media_studio.models.provider.CloudProvider`): everything outside
    local coverage.

Language-aware routing: :data:`ROUTING_TABLE` maps a normalized ISO 639-1 code
to its tier (the survey's table); unknown codes route to the hosted tier. On a
tier failure the chain falls back to the remaining tiers in ascending order.

Integration seams (consumed by ``subtitles.translate`` and the T2 dub pipeline):

  * :meth:`TieredTranslator.translate` — **the** ``translate(cues, targetLang)``
    callable the dub pipeline batches through (A4: translate ALL cues, then
    free the MT model — never interleave model swaps).
  * :meth:`TieredTranslator.translate_track` — the ``subtitles.translate`` job
    body (same shape as ``features.subtitles.translate``: new track, ``lang``
    updated, timings preserved).
  * :meth:`TieredTranslator.line_translator` — a ``str -> str`` adapter for the
    existing ``features.subtitles.translate(translator=...)`` seam (stateful:
    escalates tiers on failure and STAYS on the escalated tier).

Local tiers reach the GPU only through the injected
:class:`~media_studio.models.runner.ModelRunner` (whose ``start_server`` is
model-identity-aware: switching tier1 <-> tier2 restarts the llama.cpp server
with the right GGUF; re-using the same tier reuses the live process) and an
injectable provider factory — tests drive the full chain with fakes: no process,
no network, no GPU.

This module also registers the two MT GGUF manifest entries (U4
``assets.manifest.register_asset``) with PINNED Hugging Face URLs (A6 lesson 5).

NO new RPC methods are registered here (A2's method names are frozen;
``subtitles.translate`` already exists) — the handler wiring snippet lives in
``docs/wiring/WIRING-T3.md``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..assets.manifest import AssetEntry, register_asset
from ..features import languages as _languages
from ..pathsafe import ensure_within
from ..util import get_logger
from . import provider as provider_mod

log = get_logger("media_studio.models.translation")

# Cue/SubtitleTrack are the frozen §3 dict shapes (same aliases subtitles.py uses).
Cue = dict[str, Any]
SubtitleTrack = dict[str, Any]

# --------------------------------------------------------------------------- #
# Tiers (docs/research/MT-MODELS-2026.md §2)
# --------------------------------------------------------------------------- #
TIER_LOCAL: str = "tier1"  # TranslateGemma-4B Q4_K_M, fully resident
TIER_LOCAL_HEAVY: str = "tier2"  # TranslateGemma-12B Q4_K_M, partial offload, SLOW
TIER_HOSTED: str = "tier3"  # hosted OpenAI-compatible provider
TIERS: tuple[str, ...] = (TIER_LOCAL, TIER_LOCAL_HEAVY, TIER_HOSTED)

#: The progress label the heavy tier carries (the T3 brief: "label SLOW").
SLOW_LABEL: str = "SLOW"

# Pinned artifacts (survey §2). File names double as the modelsDir lookup names.
# F3c: the resolve URLs pin a COMMIT HASH (not "main") and carry the file's LFS
# oid as sha256 (both verified via the HF tree + revision APIs, 2026-06-28).
TIER1_GGUF_NAME: str = "translategemma-4b-it.Q4_K_M.gguf"
TIER1_GGUF_COMMIT: str = "35a7486e128b19642cdc72d7b91b21ba388aaf42"
TIER1_GGUF_URL: str = (
    "https://huggingface.co/mradermacher/translategemma-4b-it-GGUF/resolve/"
    f"{TIER1_GGUF_COMMIT}/translategemma-4b-it.Q4_K_M.gguf"
)
TIER1_GGUF_SHA256: str = "81200d03e843d2ec1ece6eeafe7d13cb6e5211e1fcd336ade55790b683a08330"
TIER1_SIZE_MB: int = 2550  # 2.49 GB

TIER2_GGUF_NAME: str = "translategemma-12b-it.Q4_K_M.gguf"
TIER2_GGUF_COMMIT: str = "fdf84c9f6fe14e69d58814f14e7b5b63bb6a1b28"
TIER2_GGUF_URL: str = (
    "https://huggingface.co/mradermacher/translategemma-12b-it-GGUF/resolve/"
    f"{TIER2_GGUF_COMMIT}/translategemma-12b-it.Q4_K_M.gguf"
)
TIER2_GGUF_SHA256: str = "b7aac4b4be7ab0c49b6556c29c4467e74313df7f1e95d9f9676bb2adf0afa528"
TIER2_SIZE_MB: int = 7580  # 7.4 GB

#: Partial offload for the 12B tier on a 6GB card (survey §2; re-tune on the
#: real GPU — analytic sizing, not measured).
TIER2_GPU_LAYERS: int = 24

TIER1_ASSET_NAME: str = "translategemma-4b-gguf"
TIER2_ASSET_NAME: str = "translategemma-12b-gguf"

# --------------------------------------------------------------------------- #
# Routing table (survey §3) — normalized ISO 639-1 code -> tier
# --------------------------------------------------------------------------- #
# The two coverage sets are DEFINED in ``features.languages`` (the language-
# inventory SSOT the renderer mirrors and a conformance test pins) and re-exported
# here under their historical names, so the routing table and the UI cannot drift.
# The dependency runs this way round because ``features.languages`` is pure stdlib
# with no import-time side effects, while THIS module registers HF assets on
# import — a vocabulary module must not pull that in.
TIER1_LANGS: frozenset = _languages.TIER1_LANGS
TIER2_LANGS: frozenset = _languages.TIER2_LANGS

ROUTING_TABLE: dict[str, str] = {
    **dict.fromkeys(TIER1_LANGS, TIER_LOCAL),
    **dict.fromkeys(TIER2_LANGS, TIER_LOCAL_HEAVY),
}

#: Languages outside the table route hosted — the safe default for anything the
#: local TranslateGemma coverage does not include (survey §3).
DEFAULT_TIER: str = TIER_HOSTED


def normalize_lang(lang: str) -> str:
    """Normalize a language tag to a bare lowercase primary subtag.

    ``pt-BR`` / ``pt_BR`` -> ``pt``; ``zh_Hant`` -> ``zh``; ``EN`` -> ``en``.
    Raises ``ValueError`` on an empty/blank tag so a missing targetLang fails
    loudly instead of silently routing to the default tier.
    """
    code = str(lang or "").strip().lower().replace("_", "-")
    code = code.split("-", 1)[0].strip()
    if not code:
        raise ValueError("language code is required")
    return code


def route(lang: str, table: dict[str, str] | None = None) -> str:
    """Map ``lang`` to its tier via the routing ``table`` (default survey table)."""
    routing = ROUTING_TABLE if table is None else table
    return routing.get(normalize_lang(lang), DEFAULT_TIER)


#: Relative capability of each tier — a higher number is the heavier model.
_TIER_WEIGHT: dict[str, int] = {TIER_LOCAL: 1, TIER_LOCAL_HEAVY: 2, TIER_HOSTED: 3}


def route_pair(source_lang: str | None, target_lang: str, table: dict[str, str] | None = None) -> str:
    """Route on the language PAIR, not the target alone.

    ``route`` is target-only, so ``ro -> en`` routed to the LIGHT tier1 model purely
    because ``en`` is tier1 — the heavier model was unreachable for exactly the
    direction that needs it
    (`docs/plans/v1.5/captions-translation-audit-2026-08.md` §3.3, T4). Here a source
    language whose own tier is heavier than the target's escalates the choice.

    **The escalation is capped at the heavy LOCAL tier.** A low-resource SOURCE never
    turns a locally-servable translation into a hosted (network) one, so the pair rule
    cannot change a job's privacy posture; tier3 stays an explicit TARGET decision
    (the class docstring's CONTRACT-NOTE). A missing/blank source is target-only
    routing, so ``route_pair(None, lang) == route(lang)``.
    """
    target_tier = route(target_lang, table)
    if target_tier == TIER_HOSTED or not str(source_lang or "").strip():
        return target_tier
    source_tier = route(str(source_lang), table)
    if _TIER_WEIGHT.get(source_tier, 0) > _TIER_WEIGHT.get(target_tier, 0):
        return TIER_LOCAL_HEAVY
    return target_tier


def fallback_chain(lang: str, table: dict[str, str] | None = None, *, source_lang: str | None = None) -> list[str]:
    """The tier order to attempt for ``lang``: routed tier first, then the rest.

    The remaining tiers follow in ascending order (tier1 -> tier2 -> tier3), so
    e.g. a tier2-routed language falls back to tier1 then tier3, and a hosted
    failure still gets a best-effort local attempt. ``source_lang`` opts into
    :func:`route_pair` for the first hop.
    """
    routed = route_pair(source_lang, lang, table)
    return [routed] + [t for t in TIERS if t != routed]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class TranslationError(RuntimeError):
    """All tiers failed (or none were available). Surfaces via job.done (A6.3)."""


class TierUnavailableError(TranslationError):
    """A single tier cannot run (no runner / no GGUF configured / no cloud key).

    Internal to the fallback chain: the chain logs it and moves on; only when
    EVERY tier fails does the aggregate :class:`TranslationError` escape.
    """


# --------------------------------------------------------------------------- #
# Prompt build (pure, unit-testable)
# --------------------------------------------------------------------------- #
_MT_SYSTEM = (
    "You are a professional subtitle translator. Translate the user's text into "
    "{target}. Reply with ONLY the translation — no quotes, no notes, no "
    "explanation. Preserve meaning and keep it concise enough to read as a "
    "subtitle."
)
# CONTRACT-NOTE: TranslateGemma's opinionated source/target content format is
# applied by the GGUF's own chat template inside the llama.cpp server; through
# the Provider seam we send plain system+user instruction messages (the same
# shape features/subtitles.py already uses), which the community GGUF cards
# document for llama-cli/server use.


#: Preamble for the neighbouring-sentence context (T2, folded into T1). The context
#: rides the SYSTEM message so the user message stays the bare text to translate and
#: the "reply with ONLY the translation" instruction is never diluted.
_MT_CONTEXT = (
    " The surrounding transcript below is given for CONTEXT ONLY — use it to get "
    "gender, number, tense and referents right, but translate ONLY the user's text "
    "and never repeat any of the context."
)

#: Max characters of source text joined into ONE sentence-level translation call.
#: A bound is required: a transcript is unbounded, and an unbounded prompt would
#: blow the local server's context window.
SENTENCE_GROUP_MAX_CHARS: int = 400
#: Max characters of neighbouring source text passed as context, per side.
CONTEXT_MAX_CHARS: int = 300


def _clip_context(raw: str | None, *, keep_tail: bool) -> str:
    """Whitespace-normalize ``raw`` and clip it to :data:`CONTEXT_MAX_CHARS`.

    ``keep_tail`` keeps the END of the text (for the PRECEDING context, whose last
    words are the ones adjacent to the translated sentence); otherwise the START is
    kept (for the FOLLOWING context). Pure.
    """
    body = " ".join(str(raw or "").split())
    if len(body) <= CONTEXT_MAX_CHARS:
        return body
    return body[-CONTEXT_MAX_CHARS:] if keep_tail else body[:CONTEXT_MAX_CHARS]


def build_messages(
    text: str,
    target_lang: str,
    source_lang: str | None = None,
    *,
    context_before: str | None = None,
    context_after: str | None = None,
) -> list[dict[str, str]]:
    """Build the 2-message chat for one SENTENCE-level translation.

    ``context_before`` / ``context_after`` are the neighbouring sentences' SOURCE
    text. Passing source (never previously-translated) text keeps the call
    order-independent and stops one bad translation propagating into the next.
    """
    system = _MT_SYSTEM.format(target=target_lang)
    if source_lang:
        system += f" The source language is {source_lang}."
    before = _clip_context(context_before, keep_tail=True)
    after = _clip_context(context_after, keep_tail=False)
    if before or after:
        system += _MT_CONTEXT
        if before:
            system += f'\nPreceding text: "{before}"'
        if after:
            system += f'\nFollowing text: "{after}"'
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def _is_blank(text: str) -> bool:
    return not text or not text.strip()


def _polish() -> Any:
    """The caption-polish module (LAZY import — it registers an asset at import).

    ``caption_polish`` owns the pure segmentation primitives this module reuses
    (``ends_sentence`` / ``redistribute_cue_text``); importing it lazily keeps
    ``models.translation`` import-light and free of that asset-registration
    side-effect until a translation actually runs.
    """
    from ..features import caption_polish  # noqa: PLC0415 - lazy: see the docstring

    return caption_polish


def cue_text(cue: Cue) -> str:
    """One cue's text, whitespace-normalized.

    The flattening is load-bearing: ``captionPolish`` runs at GENERATE time
    (``handlers/media_ops.py`` ``subtitles_generate``) and translation runs later over
    the persisted track, so ``caption_polish.wrap_two_lines`` has already inserted
    HARD line breaks into the cue text. Feeding those to the model is the audit's
    suspected fourth root cause; this is where they are removed.
    """
    return " ".join(str(cue.get("text", "") or "").split())


def group_text(group: Sequence[Cue]) -> str:
    """The joined, whitespace-normalized source text of one translation group."""
    return " ".join(cue_text(cue) for cue in group).strip()


def group_cues_for_translation(
    cues: Sequence[Cue],
    *,
    max_chars: int = SENTENCE_GROUP_MAX_CHARS,
) -> list[list[Cue]]:
    """Group consecutive cues into SENTENCE-level translation units (pure).

    Caption cues are segmented for READING SPEED (``subtitles.cues_from_transcript``
    splits on ``max_chars`` / ``max_duration``), so one sentence routinely spans two
    or three cues. Translating each fragment alone is the mechanical cause of the
    owner's "bad translations"
    (`docs/plans/v1.5/captions-translation-audit-2026-08.md` §3.1/§3.2) — for
    verb-final or different-word-order targets (de, ja, ko, tr, hi) a fragment simply
    cannot be translated correctly in isolation.

    A group closes when: the cue ends a sentence (:func:`caption_polish.ends_sentence`),
    OR adding the next cue would pass ``max_chars``, OR the cues run out. A BLANK cue
    is never merged — it becomes its own group and passes through untranslated, so a
    gap in the transcript can never glue two unrelated sentences together.
    """
    ends = _polish().ends_sentence
    groups: list[list[Cue]] = []
    current: list[Cue] = []
    current_len = 0

    def close() -> None:
        nonlocal current, current_len
        if current:
            groups.append(current)
            current = []
            current_len = 0

    for cue in cues:
        text = cue_text(cue)
        if _is_blank(text):
            close()
            groups.append([cue])
            continue
        if current and current_len + 1 + len(text) > max_chars:
            close()
        current_len += len(text) + (1 if current else 0)
        current.append(cue)
        if ends(text):
            close()
    close()
    return groups


def _make_cue(index: int, start: float, end: float, text: str) -> Cue:
    """A §3 Cue dict (field names frozen; mirrors features.subtitles.make_cue)."""
    return {"index": int(index), "start": float(start), "end": float(end), "text": text}


# --------------------------------------------------------------------------- #
# TieredTranslator
# --------------------------------------------------------------------------- #
# Factory seams (injected in tests): () -> a Provider-like object with .chat().
ProviderFactory = Callable[[], Any]


class TieredTranslator:
    """Routes cue translation across tier1/tier2/tier3 with fallback (T3.1).

    Everything heavy is injected:
      * ``runner``      — the shared :class:`models.runner.ModelRunner`; local
                          tiers call ``start_server(gguf_path=...)`` on it (its
                          model-identity awareness handles the GGUF swap).
      * ``local_provider_factory``  — builds the provider that talks to the
                          local llama.cpp server (default: LocalServerProvider
                          honoring ``settings.localBaseUrl``).
      * ``hosted_provider_factory`` — builds the tier3 provider (default:
                          CloudProvider iff ``settings.cloudApiKey`` is set).

    CONTRACT-NOTE: tier3 availability is keyed on a non-empty
    ``settings.cloudApiKey`` alone (§2 names it optional); ``useCloud`` governs
    the *general-LLM* provider choice in ``provider.get_provider`` and is not
    re-checked here — routing to tier3 is an explicit per-language decision.
    """

    def __init__(
        self,
        *,
        runner: Any | None = None,
        settings: dict[str, Any] | None = None,
        local_provider_factory: ProviderFactory | None = None,
        hosted_provider_factory: ProviderFactory | None = None,
        routing: dict[str, str] | None = None,
        tier2_gpu_layers: int = TIER2_GPU_LAYERS,
        ensure: Callable[[], None] | None = None,
    ) -> None:
        self._runner = runner
        self._settings = dict(settings or {})
        self._local_factory = local_provider_factory
        self._hosted_factory = hosted_provider_factory
        self._routing = routing
        self._tier2_gpu_layers = int(tier2_gpu_layers)
        # WU-B2: the injected llama-backstop ensure() callback. A local tier calls
        # ``start_server`` then this readiness probe, so a subtitle/dub translation
        # never hits the server before it is listening (fixes "LLM 10061"). ``None``
        # keeps the legacy behaviour (no probe). The engine layer that owns the
        # ModelRunner builds and injects it (this module stays runner-agnostic).
        self._ensure = ensure

    # -- routing ------------------------------------------------------------
    def route(self, target_lang: str) -> str:
        """The tier this translator routes ``target_lang`` to."""
        return route(target_lang, self._routing)

    def chain_for(self, target_lang: str, source_lang: str | None = None) -> list[str]:
        """The full fallback chain for ``target_lang`` (routed tier first).

        ``source_lang`` opts the first hop into pair routing (:func:`route_pair`), so a
        low-resource SOURCE escalates to the heavier local model.
        """
        return fallback_chain(target_lang, self._routing, source_lang=source_lang)

    # -- the batched seam (T2 dub + subtitles.translate job body) -----------
    def translate(
        self,
        cues: Sequence[Cue],
        target_lang: str,
        *,
        source_lang: str | None = None,
        progress: Callable[[int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[Cue]:
        """Translate ``cues`` into ``target_lang`` — the ``translate(cues,
        targetLang)`` callable the T2 dub pipeline consumes.

        Translation is **sentence-scoped**: consecutive cues that belong to one
        sentence are joined into a single call carrying the neighbouring sentences as
        context, and the reply is laid back over the SAME cue timings (T1 — see
        :func:`group_cues_for_translation` and
        :func:`caption_polish.redistribute_cue_text`). Cue count, indices and timings
        are preserved exactly; only the text changes.

        Tries the routed tier first; on any tier failure the WHOLE batch is
        retried on the next tier (a mid-batch failure discards that tier's
        partial output, so the result is never a mixed-tier patchwork).
        Cooperative cancellation mirrors ``features.subtitles.translate``:
        when ``cancelled()`` turns true the loop stops (at a sentence boundary) and
        the cues translated so far are returned. Raises :class:`TranslationError` when
        every tier fails — the job body lets that surface via job.done (A6 lesson 3).
        """
        cue_list = list(cues or [])
        if not cue_list:
            return []
        failures: list[str] = []
        for tier in self.chain_for(target_lang, source_lang):
            try:
                return self._translate_with_tier(tier, cue_list, target_lang, source_lang, progress, cancelled)
            except Exception as exc:  # noqa: BLE001 - each tier failure feeds the chain
                log.warning("translation %s failed for %r: %s", tier, target_lang, exc)
                failures.append(f"{tier}: {exc}")
        raise TranslationError(f"all translation tiers failed for {target_lang!r} ({'; '.join(failures)})")

    def translate_track(
        self,
        track: SubtitleTrack,
        target_lang: str,
        *,
        source_lang: str | None = None,
        progress: Callable[[int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> SubtitleTrack:
        """``subtitles.translate`` job body: a NEW track, ``lang`` updated.

        Same output shape as ``features.subtitles.translate`` (timings/indices
        preserved, input track not mutated).
        """
        new_cues = self.translate(
            track.get("cues") or [],
            target_lang,
            source_lang=source_lang,
            progress=progress,
            cancelled=cancelled,
        )
        updated = dict(track)
        updated["lang"] = target_lang
        updated["cues"] = new_cues
        return updated

    # -- the str -> str adapter (features.subtitles.translate translator=) --
    def line_translator(self, target_lang: str, *, source_lang: str | None = None) -> Callable[[str], str]:
        """A stateful one-line translator for the existing LineTranslator seam.

        Lazily binds the routed tier's provider on first use; a failing line
        escalates to the next tier in the chain and STAYS there (no per-line
        tier thrash). Raises :class:`TranslationError` once the chain is spent.

        CONTRACT-NOTE: this seam is ``str -> str`` by construction, so it is the ONE
        path that cannot see a sentence's neighbours — a caller that wants the T1
        sentence-level quality must use :meth:`translate` / :meth:`translate_track`,
        which take whole cue lists. It has no production caller today (only
        ``features.subtitles.translate(translator=...)``, which the handler does not
        use); it is kept for that seam's signature.
        """
        chain = list(self.chain_for(target_lang, source_lang))
        state: dict[str, Any] = {"provider": None, "label": ""}

        def _translate(text: str) -> str:
            if _is_blank(text):
                return text
            failures: list[str] = []
            while True:
                if state["provider"] is None:
                    if not chain:
                        raise TranslationError(
                            f"all translation tiers failed for {target_lang!r} ({'; '.join(failures)})"
                        )
                    tier = chain.pop(0)
                    try:
                        state["provider"] = self._tier_provider(tier)
                        state["label"] = self._tier_label(tier)
                    except Exception as exc:  # noqa: BLE001 - feed the chain
                        log.warning("translation %s unavailable: %s", tier, exc)
                        failures.append(f"{tier}: {exc}")
                        continue
                try:
                    return self._chat_one(state["provider"], text, target_lang, source_lang)
                except Exception as exc:  # noqa: BLE001 - escalate to next tier
                    log.warning("translation line failed on %s: %s", state["label"], exc)
                    failures.append(f"{state['label']}: {exc}")
                    state["provider"] = None

        return _translate

    # -- per-tier internals --------------------------------------------------
    def _tier_label(self, tier: str) -> str:
        """The progress label for a tier (the heavy tier is marked SLOW)."""
        if tier == TIER_LOCAL_HEAVY:
            return f"{tier} ({SLOW_LABEL})"
        return tier

    def _translate_with_tier(
        self,
        tier: str,
        cues: list[Cue],
        target_lang: str,
        source_lang: str | None,
        progress: Callable[[int, str], None] | None,
        cancelled: Callable[[], bool] | None,
    ) -> list[Cue]:
        """Translate the whole batch on ONE tier, sentence by sentence (raises on failure).

        One provider call per SENTENCE group, not per cue; the reply is redistributed
        onto the group's own cues so timings never move. Progress is still reported per
        CUE so the job bar keeps its granularity.
        """
        provider = self._tier_provider(tier)
        label = self._tier_label(tier)
        groups = group_cues_for_translation(cues)
        texts = [group_text(group) for group in groups]
        redistribute = _polish().redistribute_cue_text
        total = len(cues)
        out: list[Cue] = []
        for position, group in enumerate(groups):
            if cancelled is not None and cancelled():
                break
            source_text = texts[position]
            if _is_blank(source_text):
                translated_cues: list[Cue] = list(group)
            else:
                reply = self._chat_one(
                    provider,
                    source_text,
                    target_lang,
                    source_lang,
                    context_before=texts[position - 1] if position else None,
                    context_after=texts[position + 1] if position + 1 < len(groups) else None,
                )
                translated_cues = redistribute(group, reply)
            done = len(out)
            for offset, cue in enumerate(translated_cues):
                out.append(
                    _make_cue(
                        int(cue.get("index", done + offset + 1)),
                        float(cue.get("start", 0.0)),
                        float(cue.get("end", 0.0)),
                        str(cue.get("text", "")),
                    )
                )
            if progress is not None and total:
                for count in range(done + 1, len(out) + 1):
                    progress(int(round(count / total * 100)), f"{label}: translated {count}/{total}")
        return out

    def _tier_provider(self, tier: str) -> Any:
        """Materialize the provider for ``tier`` (raises :class:`TierUnavailableError`).

        Local tiers ensure the llama.cpp server is serving the tier's GGUF
        first — ``ModelRunner.start_server`` reuses the live process for the
        same model and restarts it for a different one (T3 runner change).
        """
        if tier == TIER_HOSTED:
            return self._hosted_provider()
        if tier in (TIER_LOCAL, TIER_LOCAL_HEAVY):
            return self._local_provider(tier)
        raise TierUnavailableError(f"unknown translation tier: {tier!r}")

    def _local_provider(self, tier: str) -> Any:
        if self._runner is None:
            raise TierUnavailableError(f"{tier} unavailable: no model runner")
        gguf = self.tier_gguf_path(tier)
        if not gguf:
            raise TierUnavailableError(
                f"{tier} unavailable: no MT GGUF configured (install the asset or set settings.modelsDir)"
            )
        if tier == TIER_LOCAL_HEAVY:
            # Partial offload: the 12B Q4 exceeds 6GB VRAM (survey §2) — SLOW.
            self._runner.start_server(gguf_path=gguf, gpu_layers=self._tier2_gpu_layers)
        else:
            self._runner.start_server(gguf_path=gguf)
        # WU-B2: bounded readiness probe AFTER the spawn so the first chat never
        # races the not-yet-listening server; a slow/failed start raises loudly.
        if self._ensure is not None:
            self._ensure()
        if self._local_factory is not None:
            return self._local_factory()
        return provider_mod.LocalServerProvider(
            base_url=str(self._settings.get("localBaseUrl") or provider_mod.DEFAULT_LOCAL_BASE_URL)
        )

    def _hosted_provider(self) -> Any:
        if self._hosted_factory is not None:
            provider = self._hosted_factory()
            if provider is None:
                raise TierUnavailableError("tier3 unavailable: hosted factory returned None")
            return provider
        api_key = self._settings.get("cloudApiKey") or ""
        if not api_key:
            raise TierUnavailableError("tier3 unavailable: no cloudApiKey configured")
        return provider_mod.CloudProvider(
            api_key=str(api_key),
            base_url=str(self._settings.get("cloudBaseUrl") or provider_mod.DEFAULT_CLOUD_BASE_URL),
            model=str(self._settings.get("cloudModel") or provider_mod.DEFAULT_CLOUD_MODEL),
        )

    def _chat_one(
        self,
        provider: Any,
        text: str,
        target_lang: str,
        source_lang: str | None,
        *,
        context_before: str | None = None,
        context_after: str | None = None,
    ) -> str:
        """One sentence through ``provider.chat`` -> stripped translation string."""
        reply = provider.chat(
            build_messages(
                text,
                target_lang,
                source_lang,
                context_before=context_before,
                context_after=context_after,
            )
        )
        return str(reply).strip()

    # -- gguf resolution ------------------------------------------------------
    def tier_gguf_path(self, tier: str) -> str | None:
        """Resolve the GGUF path for a local tier from settings.

        Order: explicit ``settings.translateGgufPath`` (tier1) /
        ``settings.translateTier2GgufPath`` (tier2) -> ``settings.modelsDir`` +
        the pinned file name -> the first-run PROVISIONING location
        ``<configDir>/models/<name>`` (matching the manifest entry's dest, so the
        assets-managed copy is found automatically on a DEFAULT install where
        ``modelsDir`` is empty). Mirrors :func:`runner.resolve_gguf_path`: the
        settings-driven hops stay string-only; the provisioning hop is existence-
        checked and confined via ``ensure_within`` (the CodeQL py/path-injection
        barrier) so a not-yet-provisioned machine still yields ``None``.

        CONTRACT-NOTE: §2's settings enumerate ``modelsDir``; the two explicit
        ``translate*GgufPath`` overrides are optional extras, NOT required by
        the contract.
        """
        if tier == TIER_LOCAL:
            explicit = self._settings.get("translateGgufPath")
            name = TIER1_GGUF_NAME
        elif tier == TIER_LOCAL_HEAVY:
            explicit = self._settings.get("translateTier2GgufPath")
            name = TIER2_GGUF_NAME
        else:
            return None
        if explicit:
            return str(explicit)
        models_dir = self._settings.get("modelsDir")
        if models_dir:
            base = str(models_dir).replace("\\", "/").rstrip("/")
            return f"{base}/{name}"
        from ..settings_store import default_config_dir  # local import: avoids a cycle

        provisioned = ensure_within(default_config_dir(), "models", name)
        if os.path.isfile(provisioned):
            return provisioned.replace(os.sep, "/")
        return None


def _default_hosted_factory(
    settings: dict[str, Any] | None,
    *,
    transport: Any | None,
    prefer: str | None = None,
) -> ProviderFactory:
    """Build the tier3 hosted-provider factory shared with the general LLM seam.

    The tier3 (``TIER_HOSTED``) provider resolves through the SAME
    :func:`~media_studio.models.provider.get_provider` factory the general LLM
    seam uses (WU-pool: BOTH seams), so a hosted translation call rotates/fails-
    over identically when ``settings.providers`` is configured and otherwise
    follows the legacy cloud/local routing. The factory raises
    :class:`TierUnavailableError` (not the generic local fall-through) when there
    is no pool AND no ``cloudApiKey`` — tier3 is an EXPLICIT hosted decision, so a
    bare local server is not a valid tier3 provider.
    """
    settings = settings or {}

    def _factory() -> Any:
        # WU-presets: when the translation function routes to LOCAL, the tier3
        # hosted provider IS the local backstop pool (an explicit local choice,
        # never the no-pool failure) so a privacy-routed translation never egresses.
        if prefer == provider_mod.LOCAL_PROVIDER_ID:
            return provider_mod.get_provider(settings, transport=transport, prefer=prefer)
        has_pool = bool(provider_mod._cloud_specs_from_settings(settings))
        has_cloud_key = bool(settings.get("cloudApiKey"))
        if not has_pool and not has_cloud_key:
            raise TierUnavailableError("tier3 unavailable: no provider pool and no cloudApiKey configured")
        merged = dict(settings)
        if has_cloud_key:
            # The legacy single-cloud path expects useCloud to gate CloudProvider.
            merged.setdefault("useCloud", True)
        return provider_mod.get_provider(merged, transport=transport, prefer=prefer)

    return _factory


def get_translator(
    settings: dict[str, Any] | None = None,
    *,
    runner: Any | None = None,
    transport: Any | None = None,
    prefer: str | None = None,
    ensure: Callable[[], None] | None = None,
    **seams: Any,
) -> TieredTranslator:
    """Factory the wiring layer calls (mirrors ``provider.get_provider``).

    The tier3 hosted provider resolves through the SAME rotation pool / cloud
    factory as the general LLM seam (WU-pool). ``prefer`` (WU-presets) is the
    configured provider id the translation function prefers; it is threaded into
    the hosted factory so the tier3 pool tries that provider first
    (``LOCAL_PROVIDER_ID`` -> a local-only hosted pool). An explicit
    ``hosted_provider_factory`` in ``seams`` still wins (tests / overrides).
    """
    if "hosted_provider_factory" not in seams:
        seams["hosted_provider_factory"] = _default_hosted_factory(settings, transport=transport, prefer=prefer)
    return TieredTranslator(runner=runner, settings=settings, ensure=ensure, **seams)


# --------------------------------------------------------------------------- #
# U4 manifest entries — the chosen MT GGUFs (PINNED urls; A6 lesson 5)
# --------------------------------------------------------------------------- #
def _detect_existing(explicit_key: str, name: str) -> Callable[[dict[str, Any]], str | None]:
    """Build a settings-driven existing-path probe for one MT GGUF (U4 detect)."""

    def _probe(settings: dict[str, Any]) -> str | None:
        settings = settings or {}
        explicit = settings.get(explicit_key)
        if explicit:
            p = Path(str(explicit))
            if p.is_file():
                return str(p)
        models_dir = settings.get("modelsDir")
        if models_dir:
            cand = Path(str(models_dir)) / name
            if cand.is_file():
                return str(cand)
        return None

    return _probe


detect_existing_tier1_gguf = _detect_existing("translateGgufPath", TIER1_GGUF_NAME)
detect_existing_tier2_gguf = _detect_existing("translateTier2GgufPath", TIER2_GGUF_NAME)


def _register_mt_assets() -> None:
    """Register the survey-chosen MT GGUFs (idempotent re-register is a no-op).

    F3c: sha256 + HF commit revision are now PINNED (verified via the HF tree +
    revision APIs). URLs + quant sizes: docs/research/MT-MODELS-2026.md §2.
    """
    register_asset(
        AssetEntry(
            name=TIER1_ASSET_NAME,
            kind="model",
            size_mb=TIER1_SIZE_MB,
            dest=f"models/{TIER1_GGUF_NAME}",
            label="TranslateGemma-4B Q4_K_M (translation, tier 1)",
            installer="download",
            url=TIER1_GGUF_URL,
            sha256=TIER1_GGUF_SHA256,
            detect=detect_existing_tier1_gguf,
        )
    )
    register_asset(
        AssetEntry(
            name=TIER2_ASSET_NAME,
            kind="model",
            size_mb=TIER2_SIZE_MB,
            dest=f"models/{TIER2_GGUF_NAME}",
            label="TranslateGemma-12B Q4_K_M (translation, tier 2 — SLOW)",
            installer="download",
            url=TIER2_GGUF_URL,
            sha256=TIER2_GGUF_SHA256,
            detect=detect_existing_tier2_gguf,
        )
    )


_register_mt_assets()
