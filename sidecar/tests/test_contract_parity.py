"""Round-trip PARITY tests for the schema-first RPC contract POC (v1.5).

These prove the GENERATED contract agrees with the hand-written reality it will
eventually replace, so the generator can be trusted before any of the 123 methods
is migrated:

  * every POC method the contract declares is a REAL registered method;
  * the generated ``needsKeyInjection`` classification matches ``keyBridge.ts``;
  * the generated param validators accept valid params and reject invalid ones,
    exactly like the current ``_require_str`` / ``_require_number`` handlers;
  * the typed ``Settings`` model agrees with ``DEFAULT_SETTINGS`` and validates a
    real ``settings.get()`` payload, AND newly DECLARES the shortmaker keys that
    were previously only reachable via stringly-typed ``settings.get("...")``;
  * the committed generated artifacts are up to date with the spec (drift gate).

The test lives OUTSIDE ``media_studio`` (the ``--cov=media_studio`` root), imports
the contract as a standalone package, and never mutates on-disk state (a tmp-dir
``Services`` + a collecting registrar, mirroring the composition CE test).
"""

from __future__ import annotations

import pytest
from contract import generate, registry, spec
from contract.validate import ContractValidationError
from media_studio import protocol
from media_studio.handlers import Services, register_all
from media_studio.settings_store import DEFAULT_SETTINGS, SettingsStore

# The 5 representative POC methods (mirrors contract/spec.py METHODS).
POC_METHODS = ("ping", "library.add", "settings.get", "settings.set", "shortmaker.select", "providers.revealKey")

# ---- the CURRENT keyBridge.ts classification, transcribed as an oracle -------
# app/main/keyBridge.ts INJECT_PREFIXES + INJECT_METHODS (kept in sync by hand
# TODAY — the very drift this contract retires). The parity test asserts the
# GENERATED set agrees with this oracle for the POC slice.
_KEYBRIDGE_PREFIXES = ("ai.", "director.", "shortmaker.", "index.")
_KEYBRIDGE_EXACT = frozenset(
    {
        "subtitles.translate",
        "providers.usage",
        "providers.openrouterUsage",
        "providers.revealKey",
        "thumbnail.select",
        "phase8.select",
        "recipes.run",
        "templates.apply",
        "batch.start",
        "batch.resume",
    }
)


def _keybridge_needs_key(method: str) -> bool:
    return method.startswith(_KEYBRIDGE_PREFIXES) or method in _KEYBRIDGE_EXACT


def _live_methods(tmp_path) -> set[str]:
    """Every registered method: feature handlers (collected) + protocol built-ins.

    Registers into a local dict via the ``register=`` seam (composition CE
    pattern) so the global ``protocol.METHODS`` is never mutated; ping/job.* are
    ``@method`` built-ins already present on ``protocol.METHODS``.
    """
    registered: dict[str, object] = {}
    register_all(Services(data_dir=tmp_path), register=lambda name, handler: registered.__setitem__(name, handler))
    return set(registered) | set(protocol.METHODS)


# --------------------------------------------------------------------------- #
# 1. Every POC method the contract declares is a REAL registered method.
# --------------------------------------------------------------------------- #


def test_every_poc_method_is_registered(tmp_path):
    live = _live_methods(tmp_path)
    missing = [m for m in POC_METHODS if m not in live]
    assert not missing, f"contract declares unregistered methods: {missing}"


def test_contract_method_names_match_spec():
    assert set(registry.method_names()) == set(POC_METHODS)
    assert set(spec.method_names()) == set(POC_METHODS)


# --------------------------------------------------------------------------- #
# 2. needsKeyInjection parity with keyBridge.ts (retires finding #5).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", POC_METHODS)
def test_needs_key_matches_keybridge_oracle(method):
    assert registry.needs_key(method) == _keybridge_needs_key(method)


def test_generated_needs_key_set_is_exactly_the_two_key_methods():
    # shortmaker.select (prefix family) + providers.revealKey (exact allowlist).
    assert registry.needs_key_injection() == frozenset({"shortmaker.select", "providers.revealKey"})


# --------------------------------------------------------------------------- #
# 3. Generated param validators mirror the hand-written _require_* checks.
# --------------------------------------------------------------------------- #


def test_library_add_requires_path():
    registry.validate_request("library.add", {"path": "/videos/a.mp4"})  # valid -> no raise
    with pytest.raises(ContractValidationError):
        registry.validate_request("library.add", {})  # missing required path
    with pytest.raises(ContractValidationError):
        registry.validate_request("library.add", {"path": 123})  # wrong type


def test_reveal_key_id_and_index_types():
    registry.validate_request("providers.revealKey", {"id": "openrouter"})  # index optional
    registry.validate_request("providers.revealKey", {"id": "openrouter", "index": 2})
    with pytest.raises(ContractValidationError):
        registry.validate_request("providers.revealKey", {"index": 0})  # missing id
    with pytest.raises(ContractValidationError):
        registry.validate_request("providers.revealKey", {"id": 5})  # id not a string
    with pytest.raises(ContractValidationError):
        # bool is an int subclass but never a valid index (mirrors _shared._require_number).
        registry.validate_request("providers.revealKey", {"id": "x", "index": True})


def test_shortmaker_select_requires_video_id_and_prompt():
    registry.validate_request("shortmaker.select", {"videoId": "v1", "prompt": "best bits", "controls": {}})
    with pytest.raises(ContractValidationError):
        registry.validate_request("shortmaker.select", {"prompt": "p", "controls": {}})  # no videoId


def test_no_param_methods_validate_as_noop():
    # ping / settings.get take no params -> any params are accepted (no schema).
    registry.validate_request("ping", {"unexpected": 1})
    registry.validate_request("settings.get", None)


# --------------------------------------------------------------------------- #
# 4. Typed Settings parity (retires findings #6/#7).
# --------------------------------------------------------------------------- #

# Scalar settings keys with a statically-known default the contract must mirror.
_STATIC_DEFAULT_KEYS = (
    "useCloud",
    "modelsDir",
    "ffmpegPath",
    "confirmCloudBudget",
    "defaultTargetJobSize",
    "monthlySoftLimitCents",
    "monthlyHardLimitCents",
    "enforceMonthlyHardLimit",
    "activePreset",
    "firstRunChoiceMade",
    "lastOpenedVideoId",
    # WU-B1: the lip-sync build flag. Parity is asserted here (the THIRD of the
    # three places a scalar setting must land) so the default cannot drift to
    # ON in one file only — for a face-manipulation gate that drift is the whole
    # risk, not a cosmetic mismatch.
    "lipSyncEnabled",
)

# Keys the contract NEWLY declares — previously reached only via stringly-typed
# settings.get("...") in shortmaker/refine, so a typo silently returned None.
_NEWLY_DECLARED_KEYS = ("silenceTrim", "removeFillers", "hookTitle", "stabilize", "captionSpeakerLabels")

# The two settings keys the contract models as a NESTED BLOCK (``Autosave`` /
# ``ExportDefaults``). Their contract default is ``None`` — meaning "absent", per
# ``Settings``' partial-merge docstring — while ``DEFAULT_SETTINGS`` materialises the
# whole block, so comparing the two scalar-style would compare two deliberately
# different things. Exempt from the default-parity rule below, and the exemption is
# GUARDED: the rule first asserts each of these really is an ``object`` in the schema,
# so the waiver cannot be reused to hide a drifted scalar.
_NESTED_BLOCK_KEYS = ("autosave", "exportDefaults")


@pytest.mark.parametrize("key", _STATIC_DEFAULT_KEYS)
def test_settings_defaults_match_default_settings(key):
    assert registry.settings_defaults()[key] == DEFAULT_SETTINGS[key], f"drift on {key!r} default"


def test_settings_schema_validates_real_get_payload(tmp_path):
    store = SettingsStore(config_path=tmp_path / "settings.json")
    registry.validate_settings_object(store.get())  # a real, backfilled settings.get()
    registry.validate_settings_object(DEFAULT_SETTINGS)  # and the raw defaults


def test_settings_schema_catches_a_wrong_type():
    with pytest.raises(ContractValidationError):
        registry.validate_settings_object({"useCloud": "yes"})  # must be a boolean


def test_newly_declared_keys_are_modeled():
    """W38: the invariant is that the 5 keys ARE declared contract fields.

    This test used to also assert ``key not in DEFAULT_SETTINGS``, which froze a
    TRANSIENT state as an invariant: declaring one of these keys in
    ``DEFAULT_SETTINGS`` is the correct next migration step, and it made the test go
    RED. Measured before removal (five states, `defaultTargetJobSize` and
    `silenceTrim` as the probes): the old assertion fired on a COMPLETE migration —
    both sides landed, nothing drifted — so the suite punished exactly the progress
    the contract exists to enable. The half it was really reaching for (store and
    contract must not disagree) is now enforced, and enforced more widely, by
    ``test_declared_settings_defaults_match_the_store`` below, whose RED conditions
    are pinned by ``test_default_parity_rule_goes_red_on_*``.
    """
    props = registry.settings_schema()["properties"]
    missing = [key for key in _NEWLY_DECLARED_KEYS if key not in props]
    assert not missing, f"these should be declared settings fields: {missing}"


def _default_parity_drift(
    schema: dict[str, object],
    declared_defaults: dict[str, object],
    store_defaults: dict[str, object],
) -> dict[str, tuple[object, object]]:
    """The contract-vs-store default drift over EVERY overlapping settings key.

    Computed, not enumerated: ``_STATIC_DEFAULT_KEYS`` above is a hand-written list of
    12, so a 13th scalar key declared on both sides would have been parity-checked
    nowhere. This walks ``schema.properties ∩ store`` instead, so the checked set
    grows with the tree. ``_STATIC_DEFAULT_KEYS`` is kept as a FLOOR by the caller —
    a computed set that silently shrank to nothing would otherwise pass vacuously.
    """
    props = schema["properties"]
    assert isinstance(props, dict)
    checked = sorted((set(props) & set(store_defaults)) - set(_NESTED_BLOCK_KEYS))
    return {
        key: (declared_defaults.get(key, "<no contract default>"), store_defaults[key])
        for key in checked
        if declared_defaults.get(key) != store_defaults[key]
    }


def test_declared_settings_defaults_match_the_store():
    """Every key both sides declare must agree — including a HALF migration.

    Fires when the store gains a default the contract does not declare (contract
    still says ``None`` = absent) as well as on a plain value drift, and stays green
    when both sides land together.
    """
    schema = registry.settings_schema()
    props = schema["properties"]
    for key in _NESTED_BLOCK_KEYS:
        assert props[key].get("type") == "object", (
            f"{key!r} is exempt from default parity only because it is a nested block; "
            f"it is declared as {props[key].get('type')!r}"
        )
    checked = sorted((set(props) & set(DEFAULT_SETTINGS)) - set(_NESTED_BLOCK_KEYS))
    assert set(_STATIC_DEFAULT_KEYS) <= set(checked), (
        f"the computed parity set lost hand-pinned keys: {sorted(set(_STATIC_DEFAULT_KEYS) - set(checked))}"
    )
    drift = _default_parity_drift(schema, registry.settings_defaults(), dict(DEFAULT_SETTINGS))
    assert not drift, f"settings default drift ({len(checked)} keys checked): {drift}"


def test_default_parity_rule_goes_red_on_a_scalar_drift():
    """Both-states proof: the rule above is not vacuous (mutate the store value)."""
    drift = _default_parity_drift(
        registry.settings_schema(),
        registry.settings_defaults(),
        dict(DEFAULT_SETTINGS) | {"defaultTargetJobSize": DEFAULT_SETTINGS["defaultTargetJobSize"] + 1},
    )
    assert "defaultTargetJobSize" in drift


def test_default_parity_rule_goes_red_on_a_half_migration():
    """A store-only landing of a newly-declared key is caught (contract still None)."""
    drift = _default_parity_drift(
        registry.settings_schema(),
        registry.settings_defaults(),
        dict(DEFAULT_SETTINGS) | {"silenceTrim": True},
    )
    assert drift == {"silenceTrim": (None, True)}


def test_default_parity_rule_stays_green_on_a_full_migration():
    """The forward-progress case the removed assertion punished must PASS.

    Both sides land ``silenceTrim`` together with the same default -> no drift.
    """
    drift = _default_parity_drift(
        registry.settings_schema(),
        dict(registry.settings_defaults()) | {"silenceTrim": True},
        dict(DEFAULT_SETTINGS) | {"silenceTrim": True},
    )
    assert not drift


# --------------------------------------------------------------------------- #
# 5. Drift gate: the committed generated artifacts are current with the spec.
# --------------------------------------------------------------------------- #


def test_generated_artifacts_are_current():
    problems = generate.check()
    assert not problems, "generated artifacts are stale — run `python -m contract.generate`:\n" + "\n".join(problems)


def test_source_hash_is_stamped_into_the_typescript(tmp_path):
    sha = generate.build_contract()["sourceSha256"]
    assert len(sha) == 64
    schemas_ts = (generate._TS_DIR / "schemas.generated.ts").read_text(encoding="utf-8")
    assert f"contract-source-sha256: {sha}" in schemas_ts


def test_drift_gate_is_not_vacuous(tmp_path, monkeypatch):
    # Point the generator at an EMPTY output tree so every artifact is missing:
    # the drift gate MUST flag it (proving test_generated_artifacts_are_current
    # is a real check, not a no-op).
    monkeypatch.setattr(generate, "_JSON_PATH", tmp_path / "contract.schema.json")
    monkeypatch.setattr(generate, "_TS_DIR", tmp_path / "ts")
    problems = generate.check()
    assert problems, "the drift gate should have flagged the missing artifacts"
    assert any("contract.schema.json" in p for p in problems)
