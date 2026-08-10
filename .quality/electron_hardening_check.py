"""Electron hardening gate (W66) — the packaging fuses and the renderer sandbox.

PROGRAM.md's Wave-1 line claimed "Electron 39 (EOL) -> 43 + ASAR-integrity fuses +
Electronegativity CI. SHIPPED". Only the version bump had landed: `electron-builder.yml`
declared no `electronFuses` block at all, so the shipped exe kept every Node-injection
surface open and would happily load a tampered `app.asar`.

Two rules, both read from the files that actually decide the outcome:

``e1``  `electron-builder.yml` declares an `electronFuses:` block containing every key
        in ``REQUIRED_FUSES`` with exactly the required value. `runAsNode: true` is in
        that set on purpose — see the comment beside it in the yml: the caption render
        path spawns the Electron exe as plain Node, so the "hardened" value would break
        the product. Pinning it here is what stops a future harden-everything sweep from
        flipping it silently.
``e2``  `app/main/main.ts` declares the BrowserWindow sandbox triple
        (``contextIsolation: true`` / ``nodeIntegration: false`` / ``sandbox: true``),
        and no file under `app/main/` re-opens the renderer with
        ``webSecurity: false`` or ``allowRunningInsecureContent: true``.

e2 exists because of a measured overclaim: while writing the charter note for W66 the
sentence "those checks are already asserted by app/main/security.test.ts" was drafted
and then CHECKED — that suite asserts the CSP header only. The three literals at
main.ts:1080-1085 had NO assertion anywhere. This is that assertion.

DETECTOR NOTE — anchoring, which this exact item has already cost the programme once: a
naive search for ``fuses`` matches the substring in "re​fuses", of which this repo has
many. Every pattern below is anchored to a line START plus the expected indentation, and
``test_electron_hardening_gate`` proves each one finds a KNOWN-PRESENT item before any
zero is trusted.

Also asserted: ``asar: true``. Without it there is no asar to validate and the integrity
fuse is decoration.

FAIL CLOSED (rules/common/ci-hygiene.md §1): a missing file, an absent block, or a
zero-length required set returns non-zero.

Usage:  python .quality/electron_hardening_check.py
Exit 0 when clean, 1 on any violation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / ".git").exists() and (cand / "app/package.json").is_file():
            return cand
    raise SystemExit(f"FAILED:electronhardening cannot locate the repo root from {here}")


ROOT = _find_root()
BUILDER_YML = "electron-builder.yml"
MAIN_TS = "app/main/main.ts"
MAIN_DIR = "app/main"

# fuse name -> required literal, with WHY it is required in that direction.
REQUIRED_FUSES: dict[str, tuple[str, str]] = {
    "runAsNode": (
        "true",
        "the caption render path spawns the Electron exe as plain Node "
        "(ELECTRON_RUN_AS_NODE=1); false breaks every animated caption render",
    ),
    "enableCookieEncryption": ("true", "cookies at rest encrypted with the OS credential store"),
    "enableNodeOptionsEnvironmentVariable": ("false", "closes NODE_OPTIONS code injection into the packaged app"),
    "enableNodeCliInspectArguments": ("false", "closes --inspect on the packaged app"),
    "enableEmbeddedAsarIntegrityValidation": ("true", "W66 headline: refuse a tampered app.asar"),
    "onlyLoadAppFromAsar": ("true", "refuse an unpacked app/ dir beside the asar (integrity bypass)"),
    "loadBrowserProcessSpecificV8Snapshot": ("false", "no custom V8 snapshot is built"),
    "grantFileProtocolExtraPrivileges": ("true", "Electron's default, deliberately NOT hardened — see the yml comment"),
}

# The renderer sandbox triple, as literals in the BrowserWindow webPreferences.
REQUIRED_WEBPREFS: dict[str, str] = {
    "contextIsolation": "true",
    "nodeIntegration": "false",
    "sandbox": "true",
}

# Anchored: line start, exactly two spaces of block indentation, the key, a colon, the
# value, then end-of-line (a trailing comment is allowed). Anchoring on the line start
# is what keeps `refuses` and any prose mention out of the match.
_FUSES_BLOCK_RE = re.compile(r"^electronFuses:[ \t]*$", re.MULTILINE)
_ASAR_TRUE_RE = re.compile(r"^asar:[ \t]+true[ \t]*(?:#.*)?$", re.MULTILINE)
_BANNED_WEBPREFS = (("webSecurity", "false"), ("allowRunningInsecureContent", "true"))


def fuse_line_re(key: str) -> re.Pattern[str]:
    return re.compile(rf"^  {re.escape(key)}:[ \t]+(?P<value>true|false)[ \t]*(?:#.*)?$", re.MULTILINE)


def webpref_line_re(key: str) -> re.Pattern[str]:
    return re.compile(rf"^\s+{re.escape(key)}:[ \t]*(?P<value>true|false),?[ \t]*(?://.*)?$", re.MULTILINE)


def check_fuses(text: str) -> list[str]:
    problems: list[str] = []
    if not _FUSES_BLOCK_RE.search(text):
        problems.append(f"e1 {BUILDER_YML} declares no `electronFuses:` block — the packaged exe is unhardened")
        return problems
    if not _ASAR_TRUE_RE.search(text):
        problems.append(
            f"e1 {BUILDER_YML} does not set `asar: true` — asar-integrity validation has nothing to validate"
        )
    for key, (want, why) in REQUIRED_FUSES.items():
        match = fuse_line_re(key).search(text)
        if match is None:
            problems.append(f"e1 {BUILDER_YML} does not declare fuse `{key}` (required {want}: {why})")
        elif match.group("value") != want:
            problems.append(f"e1 {BUILDER_YML} fuse `{key}` is {match.group('value')}, must be {want} — {why}")
    return problems


def check_webprefs(main_text: str, main_dir_texts: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for key, want in REQUIRED_WEBPREFS.items():
        match = webpref_line_re(key).search(main_text)
        if match is None:
            problems.append(f"e2 {MAIN_TS} no longer declares `{key}: {want}` in the BrowserWindow webPreferences")
        elif match.group("value") != want:
            problems.append(f"e2 {MAIN_TS} declares `{key}: {match.group('value')}`, must be {want}")
    for rel, text in sorted(main_dir_texts.items()):
        for key, banned in _BANNED_WEBPREFS:
            match = webpref_line_re(key).search(text)
            if match is not None and match.group("value") == banned:
                problems.append(f"e2 {rel} sets `{key}: {banned}`, which re-opens the renderer")
    return problems


def main() -> int:
    yml_path = ROOT / BUILDER_YML
    main_path = ROOT / MAIN_TS
    for path in (yml_path, main_path):
        if not path.is_file():
            print(f"FAILED:electronhardening missing {path.relative_to(ROOT).as_posix()}")
            return 1
    if not REQUIRED_FUSES or not REQUIRED_WEBPREFS:
        print("FAILED:electronhardening the required sets are empty — the gate would check nothing")
        return 1

    main_dir_texts = {
        p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8", errors="replace")
        for p in sorted((ROOT / MAIN_DIR).rglob("*.ts"))
        if ".test." not in p.name
    }
    if not main_dir_texts:
        print(f"FAILED:electronhardening zero production modules found under {MAIN_DIR} — the walk is broken")
        return 1

    violations = check_fuses(yml_path.read_text(encoding="utf-8"))
    violations += check_webprefs(main_path.read_text(encoding="utf-8"), main_dir_texts)

    counts = {"e1": 0, "e2": 0}
    for v in violations:
        counts[v.split(" ", 1)[0]] += 1
    for v in violations:
        print(v)
    print(
        f"electronhardening: fuses-required={len(REQUIRED_FUSES)} webprefs-required={len(REQUIRED_WEBPREFS)} "
        f"main-modules-scanned={len(main_dir_texts)} e1={counts['e1']} e2={counts['e2']}"
    )
    if violations:
        print(f"FAILED:electronhardening {len(violations)} violation(s)")
        return 1
    print("SUCCESS:electronhardening")
    return 0


if __name__ == "__main__":
    sys.exit(main())
