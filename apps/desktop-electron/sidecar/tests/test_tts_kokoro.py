

# -- lang mapping (Phase-Z smoke regression: bare "en" failed espeak) --------


def test_kokoro_lang_maps_bare_iso_codes():
    from media_studio.features.tts.kokoro import _kokoro_lang

    assert _kokoro_lang("en", "af_sarah") == "en-us"
    assert _kokoro_lang("eng", "am_adam") == "en-us"
    assert _kokoro_lang("en", "bf_emma") == "en-gb"  # UK voice prefix wins
    assert _kokoro_lang("fr", "af_sarah") == "fr-fr"
    assert _kokoro_lang("zh", "af_sarah") == "cmn"
    assert _kokoro_lang("", "af_sarah") == "en-us"  # default
    assert _kokoro_lang("ko", "af_sarah") == "ko"  # unknown passes through
