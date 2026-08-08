"""Tests for the voice catalog + sample store (features/tts/voices.py, T2)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from media_studio.features.tts import register as tts_register
from media_studio.features.tts import voices as v
from media_studio.features.tts.engine import TtsEngine, TtsError
from media_studio.protocol import RpcContext, RpcError


def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


@pytest.fixture()
def store(tmp_path):
    return v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 3.5)


@pytest.fixture()
def sample_file(tmp_path):
    f = tmp_path / "my voice.wav"
    f.write_bytes(b"RIFF0000WAVEfake")
    return f


# --------------------------------------------------------------------------- #
# VoiceStore
# --------------------------------------------------------------------------- #
class TestVoiceStore:
    def test_add_copies_and_persists(self, store, sample_file, tmp_path):
        sample = store.add(str(sample_file), consent_attested=True)
        # A3 VoiceSample shape (frozen field names) + the WU-A2 consent record
        assert set(sample) == {
            "id",
            "name",
            "path",
            "durationSec",
            "consentAttested",
            "consentAt",
            "consentNote",
        }
        assert sample["name"] == "my voice"
        assert sample["durationSec"] == 3.5
        copied = Path(sample["path"])
        assert copied.is_file()
        assert copied.parent == tmp_path / "voices"
        # persists across a NEW store instance (round-trip)
        again = v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0)
        assert [s["id"] for s in again.list()] == [sample["id"]]
        assert again.get(sample["id"])["path"] == sample["path"]

    def test_add_missing_file_raises(self, store, tmp_path):
        with pytest.raises(TtsError, match="not found"):
            store.add(str(tmp_path / "ghost.wav"), consent_attested=True)

    def test_add_unsupported_format_raises(self, store, tmp_path):
        bad = tmp_path / "notes.txt"
        bad.write_text("hi", encoding="utf-8")
        with pytest.raises(TtsError, match="unsupported"):
            store.add(str(bad), consent_attested=True)

    def test_probe_failure_stores_zero(self, tmp_path, sample_file):
        def boom(path):
            raise RuntimeError("no ffprobe")

        store = v.VoiceStore(tmp_path / "voices", duration_probe=boom)
        assert store.add(str(sample_file), consent_attested=True)["durationSec"] == 0.0

    def test_corrupt_index_starts_empty(self, tmp_path):
        d = tmp_path / "voices"
        d.mkdir()
        (d / "voices.json").write_text("{broken", encoding="utf-8")
        assert v.VoiceStore(d, duration_probe=lambda p: 0.0).list() == []

    def test_get_unknown_returns_none(self, store):
        assert store.get("nope") is None

    def test_get_skips_non_matching_rows(self, store, tmp_path):
        """get() iterates past non-matching rows to find the target (121->120)."""
        first = tmp_path / "first.wav"
        first.write_bytes(b"RIFF0000WAVEa")
        second = tmp_path / "second.wav"
        second.write_bytes(b"RIFF0000WAVEb")
        s1 = store.add(str(first), consent_attested=True)
        s2 = store.add(str(second), consent_attested=True)
        # the SECOND id forces the loop to skip s1 before matching s2.
        assert s1["id"] != s2["id"]
        assert store.get(s2["id"])["path"] == s2["path"]


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #
class StaticEngine(TtsEngine):
    id = "kokoro"
    label = "fake"

    def __init__(self, rows):
        self._rows = rows

    def synth(self, cues, voice, lang, out_wav, *, rate=1.0):
        raise AssertionError("catalog handlers must never synthesize")

    def voices(self):
        return list(self._rows)


class TestHandlers:
    def test_voices_aggregates_engines_and_samples(self, store, sample_file):
        sample = store.add(str(sample_file), consent_attested=True)
        rows = [{"id": "af_x", "engine": "kokoro", "lang": "en-us", "name": "X"}]
        handler = v.make_voices_handler([StaticEngine(rows)], store)
        result = handler({}, ctx())
        ids = [(row["engine"], row["id"]) for row in result["voices"]]
        assert ("kokoro", "af_x") in ids
        assert ("chatterbox", sample["id"]) in ids
        for row in result["voices"]:
            assert set(row) == {"id", "engine", "lang", "name"}

    def test_one_failing_engine_does_not_hide_the_rest(self, store):
        class BoomEngine(TtsEngine):
            id = "boom"
            label = "boom"

            def synth(self, cues, voice, lang, out_wav, *, rate=1.0):  # pragma: no cover - unused
                raise AssertionError("never synthesizes")

            def voices(self):
                raise RuntimeError("catalog backend down")

        good_rows = [{"id": "af_x", "engine": "kokoro", "lang": "en-us", "name": "X"}]
        handler = v.make_voices_handler([BoomEngine(), StaticEngine(good_rows)], store)
        result = handler({}, ctx())
        # the broken engine is skipped; the good engine's catalog still surfaces
        ids = [row["id"] for row in result["voices"]]
        assert "af_x" in ids

    def test_sample_add_handler_shape_and_validation(self, store, sample_file):
        handler = v.make_sample_add_handler(store)
        result = handler({"path": str(sample_file), "consentAttested": True}, ctx())
        assert set(result) == {"sample"}
        assert set(result["sample"]) == {
            "id",
            "name",
            "path",
            "durationSec",
            "consentAttested",
            "consentAt",
            "consentNote",
        }
        with pytest.raises(RpcError):
            handler({}, ctx())
        with pytest.raises(RpcError):
            handler({"path": "C:/nope.wav", "consentAttested": True}, ctx())


# --------------------------------------------------------------------------- #
# the package register() (frozen A2 method names)
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_registers_exactly_the_a2_names(self, tmp_path):
        registered = {}

        def fake_reg(name, handler):
            registered[name] = handler

        service = tts_register(
            resolver=lambda vid: None,
            load_track=lambda vid, tid: {},
            audio_tracks=object(),
            voice_store=v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0),
            register_fn=fake_reg,
        )
        assert set(registered) == {"tts.voices", "tts.sample.add", "tts.dub.start"}
        assert service is not None

    def test_registered_voices_handler_serves_all_three_engines(self, tmp_path):
        registered = {}
        tts_register(
            resolver=lambda vid: None,
            load_track=lambda vid, tid: {},
            audio_tracks=object(),
            voice_store=v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0),
            register_fn=lambda name, h: registered.__setitem__(name, h),
        )
        result = registered["tts.voices"]({}, ctx())
        engines = {row["engine"] for row in result["voices"]}
        # kokoro + edgetts ship static catalogs; chatterbox rows appear once
        # samples exist (none here).
        assert {"kokoro", "edgetts"} <= engines


# --------------------------------------------------------------------------- #
# WU-A2 — the voice-clone CONSENT gate (docs/plans/v1.5/flagship-lip-sync-dub.md
# §4 WU-A2 + §5.1, the legal keystone). Mirrors models/consent.py's typed-refusal
# / default-deny idiom for the SEPARATE voice-clone act.
# --------------------------------------------------------------------------- #
FROZEN_ISO = "2026-08-08T10:20:30Z"


@pytest.fixture()
def consenting_store(tmp_path):
    """A store with a FROZEN consent clock so ``consentAt`` is deterministic."""
    return v.VoiceStore(
        tmp_path / "voices",
        duration_probe=lambda p: 3.5,
        now=lambda: FROZEN_ISO,
    )


class TestConsentPredicate:
    @pytest.mark.parametrize(
        "row",
        [
            None,
            {},
            "not-a-mapping",
            {"consentAttested": False},
            {"consentAttested": None},
            # default-deny: a TRUTHY non-True value is NOT an attestation
            {"consentAttested": "true"},
            {"consentAttested": 1},
        ],
    )
    def test_default_deny(self, row):
        assert v.consent_attested(row) is False

    def test_explicit_true_is_the_only_grant(self):
        assert v.consent_attested({"consentAttested": True}) is True

    def test_require_consent_raises_typed_error_naming_the_sample(self):
        with pytest.raises(v.VoiceConsentError) as excinfo:
            v.require_consent({"consentAttested": False}, "abc123")
        assert "abc123" in str(excinfo.value)
        assert excinfo.value.sample_id == "abc123"

    def test_require_consent_without_an_id_still_refuses(self):
        with pytest.raises(v.VoiceConsentError) as excinfo:
            v.require_consent(None)
        assert excinfo.value.sample_id is None
        assert "consent" in str(excinfo.value).lower()

    def test_require_consent_passes_on_an_attested_row(self):
        assert v.require_consent({"consentAttested": True}, "ok") is None

    def test_is_a_tts_error_so_rpc_boundaries_convert_it(self):
        assert issubclass(v.VoiceConsentError, TtsError)


class TestStoreConsentGate:
    def test_add_without_attestation_refuses_and_stores_NOTHING(self, consenting_store, sample_file, tmp_path):
        """The gate is real: no file is copied and no index row is written."""
        with pytest.raises(v.VoiceConsentError):
            consenting_store.add(str(sample_file))
        assert consenting_store.list() == []
        voices_dir = tmp_path / "voices"
        assert not voices_dir.exists() or list(voices_dir.iterdir()) == []

    def test_consent_is_checked_before_ANY_filesystem_touch(self, consenting_store, tmp_path):
        """A missing path + no consent reports CONSENT, not 'not found' (deny-first)."""
        with pytest.raises(v.VoiceConsentError):
            consenting_store.add(str(tmp_path / "ghost.wav"))

    def test_add_with_attestation_persists_the_consent_record(self, consenting_store, sample_file, tmp_path):
        sample = consenting_store.add(
            str(sample_file),
            consent_attested=True,
            consent_note="signed release 2026-08-01",
        )
        assert set(sample) == {
            "id",
            "name",
            "path",
            "durationSec",
            "consentAttested",
            "consentAt",
            "consentNote",
        }
        assert sample["consentAttested"] is True
        assert sample["consentAt"] == FROZEN_ISO
        assert sample["consentNote"] == "signed release 2026-08-01"
        # the record survives a round-trip through voices.json
        again = v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0)
        stored = again.get(sample["id"])
        assert stored["consentAttested"] is True
        assert stored["consentAt"] == FROZEN_ISO
        assert stored["consentNote"] == "signed release 2026-08-01"

    @pytest.mark.parametrize("note", [None, "", "   ", 42])
    def test_blank_or_non_string_note_normalizes_to_None(self, consenting_store, sample_file, note):
        sample = consenting_store.add(str(sample_file), consent_attested=True, consent_note=note)
        assert sample["consentNote"] is None

    def test_default_clock_emits_an_iso8601_utc_stamp(self, tmp_path, sample_file):
        store = v.VoiceStore(tmp_path / "voices", duration_probe=lambda p: 0.0)
        stamp = store.add(str(sample_file), consent_attested=True)["consentAt"]
        # YYYY-MM-DDTHH:MM:SSZ — UTC, no local-time ambiguity in a legal record
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp)


class TestLegacyRowBackfill:
    def test_normalize_backfills_a_pre_consent_row_as_NOT_attested(self):
        row = v.normalize_sample({"id": "old", "name": "n", "path": "p", "durationSec": 1.0})
        assert row["consentAttested"] is False
        assert row["consentAt"] is None
        assert row["consentNote"] is None

    def test_normalize_preserves_a_stored_consent_record(self):
        row = v.normalize_sample(
            {
                "id": "new",
                "name": "n",
                "path": "p",
                "durationSec": 1.0,
                "consentAttested": True,
                "consentAt": FROZEN_ISO,
                "consentNote": "note",
            }
        )
        assert (row["consentAttested"], row["consentAt"], row["consentNote"]) == (True, FROZEN_ISO, "note")

    def test_normalize_rejects_a_non_string_consentAt(self):
        row = v.normalize_sample({"id": "x", "consentAttested": True, "consentAt": 1723106430})
        assert row["consentAt"] is None

    def test_a_legacy_row_on_disk_is_read_back_as_unattested(self, tmp_path):
        d = tmp_path / "voices"
        d.mkdir()
        (d / "voices.json").write_text(
            '{"version": 1, "samples": [{"id": "old", "name": "n", "path": "p", "durationSec": 2.0}]}',
            encoding="utf-8",
        )
        store = v.VoiceStore(d, duration_probe=lambda p: 0.0)
        assert store.get("old")["consentAttested"] is False


class TestCatalogMarksUnattestedSamples:
    def test_attested_and_legacy_rows_are_labelled_differently(self):
        rows = v.samples_as_voices(
            [
                {"id": "a", "name": "Ann", "path": "p", "durationSec": 1.0, "consentAttested": True},
                {"id": "b", "name": "Bob", "path": "p", "durationSec": 1.0, "consentAttested": False},
            ]
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id["a"]["name"] == "Ann (cloned sample)"
        assert "consent required" in by_id["b"]["name"]
        # the A2 Voice shape stays FROZEN at exactly four keys
        for row in rows:
            assert set(row) == {"id", "engine", "lang", "name"}


class TestSampleAddHandlerConsent:
    @pytest.mark.parametrize("attested", [None, False, "true", 1])
    def test_add_without_a_true_attestation_is_refused(self, consenting_store, sample_file, attested):
        handler = v.make_sample_add_handler(consenting_store)
        params = {"path": str(sample_file)}
        if attested is not None:
            params["consentAttested"] = attested
        with pytest.raises(RpcError, match="consentAttested"):
            handler(params, ctx())
        assert consenting_store.list() == []

    def test_add_with_attestation_returns_the_consent_record(self, consenting_store, sample_file):
        handler = v.make_sample_add_handler(consenting_store)
        result = handler(
            {
                "path": str(sample_file),
                "name": "Ann",
                "consentAttested": True,
                "consentNote": "written permission on file",
            },
            ctx(),
        )
        sample = result["sample"]
        assert sample["name"] == "Ann"
        assert sample["consentAttested"] is True
        assert sample["consentAt"] == FROZEN_ISO
        assert sample["consentNote"] == "written permission on file"

    def test_a_non_string_note_is_dropped_not_rejected(self, consenting_store, sample_file):
        handler = v.make_sample_add_handler(consenting_store)
        result = handler(
            {"path": str(sample_file), "consentAttested": True, "consentNote": 7},
            ctx(),
        )
        assert result["sample"]["consentNote"] is None

    def test_the_path_check_still_runs_first(self, consenting_store):
        handler = v.make_sample_add_handler(consenting_store)
        with pytest.raises(RpcError, match="path"):
            handler({"consentAttested": True}, ctx())
