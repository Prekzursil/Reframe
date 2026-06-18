"""Repurpose TEMPLATES (the repurpose bundle's WU3 store).

A *template* is the durable, multi-source generalization of a saved pipeline: a
recipe (the frozen ``recipes`` wire shape — ``{id, name, steps:[Step]}``) PLUS
two additive fields the repurpose flow needs:

  * ``defaultControls`` — a dict of shared knobs (count / captionStyle / window
    …) applied to every export step before the per-preset merge (WU4 fan-out).
  * ``exportTargets`` — a list of :class:`export_presets.ExportPreset` ids the
    template fans out across; ``["tiktok", "shorts"]`` means "make both".

Design (DESIGN §5.4, gate F-template-shape → new module, recommended): this file
REUSES the proven recipe substrate by IMPORT rather than mutating the frozen,
fully-covered ``recipes.*`` wire shape:

  * **Validation** — :func:`normalize_template` calls
    :func:`recipes.normalize_recipe` for the recipe core (name / steps / ids /
    labels), then validates the two additive fields and a **method allowlist**.
    ``recipes.normalize_recipe`` is the ONLY recipe-validation path; there is no
    fork of the wire shape.
  * **Allowlist (G-10.6)** — every step ``method`` must fall inside the curated
    repurpose verb set (transcribe / subtitles / shortmaker / phase8.select /
    nle.export / package.export / convert / audio). A method outside it raises
    the SAME fail-loud ``RpcError`` posture as ``normalize_recipe`` so a save can
    never persist a step that escapes the repurpose surface.
  * **Storage** — :class:`TemplateStore` IS a :class:`recipes.RecipeStore` over
    ``templates.json`` (atomic temp+rename writes); a template is just a richer
    record in the same JSON-list shape.

Pure logic + filesystem only — no heavy-ML / network / provider imports. The
``templates.*`` RPC (``list``/``save``/``delete``/``apply``) and the export-step
fan-out are later WUs; this module is the store + normalize + allowlist only.
"""

from __future__ import annotations

from typing import Any

from ..protocol import ErrorCode, RpcError
from ..util import get_logger
from . import recipes

log = get_logger("media_studio.features.templates")

Template = dict[str, Any]

#: Allowed step-method prefixes/exact-ids — the curated repurpose verb set
#: (DESIGN §5.4 / G-10.6). A ``"name.*"`` entry allows any method under that
#: namespace (``transcribe.start``, ``convert.run`` …); a bare ``"name.id"``
#: entry is an exact match (``phase8.select`` only, never ``phase8.other``).
ALLOWED_METHOD_PREFIXES: frozenset[str] = frozenset({"transcribe.", "subtitles.", "shortmaker.", "convert.", "audio."})
ALLOWED_METHOD_EXACT: frozenset[str] = frozenset({"phase8.select", "nle.export", "package.export"})


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _is_allowed_method(method: str) -> bool:
    """True iff ``method`` is inside the curated repurpose allowlist."""
    if method in ALLOWED_METHOD_EXACT:
        return True
    return any(method.startswith(prefix) for prefix in ALLOWED_METHOD_PREFIXES)


def _normalize_export_targets(raw: Any) -> list[str]:
    """Validate ``exportTargets`` into a list of non-empty preset-id strings."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _invalid("template.exportTargets must be an array of preset ids")
    targets: list[str] = []
    for index, target in enumerate(raw):
        if not isinstance(target, str) or not target.strip():
            raise _invalid(f"template.exportTargets[{index}] (non-empty str) is required")
        targets.append(target.strip())
    return targets


def _normalize_default_controls(raw: Any) -> dict[str, Any]:
    """Validate ``defaultControls`` into a (copied) dict."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _invalid("template.defaultControls must be an object")
    return dict(raw)


#: The method id whose ``exportTargets`` drive the per-preset fan-out (§5.1/§5.3).
EXPORT_METHOD = "shortmaker.export"

#: The :class:`export_presets.ExportPreset` controls fields merged onto a
#: template's ``defaultControls`` for each fanned-out export step. ``id``/``label``
#: are excluded (``id`` becomes ``presetId`` on the params; ``label`` only flavors
#: the step label) — these are exactly the knobs ``shortmaker.export`` consumes
#: (DESIGN §5.3: ``buildExportParams`` → ``ShortMaker.export``).
PRESET_CONTROL_FIELDS: tuple[str, ...] = (
    "aspect",
    "minSec",
    "maxSec",
    "count",
    "captionStyle",
    "reframeEngine",
)


# --------------------------------------------------------------------------- #
# pure: per-preset export-step fan-out (WU4 — no I/O, no provider)
# --------------------------------------------------------------------------- #
def expand_export_steps(
    steps: list[dict[str, Any]],
    controls: dict[str, Any],
    presets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand multi-target ``shortmaker.export`` steps into one step per preset.

    DESIGN §5.1/§5.3: before a template runs, a single ``shortmaker.export`` step
    whose ``params.exportTargets`` names multiple :class:`export_presets.ExportPreset`
    ids is fanned out into one export call per resolved preset. Each fanned step's
    params are the merge ``{**controls, **otherStepParams, **presetControls,
    presetId}`` — the preset's clamped window/style/count/aspect OVERRIDE the
    template's ``defaultControls`` (which override nothing the step itself set
    besides the preset knobs), and the originating ``exportTargets`` control is
    consumed (never forwarded to the export handler).

    Pure + total: no I/O, no provider, no store. ``presets`` is an in-memory
    ``{id: ExportPreset}`` map (the caller supplies it from the catalog). Rules:

      * non-export steps pass through unchanged and in order;
      * an export step with empty / absent ``exportTargets`` passes through
        unchanged (the runner still runs it against ``defaultControls``);
      * a target id absent from ``presets`` raises ``INVALID_PARAMS`` BEFORE any
        output is appended (no partial expansion);
      * the function is idempotent on already-flat step lists (single/no target).

    Each fanned step carries ``params.presetId`` so the Shorts gallery can group
    by platform, and a ``"<label> · <preset label>"`` step label for progress.
    """
    expanded: list[dict[str, Any]] = []
    for step in steps:
        targets = step.get("params", {}).get("exportTargets") if step.get("method") == EXPORT_METHOD else None
        if not isinstance(targets, list) or not targets:
            expanded.append(step)
            continue
        # Resolve every preset FIRST so an unknown id fails loud with no partial
        # expansion of this step.
        resolved = [(target, _resolve_preset(target, presets)) for target in targets]
        base_label = step.get("label", EXPORT_METHOD)
        base_params = {key: value for key, value in step["params"].items() if key != "exportTargets"}
        for target_id, preset in resolved:
            merged = {**controls, **base_params}
            for field in PRESET_CONTROL_FIELDS:
                if field in preset:
                    merged[field] = preset[field]
            merged["presetId"] = target_id
            expanded.append(
                {
                    "method": EXPORT_METHOD,
                    "params": merged,
                    "label": f"{base_label} · {preset.get('label', target_id)}",
                }
            )
    return expanded


def _resolve_preset(target_id: str, presets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    preset = presets.get(target_id)
    if preset is None:
        raise _invalid(f"export target not found in presets: {target_id!r}")
    return preset


# --------------------------------------------------------------------------- #
# pure: template shaping (recipe core via import + additive fields + allowlist)
# --------------------------------------------------------------------------- #
def normalize_template(raw: Any) -> Template:
    """Validate + normalize a template payload into the frozen wire shape.

    ``{id?, name, steps:[Step], defaultControls?, exportTargets?}``. The recipe
    core is validated EXCLUSIVELY by :func:`recipes.normalize_recipe` (no fork of
    the wire shape); this then enforces the method allowlist and the two additive
    fields. Raises ``INVALID_PARAMS`` on any malformed field so a bad save can
    never persist a half-typed or out-of-surface record.
    """
    if not isinstance(raw, dict):
        raise _invalid("template must be an object")

    # Recipe core (name / steps / ids / labels) — the SINGLE validation path.
    recipe = recipes.normalize_recipe(raw)

    for index, step in enumerate(recipe["steps"]):
        method = step["method"]
        if not _is_allowed_method(method):
            raise _invalid(f"template.steps[{index}].method not allowed: {method!r}")

    return {
        **recipe,
        "defaultControls": _normalize_default_controls(raw.get("defaultControls")),
        "exportTargets": _normalize_export_targets(raw.get("exportTargets")),
    }


# --------------------------------------------------------------------------- #
# storage (templates.json under the data root; IS a RecipeStore)
# --------------------------------------------------------------------------- #
class TemplateStore(recipes.RecipeStore):
    """A JSON-backed list of templates (reuses :class:`recipes.RecipeStore`).

    A template is just a richer record in the same atomic JSON-list document, so
    the proven temp+rename store is reused verbatim — only the file name differs
    (``templates.json``). No behavior is overridden.
    """


__all__ = [
    "ALLOWED_METHOD_EXACT",
    "ALLOWED_METHOD_PREFIXES",
    "EXPORT_METHOD",
    "PRESET_CONTROL_FIELDS",
    "Template",
    "TemplateStore",
    "expand_export_steps",
    "normalize_template",
]
