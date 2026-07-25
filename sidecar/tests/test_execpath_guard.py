"""Renderer-writable executable/script-path guard — audit C1/C2/C3 + T2.

THE CHAIN THIS CLOSES (verified by execution before this test was written):
  1. ``app/main/ipc.ts`` forwards ANY renderer-supplied method to the sidecar with no
     allowlist, no sender check and no per-method schema, so an untrusted renderer (XSS or a
     compromised dependency) can call ``settings.set``.
  2. ``SettingsStore.set`` was a shallow merge with NO key validation, so
     ``settings.set({"ffmpegPath": r"C:\\attacker\\evil.exe"})`` PERSISTED verbatim.
  3. ``ffmpeg.resolve_binary`` checks ``settings.ffmpegPath`` FIRST (ahead of the env,
     bundled and PATH branches) and used it unvalidated -> ``sp.is_file()`` -> ``return str(sp)``.
  4. Any subsequent media operation spawns that path => native code execution outside the
     Electron sandbox, with the user's privileges.

WHY REFUSING THE WRITE IS THE REAL CONTROL (and canonicalisation is not):
``pathsafe.ensure_within(value)`` called with NO extra parts is a *canonicaliser*, not a
containment check -- ``target == base_real`` so it always returns. An attacker-supplied
absolute path canonicalises perfectly happily. Therefore the only control that actually breaks
the chain is refusing the renderer-originated WRITE of an executable/script-path key.

WHY THIS COSTS NO FEATURE (verified, not assumed): the renderer never writes these keys. A scan
of ``app/renderer`` for every exec-path key found ZERO writes; the single ``ffmpegPath``
reference is ``ShortMaker.test.tsx`` asserting that ``readBrandSettings`` FILTERS it out. Power
users keep the main-owned, non-renderer-reachable escape hatches: the ``MEDIA_STUDIO_FFMPEG`` /
``MEDIA_STUDIO_FFPROBE`` env overrides, the bundled binaries, and PATH.

COMPAT REQUIREMENT PROVEN BY EXECUTION: ``ffmpegPath`` IS in ``DEFAULT_SETTINGS`` and IS one of
the 20 top-level keys ``get()`` returns, and ``set(get())`` round-trips today. So the guard must
refuse only a value that would CHANGE the stored path; an identical (no-op) value must still be
accepted, or the UI's legitimate get -> modify -> set round-trip breaks.
"""

from __future__ import annotations

import pytest
from media_studio.settings_store import (
    DEFAULT_SETTINGS,
    EXECUTABLE_SETTING_KEYS,
    ExecutablePathWriteError,
    SettingsStore,
)

ATTACKER = r"C:\attacker\evil.exe"


@pytest.fixture()
def store(tmp_path):
    """A SettingsStore backed by a throwaway config file."""
    return SettingsStore(tmp_path / "settings.json")


class TestExecutableKeyInventory:
    """The guarded set must actually cover the keys that select a native binary."""

    def test_covers_every_known_executable_key(self):
        # Each of these is documented in the sidecar as selecting an executable or a
        # script that gets spawned: ffmpeg.py, reframe.py (wsl bash), tools_resolver.py,
        # caption_remotion.py.
        for key in (
            "ffmpegPath",
            "ffprobePath",
            "verthorScript",
            "nodeExePath",
            "renderJsPath",
            "chromeHeadlessShellPath",
        ):
            assert key in EXECUTABLE_SETTING_KEYS, key

    def test_is_immutable(self):
        assert isinstance(EXECUTABLE_SETTING_KEYS, frozenset)


class TestExecPathWriteRefused:
    """The primary control: an RPC write that CHANGES an exec path is refused."""

    def test_refuses_to_change_ffmpeg_path(self, store):
        """THE VULNERABILITY. Before the guard this persisted the attacker path."""
        with pytest.raises(ExecutablePathWriteError):
            store.set({"ffmpegPath": ATTACKER})

    def test_refused_write_does_not_mutate_the_store(self, store):
        before = store.get().get("ffmpegPath")
        with pytest.raises(ExecutablePathWriteError):
            store.set({"ffmpegPath": ATTACKER})
        assert store.get().get("ffmpegPath") == before
        assert store.get().get("ffmpegPath") != ATTACKER

    @pytest.mark.parametrize("key", sorted(EXECUTABLE_SETTING_KEYS))
    def test_refuses_every_guarded_key(self, store, key):
        with pytest.raises(ExecutablePathWriteError):
            store.set({key: ATTACKER})

    def test_error_names_the_key(self, store):
        """The refusal must be diagnosable — it names the key it rejected."""
        with pytest.raises(ExecutablePathWriteError) as excinfo:
            store.set({"verthorScript": ATTACKER})
        assert "verthorScript" in str(excinfo.value)

    def test_refuses_when_mixed_with_legitimate_keys(self, store):
        """A guarded key smuggled alongside innocuous ones is still refused, atomically."""
        with pytest.raises(ExecutablePathWriteError):
            store.set({"lastOpenedVideoId": "vid-1", "ffmpegPath": ATTACKER})
        # atomic: the innocuous key must NOT have been written either
        assert store.get().get("lastOpenedVideoId") == DEFAULT_SETTINGS["lastOpenedVideoId"]


class TestCompatibilityPreserved:
    """The guard must not break the UI's legitimate read-modify-write cycle."""

    def test_allows_noop_identical_value(self, store):
        """Writing back the value already stored is a no-op, not an attack."""
        current = store.get().get("ffmpegPath")
        merged = store.set({"ffmpegPath": current})
        assert merged.get("ffmpegPath") == current

    def test_full_get_set_round_trip_still_works(self, store):
        """The exact pattern a settings UI performs: set(get())."""
        snapshot = dict(store.get())
        merged = store.set(snapshot)
        assert merged.get("ffmpegPath") == snapshot.get("ffmpegPath")

    def test_round_trip_after_a_legitimate_edit(self, store):
        snapshot = dict(store.get())
        snapshot["lastOpenedVideoId"] = "vid-42"
        merged = store.set(snapshot)
        assert merged["lastOpenedVideoId"] == "vid-42"

    def test_non_exec_keys_still_writable(self, store):
        merged = store.set({"lastOpenedVideoId": "vid-7"})
        assert merged["lastOpenedVideoId"] == "vid-7"

    def test_absent_key_is_not_refused(self, store):
        """A payload with no guarded key at all passes straight through."""
        merged = store.set({"activePreset": "punchy"})
        assert merged["activePreset"] == "punchy"

    def test_non_dict_still_rejected_with_value_error(self, store):
        """The pre-existing contract is preserved (not shadowed by the new guard)."""
        with pytest.raises(ValueError):
            store.set(["not", "a", "dict"])  # type: ignore[arg-type]


class TestGuardIsTypedForRpc:
    """The refusal must surface as an RPC error, not crash the sidecar."""

    def test_is_a_value_error_subclass(self):
        # Mirrors UnsafeConfigDirError: existing broad `except ValueError` handlers in the
        # protocol layer turn this into a clean JSON-RPC error instead of a 500.
        assert issubclass(ExecutablePathWriteError, ValueError)
