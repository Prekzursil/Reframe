"""Unit tests for media_studio.features.caption_remotion (RemotionCaptionEngine).

Heavy-free: no node/electron/remotion is ever spawned — the popen seam is a
fake, the resolution chains probe pytest tmp dirs, and the assets root is a tmp
dir. Focus areas mandated by the T4a unit contract:

  * job-file shape ({bundleDir, composition, inputProps, outPath[, chromium]})
  * argv construction (list, no shell) + the exe resolution chain
    (env MEDIA_STUDIO_NODE_EXE -> settings -> dev node_modules electron)
  * RENDER_OK parsing + failure surfacing (RemotionCaptionError)
  * BOTH pipes drained (fake popen records full consumption)
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest
from media_studio.assets.manifest import get_asset
from media_studio.features import caption_remotion as cr
from media_studio.features.caption_remotion import (
    COMPOSITION_ID,
    MAX_SUBPROCESS_ATTEMPTS,
    STYLES,
    TRANSIENT_SIGNATURES,
    RemotionCaptionEngine,
    RemotionCaptionError,
    build_argv,
    build_job,
    build_spawn_env,
    ensure_chrome_extracted,
    is_transient_compositor_failure,
    parse_render_ok,
    parse_render_progress,
    register_assets,
    resolve_bundle_dir,
    resolve_chromium,
    resolve_node_exe,
    resolve_render_js,
    run_render,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _ConsumableLines:
    """An iterable of lines that records whether it was read to exhaustion."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self.consumed = False

    def __iter__(self):
        yield from self._lines
        self.consumed = True


class _FakeProc:
    def __init__(
        self,
        stdout_lines: list[str],
        stderr_lines: list[str],
        code: int = 0,
    ) -> None:
        self.stdout = _ConsumableLines(stdout_lines)
        self.stderr = _ConsumableLines(stderr_lines)
        self._code = code
        self.terminated = False
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        return self._code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class _FakePopen:
    """Callable popen seam capturing argv/kwargs and (optionally) the job file.

    The job file is deleted by the engine after the run, so it is snapshotted
    at spawn time — exactly when a real process would read it.
    """

    def __init__(
        self,
        stdout_lines: list[str],
        stderr_lines: list[str] | None = None,
        code: int = 0,
    ) -> None:
        self._stdout_lines = stdout_lines
        self._stderr_lines = stderr_lines or []
        self._code = code
        self.captured: dict[str, Any] = {}
        self.job_snapshot: dict[str, Any] | None = None
        self.proc: _FakeProc | None = None

    def __call__(self, argv: list[str], **kwargs: Any) -> _FakeProc:
        self.captured = {"argv": argv, "kwargs": kwargs}
        if len(argv) >= 3 and os.path.isfile(argv[2]):
            with open(argv[2], encoding="utf-8") as fh:
                self.job_snapshot = json.load(fh)
        self.proc = _FakeProc(self._stdout_lines, self._stderr_lines, self._code)
        return self.proc


class _SequencedPopen:
    """Popen seam returning a different _FakeProc per call (subprocess retry).

    Each tuple is (stdout_lines, stderr_lines, code). The last tuple is reused
    for any spawn beyond the supplied sequence so an over-eager retry still gets
    a deterministic (and asserted-against) result rather than IndexError.
    """

    def __init__(self, sequence: list[tuple]) -> None:
        assert sequence, "need at least one outcome"
        self._sequence = sequence
        self.calls = 0
        self.argv_log: list[list[str]] = []
        self.procs: list[_FakeProc] = []
        self.job_snapshots: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> _FakeProc:
        self.argv_log.append(list(argv))
        if len(argv) >= 3 and os.path.isfile(argv[2]):
            with open(argv[2], encoding="utf-8") as fh:
                self.job_snapshots.append(json.load(fh))
        idx = min(self.calls, len(self._sequence) - 1)
        stdout_lines, stderr_lines, code = self._sequence[idx]
        self.calls += 1
        proc = _FakeProc(list(stdout_lines), list(stderr_lines), code)
        self.procs.append(proc)
        return proc


# --------------------------------------------------------------------------- #
# fixtures: a fake dev checkout with the resolvable runtime files
# --------------------------------------------------------------------------- #
@pytest.fixture()
def dev_root(tmp_path: Path) -> Path:
    electron = tmp_path / "app" / "node_modules" / "electron" / "dist" / f"electron{cr._EXE}"
    electron.parent.mkdir(parents=True)
    electron.write_bytes(b"fake-electron")
    render_js = tmp_path / "app" / "render-cli" / "dist" / "render.js"
    render_js.parent.mkdir(parents=True)
    render_js.write_text("// fake render.js", encoding="utf-8")
    bundle_dir = tmp_path / "app" / "render-cli" / "out" / "remotion-bundle"
    bundle_dir.mkdir(parents=True)
    return tmp_path


def _dev_electron(dev_root: Path) -> Path:
    return dev_root / "app" / "node_modules" / "electron" / "dist" / f"electron{cr._EXE}"


CUES = [
    {"index": 1, "start": 120.0, "end": 121.5, "text": "Hello there"},
    {"index": 2, "start": 121.5, "end": 124.0, "text": "{braces} stay literal"},
]


# --------------------------------------------------------------------------- #
# style registry + asset manifest
# --------------------------------------------------------------------------- #
def test_styles_registry_for_shortmaker_picker() -> None:
    # P4 §4: the registry grew from 4 to >=12 OpusClip-style templates. The four
    # originals must remain valid for backward compat; the additions are present.
    assert set(STYLES) >= {"bold", "bounce", "clean", "karaoke"}
    assert len(STYLES) >= 12
    assert len(set(STYLES)) == len(STYLES)  # no duplicate ids
    assert {
        "hormozi",
        "neon",
        "tiktok",
        "gradient",
        "impact",
        "mrbeast",
        "pop",
        "serif",
        "subtitle",
        "fire",
    } <= set(STYLES)
    assert cr.ENGINE_NAME == "remotion"
    assert COMPOSITION_ID == "CaptionedClip"


def test_chrome_headless_shell_asset_registered_and_pinned() -> None:
    entry = get_asset(cr.CHROME_HEADLESS_SHELL_ASSET)
    assert entry is not None
    assert entry.kind == "tool"
    assert entry.installer == "download"
    # A6 lesson 5: the URL is PINNED to an exact version.
    assert cr.CHROME_HEADLESS_SHELL_VERSION in str(entry.url)
    assert str(entry.url).endswith("chrome-headless-shell-win64.zip")
    assert entry.dest == cr.CHROME_HEADLESS_SHELL_ZIP_DEST
    assert entry.detect is cr.detect_chrome_headless_shell


def test_register_assets_is_idempotent() -> None:
    # Module import already registered; an identical re-register is a no-op.
    entry_again = register_assets()
    assert entry_again is get_asset(cr.CHROME_HEADLESS_SHELL_ASSET)


def test_detect_chrome_headless_shell_settings_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cr, "default_config_dir", lambda: tmp_path / "appdata")
    exe = tmp_path / "chs.exe"
    exe.write_bytes(b"x")
    assert cr.detect_chrome_headless_shell({cr.SETTING_CHROME: str(exe)}) == str(exe)
    assert cr.detect_chrome_headless_shell({}) is None


def test_detect_chrome_headless_shell_extracted_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cr, "default_config_dir", lambda: tmp_path)
    exe = tmp_path / cr.CHROME_HEADLESS_SHELL_EXE_REL
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    assert cr.detect_chrome_headless_shell({}) == str(exe)


# --------------------------------------------------------------------------- #
# zip extraction (the engine-owned unzip step)
# --------------------------------------------------------------------------- #
def _exe_member() -> str:
    # The in-zip member path for the headless shell exe (always forward-slash).
    return Path(cr.CHROME_HEADLESS_SHELL_EXE_REL).relative_to(cr.CHROME_HEADLESS_SHELL_EXTRACT_DIR).as_posix()


def _make_chrome_zip(zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(_exe_member(), b"fake chrome headless shell")


def test_ensure_chrome_extracted_roundtrip(tmp_path: Path) -> None:
    zip_path = tmp_path / cr.CHROME_HEADLESS_SHELL_ZIP_DEST
    extract_root = tmp_path / cr.CHROME_HEADLESS_SHELL_EXTRACT_DIR
    _make_chrome_zip(zip_path)

    exe = ensure_chrome_extracted(zip_path, extract_root)
    assert exe is not None and exe.is_file()
    # Idempotent: a second call short-circuits on the existing exe.
    assert ensure_chrome_extracted(zip_path, extract_root) == exe


def test_ensure_chrome_extracted_missing_zip(tmp_path: Path) -> None:
    assert ensure_chrome_extracted(tmp_path / "nope.zip", tmp_path / "t") is None


def test_ensure_chrome_extracted_rejects_zip_slip(tmp_path: Path) -> None:
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escape.txt", b"boom")
    with pytest.raises(RemotionCaptionError):
        ensure_chrome_extracted(evil, tmp_path / "extract")
    assert not (tmp_path / "escape.txt").exists()


# --------------------------------------------------------------------------- #
# resolution chains
# --------------------------------------------------------------------------- #
def test_resolve_node_exe_env_override_wins(tmp_path: Path, dev_root: Path) -> None:
    override = tmp_path / "custom node.exe"
    override.write_bytes(b"x")
    settings_exe = tmp_path / "settings-node.exe"
    settings_exe.write_bytes(b"x")
    result = resolve_node_exe(
        {cr.SETTING_NODE_EXE: str(settings_exe)},
        env={cr.ENV_NODE_EXE: str(override)},
        dev_root=dev_root,
    )
    assert result == str(override)


def test_resolve_node_exe_env_missing_file_falls_through(tmp_path: Path, dev_root: Path) -> None:
    settings_exe = tmp_path / "settings-node.exe"
    settings_exe.write_bytes(b"x")
    result = resolve_node_exe(
        {cr.SETTING_NODE_EXE: str(settings_exe)},
        env={cr.ENV_NODE_EXE: str(tmp_path / "ghost.exe")},
        dev_root=dev_root,
    )
    assert result == str(settings_exe)


def test_resolve_node_exe_dev_electron_fallback(dev_root: Path) -> None:
    result = resolve_node_exe({}, env={}, dev_root=dev_root)
    assert result == str(_dev_electron(dev_root))


def test_resolve_node_exe_nothing_raises(tmp_path: Path) -> None:
    with pytest.raises(RemotionCaptionError, match="node runner not found"):
        resolve_node_exe({}, env={}, dev_root=tmp_path / "empty")


def test_resolve_render_js_chain(tmp_path: Path, dev_root: Path) -> None:
    dev = resolve_render_js({}, env={}, dev_root=dev_root)
    assert dev == str(dev_root / "app" / "render-cli" / "dist" / "render.js")

    override = tmp_path / "elsewhere render.js"
    override.write_text("//", encoding="utf-8")
    assert resolve_render_js({}, env={cr.ENV_RENDER_JS: str(override)}, dev_root=dev_root) == str(override)
    assert resolve_render_js({cr.SETTING_RENDER_JS: str(override)}, env={}, dev_root=dev_root) == str(override)
    with pytest.raises(RemotionCaptionError, match="render.js not found"):
        resolve_render_js({}, env={}, dev_root=tmp_path / "empty")


def test_resolve_bundle_dir_chain(tmp_path: Path, dev_root: Path) -> None:
    dev = resolve_bundle_dir({}, env={}, dev_root=dev_root)
    assert dev == str(dev_root / "app" / "render-cli" / "out" / "remotion-bundle")

    override = tmp_path / "custom bundle"
    override.mkdir()
    assert resolve_bundle_dir({}, env={cr.ENV_BUNDLE_DIR: str(override)}, dev_root=dev_root) == str(override)
    assert resolve_bundle_dir({cr.SETTING_BUNDLE_DIR: str(override)}, env={}, dev_root=dev_root) == str(override)
    with pytest.raises(RemotionCaptionError, match="bundle not found"):
        resolve_bundle_dir({}, env={}, dev_root=tmp_path / "empty")


def test_resolve_chromium_chain_and_soft_miss(tmp_path: Path) -> None:
    # Nothing anywhere -> None (soft miss, never raises).
    assert resolve_chromium({}, env={}, assets_root=tmp_path / "empty") is None

    # Managed asset: the pinned zip is extracted on first use.
    assets_root = tmp_path / "assets"
    _make_chrome_zip(assets_root / cr.CHROME_HEADLESS_SHELL_ZIP_DEST)
    extracted = resolve_chromium({}, env={}, assets_root=assets_root)
    assert extracted is not None
    assert Path(extracted).is_file()

    # env beats everything.
    env_exe = tmp_path / "env-chrome.exe"
    env_exe.write_bytes(b"x")
    assert resolve_chromium({}, env={cr.ENV_CHROME: str(env_exe)}, assets_root=assets_root) == str(env_exe)


# --------------------------------------------------------------------------- #
# job-file shape
# --------------------------------------------------------------------------- #
def test_build_job_shape_and_rebase() -> None:
    job = build_job(
        "C:/clips/clip one.mp4",
        CUES,
        "C:/out/short one.mp4",
        bundle_dir="C:/bundle",
        style="bounce",
        source_start=120.0,
        total_sec=8.5,
    )
    assert set(job.keys()) == {"bundleDir", "composition", "inputProps", "outPath"}
    assert job["bundleDir"] == "C:/bundle"
    assert job["composition"] == COMPOSITION_ID
    assert job["outPath"] == "C:/out/short one.mp4"

    props = job["inputProps"]
    assert set(props.keys()) == {
        "videoSrc",
        "cues",
        "style",
        "width",
        "height",
        "durationInSeconds",
    }
    assert props["videoSrc"] == "C:/clips/clip one.mp4"
    assert props["style"] == "bounce"
    assert props["width"] == 1080 and props["height"] == 1920
    assert props["durationInSeconds"] == 8.5

    # Cue times re-based to clip-local t=0 (sourceStart subtracted, §4).
    assert props["cues"][0]["start"] == 0.0
    assert props["cues"][0]["end"] == 1.5
    assert props["cues"][1]["start"] == 1.5
    # Text travels verbatim as JSON — braces need no ASS-style escaping.
    assert props["cues"][1]["text"] == "{braces} stay literal"
    # The payload is JSON-serializable as-is.
    json.dumps(job)


def test_build_job_drops_cues_entirely_before_clip() -> None:
    cues = [
        {"index": 0, "start": 10.0, "end": 11.0, "text": "before the clip"},
        {"index": 1, "start": 120.5, "end": 122.0, "text": "inside"},
    ]
    job = build_job("c.mp4", cues, "o.mp4", bundle_dir="b", source_start=120.0, total_sec=5.0)
    rendered = job["inputProps"]["cues"]
    assert len(rendered) == 1
    assert rendered[0]["text"] == "inside"


def test_build_job_duration_falls_back_to_last_cue_end() -> None:
    job = build_job("c.mp4", CUES, "o.mp4", bundle_dir="b", source_start=120.0)
    assert job["inputProps"]["durationInSeconds"] == 4.0  # 124.0 - 120.0
    empty = build_job("c.mp4", [], "o.mp4", bundle_dir="b")
    assert empty["inputProps"]["durationInSeconds"] == 1.0  # floor


def test_build_job_chromium_only_when_provided() -> None:
    without = build_job("c.mp4", [], "o.mp4", bundle_dir="b")
    assert "chromiumExecutable" not in without
    with_chrome = build_job("c.mp4", [], "o.mp4", bundle_dir="b", chromium_executable="C:/chs/chs.exe")
    assert with_chrome["chromiumExecutable"] == "C:/chs/chs.exe"


def test_build_job_rejects_unknown_style() -> None:
    with pytest.raises(RemotionCaptionError, match="unknown caption style"):
        build_job("c.mp4", [], "o.mp4", bundle_dir="b", style="comic-sans")


def test_build_job_omits_hook_title_by_default() -> None:
    """P3-A: with no hook_title the inputProps shape is byte-identical to the
    frozen T4a contract (no hookTitle key)."""
    job = build_job("c.mp4", [], "o.mp4", bundle_dir="b")
    assert "hookTitle" not in job["inputProps"]
    blank = build_job("c.mp4", [], "o.mp4", bundle_dir="b", hook_title="   ")
    assert "hookTitle" not in blank["inputProps"]  # blank is treated as absent


def test_build_job_includes_hook_title_when_given() -> None:
    job = build_job("c.mp4", [], "o.mp4", bundle_dir="b", hook_title="The Hook")
    assert job["inputProps"]["hookTitle"] == "The Hook"
    # Still JSON-serialisable; text travels verbatim (no ASS-style escaping).
    json.dumps(job)


# --------------------------------------------------------------------------- #
# P4 §8a: emphasis spans + trailing emoji pass through to the render job
# --------------------------------------------------------------------------- #
def test_build_job_carries_emphasis_and_emoji() -> None:
    cues = [
        {
            "index": 1,
            "start": 0.0,
            "end": 1.0,
            "text": "FREE money",
            "emphasis": [
                {"start": 0, "end": 4, "kind": "caps"},
                {"start": 5, "end": 10, "kind": "keyword"},
            ],
            "emoji": "\U0001f525",
        }
    ]
    job = build_job("c.mp4", cues, "o.mp4", bundle_dir="b", total_sec=1.0)
    rendered = job["inputProps"]["cues"][0]
    assert rendered["emphasis"] == [
        {"start": 0, "end": 4, "kind": "caps"},
        {"start": 5, "end": 10, "kind": "keyword"},
    ]
    assert rendered["emoji"] == "\U0001f525"
    json.dumps(job)  # still serialisable


def test_build_job_omits_emphasis_and_emoji_when_absent() -> None:
    # No annotation -> the cue shape stays byte-identical to the frozen contract.
    job = build_job("c.mp4", CUES, "o.mp4", bundle_dir="b", source_start=120.0)
    for cue in job["inputProps"]["cues"]:
        assert "emphasis" not in cue
        assert "emoji" not in cue


def test_build_job_drops_malformed_emphasis_spans() -> None:
    cues = [
        {
            "index": 1,
            "start": 0.0,
            "end": 1.0,
            "text": "hi",
            "emphasis": [
                {"start": 0, "end": 2, "kind": "long"},  # valid
                {"start": 2, "end": 2, "kind": "x"},  # zero-length -> dropped
                {"start": "a", "end": 5},  # non-numeric -> dropped
                "not-a-span",  # not a mapping -> dropped
            ],
        }
    ]
    job = build_job("c.mp4", cues, "o.mp4", bundle_dir="b", total_sec=1.0)
    assert job["inputProps"]["cues"][0]["emphasis"] == [{"start": 0, "end": 2, "kind": "long"}]


# --------------------------------------------------------------------------- #
# argv + spawn env
# --------------------------------------------------------------------------- #
def test_build_argv_is_a_plain_list() -> None:
    argv = build_argv("C:/app/electron.exe", "C:/cli/render.js", "C:/tmp/job 1.json")
    assert argv == ["C:/app/electron.exe", "C:/cli/render.js", "C:/tmp/job 1.json"]


def test_build_spawn_env_sets_electron_run_as_node() -> None:
    env = build_spawn_env({"PATH": "/usr/bin", "HOME": "/home/u"})
    assert env["ELECTRON_RUN_AS_NODE"] == "1"
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/u"


# --------------------------------------------------------------------------- #
# stdout protocol parsing
# --------------------------------------------------------------------------- #
def test_parse_render_ok() -> None:
    assert parse_render_ok("RENDER_OK C:/out/My Short 01.mp4\n") == ("C:/out/My Short 01.mp4")
    assert parse_render_ok("RENDER_OK") is None
    assert parse_render_ok("something else") is None
    assert parse_render_ok("RENDER_PROGRESS 50") is None


def test_parse_render_progress() -> None:
    assert parse_render_progress("RENDER_PROGRESS 42\n") == 42.0
    assert parse_render_progress("RENDER_PROGRESS 250") == 100.0  # clamped
    assert parse_render_progress("RENDER_PROGRESS abc") is None
    assert parse_render_progress("RENDER_OK x.mp4") is None


# --------------------------------------------------------------------------- #
# run_render: drained pipes, progress, cancel, failure
# --------------------------------------------------------------------------- #
def test_run_render_success_parses_ok_and_drains_both_pipes() -> None:
    popen = _FakePopen(
        stdout_lines=[
            "RENDER_PROGRESS 10\n",
            "noise the renderer printed\n",
            "RENDER_PROGRESS 60\n",
            "RENDER_OK C:/out/clip with spaces.mp4\n",
        ],
        stderr_lines=["chromium chatter\n"] * 50,  # more than the tail bound
        code=0,
    )
    pcts: list[float] = []
    code, ok_path, tail = run_render(
        ["exe", "render.js", "job.json"],
        env={"ELECTRON_RUN_AS_NODE": "1"},
        on_progress=lambda p, m: pcts.append(p),
        popen=popen,
    )
    assert code == 0
    assert ok_path == "C:/out/clip with spaces.mp4"
    assert pcts == [10.0, 60.0]
    # A6 lesson 2: BOTH pipes were read to exhaustion.
    assert popen.proc is not None
    assert popen.proc.stdout.consumed
    assert popen.proc.stderr.consumed
    # bounded stderr tail
    assert len(tail) <= 40
    # argv list + no shell + env forwarded
    assert popen.captured["argv"] == ["exe", "render.js", "job.json"]
    assert popen.captured["kwargs"].get("shell") in (None, False)
    assert popen.captured["kwargs"]["env"]["ELECTRON_RUN_AS_NODE"] == "1"
    assert popen.captured["kwargs"]["text"] is True


def test_run_render_failure_returns_code_and_stderr_tail() -> None:
    popen = _FakePopen(
        stdout_lines=["RENDER_PROGRESS 5\n"],
        stderr_lines=["RENDER_FAIL composition not found\n"],
        code=1,
    )
    code, ok_path, tail = run_render(["exe", "r.js", "j.json"], popen=popen)
    assert code == 1
    assert ok_path is None
    assert any("composition not found" in line for line in tail)
    assert popen.proc is not None and popen.proc.stderr.consumed


def test_run_render_cancel_terminates_process() -> None:
    popen = _FakePopen(
        stdout_lines=["RENDER_PROGRESS 1\n", "RENDER_PROGRESS 2\n"],
        code=1,
    )
    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # cancel on the second line

    code, ok_path, _tail = run_render(["exe", "r.js", "j.json"], should_cancel=should_cancel, popen=popen)
    assert popen.proc is not None and popen.proc.terminated
    assert ok_path is None


def test_run_render_rejects_shell_strings() -> None:
    with pytest.raises(TypeError):
        run_render("exe render.js job.json")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# RemotionCaptionEngine end-to-end (fake popen, tmp runtime)
# --------------------------------------------------------------------------- #
def _engine(dev_root: Path, popen: _FakePopen, tmp_path: Path) -> RemotionCaptionEngine:
    return RemotionCaptionEngine(
        settings={},
        popen=popen,
        env={},  # no env overrides; spawn env gains only ELECTRON_RUN_AS_NODE
        dev_root=dev_root,
        assets_root=tmp_path / "assets-empty",
    )


def test_engine_render_success_full_flow(dev_root: Path, tmp_path: Path) -> None:
    out_path = "C:/out/final short.mp4"
    popen = _FakePopen(stdout_lines=[f"RENDER_OK {out_path}\n"], code=0)
    engine = _engine(dev_root, popen, tmp_path)

    result = engine.render(
        "C:/clips/clip 7.mp4",
        CUES,
        out_path,
        style="karaoke",
        source_start=120.0,
        total_sec=4.0,
    )
    assert result == out_path

    # argv: [node-runner exe, render.js, job.json] — resolved via the chain.
    argv = popen.captured["argv"]
    assert argv[0] == str(_dev_electron(dev_root))
    assert argv[1] == str(dev_root / "app" / "render-cli" / "dist" / "render.js")
    assert argv[2].endswith(".json")
    # ELECTRON_RUN_AS_NODE in the spawn env (A4).
    assert popen.captured["kwargs"]["env"]["ELECTRON_RUN_AS_NODE"] == "1"

    # The job file existed at spawn time with the frozen shape...
    job = popen.job_snapshot
    assert job is not None
    assert job["composition"] == COMPOSITION_ID
    assert job["outPath"] == out_path
    assert job["inputProps"]["style"] == "karaoke"
    assert job["inputProps"]["cues"][0]["start"] == 0.0
    assert job["inputProps"]["durationInSeconds"] == 4.0
    assert "chromiumExecutable" not in job  # empty assets root -> soft miss
    # ...and is cleaned up afterwards.
    assert not os.path.exists(argv[2])


def test_engine_render_includes_chromium_when_asset_present(dev_root: Path, tmp_path: Path) -> None:
    assets_root = tmp_path / "assets"
    _make_chrome_zip(assets_root / cr.CHROME_HEADLESS_SHELL_ZIP_DEST)
    popen = _FakePopen(stdout_lines=["RENDER_OK o.mp4\n"], code=0)
    engine = RemotionCaptionEngine(settings={}, popen=popen, env={}, dev_root=dev_root, assets_root=assets_root)
    engine.render("c.mp4", [], "o.mp4")
    job = popen.job_snapshot
    assert job is not None
    assert Path(job["chromiumExecutable"]).name.startswith("chrome-headless-shell")


def test_engine_render_failure_raises_with_stderr_tail(dev_root: Path, tmp_path: Path) -> None:
    popen = _FakePopen(
        stdout_lines=[],
        stderr_lines=["RENDER_FAIL bundleDir does not exist\n"],
        code=1,
    )
    engine = _engine(dev_root, popen, tmp_path)
    with pytest.raises(RemotionCaptionError, match="bundleDir does not exist"):
        engine.render("c.mp4", CUES, "o.mp4", source_start=120.0)


def test_engine_render_exit_zero_without_render_ok_is_a_failure(dev_root: Path, tmp_path: Path) -> None:
    popen = _FakePopen(stdout_lines=["RENDER_PROGRESS 99\n"], code=0)
    engine = _engine(dev_root, popen, tmp_path)
    with pytest.raises(RemotionCaptionError, match="RENDER_OK missing"):
        engine.render("c.mp4", CUES, "o.mp4", source_start=120.0)


def test_engine_render_cleans_job_file_on_failure(dev_root: Path, tmp_path: Path) -> None:
    popen = _FakePopen(stdout_lines=[], code=1)
    engine = _engine(dev_root, popen, tmp_path)
    with pytest.raises(RemotionCaptionError):
        engine.render("c.mp4", [], "o.mp4")
    job_path = popen.captured["argv"][2]
    assert not os.path.exists(job_path)


def test_engine_render_rejects_softmux(dev_root: Path, tmp_path: Path) -> None:
    popen = _FakePopen(stdout_lines=["RENDER_OK o.mp4\n"], code=0)
    engine = _engine(dev_root, popen, tmp_path)
    with pytest.raises(RemotionCaptionError, match="only burns"):
        engine.render("c.mp4", [], "o.mp4", burn=False)
    assert popen.captured == {}  # never spawned


def test_engine_render_streams_progress(dev_root: Path, tmp_path: Path) -> None:
    popen = _FakePopen(
        stdout_lines=[
            "RENDER_PROGRESS 25\n",
            "RENDER_PROGRESS 75\n",
            "RENDER_OK o.mp4\n",
        ],
        code=0,
    )
    engine = _engine(dev_root, popen, tmp_path)
    seen: list[float] = []
    engine.render("c.mp4", [], "o.mp4", on_progress=lambda p, m: seen.append(p))
    assert seen == [25.0, 75.0]


# --------------------------------------------------------------------------- #
# transient-compositor signature matcher + subprocess retry (batch robustness)
# --------------------------------------------------------------------------- #
def test_is_transient_compositor_failure_matches_known_signatures() -> None:
    # Every documented signature is detected, case-insensitively.
    assert is_transient_compositor_failure(["RENDER_FAIL Error: Request closed"])
    assert is_transient_compositor_failure(["Could not extract frame from compositor"])
    assert is_transient_compositor_failure(["chatter", "Target closed", "more"])
    assert is_transient_compositor_failure(["NAVIGATION FAILED while loading"])
    # Sanity: each constant is its own match.
    for sig in TRANSIENT_SIGNATURES:
        assert is_transient_compositor_failure([sig.upper()])


def test_is_transient_compositor_failure_ignores_non_transient() -> None:
    assert not is_transient_compositor_failure([])
    assert not is_transient_compositor_failure(["RENDER_FAIL composition not found"])
    assert not is_transient_compositor_failure(["bundleDir does not exist"])


def test_engine_render_retries_once_then_succeeds_on_transient(dev_root: Path, tmp_path: Path) -> None:
    """A first spawn that dies with a transient compositor signature is retried
    ONCE (fresh process); the second spawn succeeds -> out_path returned."""
    out_path = "C:/out/batch clip.mp4"
    popen = _SequencedPopen(
        [
            # attempt 1: transient compositor death, non-zero exit, no RENDER_OK
            ([], ["RENDER_FAIL Error: Request closed"], 1),
            # attempt 2: clean success
            ([f"RENDER_OK {out_path}\n"], [], 0),
        ]
    )
    engine = _engine(dev_root, popen, tmp_path)

    result = engine.render("C:/clips/c.mp4", CUES, out_path, source_start=120.0)
    assert result == out_path
    # Exactly ONE retry (two spawns total).
    assert popen.calls == 2
    assert len(popen.argv_log) == 2
    # Both spawns read the SAME job file (job written once, reused on retry).
    assert popen.argv_log[0][2] == popen.argv_log[1][2]
    # Both child procs were fully drained on each attempt (A6 lesson 2).
    for proc in popen.procs:
        assert proc.stdout.consumed
        assert proc.stderr.consumed
    # Job file cleaned up after success.
    assert not os.path.exists(popen.argv_log[-1][2])


def test_engine_render_raises_after_retries_when_transient_persists(dev_root: Path, tmp_path: Path) -> None:
    """A transient signature on EVERY attempt -> RemotionCaptionError after the
    bounded retries; both pipes drained on every spawn; no hang."""
    transient = ([], ["Could not extract frame from compositor"], 1)
    popen = _SequencedPopen([transient, transient, transient])
    engine = _engine(dev_root, popen, tmp_path)

    with pytest.raises(RemotionCaptionError, match="remotion render failed"):
        engine.render("C:/clips/c.mp4", CUES, "o.mp4", source_start=120.0)

    # Bounded: exactly MAX_SUBPROCESS_ATTEMPTS spawns, no more.
    assert popen.calls == MAX_SUBPROCESS_ATTEMPTS
    # Both pipes drained on every attempt (the proven freeze guard).
    for proc in popen.procs:
        assert proc.stdout.consumed
        assert proc.stderr.consumed
    # Job file cleaned up even on terminal failure.
    assert not os.path.exists(popen.argv_log[-1][2])


def test_engine_render_does_not_retry_non_transient_failure(dev_root: Path, tmp_path: Path) -> None:
    """A non-transient failure is surfaced immediately — NO wasted retry."""
    popen = _SequencedPopen(
        [
            ([], ["RENDER_FAIL composition not found"], 1),
            # A success here would be a BUG (we must not reach a 2nd spawn).
            (["RENDER_OK should-not-happen.mp4\n"], [], 0),
        ]
    )
    engine = _engine(dev_root, popen, tmp_path)

    with pytest.raises(RemotionCaptionError, match="composition not found"):
        engine.render("C:/clips/c.mp4", CUES, "o.mp4", source_start=120.0)
    # Only ONE spawn — a non-transient error short-circuits the retry loop.
    assert popen.calls == 1


def test_engine_render_does_not_retry_on_cancel(dev_root: Path, tmp_path: Path) -> None:
    """A cooperative cancel ends the loop immediately even though the exit is
    non-zero — a user cancel is never a transient-compositor retry."""
    # stdout has a transient-looking stderr but the cancel must win.
    popen = _SequencedPopen(
        [
            (["RENDER_PROGRESS 5\n"], ["Request closed"], 1),
            (["RENDER_OK nope.mp4\n"], [], 0),
        ]
    )
    engine = _engine(dev_root, popen, tmp_path)

    with pytest.raises(RemotionCaptionError):
        engine.render(
            "C:/clips/c.mp4",
            CUES,
            "o.mp4",
            source_start=120.0,
            should_cancel=lambda: True,
        )
    # Cancel short-circuits: exactly one spawn, no retry.
    assert popen.calls == 1
