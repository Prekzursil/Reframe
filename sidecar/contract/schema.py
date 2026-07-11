"""Stdlib introspection: a :func:`dataclasses.dataclass` -> JSON Schema and -> TS.

The neutral interchange format is JSON Schema (draft-2020-12 subset): the Python
side validates params against it, and the TS emitter renders interfaces from the
same field walk. Supported field types (deliberately the minimal set the contract
uses; anything else raises :class:`UnsupportedType` so an unhandled type fails
LOUDLY at generation time rather than emitting a silent ``any``):

    str · int · float · bool · X | None (optional) · list[X] · dict[str, X] ·
    a nested dataclass.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any

# The JSON-Schema keyword for each scalar Python type.
_SCALAR_JSON: dict[type, str] = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
}

# The TypeScript type for each scalar Python type.
_SCALAR_TS: dict[type, str] = {
    str: "string",
    bool: "boolean",
    int: "number",
    float: "number",
}


class UnsupportedTypeError(TypeError):
    """A field used a type the contract introspector does not model."""


def _is_union(origin: Any) -> bool:
    """True for both ``typing.Union[...]`` and the PEP 604 ``X | Y`` form."""
    return origin is typing.Union or origin is types.UnionType


def optional_inner(annotation: Any) -> Any | None:
    """Return ``X`` when ``annotation`` is ``X | None`` / ``Optional[X]``, else ``None``.

    Only the two-member ``X | None`` shape is modeled (the contract never uses a
    wider union); a wider union raises via the caller's scalar/dataclass walk.
    """
    if not _is_union(typing.get_origin(annotation)):
        return None
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if len(args) == 1 and type(None) in typing.get_args(annotation):
        return args[0]
    return None


def json_schema_for_type(annotation: Any) -> dict[str, Any]:
    """Return the JSON Schema for a single (non-optional) field type."""
    if annotation in _SCALAR_JSON:
        return {"type": _SCALAR_JSON[annotation]}
    origin = typing.get_origin(annotation)
    if origin is list:
        (item,) = typing.get_args(annotation)
        return {"type": "array", "items": json_schema_for_type(item)}
    if origin is dict:
        _key, value = typing.get_args(annotation)
        return {"type": "object", "additionalProperties": json_schema_for_type(value)}
    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        return dataclass_json_schema(annotation)
    raise UnsupportedTypeError(f"cannot map {annotation!r} to JSON Schema")


def _field_is_required(f: dataclasses.Field[Any], annotation: Any) -> bool:
    """A field is required iff it has no default AND its type is not optional."""
    has_default = f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
    return not has_default and optional_inner(annotation) is None


def dataclass_json_schema(cls: type, *, additional_properties: bool = True) -> dict[str, Any]:
    """Return an object JSON Schema for a dataclass (properties + required)."""
    hints = typing.get_type_hints(cls)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for f in dataclasses.fields(cls):
        annotation = hints[f.name]
        inner = optional_inner(annotation)
        properties[f.name] = json_schema_for_type(inner if inner is not None else annotation)
        if _field_is_required(f, annotation):
            required.append(f.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    schema["additionalProperties"] = additional_properties
    return schema


def ts_type_for_type(annotation: Any) -> str:
    """Return the TypeScript type string for a single (non-optional) field type."""
    if annotation in _SCALAR_TS:
        return _SCALAR_TS[annotation]
    origin = typing.get_origin(annotation)
    if origin is list:
        (item,) = typing.get_args(annotation)
        return f"{ts_type_for_type(item)}[]"
    if origin is dict:
        _key, value = typing.get_args(annotation)
        return f"Record<string, {ts_type_for_type(value)}>"
    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        return annotation.__name__
    raise UnsupportedTypeError(f"cannot map {annotation!r} to a TypeScript type")


def dataclass_ts_fields(cls: type) -> list[tuple[str, str, bool]]:
    """Return ``(name, ts_type, optional)`` per field, in declaration order."""
    hints = typing.get_type_hints(cls)
    out: list[tuple[str, str, bool]] = []
    for f in dataclasses.fields(cls):
        annotation = hints[f.name]
        inner = optional_inner(annotation)
        optional = inner is not None
        out.append((f.name, ts_type_for_type(inner if optional else annotation), optional))
    return out


def dataclass_defaults(cls: type) -> dict[str, Any]:
    """Return the statically-known default value per field (skips factory/no-default).

    Nested dataclass defaults are recursed into a plain dict so the value is
    JSON-serialisable for the generated ``SETTINGS_DEFAULTS`` map.
    """
    out: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.default is dataclasses.MISSING:
            continue
        value = f.default
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            value = dataclass_defaults(type(value))
        out[f.name] = value
    return out
