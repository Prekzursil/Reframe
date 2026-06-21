"""Tests for media_studio.features.offline — the enforced OFFLINE switch.

Pure logic: no network, no heavy imports. Covers the setting/env precedence, the
typed refusal, and the env-hardening copy.
"""

from __future__ import annotations

import pytest
from media_studio.features import offline
from media_studio.protocol import ErrorCode


class TestIsOffline:
    def test_setting_true_is_authoritative(self):
        assert offline.is_offline({"offline": True}) is True

    def test_setting_false_overrides_env(self):
        # An explicit offline=False wins even if the env says offline.
        assert offline.is_offline({"offline": False}, env={"MEDIA_STUDIO_OFFLINE": "1"}) is False

    def test_env_override_when_setting_absent(self):
        assert offline.is_offline({}, env={"MEDIA_STUDIO_OFFLINE": "1"}) is True
        assert offline.is_offline({}, env={"MEDIA_STUDIO_OFFLINE": "yes"}) is True
        assert offline.is_offline({}, env={"MEDIA_STUDIO_OFFLINE": "0"}) is False

    def test_default_online(self):
        assert offline.is_offline({}, env={}) is False
        assert offline.is_offline(None, env={}) is False

    @pytest.mark.parametrize(
        "value,expected",
        [(1, True), (0, False), ("true", True), ("ON", True), ("nope", False), (None, False)],
    )
    def test_truthy_variants(self, value, expected):
        assert offline.is_offline({"offline": value}) is expected


class TestGuardNetwork:
    def test_raises_typed_offline_error_when_offline(self):
        with pytest.raises(offline.OfflineError) as exc:
            offline.guard_network({"offline": True}, "downloading a model")
        assert exc.value.code == ErrorCode.INVALID_PARAMS
        assert "downloading a model" in str(exc.value)
        assert "Offline mode is on" in str(exc.value)
        assert "System Health" in str(exc.value)  # surfaces the FIX

    def test_noop_when_online(self):
        # No exception -> returns None.
        assert offline.guard_network({"offline": False}, "anything") is None

    def test_env_forced_offline_raises(self):
        with pytest.raises(offline.OfflineError):
            offline.guard_network({}, "fetching", env={"MEDIA_STUDIO_OFFLINE": "1"})


class TestEnforceOfflineEnv:
    def test_sets_sentinels_when_offline(self):
        out = offline.enforce_offline_env({"PATH": "/x"}, {"offline": True})
        assert out["HF_HUB_OFFLINE"] == "1"
        assert out["TRANSFORMERS_OFFLINE"] == "1"
        assert out["PATH"] == "/x"  # preserved

    def test_copy_unchanged_when_online(self):
        base = {"PATH": "/x"}
        out = offline.enforce_offline_env(base, {"offline": False})
        assert "HF_HUB_OFFLINE" not in out
        assert out is not base  # always a copy

    def test_offline_via_env_inside_base(self):
        out = offline.enforce_offline_env({"MEDIA_STUDIO_OFFLINE": "1"}, {})
        assert out["HF_HUB_OFFLINE"] == "1"
