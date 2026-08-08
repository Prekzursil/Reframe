"""Tiered subtitle translation (T3): local MT GGUF -> heavy local -> hosted.

The survey (``docs/research/MT-MODELS-2026.md``, verified live 2026-06-12) picked
the tier STRUCTURE; WU-A1 re-picked the WEIGHTS on licence grounds (see below):

  * **tier1** — Qwen3-4B Q4_K_M (2.5GB, fully GPU-resident, **Apache-2.0**): the
    fast local default for high/mid-resource languages. This is the SAME asset
    the general-LLM seam already installs (``manifest.QWEN_ASSET_NAME``), so it
    costs zero extra download and zero extra disk.
  * **tier2** — Qwen3-8B Q4_K_M (5.03GB, PARTIAL offload, **Apache-2.0**,
    labelled ``SLOW`` in progress messages): the low-resource/quality tier.
  * **tier3** — a hosted OpenAI-compatible provider
    (:class:`~media_studio.models.provider.CloudProvider`): everything outside
    local coverage.

**WU-A1 licence remediation (why the weights changed).** tier1/tier2 previously
pinned TranslateGemma-4B/12B, whose authoritative Hugging Face tag is
``license:gemma`` — "Open Weights", **not** OSI-permissive: gated, carrying a
Prohibited-Use Policy and a downstream pass-through obligation.
``docs/plans/v1.5/flagship-lip-sync-dub.md:94`` grades that a **commercial
BLOCKER** in the shipping path, and the owner's constraint is MIT/Apache/BSD only
for anything a commercial build ships. Both tiers are now Apache-2.0 Qwen3 GGUFs
running on the SAME llama.cpp :class:`~media_studio.models.runner.ModelRunner`, so
this is a drop-in weight swap: no new runner seam, and the routing table, the
fallback chain and the prompt shape are all unchanged.

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

from ..assets.manifest import QWEN_ASSET_NAME, QWEN_DEST, AssetEntry, register_asset
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
TIER_LOCAL: str = "tier1"  # Qwen3-4B Q4_K_M, fully resident
TIER_LOCAL_HEAVY: str = "tier2"  # Qwen3-8B Q4_K_M, partial offload, SLOW
TIER_HOSTED: str = "tier3"  # hosted OpenAI-compatible provider
TIERS: tuple[str, ...] = (TIER_LOCAL, TIER_LOCAL_HEAVY, TIER_HOSTED)

#: The progress label the heavy tier carries (the T3 brief: "label SLOW").
SLOW_LABEL: str = "SLOW"

# Pinned artifacts. File names double as the modelsDir lookup names.
# F3c: the resolve URLs pin a COMMIT HASH (not "main") and carry the file's LFS
# oid as sha256.

# tier1 IS the general-LLM Qwen3-4B asset the app already installs at "core"
# tier, so WU-A1 registers NOTHING for it: the swap costs zero new download, and
# because the resolved path is byte-identical to the one the general-LLM seam
# uses, ModelRunner.start_server REUSES a live llama.cpp process across an
# LLM -> MT hand-off instead of restarting it on a different GGUF.
TIER1_ASSET_NAME: str = QWEN_ASSET_NAME
TIER1_GGUF_NAME: str = QWEN_DEST.rsplit("/", 1)[-1]

# tier2 — Qwen3-8B Q4_K_M (Apache-2.0). Commit + sha256 verified live 2026-08-08
# via the HF revision + tree APIs; the SAME probe re-derived the already-shipped
# Qwen3-4B pin (manifest.QWEN_GGUF_COMMIT / QWEN_SHA256) byte-for-byte, which is
# the detector control proving the probe reads real values rather than plausible
# ones. Note this is SMALLER than the 7.58 GB weight it replaces.
TIER2_GGUF_NAME: str = "Qwen3-8B-Q4_K_M.gguf"
TIER2_GGUF_COMMIT: str = "7c41481f57cb95916b40956ab2f0b139b296d974"
TIER2_GGUF_URL: str = f"https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/{TIER2_GGUF_COMMIT}/{TIER2_GGUF_NAME}"
TIER2_GGUF_SHA256: str = "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
TIER2_SIZE_MB: int = 5030  # 5,027,783,488 B (HF tree API)
TIER2_ASSET_NAME: str = "qwen3-8b-gguf"

#: Partial offload for the heavy tier on a 6GB card.
#: UNVERIFIED — this number was sized analytically for the 7.58GB
#: TranslateGemma-12B and is CARRIED OVER UNCHANGED. The 5.03GB Qwen3-8B leaves
#: more headroom so a higher count very likely (~80-90%) fits, but no GPU was
#: measured in this change and guessing a runtime value is fabrication. Settle
#: it by running ``llama-server --n-gpu-layers N`` on the 6GB target and taking
#: the largest N that does not spill to host RAM.
TIER2_GPU_LAYERS: int = 24

# --------------------------------------------------------------------------- #
# WU-A1 licence gate — MIT/Apache/BSD ONLY for anything a commercial build ships
# --------------------------------------------------------------------------- #
#: SPDX ids a commercial Reframe build may ship a model weight under. Deliberately
#: excludes ``gemma`` (Open Weights, gated, use-restricted), ``cc-by-nc-*``,
#: ``creativeml-openrail-m`` / ``openrail++`` and ``cc-by-4.0`` (attribution is
#: outside the owner's strict gate) — see flagship-lip-sync-dub.md §3.2 / §7.
PERMISSIVE_LICENCES: frozenset[str] = frozenset({"apache-2.0", "mit", "bsd-3-clause"})

#: MT asset name -> (the HF repo its pin MUST resolve from, verified SPDX id).
#: Verified 2026-08-08 against the HF model-metadata API; the Qwen3-8B repo's
#: LICENSE file independently reads "Apache License / Version 2.0" (a second,
#: mechanically different signal from the tag). ``test_mt_weight_licences_are_
#: permissive`` re-derives the repo from the REGISTERED url, so this record
#: cannot drift away from the artifact that is actually downloaded.
MT_WEIGHT_LICENCES: dict[str, tuple[str, str]] = {
    TIER1_ASSET_NAME: ("Qwen/Qwen3-4B-GGUF", "apache-2.0"),
    TIER2_ASSET_NAME: ("Qwen/Qwen3-8B-GGUF", "apache-2.0"),
}

# --------------------------------------------------------------------------- #
# Routing table (survey §3) — normalized ISO 639-1 code -> tier
# --------------------------------------------------------------------------- #
TIER1_LANGS: frozenset = frozenset(
    {
        "ar",
        "bg",
        "ca",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fa",
        "fi",
        "fr",
        "he",
        "hi",
        "hr",
        "hu",
        "id",
        "it",
        "ja",
        "ko",
        "lt",
        "lv",
        "ms",
        "nb",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sr",
        "sv",
        "th",
        "tr",
        "uk",
        "vi",
        "zh",
    }
)
TIER2_LANGS: frozenset = frozenset({"bn", "gu", "is", "kn", "ml", "mr", "pa", "sw", "ta", "te", "ur", "zu"})

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


def fallback_chain(lang: str, table: dict[str, str] | None = None) -> list[str]:
    """The tier order to attempt for ``lang``: routed tier first, then the rest.

    The remaining tiers follow in ascending order (tier1 -> tier2 -> tier3), so
    e.g. a tier2-routed language falls back to tier1 then tier3, and a hosted
    failure still gets a best-effort local attempt.
    """
    routed = route(lang, table)
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
# CONTRACT-NOTE: the GGUF's own chat template is applied inside the llama.cpp
# server; through the Provider seam we send plain system+user instruction
# messages (the same shape features/subtitles.py already uses). WU-A1: this is
# why the Gemma -> Qwen3 swap needs no prompt change — the previous note said the
# template applied "TranslateGemma's opinionated source/target content format",
# but that formatting lives in the template, not in what we send, so an
# instruction-tuned Qwen3 consumes the identical 2-message shape.


def build_messages(text: str, target_lang: str, source_lang: str | None = None) -> list[dict[str, str]]:
    """Build the 2-message chat for one cue translation."""
    system = _MT_SYSTEM.format(target=target_lang)
    if source_lang:
        system += f" The source language is {source_lang}."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def _is_blank(text: str) -> bool:
    return not text or not text.strip()


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

    def chain_for(self, target_lang: str) -> list[str]:
        """The full fallback chain for ``target_lang`` (routed tier first)."""
        return fallback_chain(target_lang, self._routing)

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

        Tries the routed tier first; on any tier failure the WHOLE batch is
        retried on the next tier (a mid-batch failure discards that tier's
        partial output, so the result is never a mixed-tier patchwork).
        Cooperative cancellation mirrors ``features.subtitles.translate``:
        when ``cancelled()`` turns true the loop stops and the cues translated
        so far are returned. Raises :class:`TranslationError` when every tier
        fails — the job body lets that surface via job.done (A6 lesson 3).
        """
        cue_list = list(cues or [])
        if not cue_list:
            return []
        failures: list[str] = []
        for tier in self.chain_for(target_lang):
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
        """
        chain = list(self.chain_for(target_lang))
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
        """Translate the whole batch on ONE tier (raises on any failure)."""
        provider = self._tier_provider(tier)
        label = self._tier_label(tier)
        total = len(cues)
        out: list[Cue] = []
        for i, cue in enumerate(cues):
            if cancelled is not None and cancelled():
                break
            text = str(cue.get("text", ""))
            new_text = text if _is_blank(text) else self._chat_one(provider, text, target_lang, source_lang)
            out.append(
                _make_cue(
                    int(cue.get("index", i + 1)),
                    float(cue.get("start", 0.0)),
                    float(cue.get("end", 0.0)),
                    new_text,
                )
            )
            if progress is not None and total:
                progress(
                    int(round((i + 1) / total * 100)),
                    f"{label}: translated {i + 1}/{total}",
                )
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
            # Partial offload: the 8B Q4 (5.03GB) plus context exceeds 6GB VRAM — SLOW.
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

    def _chat_one(self, provider: Any, text: str, target_lang: str, source_lang: str | None) -> str:
        """One cue through ``provider.chat`` -> stripped translation string."""
        reply = provider.chat(build_messages(text, target_lang, source_lang))
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


detect_existing_tier2_gguf = _detect_existing("translateTier2GgufPath", TIER2_GGUF_NAME)


def _register_mt_assets() -> None:
    """Register the heavy MT tier (idempotent re-register is a no-op).

    tier1 registers NOTHING. It reuses ``manifest.QWEN_ASSET_NAME`` — the
    Apache-2.0 Qwen3-4B GGUF the general-LLM seam already installs at "core"
    tier — so a second entry for byte-identical weights would pull a redundant
    ~2.5 GB into a second dest. The heavy tier is the only asset this module owns.

    F3c: sha256 + HF commit revision are PINNED (verified via the HF tree +
    revision APIs, 2026-08-08).
    """
    register_asset(
        AssetEntry(
            name=TIER2_ASSET_NAME,
            kind="model",
            size_mb=TIER2_SIZE_MB,
            dest=f"models/{TIER2_GGUF_NAME}",
            label="Qwen3-8B Q4_K_M (translation, tier 2 — SLOW, Apache-2.0)",
            installer="download",
            url=TIER2_GGUF_URL,
            sha256=TIER2_GGUF_SHA256,
            detect=detect_existing_tier2_gguf,
        )
    )


_register_mt_assets()
