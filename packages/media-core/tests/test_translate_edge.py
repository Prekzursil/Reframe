"""Edge-case coverage for translators and SRT parsing/translation."""

from __future__ import annotations

import sys
import types

import pytest

from media_core.translate import srt as srt_mod
from media_core.translate.srt import _parse_timestamp, parse_srt
from media_core.translate.translator import (
    CloudTranslator,
    LocalTranslator,
    NoOpTranslator,
    Translator,
)


# ---------------------------------------------------------------------------
# Translator base / NoOp
# ---------------------------------------------------------------------------
def test_abstract_translate_batch_raises_not_implemented():
    class PartialTranslator(Translator):
        def translate_batch(self, texts, src, tgt):
            # Delegate to the abstract base implementation, which raises.
            return super().translate_batch(texts, src, tgt)

    with pytest.raises(NotImplementedError):
        PartialTranslator().translate_batch(["x"], "en", "es")


# ---------------------------------------------------------------------------
# CloudTranslator
# ---------------------------------------------------------------------------
def test_cloud_translator_requires_client():
    with pytest.raises(ValueError, match="requires a chat client"):
        CloudTranslator(client=None, model="m")


def test_cloud_translator_refuses_in_offline_mode(monkeypatch):
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "true")

    class Dummy:
        pass

    translator = CloudTranslator(client=Dummy(), model="m")
    with pytest.raises(RuntimeError, match="REFRAME_OFFLINE_MODE"):
        translator.translate_batch(["hello"], "en", "es")


def test_cloud_translator_applies_postprocess(monkeypatch):
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    class FakeClient:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, model, messages, temperature=0.0):  # noqa: ARG002
            msg = type("Msg", (), {"content": "  HOLA  "})()
            choice = type("Choice", (), {"message": msg})()
            return type("Resp", (), {"choices": [choice]})()

    translator = CloudTranslator(
        client=FakeClient(),
        model="m",
        postprocess=lambda s: s.lower() + "!",
    )
    out = translator.translate_batch(["hello"], "en", "es")
    # content is stripped to "HOLA", then postprocessed to "hola!".
    assert out == ["hola!"]


# ---------------------------------------------------------------------------
# LocalTranslator (argostranslate mocked)
# ---------------------------------------------------------------------------
class _FakeLang:
    def __init__(self, code, translator=None):
        self.code = code
        self._translator = translator

    def get_translation(self, _tgt):
        return self._translator


class _FakeArgosTranslator:
    def translate(self, text):
        return f"[es]{text}"


def _install_fake_argostranslate(monkeypatch, languages):
    fake_translate = types.ModuleType("argostranslate.translate")
    fake_translate.get_installed_languages = lambda: languages

    fake_pkg = types.ModuleType("argostranslate")
    fake_pkg.translate = fake_translate
    monkeypatch.setitem(sys.modules, "argostranslate", fake_pkg)
    monkeypatch.setitem(sys.modules, "argostranslate.translate", fake_translate)


def test_local_translator_translates_with_installed_pack(monkeypatch):
    en = _FakeLang("en", translator=_FakeArgosTranslator())
    es = _FakeLang("es")
    _install_fake_argostranslate(monkeypatch, [en, es])

    translator = LocalTranslator("en", "es")
    out = translator.translate_batch(["hi", "there"], "en", "es")
    assert out == ["[es]hi", "[es]there"]


def test_local_translator_missing_language_pack_raises(monkeypatch):
    en = _FakeLang("en", translator=_FakeArgosTranslator())
    _install_fake_argostranslate(monkeypatch, [en])  # no 'es' pack

    with pytest.raises(RuntimeError, match="missing language pack"):
        LocalTranslator("en", "es")


# ---------------------------------------------------------------------------
# SRT parsing
# ---------------------------------------------------------------------------
def test_parse_timestamp_invalid_raises():
    with pytest.raises(ValueError, match="Invalid timestamp"):
        _parse_timestamp("99:99")


def test_parse_srt_skips_blocks_with_too_few_lines():
    # A block with only an index/single line (< 2 parts) is skipped.
    srt = "1\n\n2\n00:00:01,000 --> 00:00:02,000\nhello\n"
    lines = parse_srt(srt)
    assert len(lines) == 1
    assert lines[0].text() == "hello"


def test_parse_srt_skips_block_that_is_only_an_index():
    # After stripping the numeric index line, no parts remain -> skipped.
    srt = "00:00:00,000 --> 00:00:01,000\nreal\n\n42\n"
    lines = parse_srt(srt)
    assert len(lines) == 1
    assert lines[0].text() == "real"


def test_parse_srt_invalid_timing_raises():
    srt = "1\nNOT-A-TIMING-LINE\nhello\n"
    with pytest.raises(ValueError, match="Invalid timing line"):
        parse_srt(srt)


def test_srt_module_exports():
    assert hasattr(srt_mod, "translate_srt")
