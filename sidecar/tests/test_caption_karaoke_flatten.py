"""Karaoke groups multi-word lines even from ONE-WORD cues (bug-sweep fix).

The shortmaker pipeline (features._cues_for_clip) emits one cue PER transcript
word, so build_karaoke_ass's per-cue grouping collapsed every karaoke line to a
single word. It now flattens words across all cues before grouping, restoring the
1-4-words-per-line OpusClip look. This feeds the ACTUAL per-word cue shape.
"""

from __future__ import annotations

from media_studio.features import caption_karaoke as ck


def test_karaoke_groups_multiple_words_from_one_word_cues() -> None:
    words = ["hello", "there", "how", "are", "you", "today"]
    cues = [
        {"index": i + 1, "start": float(i), "end": float(i) + 0.5, "text": w}
        for i, w in enumerate(words)
    ]
    ass = ck.build_karaoke_ass(cues, source_start=0.0)
    dialogues = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    assert dialogues, "no karaoke dialogue events were produced"
    # The first rendered line must carry MULTIPLE words (grouped), not a single one.
    # build_line_text upper-cases (the OpusClip all-caps look), so match case-insensitively.
    first = dialogues[0].lower()
    grouped = sum(1 for w in words if w in first)
    assert grouped >= 2, f"karaoke line did not group multiple words (one-per-line bug): {dialogues[0]!r}"
