#!/usr/bin/env python3
from __future__ import annotations

import ast
import argparse
import fnmatch
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass
class CoverageStats:
    name: str
    path: str
    covered: int
    total: int
    file_stats: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 100.0
        return (self.covered / self.total) * 100.0


TARGET_RULES = (
    {
        "root": "apps/api/app",
        "ext": {".py"},
        "exclude": {"**/__pycache__/**", "**/tests/**", "**/test_*.py", "**/*_test.py"},
    },
    {
        "root": "services/worker",
        "ext": {".py"},
        "exclude": {"**/__pycache__/**", "**/tests/**", "**/test_*.py", "**/*_test.py"},
    },
    {
        "root": "packages/media-core/src/media_core",
        "ext": {".py"},
        "exclude": {"**/__pycache__/**", "**/tests/**", "**/test_*.py", "**/*_test.py"},
    },
    {
        "root": "scripts",
        "ext": {".py"},
        "exclude": {"**/__pycache__/**", "**/tests/**", "**/test_*.py", "**/*_test.py"},
    },
    {
        "root": "apps/web/src",
        "ext": {".ts", ".tsx"},
        "exclude": {
            "apps/web/src/*.test.ts",
            "apps/web/src/*.test.tsx",
            "apps/web/src/**/*.test.ts",
            "apps/web/src/**/*.test.tsx",
            "apps/web/src/**/__tests__/**",
            "apps/web/src/test/**",
        },
    },
    {
        "root": "apps/desktop/src",
        "ext": {".ts"},
        "exclude": {
            "apps/desktop/src/*.test.ts",
            "apps/desktop/src/**/*.test.ts",
            "apps/desktop/src/**/__tests__/**",
        },
    },
    {
        "root": "apps/desktop/src-tauri/src",
        "ext": {".rs"},
        "exclude": set(),
    },
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert strict 100% coverage for tracked first-party code.")
    parser.add_argument("--xml", action="append", default=[], help="Coverage XML input: name=path")
    parser.add_argument("--lcov", action="append", default=[], help="LCOV input: name=path")
    parser.add_argument("--out-json", default="coverage-100/coverage.json", help="Output JSON path")
    parser.add_argument("--out-md", default="coverage-100/coverage.md", help="Output markdown path")
    parser.add_argument(
        "--inventory-root",
        default=".",
        help="Workspace root used to collect tracked-code inventory (default: current directory)",
    )
    parser.add_argument(
        "--no-inventory-check",
        action="store_true",
        help="Disable tracked-code inventory validation",
    )
    return parser.parse_args()


def _resolve_relative_candidate(relative_root: Path, candidate: Path) -> Path:
    # LCOV often writes SF paths like "src/App.tsx" while report file is at apps/web/coverage/lcov.info.
    primary = (relative_root / candidate).resolve(strict=False)
    if primary.exists():
        return primary

    if relative_root.name.lower() == "coverage":
        parent_candidate = (relative_root.parent / candidate).resolve(strict=False)
        if parent_candidate.exists() or candidate.parts[:1] == ("src",):
            return parent_candidate

    return primary


def _normalize_path(raw: str, *, base: Path | None = None, relative_root: Path | None = None) -> str:
    text = (raw or "").strip().replace("\\", "/")
    if text:
        candidate = Path(text)
        resolved: Path | None = None
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
        elif relative_root is not None:
            resolved = _resolve_relative_candidate(relative_root, candidate)

        if base is not None and resolved is not None:
            try:
                text = str(resolved.relative_to(base.resolve())).replace("\\", "/")
            except Exception:
                text = str(resolved).replace("\\", "/")
        elif resolved is not None:
            text = str(resolved).replace("\\", "/")

    while text.startswith("./"):
        text = text[2:]
    return text


def parse_named_path(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"Invalid input '{value}'. Expected format: name=path")
    name, path = value.split("=", 1)
    name = name.strip()
    path = Path(path.strip())
    if not name or not path:
        raise ValueError(f"Invalid input '{value}'. Expected format: name=path")
    return name, path


def _sum_file_stats(file_stats: dict[str, tuple[int, int]]) -> tuple[int, int]:
    covered = sum(v[0] for v in file_stats.values())
    total = sum(v[1] for v in file_stats.values())
    return covered, total


def _xml_source_roots(root: ET.Element) -> list[str]:
    sources: list[str] = []
    for source in root.findall(".//sources/source"):
        raw = (source.text or "").strip()
        if raw:
            sources.append(raw)
    return sources


def _normalize_xml_filename(filename: str, *, source_roots: list[str], base: Path | None, xml_path: Path) -> str:
    if Path(filename).is_absolute():
        return _normalize_path(filename, base=base)

    if source_roots:
        first_normalized: str | None = None
        for src in source_roots:
            candidate = (Path(src) / filename).resolve(strict=False)
            normalized = _normalize_path(str(candidate), base=base)
            if not first_normalized and normalized and normalized != filename:
                first_normalized = normalized
            if candidate.exists():
                return normalized
        if first_normalized:
            return first_normalized

    return _normalize_path(filename, base=base, relative_root=xml_path.parent)


def parse_coverage_xml(name: str, path: Path, *, base: Path | None = None) -> CoverageStats:
    file_stats: dict[str, tuple[int, int]] = {}

    tree = ET.parse(path)
    root = tree.getroot()
    source_roots = _xml_source_roots(root)

    for cls in root.findall(".//class"):
        filename = cls.attrib.get("filename")
        if not filename:
            continue
        norm = _normalize_xml_filename(filename, source_roots=source_roots, base=base, xml_path=path)
        total = 0
        covered = 0
        for line in cls.findall("./lines/line"):
            hits_raw = line.attrib.get("hits", "0")
            try:
                hits = int(float(hits_raw))
            except ValueError:
                hits = 0
            total += 1
            if hits > 0:
                covered += 1
        if total > 0:
            prev = file_stats.get(norm)
            if prev:
                file_stats[norm] = (prev[0] + covered, prev[1] + total)
            else:
                file_stats[norm] = (covered, total)

    covered, total = _sum_file_stats(file_stats)
    if total == 0:
        total = int(float(root.attrib.get("lines-valid", "0") or 0))
        covered = int(float(root.attrib.get("lines-covered", "0") or 0))

    return CoverageStats(name=name, path=str(path), covered=covered, total=total, file_stats=file_stats)


def parse_lcov(name: str, path: Path, *, base: Path | None = None) -> CoverageStats:
    file_stats: dict[str, tuple[int, int]] = {}
    current_file: str | None = None
    record_has_da = False
    record_lf = 0
    record_lh = 0

    if base is None:
        base = Path.cwd()

    def finalize_record() -> None:
        nonlocal current_file, record_has_da, record_lf, record_lh
        if not current_file:
            return
        if not record_has_da and record_lf > 0:
            file_stats[current_file] = (record_lh, record_lf)

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            finalize_record()
            current_file = _normalize_path(line.split(":", 1)[1], base=base, relative_root=path.parent)
            file_stats.setdefault(current_file, (0, 0))
            record_has_da = False
            record_lf = 0
            record_lh = 0
        elif line.startswith("DA:") and current_file:
            record_has_da = True
            try:
                _, rest = line.split(":", 1)
                _, hits_raw = rest.split(",", 1)
                hits = int(float(hits_raw))
            except ValueError:
                continue
            c, t = file_stats[current_file]
            t += 1
            if hits > 0:
                c += 1
            file_stats[current_file] = (c, t)
        elif line.startswith("LF:") and current_file:
            try:
                record_lf = int(float(line.split(":", 1)[1]))
            except ValueError:
                record_lf = 0
        elif line.startswith("LH:") and current_file:
            try:
                record_lh = int(float(line.split(":", 1)[1]))
            except ValueError:
                record_lh = 0
        elif line == "end_of_record":
            finalize_record()
            current_file = None
            record_has_da = False
            record_lf = 0
            record_lh = 0

    finalize_record()
    covered, total = _sum_file_stats(file_stats)
    return CoverageStats(name=name, path=str(path), covered=covered, total=total, file_stats=file_stats)


def _load_git_tracked_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [_normalize_path(line) for line in proc.stdout.splitlines() if line.strip()]


def _is_excluded(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def _has_trackable_lines(root: Path, relative_path: str) -> bool:
    file_path = (root / relative_path).resolve(strict=False)
    if not file_path.is_file():
        return False
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.stat().st_size > 0

    if file_path.suffix.lower() == ".py":
        try:
            module = ast.parse(content)
        except SyntaxError:
            return any(line.strip() for line in content.splitlines())

        body = list(module.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
            if isinstance(body[0].value.value, str):
                body = body[1:]

        for stmt in body:
            if isinstance(stmt, ast.Assign):
                names = [target.id for target in stmt.targets if isinstance(target, ast.Name)]
                if names and all(name.startswith("__") and name.endswith("__") for name in names):
                    continue
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                if name.startswith("__") and name.endswith("__"):
                    continue
            return True
        return False

    return any(line.strip() for line in content.splitlines())


def _collect_expected_inventory(root: Path) -> set[str]:
    tracked = _load_git_tracked_files(root)
    expected: set[str] = set()

    for file_path in tracked:
        p = Path(file_path)
        suffix = p.suffix.lower()
        for rule in TARGET_RULES:
            rule_root = rule["root"]
            if file_path == rule_root or file_path.startswith(f"{rule_root}/"):
                if suffix not in rule["ext"]:
                    continue
                if _is_excluded(file_path, rule["exclude"]):
                    continue
                if not _has_trackable_lines(root, file_path):
                    continue
                expected.add(file_path)
                break

    return expected


def _find_coverage_for_file(path: str, combined_stats: dict[str, tuple[int, int]]) -> tuple[int, int] | None:
    normalized_path = path.replace("\\", "/")
    direct = combined_stats.get(normalized_path)
    if direct:
        return direct

    lower_path = normalized_path.lower()
    suffix = "/" + lower_path
    for key, value in combined_stats.items():
        candidate = key.replace("\\", "/").lower()
        if candidate == lower_path or candidate.endswith(suffix):
            return value
    return None


def evaluate(stats: list[CoverageStats], *, expected_inventory: set[str] | None) -> tuple[str, list[str], dict[str, int]]:
    findings: list[str] = []
    for item in stats:
        if item.percent < 100.0:
            findings.append(f"{item.name} coverage below 100%: {item.percent:.2f}% ({item.covered}/{item.total})")

    combined_total = sum(item.total for item in stats)
    combined_covered = sum(item.covered for item in stats)
    combined = 100.0 if combined_total <= 0 else (combined_covered / combined_total) * 100.0
    if combined < 100.0:
        findings.append(f"combined coverage below 100%: {combined:.2f}% ({combined_covered}/{combined_total})")

    metrics = {
        "expected_files": 0,
        "missing_files": 0,
        "uncovered_files": 0,
    }

    if expected_inventory is not None:
        combined_file_stats: dict[str, tuple[int, int]] = {}
        for item in stats:
            for path, (covered, total) in item.file_stats.items():
                prev = combined_file_stats.get(path)
                if prev:
                    combined_file_stats[path] = (prev[0] + covered, prev[1] + total)
                else:
                    combined_file_stats[path] = (covered, total)

        missing: list[str] = []
        uncovered: list[str] = []
        for path in sorted(expected_inventory):
            cov = _find_coverage_for_file(path, combined_file_stats)
            if cov is None:
                missing.append(path)
                continue
            covered, total = cov
            if total <= 0 or covered < total:
                pct = 100.0 if total <= 0 else (covered / total) * 100.0
                uncovered.append(f"{path} ({covered}/{total}, {pct:.2f}%)")

        metrics["expected_files"] = len(expected_inventory)
        metrics["missing_files"] = len(missing)
        metrics["uncovered_files"] = len(uncovered)

        if missing:
            findings.append(f"coverage inventory missing files: {len(missing)}")
            findings.extend(f"missing: {p}" for p in missing)
        if uncovered:
            findings.append(f"coverage inventory uncovered files: {len(uncovered)}")
            findings.extend(f"uncovered: {p}" for p in uncovered)

    status = "pass" if not findings else "fail"
    return status, findings, metrics


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

    inventory = payload.get("inventory_metrics") or {}
    lines.extend([
        "",
        "## Inventory",
        f"- expected_files: `{inventory.get('expected_files', 0)}`",
        f"- missing_files: `{inventory.get('missing_files', 0)}`",
        f"- uncovered_files: `{inventory.get('uncovered_files', 0)}`",
        "",
        "## Findings",
    ])
    findings = payload.get("findings") or []
    if findings:
        lines.extend(f"- {finding}" for finding in findings)
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
    workspace_root = Path(args.inventory_root).resolve()

    stats: list[CoverageStats] = []
    for item in args.xml:
        name, path = parse_named_path(item)
        stats.append(parse_coverage_xml(name, path, base=workspace_root))
    for item in args.lcov:
        name, path = parse_named_path(item)
        stats.append(parse_lcov(name, path, base=workspace_root))

    if not stats:
        raise SystemExit("No coverage files were provided; pass --xml and/or --lcov inputs.")

    expected_inventory = None
    if not args.no_inventory_check:
        expected_inventory = _collect_expected_inventory(workspace_root)

    status, findings, inventory_metrics = evaluate(stats, expected_inventory=expected_inventory)
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
                "files": len(item.file_stats),
            }
            for item in stats
        ],
        "inventory_metrics": inventory_metrics,
        "findings": findings,
    }

    try:
        out_json = _safe_output_path(args.out_json, "coverage-100/coverage.json", base=workspace_root)
        out_md = _safe_output_path(args.out_md, "coverage-100/coverage.md", base=workspace_root)
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
