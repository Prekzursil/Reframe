"""Unit tests for media_studio.models.translation (T3 tiered translation).

Everything heavy is mocked: the model runner is a fake (or a real ModelRunner
driven by a fake popen — no process), providers are fakes (no network), and no
GGUF file is ever touched. Covers: routing table -> correct tier per language,
the fallback chain on tier failure, the SLOW labelling of tier2, cooperative
cancellation, the translate_track / line_translator seams, GGUF resolution from
settings, and the U4 manifest registration of the chosen MT GGUFs.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.assets import manifest
from media_studio.models.provider import (
    CloudProvider,
    LocalServerProvider,
    ProviderError,
)
from media_studio.models.runner import ModelRunner
from media_studio.models.translation import (
    DEFAULT_TIER,
    ROUTING_TABLE,
    TIER1_ASSET_NAME,
    TIER1_GGUF_NAME,
    TIER2_ASSET_NAME,
    TIER2_GGUF_NAME,
    TIER2_GPU_LAYERS,
    TIER_HOSTED,
    TIER_LOCAL,
    TIER_LOCAL_HEAVY,
    TIERS,
    TieredTranslator,
    TierUnavailableError,
    TranslationError,
    build_messages,
    fallback_chain,
    get_translator,
    normalize_lang,
    route,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeRunner:
    """Records start_server calls; never spawns anything."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.current_model_path: str | None = None

    def start_server(self, *, gguf_path=None, gpu_layers=None, extra_args=None):
        self.calls.append({"gguf_path": gguf_path, "gpu_layers": gpu_layers})
        self.current_model_path = gguf_path
        return object()


class FakeProvider:
    """A chat seam that records calls and can fail on demand.

    ``fail_at`` (0-based call ordinal) makes that chat call raise; ``fail_all``
    makes every call raise — both with ProviderError, the real seam's error.
    """

    def __init__(self, *, prefix: str = "XX", fail_all: bool = False, fail_at: int | None = None):
        self.prefix = prefix
        self.fail_all = fail_all
        self.fail_at = fail_at
        self.chats: list[list[dict[str, str]]] = []

    def chat(self, messages, **kwargs: Any) -> str:
        ordinal = len(self.chats)
        self.chats.append([dict(m) for m in messages])
        if self.fail_all or (self.fail_at is not None and ordinal == self.fail_at):
            raise ProviderError("provider down")
        return f"{self.prefix}:{messages[-1]['content']}"


def make_factory(providers: list[Any]):
    """A provider factory that returns the given providers in order."""
    queue = list(providers)
    built: list[Any] = []

    def factory():
        provider = queue.pop(0)
        built.append(provider)
        return provider

    factory.built = built  # type: ignore[attr-defined]
    return factory


def cues2() -> list[dict[str, Any]]:
    return [
        {"index": 1, "start": 0.0, "end": 1.5, "text": "hello there"},
        {"index": 2, "start": 1.5, "end": 3.0, "text": "good night"},
    ]


SETTINGS = {"modelsDir": "D:/models"}
TIER1_PATH = f"D:/models/{TIER1_GGUF_NAME}"
TIER2_PATH = f"D:/models/{TIER2_GGUF_NAME}"


def make_translator(
    *,
    runner: Any | None = None,
    settings: dict[str, Any] | None = None,
    local: list[Any] | None = None,
    hosted: list[Any] | None = None,
    routing: dict[str, str] | None = None,
) -> TieredTranslator:
    return TieredTranslator(
        runner=runner,
        settings=SETTINGS if settings is None else settings,
        local_provider_factory=make_factory(local) if local is not None else None,
        hosted_provider_factory=make_factory(hosted) if hosted is not None else None,
        routing=routing,
    )


# --------------------------------------------------------------------------- #
# normalize_lang / route / fallback_chain (pure routing logic)
# --------------------------------------------------------------------------- #
def test_normalize_lang_strips_region_and_case():
    assert normalize_lang("pt-BR") == "pt"
    assert normalize_lang("PT_br") == "pt"
    assert normalize_lang("EN") == "en"
    assert normalize_lang("zh_Hant") == "zh"
    assert normalize_lang("  es  ") == "es"


def test_normalize_lang_empty_raises():
    with pytest.raises(ValueError):
        normalize_lang("")
    with pytest.raises(ValueError):
        normalize_lang("   ")


def test_route_high_resource_to_tier1():
    for lang in ("es", "de", "ja", "zh", "pt-BR", "EN"):
        assert route(lang) == TIER_LOCAL, lang


def test_route_low_resource_to_tier2():
    for lang in ("sw", "ta", "bn", "is", "ta-IN"):
        assert route(lang) == TIER_LOCAL_HEAVY, lang


def test_route_uncovered_to_tier3():
    for lang in ("yo", "yue", "bo", "und", "xx"):
        assert route(lang) == TIER_HOSTED, lang
    assert DEFAULT_TIER == TIER_HOSTED


def test_route_custom_table_wins():
    assert route("es", {"es": TIER_HOSTED}) == TIER_HOSTED


def test_routing_table_values_are_known_tiers():
    assert set(ROUTING_TABLE.values()) <= set(TIERS)


def test_fallback_chain_orders():
    assert fallback_chain("es") == [TIER_LOCAL, TIER_LOCAL_HEAVY, TIER_HOSTED]
    assert fallback_chain("sw") == [TIER_LOCAL_HEAVY, TIER_LOCAL, TIER_HOSTED]
    assert fallback_chain("yo") == [TIER_HOSTED, TIER_LOCAL, TIER_LOCAL_HEAVY]


def test_translator_route_and_chain_use_instance_routing():
    t = make_translator(routing={"es": TIER_HOSTED})
    assert t.route("es") == TIER_HOSTED
    assert t.chain_for("es")[0] == TIER_HOSTED


# --------------------------------------------------------------------------- #
# build_messages (prompt build)
# --------------------------------------------------------------------------- #
def test_build_messages_shape_and_target():
    msgs = build_messages("hello", "fr")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "fr" in msgs[0]["content"]
    assert "ONLY the translation" in msgs[0]["content"]
    assert msgs[1]["content"] == "hello"


def test_build_messages_includes_source_lang_when_given():
    msgs = build_messages("hello", "fr", "en")
    assert "en" in msgs[0]["content"]
    no_src = build_messages("hello", "fr")
    assert "source language" not in no_src[0]["content"]


# --------------------------------------------------------------------------- #
# tier1: routed local translation
# --------------------------------------------------------------------------- #
def test_tier1_translates_and_starts_server_with_tier1_gguf():
    runner = FakeRunner()
    provider = FakeProvider()
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues2(), "es")
    assert [c["text"] for c in out] == ["XX:hello there", "XX:good night"]
    assert runner.calls == [{"gguf_path": TIER1_PATH, "gpu_layers": None}]


def test_tier1_preserves_timings_and_indices_immutably():
    runner = FakeRunner()
    src = cues2()
    t = make_translator(runner=runner, local=[FakeProvider()])
    out = t.translate(src, "de")
    assert [(c["index"], c["start"], c["end"]) for c in out] == [
        (1, 0.0, 1.5),
        (2, 1.5, 3.0),
    ]
    assert src[0]["text"] == "hello there"  # input not mutated
    assert out[0] is not src[0]


def test_blank_cue_skips_provider_call():
    runner = FakeRunner()
    provider = FakeProvider()
    cues = [
        {"index": 1, "start": 0.0, "end": 1.0, "text": "   "},
        {"index": 2, "start": 1.0, "end": 2.0, "text": "hi"},
    ]
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues, "es")
    assert out[0]["text"] == "   "  # passed through untranslated
    assert len(provider.chats) == 1  # only the non-blank cue hit the provider


def test_empty_cues_short_circuits_without_touching_runner():
    runner = FakeRunner()
    t = make_translator(runner=runner, local=[FakeProvider()])
    assert t.translate([], "es") == []
    assert runner.calls == []


def test_progress_emitted_with_pct_and_tier_label():
    runner = FakeRunner()
    seen: list[Any] = []
    t = make_translator(runner=runner, local=[FakeProvider()])
    t.translate(cues2(), "es", progress=lambda pct, msg: seen.append((pct, msg)))
    assert [p for p, _m in seen] == [50, 100]
    assert all("tier1" in m for _p, m in seen)


# --------------------------------------------------------------------------- #
# tier2: routed heavy local (offload + SLOW label)
# --------------------------------------------------------------------------- #
def test_tier2_routed_lang_uses_offload_and_slow_label():
    runner = FakeRunner()
    seen: list[str] = []
    t = make_translator(runner=runner, local=[FakeProvider()])
    out = t.translate(cues2(), "sw", progress=lambda _p, m: seen.append(m))
    assert len(out) == 2
    assert runner.calls == [{"gguf_path": TIER2_PATH, "gpu_layers": TIER2_GPU_LAYERS}]
    assert all("SLOW" in m for m in seen)


# --------------------------------------------------------------------------- #
# fallback chain on tier failure
# --------------------------------------------------------------------------- #
def test_tier1_failure_falls_back_to_tier2_full_batch():
    """A mid-batch tier1 failure discards the partial output: tier2 redoes ALL."""
    runner = FakeRunner()
    failing = FakeProvider(fail_at=1)  # dies on the SECOND cue
    working = FakeProvider(prefix="T2")
    t = make_translator(runner=runner, local=[failing, working])
    out = t.translate(cues2(), "es")
    # no mixed-tier patchwork: every cue came from the tier2 provider
    assert [c["text"] for c in out] == ["T2:hello there", "T2:good night"]
    assert len(working.chats) == 2
    # server was started for tier1 first, then switched to tier2 with offload
    assert runner.calls[0] == {"gguf_path": TIER1_PATH, "gpu_layers": None}
    assert runner.calls[1] == {"gguf_path": TIER2_PATH, "gpu_layers": TIER2_GPU_LAYERS}


def test_local_failures_fall_back_to_hosted():
    runner = FakeRunner()
    hosted = FakeProvider(prefix="CLOUD")
    t = make_translator(
        runner=runner,
        local=[FakeProvider(fail_all=True), FakeProvider(fail_all=True)],
        hosted=[hosted],
    )
    out = t.translate(cues2(), "es")
    assert [c["text"] for c in out] == ["CLOUD:hello there", "CLOUD:good night"]


def test_all_tiers_fail_raises_translation_error_with_reasons():
    runner = FakeRunner()
    t = make_translator(
        runner=runner,
        local=[FakeProvider(fail_all=True), FakeProvider(fail_all=True)],
        hosted=[FakeProvider(fail_all=True)],
    )
    with pytest.raises(TranslationError) as exc_info:
        t.translate(cues2(), "es")
    msg = str(exc_info.value)
    assert "tier1" in msg and "tier2" in msg and "tier3" in msg


def test_unavailable_local_tiers_skip_to_hosted():
    # No runner at all -> both local tiers unavailable -> hosted serves.
    hosted = FakeProvider(prefix="CLOUD")
    t = make_translator(runner=None, hosted=[hosted])
    out = t.translate(cues2(), "es")
    assert out[0]["text"] == "CLOUD:hello there"


def test_nothing_available_raises():
    t = make_translator(runner=None, settings={})  # no runner, no key, no factory
    with pytest.raises(TranslationError):
        t.translate(cues2(), "es")


def test_tier3_routed_lang_never_touches_the_runner():
    runner = FakeRunner()
    t = make_translator(runner=runner, hosted=[FakeProvider(prefix="CLOUD")])
    out = t.translate(cues2(), "yo")
    assert out[0]["text"] == "CLOUD:hello there"
    assert runner.calls == []


def test_hosted_unavailable_falls_back_to_local_for_tier3_lang():
    runner = FakeRunner()
    t = make_translator(runner=runner, local=[FakeProvider()])  # no hosted/no key
    out = t.translate(cues2(), "yo")
    assert out[0]["text"] == "XX:hello there"
    assert runner.calls[0]["gguf_path"] == TIER1_PATH


def test_hosted_tier_unavailable_without_cloud_key():
    # Without a factory, tier3 builds a CloudProvider from cloudApiKey; with an
    # empty key it is unavailable (the real CloudProvider construction is
    # covered by test_provider.py).
    t = TieredTranslator(runner=None, settings={"cloudApiKey": ""})
    with pytest.raises(TranslationError):
        t.translate(cues2(), "yo")


def test_hosted_factory_returning_none_is_unavailable():
    t = TieredTranslator(runner=None, settings={}, hosted_provider_factory=lambda: None)
    with pytest.raises(TranslationError) as exc_info:
        t.translate(cues2(), "yo")
    assert "tier3" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# cooperative cancellation (the job seam)
# --------------------------------------------------------------------------- #
def test_cancelled_mid_batch_returns_partial():
    runner = FakeRunner()
    provider = FakeProvider()
    flags = iter([False, True])  # allow cue 1, cancel before cue 2
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues2(), "es", cancelled=lambda: next(flags))
    assert len(out) == 1
    assert len(provider.chats) == 1


def test_cancelled_before_start_returns_empty():
    runner = FakeRunner()
    provider = FakeProvider()
    t = make_translator(runner=runner, local=[provider])
    out = t.translate(cues2(), "es", cancelled=lambda: True)
    assert out == []
    assert provider.chats == []


# --------------------------------------------------------------------------- #
# translate_track (the subtitles.translate job body)
# --------------------------------------------------------------------------- #
def test_translate_track_returns_new_track_with_lang():
    runner = FakeRunner()
    track = {
        "id": "trk1",
        "lang": "en",
        "name": "English",
        "format": "srt",
        "kind": "soft",
        "cues": cues2(),
    }
    t = make_translator(runner=runner, local=[FakeProvider()])
    out = t.translate_track(track, "es")
    assert out["lang"] == "es"
    assert out["id"] == "trk1"
    assert [c["text"] for c in out["cues"]] == ["XX:hello there", "XX:good night"]
    assert track["lang"] == "en"  # input not mutated
    assert track["cues"][0]["text"] == "hello there"


# --------------------------------------------------------------------------- #
# line_translator (the features.subtitles LineTranslator seam)
# --------------------------------------------------------------------------- #
def test_line_translator_translates_and_binds_tier_once():
    runner = FakeRunner()
    provider = FakeProvider()
    factory = make_factory([provider])
    t = TieredTranslator(runner=runner, settings=SETTINGS, local_provider_factory=factory)
    line = t.line_translator("es")
    assert line("hello") == "XX:hello"
    assert line("bye") == "XX:bye"
    assert len(factory.built) == 1  # provider bound once, reused per line
    assert runner.calls == [{"gguf_path": TIER1_PATH, "gpu_layers": None}]


def test_line_translator_blank_passthrough():
    t = make_translator(runner=FakeRunner(), local=[FakeProvider()])
    line = t.line_translator("es")
    assert line("") == ""
    assert line("   ") == "   "


def test_line_translator_escalates_and_stays_on_next_tier():
    runner = FakeRunner()
    failing = FakeProvider(fail_all=True)
    working = FakeProvider(prefix="T2")
    factory = make_factory([failing, working])
    t = TieredTranslator(runner=runner, settings=SETTINGS, local_provider_factory=factory)
    line = t.line_translator("es")
    assert line("hello") == "T2:hello"  # tier1 failed -> tier2 answered
    assert line("bye") == "T2:bye"  # stays on tier2 (no re-bind)
    assert len(factory.built) == 2
    # the escalation switched the server to the tier2 GGUF with offload
    assert runner.calls[-1] == {"gguf_path": TIER2_PATH, "gpu_layers": TIER2_GPU_LAYERS}


def test_line_translator_raises_when_chain_exhausted():
    t = make_translator(
        runner=FakeRunner(),
        local=[FakeProvider(fail_all=True), FakeProvider(fail_all=True)],
        hosted=[FakeProvider(fail_all=True)],
    )
    line = t.line_translator("es")
    with pytest.raises(TranslationError):
        line("hello")


# --------------------------------------------------------------------------- #
# GGUF resolution from settings
# --------------------------------------------------------------------------- #
def test_tier_gguf_path_from_models_dir_normalizes():
    t = TieredTranslator(settings={"modelsDir": "D:\\models\\"})
    assert t.tier_gguf_path(TIER_LOCAL) == TIER1_PATH
    assert t.tier_gguf_path(TIER_LOCAL_HEAVY) == TIER2_PATH


def test_tier_gguf_path_explicit_overrides_win():
    t = TieredTranslator(
        settings={
            "modelsDir": "D:/models",
            "translateGgufPath": "/x/a.gguf",
            "translateTier2GgufPath": "/x/b.gguf",
        }
    )
    assert t.tier_gguf_path(TIER_LOCAL) == "/x/a.gguf"
    assert t.tier_gguf_path(TIER_LOCAL_HEAVY) == "/x/b.gguf"


def test_tier_gguf_path_none_when_unconfigured():
    t = TieredTranslator(settings={})
    assert t.tier_gguf_path(TIER_LOCAL) is None
    assert t.tier_gguf_path(TIER_HOSTED) is None


def test_get_translator_factory():
    t = get_translator({"modelsDir": "D:/models"}, runner=FakeRunner())
    assert isinstance(t, TieredTranslator)
    assert t.tier_gguf_path(TIER_LOCAL) == TIER1_PATH


# --------------------------------------------------------------------------- #
# integration: the REAL ModelRunner switches models across the fallback chain
# --------------------------------------------------------------------------- #
class SpawnRecorder:
    """An argv-list popen seam (mirrors test_runner's FakePopen)."""

    def __init__(self) -> None:
        self.spawned: list[list[str]] = []
        self.procs: list[Any] = []

    def __call__(self, argv, *args: Any, **kwargs: Any):
        assert isinstance(argv, list)

        class Proc:
            def __init__(self) -> None:
                self.terminated = False

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout=None) -> int:
                return 0

            def kill(self) -> None:
                pass

            def poll(self):
                return None

        proc = Proc()
        self.spawned.append(list(argv))
        self.procs.append(proc)
        return proc


def test_real_runner_model_switch_through_fallback():
    popen = SpawnRecorder()
    runner = ModelRunner(settings={}, popen=popen)
    t = TieredTranslator(
        runner=runner,
        settings=SETTINGS,
        local_provider_factory=make_factory([FakeProvider(fail_all=True), FakeProvider(prefix="T2")]),
    )
    out = t.translate(cues2(), "es")
    assert [c["text"] for c in out] == ["T2:hello there", "T2:good night"]
    # two launches: tier1 GGUF first, then the tier2 GGUF with partial offload
    assert len(popen.spawned) == 2
    assert TIER1_PATH in popen.spawned[0]
    assert TIER2_PATH in popen.spawned[1]
    idx = popen.spawned[1].index("--n-gpu-layers")
    assert popen.spawned[1][idx + 1] == str(TIER2_GPU_LAYERS)
    # the tier1 server was gracefully stopped during the model switch
    assert popen.procs[0].terminated is True
    assert runner.current_model_path == TIER2_PATH


# --------------------------------------------------------------------------- #
# U4 manifest entries (pinned MT GGUFs)
# --------------------------------------------------------------------------- #
def test_mt_assets_registered_with_pinned_urls():
    for name, gguf in ((TIER1_ASSET_NAME, TIER1_GGUF_NAME), (TIER2_ASSET_NAME, TIER2_GGUF_NAME)):
        entry = manifest.get_asset(name)
        assert entry is not None, name
        assert entry.kind == "model"
        assert entry.installer == "download"
        assert entry.url is not None and entry.url.startswith("https://huggingface.co/")
        assert entry.url.endswith(gguf)  # the exact pinned file
        assert entry.dest == f"models/{gguf}"
        assert entry.size_mb > 0


def test_mt_asset_detect_finds_existing_copy(tmp_path):
    gguf = tmp_path / TIER1_GGUF_NAME
    gguf.write_bytes(b"GGUF")
    entry = manifest.get_asset(TIER1_ASSET_NAME)
    assert entry.detect({"modelsDir": str(tmp_path)}) == str(gguf)
    assert entry.detect({"modelsDir": str(tmp_path / "missing")}) is None
    assert entry.detect({}) is None


def test_mt_asset_detect_explicit_path(tmp_path):
    gguf = tmp_path / "anywhere.gguf"
    gguf.write_bytes(b"GGUF")
    entry = manifest.get_asset(TIER2_ASSET_NAME)
    assert entry.detect({"translateTier2GgufPath": str(gguf)}) == str(gguf)
    assert entry.detect({"translateTier2GgufPath": str(tmp_path / "nope.gguf")}) is None


# --------------------------------------------------------------------------- #
# _tier_provider / _local_provider / _hosted_provider — direct branch coverage
# --------------------------------------------------------------------------- #
def test_tier_provider_unknown_tier_raises():
    # An unrecognized tier matches neither hosted nor the two local tiers and
    # raises TierUnavailableError (line 415).
    t = TieredTranslator(runner=FakeRunner(), settings=SETTINGS)
    with pytest.raises(TierUnavailableError):
        t._tier_provider("tier-bogus")


def test_local_provider_raises_when_no_gguf_configured():
    # A runner is present but no GGUF can be resolved (no modelsDir / no override)
    # -> _local_provider raises TierUnavailableError (line 422).
    t = TieredTranslator(runner=FakeRunner(), settings={})  # runner, but no gguf
    with pytest.raises(TierUnavailableError):
        t._local_provider(TIER_LOCAL)


def test_local_provider_builds_real_local_server_provider_without_factory():
    # No local_provider_factory -> _local_provider constructs a real
    # LocalServerProvider pointed at the configured base URL (line 433).
    runner = FakeRunner()
    t = TieredTranslator(
        runner=runner,
        settings={"modelsDir": "D:/models", "localBaseUrl": "http://127.0.0.1:9/v1"},
    )
    provider = t._local_provider(TIER_LOCAL)
    assert isinstance(provider, LocalServerProvider)
    assert provider.base_url == "http://127.0.0.1:9/v1"
    # The runner was asked to serve the tier1 GGUF.
    assert runner.calls[0]["gguf_path"] == TIER1_PATH


def test_hosted_provider_builds_real_cloud_provider_without_factory():
    # No hosted_provider_factory + a cloudApiKey present -> _hosted_provider
    # constructs a real CloudProvider (line 448).
    t = TieredTranslator(
        runner=None,
        settings={"cloudApiKey": "sk-key", "cloudBaseUrl": "https://api.example/v1"},
    )
    provider = t._hosted_provider()
    assert isinstance(provider, CloudProvider)
    assert provider.base_url == "https://api.example/v1"


def test_line_translator_skips_unbindable_tier_then_uses_hosted():
    # tier1/tier2 cannot even materialize a provider (no runner) -> the binding
    # except in line_translator logs + records the failure + continues to the
    # next tier (lines 344-347); tier3 hosted then serves the line.
    hosted = FakeProvider(prefix="CLOUD")
    t = TieredTranslator(
        runner=None,  # both local tiers fail to bind
        settings={},
        hosted_provider_factory=lambda: hosted,
    )
    line = t.line_translator("es")  # tier1-routed lang
    assert line("hello") == "CLOUD:hello"
