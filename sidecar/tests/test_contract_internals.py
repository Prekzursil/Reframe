"""W37 — unit coverage for `sidecar/contract/`, the tree the coverage SSOT never reached.

`--cov=media_studio` excluded `sidecar/contract/` entirely, so the ~35 KB that GENERATES
the interface contract and the drift gate that guards it were the one tree in the repo
with no coverage floor: the schema introspector, the JSON/TS emitters and the runtime
param validator could all regress silently while the gate stayed green. Measured before
this file: 419 statements, 150 missed, 13 partial branches — 59%.

`test_contract_parity.py` covers the CONTRACT (does the generated artifact agree with
reality). This file covers the MACHINERY (does each emitter/validator branch behave), so
the two do not overlap: parity asserts outputs, these assert paths — including every
`UnsupportedTypeError` and every rejection branch, which no parity test can reach.

Nothing here writes to the real generated tree: every generator test monkeypatches
`_JSON_PATH` / `_TS_DIR` into ``tmp_path`` first (the arrangement
`test_drift_gate_is_not_vacuous` established).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Optional, Union

import pytest
from contract import generate, registry, schema, spec
from contract.validate import (
    ContractValidationError,
    validate_params,
    validate_settings,
)

# --------------------------------------------------------------------------- #
# Fixture dataclasses — deliberately local so the real spec stays untouched.
# --------------------------------------------------------------------------- #


@dataclass
class _Nested:
    flag: bool = True
    depth: int = 2


@dataclass
class _Shapes:
    """One field per supported type, so a single walk exercises every branch."""

    name: str
    count: int
    ratio: float
    on: bool
    tags: list[str]
    lookup: dict[str, int]
    nested: _Nested
    maybe: str | None = None
    listed: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class _FrozenNested:
    """`frozen=True` so an INSTANCE is hashable and may be a dataclass default.

    Python 3.14 rejects a mutable default outright (`ValueError: mutable default ... use
    default_factory`), so the nested-default recursion branch in
    `schema.dataclass_defaults` is only reachable through a frozen nested dataclass. That
    is worth recording: the branch is currently unreachable from `contract.spec` itself —
    `Settings.autosave` defaults to `None`, not to an `Autosave()` — so it is forward-
    looking code, and this is the only thing exercising it.
    """

    flag: bool = True
    depth: int = 2


@dataclass
class _WithNestedDefault:
    block: _FrozenNested = _FrozenNested()  # noqa: RUF009 — the frozen instance default IS the case under test
    bare: str = "x"


@dataclass
class _Unsupported:
    when: tuple[int, ...]


@dataclass
class _WiderUnion:
    either: Union[int, str, None]  # noqa: UP007 — the >2-member union shape is the case under test


# --------------------------------------------------------------------------- #
# schema.optional_inner
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (str, None),
        (list[int], None),
        (str | None, str),
        (Optional[int], int),  # noqa: UP045 — the typing.Optional spelling must behave the same
        (int | str, None),
        (int | str | None, None),
    ],
)
def test_optional_inner(annotation: object, expected: object) -> None:
    assert schema.optional_inner(annotation) is expected


# --------------------------------------------------------------------------- #
# schema: JSON Schema + TS emission for every supported type, and the loud failures
# --------------------------------------------------------------------------- #


def test_json_schema_covers_every_supported_shape() -> None:
    out = schema.dataclass_json_schema(_Shapes)
    props = out["properties"]
    assert out["type"] == "object"
    assert out["additionalProperties"] is True
    assert props["name"] == {"type": "string"}
    assert props["count"] == {"type": "integer"}
    assert props["ratio"] == {"type": "number"}
    assert props["on"] == {"type": "boolean"}
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}
    assert props["lookup"] == {"type": "object", "additionalProperties": {"type": "integer"}}
    assert props["nested"]["properties"]["flag"] == {"type": "boolean"}
    assert props["maybe"] == {"type": "string"}, "an optional field is modeled by its INNER type"


def test_required_is_no_default_and_not_optional() -> None:
    required = schema.dataclass_json_schema(_Shapes)["required"]
    assert required == ["name", "count", "ratio", "on", "tags", "lookup", "nested"]
    assert "maybe" not in required, "X | None is never required"
    assert "listed" not in required, "a default_factory counts as a default"


def test_additional_properties_can_be_closed() -> None:
    assert schema.dataclass_json_schema(_Nested, additional_properties=False)["additionalProperties"] is False


def test_a_schema_with_no_required_fields_omits_the_key() -> None:
    assert "required" not in schema.dataclass_json_schema(_Nested)


def test_ts_types_cover_every_supported_shape() -> None:
    fields_ts = {name: ts for name, ts, _opt in schema.dataclass_ts_fields(_Shapes)}
    assert fields_ts["name"] == "string"
    assert fields_ts["count"] == "number", "int maps to number in TS, not integer"
    assert fields_ts["ratio"] == "number"
    assert fields_ts["on"] == "boolean"
    assert fields_ts["tags"] == "string[]"
    assert fields_ts["lookup"] == "Record<string, number>"
    assert fields_ts["nested"] == "_Nested", "a nested dataclass emits its class name"
    optionals = {name for name, _ts, opt in schema.dataclass_ts_fields(_Shapes) if opt}
    assert optionals == {"maybe"}


def test_an_unmodeled_type_fails_loudly_in_both_emitters() -> None:
    """The whole point of `UnsupportedTypeError`: never a silent `any`."""
    with pytest.raises(schema.UnsupportedTypeError, match="JSON Schema"):
        schema.dataclass_json_schema(_Unsupported)
    with pytest.raises(schema.UnsupportedTypeError, match="TypeScript"):
        schema.dataclass_ts_fields(_Unsupported)


def test_a_wider_union_is_unmodeled_rather_than_guessed() -> None:
    """`optional_inner` returns None for a 3-member union, so the walk must REJECT it."""
    with pytest.raises(schema.UnsupportedTypeError):
        schema.dataclass_json_schema(_WiderUnion)


def test_defaults_skip_missing_and_recurse_into_a_nested_dataclass() -> None:
    assert schema.dataclass_defaults(_Shapes) == {"maybe": None}, "no-default and factory fields are skipped"
    assert schema.dataclass_defaults(_WithNestedDefault) == {
        "block": {"flag": True, "depth": 2},
        "bare": "x",
    }, "a nested dataclass default becomes a JSON-serialisable dict"


# --------------------------------------------------------------------------- #
# validate: every rejection branch (these are the sidecar's INVALID_PARAMS paths)
# --------------------------------------------------------------------------- #

_SCALARS = {
    "type": "object",
    "properties": {
        "s": {"type": "string"},
        "i": {"type": "integer"},
        "n": {"type": "number"},
        "b": {"type": "boolean"},
    },
}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"s": 1}, "must be a string"),
        ({"b": "yes"}, "must be a boolean"),
        ({"i": "1"}, "must be an integer"),
        ({"i": True}, "must be an integer"),
        ({"n": "1.5"}, "must be a number"),
        ({"n": False}, "must be a number"),
    ],
)
def test_scalar_rejections(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        validate_params("m", payload, _SCALARS)


def test_bool_is_never_a_valid_number_or_integer() -> None:
    """`True` is an `int` subclass; the handlers reject it and so must this."""
    validate_params("m", {"i": 3, "n": 1.5}, _SCALARS)  # the accepting direction
    for key in ("i", "n"):
        with pytest.raises(ContractValidationError):
            validate_params("m", {key: True}, _SCALARS)


def test_missing_required_key_is_named() -> None:
    strict = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    with pytest.raises(ContractValidationError, match="m.a is required"):
        validate_params("m", {}, strict)


def test_a_non_object_payload_is_rejected() -> None:
    with pytest.raises(ContractValidationError, match="must be an object"):
        validate_params("m", "nope", {"type": "object", "properties": {}})


def test_none_params_validate_as_an_empty_object() -> None:
    strict = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    with pytest.raises(ContractValidationError, match="is required"):
        validate_params("m", None, strict)


def test_a_none_schema_is_a_no_op() -> None:
    validate_params("ping", {"anything": object()}, None)


def test_closed_additional_properties_rejects_an_extra_key() -> None:
    closed = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    validate_params("m", {"a": "x"}, closed)
    with pytest.raises(ContractValidationError, match="m.z is not an allowed property"):
        validate_params("m", {"z": 1}, closed)


def test_schema_valued_additional_properties_validates_each_extra() -> None:
    typed_map = {"type": "object", "properties": {}, "additionalProperties": {"type": "integer"}}
    validate_params("m", {"anything": 4}, typed_map)
    with pytest.raises(ContractValidationError, match="m.anything must be an integer"):
        validate_params("m", {"anything": "4"}, typed_map)


def test_array_validation_and_per_item_paths() -> None:
    arr = {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "integer"}}}}
    validate_params("m", {"xs": [1, 2]}, arr)
    with pytest.raises(ContractValidationError, match="must be an array"):
        validate_params("m", {"xs": "1,2"}, arr)
    with pytest.raises(ContractValidationError, match=r"m\.xs\[1\] must be an integer"):
        validate_params("m", {"xs": [1, "2"]}, arr)


def test_an_itemless_array_accepts_anything() -> None:
    validate_params("m", {"xs": [1, "two", None]}, {"type": "object", "properties": {"xs": {"type": "array"}}})


def test_a_bare_array_schema_reports_the_root_path() -> None:
    with pytest.raises(ContractValidationError, match="^value must be an array"):
        validate_params("", "nope", {"type": "array", "items": {"type": "integer"}})


def test_an_untyped_schema_accepts_anything() -> None:
    """A property with no `type` is unmodeled, not invalid — the additive-rollout rule."""
    validate_params("m", {"a": object()}, {"type": "object", "properties": {"a": {}}})


def test_validate_settings_prefixes_the_settings_path() -> None:
    with pytest.raises(ContractValidationError, match="^settings must be an object"):
        validate_settings("nope", registry.settings_schema())


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #


def test_params_schema_is_none_for_an_unregistered_method() -> None:
    """The additive-rollout seam: an unmodeled method validates as a no-op."""
    assert registry.params_schema("does.notExist") is None
    assert registry.params_schema("library.add") is not None


def test_spec_param_field_names_is_declaration_order() -> None:
    assert spec.param_field_names(spec.ShortmakerSelectParams) == ("videoId", "prompt", "controls")


# --------------------------------------------------------------------------- #
# generate: the emitters, end to end, into a throwaway tree
# --------------------------------------------------------------------------- #


@pytest.fixture()
def sandbox(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Redirect every artifact path into tmp_path (never touch the real tree)."""
    json_path = tmp_path / "generated" / "contract.schema.json"
    ts_dir = tmp_path / "ts"
    monkeypatch.setattr(generate, "_JSON_PATH", json_path)
    monkeypatch.setattr(generate, "_TS_DIR", ts_dir)
    # `main()` prints each written path RELATIVE to _REPO_ROOT, which raises ValueError
    # on Python 3.14 for a path outside it — so the redirect has to include the root or
    # the CLI path cannot be tested at all.
    monkeypatch.setattr(generate, "_REPO_ROOT", tmp_path)
    return json_path, ts_dir


def test_write_all_emits_all_four_artifacts(sandbox) -> None:
    json_path, ts_dir = sandbox
    written = generate.write_all()
    assert len(written) == 4
    assert json_path.is_file()
    for name in ("schemas.generated.ts", "client.generated.ts", "needsKeyInjection.generated.ts"):
        assert (ts_dir / name).is_file(), name


def test_written_artifacts_carry_the_version_and_the_source_hash(sandbox) -> None:
    """A freshly written tree is self-describing.

    Deliberately NOT "byte-identical to the committed tree" — that claim belongs to
    `test_check_is_clean_on_the_committed_tree`, which compares through the module's own
    real paths. Asserting it here, against a redirected sandbox, would be a sentence
    wider than the evidence.
    """
    json_path, ts_dir = sandbox
    generate.write_all()
    assert json.loads(json_path.read_text(encoding="utf-8"))["version"] == "v1.5-poc"
    assert "contract-source-sha256:" in (ts_dir / "schemas.generated.ts").read_text(encoding="utf-8")


def test_write_all_is_idempotent(sandbox) -> None:
    json_path, ts_dir = sandbox
    generate.write_all()
    first = {p: p.read_text(encoding="utf-8") for p in (json_path, *sorted(ts_dir.iterdir()))}
    generate.write_all()
    second = {p: p.read_text(encoding="utf-8") for p in (json_path, *sorted(ts_dir.iterdir()))}
    assert first == second


def test_emitted_typescript_shape() -> None:
    contract = generate.build_contract()
    schemas_ts = generate.render_schemas_ts(contract)
    client_ts = generate.render_client_ts(contract)
    needskey_ts = generate.render_needskey_ts(contract)

    # every DATA_MODEL becomes an interface, and the MethodName union lists every method
    for model in spec.DATA_MODELS:
        assert f"export interface {model.__name__} {{" in schemas_ts
    for name in spec.method_names():
        assert f"| '{name}'" in schemas_ts
    assert schemas_ts.rstrip().endswith("';"), "the last union member must be terminated"

    # the three Binding shapes
    assert "ping: (): Promise<{ pong: boolean; version: string }> => rpc('ping')," in client_ts
    assert "values: Partial<Settings>" in client_ts, "SPREAD binding passes the object through"
    assert "add: (path: string): Promise<{ video: Video }> => rpc('library.add', { path })," in client_ts
    assert "index = 0" in client_ts, "a defaulted params field becomes a TS default arg"
    # imports are split by source module
    assert "import { rpc } from '../client';" in client_ts
    assert "from './schemas.generated';" in client_ts
    assert "from '../schemas';" in client_ts, "JobHandle/Candidate are still hand-written"
    # grouping: ping is top-level, the rest nest under their first path segment
    assert "  library: {" in client_ts
    assert "} as const;" in client_ts

    for name in spec.needs_key_names():
        assert f"  '{name}',\n" in needskey_ts
    assert "export function needsKeyInjection(method: string): boolean {" in needskey_ts


@pytest.mark.parametrize(
    ("value", "literal"),
    [(True, "true"), (False, "false"), ("s", "'s'"), (None, "undefined"), (0, "0"), (1.5, "1.5")],
)
def test_ts_default_literal(value: object, literal: str) -> None:
    assert generate._ts_default_literal(value) == literal


def test_wrapper_signature_for_each_binding() -> None:
    by_name = {m.name: m for m in spec.METHODS}
    assert generate._wrapper_signature_arrow(by_name["ping"]) == ("", "rpc('ping')")
    assert generate._wrapper_signature_arrow(by_name["settings.set"]) == (
        "values: Partial<Settings>",
        "rpc('settings.set', values)",
    )
    params, body = generate._wrapper_signature_arrow(by_name["providers.revealKey"])
    assert params == "id: string, index = 0"
    assert body == "rpc('providers.revealKey', { id, index })"


def test_spread_binding_without_params_falls_back_to_unknown() -> None:
    """Defensive branch: a SPREAD method must still emit valid TS if params is None."""
    bare = dataclasses.replace(next(m for m in spec.METHODS if m.name == "settings.set"), params=None)
    assert generate._wrapper_signature_arrow(bare) == ("values: Partial<unknown>", "rpc('settings.set', values)")


def test_client_ts_omits_the_hand_written_import_when_nothing_needs_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `if hand:` branch: with no `../schemas` type referenced, no such import line.

    Today `shortmaker.select` pulls JobHandle/Candidate from the hand-written module, so
    the false branch is only reachable once every result type is generated — i.e. at the
    END of the migration. Asserting it now means the emitter is already correct then.
    """
    monkeypatch.setattr(
        spec, "METHODS", tuple(m for m in spec.METHODS if not any(mod == "../schemas" for _n, mod in m.result_imports))
    )
    client_ts = generate.render_client_ts(generate.build_contract())
    assert "from './schemas.generated';" in client_ts
    assert "from '../schemas';" not in client_ts


def test_named_arg_specs_reports_defaults() -> None:
    assert generate._named_arg_specs(spec.RevealKeyParams) == [
        ("id", "string", False, dataclasses.MISSING),
        ("index", "number", True, 0),
    ]


def test_the_source_hash_excludes_itself_and_changes_with_the_body() -> None:
    contract = generate.build_contract()
    assert contract["sourceSha256"] == generate._hash_contract(contract)
    assert generate._hash_contract({**contract, "methodNames": []}) != contract["sourceSha256"]


def test_render_json_is_sorted_with_a_trailing_newline() -> None:
    text = generate.render_json(generate.build_contract())
    assert text.endswith("\n")
    assert list(json.loads(text)) == sorted(json.loads(text))


def test_check_is_clean_on_the_committed_tree() -> None:
    assert generate.check() == []


def test_check_flags_a_stale_typescript_source_hash(sandbox) -> None:
    """The TS half of the drift gate: a wrong embedded hash must be caught."""
    _json_path, ts_dir = sandbox
    generate.write_all()
    target = ts_dir / "client.generated.ts"
    target.write_text(target.read_text(encoding="utf-8").replace("contract-source-sha256: ", "x: "), encoding="utf-8")
    problems = generate.check()
    assert any("client.generated.ts" in p for p in problems)
    assert not any("schemas.generated.ts" in p for p in problems), "only the tampered file is flagged"


def test_check_tolerates_crlf_in_the_json_artifact(sandbox) -> None:
    """`_read` normalises line endings, so a Windows checkout is not false drift."""
    json_path, _ts_dir = sandbox
    generate.write_all()
    json_path.write_bytes(json_path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    assert generate.check() == []


def test_main_check_reports_ok_on_the_committed_tree(capsys) -> None:
    assert generate.main(["--check"]) == 0
    assert "artifacts current" in capsys.readouterr().out


def test_main_check_reports_drift_and_exits_1(sandbox, capsys) -> None:
    assert generate.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "DRIFT" in out
    assert "contract.schema.json" in out


def test_main_writes_and_lists_the_artifacts(sandbox, capsys) -> None:
    json_path, _ts_dir = sandbox
    assert generate.main([]) == 0
    assert "wrote 4 artifacts" in capsys.readouterr().out
    assert json_path.is_file()


def test_main_defaults_to_sys_argv(sandbox, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """`argv=None` reads `sys.argv[1:]` — the real CLI path."""
    monkeypatch.setattr("sys.argv", ["contract.generate", "--check"])
    assert generate.main() == 1
    assert "DRIFT" in capsys.readouterr().out
