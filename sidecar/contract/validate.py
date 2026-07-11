"""Runtime parameter validation against a generated JSON Schema.

This is the reusable half of the contract: the sidecar dispatch layer validates a
request's params against ``PARAMS_SCHEMA[method]`` BEFORE invoking the handler,
replacing the scattered ad-hoc ``_require_str`` / ``_require_number`` checks with
one schema-driven validator. It raises :class:`ContractValidationError` (a plain
exception — the contract package never imports ``media_studio``); the migration's
one-line dispatch adapter maps it to ``RpcError(INVALID_PARAMS)``::

    try:
        validate_params(method, params, PARAMS_SCHEMA.get(method))
    except ContractValidationError as exc:
        raise RpcError(str(exc), ErrorCode.INVALID_PARAMS) from exc

The type checks mirror the current handlers exactly: ``integer``/``number`` reject
``bool`` (``True``/``False`` are ``int`` subclasses but never a valid count or
index — see ``handlers/_shared.py``), and a required string must be present.
"""

from __future__ import annotations

from typing import Any


class ContractValidationError(ValueError):
    """A request's params (or a settings object) violated the generated schema."""


def _type_name(value: Any) -> str:
    return type(value).__name__


def _validate(schema: dict[str, Any], value: Any, path: str) -> None:
    kind = schema.get("type")
    if kind == "object":
        _validate_object(schema, value, path)
    elif kind == "array":
        _validate_array(schema, value, path)
    else:
        _validate_scalar(kind, value, path)


def _validate_scalar(kind: Any, value: Any, path: str) -> None:
    """Type-check a scalar value. ``integer``/``number`` reject ``bool`` (an ``int``
    subclass but never a valid count/index — mirrors ``handlers/_shared.py``)."""
    where = path or "value"
    if kind == "string" and not isinstance(value, str):
        raise ContractValidationError(f"{where} must be a string (got {_type_name(value)})")
    if kind == "boolean" and not isinstance(value, bool):
        raise ContractValidationError(f"{where} must be a boolean (got {_type_name(value)})")
    if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        raise ContractValidationError(f"{where} must be an integer (got {_type_name(value)})")
    if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise ContractValidationError(f"{where} must be a number (got {_type_name(value)})")


def _validate_object(schema: dict[str, Any], value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path or 'params'} must be an object (got {_type_name(value)})")
    properties: dict[str, Any] = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in value:
            raise ContractValidationError(f"{_join(path, key)} is required")
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        child = _join(path, key)
        if key in properties:
            _validate(properties[key], item, child)
        elif extra is False:
            raise ContractValidationError(f"{child} is not an allowed property")
        elif isinstance(extra, dict):
            _validate(extra, item, child)


def _validate_array(schema: dict[str, Any], value: Any, path: str) -> None:
    if not isinstance(value, list):
        raise ContractValidationError(f"{path or 'value'} must be an array (got {_type_name(value)})")
    items = schema.get("items")
    if isinstance(items, dict):
        for i, item in enumerate(value):
            _validate(items, item, f"{path}[{i}]")


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def validate_params(method: str, params: Any, schema: dict[str, Any] | None) -> None:
    """Validate a method's request ``params`` against its schema.

    A ``None`` schema (a no-param method such as ``ping`` / ``settings.get``) is a
    no-op. Raises :class:`ContractValidationError` on the first violation.
    """
    if schema is None:
        return
    _validate(schema, params if params is not None else {}, method)


def validate_settings(obj: Any, schema: dict[str, Any]) -> None:
    """Validate a settings object against the generated ``SETTINGS_SCHEMA``."""
    _validate(schema, obj, "settings")
