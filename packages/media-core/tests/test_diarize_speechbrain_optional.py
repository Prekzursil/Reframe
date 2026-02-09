import importlib.util

import pytest

from media_core.diarize import DiarizationBackend, DiarizationConfig, diarize_audio


def test_speechbrain_backend_requires_optional_deps(tmp_path):
    if importlib.util.find_spec("speechbrain") is not None:
        pytest.skip("speechbrain is installed; this test targets the optional-deps error path.")

    fake_audio = tmp_path / "audio.wav"
    fake_audio.write_bytes(b"not-a-real-wav")

    config = DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN, model="speechbrain/spkrec-ecapa-voxceleb")
    with pytest.raises(RuntimeError, match=r"speechbrain diarization backend selected"):
        diarize_audio(fake_audio, config)

