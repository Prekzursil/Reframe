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
    "Template",
    "TemplateStore",
    "normalize_template",
]
