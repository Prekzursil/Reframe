#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert Applitools visual checks are zero-diff.")
    parser.add_argument("--provider", choices=["applitools"], default="applitools")
    parser.add_argument("--applitools-results", default="", help="Path to Applitools results JSON")
    parser.add_argument("--out-json", default="visual-zero/visual.json", help="Output JSON path")
    parser.add_argument("--out-md", default="visual-zero/visual.md", help="Output markdown path")
    return parser.parse_args()


def _safe_path(raw: str, fallback: str, *, base: Path | None = None) -> Path:
    root = (base or Path.cwd()).resolve()
    candidate = Path((raw or "").strip() or fallback).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace root: {candidate}") from exc
    return resolved


def _run_applitools(args: argparse.Namespace) -> tuple[str, dict[str, Any], list[str]]:
    findings: list[str] = []
    results_path = _safe_path(args.applitools_results, "")
    details: dict[str, Any] = {
        "results_path": str(results_path) if args.applitools_results else "",
        "unresolved": None,
        "mismatches": None,
        "missing": None,
    }

    if not args.applitools_results:
        findings.append("--applitools-results is required for provider=applitools.")
        return "fail", details, findings
    if not results_path.exists():
        findings.append(f"Applitools results file not found: {results_path}")
        return "fail", details, findings

    payload = json.loads(results_path.read_text(encoding="utf-8"))
    unresolved = payload.get("unresolved")
    mismatches = payload.get("mismatches")
    missing = payload.get("missing")

    details["unresolved"] = unresolved
    details["mismatches"] = mismatches
    details["missing"] = missing

    for key, value in (("unresolved", unresolved), ("mismatches", mismatches), ("missing", missing)):
        if value is None:
            findings.append(f"Applitools results missing '{key}' field.")
        elif int(value) != 0:
            findings.append(f"Applitools reports {key}={value} (expected 0).")

    return ("pass" if not findings else "fail"), details, findings


def _render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Visual Zero Gate",
        "",
        f"- Provider: `{payload['provider']}`",
        f"- Status: `{payload['status']}`",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        "",
        "## Details",
    ]

    for key, value in (payload.get("details") or {}).items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(["", "## Findings"])
    findings = payload.get("findings") or []
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()

    status, details, findings = _run_applitools(args)

    payload = {
        "provider": args.provider,
        "status": status,
        "details": details,
        "findings": findings,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    try:
        out_json = _safe_path(args.out_json, "visual-zero/visual.json")
        out_md = _safe_path(args.out_md, "visual-zero/visual.md")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_md(payload), encoding="utf-8")
    print(out_md.read_text(encoding="utf-8"), end="")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

