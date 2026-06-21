"""Tests for the WU-A1 ``_text_consented_settings`` pool filter (G-A5, privacy).

The TEXT analog of ``_frame_consented_vision_settings`` (covered in
test_handlers_thumbnail.py / test_handlers_phase8.py): it filters
``settings["providers"]`` to TEXT-consented entries PER-ENTRY so a 429 failover
in the embedder pool can NEVER rotate transcript text onto a non-consented
provider. PURE: returns a NEW dict; the original settings are never mutated.

Heavy-free: only a Services instance + plain dict settings are needed (no model,
no network, no cv2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio.handlers import Services


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
def _services(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "ffmpeg_run": lambda argv, **k: 0,
        "ffprobe_duration": lambda p: 12.0,
    }
    base.update(over)
    return Services(**base)


def _consent(per_provider: dict[str, Any]) -> dict[str, Any]:
    return {"consent": {"perProvider": per_provider}}


# --------------------------------------------------------------------------- #
# AC(b): per-entry drop of the non-consented provider, keeping the consented one
# --------------------------------------------------------------------------- #
def test_drops_non_text_consented_entry_keeps_consented(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    settings = {
        **_consent({"Gemini": {"text": True}, "OpenAI": {"text": False}}),
        "providers": [{"provider": "Gemini"}, {"provider": "OpenAI"}],
    }
    out = svc._text_consented_settings(settings)
    assert out["providers"] == [{"provider": "Gemini"}]


def test_original_settings_never_mutated(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    providers = [{"provider": "Gemini"}, {"provider": "OpenAI"}]
    settings = {
        **_consent({"Gemini": {"text": True}, "OpenAI": {"text": False}}),
        "providers": providers,
    }
    out = svc._text_consented_settings(settings)
    # PURE: original list and dict are untouched; a NEW dict is returned.
    assert settings["providers"] == [{"provider": "Gemini"}, {"provider": "OpenAI"}]
    assert settings["providers"] is providers
    assert out is not settings


# --------------------------------------------------------------------------- #
# provider-id resolution: provider -> id -> "cloud" fallback (mirror frame filter)
# --------------------------------------------------------------------------- #
def test_resolves_provider_via_id_field(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    settings = {
        **_consent({"Groq": {"text": True}}),
        "providers": [{"id": "Groq"}],
    }
    out = svc._text_consented_settings(settings)
    assert out["providers"] == [{"id": "Groq"}]


def test_resolves_provider_via_cloud_fallback(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    # No provider/id key → the literal "cloud" name is used for the consent lookup.
    settings = {
        **_consent({"cloud": {"text": True}}),
        "providers": [{"key": "sk-x"}],
    }
    out = svc._text_consented_settings(settings)
    assert out["providers"] == [{"key": "sk-x"}]


# --------------------------------------------------------------------------- #
# AC(c): a non-dict provider entry is dropped (never egress)
# --------------------------------------------------------------------------- #
def test_drops_non_dict_provider_entry(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    settings = {
        **_consent({"Gemini": {"text": True}}),
        "providers": [{"provider": "Gemini"}, "not-a-dict"],
    }
    out = svc._text_consented_settings(settings)
    assert out["providers"] == [{"provider": "Gemini"}]


# --------------------------------------------------------------------------- #
# malformed / absent providers: returned unchanged (mirror frame filter)
# --------------------------------------------------------------------------- #
def test_returns_settings_unchanged_when_providers_absent(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    settings = _consent({"Gemini": {"text": True}})
    out = svc._text_consented_settings(settings)
    assert out is settings


def test_returns_settings_unchanged_when_providers_not_list(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    settings = {**_consent({"Gemini": {"text": True}}), "providers": "nope"}
    out = svc._text_consented_settings(settings)
    assert out is settings
