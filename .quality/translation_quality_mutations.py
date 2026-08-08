"""Both-states proof for the v1.5 translation-quality fixes.

A test's silence is only evidence once the test has been shown to FIRE on the
known-broken state (`rules/common/single-signal-verification.md` §3b — a probe that is
quiet in both states measures nothing). The translation fixes are exactly the kind that
can rot into a no-op without any suite going red: sentence GROUPING can collapse back to
one-cue-per-call, the language GATE can be reverted, and re-segmentation can start
drifting a timing — each of which still leaves a translated track that looks fine.

So this reverts each fix in turn (one exact, unique string patch), requires the named
tests to go RED, and restores the file byte-for-byte. It also asserts the baseline is
GREEN before each mutation, because a RED after a mutation proves nothing if the test
was already failing (the detector-control half of §3 rule 3).

BY HAND, NOT A GATE. It mutates tracked source, so it must never run in CI — the same
contract as `.quality/docs_check_mutations.py`, which is this file's precedent. Run it
after touching `models/translation.py`, `features/caption_polish.py`, or the
`generate_polished` language wiring:

    sidecar/.venv/Scripts/python .quality/translation_quality_mutations.py

Exit 0 when every mutation was caught; 1 when any survived (or an anchor moved, which
fails CLOSED — a stale anchor means the proof is no longer testing what it names).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _find_root() -> Path:
    """Anchor on markers that exist only at the repo root (see `docs_check.py`)."""
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise SystemExit(f"FAILED:mtproof cannot locate the repo root from {here}")


ROOT = _find_root()
SIDECAR = ROOT / "sidecar"
POLISH = SIDECAR / "media_studio/features/caption_polish.py"
TRANSLATION = SIDECAR / "media_studio/models/translation.py"
SUBTITLES = SIDECAR / "media_studio/features/subtitles.py"

# (label, file, find, replace, the tests that MUST go red)
MUTATIONS: list[tuple[str, Path, str, str, list[str]]] = [
    (
        "M1 timing-drift: re-segmentation shifts a cue start",
        POLISH,
        'return [{**cue, "text": piece} for cue, piece in zip(source, pieces, strict=True)]',
        'return [{**cue, "text": piece, "start": float(cue.get("start", 0.0)) + 0.01}'
        " for cue, piece in zip(source, pieces, strict=True)]",
        [
            "tests/test_translation.py::test_grouped_translation_preserves_every_cue_timing_exactly",
            "tests/test_caption_polish.py::TestRedistributeCueText::test_timings_and_indices_are_byte_identical",
        ],
    ),
    (
        "M2 revert the language gate: the EN-only punct model runs on every language",
        POLISH,
        "    punct = punct_backend\n    if punct is not None and not _is_english(resolved_language):",
        "    punct = punct_backend\n    if False and punct is not None and not _is_english(resolved_language):",
        ["tests/test_caption_polish.py::TestPunctLanguageGate"],
    ),
    (
        "M3 revert sentence grouping: one group per cue (the audit's §3.1 defect)",
        TRANSLATION,
        "    groups = group_cues_for_translation(cues)",
        "    groups = [[c] for c in cues]",
        [
            "tests/test_translation.py::test_sentence_fragments_translate_in_one_context_bearing_call",
            "tests/test_translation.py::test_polished_hard_wraps_are_flattened_before_the_model_sees_them",
        ],
    ),
    (
        "M4 drop the neighbouring-sentence context",
        TRANSLATION,
        "                    context_before=texts[position - 1] if position else None,\n"
        "                    context_after=texts[position + 1] if position + 1 < len(groups) else None,",
        "                    context_before=None,\n                    context_after=None,",
        ["tests/test_translation.py::test_neighbouring_sentences_are_supplied_as_context"],
    ),
    (
        "M5 lossy redistribution: the last piece silently drops its tail word",
        POLISH,
        '    pieces.append(" ".join(words[cursor:]))\n    return pieces',
        '    pieces.append(" ".join(words[cursor:-1] or words[cursor:]))\n    return pieces',
        [
            "tests/test_translation.py::test_redistribution_loses_no_characters_of_the_translation",
            "tests/test_caption_polish.py::TestSplitTextProportional::test_losslessness_over_every_split",
        ],
    ),
    (
        "M6 stop flattening the hard line breaks wrap_two_lines inserted",
        TRANSLATION,
        '    return " ".join(str(cue.get("text", "") or "").split())',
        '    return str(cue.get("text", "") or "").strip()',
        ["tests/test_translation.py::test_polished_hard_wraps_are_flattened_before_the_model_sees_them"],
    ),
    (
        "M7 uncap route_pair: a low-resource SOURCE can force the HOSTED tier",
        TRANSLATION,
        "        return TIER_LOCAL_HEAVY\n    return target_tier",
        "        return source_tier\n    return target_tier",
        ["tests/test_translation.py::TestRoutePair"],
    ),
    (
        "M8 drop the track-language wiring: the language gate goes cosmetic",
        SUBTITLES,
        '        language=str(base.get("lang") or ""),',
        "        language=None,",
        ["tests/test_subtitles.py::test_generate_polished_threads_cues_through_injected_polisher"],
    ),
]


def read_exact(path: Path) -> str:
    """Read ``path`` WITHOUT newline translation.

    ``newline=""`` matters twice over: the working tree is CRLF while the stored blob is
    LF (`rules/common/windows-shell.md` §8b), so translating on read and writing back
    would silently rewrite every line ending in a tracked file; and a pattern written
    with ``\\n`` would then match zero times against the untranslated text. ``Path.read_text``
    only grew a ``newline`` argument in 3.13, so go through ``open`` for 3.12 parity.
    """
    with open(path, encoding="utf-8", newline="") as handle:  # noqa: PTH123 - see the docstring
        return handle.read()


def write_exact(path: Path, text: str) -> None:
    """Write ``text`` byte-for-byte (no newline translation) — see :func:`read_exact`."""
    with open(path, "w", encoding="utf-8", newline="") as handle:  # noqa: PTH123 - see read_exact
        handle.write(text)


def run(tests: list[str]) -> int:
    """Run ``tests`` from the sidecar with the sidecar on ``PYTHONPATH``."""
    env = dict(os.environ, PYTHONPATH=str(SIDECAR))
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, repo-local paths
        [sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:randomly", "--no-header", "-x"],
        cwd=SIDECAR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def main() -> int:
    survivors: list[str] = []
    for label, path, find, replace, tests in MUTATIONS:
        original = read_exact(path)
        if original.count(find) != 1:
            print(f"FAILED:mtproof anchor is missing or not unique ({original.count(find)}x) for {label}")
            return 1
        if run(tests) != 0:
            print(f"FAILED:mtproof baseline is not green for {label} — fix the suite before trusting this proof")
            return 1
        write_exact(path, original.replace(find, replace))
        try:
            code = run(tests)
        finally:
            write_exact(path, original)
        print(f"{'CAUGHT' if code != 0 else 'SURVIVED':9s} {label}")
        if code == 0:
            survivors.append(label)
    if survivors:
        print(f"FAILED:mtproof {len(survivors)} surviving mutant(s): {'; '.join(survivors)}")
        return 1
    print(f"SUCCESS:mtproof {len(MUTATIONS)}/{len(MUTATIONS)} mutations caught")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
