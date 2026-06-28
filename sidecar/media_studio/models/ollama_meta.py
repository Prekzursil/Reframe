"""Ollama metadata-driven model eligibility (V1.1 WU M1b, DESIGN §2.2/§2.3).

Today :mod:`model_recommend` picks an LLM from two *hardcoded* ladders whose
per-rung VRAM/RAM floors are only *guesses* at each model's resident cost. This
module refines that pick **from a runner's real metadata** when Ollama is
present, keeping the static ladder strictly as the no-runner / unknown-model
fallback (DESIGN: "compute fit from it; keep the ladder only as the floor").

It talks to **Ollama's native ``/api/*`` ROOT** (NOT the OpenAI-compatible
``/v1`` surface :mod:`local_detect` probes):

  * ``GET  {root}/api/tags``  — installed models with ``size`` + a content
    ``digest`` (the dedup key) and a ``details`` block (parameter_size /
    quantization_level).[^tags]
  * ``POST {root}/api/show {model}`` — the model's ``capabilities`` array
    (``completion`` / ``vision`` / ``tools`` / ``embedding`` / ``thinking``)
    plus an authoritative ``details`` block.[^show]

From parameter count + quant it computes a resident-VRAM estimate via the field
fit formula (``params_B × bytes_per_param × (1 + overhead) + kv_cache``), gates
each model on the requested **capability**, **dedups by ``digest``** (``/api/tags``
routinely lists one blob under several aliases), and ranks the ones that fit.

PURE + import-light, mirroring :mod:`local_detect`: it imports nothing heavy,
opens no socket and reads no clock. Every HTTP call goes through an injected
**method-aware** :data:`OllamaTransport` (GET for tags, POST for show), so under
test the transport is a fake and **no socket is ever opened**. Detection is
best-effort and **never raises**: any transport/parse failure simply degrades to
the static ladder fallback (a pick always exists).

[^tags]: <https://docs.ollama.com/api/tags>
[^show]: <https://docs.ollama.com/api/show>
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from ..util import get_logger
from .model_recommend import ModelReco, _as_int, recommend_llm

log = get_logger("media_studio.models.ollama_meta")

# --------------------------------------------------------------------------- #
# transport seam + tunables
# --------------------------------------------------------------------------- #
#: A **method-aware** transport: given ``(url, method, body, timeout)`` it performs
#: the HTTP call and returns the decoded JSON dict. ``method`` is ``"GET"`` (for
#: ``/api/tags``; body ignored) or ``"POST"`` (for ``/api/show``; body carries
#: ``{"model": name}``). Injected in tests so no socket is ever opened; the real
#: implementation is a thin method-aware adapter over :mod:`provider`'s stdlib
#: request core (``urllib_get_json`` for GET / ``_urllib_post_json`` for POST),
#: wired in at the handler boundary so this module stays socket-free and pure.
OllamaTransport = Callable[[str, str, dict[str, Any], float], dict[str, Any]]

#: Probe timeout (seconds). ``/api/show`` can be a touch slower than the bare
#: ``/v1/models`` detection probe, so a slightly larger budget than ``local_detect``.
_PROBE_TIMEOUT: float = 5.0

#: VRAM fit formula constants (DESIGN §2.2 / [^vram]). ``bytes_per_param`` =
#: ``quant_bits / 8`` (FP16 = 2 B/param, Q8 ≈ 1, Q4 ≈ 0.5); ``overhead`` ≈
#: 0.15–0.20 (we use the midpoint); plus a flat KV-cache allowance.
_BITS_PER_BYTE: float = 8.0
DEFAULT_OVERHEAD: float = 0.18
DEFAULT_KV_CACHE_GB: float = 0.5
_MB_PER_GB: float = 1024.0

#: The capability moment-selection needs (DESIGN: "don't offer an embedding-only
#: model"). Overridable per call (e.g. ``"tools"`` where the director needs them).
DEFAULT_REQUIRED_CAPABILITY: str = "completion"

#: Known quant-family → bits map. Exact tokens (``F16``) and the leading family
#: token of a compound level (``Q4_K_M`` → ``Q4``) both resolve here; an unknown
#: level yields ``None`` (→ ladder fallback for that model).
_QUANT_BITS: dict[str, float] = {
    "F32": 32.0,
    "FP32": 32.0,
    "F16": 16.0,
    "FP16": 16.0,
    "BF16": 16.0,
    "Q8": 8.0,
    "Q6": 6.0,
    "Q5": 5.0,
    "Q4": 4.0,
    "Q3": 3.0,
    "Q2": 2.0,
}


# --------------------------------------------------------------------------- #
# typed wire shapes
# --------------------------------------------------------------------------- #
class TagRow(TypedDict):
    """One parsed ``/api/tags`` row (the dedup + fit inputs)."""

    name: str
    digest: str
    sizeBytes: int | None
    paramsB: float | None
    quantBits: float | None


class ModelMeta(TypedDict):
    """A deduped, metadata-enriched installed model + its VRAM-fit verdict."""

    model: str
    digest: str
    sizeBytes: int | None
    paramsB: float | None
    quantBits: float | None
    vramEstimateGb: float | None
    capabilities: list[str]
    aliases: list[str]
    fits: bool


class Eligibility(TypedDict):
    """The eligibility result: metadata-ranked models + the ladder ``fallback``.

    ``source`` is ``"metadata"`` when at least one installed model is
    capability-eligible AND fits the device; ``"ladder"`` otherwise (no runner /
    no metadata / nothing fits). ``fallback`` is ALWAYS the device-fit static
    ladder pick, so a usable pick exists regardless of ``source``.
    """

    source: str
    models: list[ModelMeta]
    fallback: ModelReco


# --------------------------------------------------------------------------- #
# native API-root resolution
# --------------------------------------------------------------------------- #
def api_root(base_url: str) -> str:
    """Strip the OpenAI-compat ``/v1`` suffix to reach Ollama's native API root.

    :mod:`local_detect` probes ``http://127.0.0.1:11434/v1``; the native
    ``/api/*`` endpoints live one level up at ``http://127.0.0.1:11434``. A base
    URL without ``/v1`` is returned unchanged (trailing slashes trimmed).
    """
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root.rstrip("/")


# --------------------------------------------------------------------------- #
# pure parsing: parameter size, quant bits, VRAM estimate
# --------------------------------------------------------------------------- #
def parse_params_b(text: Any) -> float | None:
    """``'7.6B'`` → ``7.6``, ``'270M'`` → ``0.27`` (billions of params), else ``None``.

    Returns ``None`` for a non-string, an empty value, an unrecognised unit
    suffix, an unparseable number, or a non-positive count.
    """
    if not isinstance(text, str):
        return None
    token = text.strip().upper()
    if not token:
        return None
    multiplier = {"B": 1.0, "M": 0.001}.get(token[-1])
    if multiplier is None:
        return None
    try:
        value = float(token[:-1])
    except ValueError:
        return None
    if value <= 0:
        return None
    return value * multiplier


def parse_quant_bits(text: Any) -> float | None:
    """``'Q4_K_M'`` → ``4``, ``'F16'`` → ``16``, else ``None`` (unknown family)."""
    if not isinstance(text, str):
        return None
    token = text.strip().upper()
    if not token:
        return None
    if token in _QUANT_BITS:
        return _QUANT_BITS[token]
    return _QUANT_BITS.get(token.split("_", 1)[0])


def estimate_vram_gb(
    params_b: float | None,
    quant_bits: float | None,
    *,
    overhead: float = DEFAULT_OVERHEAD,
    kv_cache_gb: float = DEFAULT_KV_CACHE_GB,
) -> float | None:
    """Resident VRAM (GB) ≈ ``params_B × (bits/8) × (1 + overhead) + kv_cache``.

    Returns ``None`` when either input is unknown (so the model can't be asserted
    to fit and the caller falls back to the static ladder floor).
    """
    if params_b is None or quant_bits is None:
        return None
    bytes_per_param = quant_bits / _BITS_PER_BYTE
    return params_b * bytes_per_param * (1.0 + overhead) + kv_cache_gb


# --------------------------------------------------------------------------- #
# /api/tags — parse + dedup by digest
# --------------------------------------------------------------------------- #
def _parse_tag(entry: Any) -> TagRow | None:
    """Parse one ``/api/tags`` ``models[]`` entry; ``None`` if not a usable row."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name") or entry.get("model")
    if not isinstance(name, str) or not name:
        return None
    digest = entry.get("digest")
    if not isinstance(digest, str) or not digest:
        return None
    raw_details = entry.get("details")
    details = raw_details if isinstance(raw_details, dict) else {}
    return TagRow(
        name=name,
        digest=digest,
        sizeBytes=_as_int(entry.get("size")),
        paramsB=parse_params_b(details.get("parameter_size")),
        quantBits=parse_quant_bits(details.get("quantization_level")),
    )


def list_installed_tags(
    root: str,
    transport: OllamaTransport,
    *,
    timeout: float = _PROBE_TIMEOUT,
) -> list[TagRow]:
    """``GET {root}/api/tags`` → parsed rows; ``[]`` on any failure (never raises)."""
    url = f"{root}/api/tags"
    try:
        response = transport(url, "GET", {}, timeout)
    except Exception as exc:  # noqa: BLE001 - best-effort probe, must not raise
        log.debug("ollama /api/tags probe failed at %s: %s", root, exc)
        return []
    models = response.get("models")
    if not isinstance(models, list):
        return []
    rows: list[TagRow] = []
    for entry in models:
        row = _parse_tag(entry)
        if row is not None:
            rows.append(row)
    return rows


def _more_specific(candidate: str, current: str) -> bool:
    """Whether ``candidate`` is a more specific tag than ``current``.

    More qualifiers ⇒ a longer tag (``qwen2.5:7b-instruct-q4_K_M`` over
    ``qwen2.5:7b``); equal length tie-breaks alphabetically for determinism.
    """
    if len(candidate) != len(current):
        return len(candidate) > len(current)
    return candidate < current


def group_by_digest(rows: list[TagRow]) -> list[tuple[str, list[TagRow]]]:
    """Group rows by content ``digest``, preserving first-seen digest order."""
    groups: dict[str, list[TagRow]] = {}
    order: list[str] = []
    for row in rows:
        digest = row["digest"]
        if digest not in groups:
            groups[digest] = []
            order.append(digest)
        groups[digest].append(row)
    return [(digest, groups[digest]) for digest in order]


def _representative(group: list[TagRow]) -> TagRow:
    """The most specific tag in a same-digest group (the picker shows just this)."""
    best = group[0]
    for row in group[1:]:
        if _more_specific(row["name"], best["name"]):
            best = row
    return best


# --------------------------------------------------------------------------- #
# /api/show — capabilities + authoritative details
# --------------------------------------------------------------------------- #
def show_model(
    root: str,
    name: str,
    transport: OllamaTransport,
    *,
    timeout: float = _PROBE_TIMEOUT,
) -> dict[str, Any]:
    """``POST {root}/api/show {model}`` → response dict; ``{}`` on failure (never raises)."""
    url = f"{root}/api/show"
    try:
        return transport(url, "POST", {"model": name}, timeout)
    except Exception as exc:  # noqa: BLE001 - best-effort probe, must not raise
        log.debug("ollama /api/show probe failed for %s at %s: %s", name, root, exc)
        return {}


def _capabilities(show: dict[str, Any]) -> list[str]:
    """The non-empty string ``capabilities`` from an ``/api/show`` response."""
    caps = show.get("capabilities")
    if not isinstance(caps, list):
        return []
    return [cap for cap in caps if isinstance(cap, str) and cap]


def _show_detail(show: dict[str, Any], key: str) -> Any:
    """Read ``show['details'][key]`` defensively (``None`` if absent/wrong shape)."""
    details = show.get("details")
    if not isinstance(details, dict):
        return None
    return details.get(key)


# --------------------------------------------------------------------------- #
# device fit (reuses the hardware wire dict {vramMb, ramMb, gpuPresent})
# --------------------------------------------------------------------------- #
def _meta_fits(vram_estimate_gb: float | None, hardware: dict[str, Any]) -> bool:
    """Whether the estimated resident VRAM fits the device (GPU VRAM, else RAM).

    An unknown estimate (``None``) is treated as "cannot assert it fits" → the
    model is excluded and the static ladder floor takes over.
    """
    if vram_estimate_gb is None:
        return False
    vram_mb = _as_int(hardware.get("vramMb"))
    ram_mb = _as_int(hardware.get("ramMb"))
    gpu_present = bool(hardware.get("gpuPresent"))
    need_mb = vram_estimate_gb * _MB_PER_GB
    if gpu_present and vram_mb is not None:
        return need_mb <= vram_mb
    if ram_mb is not None:
        return need_mb <= ram_mb
    return False


def _meta_for(
    group: list[TagRow],
    digest: str,
    root: str,
    transport: OllamaTransport,
    hardware: dict[str, Any],
    timeout: float,
) -> ModelMeta:
    """Build one deduped :class:`ModelMeta` from a same-digest group + ``/api/show``."""
    rep = _representative(group)
    aliases = sorted(row["name"] for row in group if row["name"] != rep["name"])
    show = show_model(root, rep["name"], transport, timeout=timeout)
    params_b = parse_params_b(_show_detail(show, "parameter_size")) or rep["paramsB"]
    quant_bits = parse_quant_bits(_show_detail(show, "quantization_level")) or rep["quantBits"]
    vram = estimate_vram_gb(params_b, quant_bits)
    return ModelMeta(
        model=rep["name"],
        digest=digest,
        sizeBytes=rep["sizeBytes"],
        paramsB=params_b,
        quantBits=quant_bits,
        vramEstimateGb=vram,
        capabilities=_capabilities(show),
        aliases=aliases,
        fits=_meta_fits(vram, hardware),
    )


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def eligible_models(
    base_url: str,
    hardware: dict[str, Any],
    transport: OllamaTransport,
    *,
    capability: str = DEFAULT_REQUIRED_CAPABILITY,
    timeout: float = _PROBE_TIMEOUT,
) -> Eligibility:
    """Metadata-driven eligible LLMs for the device, with the static ladder fallback.

    Reads ``/api/tags`` + ``/api/show`` over the injected ``transport``, dedups by
    ``digest``, gates each model on ``capability``, estimates VRAM, keeps the ones
    that fit (best-first by parameter count), and ALWAYS attaches the device-fit
    static ladder pick as ``fallback``. ``source`` is ``"metadata"`` when ≥1 model
    qualifies, else ``"ladder"``. Best-effort: a down runner ⇒ ``source="ladder"``,
    empty ``models``, ladder fallback (never raises).
    """
    root = api_root(base_url)
    fallback = recommend_llm(hardware)
    rows = list_installed_tags(root, transport, timeout=timeout)
    metas = [_meta_for(group, digest, root, transport, hardware, timeout) for digest, group in group_by_digest(rows)]
    eligible = [meta for meta in metas if capability in meta["capabilities"] and meta["fits"]]
    eligible.sort(key=lambda meta: (-(meta["paramsB"] or 0.0), meta["model"]))
    source = "metadata" if eligible else "ladder"
    return Eligibility(source=source, models=eligible, fallback=fallback)


__all__ = [
    "DEFAULT_KV_CACHE_GB",
    "DEFAULT_OVERHEAD",
    "DEFAULT_REQUIRED_CAPABILITY",
    "Eligibility",
    "ModelMeta",
    "OllamaTransport",
    "TagRow",
    "api_root",
    "eligible_models",
    "estimate_vram_gb",
    "group_by_digest",
    "list_installed_tags",
    "parse_params_b",
    "parse_quant_bits",
    "show_model",
]
