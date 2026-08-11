"""Round-trip PARITY tests for the schema-first RPC contract POC (v1.5).

These prove the GENERATED contract agrees with the hand-written reality it will
eventually replace, so the generator can be trusted before any of the remaining
methods is migrated (the live surface is sized in `docs/rpc-contract-v2.md` §1;
this docstring deliberately states no count, because the literal it used to carry
is exactly the one that rotted):

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

import re
from pathlib import Path

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
    contract must not disagree) is now enforced by
    ``test_declared_settings_defaults_match_the_store`` below, whose RED conditions
    are pinned by ``test_default_parity_rule_goes_red_on_*``.

    REFUTED wording, kept so it is not re-derived: this used to read "enforced, and
    enforced more widely". Measured against the live registry 2026-08-11 — schema
    properties 20, ``DEFAULT_SETTINGS`` 22, intersection 14, minus the 2 nested-block
    exemptions = **12 keys checked**, and ``set(checked) == set(_STATIC_DEFAULT_KEYS)``
    exactly (symmetric difference empty both ways). The rule's own failure message prints
    ``(12 keys checked)``. So the replacement is not wider TODAY; it is the same 12 keys
    obtained by computation instead of enumeration. The forward-looking claim at
    ``_default_parity_drift`` ("the checked set grows with the tree") is the true one and
    is where the value actually is.
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

    That "grows with the tree" claim is forward-looking and is the whole value here; it
    is NOT a claim that the checked set is wider than the hand list today. Measured
    2026-08-11: schema properties 20 ∩ store 22 = 14, minus the 2 nested-block
    exemptions = 12 checked, which is exactly ``set(_STATIC_DEFAULT_KEYS)``.

    THREE RESIDUALS, measured the same day by calling this function against mutated
    inputs, disclosed here rather than in a footer because each bounds the sentence above.
    Three FOUND by that probe — the list is not a proof that there are only three, and both
    2 and 3 below carry the record of having been stated wider than their evidence on the
    first pass:

    1. It still punishes forward progress, one class narrower than the assertion W38
       removed. A COMPLETE, correct migration of a THIRD nested block — declared
       ``{"type": "object"}`` in the schema, materialised in the store, contract default
       ``None`` = absent — reports drift (measured: ``{'zzNewBlock': (None, {'a': 1})}``)
       and goes RED until ``_NESTED_BLOCK_KEYS`` is hand-edited to add it. Settling change:
       exempt by SCHEMA TYPE (``props[key]["type"] == "object"``) instead of by name, which
       also removes the hand list this drift-check would then be waiting on.
    2. Nested-block CONTENTS are dropped whole by this function — but the exposure is on
       the CONTRACT side, and the first version of this residual had it backwards. REFUTED
       wording AND refuted evidence, both kept rather than deleted: it read "the five
       sub-properties ... carry the same drift exposure the scalars had before W38", and
       offered ``DEFAULT_SETTINGS["autosave"]["debounceMs"] = "not-an-int"`` -> ``{}`` as
       the demonstration. That is the most-caught mutation of the set — measured over the
       whole suite it goes red in THREE places, starting with
       ``test_settings_schema_validates_real_get_payload`` (earlier in this module), which
       calls ``registry.validate_settings_object(DEFAULT_SETTINGS)`` over a schema that
       REJECTS a string there. The residual's own probe demonstrated a hole that does not
       exist.
       Re-measured 2026-08-11 by running the WHOLE sidecar suite once per mutation: the
       STORE side is guarded too. ``autosave.debounceMs`` -> ``999999``, ``autosave.enabled``
       -> ``False`` and ``autosave.debounceMs`` DELETED each fail
       ``test_settings_store.py::test_qol_defaults_present_exact`` +
       ``::test_qol_keys_round_trip``; ``exportDefaults.nleFps`` -> ``0`` fails
       ``::test_qol_defaults_present_exact`` + ``::test_export_defaults_exact_acceptance`` +
       ``::test_autosave_partial_set_round_trips``. Those tests pin both blocks as exact
       dicts. Control: the same suite with no mutation is all-green, so the reds are the
       mutations and not the harness.
       What IS unguarded is CONTRACT-vs-store parity inside a block. ``contract/spec.py``
       declares ``Autosave.debounceMs = 1500`` / ``ExportDefaults.nleFps = 30`` and
       ``media_studio.settings_store`` declares the same numbers again, and nothing compares
       the two copies: the generated schema for a nested block carries sub-property TYPES
       only, with no ``default`` key at all (measured), and
       ``registry.settings_defaults()["autosave"]`` is ``None``. Drifting the CONTRACT copy
       to 2000 leaves this function at ``{}``, the schema byte-identical and
       ``validate_settings_object`` ACCEPTING, and no test reads those dataclass defaults.
       Detector control for that reading: the first attempt patched the class attribute
       only, which a ``@dataclass`` ignores — ``spec.Autosave()`` still read 1500, so that
       run measured nothing and was discarded; the numbers above come from patching
       ``__init__.__defaults__``, asserted to have taken effect before anything was read.
       Settling change: recurse one level into an exempt block and compare the contract
       sub-field defaults against the store's materialised values.
    3. The set is an INTERSECTION, so it drops keys in BOTH directions — 14 of the 28-key
       union, not the 6 first disclosed. REFUTED wording, kept rather than deleted: this
       residual originally read "a contract-only default is invisible ... Six keys are
       schema-only today", which quantified ONE side of an intersection while presenting
       itself as the whole loss. Re-measured 2026-08-11: schema-only = 6
       (``captionSpeakerLabels``, ``captionStyle``, ``hookTitle``, ``removeFillers``,
       ``silenceTrim``, ``stabilize``), all six with contract default ``None`` (measured,
       not assumed) — which is why nothing is wrong on that side right now, and why none of
       them would be caught if that changed. Store-only = 8, MORE than the six disclosed
       (``asrVocabulary``, ``brandCaptionTemplate``, ``brandFontFamily``, ``brandLogoPath``,
       ``consent``, ``providers``, ``routing``, ``savePresets``) — each equally dropped
       (measured: mutating ``asrVocabulary`` to a sentinel returns ``{}``), and unlike the
       schema-only six they are not modelled by the contract at all, so
       ``test_newly_declared_keys_are_modeled`` above polices only the 5 it names by hand.
       Settling change, one change covering both directions: walk the UNION, treat
       "declared non-None contract default, absent from the store" as drift, and treat
       "materialised by the store, declared nowhere in the schema" as unmodelled.

    Detector control for the two ``{}`` readings above: residual 1 shows this same function
    DOES emit drift on mutated input, and ``test_default_parity_rule_goes_red_on_a_scalar_drift``
    pins the scalar direction — so the empty results are real holes, not a dead probe.
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


# --------------------------------------------------------------------------- #
# 6. SIZE anti-drift: the migration docs must state the MEASURED size of the
#    surface, never a hand-copied literal.
#
# Why this test exists. Every "123 methods" in the v2 contract docs — including
# the long-pole `eng-days` estimate that was SIZED from it — was a literal typed
# once and never re-measured, so it decayed silently as methods were added. The
# same defect shape as the tab-strip count in #371: a number asserted in prose
# that no check could see. #371's fix was a test that DERIVES the count from
# source, so that is the fix here too. A method added without touching the docs
# now fails gate:3 instead of quietly widening the drift.
#
# What the FIRST version of this test did NOT do, and now does. It asserted only
# that a canonical PHRASE is PRESENT ("<n> live-registered methods"). Presence is
# not uniqueness: the same two docs carried the live count five and three times
# respectively, so updating the one phrase the assertion names would have gone
# green while four stale siblings survived — reproducing #371's duplicated-literal
# mechanism inside the fix for it. The comment here claimed "one literal per
# quantity" as a fact; that claim was REFUTED by measurement. It is now an
# ENFORCED invariant (`test_docs_carry_exactly_one_literal_per_quantity`) rather
# than an aspiration, and every other mention of a surface size in those two docs
# was rewritten to be qualitative or to delegate.
#
# Cost, stated because it is real and lands on OTHER lanes: registering one new
# method changes `live`, so any branch that adds a `reg(...)`/`@method` must also
# update ONE line in each of the two v2 docs or its own `gate:3` goes red. That is
# the intended trade (a red gate beats silent decay), but it is a coupling this
# test creates, not a free lunch.
# --------------------------------------------------------------------------- #


def _repo_root() -> Path:
    """Anchor on root-only markers.

    NOT `parents[2]`: pytest runs with cwd=`sidecar/` (quality.yml gate:3), and
    `.quality/docs_check.py::_find_root` records what a positional guess cost
    when a file moved — every relative read missed and the detector blamed the
    repo for its own relocation.
    """
    for cand in Path(__file__).resolve().parents:
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise AssertionError(f"cannot locate the repo root from {__file__}")


# ANCHORED on the opening quote of the wire name so only a real dispatch matches:
# a bare `rpc(` substring also appears in `rpcTimeout`/`onProgress(` tails, and the
# orchestrator paid for exactly that class of unanchored probe three times today.
_RPC_CALL_RE = re.compile(r"\brpc(?:<[^>]*>)?\(\s*'([A-Za-z][A-Za-z0-9_.]*)'")

# The SECOND dispatch shape, and the reason this helper is not a one-liner:
# `rpc(BROLL_METHODS.status)` names its method through an `as const` map declared at
# `client.ts:252`, which `client.ts:247` puts forward as the PREFERRED pattern ("a
# call site cannot invent a string"). An inline-literal-only probe is therefore blind
# to exactly the direction the codebase is migrating toward: it reported `134`, seven
# short, and — worse — the seven invisible names were also exempt from the
# `wrappers <= live` dead-wire-name invariant. Resolving the map closes both.
_RPC_CONST_CALL_RE = re.compile(r"\brpc(?:<[^>]*>)?\(\s*([A-Z][A-Z0-9_]*)\.(\w+)")
_CONST_MAP_RE = re.compile(r"\bconst\s+([A-Z][A-Z0-9_]*)\s*=\s*\{(.*?)\}\s*as const", re.S)
_CONST_MAP_ENTRY_RE = re.compile(r"(\w+)\s*:\s*'([A-Za-z][A-Za-z0-9_.]*)'")


def _client_wrapper_methods() -> set[str]:
    """Every wire name `app/renderer/src/lib/rpc/client.ts` calls by hand.

    BOTH dispatch shapes: an inline string literal, and a member of an UPPER_SNAKE
    ``as const`` map. An unresolvable map member is an ERROR, not a silent skip —
    a probe that quietly drops what it cannot parse is how the count drifted.
    """
    text = (_repo_root() / "app/renderer/src/lib/rpc/client.ts").read_text(encoding="utf-8")
    maps = {name: dict(_CONST_MAP_ENTRY_RE.findall(body)) for name, body in _CONST_MAP_RE.findall(text)}
    named = set(_RPC_CALL_RE.findall(text))
    for map_name, key in _RPC_CONST_CALL_RE.findall(text):
        wire = maps.get(map_name, {}).get(key)
        assert wire, f"client.ts dispatches rpc({map_name}.{key}) but no `as const` map declares that key"
        named.add(wire)
    return named


def test_the_count_probes_find_known_present_methods(tmp_path):
    """Detector control. A zero from a broken matcher must not read as a finding.

    Both probes below are asserted to find methods that are known-present, and the
    live registry is asserted to be a SUPERSET of the hand-written client (a wrapper
    for an unregistered method would be a dead wire name — finding #1's failure
    mode). Without this, `test_docs_state_the_measured_surface_size` could pass on
    two matching zeros.
    """
    wrappers = _client_wrapper_methods()
    live = _live_methods(tmp_path)
    assert {"ping", "library.add", "settings.get"} <= wrappers
    assert {"ping", "library.add", "settings.get"} <= live
    # A CONSTANT-MAP dispatch must be visible too. `client.ts` also calls
    # `rpc(BROLL_METHODS.status)`, where the wire name is reached through an
    # `as const` map — and `client.ts:247` actively recommends that pattern ("a call
    # site cannot invent a string"). A literal-only probe reported the whole broll
    # family as absent, under-counting the surface AND silently exempting those names
    # from the `wrappers <= live` dead-wire check below. Three inline names alone
    # cannot catch that, because none of them is constant-referenced.
    assert "broll.status" in wrappers, "the probe is blind to constant-map `rpc(MAP.key)` dispatch"
    assert wrappers <= live, f"client.ts calls unregistered wire names: {sorted(wrappers - live)}"


_V2_DOCS = ("docs/rpc-contract-v2.md", "docs/rpc-contract-v2-migration.md")


def _standalone_number_hits(body: str, value: int) -> int:
    """How many times `value` appears as a whole number (not a digit-slice).

    The lookaround stops `169` matching inside `1169`/`169.5`; it deliberately DOES
    match inside a code span or a table cell, because that is where the stale
    siblings lived.
    """
    return len(re.findall(rf"(?<![\d.]){value}(?![\d])", body))


def test_docs_state_the_measured_surface_size(tmp_path):
    live = len(_live_methods(tmp_path))
    wrappers = len(_client_wrapper_methods())
    root = _repo_root()

    for rel in _V2_DOCS:
        body = (root / rel).read_text(encoding="utf-8")
        assert f"{live} live-registered methods" in body, (
            f"{rel} does not state the measured method count ({live}). "
            "Re-measure and update the doc; do not adjust this test."
        )

    body = (root / "docs/rpc-contract-v2.md").read_text(encoding="utf-8")
    assert f"{wrappers} hand-written `rpc()` wire names" in body, (
        f"docs/rpc-contract-v2.md does not state the measured client.ts wrapper "
        f"count ({wrappers}). Re-measure and update the doc; do not adjust this test."
    )


def test_docs_carry_exactly_one_literal_per_quantity(tmp_path):
    """Presence is not uniqueness — a partial update must NOT be able to pass.

    Measured before this test existed: `169` appeared 5x in the contract doc and 3x
    in the migration plan, and `134` 3x. Updating only the phrase the assertion
    above names left the rest stale WITH A GREEN GATE — the #371 duplicated-literal
    defect, re-created inside the fix for it.
    """
    live = len(_live_methods(tmp_path))
    wrappers = len(_client_wrapper_methods())
    root = _repo_root()

    for rel in _V2_DOCS:
        body = (root / rel).read_text(encoding="utf-8")
        hits = _standalone_number_hits(body, live)
        assert hits == 1, (
            f"{rel} states the live method count ({live}) {hits}x; exactly 1 is allowed. "
            "Keep the canonical sentence and make every other mention qualitative "
            "(or delegate to it). If the number collides with an unrelated figure, "
            "reword that figure — do not relax this assertion."
        )

    body = (root / "docs/rpc-contract-v2.md").read_text(encoding="utf-8")
    hits = _standalone_number_hits(body, wrappers)
    assert hits == 1, (
        f"docs/rpc-contract-v2.md states the client.ts wrapper count ({wrappers}) "
        f"{hits}x; exactly 1 is allowed. See the sibling assertion for why."
    )
