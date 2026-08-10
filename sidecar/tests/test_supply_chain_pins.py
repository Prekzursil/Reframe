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
* ``.github/workflows/quality.yml`` again, W23 — the ``gate-deps`` osv-scanner
  invocation passed THREE ``--lockfile`` arguments and none of them was the
  chatterbox environment, so a Python env that SHIPS (``build/make-portable.ps1``
  ships a second, py3.14 embeddable CPython for it) and that carries its own
  ``+cu128`` torch build had ZERO CVE scanning. Section 5 below turns "every
  shipped dependency environment is in the deps gate" into an asserted
  invariant, discovered from disk rather than from a hardcoded list, so a fourth
  environment cannot be added unscanned later.

The lockfile-mechanism tests live in ``test_env_lockfile.py``; this module only
covers the WU-S10 pinning deltas.
"""

from __future__ import annotations

import calendar
import re
from pathlib import Path

import pytest
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
APP_DIR = REPO_ROOT / "app"
SIDECAR_DIR = REPO_ROOT / "sidecar"
RUNTIME_SETUP_DIR = SIDECAR_DIR / "runtime_setup"


def _recording_manager(root: Path, **kwargs: object) -> tuple[AssetManager, list[list[str]]]:
    """An AssetManager with get-pip pre-staged and a recording run_cmd (no pip).

    "no pip" requires INJECTING the staged digest, not merely writing the file:
    `_install_env` re-verifies a cached get-pip.py against the manager's pin, so an
    un-injected dummy is discarded and silently refetched over the network. That is
    how an upstream rotation of the rolling get-pip.py URL turned this file red.
    """
    gp = root / "tools" / "get-pip.py"
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.write_text("# gp", encoding="utf-8")
    kwargs.setdefault(
        "get_pip_sha256", "8153d63a9c9aa82b8751e206360a47ac82a56eac21edcc3ae6b121bc72de2cf0"
    )  # sha256(b"# gp")
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

    def test_every_pin_default_is_populated(self):
        """Every ``-Expected*Sha256`` default must BE a 64-hex digest, not ''.

        WU-S10 made the pin mandatory but shipped three of them EMPTY
        (``ExpectedPythonSha256``, ``ExpectedChatterboxPythonSha256``,
        ``ExpectedFfmpegSha256``). The gate then did exactly what it promised and
        refused every download, so `Stage packaged runtime` failed on every
        Windows CI run and the Windows package could not be built at all. The
        sibling tests above only prove the MECHANISM exists (Assert-Sha256Pin is
        called, no `-and` short-circuit) — none of them notice that the mechanism
        has nothing to check against. A fail-closed guard with no key is not a
        guard, it is an outage.
        """
        body = self._body()
        found = dict(re.findall(r"\$(Expected\w*Sha256)\s*=\s*'([^']*)'", body))
        # All four artifacts the script can fetch must carry a pin default.
        assert set(found) >= {
            "ExpectedPythonSha256",
            "ExpectedChatterboxPythonSha256",
            "ExpectedFfmpegSha256",
            "ExpectedGetPipSha256",
        }, f"a pin parameter disappeared from the param block: {sorted(found)}"
        empty = sorted(name for name, value in found.items() if not value)
        assert not empty, (
            f"these SHA-256 pins ship EMPTY, so the fail-closed gate refuses the "
            f"download and nothing can ever be staged: {empty}. Obtain each digest "
            f"with -RecordHashes, cross-check it against the vendor's published "
            f"checksum, then record it as the parameter default."
        )
        malformed = sorted(name for name, value in found.items() if not re.fullmatch(r"[0-9a-f]{64}", value))
        assert not malformed, f"pins are not lowercase 64-hex digests: {malformed}"

    def test_pinned_ffmpeg_release_is_a_month_end_tag(self):
        """BtbN prunes mid-month dailies; only month-end builds are durable.

        Retention measured 2026-07-26: the last ~2 weeks of DAILY autobuilds plus
        the LAST-DAY-OF-MONTH build of every month back to 2024-08-31. The former
        pin ``autobuild-2026-07-03-13-21`` was a mid-month daily, so it was
        deleted and started returning 404 — breaking the Windows build weeks after
        it was chosen, with no code change. Pin a month-end tag or the same silent
        expiry recurs.
        """
        body = self._body()
        tag = re.search(r"releases/download/autobuild-(\d{4})-(\d{2})-(\d{2})-", body)
        assert tag, "the ffmpeg pin is not a BtbN dated autobuild URL"
        year, month, day = (int(part) for part in tag.groups())
        last_day = calendar.monthrange(year, month)[1]
        assert day == last_day, (
            f"ffmpeg is pinned to autobuild-{year:04d}-{month:02d}-{day:02d}, a MID-MONTH "
            f"daily that BtbN deletes after ~2 weeks. Pin the month-end build "
            f"({year:04d}-{month:02d}-{last_day:02d}), which is retained for years."
        )

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


# --------------------------------------------------------------------------- #
# 5. W23 — the deps gate must scan EVERY shipped dependency environment
# --------------------------------------------------------------------------- #
#: `npm ci` / electron-builder create these; a manifest inside one is generated
#: output, not a shipped environment, so discovery must not demand it be scanned.
GENERATED_APP_DIRS = frozenset({"node_modules", "dist", "out"})

#: `name:` as the FIRST key of a sequence item — i.e. a real workflow STEP. Same
#: shape `.quality/charter_check.py` matches on, and for the same reason: a
#: job-level or `with:`-block `name:` is a plain mapping key, not a step.
STEP_NAME_KEY = re.compile(r"^\s*-\s+name:\s*(?P<value>\S.*)$")
#: any other key of the step mapping (`run:`, `if:`, `env:`, `working-directory:`).
STEP_MAPPING_KEY = re.compile(r"^\s*(?P<key>[A-Za-z][\w-]*):(?P<rest>.*)$")
#: a shell comment marker: `#` at line start or after whitespace.
SHELL_COMMENT = re.compile(r"(?:^|\s)#")
#: the block-scalar indicators that mean "the body is on the FOLLOWING lines".
BLOCK_SCALARS = frozenset({"|", ">", "|-", ">-", "|+", ">+", "|2", ">2"})
#: `--lockfile=<path>`. Quote characters and the trailing `\` of a shell line
#: continuation are excluded from the path by the character class.
LOCKFILE_ARG = re.compile(r"--lockfile[=\s]+(?P<path>[^\s\\'\"]+)")


def _repo_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _strip_shell_comment(line: str) -> str:
    """Everything from the first shell comment marker onward is not an argument."""
    marker = SHELL_COMMENT.search(line)
    return line[: marker.start()] if marker else line


def gate_deps_run_script(workflow_text: str) -> str:
    """The ``run:`` script of the ``gate-deps`` step, and nothing else.

    Scoping to ``run:`` — rather than to "every line of the step" — is what keeps
    a ``--lockfile`` named in a step-level ``if:``/``env:``/``with:`` value out of
    the count. Both the inline (``run: osv-scanner …``) and block-scalar
    (``run: |``) forms are handled.
    """
    in_step = in_run = False
    script: list[str] = []
    for raw in workflow_text.splitlines():
        step = STEP_NAME_KEY.match(raw)
        if step:
            in_step = step.group("value").startswith("gate-deps")
            in_run = False
            continue
        if not in_step:
            continue
        key = STEP_MAPPING_KEY.match(raw)
        if key:
            inline = key.group("rest").strip()
            in_run = key.group("key") == "run" and inline in BLOCK_SCALARS
            if key.group("key") == "run" and not in_run:
                script.append(inline)
            continue
        if in_run:
            script.append(raw)
    return "\n".join(script)


def shell_commands(script: str) -> list[str]:
    """``script`` split into logical shell commands, comments removed.

    Trailing ``\\`` continuations are joined so a multi-line invocation is ONE
    command; that is what lets the caller ask "which command is this argument
    actually on?" instead of trusting a bare line match.
    """
    commands: list[str] = []
    pending = ""
    for raw in script.splitlines():
        line = _strip_shell_comment(raw).strip()
        if not line:
            continue
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        commands.append((pending + line).strip())
        pending = ""
    if pending:
        commands.append(pending.strip())
    return commands


def gate_deps_lockfile_args(workflow_text: str) -> set[str]:
    """The ``--lockfile`` paths the ``gate-deps`` osv-scanner COMMAND passes.

    Measure the FIELD, not the document — and specifically, measure the COMMAND.
    Four shapes in a workflow can name a lockfile without passing it, and all
    four were counted by the first version of this function (each is now pinned
    by :class:`TestArgParserMeasuresTheCommandNotTheDocument`): the explanatory
    comment block above the step names lockfiles in prose; a ``#``-disabled
    argument line; a *trailing* ``#`` mention on a live argument line; and an
    ``echo`` of an argument inside the ``run:`` body. So the scan reads only the
    step's ``run:`` script, strips shell comments, joins ``\\`` continuations
    into logical commands, and accepts arguments ONLY from a command whose
    executable is ``osv-scanner``.

    Scope of that claim, measured rather than assumed (this is a line walker, not
    a YAML+shell parser). NOT handled: a ``--lockfile`` inside a heredoc body, a
    path built by variable expansion, an ``osv-scanner`` invoked through a
    wrapper (``xargs``/``bash -c``/a script), and a flow-style ``- {name: …}``
    step. Every one of those DROPS an argument, which makes the invariant report
    the environment as unscanned and fails CI loudly; none can add a phantom
    argument. That is the same fail-closed error direction
    ``.quality/charter_check.py`` documents for its own parser, and it is the
    direction that matters here — a false GREEN on a security gate is the
    dangerous one.
    """
    found: set[str] = set()
    for command in shell_commands(gate_deps_run_script(workflow_text)):
        if not command.startswith("osv-scanner"):
            continue
        found.update(match.group("path") for match in LOCKFILE_ARG.finditer(command))
    return found


def shipped_dependency_manifests(repo_root: Path | None = None) -> dict[str, frozenset[str]]:
    """``{environment -> the manifests that would cover it}``, read off disk.

    Deliberately NOT a hardcoded list: a literal list would be edited by the very
    commit that introduces a new environment, so discovery is the point.

    Discovered shapes, and ONLY these (``repo_root`` defaults to this repo; it is
    a parameter so :class:`TestDiscoveryScopeIsTheThreeGlobs` can plant manifests
    in a throwaway tree and pin the boundary):

    * ``app/package-lock.json`` and ``app/<immediate-subdir>/package-lock.json``
      — one environment per npm tree;
    * ``sidecar/requirements*.txt`` — the resolved closure the gate has read
      since it was written;
    * ``sidecar/runtime_setup/requirements*.txt`` — the first-run
      ``pip --target`` environments. A sibling ``requirements-<env>.lock.txt`` is
      an F1 build-prep artifact that is generated rather than committed, so
      scanning EITHER file covers that environment; hence a SET per environment
      instead of a single path.

    Both globs are single-level on purpose: a recursive walk would descend into
    ``sidecar/.venv`` and ``app/node_modules`` and pick up third-party
    requirements files that this repo does not ship. The cost of that choice is
    stated, not hidden: a manifest anywhere ELSE — a repo-root lockfile, two
    levels under ``app/``, a sibling top-level tree, a ``sidecar/envs/…`` tree, a
    pin list not named ``requirements*``, or a dependency set declared as a
    ``pyproject.toml`` extra (which is how the live ``reframe-gpu`` extra escapes
    this gate) — is NOT discovered and therefore NOT demanded by the invariant.
    """
    root = REPO_ROOT if repo_root is None else repo_root
    app_dir = root / "app"
    sidecar_dir = root / "sidecar"
    environments: dict[str, set[str]] = {}
    npm_roots = [
        app_dir,
        *(d for d in sorted(app_dir.iterdir()) if d.is_dir() and d.name not in GENERATED_APP_DIRS),
    ]
    for npm_root in npm_roots:
        lock = npm_root / "package-lock.json"
        if lock.is_file():
            environments[_repo_rel(lock, root)] = {_repo_rel(lock, root)}
    for req in sorted(sidecar_dir.glob("requirements*.txt")):
        environments[_repo_rel(req, root)] = {_repo_rel(req, root)}
    for req in sorted((sidecar_dir / "runtime_setup").glob("requirements*.txt")):
        env = req.name.removesuffix(".txt").removesuffix(".lock")
        environments.setdefault(env, set()).add(_repo_rel(req, root))
    return {name: frozenset(paths) for name, paths in environments.items()}


def _distribution_names(path: Path) -> set[str]:
    """The normalized distribution names pinned in a requirements-style file."""
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):  # comment / `--extra-index-url` / `--hash`
            continue
        names.add(re.split(r"[=<>!~\[; ]", line, maxsplit=1)[0].strip().lower().replace("_", "-"))
    return names


class TestDepsGateCoversEveryShippedEnv:
    @staticmethod
    def _body() -> str:
        return QUALITY_WORKFLOW.read_text(encoding="utf-8")

    # --- detector control: both halves must find KNOWN-PRESENT items --------- #
    def test_arg_parser_finds_the_three_long_standing_lockfiles(self):
        """A zero read here would make every assertion below vacuously true.

        These three have been in the ``gate-deps`` step since it was written, so
        the parser must see them before its silence about a fourth means anything.
        """
        found = gate_deps_lockfile_args(self._body())
        assert {
            "app/package-lock.json",
            "app/render-cli/package-lock.json",
            "sidecar/requirements.lock.txt",
        } <= found, f"the --lockfile parser is broken, it found {sorted(found)}"

    def test_discovery_finds_the_known_environments(self):
        environments = shipped_dependency_manifests()
        assert "app/package-lock.json" in environments
        assert "app/render-cli/package-lock.json" in environments
        assert "sidecar/requirements.lock.txt" in environments
        assert environments["requirements-chatterbox"] >= {"sidecar/runtime_setup/requirements-chatterbox.txt"}
        assert environments["requirements-sidecar"] >= {"sidecar/runtime_setup/requirements-sidecar.txt"}

    def test_arg_parser_ignores_lockfiles_outside_the_gate_deps_step(self):
        text = "\n".join(
            [
                "      # --lockfile=prose/one.json is read by the deps gate",
                "      - name: gate-sast opengrep",
                "        run: echo --lockfile=other-step/two.json",
                "      - name: gate-deps osv-scanner",
                "        run: |",
                "          osv-scanner scan source \\",
                "            --lockfile=real/three.json \\",
                "            # --lockfile=disabled/four.json",
                "      - name: charter-check",
                "        run: echo --lockfile=later-step/five.json",
            ]
        )
        assert gate_deps_lockfile_args(text) == {"real/three.json"}

    # --- the invariant ------------------------------------------------------- #
    def test_every_shipped_environment_is_scanned_by_the_deps_gate(self):
        scanned = gate_deps_lockfile_args(self._body())
        missing = {env: sorted(paths) for env, paths in shipped_dependency_manifests().items() if not (paths & scanned)}
        assert not missing, (
            f"these dependency environments SHIP but no --lockfile in the gate-deps step scans them, "
            f"so their known CVEs are invisible to the gate: {missing}. Add one manifest per "
            f"environment to the osv-scanner invocation in .github/workflows/quality.yml (and, if a "
            f"finding is genuinely unfixable, a dated + reasoned ignore in osv-scanner.toml)."
        )

    # --- MUTATION: the invariant must be able to FAIL ------------------------ #
    @pytest.mark.parametrize(
        "env",
        [
            "app/package-lock.json",
            "app/render-cli/package-lock.json",
            "sidecar/requirements.lock.txt",
            "requirements-chatterbox",
            "requirements-sidecar",
        ],
    )
    def test_removing_one_environments_lockfile_arg_is_caught(self, env: str):
        """Drop each environment's argument in turn; the invariant must name it.

        A green invariant proves nothing on its own — this is the both-states
        check that it goes RED in the known-broken state, run permanently rather
        than once at authoring time.
        """
        body = self._body()
        mutated = body
        for path in shipped_dependency_manifests()[env]:
            mutated = re.sub(rf"^.*--lockfile={re.escape(path)}.*$\n?", "", mutated, flags=re.MULTILINE)
        assert mutated != body, f"no --lockfile argument for {env} was found to remove"
        scanned = gate_deps_lockfile_args(mutated)
        still_missing = sorted(name for name, paths in shipped_dependency_manifests().items() if not (paths & scanned))
        assert still_missing == [env]

    def test_a_commented_out_lockfile_arg_does_not_satisfy_the_invariant(self):
        """use-vs-mention on the live file: a disabled argument is not passed."""
        target = "sidecar/runtime_setup/requirements-chatterbox.txt"
        body = self._body()
        mutated = re.sub(rf"^(\s*)(--lockfile={re.escape(target)})", r"\1# \2", body, flags=re.MULTILINE)
        assert mutated != body, f"no --lockfile argument for {target} was found to comment out"
        assert target not in gate_deps_lockfile_args(mutated)


class TestArgParserMeasuresTheCommandNotTheDocument:
    """Only the osv-scanner COMMAND counts — a *mention* is not an argument.

    Every case below was executed against the FIRST version of
    :func:`gate_deps_lockfile_args`, which skipped a line only when its first
    non-space character was ``#``. Three shapes leaked through it and were
    counted as scanned lockfiles: a trailing ``#`` mention on a live argument
    line, an ``echo`` inside the ``run:`` body, and an ``if:`` expression. The
    last test is the dangerous one — with the chatterbox argument DELETED and
    re-mentioned as a trailing comment, the invariant above reported
    ``missing = {}`` (GREEN) while the gate no longer scanned the file at all.
    False-GREEN on a security gate is the wrong error direction, so all four are
    asserted permanently rather than measured once.
    """

    @staticmethod
    def _run_block(*body: str) -> str:
        return "\n".join(["      - name: gate-deps osv-scanner", "        run: |", *body])

    @classmethod
    def _osv_command(cls, *arg_lines: str) -> str:
        """A ``gate-deps`` step whose run body is ONE continued osv-scanner call."""
        return cls._run_block("          osv-scanner scan source \\", *arg_lines)

    # --- detector control: the parser must SEE a known-present argument ------ #
    def test_a_real_argument_is_seen(self):
        assert gate_deps_lockfile_args(self._osv_command("            --lockfile=real/a.json")) == {"real/a.json"}

    def test_an_inline_run_argument_is_seen(self):
        text = "\n".join(
            [
                "      - name: gate-deps osv-scanner",
                "        run: osv-scanner scan source --lockfile=real/a.json",
            ]
        )
        assert gate_deps_lockfile_args(text) == {"real/a.json"}

    # --- the four shapes that must NOT count -------------------------------- #
    def test_a_whole_line_comment_argument_is_not_seen(self):
        assert gate_deps_lockfile_args(self._osv_command("            # --lockfile=dead/b.json")) == set()

    def test_a_trailing_comment_mention_is_not_seen(self):
        text = self._osv_command("            --lockfile=real/a.json  # --lockfile=ghost/c.json")
        assert gate_deps_lockfile_args(text) == {"real/a.json"}

    def test_an_echoed_mention_inside_the_run_body_is_not_seen(self):
        # A SEPARATE command in the same run body. (An `echo` glued on by a `\`
        # continuation genuinely IS part of the osv-scanner argv, so that shape is
        # not the hole — this one is.)
        text = self._run_block(
            "          echo '--lockfile=ghost/d.json'",
            "          osv-scanner scan source --lockfile=real/a.json",
        )
        assert gate_deps_lockfile_args(text) == {"real/a.json"}

    def test_a_mention_in_a_step_level_if_expression_is_not_seen(self):
        text = "\n".join(
            [
                "      - name: gate-deps osv-scanner",
                "        if: contains(github.event.head_commit.message, '--lockfile=ghost/e.json')",
                "        run: osv-scanner scan source --lockfile=real/a.json",
            ]
        )
        assert gate_deps_lockfile_args(text) == {"real/a.json"}

    # --- end to end on the REAL committed workflow --------------------------- #
    def test_a_deleted_argument_cannot_be_faked_by_a_trailing_comment(self):
        target = "sidecar/runtime_setup/requirements-chatterbox.txt"
        survivor = "--lockfile=sidecar/runtime_setup/requirements-sidecar.txt"
        body = QUALITY_WORKFLOW.read_text(encoding="utf-8")
        stripped = re.sub(rf"^.*--lockfile={re.escape(target)}.*$\n?", "", body, flags=re.MULTILINE)
        assert f"--lockfile={target}" not in stripped, "the argument survived removal — this probe is broken"
        assert survivor in stripped, "the surviving argument this case hangs the comment on is gone"
        faked = stripped.replace(survivor, f"{survivor}  # dropped --lockfile={target}")
        scanned = gate_deps_lockfile_args(faked)
        assert target not in scanned, f"a commented-out mention was counted as an argument: {sorted(scanned)}"
        still_missing = sorted(name for name, paths in shipped_dependency_manifests().items() if not (paths & scanned))
        assert still_missing == ["requirements-chatterbox"]


class TestDiscoveryScopeIsTheThreeGlobs:
    """Pin exactly which manifest shapes discovery CAN and cannot see.

    The W23 summary sentences originally said a fourth environment "cannot be
    added unscanned" without qualification. Three independent reviewers REFUTED
    that by executing :func:`shipped_dependency_manifests` against synthetic trees
    with a manifest planted outside the three globs — a ``pyproject.toml`` extra,
    a repo-root lockfile, one two levels under ``app/``, a sibling top-level tree,
    a ``sidecar/envs/…`` tree, and a pin list not named ``requirements*``. The
    code was right and the sentences were wider than the evidence, so the real
    boundary is asserted here instead of merely described. Widening a glob is a
    deliberate change that must update this test AND the prose in the same commit.
    """

    @staticmethod
    def _tree(root: Path, *relative: str) -> Path:
        (root / "app").mkdir(parents=True, exist_ok=True)
        (root / "sidecar" / "runtime_setup").mkdir(parents=True, exist_ok=True)
        for rel in relative:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# planted\n", encoding="utf-8")
        return root

    @pytest.mark.parametrize(
        "planted",
        [
            "app/package-lock.json",
            "app/render-cli/package-lock.json",
            "sidecar/requirements.lock.txt",
            "sidecar/runtime_setup/requirements-newenv.txt",
        ],
    )
    def test_a_manifest_in_a_discovered_shape_is_found(self, tmp_path, planted: str):
        """Detector control. Without this, every zero below would be meaningless."""
        environments = shipped_dependency_manifests(self._tree(tmp_path, planted))
        assert any(planted in paths for paths in environments.values()), (
            f"discovery missed {planted}, which it is supposed to find: {environments}"
        )

    @pytest.mark.parametrize(
        "planted",
        [
            "package-lock.json",  # repo root
            "app/renderer/plugins/package-lock.json",  # two levels under app/
            "tools/cli/package-lock.json",  # a sibling top-level tree
            "sidecar/envs/whisperx/requirements.txt",  # nested under sidecar/
            "sidecar/runtime_setup/gpu-pins.txt",  # not named requirements*
            "sidecar/pyproject.toml",  # a dependency set declared as an extra
        ],
    )
    def test_a_manifest_outside_the_three_globs_is_not_found(self, tmp_path, planted: str):
        environments = shipped_dependency_manifests(self._tree(tmp_path, planted))
        assert not any(planted in paths for paths in environments.values()), (
            f"discovery now sees {planted}. That is an improvement, not a failure — but the "
            f"claim in QUALITY-CHARTER.md, osv-scanner.toml and this module's docstring must be "
            f"widened in the same commit, and this case moved to the discovered-shapes list."
        )

    def test_the_live_reframe_gpu_extra_is_a_real_instance_of_that_gap(self):
        """The gap is not hypothetical: it is why ``reframe-gpu`` is unscanned.

        ``sidecar/pyproject.toml`` declares a ``reframe-gpu`` extra with its own
        pinned torch, and the SHIPPED sidecar tells the user to install it at
        runtime — yet no scanned manifest contains those pins, and a pyproject
        extra is not a shape discovery looks at. Asserted here so the honest scope
        of gate 6 cannot silently drift back to "every shipped environment".
        """
        pyproject = (SIDECAR_DIR / "pyproject.toml").read_text(encoding="utf-8")
        assert "reframe-gpu" in pyproject, "the reframe-gpu extra is gone; retire this test and the caveats"
        assert re.search(r"^\s*\"torch==", pyproject, flags=re.MULTILINE), "reframe-gpu no longer pins torch"
        assert "sidecar/pyproject.toml" not in gate_deps_lockfile_args(QUALITY_WORKFLOW.read_text(encoding="utf-8"))
        assert "torch" not in _distribution_names(SIDECAR_DIR / "requirements.lock.txt")
        assert "torch" not in _distribution_names(RUNTIME_SETUP_DIR / "requirements-sidecar.txt")


class TestDepsGateChatterboxRationale:
    # --- WHY the chatterbox env needs its own argument ----------------------- #
    def test_the_chatterbox_env_pins_distributions_no_other_manifest_covers(self):
        """``sidecar/requirements.lock.txt`` structurally cannot cover this env.

        ``sidecar/pyproject.toml`` states that chatterbox-tts/torch must NOT be
        added to the main sidecar env (isolated env asset only), so the only
        Python lockfile the gate read before W23 sees none of them. Measured at
        this commit ALL THREE pins are absent from it (chatterbox-tts, torch,
        torchaudio — the latter two a ``+cu128`` build the sidecar tree never
        names); the assertion is the weaker "at least one", so a future dep
        change cannot make it brittle while the load-bearing property holds.
        """
        chatterbox = _distribution_names(RUNTIME_SETUP_DIR / "requirements-chatterbox.txt")
        sidecar_closure = _distribution_names(SIDECAR_DIR / "requirements.lock.txt")
        assert chatterbox, "the chatterbox requirements file parsed to zero distributions"
        assert len(sidecar_closure) > 1, "the sidecar closure parsed to nothing — the parser is broken"
        assert chatterbox - sidecar_closure, (
            "every chatterbox distribution is already pinned in sidecar/requirements.lock.txt; "
            "re-check whether this environment still needs its own --lockfile argument"
        )
