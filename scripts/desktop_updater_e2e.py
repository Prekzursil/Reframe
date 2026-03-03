#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _tag_to_version(tag: str) -> str:
    value = str(tag or "").strip()
    if value.startswith("desktop-v"):
        return value[len("desktop-v") :]
    if value.startswith("v"):
        return value[1:]
    return value


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _helper_command(repo: Path, platform: str, old_tag: str, new_tag: str, work_dir: Path) -> list[str]:
    scripts_dir = repo / "scripts"
    if platform == "windows":
        helper = scripts_dir / "desktop_updater_e2e_windows.ps1"
        return [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-OldTag",
            old_tag,
            "-NewTag",
            new_tag,
            "-WorkDir",
            str(work_dir),
        ]
    if platform == "macos":
        helper = scripts_dir / "desktop_updater_e2e_macos.sh"
        return ["bash", str(helper), "--old-tag", old_tag, "--new-tag", new_tag, "--work-dir", str(work_dir)]
    if platform == "linux":
        helper = scripts_dir / "desktop_updater_e2e_linux.sh"
        return ["bash", str(helper), "--old-tag", old_tag, "--new-tag", new_tag, "--work-dir", str(work_dir)]
    raise ValueError(f"Unsupported platform: {platform}")


def _write_markdown(path: Path, payload: dict[str, Any], verify_cmd: list[str], helper_cmd: list[str]) -> None:
    lines: list[str] = []
    lines.append(f"# Desktop updater E2E ({payload.get('platform', 'unknown')})")
    lines.append("")
    lines.append(f"- timestamp_utc: `{payload.get('timestamp_utc')}`")
    lines.append(f"- success: `{payload.get('success')}`")
    lines.append(f"- old_tag: `{payload.get('old_tag')}`")
    lines.append(f"- new_tag: `{payload.get('new_tag')}`")
    lines.append(f"- expected_old_version: `{payload.get('expected_old_version')}`")
    lines.append(f"- expected_new_version: `{payload.get('expected_new_version')}`")
    lines.append(f"- observed_old_version: `{payload.get('observed_old_version')}`")
    lines.append(f"- observed_new_version: `{payload.get('observed_new_version')}`")
    if payload.get("error"):
        lines.append(f"- error: `{payload.get('error')}`")
    lines.append("")
    lines.append("## Commands")
    lines.append("")
    lines.append("```text")
    lines.append(shlex.join(verify_cmd))
    lines.append(shlex.join(helper_cmd))
    lines.append("```")
    lines.append("")
    lines.append("## Raw Helper Output")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload.get("helper_output", {}), indent=2, sort_keys=True))
    lines.append("```")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_workspace_path(raw: str, *, base: Path) -> Path:
    candidate = Path((raw or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace root: {candidate}") from exc
    return resolved


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Automated desktop updater E2E verification wrapper.")
    parser.add_argument("--old-tag", default="desktop-v0.1.6")
    parser.add_argument("--new-tag", default="desktop-v0.1.7")
    parser.add_argument("--platform", choices=["windows", "macos", "linux"], required=True)
    parser.add_argument("--out-md", default="")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args(argv)

    repo = _repo_root()
    stamp = _default_stamp()
    default_base = repo / "docs" / "plans" / f"{stamp}-updater-e2e-{args.platform}"
    try:
        out_md = _safe_workspace_path(args.out_md, base=repo) if args.out_md else default_base.with_suffix(".md")
        out_json = _safe_workspace_path(args.out_json, base=repo) if args.out_json else default_base.with_suffix(".json")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    work_dir = repo / ".tmp" / "desktop-updater-e2e" / args.platform
    work_dir.mkdir(parents=True, exist_ok=True)

    verify_cmd = [sys.executable, str(repo / "scripts" / "verify_desktop_updater_release.py")]
    verify = _run(verify_cmd, cwd=repo)
    if verify.returncode != 0:
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "platform": args.platform,
            "success": False,
            "old_tag": args.old_tag,
            "new_tag": args.new_tag,
            "expected_old_version": _tag_to_version(args.old_tag),
            "expected_new_version": _tag_to_version(args.new_tag),
            "observed_old_version": None,
            "observed_new_version": None,
            "error": "Updater manifest validation failed.",
            "verify": {
                "returncode": verify.returncode,
                "stdout": verify.stdout,
                "stderr": verify.stderr,
            },
            "helper_output": {},
        }
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _write_markdown(out_md, payload, verify_cmd, ["<helper-not-run>"])
        return 1

    helper_cmd = _helper_command(repo, args.platform, args.old_tag, args.new_tag, work_dir)
    env = os.environ.copy()
    if "GH_TOKEN" not in env and "GITHUB_TOKEN" in env:
        env["GH_TOKEN"] = env["GITHUB_TOKEN"]

    helper = _run(helper_cmd, cwd=repo, env=env)

    helper_obj: dict[str, Any]
    try:
        helper_obj = json.loads(helper.stdout.strip() or "{}")
    except json.JSONDecodeError:
        helper_obj = {
            "parse_error": "Helper output was not valid JSON.",
            "stdout": helper.stdout,
            "stderr": helper.stderr,
            "returncode": helper.returncode,
        }

    expected_old = _tag_to_version(args.old_tag)
    expected_new = _tag_to_version(args.new_tag)
    observed_old = str(helper_obj.get("observed_old_version") or "")
    observed_new = str(helper_obj.get("observed_new_version") or "")

    success = (
        helper.returncode == 0
        and observed_old == expected_old
        and observed_new == expected_new
        and bool(helper_obj.get("success", True))
    )

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": args.platform,
        "success": success,
        "old_tag": args.old_tag,
        "new_tag": args.new_tag,
        "expected_old_version": expected_old,
        "expected_new_version": expected_new,
        "observed_old_version": observed_old or None,
        "observed_new_version": observed_new or None,
        "error": None if success else "Observed versions did not match expected transition.",
        "verify": {
            "returncode": verify.returncode,
            "stdout": verify.stdout,
            "stderr": verify.stderr,
        },
        "helper": {
            "returncode": helper.returncode,
            "stderr": helper.stderr,
            "command": helper_cmd,
        },
        "helper_output": helper_obj,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_markdown(out_md, payload, verify_cmd, helper_cmd)

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
