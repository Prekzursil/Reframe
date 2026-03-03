#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CoverageStats:
    name: str
    path: str
    covered: int
    total: int

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 100.0
        return (self.covered / self.total) * 100.0


_PAIR_RE = re.compile(r"^(?P<name>[^=]+)=(?P<path>.+)$")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert 100% coverage for all declared components.")
    parser.add_argument("--xml", action="append", default=[], help="Coverage XML input: name=path")
    parser.add_argument("--lcov", action="append", default=[], help="LCOV input: name=path")
    parser.add_argument("--out-json", default="coverage-100/coverage.json", help="Output JSON path")
    parser.add_argument("--out-md", default="coverage-100/coverage.md", help="Output markdown path")
    return parser.parse_args()


def parse_named_path(value: str) -> tuple[str, Path]:
    match = _PAIR_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid input '{value}'. Expected format: name=path")
    return match.group("name").strip(), Path(match.group("path").strip())


def parse_coverage_xml(name: str, path: Path) -> CoverageStats:
    root = ET.fromstring(path.read_text(encoding="utf-8"))

    lines_valid = root.attrib.get("lines-valid")
    lines_covered = root.attrib.get("lines-covered")

    if lines_valid is not None and lines_covered is not None:
        total = int(float(lines_valid))
        covered = int(float(lines_covered))
        return CoverageStats(name=name, path=str(path), covered=covered, total=total)

    total = 0
    covered = 0
    for line in root.findall(".//line"):
        hits_raw = line.attrib.get("hits")
        if hits_raw is None:
            continue
        total += 1
        try:
            if int(float(hits_raw)) > 0:
                covered += 1
        except ValueError:
            continue

    return CoverageStats(name=name, path=str(path), covered=covered, total=total)


def parse_lcov(name: str, path: Path) -> CoverageStats:
    total = 0
    covered = 0

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("LF:"):
            total += int(line.split(":", 1)[1])
        elif line.startswith("LH:"):
            covered += int(line.split(":", 1)[1])

    return CoverageStats(name=name, path=str(path), covered=covered, total=total)


def evaluate(stats: list[CoverageStats]) -> tuple[str, list[str]]:
    findings: list[str] = []
    for item in stats:
        if item.percent < 100.0:
            findings.append(f"{item.name} coverage below 100%: {item.percent:.2f}% ({item.covered}/{item.total})")

    combined_total = sum(item.total for item in stats)
    combined_covered = sum(item.covered for item in stats)
    combined = 100.0 if combined_total <= 0 else (combined_covered / combined_total) * 100.0

    if combined < 100.0:
        findings.append(f"combined coverage below 100%: {combined:.2f}% ({combined_covered}/{combined_total})")

    status = "pass" if not findings else "fail"
    return status, findings


def _render_md(payload: dict) -> str:
    lines = [
        "# Coverage 100 Gate",
        "",
        f"- Status: `{payload['status']}`",
        f"- Timestamp (UTC): `{payload['timestamp_utc']}`",
        "",
        "## Components",
    ]

    for item in payload.get("components", []):
        lines.append(
            f"- `{item['name']}`: `{item['percent']:.2f}%` ({item['covered']}/{item['total']}) from `{item['path']}`"
        )

    if not payload.get("components"):
        lines.append("- None")

    lines.extend(["", "## Findings"])
    findings = payload.get("findings") or []
    if findings:
        lines.extend(f"- {finding}" for finding in findings)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()

    stats: list[CoverageStats] = []
    for item in args.xml:
        name, path = parse_named_path(item)
        stats.append(parse_coverage_xml(name, path))
    for item in args.lcov:
        name, path = parse_named_path(item)
        stats.append(parse_lcov(name, path))

    if not stats:
        raise SystemExit("No coverage files were provided; pass --xml and/or --lcov inputs.")

    status, findings = evaluate(stats)
    payload = {
        "status": status,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "components": [
            {
                "name": item.name,
                "path": item.path,
                "covered": item.covered,
                "total": item.total,
                "percent": item.percent,
            }
            for item in stats
        ],
        "findings": findings,
    }

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_render_md(payload), encoding="utf-8")
    print(out_md.read_text(encoding="utf-8"), end="")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
