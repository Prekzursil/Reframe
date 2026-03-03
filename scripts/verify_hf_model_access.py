#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from security_helpers import normalize_https_url


@dataclass
class ProbeResult:
    timestamp_utc: str
    status: str
    model: str
    url: str
    http_status: int | None
    error: str | None


def _load_token(cli_token: str | None, repo_root: Path) -> str:
    if cli_token:
        token = cli_token.strip()
        if token:
            return token

    for key in ("HF_TOKEN", "HUGGINGFACE_TOKEN"):
        token = os.getenv(key, "").strip()
        if token:
            return token

    env_path = repo_root / ".env"
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() not in {"HF_TOKEN", "HUGGINGFACE_TOKEN"}:
                continue
            candidate = value.strip().strip("\"'")
            if candidate:
                return candidate

    return ""


def _probe(url: str, token: str, *, model: str) -> ProbeResult:
    safe_url = normalize_https_url(url, allowed_hosts={"huggingface.co"})
    ts = datetime.now(timezone.utc).isoformat()

    if not token:
        return ProbeResult(
            timestamp_utc=ts,
            status="missing_token",
            model=model,
            url=safe_url,
            http_status=None,
            error="HF_TOKEN/HUGGINGFACE_TOKEN is missing.",
        )

    request = urllib.request.Request(
        safe_url,
        method="HEAD",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "reframe-hf-model-access-probe",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return ProbeResult(
                timestamp_utc=ts,
                status="ok",
                model=model,
                url=safe_url,
                http_status=getattr(response, "status", 200),
                error=None,
            )
    except urllib.error.HTTPError as exc:
        status = "blocked_403" if int(exc.code) == 403 else f"http_{int(exc.code)}"
        return ProbeResult(
            timestamp_utc=ts,
            status=status,
            model=model,
            url=safe_url,
            http_status=int(exc.code),
            error=str(exc),
        )
    except urllib.error.URLError as exc:
        return ProbeResult(
            timestamp_utc=ts,
            status="network_error",
            model=model,
            url=safe_url,
            http_status=None,
            error=str(exc.reason),
        )


def _aggregate_status(results: list[ProbeResult]) -> str:
    statuses = {r.status for r in results}
    if "missing_token" in statuses:
        return "missing_token"
    if "blocked_403" in statuses:
        return "blocked_403"
    if any(s.startswith("http_") for s in statuses):
        return "network_error"
    if "network_error" in statuses:
        return "network_error"
    if statuses == {"ok"}:
        return "ok"
    return "blocked_403"


def _safe_output_path(raw: str, *, base: Path) -> Path:
    candidate = Path((raw or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Output path escapes workspace root: {candidate}") from exc
    return resolved


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Probe Hugging Face gated model access for pyannote models.")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Model id to probe (repeat flag for multiple models). Defaults to required pyannote dependencies.",
    )
    parser.add_argument("--token", default="", help="Optional HF token override")
    parser.add_argument("--out-json", default="", help="Optional output JSON path")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    models = [m.strip() for m in args.model if str(m).strip()]
    if not models:
        models = [
            "pyannote/speaker-diarization-3.1",
            "pyannote/segmentation-3.0",
            "pyannote/speaker-diarization-community-1",
        ]

    token = _load_token(args.token, repo_root)
    results = [
        _probe(f"https://huggingface.co/{model}/resolve/main/config.yaml", token, model=model)
        for model in models
    ]
    status = _aggregate_status(results)

    # Keep top-level compatibility fields while exposing full per-model probe details.
    primary = next((r for r in results if r.status != "ok"), results[0])
    payload = {
        **asdict(primary),
        "status": status,
        "models": models,
        "probes": [asdict(r) for r in results],
    }
    out_json = _safe_output_path(args.out_json, base=repo_root) if args.out_json else None
    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))

    if status == "ok":
        return 0
    if status == "missing_token":
        return 3
    if status == "blocked_403":
        return 4
    if status == "network_error":
        return 5
    return 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
