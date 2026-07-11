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
    nle.export / package.export / convert / audiomix / silence / tracks.audio).
    A method outside it raises the SAME fail-loud ``RpcError`` posture as
    ``normalize_recipe`` so a save can never persist a step that escapes the
    repurpose surface.
  * **Storage** — :class:`TemplateStore` IS a :class:`recipes.RecipeStore` over
    ``templates.json`` (atomic temp+rename writes); a template is just a richer
    record in the same JSON-list shape.

Pure logic + filesystem only — no heavy-ML / network / provider imports. The
``templates.*`` RPC (``list``/``save``/``delete``/``apply``) and the export-step
fan-out are later WUs; this module is the store + normalize + allowlist only.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from .. import protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import recipes

log = get_logger("media_studio.features.templates")

Template = dict[str, Any]

#: Allowed step-method prefixes/exact-ids — the curated repurpose verb set
#: (DESIGN §5.4 / G-10.6). A ``"name.*"`` entry allows any method under that
#: namespace (``transcribe.start``, ``convert.start`` …); a bare ``"name.id"``
#: entry is an exact match (``phase8.select`` only, never ``phase8.other``).
#: The audio namespaces are the real registered ones — ``audiomix.*`` (merge /
#: normalize), ``silence.*`` (trim) and ``tracks.audio.*`` (list / mux / replace
#: / strip); a bare ``"audio."`` matched no registered method and was dropped.
ALLOWED_METHOD_PREFIXES: frozenset[str] = frozenset(
    {"transcribe.", "subtitles.", "shortmaker.", "convert.", "audiomix.", "silence.", "tracks.audio."}
)
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


# --------------------------------------------------------------------------- #
# pure: bind a template's steps to ONE source video
# --------------------------------------------------------------------------- #
#: The params key naming the source video a step operates on (wire name).
SOURCE_PARAM = "videoId"


def bind_steps_to_source(steps: list[dict[str, Any]], video_id: str) -> list[dict[str, Any]]:
    """Return ``steps`` with each step's params bound to ``video_id``.

    A template is source-agnostic; :meth:`Templates.apply` binds it to ONE source
    by stamping ``params.videoId`` on every step. A step that already names a
    ``videoId`` (e.g. an explicit override in the saved template) is left as-is,
    so the binding never clobbers an intentional value. Pure + total: no I/O, a
    fresh copy of each step + its params (the template record is never mutated).
    """
    bound: list[dict[str, Any]] = []
    for step in steps:
        params = dict(step.get("params") or {})
        params.setdefault(SOURCE_PARAM, video_id)
        bound.append({**step, "params": params})
    return bound


# --------------------------------------------------------------------------- #
# the apply service (CRUD + single-source apply over the recipe runner)
# --------------------------------------------------------------------------- #
class Templates:
    """Owns the ``templates.*`` methods over a :class:`TemplateStore`.

    ``list``/``save``/``delete`` are direct-return CRUD (mirroring
    :class:`recipes.Recipes`). ``apply`` runs a saved template against ONE source:
    it binds the template's steps to the requested ``videoId``
    (:func:`bind_steps_to_source`), fans out the multi-target export step over the
    live :class:`export_presets.ExportPreset` catalog (:func:`expand_export_steps`,
    WU4), then drives the EXISTING :meth:`recipes.Recipes._run_steps` /
    ``_await_subjob`` — NO new runner, NO new sub-job machinery, NO new cancel
    code. ``apply`` is the single-source sugar over the later batch path (one item).

    Seams (all injectable so tests run with fake methods/presets and no media):

      * ``methods_provider`` — the live RPC method registry a step invokes
        (defaults to ``protocol.METHODS``); shared verbatim with the inner
        :class:`recipes.Recipes` so steps resolve against the same registry.
      * ``presets_provider`` — returns the ``{presetId: ExportPreset}`` map the
        export fan-out resolves targets against (defaults to an empty catalog so
        a template with no export targets still runs).
    """

    def __init__(
        self,
        store: TemplateStore,
        *,
        methods_provider: Callable[[], dict[str, Any]] | None = None,
        presets_provider: Callable[[], dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.store = store
        self._presets_provider = presets_provider or (lambda: {})
        # Reuse the proven recipe runner verbatim (step loop, scaled progress,
        # cancel via raise_if_cancelled, sub-job await/unwrap). The Templates
        # service owns NO orchestration logic of its own.
        self._runner = recipes.Recipes(store, methods_provider=methods_provider)

    # -- direct-return CRUD -------------------------------------------------
    def list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``templates.list()`` -> ``{templates:[Template]}`` (direct-return)."""
        return {"templates": self.store.list()}

    def save(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``templates.save({template})`` -> ``{template}`` (direct-return; upsert).

        The template is normalized (recipe core + additive fields + method
        allowlist) before any write, so a bad save can never persist.
        """
        raw = params.get("template")
        if not isinstance(raw, dict):
            raise _invalid("template (object) is required")
        template = normalize_template(raw)
        return {"template": self.store.save(template)}

    def delete(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``templates.delete({id})`` -> ``{ok}`` (direct-return)."""
        template_id = params.get("id")
        if not isinstance(template_id, str) or not template_id:
            raise _invalid("id (str) is required")
        return {"ok": self.store.delete(template_id)}

    # -- templates.apply (the long job, over the recipe runner) -------------
    def apply(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``templates.apply({templateId, videoId})`` -> ``{jobId}`` (long job).

        Binds the template to ONE source, expands the export fan-out, then runs
        the resulting flat step list through the EXISTING recipe runner. The job's
        progress + sub-job await + cancellation are all the recipe runner's.
        """
        template_id = params.get("templateId")
        if not isinstance(template_id, str) or not template_id:
            raise _invalid("templateId (str) is required")
        video_id = params.get("videoId")
        if not isinstance(video_id, str) or not video_id:
            raise _invalid("videoId (str) is required")
        template = self.store.get(template_id)
        if template is None:
            raise _invalid(f"unknown template: {template_id}")

        # Pure pre-job shaping: bind to the source, then fan the export step out
        # over the live preset catalog. An unknown preset id fails loud HERE
        # (before any job is started), so a bad template never spawns a dead job.
        bound = bind_steps_to_source(list(template.get("steps") or []), video_id)
        steps = expand_export_steps(bound, template.get("defaultControls") or {}, self._presets_provider())

        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)

        def job_body(job_ctx: Any) -> dict[str, Any]:
            return self._runner._run_steps(steps, job_ctx, ctx)

        job = ctx.jobs.start(
            job_body, feature="templates", label=f"template: {template.get('name', '')}", videoId=video_id
        )
        return {"jobId": job.id}


# --------------------------------------------------------------------------- #
# registration (mirrors recipes.register)
# --------------------------------------------------------------------------- #
def register(
    *,
    path: str | os.PathLike[str],
    methods_provider: Callable[[], dict[str, Any]] | None = None,
    presets_provider: Callable[[], dict[str, dict[str, Any]]] | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> Templates:
    """Create a :class:`Templates` over ``path`` and register the four methods.

    ``register_fn`` defaults to :func:`protocol.register`; tests inject a fake
    registrar + a tmp ``path`` + fake method/preset providers. Returns the service
    so the caller can hold it (mirrors :func:`recipes.register`).
    """
    service = Templates(
        TemplateStore(path),
        methods_provider=methods_provider,
        presets_provider=presets_provider,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("templates.list", service.list)
    reg("templates.save", service.save)
    reg("templates.delete", service.delete)
    reg("templates.apply", service.apply)
    return service


__all__ = [
    "ALLOWED_METHOD_EXACT",
    "ALLOWED_METHOD_PREFIXES",
    "EXPORT_METHOD",
    "PRESET_CONTROL_FIELDS",
    "SOURCE_PARAM",
    "Template",
    "TemplateStore",
    "Templates",
    "bind_steps_to_source",
    "expand_export_steps",
    "normalize_template",
    "register",
]
