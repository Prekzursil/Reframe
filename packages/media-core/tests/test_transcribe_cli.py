"""Coverage for the transcribe CLI entry point and the noop helper."""

from __future__ import annotations

import json
import sys
import types

import pytest

from media_core.transcribe import TranscriptionConfig, transcribe_noop
from media_core.transcribe import __main__ as cli


def test_transcribe_noop_uses_filename_and_config(tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")
    config = TranscriptionConfig(model="custom-model", language="en")

    result = transcribe_noop(media, config)
    assert result.text == "clip.wav"
    assert result.model == "custom-model"
    assert result.language == "en"
    assert [w.text for w in result.words] == ["clip.wav"]


def test_transcribe_noop_without_config(tmp_path):
    media = tmp_path / "name.wav"
    media.write_bytes(b"audio")
    result = transcribe_noop(media)
    assert result.model == "noop"
    assert result.language is None


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "input.wav"])
    args = cli.parse_args()
    assert args.input == "input.wav"
    assert args.backend == "noop"
    assert args.model == "whisper-1"


def test_main_unsupported_backend(monkeypatch, capsys, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")
    monkeypatch.setattr(sys, "argv", ["prog", str(media), "--backend", "does-not-exist"])

    rc = cli.main()
    assert rc == 1
    assert "Unsupported backend" in capsys.readouterr().err


def test_main_invalid_input_path(monkeypatch, capsys, tmp_path):
    missing = tmp_path / "missing.wav"
    monkeypatch.setattr(sys, "argv", ["prog", str(missing), "--backend", "noop"])

    rc = cli.main()
    assert rc == 1
    assert "Invalid input path" in capsys.readouterr().err


def test_main_noop_backend_success(monkeypatch, capsys, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")
    monkeypatch.setattr(sys, "argv", ["prog", str(media), "--backend", "noop"])

    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["text"] == "clip.wav"


def test_main_dispatches_to_each_backend(monkeypatch, capsys, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")

    from media_core.transcribe.models import TranscriptionResult, Word

    def fake_result(*_args, **_kwargs):
        return TranscriptionResult.from_iterable([Word(text="ok", start=0.0, end=1.0)])

    monkeypatch.setattr(cli, "transcribe_openai_file", fake_result)
    monkeypatch.setattr(cli, "transcribe_faster_whisper", fake_result)
    monkeypatch.setattr(cli, "transcribe_whisper_cpp", fake_result)
    monkeypatch.setattr(cli, "transcribe_whisper_timestamped", fake_result)

    for backend in ("openai_whisper", "faster_whisper", "whisper_cpp", "whisper_timestamped", "whisperx"):
        monkeypatch.setattr(sys, "argv", ["prog", str(media), "--backend", backend])
        rc = cli.main()
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["words"][0]["text"] == "ok"


def test_main_handles_backend_failure(monkeypatch, capsys, tmp_path):
    media = tmp_path / "clip.wav"
    media.write_bytes(b"audio")

    def boom(*_args, **_kwargs):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(cli, "transcribe_faster_whisper", boom)
    monkeypatch.setattr(sys, "argv", ["prog", str(media), "--backend", "faster_whisper"])

    rc = cli.main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "Transcription failed" in err
    assert "noop" in err  # tip mentions the offline smoke-test backend


def test_module_entrypoint_runs_main(monkeypatch):
    """Running ``python -m media_core.transcribe`` calls main() and exits.

    We import the module fresh under __main__ semantics by invoking runpy so the
    ``if __name__ == "__main__"`` guard line is executed.
    """
    import runpy

    monkeypatch.setattr(sys, "argv", ["prog", "missing-file.wav", "--backend", "noop"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("media_core.transcribe.__main__", run_name="__main__")
    # Invalid input path -> exit code 1.
    assert exc.value.code == 1
