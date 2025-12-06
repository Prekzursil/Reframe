from media_core.translate import (
    NoOpTranslator,
    parse_srt,
    translate_srt,
    translate_srt_bilingual,
)


class UpperTranslator(NoOpTranslator):
    def translate_batch(self, texts, src, tgt):
        return [t.upper() for t in texts]


def test_parse_srt_parses_lines():
    srt = """1
00:00:00,000 --> 00:00:01,000
hello world

2
00:00:02,000 --> 00:00:03,000
second line
"""
    lines = parse_srt(srt)
    assert len(lines) == 2
    assert lines[0].text() == "hello world"
    assert lines[1].start == 2.0 and lines[1].end == 3.0


def test_translate_srt_preserves_order_and_count():
    srt = """00:00:00,000 --> 00:00:01,000
hello

00:00:01,500 --> 00:00:02,500
world
"""
    out = translate_srt(srt, UpperTranslator(), src="en", tgt="es")
    assert "HELLO" in out and "WORLD" in out
    assert out.count("--> ") == 2


def test_translate_srt_bilingual_combines_texts():
    srt = """00:00:00,000 --> 00:00:01,000
hi
"""
    out = translate_srt_bilingual(srt, UpperTranslator(), src="en", tgt="es")
    assert "hi" in out and "HI" in out
    assert "\\N" in out
