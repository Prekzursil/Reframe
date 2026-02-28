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


def _probe(url: str, token: str) -> ProbeResult:
    safe_url = normalize_https_url(url, allowed_hosts={"huggingface.co"})
    ts = datetime.now(timezone.utc).isoformat()

    if not token:
        return ProbeResult(
            timestamp_utc=ts,
            status="missing_token",
            model="",
            url=safe_url,
            http_status=None,
            error="HF_TOKEN/HUGGINGFACE_TOKEN is missing.",
        )

    request = urllib.request.Request(
        safe_url,
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
                model="",
                url=safe_url,
                http_status=getattr(response, "status", 200),
                error=None,
            )
    except urllib.error.HTTPError as exc:
        status = "blocked_403"
        return ProbeResult(
            timestamp_utc=ts,
            status=status,
            model="",
            url=safe_url,
            http_status=int(exc.code),
            error=str(exc),
        )
    except urllib.error.URLError as exc:
        return ProbeResult(
            timestamp_utc=ts,
            status="network_error",
            model="",
            url=safe_url,
            http_status=None,
            error=str(exc.reason),
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Probe Hugging Face gated model access for pyannote models.")
    parser.add_argument("--model", default="pyannote/speaker-diarization-3.1")
    parser.add_argument("--token", default="", help="Optional HF token override")
    parser.add_argument("--out-json", default="", help="Optional output JSON path")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    model = str(args.model or "").strip() or "pyannote/speaker-diarization-3.1"
    url = f"https://huggingface.co/{model}/resolve/main/config.yaml"

    token = _load_token(args.token, repo_root)
    result = _probe(url, token)
    result.model = model

    payload = asdict(result)
    out_json = Path(args.out_json) if args.out_json else None
    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))

    if result.status == "ok":
        return 0
    if result.status == "missing_token":
        return 3
    if result.status == "blocked_403":
        return 4
    if result.status == "network_error":
        return 5
    return 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
