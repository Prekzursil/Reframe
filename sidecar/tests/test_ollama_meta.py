"""Tests for the M1b Ollama metadata-driven eligibility module.

Socket-free + clock-free: every HTTP call goes through an injected **method-aware**
fake transport (GET ``/api/tags`` / POST ``/api/show``), so no socket is ever
opened and the runner need not exist. The tests pin: the native ``/api/*`` ROOT
resolution (NOT ``/v1``), the pure parsers (parameter size / quant bits / VRAM
fit formula), ``/api/tags`` parsing, **dedup by digest** (most-specific tag wins),
``/api/show`` capability extraction, device fit, and the full ``eligible_models``
orchestration with its **static-ladder fallback** (a pick ALWAYS exists, the probe
NEVER raises).
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.models import ollama_meta as om
from media_studio.models.ollama_meta import (
    DEFAULT_KV_CACHE_GB,
    DEFAULT_OVERHEAD,
    TagRow,
    api_root,
    eligible_models,
    estimate_vram_gb,
    group_by_digest,
    list_installed_tags,
    parse_params_b,
    parse_quant_bits,
    show_model,
)


# --------------------------------------------------------------------------- #
# method-aware fake transport (no socket; routes by URL + asserts the verb)
# --------------------------------------------------------------------------- #
class _FakeTransport:
    """Routes ``GET /api/tags`` and ``POST /api/show`` to canned dicts."""

    def __init__(self, *, tags: dict[str, Any] | None = None, shows: dict[str, Any] | None = None) -> None:
        self.tags = tags if tags is not None else {}
        self.shows = shows or {}
        self.calls: list[tuple[str, str, dict[str, Any], float]] = []

    def __call__(self, url: str, method: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append((url, method, body, timeout))
        if url.endswith("/api/tags"):
            assert method == "GET"
            return self.tags
        if url.endswith("/api/show"):
            assert method == "POST"
            return self.shows.get(body["model"], {})
        raise AssertionError(f"unexpected url {url}")  # pragma: no cover - guards the fake


def _boom(url: str, method: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    raise OSError("connection refused")


def _tag(
    name: str, digest: str, *, size: int | None = None, params: str | None = None, quant: str | None = None
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if params is not None:
        details["parameter_size"] = params
    if quant is not None:
        details["quantization_level"] = quant
    row: dict[str, Any] = {"name": name, "digest": digest}
    if size is not None:
        row["size"] = size
    if details:
        row["details"] = details
    return row


# --------------------------------------------------------------------------- #
# api_root — strip the OpenAI-compat /v1 suffix to reach the native API root
# --------------------------------------------------------------------------- #
def test_api_root_strips_v1_suffix() -> None:
    assert api_root("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"


def test_api_root_strips_v1_with_trailing_slash() -> None:
    assert api_root("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434"


def test_api_root_leaves_bare_root_unchanged() -> None:
    assert api_root("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"


# --------------------------------------------------------------------------- #
# parse_params_b — '7.6B' -> 7.6, '270M' -> 0.27 (billions of params)
# --------------------------------------------------------------------------- #
def test_parse_params_b_billions() -> None:
    assert parse_params_b("7.6B") == pytest.approx(7.6)


def test_parse_params_b_millions() -> None:
    assert parse_params_b("270M") == pytest.approx(0.27)


@pytest.mark.parametrize(
    "value",
    [
        123,  # not a string
        "   ",  # empty after strip
        "7X",  # unknown unit suffix
        "abcB",  # unparseable number
        "0B",  # non-positive count
        "-2B",  # negative count
    ],
)
def test_parse_params_b_rejects(value: Any) -> None:
    assert parse_params_b(value) is None


# --------------------------------------------------------------------------- #
# parse_quant_bits — 'Q4_K_M' -> 4, 'F16' -> 16, unknown -> None
# --------------------------------------------------------------------------- #
def test_parse_quant_bits_exact_token() -> None:
    assert parse_quant_bits("F16") == 16.0


def test_parse_quant_bits_compound_family() -> None:
    assert parse_quant_bits("Q4_K_M") == 4.0


@pytest.mark.parametrize("value", [4, "", "ABC", "Q9_X"])
def test_parse_quant_bits_rejects(value: Any) -> None:
    assert parse_quant_bits(value) is None


# --------------------------------------------------------------------------- #
# estimate_vram_gb — params_B × (bits/8) × (1 + overhead) + kv_cache
# --------------------------------------------------------------------------- #
def test_estimate_vram_gb_q4_7b() -> None:
    # 7.0 × 0.5 × 1.18 + 0.5 = 4.13 + 0.5 = 4.63
    assert estimate_vram_gb(7.0, 4.0) == pytest.approx(4.63)


def test_estimate_vram_gb_custom_overhead_and_kv() -> None:
    # 7.0 × 0.5 × 1.2 + 1.0 = 4.2 + 1.0 = 5.2
    assert estimate_vram_gb(7.0, 4.0, overhead=0.2, kv_cache_gb=1.0) == pytest.approx(5.2)


def test_estimate_vram_gb_uses_design_defaults() -> None:
    assert pytest.approx(0.18) == DEFAULT_OVERHEAD
    assert pytest.approx(0.5) == DEFAULT_KV_CACHE_GB


def test_estimate_vram_gb_none_params() -> None:
    assert estimate_vram_gb(None, 4.0) is None


def test_estimate_vram_gb_none_quant() -> None:
    assert estimate_vram_gb(7.0, None) is None


# --------------------------------------------------------------------------- #
# _parse_tag — one /api/tags models[] entry -> TagRow | None
# --------------------------------------------------------------------------- #
def test_parse_tag_full_row() -> None:
    row = om._parse_tag(_tag("qwen2.5:7b", "sha:A", size=4700, params="7.6B", quant="Q4_K_M"))
    assert row == TagRow(name="qwen2.5:7b", digest="sha:A", sizeBytes=4700, paramsB=pytest.approx(7.6), quantBits=4.0)


def test_parse_tag_name_from_model_key() -> None:
    row = om._parse_tag({"model": "llama3.2:3b", "digest": "sha:B"})
    assert row is not None
    assert row["name"] == "llama3.2:3b"


def test_parse_tag_details_not_a_dict_yields_unknown_meta() -> None:
    row = om._parse_tag({"name": "x", "digest": "sha:C", "details": "garbage"})
    assert row is not None
    assert row["paramsB"] is None
    assert row["quantBits"] is None


@pytest.mark.parametrize(
    "entry",
    [
        "not-a-dict",
        {"digest": "sha:D"},  # missing name
        {"name": 123, "digest": "sha:D"},  # name not a string
        {"name": "", "digest": "sha:D"},  # empty name
        {"name": "x"},  # missing digest
        {"name": "x", "digest": 5},  # digest not a string
        {"name": "x", "digest": ""},  # empty digest
    ],
)
def test_parse_tag_rejects(entry: Any) -> None:
    assert om._parse_tag(entry) is None


# --------------------------------------------------------------------------- #
# list_installed_tags — GET /api/tags, never raises
# --------------------------------------------------------------------------- #
def test_list_installed_tags_parses_and_skips_invalid() -> None:
    transport = _FakeTransport(
        tags={"models": [_tag("a", "sha:A", params="3B", quant="Q4_0"), "junk", {"name": "", "digest": "z"}]}
    )
    rows = list_installed_tags("http://h:11434", transport)
    assert [r["name"] for r in rows] == ["a"]


def test_list_installed_tags_transport_failure_degrades_to_empty() -> None:
    assert list_installed_tags("http://h:11434", _boom) == []


@pytest.mark.parametrize("payload", [{}, {"models": "not-a-list"}])
def test_list_installed_tags_bad_payload_is_empty(payload: dict[str, Any]) -> None:
    assert list_installed_tags("http://h:11434", _FakeTransport(tags=payload)) == []


# --------------------------------------------------------------------------- #
# _more_specific / group_by_digest / _representative — dedup machinery
# --------------------------------------------------------------------------- #
def test_more_specific_prefers_longer_tag() -> None:
    assert om._more_specific("qwen2.5:7b-instruct-q4_K_M", "qwen2.5:7b") is True
    assert om._more_specific("qwen2.5:7b", "qwen2.5:7b-instruct-q4_K_M") is False


def test_more_specific_equal_length_tiebreaks_alphabetically() -> None:
    assert om._more_specific("aaa", "bbb") is True
    assert om._more_specific("bbb", "aaa") is False


def test_group_by_digest_groups_and_preserves_first_seen_order() -> None:
    rows = [
        TagRow(name="a", digest="D1", sizeBytes=None, paramsB=None, quantBits=None),
        TagRow(name="b", digest="D2", sizeBytes=None, paramsB=None, quantBits=None),
        TagRow(name="c", digest="D1", sizeBytes=None, paramsB=None, quantBits=None),
    ]
    groups = group_by_digest(rows)
    assert [d for d, _ in groups] == ["D1", "D2"]
    assert [r["name"] for r in groups[0][1]] == ["a", "c"]


def test_representative_picks_most_specific_in_group() -> None:
    group = [
        TagRow(name="qwen2.5:7b", digest="D", sizeBytes=None, paramsB=None, quantBits=None),
        TagRow(name="qwen2.5:7b-instruct-q4_K_M", digest="D", sizeBytes=None, paramsB=None, quantBits=None),
    ]
    assert om._representative(group)["name"] == "qwen2.5:7b-instruct-q4_K_M"


def test_representative_covers_both_continue_arcs_mid_loop() -> None:
    # Four same-digest tags exercise BOTH non-final loop arcs: "bb" updates ``best``
    # then continues, and "x" (less specific) is skipped then continues, before
    # "dddd" finally wins. Pins the most-specific-tag dedup over a noisy group.
    group = [
        TagRow(name="a", digest="D", sizeBytes=None, paramsB=None, quantBits=None),
        TagRow(name="bb", digest="D", sizeBytes=None, paramsB=None, quantBits=None),
        TagRow(name="x", digest="D", sizeBytes=None, paramsB=None, quantBits=None),
        TagRow(name="dddd", digest="D", sizeBytes=None, paramsB=None, quantBits=None),
    ]
    assert om._representative(group)["name"] == "dddd"


def test_representative_single_row_group() -> None:
    group = [TagRow(name="solo", digest="D", sizeBytes=None, paramsB=None, quantBits=None)]
    assert om._representative(group)["name"] == "solo"


# --------------------------------------------------------------------------- #
# show_model + capability / detail extraction
# --------------------------------------------------------------------------- #
def test_show_model_returns_response() -> None:
    transport = _FakeTransport(shows={"m": {"capabilities": ["completion"]}})
    assert show_model("http://h:11434", "m", transport) == {"capabilities": ["completion"]}


def test_show_model_transport_failure_degrades_to_empty() -> None:
    assert show_model("http://h:11434", "m", _boom) == {}


def test_capabilities_filters_non_strings_and_blanks() -> None:
    assert om._capabilities({"capabilities": ["completion", "", 123, "vision"]}) == ["completion", "vision"]


def test_capabilities_missing_or_wrong_shape_is_empty() -> None:
    assert om._capabilities({}) == []
    assert om._capabilities({"capabilities": "tools"}) == []


def test_show_detail_reads_nested_value() -> None:
    assert om._show_detail({"details": {"parameter_size": "7B"}}, "parameter_size") == "7B"


def test_show_detail_missing_key_is_none() -> None:
    assert om._show_detail({"details": {}}, "parameter_size") is None


def test_show_detail_details_not_a_dict_is_none() -> None:
    assert om._show_detail({"details": "garbage"}, "parameter_size") is None


# --------------------------------------------------------------------------- #
# _meta_fits — estimated resident VRAM vs the device (GPU VRAM else RAM)
# --------------------------------------------------------------------------- #
def test_meta_fits_unknown_estimate_excludes() -> None:
    assert om._meta_fits(None, {"vramMb": 8000, "gpuPresent": True}) is False


def test_meta_fits_gpu_vram_fits_and_overflows() -> None:
    hw = {"vramMb": 8000, "gpuPresent": True}
    assert om._meta_fits(4.0, hw) is True  # 4 GB = 4096 MB <= 8000
    assert om._meta_fits(10.0, hw) is False  # 10 GB = 10240 MB > 8000


def test_meta_fits_falls_back_to_ram_when_no_gpu_vram() -> None:
    # gpu_present True but vramMb absent -> not the GPU branch -> RAM branch.
    assert om._meta_fits(4.0, {"gpuPresent": True, "ramMb": 16000}) is True


def test_meta_fits_no_ram_and_no_gpu_is_false() -> None:
    assert om._meta_fits(4.0, {"gpuPresent": False}) is False


# --------------------------------------------------------------------------- #
# eligible_models — full orchestration (metadata source + ladder fallback)
# --------------------------------------------------------------------------- #
def _rich_transport() -> _FakeTransport:
    return _FakeTransport(
        tags={
            "models": [
                _tag("qwen2.5:7b", "DIGEST_A", size=4700, params="7.6B", quant="Q4_K_M"),
                _tag("qwen2.5:7b-instruct-q4_K_M", "DIGEST_A", size=4700, params="7.6B", quant="Q4_K_M"),
                _tag("llama3.2:3b", "DIGEST_B", size=2000, params="3.2B", quant="Q4_0"),
                _tag("nomic-embed", "DIGEST_C", size=300, params="137M", quant="F16"),
                "not-a-dict",  # skipped
            ]
        },
        shows={
            "qwen2.5:7b-instruct-q4_K_M": {
                "capabilities": ["completion", "tools"],
                "details": {"parameter_size": "7.6B", "quantization_level": "Q4_K_M"},
            },
            "llama3.2:3b": {
                "capabilities": ["completion"],
                "details": {"parameter_size": "3.2B", "quantization_level": "Q4_0"},
            },
            # nomic-embed: /api/show carries NO details -> _meta_for falls back to
            # the /api/tags-derived params/quant; capability "embedding" gates it out.
            "nomic-embed": {"capabilities": ["embedding"]},
        },
    )


def test_eligible_models_metadata_dedups_sorts_and_gates_capability() -> None:
    out = eligible_models(
        "http://127.0.0.1:11434/v1",
        {"vramMb": 8000, "gpuPresent": True, "ramMb": 16000},
        _rich_transport(),
    )
    assert out["source"] == "metadata"
    # DIGEST_A collapsed to one row (the most specific tag); embedding-only gated out.
    assert [m["model"] for m in out["models"]] == ["qwen2.5:7b-instruct-q4_K_M", "llama3.2:3b"]
    qwen = out["models"][0]
    assert qwen["digest"] == "DIGEST_A"
    assert qwen["aliases"] == ["qwen2.5:7b"]
    assert qwen["capabilities"] == ["completion", "tools"]
    assert qwen["paramsB"] == pytest.approx(7.6)
    assert qwen["quantBits"] == 4.0
    assert qwen["vramEstimateGb"] == pytest.approx(7.6 * 0.5 * 1.18 + 0.5)
    assert qwen["fits"] is True
    # fallback is ALWAYS the static-ladder pick (a usable pick exists regardless).
    assert out["fallback"]["model"] == "qwen2.5:7b"


def test_eligible_models_meta_for_falls_back_to_tag_params_when_show_lacks_details() -> None:
    # Probe ONLY the embedding model (its /api/show omits details) and accept the
    # "embedding" capability so it survives into ``models`` -> the tag-derived
    # params/quant fallback in _meta_for is observable.
    transport = _FakeTransport(
        tags={"models": [_tag("nomic-embed", "DIGEST_C", size=300, params="137M", quant="F16")]},
        shows={"nomic-embed": {"capabilities": ["embedding"]}},
    )
    out = eligible_models(
        "http://127.0.0.1:11434",
        {"vramMb": 8000, "gpuPresent": True},
        transport,
        capability="embedding",
    )
    assert out["source"] == "metadata"
    only = out["models"][0]
    assert only["paramsB"] == pytest.approx(0.137)
    assert only["quantBits"] == 16.0


def test_eligible_models_capability_miss_degrades_to_ladder() -> None:
    out = eligible_models(
        "http://127.0.0.1:11434/v1",
        {"vramMb": 8000, "gpuPresent": True, "ramMb": 16000},
        _rich_transport(),
        capability="vision",  # no installed model advertises vision
    )
    assert out["source"] == "ladder"
    assert out["models"] == []
    assert out["fallback"]["model"]  # a pick still exists


def test_eligible_models_nothing_fits_degrades_to_ladder() -> None:
    out = eligible_models(
        "http://127.0.0.1:11434/v1",
        {"vramMb": 500, "gpuPresent": True},  # too small for any model
        _rich_transport(),
    )
    assert out["source"] == "ladder"
    assert out["models"] == []


def test_eligible_models_down_runner_degrades_to_ladder_without_raising() -> None:
    out = eligible_models("http://127.0.0.1:11434/v1", {"vramMb": 8000, "gpuPresent": True}, _boom)
    assert out["source"] == "ladder"
    assert out["models"] == []
    assert out["fallback"]["model"]


def test_eligible_models_probes_native_root_not_v1() -> None:
    transport = _rich_transport()
    eligible_models("http://127.0.0.1:11434/v1", {"vramMb": 8000, "gpuPresent": True}, transport)
    urls = {url for url, *_ in transport.calls}
    assert "http://127.0.0.1:11434/api/tags" in urls
    assert "http://127.0.0.1:11434/api/show" in urls
    assert all("/v1/" not in url for url in urls)


# --------------------------------------------------------------------------- #
# eligibility_for_runners (M2) — the overview bridge: probe ONLY when Ollama is
# detected, else skip straight to the static-ladder fallback (a pick always
# exists; the probe never raises)
# --------------------------------------------------------------------------- #
def _ollama_entry(base_url: str = "http://127.0.0.1:11434/v1") -> dict[str, Any]:
    return {"id": "ollama", "kind": "ollama", "base_url": base_url, "model": "qwen2.5:7b"}


def test_ollama_base_url_picks_the_ollama_runner() -> None:
    detected = [
        {"id": "lmstudio", "kind": "lmstudio", "base_url": "http://127.0.0.1:1234/v1"},
        _ollama_entry("http://host:11434/v1"),
    ]
    assert om._ollama_base_url(detected) == "http://host:11434/v1"


def test_ollama_base_url_none_when_no_ollama_runner() -> None:
    detected = [{"id": "lmstudio", "kind": "lmstudio", "base_url": "http://127.0.0.1:1234/v1"}]
    assert om._ollama_base_url(detected) is None


def test_ollama_base_url_skips_ollama_entry_without_a_url() -> None:
    # an ollama entry whose base_url is missing/blank is not usable -> None.
    assert om._ollama_base_url([{"kind": "ollama", "base_url": ""}]) is None
    assert om._ollama_base_url([{"kind": "ollama"}]) is None


def test_ollama_base_url_falls_back_to_id_when_kind_absent() -> None:
    detected = [{"id": "ollama", "base_url": "http://x:11434/v1"}]
    assert om._ollama_base_url(detected) == "http://x:11434/v1"


def test_eligibility_for_runners_no_ollama_returns_ladder_without_probing() -> None:
    # No Ollama detected -> the transport is NEVER called and the static-ladder
    # pick is returned as the fallback (a usable pick always exists).
    out = om.eligibility_for_runners(
        [{"kind": "lmstudio", "base_url": "http://127.0.0.1:1234/v1"}],
        {"vramMb": 8000, "gpuPresent": True},
        _boom,  # would raise if called
    )
    assert out["source"] == "ladder"
    assert out["models"] == []
    assert out["fallback"]["model"]


def test_eligibility_for_runners_metadata_when_ollama_detected() -> None:
    transport = _rich_transport()
    out = om.eligibility_for_runners(
        [_ollama_entry()],
        {"vramMb": 8000, "gpuPresent": True},
        transport,
    )
    assert out["source"] == "metadata"
    assert [m["model"] for m in out["models"]] == ["qwen2.5:7b-instruct-q4_K_M", "llama3.2:3b"]
    top = out["models"][0]
    assert top["quantBits"] == 4
    assert top["vramEstimateGb"] is not None and top["vramEstimateGb"] > 0
    # the native /api root (not /v1) was probed
    assert any(url.endswith("/api/tags") for url, *_ in transport.calls)


def test_eligibility_for_runners_forwards_capability_and_timeout() -> None:
    transport = _rich_transport()
    out = om.eligibility_for_runners(
        [_ollama_entry()],
        {"vramMb": 8000, "gpuPresent": True},
        transport,
        capability="tools",
        timeout=2.0,
    )
    # only the model whose /api/show advertises "tools" survives the gate
    assert [m["model"] for m in out["models"]] == ["qwen2.5:7b-instruct-q4_K_M"]
    assert all(t == 2.0 for *_, t in transport.calls)
