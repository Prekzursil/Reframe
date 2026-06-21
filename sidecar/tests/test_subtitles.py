"""Unit tests for media_studio.features.subtitles.

Pure logic only — no heavy-ML import. The translation provider is a fake object
exposing a ``chat`` method; whisper/llama are never loaded. Covers:
  - generate(Transcript) -> SubtitleTrack (schema, lang, segment-splitting)
  - edit(track, cues) (immutability + reindex)
  - translate(track, lang, provider/translator) with a FAKE provider
  - SRT / ASS / VTT round-trips + timestamp formatting/parsing
  - ASS escaping (no {}-override injection) + file export/load
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.features import subtitles as S


# --------------------------------------------------------------------------- #
# fixtures / fakes
# --------------------------------------------------------------------------- #
def _seg(start: float, end: float, text: str, words=None) -> dict[str, Any]:
    return {"start": start, "end": end, "text": text, "words": words or []}


@pytest.fixture
def transcript() -> dict[str, Any]:
    return {
        "language": "en",
        "durationSec": 12.0,
        "segments": [
            _seg(0.0, 2.0, "Hello world."),
            _seg(2.5, 5.0, "This is a talk."),
            _seg(5.5, 8.0, "   "),  # blank -> dropped
            _seg(8.0, 11.0, "Goodbye."),
        ],
    }


@pytest.fixture
def simple_track() -> dict[str, Any]:
    cues = [
        S.make_cue(1, 0.0, 2.0, "Hello world."),
        S.make_cue(2, 2.5, 5.0, "This is a talk."),
    ]
    return S.new_track(cues, lang="en", name="English", fmt="srt")


class FakeProvider:
    """A fake Provider whose ``chat`` records calls and returns canned text.

    Mirrors the seam used by make_provider_translator: messages = [system, user].
    """

    def __init__(self, reply: str = "TRANSLATED") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(messages)
        # Echo a deterministic translation so assertions can key on input.
        user = messages[-1]["content"]
        return f"[{self.reply}] {user}"


# --------------------------------------------------------------------------- #
# new_track / make_cue / reindex
# --------------------------------------------------------------------------- #
def test_new_track_has_all_schema_fields():
    t = S.new_track([], lang="es", name="Spanish", fmt="vtt", kind="hard")
    assert set(t.keys()) == {"id", "lang", "name", "format", "kind", "cues"}
    assert t["lang"] == "es"
    assert t["name"] == "Spanish"
    assert t["format"] == "vtt"
    assert t["kind"] == "hard"
    assert t["cues"] == []
    assert t["id"]


def test_new_track_coerces_unknown_kind_to_soft():
    t = S.new_track([], kind="bogus")
    assert t["kind"] == "soft"


def test_new_track_accepts_explicit_track_id():
    t = S.new_track([], track_id="fixed123")
    assert t["id"] == "fixed123"


def test_make_cue_field_names_and_types():
    c = S.make_cue(3, 1.5, 2.0, "hi")
    assert c == {"index": 3, "start": 1.5, "end": 2.0, "text": "hi"}
    assert isinstance(c["index"], int)
    assert isinstance(c["start"], float)


def test_reindex_renumbers_one_based_without_mutation():
    src = [S.make_cue(9, 0.0, 1.0, "a"), S.make_cue(4, 1.0, 2.0, "b")]
    out = S.reindex(src)
    assert [c["index"] for c in out] == [1, 2]
    # originals untouched
    assert src[0]["index"] == 9
    assert out[0] is not src[0]


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #
def test_generate_builds_soft_track_from_transcript(transcript):
    track = S.generate(transcript)
    assert track["kind"] == "soft"
    assert track["lang"] == "en"
    assert track["format"] == "srt"
    # blank segment dropped -> 3 cues, reindexed 1..3
    assert [c["index"] for c in track["cues"]] == [1, 2, 3]
    assert track["cues"][0]["text"] == "Hello world."
    assert track["cues"][-1]["text"] == "Goodbye."


def test_generate_uses_und_when_language_missing():
    track = S.generate({"segments": [_seg(0.0, 1.0, "x")]})
    assert track["lang"] == "und"


def test_generate_respects_track_id_and_name():
    track = S.generate({"language": "fr", "segments": []}, name="N", track_id="t-1")
    assert track["id"] == "t-1"
    assert track["name"] == "N"
    assert track["cues"] == []


def test_cues_from_transcript_splits_long_word_timed_segment():
    words = [
        {"text": w, "start": i * 1.0, "end": i * 1.0 + 0.9}
        for i, w in enumerate(["one", "two", "three", "four", "five", "six"])
    ]
    seg = _seg(0.0, 6.0, "one two three four five six", words=words)
    cues = S.cues_from_transcript({"segments": [seg]}, max_chars=12, max_duration=2.0)
    # must split into multiple cues, none exceeding the char budget by much
    assert len(cues) >= 2
    assert all(c["text"] for c in cues)
    # word boundaries preserved (no split mid-word)
    joined = " ".join(c["text"] for c in cues)
    assert joined == "one two three four five six"


def test_cues_from_transcript_keeps_short_segment_whole():
    seg = _seg(0.0, 1.0, "short", words=[{"text": "short", "start": 0.0, "end": 1.0}])
    cues = S.cues_from_transcript({"segments": [seg]})
    assert len(cues) == 1
    assert cues[0]["text"] == "short"


def test_cues_from_transcript_without_words_keeps_long_segment_whole():
    # No word timing -> cannot split; long segment stays as a single cue.
    long_text = "x" * 200
    cues = S.cues_from_transcript({"segments": [_seg(0.0, 30.0, long_text)]})
    assert len(cues) == 1
    assert cues[0]["text"] == long_text


# --------------------------------------------------------------------------- #
# edit
# --------------------------------------------------------------------------- #
def test_edit_replaces_cues_and_reindexes(simple_track):
    new_cues = [S.make_cue(99, 0.0, 1.0, "only")]
    edited = S.edit(simple_track, new_cues)
    assert len(edited["cues"]) == 1
    assert edited["cues"][0]["index"] == 1
    assert edited["cues"][0]["text"] == "only"


def test_edit_is_immutable(simple_track):
    before = len(simple_track["cues"])
    S.edit(simple_track, [S.make_cue(1, 0.0, 1.0, "x")])
    assert len(simple_track["cues"]) == before  # original untouched


def test_edit_preserves_track_identity_fields(simple_track):
    edited = S.edit(simple_track, [])
    assert edited["id"] == simple_track["id"]
    assert edited["lang"] == simple_track["lang"]
    assert edited["format"] == simple_track["format"]


# --------------------------------------------------------------------------- #
# translate (FAKE provider)
# --------------------------------------------------------------------------- #
def test_translate_with_fake_provider_translates_each_cue(simple_track):
    provider = FakeProvider(reply="ES")
    out = S.translate(simple_track, "es", provider=provider)
    assert out["lang"] == "es"
    assert [c["text"] for c in out["cues"]] == [
        "[ES] Hello world.",
        "[ES] This is a talk.",
    ]
    # one chat call per non-blank cue
    assert len(provider.calls) == 2
    # system prompt mentions the target language
    assert "es" in provider.calls[0][0]["content"]
    assert provider.calls[0][0]["role"] == "system"
    assert provider.calls[0][1]["role"] == "user"


def test_translate_preserves_timings_and_indices(simple_track):
    out = S.translate(simple_track, "es", provider=FakeProvider())
    assert [c["index"] for c in out["cues"]] == [1, 2]
    assert out["cues"][0]["start"] == simple_track["cues"][0]["start"]
    assert out["cues"][1]["end"] == simple_track["cues"][1]["end"]


def test_translate_is_immutable(simple_track):
    original_text = simple_track["cues"][0]["text"]
    S.translate(simple_track, "es", provider=FakeProvider())
    assert simple_track["cues"][0]["text"] == original_text
    assert simple_track["lang"] == "en"


def test_translate_with_injected_translator_callable(simple_track):
    out = S.translate(simple_track, "de", translator=lambda t: t.upper())
    assert [c["text"] for c in out["cues"]] == ["HELLO WORLD.", "THIS IS A TALK."]


def test_translate_skips_provider_call_for_blank_cue():
    track = S.new_track([S.make_cue(1, 0.0, 1.0, "   ")], lang="en")
    provider = FakeProvider()
    out = S.translate(track, "es", provider=provider)
    assert out["cues"][0]["text"] == "   "
    assert provider.calls == []  # no provider call for a blank line


def test_translate_requires_a_seam(simple_track):
    with pytest.raises(ValueError):
        S.translate(simple_track, "es")


def test_translate_emits_progress(simple_track):
    seen: list[int] = []
    S.translate(
        simple_track,
        "es",
        translator=lambda t: t,
        progress=lambda pct, msg: seen.append(pct),
    )
    assert seen == [50, 100]


def test_translate_honors_cancellation(simple_track):
    out = S.translate(
        simple_track,
        "es",
        translator=lambda t: t.upper(),
        cancelled=lambda: True,  # cancelled before the first cue
    )
    assert out["cues"] == []


def test_make_provider_translator_blank_short_circuits():
    provider = FakeProvider()
    tr = S.make_provider_translator(provider, "fr")
    assert tr("") == ""
    assert provider.calls == []


# --------------------------------------------------------------------------- #
# timestamps
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (3661.234, "01:01:01,234"),
        (-5.0, "00:00:00,000"),  # negatives clamp to zero
    ],
)
def test_format_timestamp_srt(seconds, expected):
    assert S.format_timestamp_srt(seconds) == expected


def test_format_timestamp_vtt_uses_dot():
    assert S.format_timestamp_vtt(1.5) == "00:00:01.500"


def test_format_timestamp_ass_uses_centiseconds():
    assert S.format_timestamp_ass(3661.23) == "1:01:01.23"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("00:00:01,500", 1.5),
        ("00:00:01.500", 1.5),
        ("1:01:01.23", 3661.23),  # ass centiseconds
        ("01:01:01,234", 3661.234),
    ],
)
def test_parse_timestamp(text, expected):
    assert S.parse_timestamp(text) == pytest.approx(expected)


def test_parse_timestamp_rejects_garbage():
    with pytest.raises(ValueError):
        S.parse_timestamp("not a time")


# --------------------------------------------------------------------------- #
# SRT round-trip
# --------------------------------------------------------------------------- #
def test_to_srt_format(simple_track):
    text = S.to_srt(simple_track["cues"])
    assert text.startswith("1\n00:00:00,000 --> 00:00:02,000\nHello world.")
    assert "\n\n2\n" in text
    assert text.endswith("\n")


def test_srt_round_trip(simple_track):
    text = S.to_srt(simple_track["cues"])
    cues = S.read_srt(text)
    assert [c["text"] for c in cues] == ["Hello world.", "This is a talk."]
    assert cues[0]["start"] == 0.0
    assert cues[1]["end"] == pytest.approx(5.0)
    assert [c["index"] for c in cues] == [1, 2]


def test_read_srt_tolerates_crlf_and_bom():
    raw = "﻿1\r\n00:00:00,000 --> 00:00:01,000\r\nHi\r\n"
    cues = S.read_srt(raw)
    assert len(cues) == 1
    assert cues[0]["text"] == "Hi"


def test_read_srt_handles_multiline_text():
    raw = "1\n00:00:00,000 --> 00:00:02,000\nLine one\nLine two\n"
    cues = S.read_srt(raw)
    assert cues[0]["text"] == "Line one\nLine two"


def test_read_srt_without_index_lines():
    raw = "00:00:00,000 --> 00:00:01,000\nNo index here\n"
    cues = S.read_srt(raw)
    assert len(cues) == 1
    assert cues[0]["text"] == "No index here"


def test_read_srt_empty_returns_empty():
    assert S.read_srt("") == []
    assert S.read_srt("   \n\n  ") == []


# --------------------------------------------------------------------------- #
# VTT round-trip
# --------------------------------------------------------------------------- #
def test_to_vtt_has_header(simple_track):
    text = S.to_vtt(simple_track["cues"])
    assert text.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:02.000" in text


def test_vtt_round_trip(simple_track):
    text = S.to_vtt(simple_track["cues"])
    cues = S.read_vtt(text)
    assert [c["text"] for c in cues] == ["Hello world.", "This is a talk."]
    assert cues[1]["start"] == pytest.approx(2.5)


def test_read_vtt_skips_note_blocks():
    raw = "WEBVTT\n\nNOTE this is a comment\n\n00:00:00.000 --> 00:00:01.000\nReal cue\n"
    cues = S.read_vtt(raw)
    assert len(cues) == 1
    assert cues[0]["text"] == "Real cue"


def test_read_vtt_with_cue_id_and_settings():
    raw = "WEBVTT\n\nintro\n00:00:00.000 --> 00:00:01.000 align:start position:10%\nStyled cue\n"
    cues = S.read_vtt(raw)
    assert len(cues) == 1
    assert cues[0]["text"] == "Styled cue"
    assert cues[0]["end"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# ASS round-trip + escaping
# --------------------------------------------------------------------------- #
def test_to_ass_has_sections_and_dialogue(simple_track):
    text = S.to_ass(simple_track["cues"], width=1080, height=1920)
    assert "[Script Info]" in text
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    assert "[V4+ Styles]" in text
    assert "[Events]" in text
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Hello world." in text


def test_ass_round_trip(simple_track):
    text = S.to_ass(simple_track["cues"])
    cues = S.read_ass(text)
    assert [c["text"] for c in cues] == ["Hello world.", "This is a talk."]
    assert cues[0]["start"] == pytest.approx(0.0)
    assert cues[1]["end"] == pytest.approx(5.0)


def test_escape_ass_text_blocks_override_injection():
    # raw { } would be an ASS override block — must be neutralized
    escaped = S.escape_ass_text("{\\b1}bold{\\b0}")
    assert "{" not in escaped
    assert "}" not in escaped


def test_escape_ass_text_converts_newlines():
    assert S.escape_ass_text("a\nb") == "a\\Nb"
    assert S.escape_ass_text("a\r\nb") == "a\\Nb"


def test_ass_dialogue_does_not_contain_raw_braces(simple_track):
    cues = [S.make_cue(1, 0.0, 1.0, "evil {\\fscx200} text")]
    text = S.to_ass(cues)
    dialogue_lines = [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]
    assert len(dialogue_lines) == 1
    assert "{" not in dialogue_lines[0]
    assert "}" not in dialogue_lines[0]


def test_ass_round_trip_with_comma_in_text():
    cues = [S.make_cue(1, 0.0, 2.0, "Hello, world, again")]
    text = S.to_ass(cues)
    parsed = S.read_ass(text)
    assert parsed[0]["text"] == "Hello, world, again"


def test_ass_round_trip_with_newline_in_text():
    cues = [S.make_cue(1, 0.0, 2.0, "line1\nline2")]
    parsed = S.read_ass(S.to_ass(cues))
    assert parsed[0]["text"] == "line1\nline2"


def test_read_ass_ignores_non_event_sections():
    text = S.to_ass([S.make_cue(1, 0.0, 1.0, "only cue")])
    # Style: lines in [V4+ Styles] must not become cues.
    cues = S.read_ass(text)
    assert len(cues) == 1


# --------------------------------------------------------------------------- #
# format dispatch + file I/O
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
def test_serialize_then_parse_round_trip(simple_track, fmt):
    text = S.serialize(simple_track, fmt)
    cues = S.parse(text, fmt)
    assert [c["text"] for c in cues] == ["Hello world.", "This is a talk."]


def test_normalize_format_accepts_dot_and_uppercase(simple_track):
    assert S.serialize(simple_track, ".SRT")  # does not raise
    assert S.serialize(simple_track, "SSA")  # ssa -> ass alias


def test_unsupported_format_raises(simple_track):
    with pytest.raises(ValueError):
        S.serialize(simple_track, "sub")


@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
def test_export_writes_file_and_returns_path(simple_track, tmp_path: Path, fmt):
    out = tmp_path / "subs with space" / f"track.{fmt}"
    returned = S.export(simple_track, fmt, out)
    assert Path(returned) == out
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() != ""


@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
def test_load_reads_back_exported_file(simple_track, tmp_path: Path, fmt):
    out = tmp_path / f"track.{fmt}"
    S.export(simple_track, fmt, out)
    cues = S.load(out)
    assert [c["text"] for c in cues] == ["Hello world.", "This is a talk."]


def test_track_from_file_wraps_cues(simple_track, tmp_path: Path):
    out = tmp_path / "english.srt"
    S.export(simple_track, "srt", out)
    track = S.track_from_file(out, lang="en", name="English")
    assert track["lang"] == "en"
    assert track["name"] == "English"
    assert track["format"] == "srt"
    assert track["kind"] == "soft"
    assert [c["text"] for c in track["cues"]] == ["Hello world.", "This is a talk."]


def test_track_from_file_defaults_name_to_stem(simple_track, tmp_path: Path):
    out = tmp_path / "my-subs.vtt"
    S.export(simple_track, "vtt", out)
    track = S.track_from_file(out)
    assert track["name"] == "my-subs"
    assert track["format"] == "vtt"


def test_track_to_json_round_trips(simple_track):
    import json

    text = S.track_to_json(simple_track)
    back = json.loads(text)
    assert back["id"] == simple_track["id"]
    assert back["cues"][0]["text"] == "Hello world."


def test_full_pipeline_generate_translate_export(transcript, tmp_path: Path):
    """generate -> translate (fake provider) -> export -> load round-trip."""
    track = S.generate(transcript)
    translated = S.translate(track, "es", provider=FakeProvider(reply="ES"))
    out = tmp_path / "es.srt"
    S.export(translated, "srt", out)
    cues = S.load(out)
    assert all(c["text"].startswith("[ES]") for c in cues)
    assert len(cues) == 3


# --------------------------------------------------------------------------- #
# generate_polished (WU9 wiring): caption-polish over a generated track
# --------------------------------------------------------------------------- #
def test_generate_polished_threads_cues_through_injected_polisher(transcript):
    seen: dict[str, Any] = {}

    def fake_polisher(cues, *, settings):
        seen["cues"] = cues
        seen["settings"] = settings
        # Return cues with rewritten (polished) text.
        return [{**c, "text": c["text"].upper()} for c in cues]

    track = S.generate_polished(transcript, settings={"captionChildren": True}, polisher=fake_polisher)
    # the polisher saw the generated cues + the settings
    assert seen["settings"] == {"captionChildren": True}
    assert seen["cues"], "polisher received no cues"
    # polished text landed on the track (reindexed onto a fresh §3 track)
    assert track["cues"][0]["text"] == "HELLO WORLD."
    assert set(track.keys()) == {"id", "lang", "name", "format", "kind", "cues"}
    assert track["lang"] == "en"
    assert track["kind"] == "soft"
    # cues are reindexed 1..N
    assert [c["index"] for c in track["cues"]] == list(range(1, len(track["cues"]) + 1))


def test_generate_polished_default_polisher_is_degrade_safe(transcript):
    """The default polisher delegates to the real module; with no model backends
    the timing/segmentation gate still runs and never raises (heavy-dep-free)."""
    track = S.generate_polished(transcript)
    assert track["cues"], "default polish produced no cues"
    assert track["lang"] == "en"
    # text is preserved (no punct/casing backend -> casing left as-is)
    joined = " ".join(c["text"] for c in track["cues"])
    assert "Hello world." in joined


def test_default_caption_polisher_delegates(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_polish(cues, **kwargs):
        captured["cues"] = cues
        captured.update(kwargs)
        return cues

    from media_studio.features import caption_polish

    monkeypatch.setattr(caption_polish, "polish_cues", fake_polish)
    cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "hi"}]
    out = S._default_caption_polisher(cues, settings={"x": 1})
    assert out == cues
    assert captured["cues"] == cues
    assert captured["settings"] == {"x": 1}


# --------------------------------------------------------------------------- #
# WU-3 — diarized speaker-carry (GAP #2)
# --------------------------------------------------------------------------- #
def test_make_cue_without_speaker_omits_key():
    # Back-compat: no speaker -> the §3 shape stays byte-identical (no key).
    c = S.make_cue(1, 0.0, 1.0, "hi")
    assert "speaker" not in c
    assert c == {"index": 1, "start": 0.0, "end": 1.0, "text": "hi"}


def test_make_cue_with_speaker_adds_key():
    c = S.make_cue(1, 0.0, 1.0, "hi", speaker="SPEAKER_00")
    assert c["speaker"] == "SPEAKER_00"
    # frozen fields keep their names/order; speaker is additive.
    assert c == {"index": 1, "start": 0.0, "end": 1.0, "text": "hi", "speaker": "SPEAKER_00"}


def test_make_cue_empty_speaker_omits_key():
    # Empty string is falsy -> treated as "no speaker" (no leakage).
    c = S.make_cue(1, 0.0, 1.0, "hi", speaker="")
    assert "speaker" not in c


def test_make_cue_coerces_speaker_to_str():
    c = S.make_cue(1, 0.0, 1.0, "hi", speaker=7)
    assert c["speaker"] == "7"


def test_reindex_preserves_speaker_when_present():
    src = [
        {"index": 9, "start": 0.0, "end": 1.0, "text": "a", "speaker": "SPEAKER_01"},
        {"index": 4, "start": 1.0, "end": 2.0, "text": "b"},
    ]
    out = S.reindex(src)
    assert [c["index"] for c in out] == [1, 2]
    assert out[0]["speaker"] == "SPEAKER_01"
    assert "speaker" not in out[1]  # absent -> no speaker:None leakage


def test_cues_from_transcript_carries_speaker():
    seg = {"start": 0.0, "end": 1.0, "text": "hi there", "speaker": "SPEAKER_00", "words": []}
    cues = S.cues_from_transcript({"segments": [seg]})
    assert len(cues) == 1
    assert cues[0]["speaker"] == "SPEAKER_00"


def test_cues_from_transcript_no_speaker_key_when_absent():
    cues = S.cues_from_transcript({"segments": [_seg(0.0, 1.0, "hi")]})
    assert "speaker" not in cues[0]


def test_split_segment_inherits_speaker():
    words = [
        {"text": w, "start": i * 1.0, "end": i * 1.0 + 0.9}
        for i, w in enumerate(["one", "two", "three", "four", "five", "six"])
    ]
    seg = {
        "start": 0.0,
        "end": 6.0,
        "text": "one two three four five six",
        "speaker": "SPEAKER_02",
        "words": words,
    }
    cues = S.cues_from_transcript({"segments": [seg]}, max_chars=12, max_duration=2.0)
    assert len(cues) >= 2
    assert all(c["speaker"] == "SPEAKER_02" for c in cues)


def test_split_segment_without_speaker_omits_key():
    words = [
        {"text": w, "start": i * 1.0, "end": i * 1.0 + 0.9}
        for i, w in enumerate(["one", "two", "three", "four", "five", "six"])
    ]
    seg = _seg(0.0, 6.0, "one two three four five six", words=words)
    cues = S.cues_from_transcript({"segments": [seg]}, max_chars=12, max_duration=2.0)
    assert len(cues) >= 2
    assert all("speaker" not in c for c in cues)


def test_format_speaker_prefix_off_is_identity_on_text():
    cues = [S.make_cue(1, 0.0, 1.0, "hi", speaker="SPEAKER_00")]
    out = S.format_speaker_prefix(cues, on=False)
    assert out[0]["text"] == "hi"
    assert out[0]["speaker"] == "SPEAKER_00"
    # immutable: fresh dict, input untouched.
    assert out[0] is not cues[0]


def test_format_speaker_prefix_on_prefixes_speaker_cue():
    cues = [S.make_cue(1, 0.0, 1.0, "hi", speaker="SPEAKER_00")]
    out = S.format_speaker_prefix(cues, on=True)
    assert out[0]["text"] == "SPEAKER_00: hi"
    # input not mutated
    assert cues[0]["text"] == "hi"


def test_format_speaker_prefix_on_skips_non_speaker_cue():
    cues = [S.make_cue(1, 0.0, 1.0, "hi")]
    out = S.format_speaker_prefix(cues, on=True)
    assert out[0]["text"] == "hi"
    assert "speaker" not in out[0]


def test_format_speaker_prefix_off_non_speaker_cue():
    cues = [S.make_cue(1, 0.0, 1.0, "hi")]
    out = S.format_speaker_prefix(cues, on=False)
    assert out[0]["text"] == "hi"


def test_srt_back_compat_no_speaker_prefix_off():
    # No-speaker, prefix-off path must serialize byte-identically to today.
    cues = [S.make_cue(1, 0.0, 1.0, "hello"), S.make_cue(2, 1.0, 2.0, "world")]
    plain = S.to_srt(cues)
    passed = S.to_srt(S.format_speaker_prefix(cues, on=False))
    assert passed == plain


def test_vtt_ass_back_compat_no_speaker_prefix_off():
    cues = [S.make_cue(1, 0.0, 1.0, "hello")]
    no_prefix = S.format_speaker_prefix(cues, on=False)
    assert S.to_vtt(no_prefix) == S.to_vtt(cues)
    assert S.to_ass(no_prefix) == S.to_ass(cues)
