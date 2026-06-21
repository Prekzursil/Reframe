"""Tests for the bilingual stacked-subtitle additions to features/subtitles.py.

Kept in a SEPARATE file from test_subtitles.py (which the foundation unit owns)
so the captions-export additions stay isolated. Covers stack_cue_text ordering
and stack_bilingual cue matching / lang labelling / immutability.
"""

from __future__ import annotations

from media_studio.features import subtitles as subs


def _orig() -> dict:
    return subs.new_track(
        [subs.make_cue(1, 0.0, 2.0, "Hello"), subs.make_cue(2, 2.0, 4.0, "World")],
        lang="en",
        name="EN",
    )


def _trans() -> dict:
    return subs.new_track(
        [subs.make_cue(1, 0.0, 2.0, "Hola"), subs.make_cue(2, 2.0, 4.0, "Mundo")],
        lang="es",
        name="ES",
    )


# --------------------------------------------------------------------------- #
# stack_cue_text
# --------------------------------------------------------------------------- #
def test_stack_cue_text_original_first() -> None:
    assert subs.stack_cue_text("Hello", "Hola") == "Hello\nHola"


def test_stack_cue_text_translation_first() -> None:
    assert subs.stack_cue_text("Hello", "Hola", order="translation-first") == "Hola\nHello"


def test_stack_cue_text_drops_blank_line() -> None:
    assert subs.stack_cue_text("Hello", "") == "Hello"
    assert subs.stack_cue_text("", "Hola") == "Hola"
    assert subs.stack_cue_text("  ", "  ") == ""


# --------------------------------------------------------------------------- #
# stack_bilingual
# --------------------------------------------------------------------------- #
def test_stack_bilingual_stacks_cues_by_index() -> None:
    out = subs.stack_bilingual(_orig(), _trans())
    assert out["lang"] == "en+es"
    assert out["kind"] == "soft"
    assert out["cues"][0]["text"] == "Hello\nHola"
    assert out["cues"][1]["text"] == "World\nMundo"
    # Timing preserved from the original.
    assert out["cues"][0]["start"] == 0.0 and out["cues"][0]["end"] == 2.0


def test_stack_bilingual_translation_first() -> None:
    out = subs.stack_bilingual(_orig(), _trans(), order="translation-first")
    assert out["cues"][0]["text"] == "Hola\nHello"


def test_stack_bilingual_default_name() -> None:
    out = subs.stack_bilingual(_orig(), _trans())
    assert out["name"] == "Bilingual (en/es)"


def test_stack_bilingual_custom_name() -> None:
    out = subs.stack_bilingual(_orig(), _trans(), name="EN + ES")
    assert out["name"] == "EN + ES"


def test_stack_bilingual_positional_fallback_on_index_mismatch() -> None:
    # Translation cues carry non-matching indices -> fall back to positional pairing.
    trans = subs.new_track(
        [subs.make_cue(99, 0.0, 2.0, "Hola"), subs.make_cue(100, 2.0, 4.0, "Mundo")],
        lang="es",
    )
    out = subs.stack_bilingual(_orig(), trans)
    assert out["cues"][0]["text"] == "Hello\nHola"
    assert out["cues"][1]["text"] == "World\nMundo"


def test_stack_bilingual_missing_translation_keeps_original_line() -> None:
    trans = subs.new_track([subs.make_cue(1, 0.0, 2.0, "Hola")], lang="es")  # only 1 cue
    out = subs.stack_bilingual(_orig(), trans)
    assert out["cues"][0]["text"] == "Hello\nHola"
    assert out["cues"][1]["text"] == "World"  # no translation -> original only


def test_stack_bilingual_does_not_mutate_inputs() -> None:
    orig, trans = _orig(), _trans()
    orig_snapshot = [dict(c) for c in orig["cues"]]
    subs.stack_bilingual(orig, trans)
    assert [dict(c) for c in orig["cues"]] == orig_snapshot


def test_stack_bilingual_new_id_each_call() -> None:
    a = subs.stack_bilingual(_orig(), _trans())
    b = subs.stack_bilingual(_orig(), _trans())
    assert a["id"] != b["id"]


def test_bilingual_orders_constant() -> None:
    assert "original-first" in subs.BILINGUAL_ORDERS
    assert "translation-first" in subs.BILINGUAL_ORDERS
