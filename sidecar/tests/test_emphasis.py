"""Unit tests for media_studio.features.emphasis (P4 §8a).

The annotation is DETERMINISTIC (a keyword lexicon + ALLCAPS/number/long-word
heuristic + a keyword->emoji map): no LLM, no network, no randomness. These
tests pin the determinism, the immutability (inputs never mutated), the char
offsets of the spans, the precedence between rules, and the per-style default.
"""

from __future__ import annotations

from typing import Any

from media_studio.features import emphasis as em


def cue(text: str, index: int = 1, start: float = 0.0, end: float = 1.0) -> dict[str, Any]:
    return {"index": index, "start": start, "end": end, "text": text}


# --------------------------------------------------------------------------- #
# classify_token — the per-rule precedence
# --------------------------------------------------------------------------- #
def test_classify_keyword_wins() -> None:
    # "money" is a keyword AND long (5 letters < 8, so not long) — keyword fires.
    assert em.classify_token("money") == "keyword"
    assert em.classify_token("Secret") == "keyword"  # case-insensitive
    assert em.classify_token("SECRETS") == "keyword"  # keyword beats caps


def test_classify_caps() -> None:
    assert em.classify_token("WOW") == "caps"
    assert em.classify_token("OK") == "caps"
    # single cased letter is NOT caps (avoids "A"/"I")
    assert em.classify_token("A") is None
    assert em.classify_token("I") is None


def test_classify_number() -> None:
    assert em.classify_token("100x") == "number"
    assert em.classify_token("2024") == "number"


def test_classify_long_word() -> None:
    # 8+ letters, not a keyword/caps/number
    assert em.classify_token("absolutely") == "long"
    # short, ordinary word -> nothing
    assert em.classify_token("the") is None
    assert em.classify_token("cat") is None


def test_classify_caps_beats_number_for_caps_letters() -> None:
    # All-caps wins over number when the token has >=2 caps letters and a digit.
    assert em.classify_token("AB12") == "caps"


# --------------------------------------------------------------------------- #
# find_emphasis_spans — char offsets into the ORIGINAL text
# --------------------------------------------------------------------------- #
def test_spans_are_char_offsets_into_text() -> None:
    text = "this is HUGE money"
    spans = em.find_emphasis_spans(text)
    # "HUGE" is a keyword; "money" is a keyword. "this"/"is" are short -> none.
    sliced = [text[s["start"] : s["end"]] for s in spans]
    assert sliced == ["HUGE", "money"]
    kinds = [s["kind"] for s in spans]
    assert kinds == ["keyword", "keyword"]


def test_spans_sorted_and_non_overlapping() -> None:
    text = "AMAZING 50% growth absolutely"
    spans = em.find_emphasis_spans(text)
    starts = [s["start"] for s in spans]
    assert starts == sorted(starts)
    # non-overlapping
    for a, b in zip(spans, spans[1:], strict=False):
        assert a["end"] <= b["start"]


def test_spans_empty_for_plain_text() -> None:
    # no keyword, no all-caps, no digit, no 8+ letter word -> no spans.
    assert em.find_emphasis_spans("just some plain text in here") == []
    assert em.find_emphasis_spans("") == []


# --------------------------------------------------------------------------- #
# pick_emoji — deterministic by MAP order, not text order
# --------------------------------------------------------------------------- #
def test_pick_emoji_map_order_is_the_tiebreak() -> None:
    # "money" appears before "fire" in the text, but EMOJI_MAP lists fire first,
    # so fire wins (deterministic by map order).
    text = "money then fire"
    assert em.pick_emoji(text) == em.EMOJI_MAP[0][1]  # fire's emoji


def test_pick_emoji_whole_word_only() -> None:
    # "firefly" must NOT match the "fire" stem (word boundary).
    assert em.pick_emoji("a firefly flew by") == ""


def test_pick_emoji_none() -> None:
    assert em.pick_emoji("nothing special here") == ""
    assert em.pick_emoji("") == ""


# --------------------------------------------------------------------------- #
# annotate / annotate_cue — additive, immutable, deterministic
# --------------------------------------------------------------------------- #
def test_annotate_is_deterministic() -> None:
    cues = [cue("FREE money now"), cue("just words")]
    a = em.annotate(cues)
    b = em.annotate(cues)
    assert a == b  # same input -> same output, every time


def test_annotate_does_not_mutate_input() -> None:
    src = cue("HUGE secret")
    snapshot = dict(src)
    out = em.annotate([src])
    assert src == snapshot  # input untouched
    assert "emphasis" not in src and "emoji" not in src
    assert out[0] is not src  # a new dict


def test_annotate_adds_spans_and_emoji() -> None:
    out = em.annotate([cue("This SECRET makes you money")])
    c = out[0]
    assert c["index"] == 1 and c["text"] == "This SECRET makes you money"
    sliced = [c["text"][s["start"] : s["end"]] for s in c["emphasis"]]
    assert "SECRET" in sliced and "money" in sliced
    assert c["emoji"]  # secret/money both map to an emoji


def test_annotate_disabled_clears_spans_and_emoji() -> None:
    out = em.annotate([cue("FREE money now")], enable=False)
    assert out[0]["emphasis"] == []
    assert out[0]["emoji"] == ""
    # text is preserved untouched
    assert out[0]["text"] == "FREE money now"


def test_annotate_empty_list() -> None:
    assert em.annotate([]) == []
    assert em.annotate(None) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# resolve_emphasis / default_emphasis_for_style — the §8a default policy
# --------------------------------------------------------------------------- #
def test_default_on_for_opusclip_styles() -> None:
    for style in ("bold", "hormozi", "neon", "tiktok", "mrbeast", "fire"):
        assert em.default_emphasis_for_style(style) is True


def test_default_off_for_clean_minimal_none() -> None:
    for style in ("clean", "subtitle", "none", "libass", "", None):
        assert em.default_emphasis_for_style(style) is False  # type: ignore[arg-type]


def test_resolve_explicit_setting_wins() -> None:
    # explicit OFF beats a style that defaults ON
    assert em.resolve_emphasis({"captionStyle": "bold", "emphasis": False}) is False
    # explicit ON beats a clean style that defaults OFF
    assert em.resolve_emphasis({"captionStyle": "clean", "emphasis": True}) is True


def test_resolve_falls_back_to_style_default() -> None:
    assert em.resolve_emphasis({"captionStyle": "hormozi"}) is True
    assert em.resolve_emphasis({"captionStyle": "clean"}) is False
    assert em.resolve_emphasis({}) is False  # no style -> CLEAN_STYLES contains ""
    assert em.resolve_emphasis(None) is False
