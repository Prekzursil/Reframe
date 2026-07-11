"""Fixer sidecar-runtime-0 — verified-finding regression tests for
``runtime_setup.bootstrap``.

Covers three VERIFIED findings against the first-run bootstrap:

  1. bootstrap's ``AssetManager`` was built settings-blind (``{}``), so on a
     re-bootstrap/repair a user's ``offline=true`` consent was bypassed and
     custom model-path detect probes were ignored — now the real persisted
     ``SettingsStore`` is threaded into both manager constructions.
  2. the get-pip.py fallback was downloaded-then-executed with NO sha256 check,
     and its unverified bytes poisoned the shared ``<root>/tools`` cache — now
     every return path of ``ensure_get_pip`` is sha256-verified (F3c).
  3. on a read-only install dir the ``._pth`` write is skipped, and step-2's
     ``python -m pip`` then died with "No module named pip" under the
     embeddable's isolated mode — step 2 now runs pip via a ``-c`` prelude that
     inserts the env dir onto ``sys.path`` at runtime (needsRealIntegration:
     only a real embeddable on a read-only dir can prove the runtime behaviour;
     these tests pin the generated argv + prove the prelude is valid Python).

NO real pip, NO network, NO subprocess: seams are faked, the settings store is
pointed at a tmp dir via ``MEDIA_STUDIO_CONFIG_DIR``.
"""

from __future__ import annotations

import hashlib
import io
import json

import pytest
from media_studio.assets import manifest
from media_studio.assets.manager import GET_PIP_SHA256
from media_studio.features.offline import OfflineError
from runtime_setup import bootstrap as bs


class _FakeResp(io.BytesIO):
    """A urlopen()-style context-manager response over in-memory bytes."""

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


# --------------------------------------------------------------------------- #
# Finding 1 — bootstrap's AssetManager is wired with the persisted settings.
# --------------------------------------------------------------------------- #
class TestSettingsProviderWiring:
    def _point_store_at(self, tmp_path, monkeypatch, settings: dict) -> None:
        monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
        (tmp_path / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    def test_default_asset_manager_wires_persisted_settings(self, tmp_path, monkeypatch):
        # The default manager must read the PERSISTED offline flag (not a blind
        # {}), so verify_provisioned's detect probes match the RPC path.
        self._point_store_at(tmp_path, monkeypatch, {"offline": True})
        mgr = bs._default_asset_manager(tmp_path)
        assert mgr._settings_provider is not None
        assert mgr._settings().get("offline") is True

    def test_ensure_assets_default_manager_wires_settings(self, tmp_path, monkeypatch):
        # ensure_assets' own default-manager branch is likewise settings-wired:
        # a captured manager exposes the persisted flag.
        self._point_store_at(tmp_path, monkeypatch, {"offline": True})
        captured: dict[str, object] = {}

        class _Spy:
            def __init__(self, *, root, settings_provider):
                captured["provider"] = settings_provider

            def ensure(self, names, job_ctx):
                captured["names"] = list(names)

        import media_studio.assets.manager as mgr_mod

        monkeypatch.setattr(mgr_mod, "AssetManager", _Spy)
        bs.ensure_assets([manifest.YUNET_ASSET_NAME], tmp_path)
        assert captured["names"] == [manifest.YUNET_ASSET_NAME]
        # the provider is the live store's getter — it reads the persisted flag.
        assert captured["provider"]().get("offline") is True

    def test_ensure_assets_respects_persisted_offline(self, tmp_path, monkeypatch):
        # End-to-end through the REAL AssetManager: offline=true blocks egress
        # for an un-installed asset (guard_network fires before any bytes move).
        self._point_store_at(tmp_path, monkeypatch, {"offline": True})
        with pytest.raises(OfflineError):
            bs.ensure_assets([manifest.YUNET_ASSET_NAME], tmp_path)

    def test_ensure_assets_online_does_not_block_installed_asset(self, tmp_path, monkeypatch):
        # The FALSE side of the wiring: offline=false + an already-present asset
        # is a no-op ensure (empty todo) — the wired provider never spuriously
        # raises, and nothing is downloaded.
        self._point_store_at(tmp_path, monkeypatch, {"offline": False})

        class _AllInstalled:
            def __init__(self, *, root, settings_provider):
                self.settings_provider = settings_provider

            def ensure(self, names, job_ctx):
                # mimic the real manager: no todo -> guard is never consulted.
                job_ctx.progress(100.0, "all installed")

        import media_studio.assets.manager as mgr_mod

        monkeypatch.setattr(mgr_mod, "AssetManager", _AllInstalled)
        # no raise == the wired provider did not block the online path.
        bs.ensure_assets([manifest.YUNET_ASSET_NAME], tmp_path)


# --------------------------------------------------------------------------- #
# Finding 2 — get-pip.py is sha256-verified before it is ever executed (F3c).
# --------------------------------------------------------------------------- #
class TestGetPipSha256:
    def test_staged_copy_matching_hash_is_accepted(self, tmp_path):
        embed = tmp_path / "embed"
        embed.mkdir()
        body = b"# get-pip staged"
        (embed / "get-pip.py").write_bytes(body)
        found = bs.ensure_get_pip(
            tmp_path / "root",
            embed,
            urlopen=None,
            get_pip_sha256=hashlib.sha256(body).hexdigest(),
        )
        assert found == embed / "get-pip.py"

    def test_staged_copy_mismatch_raises(self, tmp_path):
        embed = tmp_path / "embed"
        embed.mkdir()
        (embed / "get-pip.py").write_bytes(b"# tampered staged")
        with pytest.raises(bs.BootstrapError, match="sha256"):
            bs.ensure_get_pip(tmp_path / "root", embed, urlopen=None)

    def test_cached_copy_matching_hash_is_accepted(self, tmp_path):
        body = b"# get-pip cached"
        cached = tmp_path / "root" / "tools" / "get-pip.py"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(body)
        found = bs.ensure_get_pip(
            tmp_path / "root",
            None,
            urlopen=None,
            get_pip_sha256=hashlib.sha256(body).hexdigest(),
        )
        assert found == cached

    def test_poisoned_cache_is_rejected_on_read(self, tmp_path):
        # A poisoned <root>/tools/get-pip.py (bootstrap + manager share it) must
        # be re-verified on read, not silently trusted+executed.
        cached = tmp_path / "root" / "tools" / "get-pip.py"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"# poisoned bytes")
        with pytest.raises(bs.BootstrapError, match="sha256"):
            bs.ensure_get_pip(tmp_path / "root", None, urlopen=None)

    def test_download_matching_hash_is_written_and_returned(self, tmp_path):
        body = b"# freshly downloaded get-pip"
        urls: list[str] = []

        def fake_urlopen(url):
            urls.append(url)
            return _FakeResp(body)

        found = bs.ensure_get_pip(
            tmp_path / "root",
            None,
            urlopen=fake_urlopen,
            get_pip_sha256=hashlib.sha256(body).hexdigest(),
        )
        assert found.read_bytes() == body
        assert urls == [bs.GET_PIP_URL]

    def test_download_tampered_raises_and_writes_nothing(self, tmp_path):
        # verify-before-persist: a hash mismatch never lands on disk.
        def fake_urlopen(url):
            return _FakeResp(b"# MITM'd get-pip")

        with pytest.raises(bs.BootstrapError, match="sha256"):
            bs.ensure_get_pip(tmp_path / "root", None, urlopen=fake_urlopen)
        assert not (tmp_path / "root" / "tools" / "get-pip.py").exists()

    def test_download_transport_error_stays_typed(self, tmp_path):
        # A urlopen failure surfaces as the download error, NOT the sha check —
        # _verify runs only after a successful read (ordering guard).
        def fake_urlopen(url):
            raise OSError("offline")

        with pytest.raises(bs.BootstrapError, match="could not download"):
            bs.ensure_get_pip(tmp_path / "root", None, urlopen=fake_urlopen)

    def test_default_sha_is_the_manager_pin(self):
        # bootstrap and the manager verify against the SAME F3c pin.
        import inspect

        sig = inspect.signature(bs.ensure_get_pip)
        assert sig.parameters["get_pip_sha256"].default == GET_PIP_SHA256

    def test_install_env_threads_get_pip_sha256(self, tmp_path):
        # install_env forwards the sha seam to ensure_get_pip: a matching cached
        # copy installs; a mismatch fails loud before any pip step runs.
        req = tmp_path / "req.txt"
        req.write_text("numpy==2.4.6\n", encoding="utf-8")
        body = b"# gp seam"
        cached = tmp_path / "root" / "tools" / "get-pip.py"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(body)
        calls: list[list[str]] = []

        def fake_run(argv, extra_env):
            calls.append(list(argv))
            return 0

        env_dir = bs.install_env(
            python_exe=tmp_path / "python.exe",
            root=tmp_path / "root",
            env_name="sidecar",
            req_file=req,
            run_step=fake_run,
            get_pip_sha256=hashlib.sha256(body).hexdigest(),
        )
        assert env_dir == tmp_path / "root" / "envs" / "sidecar"
        assert len(calls) == 2

    def test_install_env_rejects_bad_cached_get_pip(self, tmp_path):
        req = tmp_path / "req.txt"
        req.write_text("numpy==2.4.6\n", encoding="utf-8")
        cached = tmp_path / "root" / "tools" / "get-pip.py"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"# wrong-hash cached")

        def fake_run(argv, extra_env):  # pragma: no cover - must not be reached
            raise AssertionError("pip must not run when get-pip.py fails verification")

        with pytest.raises(bs.BootstrapError, match="sha256"):
            bs.install_env(
                python_exe=tmp_path / "python.exe",
                root=tmp_path / "root",
                env_name="sidecar",
                req_file=req,
                run_step=fake_run,
            )


class TestGetPipOfflineGuard:
    """A get-pip.py DOWNLOAD is offline-consent-gated when the caller threads the
    persisted settings; using a local staged/cached copy stays allowed offline."""

    def test_offline_settings_block_the_download(self, tmp_path):
        def fake_urlopen(url):  # pragma: no cover - must never run when offline
            raise AssertionError("offline must refuse before any network I/O")

        with pytest.raises(OfflineError):
            bs.ensure_get_pip(
                tmp_path / "root", None, urlopen=fake_urlopen, settings={"offline": True}
            )
        assert not (tmp_path / "root" / "tools" / "get-pip.py").exists()

    def test_online_settings_allow_the_download(self, tmp_path):
        body = b"# online get-pip"
        found = bs.ensure_get_pip(
            tmp_path / "root",
            None,
            urlopen=lambda url: _FakeResp(body),
            get_pip_sha256=hashlib.sha256(body).hexdigest(),
            settings={"offline": False},
        )
        assert found.read_bytes() == body

    def test_offline_still_uses_a_cached_local_copy(self, tmp_path):
        # Offline never blocks reusing a local get-pip.py — only egress.
        body = b"# cached offline-ok"
        cached = tmp_path / "root" / "tools" / "get-pip.py"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(body)
        found = bs.ensure_get_pip(
            tmp_path / "root",
            None,
            urlopen=None,
            get_pip_sha256=hashlib.sha256(body).hexdigest(),
            settings={"offline": True},
        )
        assert found == cached

    def test_install_env_offline_refuses_get_pip_download(self, tmp_path):
        req = tmp_path / "req.txt"
        req.write_text("numpy==2.4.6\n", encoding="utf-8")

        def fake_run(argv, extra_env):  # pragma: no cover - never reached offline
            raise AssertionError("no pip step runs when the get-pip download is refused")

        with pytest.raises(OfflineError):
            bs.install_env(
                python_exe=tmp_path / "python.exe",
                root=tmp_path / "root",
                env_name="sidecar",
                req_file=req,
                run_step=fake_run,
                urlopen=lambda url: _FakeResp(b"x"),
                settings={"offline": True},
            )


# --------------------------------------------------------------------------- #
# Finding 3 — step-2 pip runs via a runtime sys.path prelude (read-only install).
# --------------------------------------------------------------------------- #
class TestStep2Prelude:
    def _step2(self, tmp_path, **kw):
        steps = bs.build_pip_steps(
            tmp_path / "py" / "python.exe",
            tmp_path / "get-pip.py",
            tmp_path / "envs" / "sidecar",
            tmp_path / "req.txt",
            **kw,
        )
        return steps[1]

    def test_step2_invokes_pip_via_dash_c_prelude(self, tmp_path):
        step2 = self._step2(tmp_path)
        argv = step2["argv"]
        env_dir = str(tmp_path / "envs" / "sidecar")
        assert argv[0] == str(tmp_path / "py" / "python.exe")
        assert argv[1] == "-c"  # NOT "-m pip" — self-inserts the env dir
        assert "-m" not in argv
        prelude = argv[2]
        assert "sys.path.insert(0," in prelude
        assert "runpy.run_module('pip'" in prelude
        # the env dir is embedded as a proper repr literal (survives spaces/\\).
        assert repr(env_dir) in prelude
        # the real pip args follow as inspectable argv tokens.
        assert argv[3] == "install"
        assert "--target" in argv
        assert argv[-2:] == ["-r", str(tmp_path / "req.txt")]
        # PYTHONPATH still set for a non-isolated python (belt + suspenders).
        assert step2["env"] == {"PYTHONPATH": env_dir}

    def test_prelude_is_syntactically_valid_python(self, tmp_path):
        # The prelude is only executed by a real embeddable at first run
        # (needsRealIntegration), so at minimum prove it always compiles for any
        # env dir — including one with backslashes, spaces and a quote.
        env_dir = str(tmp_path / "weird dir's\\envs" / "sidecar")
        prelude = bs._STEP2_PIP_PRELUDE.format(env=env_dir)
        compiled = compile(prelude, "<step2-prelude>", "exec")  # raises on bad syntax
        assert compiled is not None
        assert repr(env_dir) in prelude

    def test_step2_with_lock_keeps_prelude_and_hash_flags(self, tmp_path):
        lock = tmp_path / "req.lock.txt"
        step2 = self._step2(tmp_path, lock_file=lock)["argv"]
        assert step2[1] == "-c"
        assert step2[3] == "install"
        for flag in bs.HASHED_LOCK_PIP_ARGS:
            assert flag in step2
        assert step2[-2:] == ["-r", str(lock)]

    def test_prelude_does_not_depend_on_pythonpath_or_pth(self, tmp_path):
        # The prelude inserts the env dir itself, so it works even when the
        # ._pth could not be rewritten (read-only install). Prove the env dir is
        # present INSIDE the -c code, not merely as an env var.
        env_dir = str(tmp_path / "envs" / "sidecar")
        prelude = self._step2(tmp_path)["argv"][2]
        assert f"sys.path.insert(0, {env_dir!r})" in prelude
