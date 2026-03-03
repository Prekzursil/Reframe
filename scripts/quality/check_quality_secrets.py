#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REQUIRED_SECRETS = [
    "SONAR_TOKEN",
    "CODACY_API_TOKEN",
    "CODECOV_TOKEN",
    "SNYK_TOKEN",
    "SENTRY_AUTH_TOKEN",
    "APPLITOOLS_API_KEY",
    "PERCY_TOKEN",
    "BROWSERSTACK_USERNAME",
    "BROWSERSTACK_ACCESS_KEY",
]

DEFAULT_REQUIRED_VARS = [
    "SENTRY_ORG",
    "SENTRY_PROJECT_BACKEND",
    "SENTRY_PROJECT_WEB",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate required quality-gate secrets/variables are configured.")
    parser.add_argument("--required-secret", action="append", default=[], help="Additional required secret env var name")
    parser.add_argument("--required-var", action="append", default=[], help="Additional required variable env var name")
    parser.add_argument("--out-json", default="quality-secrets/secrets.json", help="Output JSON path")
    parser.add_argument("--out-md", default="quality-secrets/secrets.md", help="Output markdown path")
    return parser.parse_args()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def evaluate_env(required_secrets: list[str], required_vars: list[str]) -> dict[str, list[str]]:
    missing_secrets = [name for name in required_secrets if not str(os.environ.get(name, "")).strip()]
    missing_vars = [name for name in required_vars if not str(os.environ.get(name, "")).strip()]
    present_secrets = [name for name in required_secrets if name not in missing_secrets]
    present_vars = [name for name in required_vars if name not in missing_vars]
    return {
        "missing_secrets": missing_secrets,
        "missing_vars": missing_vars,
        "present_secrets": present_secrets,
        "present_vars": present_vars,
    }


def _render_md(payload: dict) -> str:
    lines = [
        "# Quality Secrets Preflight",
        "",
        f"- Status: `{payload['status']}`",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        "",
        "## Missing secrets",
    ]
    missing_secrets = payload.get("missing_secrets") or []
    if missing_secrets:
        lines.extend(f"- `{name}`" for name in missing_secrets)
    else:
        lines.append("- None")

    lines.extend(["", "## Missing variables"])
    missing_vars = payload.get("missing_vars") or []
    if missing_vars:
        lines.extend(f"- `{name}`" for name in missing_vars)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def _safe_output_path(raw: str, fallback: str, base: Path | None = None) -> Path:
    root = (base or Path.cwd()).resolve()
    candidate = Path((raw or "").strip() or fallback).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Output path escapes workspace root: {candidate}") from exc
    return resolved


def main() -> int:
    args = _parse_args()
    required_secrets = _dedupe(DEFAULT_REQUIRED_SECRETS + list(args.required_secret or []))
    required_vars = _dedupe(DEFAULT_REQUIRED_VARS + list(args.required_var or []))

    result = evaluate_env(required_secrets, required_vars)
    status = "pass" if not result["missing_secrets"] and not result["missing_vars"] else "fail"
    payload = {
        "status": status,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "required_secrets": required_secrets,
        "required_vars": required_vars,
        **result,
    }

    try:
        out_json = _safe_output_path(args.out_json, "quality-secrets/secrets.json")
        out_md = _safe_output_path(args.out_md, "quality-secrets/secrets.md")
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
