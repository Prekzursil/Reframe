"""E2E: the whisper offline-resolution mechanism, against the REAL huggingface_hub.

This is the BOTH-STATES proof behind ``transcribe.resolve_model_source``. The
blocking gate cannot host it: ``huggingface_hub`` is deliberately not installed
there (quality.yml installs the sidecar with ``--no-deps``), so an unconditional
import would break CI. The e2e leg DOES install it (e2e.yml), and the unit suite
covers the same resolution logic hermetically in ``tests/test_transcribe.py``.

No network is involved: every call passes ``local_files_only=True``, so this is a
pure filesystem + cache-layout assertion.

WHAT IT PROVES
--------------
``assets.ensure`` installs the whisper snapshot by 40-hex COMMIT PIN
(``manager._install_hf`` -> ``snapshot_download(revision=<sha>)``).
huggingface_hub writes ``refs/<revision>`` only when the requested revision
differs from the resolved commit hash
(``file_download._cache_commit_hash_for_specific_revision``), so a pin-installed
repo has NO ``refs/main``.

* BROKEN state — what ``WhisperModel("large-v3-turbo")`` does: faster-whisper
  calls ``snapshot_download(repo)`` with the default revision ``"main"``. Offline
  that resolves only from a commit-hash revision or an existing ``refs/<rev>``,
  so it raises ``LocalEntryNotFoundError`` **even though the weights are on
  disk**. A probe that did not fire here would be measuring nothing.
* FIXED state — asking for the pin, or handing over the snapshot directory,
  resolves with no network.
"""

from __future__ import annotations

import pytest
from media_studio.assets import manifest
from media_studio.features import transcribe

pytestmark = pytest.mark.e2e


def _pin_shaped_cache(root, repo: str, revision: str):
    """Exactly the layout ``snapshot_download(revision=<pin>)`` leaves behind.

    DELIBERATELY a second, independent copy of the same helper in
    ``tests/test_transcribe.py`` rather than an import. The unit suite's value
    rests on that hand-built layout being the real one; if both suites read the
    same helper, a wrong layout would be wrong in both and this file would stop
    being a check on the unit file's premise.
    """
    snap = root / ("models--" + repo.replace("/", "--")) / "snapshots" / revision
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"ct2-weights")
    (snap / "config.json").write_text("{}")
    (snap / "tokenizer.json").write_text("{}")
    return snap


def _whisper_pin() -> tuple[str, str]:
    entry = manifest.get_asset(manifest.WHISPER_ASSET_NAME)
    assert entry is not None, "the whisper asset must be registered"
    assert entry.hf_repo and entry.hf_revision
    return entry.hf_repo, entry.hf_revision


# huggingface_hub snapshots ``HF_HUB_CACHE`` into ``constants`` at IMPORT time, so
# monkeypatching the env after import does NOT redirect it — measured: a run that
# only set the env var read the author's real D: cache and the "broken state"
# probe silently passed. Every call below therefore passes ``cache_dir=`` explicitly.
# (``transcribe.default_snapshot_locator`` reads the env per call, which is why the
# ``ours`` side of the comparison is env-driven.)


def test_bare_model_id_cannot_resolve_a_pin_installed_cache_offline(tmp_path):
    """BROKEN state: the revision faster-whisper asks for is unresolvable offline."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    repo, revision = _whisper_pin()
    snap = _pin_shaped_cache(tmp_path, repo, revision)
    assert not (snap.parent.parent / "refs").exists()

    # The exact call shape faster_whisper.utils.download_model makes: no revision.
    with pytest.raises(LocalEntryNotFoundError):
        snapshot_download(repo, cache_dir=str(tmp_path), local_files_only=True)
    # And the explicit default it stands in for.
    with pytest.raises(LocalEntryNotFoundError):
        snapshot_download(repo, revision="main", cache_dir=str(tmp_path), local_files_only=True)


def test_the_pinned_revision_resolves_the_same_cache_offline(tmp_path):
    """FIXED state: same bytes, same offline mode, resolvable via the pin."""
    from huggingface_hub import snapshot_download

    repo, revision = _whisper_pin()
    snap = _pin_shaped_cache(tmp_path, repo, revision)

    resolved = snapshot_download(repo, revision=revision, cache_dir=str(tmp_path), local_files_only=True)
    assert (type(snap)(resolved)).resolve() == snap.resolve()


def test_resolve_model_source_agrees_with_huggingface_hub(tmp_path, monkeypatch):
    """Our filesystem locator returns the SAME dir huggingface_hub resolves.

    This is what makes the hermetic unit tests trustworthy: the layout they
    hand-build is the layout the real library reads.
    """
    from huggingface_hub import snapshot_download

    repo, revision = _whisper_pin()
    _pin_shaped_cache(tmp_path, repo, revision)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))

    ours = transcribe.resolve_model_source(manifest.WHISPER_MODEL_ID)
    theirs = snapshot_download(repo, revision=revision, cache_dir=str(tmp_path), local_files_only=True)
    assert ours != manifest.WHISPER_MODEL_ID  # not the bare id
    assert (type(tmp_path)(ours)).resolve() == (type(tmp_path)(theirs)).resolve()
