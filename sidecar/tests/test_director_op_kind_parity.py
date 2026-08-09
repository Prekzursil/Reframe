"""Drift gate: the op kinds ADVERTISED == the op kinds that can EXECUTE.

The Director's operation vocabulary was stated in FOUR places that nothing kept
in step:

  * ``models/edit_plan.OpKind``            — 18 kinds (the wire vocabulary)
  * ``edit_plan_prompt.build_system_prompt`` — string-built from ALL 18
  * ``director_op_engines.build_engines``  — a hand-written table of 15
  * ``app/renderer/src/lib/directorTypes`` — a label per kind, all 18 first-class

So the planner was TOLD it could emit ``stitchPanorama`` / ``regenScroll`` /
``ocrExtractList`` and the apply engine could not run any of them. Measured on
the pre-fix tree (``apply_plan`` over ``[trim, ocrExtractList]`` with a stub
runner): the trim reported ``applied``, the OCR op reported
``failed: no engine for kind 'ocrExtractList'``, and — because ``apply_plan`` is
stop-on-first-failure WITH auto-rollback (``apply_engine.py:126-130``) — the COPY
manifest was restored to the original source. The user loses the whole plan, not
just the impossible step. A typed, loud refusal; not a crash, not a silent skip.

The fix makes ONE list authoritative (``edit_plan.DEFERRED_OP_KINDS`` ->
``EXECUTABLE_OP_KINDS``) and derives the other three from it. This file is the
durable half: it fails if a 19th kind is added to one side only.

FAIL CLOSED (ci-hygiene R1): a missing/unparseable renderer file FAILS the test,
never skips — a parity gate that goes quiet when it cannot find its input is
indistinguishable from no gate, and this one must survive a file move, which is
exactly the event that would silently disarm it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from media_studio.features import director_op_engines as engines_mod
from media_studio.features.edit_plan_prompt import advertised_op_kinds, build_system_prompt
from media_studio.models.edit_plan import DEFERRED_OP_KINDS, EXECUTABLE_OP_KINDS, OP_KINDS

#: sidecar/tests/<this file> -> sidecar/tests -> sidecar -> <repo root>.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_LIB = _REPO_ROOT / "app" / "renderer" / "src" / "lib"
_SCHEMAS_TS = _TS_LIB / "rpc" / "schemas.ts"
_TYPES_TS = _TS_LIB / "directorTypes.ts"

#: The `DirectorOpKind` union arms, between the alias head and its `;`.
_UNION_RE = re.compile(r"export type DirectorOpKind =(.*?);", re.DOTALL)
#: The `OP_KIND_LABELS` record body, between its `{` and the closing `};`.
_LABELS_RE = re.compile(r"OP_KIND_LABELS[^=]*=\s*\{(.*?)\n\};", re.DOTALL)
#: The renderer's mirror of the deferred tuple, between its `[` and `];`. Anchored
#: on the `export const` so the prose that documents the mirror cannot match first.
_DEFERRED_RE = re.compile(r"export const DEFERRED_OP_KINDS[^=]*=\s*\[(.*?)\];", re.DOTALL)
#: One single-quoted identifier (union arms and label keys/values both use them).
_QUOTED_RE = re.compile(r"'([A-Za-z][A-Za-z0-9]*)'")
#: A record key at the start of a line (`  trim: 'trim',`) — the LABEL keys.
_KEY_RE = re.compile(r"^\s{2}([A-Za-z][A-Za-z0-9]*):", re.MULTILINE)


def _ts_source(path: Path) -> str:
    """Read a renderer module, FAILING (never skipping) when it is absent."""
    if not path.is_file():
        pytest.fail(
            f"renderer module not found at {path} — if it moved, update this parity gate rather than deleting it"
        )
    return path.read_text(encoding="utf-8")


def _extract(
    pattern: re.Pattern[str], source: str, what: str, *, inner: re.Pattern[str] = _QUOTED_RE
) -> tuple[str, ...]:
    """Pull the identifiers out of the single region ``pattern`` selects."""
    match = pattern.search(source)
    if match is None:
        pytest.fail(f"could not locate the {what} — the parity gate needs updating")
    return tuple(inner.findall(match.group(1)))


class _StubRunner:
    """A runner that is never called — ``build_engines`` only closes over it."""

    def __call__(self, argv: Any, total_sec: float = 0.0, **_k: Any) -> int:  # pragma: no cover - never invoked
        raise AssertionError("the parity gate must not render anything")


# --------------------------------------------------------------------------- #
# The sidecar side: one list, three derivations
# --------------------------------------------------------------------------- #
def test_executable_and_deferred_partition_the_toolbox() -> None:
    # Every kind is exactly one of executable / deferred, and toolbox order is kept
    # (the prompt reads as the DESIGN §2.2 toolbox, not an arbitrary shuffle).
    assert (set(EXECUTABLE_OP_KINDS) | set(DEFERRED_OP_KINDS)) == set(OP_KINDS)
    assert not (set(EXECUTABLE_OP_KINDS) & set(DEFERRED_OP_KINDS))
    assert tuple(k for k in OP_KINDS if k not in DEFERRED_OP_KINDS) == EXECUTABLE_OP_KINDS


def test_engine_module_derives_its_tuples_from_the_model() -> None:
    # The engines module must not hand-maintain a second copy of either list.
    assert engines_mod.WIRED_KINDS == EXECUTABLE_OP_KINDS
    assert engines_mod.DEFERRED_KINDS == DEFERRED_OP_KINDS


def test_the_engine_table_covers_exactly_the_executable_kinds() -> None:
    # THE 19th-op guard on the Python side. Add a kind to `OpKind` and neither
    # wire an engine nor list it as deferred, and this goes red immediately.
    assert set(engines_mod.build_engines(runner=_StubRunner())) == set(EXECUTABLE_OP_KINDS)


def test_the_prompt_advertises_exactly_the_executable_kinds() -> None:
    assert advertised_op_kinds() == EXECUTABLE_OP_KINDS
    assert tuple(_kinds_from_prompt()) == EXECUTABLE_OP_KINDS


def _kinds_from_prompt() -> list[str]:
    """The comma-list the system prompt hands the model, parsed back out."""
    match = re.search(r"ONLY these kinds: (.*?)\.", build_system_prompt())
    assert match is not None, "the system prompt no longer states its op vocabulary"
    return [k.strip() for k in match.group(1).split(",")]


def test_the_prompt_never_names_a_kind_that_cannot_execute() -> None:
    # Substring check as well as the parsed one: none of the three deferred names
    # is a substring of any other kind, so a bare `in` is exact here — and it also
    # catches a deferred kind smuggled in via prose rather than the kinds line.
    prompt = build_system_prompt()
    for kind in DEFERRED_OP_KINDS:
        assert kind not in prompt, f"the planner is still told it may emit {kind!r}, which has no engine"


# --------------------------------------------------------------------------- #
# The renderer side: TypeScript cannot see the Python union, so parse the file
# --------------------------------------------------------------------------- #
def test_ts_union_mirrors_the_whole_toolbox() -> None:
    # The WIRE type keeps all 18: a cached/old plan may still carry a deferred op
    # and must stay parseable. Order included — the union is a mirror, not a set.
    ids = _extract(_UNION_RE, _ts_source(_SCHEMAS_TS), "DirectorOpKind union in schemas.ts")
    assert ids == OP_KINDS


def test_ts_label_table_covers_every_op_kind() -> None:
    # A 19th kind with no label would render as a raw camelCase identifier.
    keys = _extract(_LABELS_RE, _ts_source(_TYPES_TS), "OP_KIND_LABELS record", inner=_KEY_RE)
    assert keys == OP_KINDS


def test_ts_deferred_mirror_matches_the_sidecar() -> None:
    ids = _extract(_DEFERRED_RE, _ts_source(_TYPES_TS), "DEFERRED_OP_KINDS array in directorTypes.ts")
    assert ids == DEFERRED_OP_KINDS


def test_the_ts_detectors_can_actually_fail() -> None:
    # BOTH-STATES: prove each extractor discriminates before trusting its silence.
    # A gate that reports parity against text it cannot parse measures nothing.
    broken_union = "export type DirectorOpKind =\n  | 'trim'\n  | 'teleport';\n"
    assert _extract(_UNION_RE, broken_union, "union") == ("trim", "teleport") != OP_KINDS

    broken_labels = "const OP_KIND_LABELS: X = {\n  trim: 'trim',\n  teleport: 'teleport',\n};\n"
    assert _extract(_LABELS_RE, broken_labels, "labels", inner=_KEY_RE) == ("trim", "teleport") != OP_KINDS

    broken_deferred = "export const DEFERRED_OP_KINDS: readonly X[] = ['teleport'];\n"
    assert _extract(_DEFERRED_RE, broken_deferred, "deferred") == ("teleport",) != DEFERRED_OP_KINDS
