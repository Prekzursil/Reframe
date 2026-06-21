"""Cover the LAZY default seams of the TTS engines (T2, group C).

Each engine hides its heavy/native backend behind a default factory that is
only built when no test fake is injected. These are normally bypassed by the
seam-injecting tests, so they're exercised here with the established
fake-``sys.modules`` technique (a stand-in ``edge_tts`` / ``kokoro_onnx`` /
``models.translation`` module) plus one REAL but harmless subprocess for the
chatterbox runner seam.

No torch / onnxruntime / real edge-tts is imported — the fakes satisfy the
lazy ``import`` inside each ``_default_*`` so the production wiring path runs
end to end without a native backend.
"""

from __future__ import annotations

import sys
import types

import pytest
from media_studio.features.tts import chatterbox as cb
from media_studio.features.tts import dub as d
from media_studio.features.tts import edgetts as et
from media_studio.features.tts import kokoro as kk
from media_studio.features.tts import voices as vc


# --------------------------------------------------------------------------- #
# chatterbox._default_run_cmd — a REAL drained subprocess (no torch involved)
# --------------------------------------------------------------------------- #
class TestChatterboxDefaultRunCmd:
    def test_runs_argv_and_drains_output(self):
        code, output = cb._default_run_cmd(
            [sys.executable, "-c", "print('hello-from-runner')"],
        )
        assert code == 0
        assert "hello-from-runner" in output

    def test_merges_stderr_and_applies_extra_env(self):
        script = "import os,sys; sys.stderr.write('ENV='+os.environ.get('MS_RUN_TOK','')); print('out')"
        code, output = cb._default_run_cmd(
            [sys.executable, "-c", script],
            {"MS_RUN_TOK": "tok123"},
        )
        assert code == 0
        # stderr is merged into stdout (one failure tail for the error payload)
        assert "ENV=tok123" in output
        assert "out" in output

    def test_nonzero_exit_is_reported(self):
        code, _ = cb._default_run_cmd([sys.executable, "-c", "raise SystemExit(3)"])
        assert code == 3


# --------------------------------------------------------------------------- #
# edgetts._default_factory — lazy edge_tts import (faked module)
# --------------------------------------------------------------------------- #
class TestEdgeTtsDefaultFactory:
    def test_builds_communicate_from_lazy_import(self, monkeypatch):
        seen = {}

        class FakeCommunicate:
            def __init__(self, text, voice, *, rate):
                seen.update(text=text, voice=voice, rate=rate)

        fake_mod = types.ModuleType("edge_tts")
        fake_mod.Communicate = FakeCommunicate
        monkeypatch.setitem(sys.modules, "edge_tts", fake_mod)

        obj = et._default_factory("Hello.", "en-US-AriaNeural", "+10%")
        assert isinstance(obj, FakeCommunicate)
        assert seen == {"text": "Hello.", "voice": "en-US-AriaNeural", "rate": "+10%"}


# --------------------------------------------------------------------------- #
# kokoro._default_factory — lazy kokoro_onnx import (faked module)
# --------------------------------------------------------------------------- #
class TestKokoroDefaultFactory:
    def test_builds_kokoro_from_lazy_import(self, monkeypatch):
        seen = {}

        class FakeKokoro:
            def __init__(self, model_path, voices_path):
                seen.update(model=model_path, voices=voices_path)

        fake_mod = types.ModuleType("kokoro_onnx")
        fake_mod.Kokoro = FakeKokoro
        monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_mod)

        obj = kk._default_factory("C:/m.onnx", "C:/v.bin")
        assert isinstance(obj, FakeKokoro)
        assert seen == {"model": "C:/m.onnx", "voices": "C:/v.bin"}

    def test_no_native_backend_leaked_at_import(self):
        # The fake is scoped to the test above; the real native must never load.
        assert "onnxruntime" not in sys.modules


# --------------------------------------------------------------------------- #
# dub._default_translator_factory — lazy models.translation seam (faked)
# --------------------------------------------------------------------------- #
class TestDubDefaultTranslatorFactory:
    def test_builds_translator_via_get_translator(self, monkeypatch):
        sentinel = object()
        fake_mod = types.ModuleType("media_studio.models.translation")
        fake_mod.get_translator = lambda: sentinel
        monkeypatch.setitem(sys.modules, "media_studio.models.translation", fake_mod)
        # `from ...models import translation` reads the parent-package attribute,
        # which is the real submodule once any other test imported it — patch both.
        monkeypatch.setattr("media_studio.models.translation", fake_mod, raising=False)

        assert d._default_translator_factory() is sentinel

    def test_missing_get_translator_raises_clear_error(self, monkeypatch):
        fake_mod = types.ModuleType("media_studio.models.translation")
        # no get_translator attribute on purpose
        monkeypatch.setitem(sys.modules, "media_studio.models.translation", fake_mod)
        monkeypatch.setattr("media_studio.models.translation", fake_mod, raising=False)
        with pytest.raises(d.DubError, match="get_translator"):
            d._default_translator_factory()

    def test_missing_module_raises_backend_unavailable(self, monkeypatch):
        # A ``None`` sentinel in sys.modules makes Python raise ImportError on
        # ``from ...models import translation`` — and strip the parent's cached
        # attribute so the import statement can't shortcut to it.
        import media_studio.models as models_pkg

        monkeypatch.setitem(sys.modules, "media_studio.models.translation", None)
        monkeypatch.delattr(models_pkg, "translation", raising=False)
        with pytest.raises(d.DubError, match="translation backend unavailable"):
            d._default_translator_factory()


# --------------------------------------------------------------------------- #
# voices._default_probe — lazy ffmpeg.ffprobe_duration seam
# --------------------------------------------------------------------------- #
class TestVoicesDefaultProbe:
    def test_delegates_to_ffprobe_duration(self, monkeypatch):
        from media_studio import ffmpeg

        monkeypatch.setattr(ffmpeg, "ffprobe_duration", lambda path: 12.5)
        assert vc._default_probe("C:/some.wav") == 12.5

    def test_default_voices_dir_under_config(self, monkeypatch):
        from pathlib import Path

        from media_studio import settings_store

        monkeypatch.setattr(settings_store, "default_config_dir", lambda: Path("C:/cfg"))
        # voices imports the symbol directly; patch where it is looked up.
        monkeypatch.setattr(vc, "default_config_dir", lambda: Path("C:/cfg"))
        assert vc.default_voices_dir() == Path("C:/cfg") / "voices"
