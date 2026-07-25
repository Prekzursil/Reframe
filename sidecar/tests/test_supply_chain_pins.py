"""WU-S10 (T4 supply chain) — pin/verify-before-exec gates on the install paths.

Three surfaces, all "an unverified artifact must never be EXECUTED":

* ``assets.manager.build_env_install_argvs`` — the env installer's UN-LOCKED
  fallback (no hashed lock staged) resolved from ambient indexes and was allowed
  to build **source distributions**, i.e. run an arbitrary ``setup.py`` /
  PEP-517 backend at install time. It now carries
  :data:`UNLOCKED_ENV_PIP_ARGS` (``--only-binary=:all:``) so only PREBUILT
  wheels are accepted on the unverified path — the same policy the hashed-lock
  path (:data:`HASHED_LOCK_PIP_ARGS`) already enforces.
* ``features.tts.chatterbox`` — the chatterbox env asset (torch + its full
  transitive closure) declared NO ``lock_file``, so the WU C4
  ``pip --require-hashes`` machinery could never engage for the ONE real
  ``installer="env"`` asset in the registry. It now declares the sibling hashed
  lock that ``runtime_setup.generate_hashed_lock`` produces.
* ``.github/workflows/quality.yml`` — the CI installer was fetched from the
  MUTABLE ``main`` branch and the scanner binary had no checksum at all.

The lockfile-mechanism tests live in ``test_env_lockfile.py``; this module only
covers the WU-S10 pinning deltas.
"""

from __future__ import annotations

import re
from pathlib import Path

from media_studio.assets import manifest
from media_studio.assets.manager import (
    GET_PIP_SHA256,
    HASHED_LOCK_PIP_ARGS,
    UNLOCKED_ENV_PIP_ARGS,
    AssetManager,
    build_env_install_argvs,
)
from media_studio.features.tts import chatterbox as cb

REPO_ROOT = Path(__file__).resolve().parents[2]
QUALITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "quality.yml"
EMBED_SETUP_PS1 = REPO_ROOT / "build" / "python-embed-setup.ps1"


def _recording_manager(root: Path, **kwargs: object) -> tuple[AssetManager, list[list[str]]]:
    """An AssetManager with get-pip pre-staged and a recording run_cmd (no pip)."""
    gp = root / "tools" / "get-pip.py"
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.write_text("# gp", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv, extra_env=None):  # noqa: ANN001, ANN202 - test seam
        calls.append(list(argv))
        return 0, ""

    mgr = AssetManager(root=root, **kwargs)  # type: ignore[arg-type]
    mgr._run_cmd = fake_run  # type: ignore[assignment]
    return mgr, calls


# --------------------------------------------------------------------------- #
# 1. the UN-LOCKED env install is wheels-only (no install-time code execution)
# --------------------------------------------------------------------------- #
class TestUnlockedEnvInstallIsWheelsOnly:
    def test_unlocked_pip_args_constant(self):
        # An sdist executes its build backend to produce a wheel; on the path
        # that has NO hash to verify, that is arbitrary code from an ambient
        # index. Refuse sdists outright.
        assert UNLOCKED_ENV_PIP_ARGS == ("--only-binary=:all:",)

    def test_unlocked_step2_carries_only_binary(self, tmp_path):
        steps = build_env_install_argvs("py", tmp_path / "gp.py", tmp_path / "env", ("numpy==2.5.0",))
        step2 = steps[1]["argv"]
        assert "--only-binary=:all:" in step2

    def test_unlocked_step2_still_installs_the_inline_pins(self, tmp_path):
        # Compat guard: hardening the fallback must not change WHAT it installs.
        steps = build_env_install_argvs("py", tmp_path / "gp.py", tmp_path / "env", ("numpy==2.5.0",))
        step2 = steps[1]["argv"]
        assert "numpy==2.5.0" in step2
        assert "--require-hashes" not in step2
        assert "-r" not in step2
        assert step2[1:4] == ["-m", "pip", "install"]

    def test_locked_step2_is_unchanged(self, tmp_path):
        # The hashed-lock path already refused sdists; it must not gain a
        # duplicate flag (pip would accept it, but the argv is a contract).
        lock = tmp_path / "env.lock.txt"
        steps = build_env_install_argvs("py", tmp_path / "gp.py", tmp_path / "env", ("numpy==2.5.0",), lock_file=lock)
        step2 = steps[1]["argv"]
        assert step2.count("--only-binary=:all:") == 1
        for flag in HASHED_LOCK_PIP_ARGS:
            assert flag in step2

    def test_install_env_runs_pip_wheels_only_without_a_lock(self, tmp_path):
        # End-to-end through _install_env with faked seams (no pip, no network).
        mgr, calls = _recording_manager(tmp_path / "root")
        entry = manifest.AssetEntry(
            name="s10-unlocked-env",
            kind="env",
            size_mb=1,
            dest="envs/s10-unlocked",
            installer="env",
            requirements=("numpy==2.5.0",),
        )
        mgr._install_env(entry, on_frac=lambda *_a: None, should_cancel=lambda: False)
        assert "--only-binary=:all:" in calls[1]
        assert "--require-hashes" not in calls[1]


# --------------------------------------------------------------------------- #
# 2. the chatterbox env asset DECLARES the hashed lock (C4 activation point)
# --------------------------------------------------------------------------- #
class TestChatterboxDeclaresHashedLock:
    def test_module_exports_the_lock_constant(self):
        assert Path(cb.CHATTERBOX_LOCK_FILE).name == "requirements-chatterbox.lock.txt"
        assert Path(cb.CHATTERBOX_LOCK_FILE).is_absolute()
        assert "CHATTERBOX_LOCK_FILE" in cb.__all__

    def test_registered_entry_declares_it(self):
        entry = manifest.get_asset(cb.CHATTERBOX_ENV_ASSET)
        assert entry is not None
        assert entry.lock_file == cb.CHATTERBOX_LOCK_FILE

    def test_declared_lock_is_the_runtime_setup_sibling(self):
        # PARITY with the repo's own convention: the same path
        # runtime_setup.bootstrap.hashed_lock_path() derives for the chatterbox
        # requirements file, so ONE generate_hashed_lock run serves the
        # first-run bootstrap AND the U4 env asset (no second staging location).
        from runtime_setup import bootstrap as bs

        assert Path(cb.CHATTERBOX_LOCK_FILE) == bs.hashed_lock_path(bs.CHATTERBOX_REQUIREMENTS)

    def test_staged_chatterbox_lock_drives_require_hashes(self, tmp_path):
        # The declared lock is an F1 build-prep artifact (real hashes need PyPI +
        # the cu128 index), so prove the WIRING with an identical entry whose
        # lock is staged in tmp: the chatterbox requirement set then installs
        # hash-verified end to end.
        lock = tmp_path / "requirements-chatterbox.lock.txt"
        lock.write_text(
            "--extra-index-url " + cb.TORCH_EXTRA_INDEX_URL + "\n"
            "chatterbox-tts==0.1.7 \\\n    --hash=sha256:" + "a" * 64 + "\n",
            encoding="utf-8",
        )
        mgr, calls = _recording_manager(tmp_path / "root", chatterbox_python=lambda: None, python_exe="py")
        entry = manifest.AssetEntry(
            name="s10-chatterbox-locked",
            kind="env",
            size_mb=1,
            dest="envs/s10-chatterbox",
            installer="env",
            requirements=cb.CHATTERBOX_REQUIREMENTS,
            python_kind="chatterbox",
            lock_file=str(lock),
        )
        mgr._install_env(entry, on_frac=lambda *_a: None, should_cancel=lambda: False)
        assert "--require-hashes" in calls[1]
        assert calls[1][-2:] == ["-r", str(lock)]


# --------------------------------------------------------------------------- #
# 3. CI tooling is fetched from IMMUTABLE refs / checksum-verified
# --------------------------------------------------------------------------- #
class TestQualityWorkflowPins:
    @staticmethod
    def _body() -> str:
        return QUALITY_WORKFLOW.read_text(encoding="utf-8")

    def test_opengrep_installer_is_not_fetched_from_a_mutable_branch(self):
        body = self._body()
        assert "opengrep/opengrep/main/install.sh" not in body
        assert "/refs/heads/" not in body

    def test_opengrep_installer_is_pinned_to_a_commit_sha(self):
        body = self._body()
        m = re.search(r"raw\.githubusercontent\.com/opengrep/opengrep/([^/]+)/install\.sh", body)
        assert m, "the opengrep installer URL is missing"
        assert re.fullmatch(r"[0-9a-f]{40}", m.group(1)), m.group(1)

    def test_osv_scanner_download_is_checksum_verified(self):
        body = self._body()
        assert "osv-scanner_linux_amd64" in body
        # a 64-hex digest fed to `sha256sum -c` guards the downloaded binary
        # BEFORE chmod +x / any invocation.
        assert re.search(r"\b[0-9a-f]{64}\b\s+/usr/local/bin/osv-scanner", body)
        assert "sha256sum -c" in body

    def test_checksum_check_precedes_chmod(self):
        body = self._body()
        assert body.index("sha256sum -c") < body.index("chmod +x /usr/local/bin/osv-scanner")


# --------------------------------------------------------------------------- #
# 4. build/python-embed-setup.ps1 — the SHA-256 pin is mandatory (fail closed)
# --------------------------------------------------------------------------- #
class TestEmbedSetupPinIsMandatory:
    @staticmethod
    def _body() -> str:
        """The script's CODE lines only — full-line ``#`` comments dropped.

        Measure the field, not the document: the header comment DESCRIBES the
        removed optional-verification shape, so a raw substring search matches
        the prose that documents the fix and reports the defect as still present
        (use-vs-mention). Only code may satisfy these assertions.
        """
        lines = EMBED_SETUP_PS1.read_text(encoding="utf-8").splitlines()
        return "\n".join(line for line in lines if not line.lstrip().startswith("#"))

    def test_no_call_site_passes_an_empty_pin(self):
        # The old shape — `Get-Download ... -ExpectedSha256 ''` for get-pip.py —
        # made verification optional at the call site.
        body = self._body()
        assert "-ExpectedSha256 ''" not in body
        assert '-ExpectedSha256 ""' not in body

    def test_missing_or_malformed_pin_is_refused(self):
        body = self._body()
        # gate helper is invoked BEFORE the request, and validates the shape
        assert "function Assert-Sha256Pin" in body
        assert "Assert-Sha256Pin -Url $Url" in body
        assert "refusing to download" in body
        assert "'^[0-9a-fA-F]{64}$'" in body

    def test_verification_is_unconditional(self):
        # The optional-verification tell: a mismatch check guarded by "is a pin
        # even set". It must be gone.
        body = self._body()
        assert "if ($ExpectedSha256 -and" not in body

    def test_get_pip_pin_matches_the_runtime_constant(self):
        # The build script and the runtime enforce the SAME get-pip.py digest;
        # a copy that silently drifts would let the packaged bootstrap and the
        # staged file disagree. Keep them in lockstep.
        body = self._body()
        assert f"$ExpectedGetPipSha256 = '{GET_PIP_SHA256}'" in body

    def test_record_hashes_mode_exists_and_stages_nothing(self):
        # The fail-closed bootstrap path: how an operator obtains a pin they do
        # not have yet, without ever producing a build from unverified bytes.
        body = self._body()
        assert "[switch]$RecordHashes" in body
        assert "staged NOTHING by design" in body
