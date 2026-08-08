"""Cross-language drift gate: the renderer's transition catalogue == the sidecar's.

The transition style vocabulary is hand-mirrored in two places — the sidecar's
``transitions.TRANSITION_STYLES`` (which resolves an id to an ffmpeg ``xfade``
name) and the renderer's ``app/renderer/src/lib/transitions.ts`` (which resolves
the same id to a label the user picks). A drift between them is INVISIBLE at
build time: TypeScript cannot see the Python union, Python cannot see the TS one,
and the first symptom is a user picking a style that makes the render fail with
``unknown transition style`` — or, worse, a style the sidecar supports never
appearing in the picker at all.

This test is the mechanical check that closes that hole. It parses the TS source
(no node, no build step — the file is the artifact) and asserts BOTH the union
type and the rendered catalogue match ``STYLE_IDS`` exactly, ORDER INCLUDED.

FAIL CLOSED (ci-hygiene R1): a missing/unparseable TS file FAILS. A parity gate
that silently skips when it cannot find its input is indistinguishable from no
gate, and this one has to survive exactly the event it exists for — a file move.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from media_studio.features.transitions import STYLE_IDS

#: sidecar/tests/<this file> -> sidecar/tests -> sidecar -> <repo root>.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_PATH = _REPO_ROOT / "app" / "renderer" / "src" / "lib" / "transitions.ts"

#: The union arm text between the alias head and its terminating semicolon.
_UNION_RE = re.compile(r"export type TransitionStyleId =(.*?);", re.DOTALL)
#: The array literal between the catalogue head and its terminating `];`.
_CATALOGUE_RE = re.compile(r"export const TRANSITION_STYLES[^=]*=\s*\[(.*?)\n\];", re.DOTALL)
#: One quoted identifier (union arms and `id:` values are both single-quoted).
_QUOTED_RE = re.compile(r"'([A-Za-z][A-Za-z0-9]*)'")


def _ts_source() -> str:
    """Read the renderer transition module, FAILING (never skipping) if absent."""
    if not _TS_PATH.is_file():
        pytest.fail(
            f"renderer transition catalogue not found at {_TS_PATH} — "
            "if it moved, update this parity gate rather than deleting it"
        )
    return _TS_PATH.read_text(encoding="utf-8")


def _extract(pattern: re.Pattern[str], source: str, what: str) -> tuple[str, ...]:
    """Pull the quoted ids out of the one region ``pattern`` selects."""
    match = pattern.search(source)
    if match is None:
        pytest.fail(f"could not locate the {what} in {_TS_PATH.name} — the parity gate needs updating")
    return tuple(_QUOTED_RE.findall(match.group(1)))


def test_ts_union_matches_the_sidecar_style_ids() -> None:
    ids = _extract(_UNION_RE, _ts_source(), "TransitionStyleId union")
    assert ids == STYLE_IDS


def test_ts_catalogue_matches_the_sidecar_style_ids() -> None:
    # The CATALOGUE (what the picker actually renders) is checked separately from
    # the union: a style could be in the type and missing from the list, which
    # type-checks fine and silently hides the option from the user.
    ids = _extract(_CATALOGUE_RE, _ts_source(), "TRANSITION_STYLES catalogue")
    assert ids == STYLE_IDS


def test_the_parity_detector_can_actually_fail() -> None:
    # BOTH-STATES: prove the extractor discriminates before trusting its silence.
    # A gate that reports parity against text it cannot parse measures nothing.
    broken = "export type TransitionStyleId =\n  | 'dissolve'\n  | 'starWipe';\n"
    assert _extract(_UNION_RE, broken, "union") != STYLE_IDS
    assert _extract(_UNION_RE, broken, "union") == ("dissolve", "starWipe")
