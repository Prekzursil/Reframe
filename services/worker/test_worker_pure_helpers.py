"""Unit tests for the worker's pure (DB-free) helper functions."""

from __future__ import annotations

import subprocess

import pytest

from services.worker import worker  # pylint: disable=import-error


def test_env_truthy_reads_plain_and_prefixed(monkeypatch):
    """``_env_truthy`` accepts both the bare and ``REFRAME_``-prefixed names."""
    monkeypatch.delenv("SOME_FLAG", raising=False)
    monkeypatch.delenv("REFRAME_SOME_FLAG", raising=False)
    assert worker._env_truthy("SOME_FLAG") is False
    monkeypatch.setenv("REFRAME_SOME_FLAG", "YES")
    assert worker._env_truthy("SOME_FLAG") is True
    monkeypatch.setenv("SOME_FLAG", "on")
    assert worker._env_truthy("SOME_FLAG") is True


def test_offline_mode_enabled_reflects_env(monkeypatch):
    """``offline_mode_enabled`` mirrors ``REFRAME_OFFLINE_MODE``."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    assert worker.offline_mode_enabled() is False
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    assert worker.offline_mode_enabled() is True


def test_retry_max_attempts_default_and_floor(monkeypatch):
    """Retry attempts default to 2, parse ints, and never drop below 1."""
    monkeypatch.delenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", raising=False)
    assert worker._retry_max_attempts() == 2
    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "5")
    assert worker._retry_max_attempts() == 5
    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "0")
    assert worker._retry_max_attempts() == 1
    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "not-a-number")
    assert worker._retry_max_attempts() == 2


def test_retry_base_delay_default_and_floor(monkeypatch):
    """Retry base delay defaults to 1.0, parses floats, and clamps at 0."""
    monkeypatch.delenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", raising=False)
    assert worker._retry_base_delay_seconds() == 1.0
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "2.5")
    assert worker._retry_base_delay_seconds() == 2.5
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "-3")
    assert worker._retry_base_delay_seconds() == 0.0
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "junk")
    assert worker._retry_base_delay_seconds() == 1.0


def test_run_ffmpeg_with_retries_returns_immediately_on_success(monkeypatch):
    """A successful call returns its result without recording a retry."""
    monkeypatch.setattr(worker, "update_job", lambda *a, **k: None)
    result = worker._run_ffmpeg_with_retries(
        job_id="job", step="x", fn=lambda: "ok"
    )
    assert result == "ok"


def test_run_ffmpeg_with_retries_raises_after_exhausting_attempts(monkeypatch):
    """When every attempt fails the last ``CalledProcessError`` is re-raised."""
    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "0")
    monkeypatch.setattr(worker, "update_job", lambda *a, **k: None)

    def always_fail():
        raise subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr=b"boom")

    with pytest.raises(subprocess.CalledProcessError):
        worker._run_ffmpeg_with_retries(job_id="job", step="x", fn=always_fail)


def test_record_ffmpeg_retry_handles_str_stderr(monkeypatch):
    """``_record_ffmpeg_retry`` accepts string stderr and applies the delay."""
    captured: dict = {}
    monkeypatch.setattr(
        worker, "update_job", lambda job_id, **kw: captured.update({"id": job_id, **kw})
    )
    sleeps: list[float] = []
    monkeypatch.setattr(worker.time, "sleep", lambda s: sleeps.append(s))
    exc = subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"])
    exc.stderr = "text-error"
    worker._record_ffmpeg_retry(
        job_id="job-9", step="cut:1", attempt=1, max_attempts=3, delay=0.5, exc=exc
    )
    assert captured["payload"]["retry_error"] == "text-error"
    assert sleeps == [0.5]


def test_coerce_bool_handles_all_types():
    """``_coerce_bool`` covers bool, numeric, truthy strings, and fallbacks."""
    assert worker._coerce_bool(True) is True
    assert worker._coerce_bool(0) is False
    assert worker._coerce_bool(3) is True
    assert worker._coerce_bool("Yes") is True
    assert worker._coerce_bool("nope") is False
    assert worker._coerce_bool(object()) is False


def test_coerce_bool_with_default():
    """``_coerce_bool_with_default`` returns the default only for ``None``."""
    assert worker._coerce_bool_with_default(None, True) is True
    assert worker._coerce_bool_with_default("on", False) is True


def test_hex_to_ass_color_variants():
    """``_hex_to_ass_color`` parses 3/6-digit hex and falls back otherwise."""
    assert worker._hex_to_ass_color("#ffffff", default="X") == "&H00FFFFFF"
    assert worker._hex_to_ass_color("f00", default="X") == "&H000000FF"
    assert worker._hex_to_ass_color("", default="X") == "X"
    assert worker._hex_to_ass_color(123, default="X") == "X"
    assert worker._hex_to_ass_color("12345", default="X") == "X"
    assert worker._hex_to_ass_color("#gggggg", default="X") == "X"


def test_is_http_uri():
    """``_is_http_uri`` recognises http/https prefixes only."""
    assert worker._is_http_uri("http://x") is True
    assert worker._is_http_uri("HTTPS://X") is True
    assert worker._is_http_uri("/local/path") is False
    assert worker._is_http_uri("") is False


def test_style_int_parses_and_falls_back():
    """``_style_int`` coerces ints and falls back on bad values."""
    assert worker._style_int({"a": "7"}, "a", 1) == 7
    assert worker._style_int({"a": None}, "a", 4) == 4
    assert worker._style_int({"a": "x"}, "a", 9) == 9


def test_build_ass_force_style_positions_and_disabled_effects():
    """``_build_ass_force_style`` maps positions and disables outline/shadow."""
    top = worker._build_ass_force_style({"position": "top"})
    assert "Alignment=8" in top
    center = worker._build_ass_force_style({"position": "center"})
    assert "Alignment=5" in center
    disabled = worker._build_ass_force_style(
        {"outline_enabled": False, "shadow_enabled": False, "stroke_width": 5}
    )
    assert "Outline=0" in disabled
    assert "Shadow=0" in disabled
    # Non-dict style still produces a default style string.
    assert "Alignment=2" in worker._build_ass_force_style(None)


def test_parse_preview_seconds():
    """``_parse_preview_seconds`` parses positives and rejects non-positives."""
    assert worker._parse_preview_seconds("5") == 5
    assert worker._parse_preview_seconds(None) is None
    assert worker._parse_preview_seconds("0") is None
    assert worker._parse_preview_seconds(-2) is None
    assert worker._parse_preview_seconds("abc") is None


def test_calledprocess_stderr_text():
    """``_calledprocess_stderr_text`` decodes bytes and ignores other errors."""
    assert worker._calledprocess_stderr_text(ValueError("x")) == ""
    bytes_exc = subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"bad")
    assert worker._calledprocess_stderr_text(bytes_exc) == "bad"
    str_exc = subprocess.CalledProcessError(1, ["ffmpeg"])
    str_exc.stderr = "boom"
    assert worker._calledprocess_stderr_text(str_exc) == "boom"


def test_resolve_style_from_options_paths():
    """``_resolve_style_from_options`` honours explicit, preset, and default styles."""
    assert worker._resolve_style_from_options({"style": {"font": "X"}}) == {"font": "X"}
    preset = worker._resolve_style_from_options({"style_preset": "clean slate"})
    assert preset["font"] == "Inter"
    unknown = worker._resolve_style_from_options({"style_preset": "missing"})
    assert unknown["font"] == "Inter"  # default preset
    assert worker._resolve_style_from_options(None)["font"] == "Inter"


def test_collect_shorts_keywords_dedup_and_extra():
    """Prompt tokens (>=3 chars) and extra keywords are merged and de-duped."""
    keywords = worker._collect_shorts_keywords(
        "Big fun fun reveal", {"keywords": ["reveal", " ", "Bonus"]}
    )
    assert keywords == ["big", "fun", "reveal", "bonus"]


def test_parse_weight_overrides_legacy_and_invalid():
    """Legacy weight keys map to canonical names; invalid values are dropped."""
    overrides = worker._parse_weight_overrides(
        {
            "keyword_density_weight": "2.0",
            "segment_scoring_weights": {"base_score": "bad"},
        }
    )
    assert overrides["keyword_density"] == 2.0
    assert "base_score" not in overrides


def test_parse_weight_overrides_ignores_unknown_keys():
    """Unknown canonical keys are ignored entirely."""
    overrides = worker._parse_weight_overrides(
        {"segment_scoring_weights": {"not_a_weight": 1.0, "duration_bonus": 0.5}}
    )
    assert overrides == {"duration_bonus": 0.5}


def test_groq_resolve_model(monkeypatch):
    """Groq model resolves from opts, env, then the built-in default."""
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    assert worker._groq_resolve_model({"groq_model": "custom"}) == "custom"
    monkeypatch.setenv("GROQ_MODEL", "env-model")
    assert worker._groq_resolve_model({}) == "env-model"
    monkeypatch.setenv("GROQ_MODEL", "   ")
    assert worker._groq_resolve_model({}) == "llama3-8b-8192"


def test_groq_prerequisite_warning(monkeypatch):
    """Each unmet Groq prerequisite returns its own skip warning."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    assert "no prompt" in worker._groq_prerequisite_warning(
        prompt="", subtitle_asset_id="x"
    )
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    assert "offline" in worker._groq_prerequisite_warning(
        prompt="p", subtitle_asset_id="x"
    )
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    assert "no subtitle_asset_id" in worker._groq_prerequisite_warning(
        prompt="p", subtitle_asset_id=""
    )
    assert worker._groq_prerequisite_warning(prompt="p", subtitle_asset_id="x") is None


def test_publish_provider_from_step():
    """Publish provider is derived from the step type or payload provider."""
    assert worker._publish_provider_from_step("publish_youtube", {}) == "youtube"
    assert (
        worker._publish_provider_from_step("publish", {"provider": "TikTok"}) == "tiktok"
    )
    with pytest.raises(ValueError):
        worker._publish_provider_from_step("not_publish", {})
    with pytest.raises(ValueError):
        worker._publish_provider_from_step("publish_unknown", {})
